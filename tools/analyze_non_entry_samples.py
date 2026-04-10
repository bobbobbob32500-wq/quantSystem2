#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
分析二次启动策略中"未触发盘中买点"的样本。

对每条未触发样本：
1. 从日线库查 T+2 收益（以信号日收盘价为基准）
2. 按盈亏分组
3. 对正收益样本，用分钟数据回放盘中走势特征，找到"为什么没触发"
4. 对比正收益/负收益未触发样本的日线特征差异
"""

from __future__ import annotations

import json
import sqlite3
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.modules.backtest.history_recommendation_db import HistoryRecommendationDB
from src.modules.secondary_launch_intraday import (
    _prepare_minute_frame,
    _build_pullback_signal,
    _build_breakout_signal,
    _resolve_breakout_threshold,
    _resolve_market_gate,
)


def _flush(*args):
    print(*args, flush=True)


def _trade_date(signal_date: str) -> str:
    s = str(signal_date)
    return f"{s[:4]}-{s[4:6]}-{s[6:8]}"


def load_day_minute(db: HistoryRecommendationDB, symbol: str, signal_date: str) -> pd.DataFrame:
    day_str = _trade_date(signal_date)
    start_t = f"{day_str}T09:00:00"
    end_t = f"{day_str}T15:30:00"
    raw = db.get_intraday_data(symbol, start_time=start_t, end_time=end_t)
    return raw


def get_daily_features(conn: sqlite3.Connection, symbol: str, signal_date: str) -> Dict[str, Any]:
    """从日线库取信号日及前后的日线特征。"""
    rows = list(conn.execute(
        """SELECT trade_date, open, close, high, low, vol, amount, pct_chg
           FROM stock_daily
           WHERE ts_code = ? AND trade_date <= ?
           ORDER BY trade_date DESC LIMIT 10""",
        (symbol, signal_date),
    ))
    if not rows:
        return {}

    today = rows[0]
    today_close = float(today["close"]) if today["close"] else None

    future_rows = list(conn.execute(
        """SELECT trade_date, open, close FROM stock_daily
           WHERE ts_code = ? AND trade_date > ?
           ORDER BY trade_date ASC LIMIT 3""",
        (symbol, signal_date),
    ))

    t1_close = float(future_rows[0]["close"]) if len(future_rows) >= 1 and future_rows[0]["close"] else None
    t2_close = float(future_rows[1]["close"]) if len(future_rows) >= 2 and future_rows[1]["close"] else None
    t2_open = float(future_rows[1]["open"]) if len(future_rows) >= 2 and future_rows[1]["open"] else None

    t2_close_ret = (t2_close / today_close - 1.0) if t2_close and today_close else None

    # 信号日涨幅
    pct_chg = float(today["pct_chg"]) if today["pct_chg"] is not None else None

    # 近5日均量
    vols = [float(r["vol"]) for r in rows[:5] if r["vol"] is not None]
    avg_vol_5 = sum(vols) / len(vols) if vols else None

    # 信号日量比
    today_vol = float(today["vol"]) if today["vol"] else None
    vol_ratio_5 = (today_vol / avg_vol_5) if today_vol and avg_vol_5 and avg_vol_5 > 0 else None

    # 信号日振幅
    amplitude = None
    if today["high"] and today["low"] and today["close"]:
        amplitude = (float(today["high"]) - float(today["low"])) / float(today["close"]) * 100

    # 近5日涨跌
    if len(rows) >= 5 and rows[4]["close"]:
        ret_5d = (today_close / float(rows[4]["close"]) - 1.0) * 100 if today_close else None
    else:
        ret_5d = None

    return {
        "signal_date_close": today_close,
        "pct_chg": pct_chg,
        "vol_ratio_5": vol_ratio_5,
        "amplitude": amplitude,
        "ret_5d": ret_5d,
        "T+2_close_ret": t2_close_ret,
        "T+1_close": t1_close,
        "T+2_close": t2_close,
    }


def diagnose_minute_shape(
    raw_frame: pd.DataFrame,
    symbol: str,
    rank: int,
) -> Dict[str, Any]:
    """对一条未触发样本的分钟数据做诊断：为什么没触发。"""
    result = {
        "has_minute_data": not raw_frame.empty,
        "minute_bars": len(raw_frame) if not raw_frame.empty else 0,
        "max_pullback_conf": 0.0,
        "max_breakout_conf": 0.0,
        "pullback_conditions": {},
        "breakout_conditions": {},
        "closest_trigger_time": "",
        "closest_trigger_type": "",
        "diagnosis": "缺少分钟数据",
    }
    if raw_frame.empty:
        return result

    candidate = {
        "symbol": symbol,
        "name": "",
        "score": 80.0 if rank == 1 else 74.0,
        "pool_type": "core" if rank == 1 else "reserve",
        "industry": "",
        "strategy_profile": "secondary_launch",
    }

    prepared = _prepare_minute_frame(raw_frame)
    if prepared.empty:
        return result

    result["minute_bars"] = len(prepared)

    best_pb_conf = 0.0
    best_bo_conf = 0.0
    best_pb_time = ""
    best_bo_time = ""
    pb_condition_fails = Counter()
    bo_condition_fails = Counter()

    for idx in range(len(prepared)):
        frame = prepared.iloc[: idx + 1].copy()
        ts = pd.Timestamp(frame.iloc[-1]["timestamp"])
        if pd.isna(ts):
            continue
        now = ts.to_pydatetime()
        current_price = float(frame.iloc[-1]["close"])
        quote = {"price": current_price}

        pb = _build_pullback_signal(frame, candidate, quote, now)
        if pb.confidence > best_pb_conf:
            best_pb_conf = pb.confidence
            best_pb_time = now.strftime("%H:%M:%S")

        bo = _build_breakout_signal(frame, candidate, quote, now)
        if bo.confidence > best_bo_conf:
            best_bo_conf = bo.confidence
            best_bo_time = now.strftime("%H:%M:%S")

    result["max_pullback_conf"] = round(best_pb_conf, 4)
    result["max_breakout_conf"] = round(best_bo_conf, 4)

    # 在最高置信度时刻做一次详细诊断
    if best_pb_conf > 0 and best_pb_conf >= best_bo_conf:
        result["closest_trigger_type"] = "pullback"
        result["closest_trigger_time"] = best_pb_time
    elif best_bo_conf > 0:
        result["closest_trigger_type"] = "breakout"
        result["closest_trigger_time"] = best_bo_time

    # 判定未触发原因
    if best_pb_conf >= 0.60 or best_bo_conf >= 0.60:
        if best_pb_conf >= 0.60 and best_pb_conf < 1.0:
            result["diagnosis"] = "回踩接近触发但signal=False（部分条件未满足）"
        elif best_bo_conf >= 0.60:
            result["diagnosis"] = "突破接近触发但signal=False（部分条件未满足）"
        else:
            result["diagnosis"] = "置信度接近但未完全满足"
    elif best_pb_conf > 0 or best_bo_conf > 0:
        result["diagnosis"] = "形态有雏形但置信度过低"
    else:
        result["diagnosis"] = "全天无任何形态信号"

    return result


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser(description="分析未触发样本的T+2收益与共性")
    parser.add_argument("--report-json", default="results/secondary_launch_unified_truth_20260402_111448.json")
    parser.add_argument("--tracking-json", default="results/secondary_launch_recent_tracking_20260402_021443.json")
    parser.add_argument("--minute-db", default="data/history_recommendation.db")
    parser.add_argument("--daily-db", default="data/database/quant_system.db")
    args = parser.parse_args()

    daily_conn = sqlite3.connect(str(ROOT / args.daily_db))
    daily_conn.row_factory = sqlite3.Row
    minute_db = HistoryRecommendationDB(str(ROOT / args.minute_db))

    # 加载统一分析报告中的未触发样本
    truth = json.loads((ROOT / args.report_json).read_text(encoding="utf-8"))
    non_entries = truth.get("non_entries", [])
    _flush(f"未触发样本总数: {len(non_entries)}")

    # 加载跟踪报表获取 rank 等详情
    tracking = json.loads((ROOT / args.tracking_json).read_text(encoding="utf-8"))
    detail_map = {}
    for d in tracking.get("details", []):
        key = (str(d.get("ts_code", "")).upper(), str(d.get("signal_date", "")))
        detail_map[key] = d

    records: List[Dict[str, Any]] = []
    _flush("分析每条未触发样本...")

    for i, ne in enumerate(non_entries):
        symbol = str(ne.get("symbol", "")).upper()
        signal_date = str(ne.get("signal_date", ""))
        rank = int(ne.get("rank", 0))

        daily_feat = get_daily_features(daily_conn, symbol, signal_date)

        # 分钟数据诊断
        raw_frame = load_day_minute(minute_db, symbol, signal_date)
        minute_diag = diagnose_minute_shape(raw_frame, symbol, rank)

        detail = detail_map.get((symbol, signal_date), {})

        record = {
            "symbol": symbol,
            "signal_date": signal_date,
            "name": detail.get("name", ""),
            "rank": rank,
            "signal_score": detail.get("signal_score"),
            "no_entry_reason": ne.get("no_entry_reason", ""),
            **daily_feat,
            **minute_diag,
        }
        records.append(record)

        if (i + 1) % 20 == 0:
            _flush(f"  已分析 {i+1}/{len(non_entries)}...")

    daily_conn.close()

    # ---- 分析 ----
    has_t2 = [r for r in records if r.get("T+2_close_ret") is not None]
    positive = [r for r in has_t2 if r["T+2_close_ret"] > 0]
    negative = [r for r in has_t2 if r["T+2_close_ret"] <= 0]

    _flush(f"\n{'='*60}")
    _flush(f"未触发样本T+2收益分布")
    _flush(f"{'='*60}")
    _flush(f"  有T+2数据: {len(has_t2)}")
    _flush(f"  T+2正收益: {len(positive)} ({len(positive)/len(has_t2)*100:.1f}%)" if has_t2 else "")
    _flush(f"  T+2负收益: {len(negative)} ({len(negative)/len(has_t2)*100:.1f}%)" if has_t2 else "")

    if positive:
        rets = [r["T+2_close_ret"] for r in positive]
        _flush(f"  正收益均值: {sum(rets)/len(rets)*100:.2f}%")
        _flush(f"  正收益最大: {max(rets)*100:.2f}%")

    if negative:
        rets = [r["T+2_close_ret"] for r in negative]
        _flush(f"  负收益均值: {sum(rets)/len(rets)*100:.2f}%")
        _flush(f"  负收益最大: {min(rets)*100:.2f}%")

    # ---- 正收益未触发的详细分析 ----
    _flush(f"\n{'='*60}")
    _flush(f"正收益未触发样本详情 ({len(positive)}条)")
    _flush(f"{'='*60}")

    # 按T+2收益排序
    positive.sort(key=lambda x: x["T+2_close_ret"], reverse=True)

    for r in positive:
        _flush(
            f"\n  {r['signal_date']} {r['symbol']} {r.get('name','')} "
            f"rank={r['rank']} score={r.get('signal_score','?')}"
        )
        _flush(f"    T+2收益: {r['T+2_close_ret']*100:.2f}%")
        _flush(f"    信号日涨跌: {r.get('pct_chg','?')}%  振幅: {r.get('amplitude','?')}")
        _flush(f"    量比(5日): {r.get('vol_ratio_5','?')}  近5日涨跌: {r.get('ret_5d','?')}%")
        _flush(f"    分钟数据: {'有' if r['has_minute_data'] else '无'} ({r['minute_bars']}根)")
        _flush(f"    最高回踩置信: {r['max_pullback_conf']}  最高突破置信: {r['max_breakout_conf']}")
        _flush(f"    最接近触发: {r['closest_trigger_type']} @ {r['closest_trigger_time']}")
        _flush(f"    诊断: {r['diagnosis']}")

    # ---- 统计共性 ----
    _flush(f"\n{'='*60}")
    _flush(f"共性分析")
    _flush(f"{'='*60}")

    # 1. rank 分布
    _flush("\n  正收益未触发 rank 分布:")
    rank_counter = Counter(r["rank"] for r in positive)
    for rk in sorted(rank_counter):
        _flush(f"    rank {rk}: {rank_counter[rk]}条")

    neg_rank_counter = Counter(r["rank"] for r in negative)
    _flush("  负收益未触发 rank 分布:")
    for rk in sorted(neg_rank_counter):
        _flush(f"    rank {rk}: {neg_rank_counter[rk]}条")

    # 2. 盘中诊断分布
    _flush("\n  正收益未触发 诊断分布:")
    diag_counter = Counter(r["diagnosis"] for r in positive)
    for d, cnt in diag_counter.most_common():
        _flush(f"    {d}: {cnt}条")

    # 3. 有无分钟数据
    has_minute_pos = sum(1 for r in positive if r["has_minute_data"])
    _flush(f"\n  正收益中有分钟数据: {has_minute_pos}/{len(positive)}")

    # 4. 最高置信度分布
    if positive:
        pb_confs = [r["max_pullback_conf"] for r in positive if r["max_pullback_conf"] > 0]
        bo_confs = [r["max_breakout_conf"] for r in positive if r["max_breakout_conf"] > 0]
        if pb_confs:
            _flush(f"  正收益最高回踩置信度: min={min(pb_confs):.2f} max={max(pb_confs):.2f} avg={sum(pb_confs)/len(pb_confs):.2f}")
        if bo_confs:
            _flush(f"  正收益最高突破置信度: min={min(bo_confs):.2f} max={max(bo_confs):.2f} avg={sum(bo_confs)/len(bo_confs):.2f}")

    # 5. 信号日日线特征对比
    _flush("\n  正收益 vs 负收益 日线特征对比:")

    def avg_feat(group, key):
        vals = [r[key] for r in group if r.get(key) is not None]
        return sum(vals) / len(vals) if vals else None

    for feat in ["pct_chg", "vol_ratio_5", "amplitude", "ret_5d"]:
        p_avg = avg_feat(positive, feat)
        n_avg = avg_feat(negative, feat)
        p_str = f"{p_avg:.2f}" if p_avg is not None else "-"
        n_str = f"{n_avg:.2f}" if n_avg is not None else "-"
        _flush(f"    {feat:>15}: 正收益={p_str}  负收益={n_str}")

    # ---- 保存 ----
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = ROOT / "results" / f"non_entry_analysis_{ts}.json"
    out_path.write_text(json.dumps(records, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    _flush(f"\n详细数据已保存: {out_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
