# -*- coding: utf-8 -*-
"""
二次启动：半年口径「选股 → 分钟买点触发 → 持仓收益」回测扩展

口径对齐实盘监控：
- 选股：MainboardSecondaryLaunchStrategy.generate_signals（当前配置含震荡限流、分层阈值等）
- 买点：secondary_launch_intraday.detect_secondary_launch_signal（分层 + 双通道 + 日线闸门）
- 成交价：首次触发时该根分钟 K 线收盘价
- 收益：相对成交价，统计「信号日收盘（买入当日）」、T+1/T+2/T+3 交易日「收盘」涨跌幅

输出：data/reports/secondary_launch_halfyear_selection_entry_*.md / .json
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import statistics
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.core.config import ConfigManager
from src.core.database import DatabaseManager
from src.modules.mainboard_secondary_launch_backtester import MainboardSecondaryLaunchBacktester
from src.modules.mainboard_secondary_launch_strategy import MainboardSecondaryLaunchStrategy
from src.modules.secondary_launch_intraday import detect_secondary_launch_signal
from src.modules.backtest.history_recommendation_db import HistoryRecommendationDB

from scripts.analyze_secondary_launch_intraday import _load_session
from tools.analyze_secondary_launch_unified_truth import (
    _fetch_daily_features,
    build_metric,
    infer_time_bucket,
    summarize_group,
)
from tools.eval_secondary_launch_oos_round2 import _build_cost, _load_params_from_config


def _query_max_trade_date(db_path: Path) -> str:
    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()
    cur.execute("SELECT MAX(trade_date) FROM stock_daily")
    row = cur.fetchone()
    conn.close()
    if not row or row[0] is None:
        return datetime.now().strftime("%Y%m%d")
    s = str(row[0]).replace("-", "")[:8]
    return s


def _shift_calendar(yyyymmdd: str, days: int) -> str:
    base = datetime.strptime(str(yyyymmdd)[:8], "%Y%m%d")
    return (base + timedelta(days=days)).strftime("%Y%m%d")


def _tier_overrides(cfg: ConfigManager) -> dict[str, float]:
    return {
        "direct_score_min": float(cfg.get("stock_selection.secondary_launch.direct_score_min", 76.0) or 76.0),
        "direct_lgb_min": float(cfg.get("stock_selection.secondary_launch.direct_lgb_min", 0.58) or 0.58),
        "semi_score_min": float(cfg.get("stock_selection.secondary_launch.semi_score_min", 70.0) or 70.0),
        "semi_lgb_min": float(cfg.get("stock_selection.secondary_launch.semi_lgb_min", 0.55) or 0.55),
        "direct_conf_min": float(cfg.get("stock_selection.secondary_launch.direct_conf_min", 0.45) or 0.45),
        "semi_conf_min": float(cfg.get("stock_selection.secondary_launch.semi_conf_min", 0.58) or 0.58),
    }


def _resolve_entry_production(
    row: pd.Series,
    frame: pd.DataFrame,
    daily_features: dict[str, Any],
    tier_overrides: dict[str, float],
) -> dict[str, Any] | None:
    """分钟递增回放，首次触发分层买点即成交。"""
    if frame.empty:
        return None
    ts_code = str(row.get("ts_code", "") or "").strip().upper()
    if not ts_code:
        return None
    rank = int(row.get("rank") or 99)
    signal_score = float(row.get("signal_score") or 0.0)
    lgb_raw = row.get("lgb_prob")
    lgb_prob = None
    if lgb_raw is not None and pd.notna(lgb_raw):
        try:
            lgb_prob = float(lgb_raw)
        except (TypeError, ValueError):
            pass
    candidate: dict[str, Any] = {
        "symbol": ts_code.split(".")[0],
        "name": str(row.get("name", "") or ""),
        "score": signal_score,
        "signal_score": signal_score,
        "rank": rank,
        "pool_type": "core" if rank == 1 else "reserve",
        "industry": "",
        "strategy_profile": "secondary_launch",
    }
    if lgb_prob is not None:
        candidate["lgb_prob"] = lgb_prob
    if daily_features:
        candidate.update(daily_features)
    candidate.update(tier_overrides)

    industry_confirm = {"score": 50.0, "level": "neutral", "industry": str(row.get("name", "") or "未知")[:30]}
    market_confirm = {"market_score": 50.0, "trend": "neutral", "index_below_vwap": False}

    for idx in range(len(frame)):
        now = pd.Timestamp(frame.iloc[idx]["trade_time"]).to_pydatetime()
        window = frame.iloc[: idx + 1].copy()
        current_price = float(window.iloc[-1]["close"])
        sig = detect_secondary_launch_signal(
            candidate=candidate,
            quote={"price": current_price},
            now=now,
            minute_df=window,
            industry_confirm=industry_confirm,
            market_confirm=market_confirm,
        )
        if sig.signal:
            return {
                "entry_time": now,
                "entry_price": current_price,
                "signal_type": str(sig.signal_type or ""),
                "confidence": float(sig.confidence or 0.0),
                "details": dict(sig.details or {}),
            }
    return None


def _profit_factor(values: list[float | None]) -> float | None:
    clean = [float(v) for v in values if v is not None]
    if not clean:
        return None
    pos = sum(v for v in clean if v > 0)
    neg = -sum(v for v in clean if v < 0)
    if neg < 1e-12:
        return None
    return round(pos / neg, 3)


def main() -> int:
    ap = argparse.ArgumentParser(description="二次启动：选股→买点→T+N 收盘收益（半年扩展）")
    ap.add_argument("--start", default="", help="分析区间起点 YYYYMMDD，留空则按 end 往前推约半年")
    ap.add_argument("--end", default="", help="分析区间终点 YYYYMMDD，留空则取日线库最新交易日")
    ap.add_argument("--calendar-days", type=int, default=185, help="start 为空时，相对 end 往前推的自然日数（约半年）")
    ap.add_argument("--minute-db", default="data/history_recommendation.db")
    ap.add_argument("--daily-db", default="data/database/quant_system.db")
    ap.add_argument("--progress-every", type=int, default=30)
    args = ap.parse_args()

    daily_db = ROOT / args.daily_db
    end = args.end.strip() or _query_max_trade_date(daily_db)
    start = args.start.strip() or _shift_calendar(end, -int(args.calendar_days))

    cfg = ConfigManager()
    db = DatabaseManager(cfg)
    params = _load_params_from_config(cfg)
    strategy = MainboardSecondaryLaunchStrategy(params)
    cost = _build_cost(cfg)
    backtester = MainboardSecondaryLaunchBacktester(db, strategy, cost)

    # 特征需要 warmup，向前多取一段自然日
    load_lo = _shift_calendar(start, -120)
    load_hi = _shift_calendar(end, 25)
    data = backtester.load_data(
        load_lo,
        load_hi,
        warmup_days=max(60, int(cfg.get("stock_selection.secondary_launch.hold_days", 2)) * 3),
        forward_days=max(15, int(cfg.get("stock_selection.secondary_launch.hold_days", 2)) * 3),
    )
    if data["daily"].empty:
        print("日线数据不足")
        return 1
    features = strategy.prepare_features(data["daily"], data["basic"])
    signals = strategy.generate_signals(features)
    if signals.empty:
        print("选股信号为空")
        return 1

    signals = signals.copy()
    signals["sd"] = pd.to_datetime(signals["signal_date"]).dt.strftime("%Y%m%d")
    sig_win = signals[(signals["sd"] >= start) & (signals["sd"] <= end)].copy()
    total_signals = int(len(sig_win))

    minute_db = HistoryRecommendationDB(str(ROOT / args.minute_db))
    conn = sqlite3.connect(str(daily_db))
    conn.row_factory = sqlite3.Row
    tier_ov = _tier_overrides(cfg)

    entries: list[dict[str, Any]] = []
    non_entries: list[dict[str, Any]] = []

    for i, (_, row) in enumerate(sig_win.iterrows()):
        if args.progress_every > 0 and i > 0 and i % int(args.progress_every) == 0:
            print(f"进度 {i}/{total_signals} …", flush=True)

        ts_code = str(row.get("ts_code", "") or "").strip().upper()
        signal_date = str(row["sd"])
        if not ts_code:
            continue

        frame = _load_session(minute_db, ts_code, signal_date)
        if frame.empty:
            non_entries.append(
                {"signal_date": signal_date, "ts_code": ts_code, "rank": int(row.get("rank") or 0), "reason": "缺少当日分钟数据"}
            )
            continue

        daily_feat = _fetch_daily_features(conn, ts_code, signal_date)
        entry = _resolve_entry_production(row, frame, daily_feat, tier_ov)
        if entry is None:
            non_entries.append(
                {"signal_date": signal_date, "ts_code": ts_code, "rank": int(row.get("rank") or 0), "reason": "未触发盘中买点"}
            )
            continue

        entry_price = float(entry["entry_price"])
        same_day_close = float(frame.iloc[-1]["close"])
        daily_rows = list(
            conn.execute(
                """
                SELECT trade_date, open, close
                FROM stock_daily
                WHERE ts_code = ? AND trade_date >= ?
                ORDER BY trade_date ASC
                """,
                (ts_code, signal_date),
            )
        )
        future_rows = [r for r in daily_rows if str(r["trade_date"]) > signal_date]

        et = entry["entry_time"]
        entry_time_str = et.strftime("%H:%M:%S") if hasattr(et, "strftime") else str(et)
        rec: dict[str, Any] = {
            "signal_date": signal_date,
            "ts_code": ts_code,
            "name": str(row.get("name", "") or ""),
            "rank": int(row.get("rank") or 0),
            "execution_tier_hint": str(row.get("execution_tier_hint", "") or ""),
            "signal_score": float(row.get("signal_score") or 0.0),
            "signal_type": str(entry.get("signal_type", "") or ""),
            "entry_time": entry_time_str,
            "time_bucket": infer_time_bucket(entry_time_str),
            "entry_price": entry_price,
            "same_day_close_ret": same_day_close / entry_price - 1.0,
            "confidence": float(entry.get("confidence") or 0.0),
        }
        for idx, label in enumerate(["T+1", "T+2", "T+3"], start=1):
            if len(future_rows) >= idx:
                bar = future_rows[idx - 1]
                rec[f"{label}_date"] = str(bar["trade_date"])
                rec[f"{label}_open_ret"] = float(bar["open"]) / entry_price - 1.0 if bar["open"] is not None else None
                rec[f"{label}_close_ret"] = float(bar["close"]) / entry_price - 1.0 if bar["close"] is not None else None
            else:
                rec[f"{label}_date"] = None
                rec[f"{label}_open_ret"] = None
                rec[f"{label}_close_ret"] = None
        entries.append(rec)

    conn.close()

    unique_signal_days = int(sig_win["sd"].nunique()) if total_signals else 0
    span_days = max(
        1,
        (datetime.strptime(end, "%Y%m%d") - datetime.strptime(start, "%Y%m%d")).days,
    )
    months_equiv = span_days / 30.44

    def _freq(n: int) -> dict[str, float]:
        return {
            "per_month_approx": round(n / months_equiv, 3) if months_equiv > 0 else 0.0,
            "per_signal_day_approx": round(total_signals / unique_signal_days, 3) if unique_signal_days else 0.0,
        }

    payload: dict[str, Any] = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "analysis_range": [start, end],
        "load_range": [load_lo, load_hi],
        "selection_signal_rows": total_signals,
        "unique_signal_days": unique_signal_days,
        "entry_count": len(entries),
        "no_entry_count": len(non_entries),
        "entry_rate_pct": round(len(entries) / total_signals * 100, 2) if total_signals else 0.0,
        "frequency": {
            "selection_signals_per_month_approx": _freq(total_signals)["per_month_approx"],
            "completed_trades_per_month_approx": _freq(len(entries))["per_month_approx"],
            "avg_selections_per_calendar_day": round(total_signals / span_days, 4),
        },
        "metrics": {
            "买入当日收盘": build_metric([r.get("same_day_close_ret") for r in entries]),
            "T+1收盘": build_metric([r.get("T+1_close_ret") for r in entries]),
            "T+2收盘": build_metric([r.get("T+2_close_ret") for r in entries]),
            "T+3收盘": build_metric([r.get("T+3_close_ret") for r in entries]),
            "T+1开盘": build_metric([r.get("T+1_open_ret") for r in entries]),
        },
        "profit_factor": {
            "买入当日收盘": _profit_factor([r.get("same_day_close_ret") for r in entries]),
            "T+1收盘": _profit_factor([r.get("T+1_close_ret") for r in entries]),
            "T+2收盘": _profit_factor([r.get("T+2_close_ret") for r in entries]),
            "T+3收盘": _profit_factor([r.get("T+3_close_ret") for r in entries]),
        },
        "by_rank": summarize_group(entries, "rank"),
        "by_time_bucket": summarize_group(entries, "time_bucket"),
        "by_tier_hint": summarize_group(entries, "execution_tier_hint"),
        "entries": entries,
        "non_entries_sample": non_entries[:200],
        "non_entries_total": len(non_entries),
    }

    out_dir = ROOT / "data" / "reports"
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_json = out_dir / f"secondary_launch_halfyear_selection_entry_{ts}.json"
    out_md = out_dir / f"secondary_launch_halfyear_selection_entry_{ts}.md"
    out_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    m0 = payload["metrics"]["买入当日收盘"]
    m1 = payload["metrics"]["T+1收盘"]
    m2 = payload["metrics"]["T+2收盘"]
    m3 = payload["metrics"]["T+3收盘"]
    pf = payload["profit_factor"]
    lines = [
        "# 二次启动：选股 → 买点 → 持仓收益（扩展回测）",
        "",
        f"- 生成时间：{payload['generated_at']}",
        f"- 分析区间：{start} ~ {end}",
        f"- 特征加载区间（含预热）：{load_lo} ~ {load_hi}",
        "",
        "## 交易频率",
        "",
        f"- 选股信号条数（区间内）：**{total_signals}**",
        f"- 有信号交易日数：**{unique_signal_days}**",
        f"- 分钟买点触发并视为成交：**{len(entries)}**",
        f"- 买点触发率：**{payload['entry_rate_pct']}%**",
        f"- 选股信号约 **{payload['frequency']['selection_signals_per_month_approx']}** 条/月（按自然日跨度折算）",
        f"- 成交样本约 **{payload['frequency']['completed_trades_per_month_approx']}** 笔/月",
        "",
        "## 收益口径（相对触发分钟收盘价）",
        "",
        "| 维度 | 样本数 | 胜率 | 平均收益 | 中位收益 | 盈亏比 |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
        f"| 买入当日收盘 | {m0['count']} | {m0['win_rate']}% | {m0['avg_return_pct']}% | {m0['median_return_pct']}% | {pf.get('买入当日收盘') or '-'} |",
        f"| T+1 收盘 | {m1['count']} | {m1['win_rate']}% | {m1['avg_return_pct']}% | {m1['median_return_pct']}% | {pf.get('T+1收盘') or '-'} |",
        f"| T+2 收盘 | {m2['count']} | {m2['win_rate']}% | {m2['avg_return_pct']}% | {m2['median_return_pct']}% | {pf.get('T+2收盘') or '-'} |",
        f"| T+3 收盘 | {m3['count']} | {m3['win_rate']}% | {m3['avg_return_pct']}% | {m3['median_return_pct']}% | {pf.get('T+3收盘') or '-'} |",
        "",
        "## 未成交原因（条数）",
        "",
    ]
    from collections import Counter

    c = Counter(str(x.get("reason", "")) for x in non_entries)
    for k, v in c.most_common(12):
        lines.append(f"- {k}: **{v}**")
    lines.extend(["", "## 输出文件", f"- `{out_json.as_posix()}`", f"- `{out_md.as_posix()}`", ""])
    out_md.write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
