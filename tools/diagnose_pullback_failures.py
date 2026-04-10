#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
精确诊断"回踩接近触发但signal=False"的正收益样本，
逐根分钟回放找到最高置信度时刻，拆解4个子条件的具体值。
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
from src.modules.secondary_launch_intraday import _prepare_minute_frame


def _flush(*args):
    print(*args, flush=True)


def _trade_date(signal_date: str) -> str:
    s = str(signal_date)
    return f"{s[:4]}-{s[4:6]}-{s[6:8]}"


def diagnose_pullback_at_bar(prepared: pd.DataFrame, n: int) -> Dict[str, Any]:
    """在第 n 根 bar 处，返回回踩4个子条件的详细值。"""
    if n + 1 < 8:
        return {"enough_bars": False}

    recent = prepared.iloc[max(0, n + 1 - 6): n + 1].reset_index(drop=True)
    current_price = float(recent.iloc[-1]["close"])
    current_vwap = float(recent.iloc[-1]["vwap"])
    session_open = float(prepared.iloc[0]["open"])
    recent_low_val = float(recent["low"].min())

    if n > 0:
        prior_high = float(prepared.iloc[:n]["high"].tail(20).max())
    else:
        prior_high = current_price

    recent_avg_vol = float(recent["volume"].tail(3).mean())
    if n + 1 >= 12:
        prev_avg_vol = float(prepared["volume"].iloc[n + 1 - 12: n + 1 - 12 + 9].mean())
    else:
        prev_avg_vol = recent_avg_vol
    volume_ratio = recent_avg_vol / prev_avg_vol if prev_avg_vol > 0 else 1.0

    support_price = max(current_vwap, session_open)

    # 当前参数 (已优化)
    support_hold = current_price >= support_price * 0.999 and recent_low_val >= support_price * 0.996
    prev_close = float(recent.iloc[-2]["close"]) if len(recent) >= 2 else current_price
    recent_close_min = float(recent["close"].min())
    rebound = current_price >= prev_close and current_price >= recent_close_min * 1.005
    not_far = prior_high <= 0 or current_price >= prior_high * 0.980
    vol_ok = 0.6 <= volume_ratio <= 1.35

    signal = support_hold and rebound and not_far and vol_ok
    conf = 0.0
    if support_hold: conf += 0.35
    if rebound: conf += 0.25
    if not_far: conf += 0.20
    if vol_ok: conf += 0.20

    failed_conditions = []
    if not support_hold:
        failed_conditions.append("support_hold")
    if not rebound:
        failed_conditions.append("rebound")
    if not not_far:
        failed_conditions.append("not_far")
    if not vol_ok:
        failed_conditions.append("volume_ok")

    return {
        "enough_bars": True,
        "signal": signal,
        "confidence": conf,
        "support_hold": support_hold,
        "rebound": rebound,
        "not_far": not_far,
        "volume_ok": vol_ok,
        "failed_conditions": failed_conditions,
        "current_price": round(current_price, 3),
        "support_price": round(support_price, 3),
        "support_ratio": round(current_price / support_price, 5) if support_price > 0 else None,
        "low_vs_support": round(recent_low_val / support_price, 5) if support_price > 0 else None,
        "prior_high": round(prior_high, 3),
        "price_vs_prior_high": round(current_price / prior_high, 5) if prior_high > 0 else None,
        "volume_ratio": round(volume_ratio, 3),
        "prev_close": round(prev_close, 3),
        "recent_close_min": round(recent_close_min, 3),
        "rebound_ratio": round(current_price / recent_close_min, 5) if recent_close_min > 0 else None,
    }


def main() -> int:
    minute_db = HistoryRecommendationDB(str(ROOT / "data/history_recommendation.db"))
    daily_conn = sqlite3.connect(str(ROOT / "data/database/quant_system.db"))
    daily_conn.row_factory = sqlite3.Row

    analysis = json.loads(
        (ROOT / "results" / "non_entry_analysis_20260402_113603.json").read_text(encoding="utf-8")
    )

    # 筛选：正收益 + 回踩接近触发
    targets = [
        r for r in analysis
        if r.get("T+2_close_ret") is not None
        and r["T+2_close_ret"] > 0
        and "回踩接近" in str(r.get("diagnosis", ""))
    ]
    _flush(f"正收益+回踩接近触发样本: {len(targets)}条")

    condition_fail_counter = Counter()
    condition_pair_counter = Counter()
    detailed_records = []

    for item in targets:
        symbol = item["symbol"]
        signal_date = item["signal_date"]

        day_str = _trade_date(signal_date)
        raw = minute_db.get_intraday_data(symbol, f"{day_str}T09:00:00", f"{day_str}T15:30:00")
        if raw.empty:
            continue

        prepared = _prepare_minute_frame(raw)
        if prepared.empty:
            continue

        # 找最高置信度时刻
        best_diag = None
        best_conf = -1
        best_time = ""

        for n in range(len(prepared)):
            diag = diagnose_pullback_at_bar(prepared, n)
            if not diag.get("enough_bars"):
                continue
            if diag["confidence"] > best_conf:
                best_conf = diag["confidence"]
                best_diag = diag
                ts = pd.Timestamp(prepared.iloc[n]["timestamp"])
                best_time = ts.strftime("%H:%M:%S") if not pd.isna(ts) else ""

        if best_diag is None:
            continue

        for fc in best_diag["failed_conditions"]:
            condition_fail_counter[fc] += 1
        if best_diag["failed_conditions"]:
            key = tuple(sorted(best_diag["failed_conditions"]))
            condition_pair_counter[key] += 1

        detailed_records.append({
            "symbol": symbol,
            "signal_date": signal_date,
            "name": item.get("name", ""),
            "rank": item.get("rank"),
            "T+2_ret": round(item["T+2_close_ret"] * 100, 2),
            "best_time": best_time,
            "best_conf": round(best_conf, 2),
            "failed": best_diag["failed_conditions"],
            "support_ratio": best_diag.get("support_ratio"),
            "low_vs_support": best_diag.get("low_vs_support"),
            "price_vs_prior_high": best_diag.get("price_vs_prior_high"),
            "volume_ratio": best_diag.get("volume_ratio"),
            "rebound_ratio": best_diag.get("rebound_ratio"),
        })

    _flush(f"\n{'='*60}")
    _flush(f"回踩子条件失败统计 (正收益未触发, {len(detailed_records)}条)")
    _flush(f"{'='*60}")
    _flush(f"\n单条件失败次数:")
    for cond, cnt in condition_fail_counter.most_common():
        _flush(f"  {cond}: {cnt}次 ({cnt/len(detailed_records)*100:.1f}%)")

    _flush(f"\n条件组合失败模式:")
    for combo, cnt in condition_pair_counter.most_common(10):
        _flush(f"  {'+'.join(combo)}: {cnt}次 ({cnt/len(detailed_records)*100:.1f}%)")

    # 按失败条件分组查看数值分布
    _flush(f"\n{'='*60}")
    _flush(f"各失败条件的数值分布")
    _flush(f"{'='*60}")

    support_fail = [r for r in detailed_records if "support_hold" in r["failed"]]
    if support_fail:
        ratios = [r["support_ratio"] for r in support_fail if r["support_ratio"]]
        low_ratios = [r["low_vs_support"] for r in support_fail if r["low_vs_support"]]
        _flush(f"\n  support_hold 失败 ({len(support_fail)}条):")
        _flush(f"    价格/支撑比: min={min(ratios):.5f} max={max(ratios):.5f} avg={sum(ratios)/len(ratios):.5f}")
        _flush(f"    当前门槛: >= 0.999")
        if low_ratios:
            _flush(f"    低点/支撑比: min={min(low_ratios):.5f} max={max(low_ratios):.5f} avg={sum(low_ratios)/len(low_ratios):.5f}")
            _flush(f"    当前门槛: >= 0.996")

    rebound_fail = [r for r in detailed_records if "rebound" in r["failed"]]
    if rebound_fail:
        ratios = [r["rebound_ratio"] for r in rebound_fail if r["rebound_ratio"]]
        _flush(f"\n  rebound 失败 ({len(rebound_fail)}条):")
        _flush(f"    现价/近期最低比: min={min(ratios):.5f} max={max(ratios):.5f} avg={sum(ratios)/len(ratios):.5f}")
        _flush(f"    当前门槛: >= 1.005")

    not_far_fail = [r for r in detailed_records if "not_far" in r["failed"]]
    if not_far_fail:
        ratios = [r["price_vs_prior_high"] for r in not_far_fail if r["price_vs_prior_high"]]
        _flush(f"\n  not_far 失败 ({len(not_far_fail)}条):")
        _flush(f"    现价/前高比: min={min(ratios):.5f} max={max(ratios):.5f} avg={sum(ratios)/len(ratios):.5f}")
        _flush(f"    当前门槛: >= 0.980")

    vol_fail = [r for r in detailed_records if "volume_ok" in r["failed"]]
    if vol_fail:
        ratios = [r["volume_ratio"] for r in vol_fail if r["volume_ratio"]]
        _flush(f"\n  volume_ok 失败 ({len(vol_fail)}条):")
        _flush(f"    量比: min={min(ratios):.3f} max={max(ratios):.3f} avg={sum(ratios)/len(ratios):.3f}")
        _flush(f"    当前区间: [0.6, 1.35]")
        below = [r for r in ratios if r < 0.6]
        above = [r for r in ratios if r > 1.35]
        _flush(f"    低于0.6: {len(below)}条  高于1.35: {len(above)}条")

    # 具体看高 T+2 收益的失败样本
    _flush(f"\n{'='*60}")
    _flush(f"T+2 > 10% 的高收益样本失败详情")
    _flush(f"{'='*60}")
    high_ret = sorted([r for r in detailed_records if r["T+2_ret"] > 10], key=lambda x: -x["T+2_ret"])
    for r in high_ret:
        _flush(f"\n  {r['signal_date']} {r['symbol']} {r['name']} rank={r['rank']} T+2={r['T+2_ret']:.2f}%")
        _flush(f"    最高置信时: {r['best_time']} conf={r['best_conf']}")
        _flush(f"    失败条件: {r['failed']}")
        _flush(f"    支撑比={r['support_ratio']} 低点/支撑={r['low_vs_support']} "
               f"前高比={r['price_vs_prior_high']} 量比={r['volume_ratio']} 回弹比={r['rebound_ratio']}")

    # 保存
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = ROOT / "results" / f"pullback_failure_diagnosis_{ts}.json"
    out.write_text(json.dumps(detailed_records, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    _flush(f"\n详细数据已保存: {out}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
