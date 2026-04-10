# -*- coding: utf-8 -*-
"""Replay legacy strategy signals from historical recommendations and intraday bars."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.core.config import ConfigManager
from src.core.database import DatabaseManager
from src.core.logger import get_logger
from src.modules.backtest.history_recommendation_db import HistoryRecommendationDB
from src.modules.enhanced_hybrid_system import EnhancedHybridSystem
from src.modules.virtual_trade_tracker import VirtualTradeTracker

logger = get_logger("legacy_signal_replay_backtest")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="原策略事件驱动回放：历史推荐 -> 盘中买点 -> 卖点退出"
    )
    parser.add_argument("--start-date", default="2026-02-05")
    parser.add_argument("--end-date", default="2026-03-25")
    parser.add_argument(
        "--top-k",
        type=int,
        default=0,
        help="每个推荐日仅保留前K只；0表示保留历史库全部推荐名单",
    )
    parser.add_argument(
        "--strategy-profile",
        default="legacy",
        choices=["legacy", "legacy_opt"],
        help="回放时绑定的策略档位，默认原策略 legacy",
    )
    parser.add_argument(
        "--enforce-t1",
        action="store_true",
        default=True,
        help="A股T+1限制：买入当日不允许卖出",
    )
    parser.add_argument(
        "--disable-t1",
        action="store_true",
        help="关闭A股T+1限制（仅用于研究）",
    )
    return parser.parse_args()


def _normalize_date_text(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if len(text) == 8 and text.isdigit():
        return f"{text[:4]}-{text[4:6]}-{text[6:]}"
    return text


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return float(default)


def _make_history_tracker(config: ConfigManager) -> VirtualTradeTracker:
    partial_take_profit_pct = config.get("monitor.virtual_partial_take_profit_pct", None)
    if str(partial_take_profit_pct).strip().lower() in {"", "none", "null"}:
        partial_take_profit_pct = None
    elif partial_take_profit_pct is not None:
        partial_take_profit_pct = float(partial_take_profit_pct)

    max_hold_hours = config.get("monitor.virtual_max_hold_hours", None)
    if str(max_hold_hours).strip().lower() in {"", "none", "null"}:
        max_hold_hours = None
    elif max_hold_hours is not None:
        max_hold_hours = float(max_hold_hours)

    fallback_max_hold_hours = config.get("monitor.virtual_fallback_max_hold_hours", 96)
    if str(fallback_max_hold_hours).strip().lower() in {"", "none", "null"}:
        fallback_max_hold_hours = None
    elif fallback_max_hold_hours is not None:
        fallback_max_hold_hours = float(fallback_max_hold_hours)

    return VirtualTradeTracker(
        stop_loss_pct=float(config.get("monitor.virtual_stop_loss_pct", -0.05)),
        take_profit_pct=float(config.get("monitor.virtual_take_profit_pct", 0.10)),
        max_hold_hours=max_hold_hours,
        enable_auto_feedback=False,
        enable_dynamic_exit=bool(config.get("monitor.virtual_dynamic_exit_enabled", True)),
        fallback_max_hold_hours=fallback_max_hold_hours,
        partial_take_ratio=float(config.get("monitor.virtual_partial_take_ratio", 0.5)),
        partial_take_profit_pct=partial_take_profit_pct,
        trailing_stop_pct=float(config.get("monitor.virtual_trailing_stop_pct", 0.035)),
    )


def _build_system(strategy_profile: str) -> EnhancedHybridSystem:
    system = EnhancedHybridSystem(enable_auto_optimization=False, enable_virtual_trade=False)
    system.push_enabled = False
    if hasattr(system, "message_pusher"):
        system.message_pusher.enabled = False
    system.enable_auto_optimization = False
    system.auto_optimizer = None
    system.enable_enhanced_optimization = False
    system.enhanced_optimizer = None
    system.optimization_runtime_enabled = False
    system.market_gate_refresh_seconds = 86400
    system.feedback_guard_refresh_seconds = 86400
    system.trade_control_status_print_interval_seconds = 10**9
    system.signal_history = {}
    system.virtual_tracker = _make_history_tracker(system.system_config)
    system.overnight_selector.strategy_profile = strategy_profile
    return system


def _load_history_recommendations(
    history_db: HistoryRecommendationDB,
    db: DatabaseManager,
    start_date: str,
    end_date: str,
    strategy_profile: str,
    top_k: int = 0,
) -> Tuple[Dict[str, List[Dict[str, Any]]], pd.DataFrame]:
    records = history_db.get_recommendations(start_date=start_date, end_date=end_date)
    if not records:
        return {}, pd.DataFrame()

    rec_df = pd.DataFrame(records)
    if rec_df.empty:
        return {}, rec_df

    rec_df["recommendation_date"] = rec_df["recommendation_date"].astype(str)
    rec_df["recommendation_score"] = pd.to_numeric(
        rec_df["recommendation_score"], errors="coerce"
    ).fillna(0.0)
    rec_df["symbol"] = rec_df["symbol"].astype(str)
    rec_df["name"] = rec_df["name"].fillna("").astype(str)

    symbols = sorted(rec_df["symbol"].dropna().unique().tolist())
    industry_map: Dict[str, str] = {}
    if symbols:
        placeholders = ",".join(["?"] * len(symbols))
        rows = db.query(
            f"SELECT ts_code, industry FROM stock_basic WHERE ts_code IN ({placeholders})",
            tuple(symbols),
        )
        industry_map = {
            str(row.get("ts_code", "")): str(row.get("industry", "") or "").strip()
            for row in rows
        }

    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for trade_date, group in rec_df.groupby("recommendation_date", sort=True):
        ordered = group.sort_values(
            by=["recommendation_score", "symbol"],
            ascending=[False, True],
        ).reset_index(drop=True)
        if top_k > 0:
            ordered = ordered.head(int(top_k)).copy()

        core_size = min(10, len(ordered))
        candidates: List[Dict[str, Any]] = []
        for idx, row in ordered.iterrows():
            industry = industry_map.get(row["symbol"], "")
            fallback_industry = str(row.get("strategy_type", "") or "").strip()
            if not industry and fallback_industry.lower() != "unknown":
                industry = fallback_industry

            candidates.append(
                {
                    "symbol": row["symbol"],
                    "name": row["name"],
                    "score": float(row["recommendation_score"]),
                    "recommendation_score": float(row["recommendation_score"]),
                    "pool_type": "core" if idx < core_size else "reserve",
                    "industry": industry,
                    "strategy_profile": strategy_profile,
                    "recommendation_date": trade_date,
                    "rank": int(idx + 1),
                }
            )
        grouped[str(trade_date)] = candidates

    return grouped, rec_df


def _load_intraday_data(
    history_db: HistoryRecommendationDB,
    start_date: str,
    end_date: str,
) -> pd.DataFrame:
    conn = sqlite3.connect(history_db.db_path)
    try:
        intraday_df = pd.read_sql_query(
            """
            SELECT symbol, trade_time, trade_date, open, high, low, close, volume, amount
            FROM intraday_data
            WHERE trade_date >= ? AND trade_date <= ?
            ORDER BY trade_time ASC, symbol ASC
            """,
            conn,
            params=(start_date, end_date),
        )
    finally:
        conn.close()

    if intraday_df.empty:
        return intraday_df

    intraday_df["trade_time"] = pd.to_datetime(intraday_df["trade_time"])
    intraday_df["trade_date"] = intraday_df["trade_date"].astype(str)
    for col in ["open", "high", "low", "close", "volume", "amount"]:
        intraday_df[col] = pd.to_numeric(intraday_df[col], errors="coerce")
    intraday_df = intraday_df.dropna(subset=["symbol", "trade_time", "close"])
    return intraday_df


def _summarize_intraday_granularity(intraday_df: pd.DataFrame) -> Dict[str, Any]:
    if intraday_df is None or intraday_df.empty:
        return {
            "median_interval_minutes": None,
            "mode_interval_minutes": None,
            "sample_pairs": 0,
        }

    intervals: List[float] = []
    sample = intraday_df[["symbol", "trade_date", "trade_time"]].copy()
    sample["trade_time"] = pd.to_datetime(sample["trade_time"])
    sample = sample.sort_values(["symbol", "trade_date", "trade_time"])
    for _, group in sample.groupby(["symbol", "trade_date"], sort=False):
        diffs = (
            group["trade_time"]
            .diff()
            .dropna()
            .dt.total_seconds()
            .div(60.0)
        )
        if not diffs.empty:
            intervals.extend([float(item) for item in diffs.tolist()])

    if not intervals:
        return {
            "median_interval_minutes": None,
            "mode_interval_minutes": None,
            "sample_pairs": 0,
        }

    interval_series = pd.Series(intervals)
    mode_values = interval_series.mode().tolist()
    return {
        "median_interval_minutes": float(interval_series.median()),
        "mode_interval_minutes": float(mode_values[0]) if mode_values else None,
        "sample_pairs": int(len(intervals)),
    }


def _build_prev_close_map(
    db: DatabaseManager,
    symbols: Iterable[str],
    start_date: str,
    end_date: str,
) -> Dict[Tuple[str, str], float]:
    symbols = sorted({str(symbol) for symbol in symbols if str(symbol).strip()})
    if not symbols:
        return {}

    start_dt = datetime.strptime(_normalize_date_text(start_date), "%Y-%m-%d") - timedelta(days=20)
    start_ymd = start_dt.strftime("%Y%m%d")
    end_ymd = _normalize_date_text(end_date).replace("-", "")
    batch = db.get_batch_daily_data(symbols, start_ymd, end_ymd)

    prev_close_map: Dict[Tuple[str, str], float] = {}
    for symbol, df in batch.items():
        if df is None or df.empty:
            continue
        ordered = df.copy()
        ordered["trade_date"] = ordered["trade_date"].astype(str)
        ordered["close"] = pd.to_numeric(ordered["close"], errors="coerce")
        ordered = ordered.sort_values("trade_date").reset_index(drop=True)
        ordered["prev_close"] = ordered["close"].shift(1)
        for _, row in ordered.iterrows():
            prev_close = row.get("prev_close")
            if pd.isna(prev_close):
                continue
            date_text = _normalize_date_text(row["trade_date"])
            prev_close_map[(str(symbol), date_text)] = float(prev_close)
    return prev_close_map


def _build_snapshots(
    cumulative_rows: Dict[str, List[Dict[str, Any]]],
    symbols: Iterable[str],
    prev_close_map: Dict[Tuple[str, str], float],
    name_map: Dict[str, str],
) -> Tuple[pd.DataFrame, Dict[str, pd.DataFrame], Dict[str, float], Dict[str, Dict[str, Any]]]:
    quote_rows: List[Dict[str, Any]] = []
    minute_map: Dict[str, pd.DataFrame] = {}
    current_prices: Dict[str, float] = {}
    last_row_map: Dict[str, Dict[str, Any]] = {}

    for symbol in symbols:
        rows = cumulative_rows.get(symbol, [])
        if not rows:
            continue

        frame = pd.DataFrame(rows)
        if frame.empty:
            continue
        frame = frame.sort_values("trade_time").reset_index(drop=True)
        minute_map[str(symbol)] = frame

        latest = frame.iloc[-1]
        trade_date = str(latest["trade_date"])
        price = float(latest["close"])
        open_price = float(frame.iloc[0]["open"])
        high = float(frame["high"].max())
        low = float(frame["low"].min())
        volume = float(frame["volume"].fillna(0.0).sum())
        amount = (
            float(frame["amount"].fillna(0.0).sum())
            if "amount" in frame.columns and not frame["amount"].isna().all()
            else float((frame["close"].fillna(0.0) * frame["volume"].fillna(0.0)).sum())
        )
        pre_close = float(prev_close_map.get((str(symbol), trade_date), open_price))
        quote_rows.append(
            {
                "symbol": str(symbol),
                "name": str(name_map.get(str(symbol), "")),
                "price": price,
                "open": open_price,
                "high": high,
                "low": low,
                "volume": volume,
                "amount": amount,
                "pre_close": pre_close,
            }
        )
        current_prices[str(symbol)] = price
        last_row_map[str(symbol)] = {
            "trade_time": latest["trade_time"],
            "trade_date": trade_date,
            "price": price,
        }

    return pd.DataFrame(quote_rows), minute_map, current_prices, last_row_map


def _build_backtest_industry_context(
    system: EnhancedHybridSystem,
    minute_map: Dict[str, pd.DataFrame],
    now: datetime,
) -> Dict[str, Any]:
    fallback = system._build_candidate_minute_industry_context(minute_map)
    ranked = sorted(
        fallback.get("industry_map", {}).values(),
        key=lambda item: float(item.get("score", 50.0)),
        reverse=True,
    )
    context = {
        "enabled": True,
        "timestamp": now.strftime("%Y-%m-%d %H:%M:%S"),
        "industry_map": fallback.get("industry_map", {}),
        "top_industries": ranked[:5],
        "bottom_industries": list(reversed(ranked[-5:])) if ranked else [],
        "source": "candidate_minute_backtest",
        "source_available": False,
    }
    system.latest_industry_context = context
    return context


def _build_lightweight_trade_control(
    system: EnhancedHybridSystem,
    quote_df: pd.DataFrame,
    now: datetime,
) -> Dict[str, Any]:
    avg_index_pct = 0.0
    breadth = 0.5
    if quote_df is not None and not quote_df.empty:
        work = quote_df.copy()
        work["pre_close"] = pd.to_numeric(work["pre_close"], errors="coerce")
        work["price"] = pd.to_numeric(work["price"], errors="coerce")
        work = work[(work["pre_close"] > 0) & work["price"].notna()]
        if not work.empty:
            work["ret_pct"] = (work["price"] / work["pre_close"] - 1.0) * 100.0
            avg_index_pct = float(work["ret_pct"].mean())
            breadth = float((work["ret_pct"] > 0).mean())

    max_signals = max(
        1,
        int(system.system_config.get("monitor.market_gate_normal_max_signals_per_round", 4)),
    )
    return {
        "timestamp": now.strftime("%Y-%m-%d %H:%M:%S"),
        "gate_tier": "normal",
        "market_regime": "NEUTRAL",
        "risk_state": "MEDIUM",
        "target_position": 0.30,
        "circuit_state": "normal",
        "circuit_reason": "backtest_lightweight",
        "avg_index_pct": avg_index_pct,
        "breadth": breadth,
        "market_snapshot_source": "candidate_backtest",
        "threshold_boost": 0.0,
        "push_boost": 0.0,
        "position_multiplier": 1.0,
        "max_signals_per_round": max_signals,
        "allow_new_signals": True,
        "feedback_guard_level": "normal",
        "feedback_guard_active": False,
        "feedback_guard_reason": "",
    }


def _summarize_route_stats(trades: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not trades:
        return []

    df = pd.DataFrame(trades)
    rows: List[Dict[str, Any]] = []
    for route, group in df.groupby("buy_route_label"):
        pnl = pd.to_numeric(group["pnl_pct"], errors="coerce").dropna()
        peak = pd.to_numeric(group["peak_pnl_pct"], errors="coerce").dropna()
        rows.append(
            {
                "buy_route_label": str(route),
                "trade_count": int(len(group)),
                "win_rate": float((pnl > 0).mean()) if not pnl.empty else 0.0,
                "avg_pnl_pct": float(pnl.mean()) if not pnl.empty else 0.0,
                "avg_peak_pnl_pct": float(peak.mean()) if not peak.empty else 0.0,
            }
        )
    rows.sort(key=lambda item: (-item["trade_count"], item["buy_route_label"]))
    return rows


def _write_report_files(
    summary: Dict[str, Any],
    trade_rows: List[Dict[str, Any]],
    buy_signal_rows: List[Dict[str, Any]],
    sell_signal_rows: List[Dict[str, Any]],
    daily_rows: List[Dict[str, Any]],
) -> Dict[str, str]:
    reports_dir = ROOT / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")

    json_path = reports_dir / f"legacy_signal_replay_backtest_{run_id}.json"
    md_path = reports_dir / f"legacy_signal_replay_backtest_{run_id}.md"
    trade_csv = reports_dir / f"legacy_signal_replay_trades_{run_id}.csv"
    buy_csv = reports_dir / f"legacy_signal_replay_buy_signals_{run_id}.csv"
    sell_csv = reports_dir / f"legacy_signal_replay_sell_signals_{run_id}.csv"
    daily_csv = reports_dir / f"legacy_signal_replay_daily_{run_id}.csv"

    payload = dict(summary)
    payload["trades"] = trade_rows
    payload["buy_signals"] = buy_signal_rows
    payload["sell_signals"] = sell_signal_rows
    payload["daily"] = daily_rows
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    pd.DataFrame(trade_rows).to_csv(trade_csv, index=False, encoding="utf-8-sig")
    pd.DataFrame(buy_signal_rows).to_csv(buy_csv, index=False, encoding="utf-8-sig")
    pd.DataFrame(sell_signal_rows).to_csv(sell_csv, index=False, encoding="utf-8-sig")
    pd.DataFrame(daily_rows).to_csv(daily_csv, index=False, encoding="utf-8-sig")

    lines = [
        "# 原策略事件驱动回放报告",
        "",
        f"- 生成时间: {summary.get('generated_at', '')}",
        f"- 回放区间: {summary.get('start_date', '')} ~ {summary.get('end_date', '')}",
        f"- 策略档位: {summary.get('strategy_profile', 'legacy')}",
        "",
        "## 关键结论",
        "",
        f"- 推荐样本: {summary.get('recommendation_count', 0)} 条，推荐日: {summary.get('recommendation_days', 0)} 天",
        f"- 触发买点信号: {summary.get('buy_signal_count', 0)} 次，实际开仓: {summary.get('executed_trade_count', 0)} 笔",
        f"- 平仓笔数: {summary.get('closed_trade_count', 0)}，胜率: {summary.get('win_rate_pct', 0.0):.2f}%",
        f"- 平均收益: {summary.get('avg_pnl_pct', 0.0):+.2f}% ，累计收益(简单求和): {summary.get('cumulative_pnl_pct', 0.0):+.2f}%",
        f"- 平均峰值收益: {summary.get('avg_peak_pnl_pct', 0.0):+.2f}% ，平均持有时长: {summary.get('avg_hold_hours', 0.0):.2f} 小时",
        "",
        "## 核心假设",
        "",
    ]
    lines.extend([f"- {item}" for item in summary.get("assumptions", [])])
    lines.extend(["", "## 买点路由表现", ""])
    for row in summary.get("buy_route_stats", []):
        lines.append(
            "- {label}: {count} 笔 | 胜率 {win:.2f}% | 平均收益 {ret:+.2f}% | 平均峰值 {peak:+.2f}%".format(
                label=row.get("buy_route_label", "unknown"),
                count=int(row.get("trade_count", 0)),
                win=float(row.get("win_rate", 0.0)) * 100.0,
                ret=float(row.get("avg_pnl_pct", 0.0)) * 100.0,
                peak=float(row.get("avg_peak_pnl_pct", 0.0)) * 100.0,
            )
        )
    lines.extend(["", "## 卖出原因分布", ""])
    for key, value in sorted(
        summary.get("sell_reason_distribution", {}).items(),
        key=lambda item: (-item[1], item[0]),
    ):
        lines.append(f"- {key}: {int(value)}")

    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {
        "markdown": str(md_path),
        "json": str(json_path),
        "trades_csv": str(trade_csv),
        "buy_signals_csv": str(buy_csv),
        "sell_signals_csv": str(sell_csv),
        "daily_csv": str(daily_csv),
    }


def main() -> None:
    args = parse_args()
    if args.disable_t1:
        args.enforce_t1 = False

    start_date = _normalize_date_text(args.start_date)
    end_date = _normalize_date_text(args.end_date)

    config = ConfigManager()
    db = DatabaseManager(config)
    history_db = HistoryRecommendationDB()
    system = _build_system(strategy_profile=args.strategy_profile)
    tracker = system.virtual_tracker

    recommendations_by_date, rec_df = _load_history_recommendations(
        history_db=history_db,
        db=db,
        start_date=start_date,
        end_date=end_date,
        strategy_profile=args.strategy_profile,
        top_k=int(args.top_k or 0),
    )
    if rec_df.empty:
        raise SystemExit("未找到历史推荐名单")

    intraday_conn = sqlite3.connect(history_db.db_path)
    try:
        intraday_max_date = intraday_conn.execute(
            "SELECT MAX(trade_date) FROM intraday_data"
        ).fetchone()[0]
    finally:
        intraday_conn.close()
    intraday_last_date = _normalize_date_text(intraday_max_date or end_date)

    intraday_df = _load_intraday_data(
        history_db=history_db,
        start_date=start_date,
        end_date=intraday_last_date,
    )
    if intraday_df.empty:
        raise SystemExit("未找到历史分时数据")

    prev_close_map = _build_prev_close_map(
        db=db,
        symbols=rec_df["symbol"].astype(str).unique().tolist(),
        start_date=start_date,
        end_date=intraday_last_date,
    )
    intraday_by_date = {
        str(trade_date): frame.sort_values("trade_time").reset_index(drop=True)
        for trade_date, frame in intraday_df.groupby("trade_date", sort=True)
    }

    buy_signal_rows: List[Dict[str, Any]] = []
    sell_signal_rows: List[Dict[str, Any]] = []
    daily_rows: List[Dict[str, Any]] = []
    last_seen_quotes: Dict[str, Dict[str, Any]] = {}

    for trade_date in sorted(intraday_by_date.keys()):
        candidates = recommendations_by_date.get(trade_date, [])
        system.candidate_pool = list(candidates)
        system.candidate_date = trade_date
        system.signal_history = {}

        open_symbols = sorted(tracker.open_trades.keys())
        relevant_symbols = set(open_symbols) | {item["symbol"] for item in candidates}
        if not relevant_symbols:
            continue

        day_frame = intraday_by_date.get(trade_date, pd.DataFrame())
        if day_frame.empty:
            continue
        day_frame = day_frame[day_frame["symbol"].isin(relevant_symbols)].copy()
        if day_frame.empty:
            continue

        name_map = {item["symbol"]: item.get("name", "") for item in candidates}
        for symbol, trade in tracker.open_trades.items():
            name_map.setdefault(symbol, getattr(trade, "name", ""))

        cumulative_rows: Dict[str, List[Dict[str, Any]]] = {}
        executed_buys_today = 0
        closed_today = 0

        for bar_time, group in day_frame.groupby("trade_time", sort=True):
            now = pd.Timestamp(bar_time).to_pydatetime()
            for _, row in group.iterrows():
                symbol = str(row["symbol"])
                cumulative_rows.setdefault(symbol, []).append(
                    {
                        "symbol": symbol,
                        "trade_time": pd.Timestamp(row["trade_time"]).to_pydatetime(),
                        "trade_date": str(row["trade_date"]),
                        "open": _safe_float(row["open"]),
                        "high": _safe_float(row["high"]),
                        "low": _safe_float(row["low"]),
                        "close": _safe_float(row["close"]),
                        "volume": _safe_float(row["volume"]),
                        "amount": _safe_float(row["amount"]),
                    }
                )

            relevant_now = set(tracker.open_trades.keys()) | {item["symbol"] for item in candidates}
            quote_df, minute_map, current_prices, last_row_map = _build_snapshots(
                cumulative_rows=cumulative_rows,
                symbols=relevant_now,
                prev_close_map=prev_close_map,
                name_map=name_map,
            )
            last_seen_quotes.update(last_row_map)
            if quote_df.empty:
                continue

            trade_control = _build_lightweight_trade_control(
                system=system,
                quote_df=quote_df,
                now=now,
            )
            industry_context = _build_backtest_industry_context(system, minute_map, now=now)

            buy_signals = []
            if candidates:
                buy_signals = system._detect_signals(
                    df=quote_df,
                    now=now,
                    minute_map=minute_map,
                    industry_context=industry_context,
                    trade_control=trade_control,
                )

            for signal in buy_signals:
                signal["signal_time"] = now
                buy_signal_rows.append(
                    {
                        "trade_date": trade_date,
                        "signal_time": now.strftime("%Y-%m-%d %H:%M:%S"),
                        "symbol": signal.get("symbol", ""),
                        "name": signal.get("name", ""),
                        "price": _safe_float(signal.get("price")),
                        "total_score": _safe_float(signal.get("total_score")),
                        "overnight_score": _safe_float(signal.get("overnight_score")),
                        "intraday_score": _safe_float(signal.get("intraday_score")),
                        "buy_route_label": str(
                            signal.get("buy_route_label", signal.get("buy_template_source", "unknown"))
                        ),
                        "buy_template_source": str(signal.get("buy_template_source", "")),
                        "signal_type": str(signal.get("signal_type", "")),
                        "executed": False,
                    }
                )
                if tracker.on_buy_signal(signal):
                    buy_signal_rows[-1]["executed"] = True
                    executed_buys_today += 1

            current_prices = {
                symbol: price
                for symbol, price in current_prices.items()
                if symbol in tracker.open_trades
            }
            blocked_symbols = []
            if args.enforce_t1:
                blocked_symbols = [
                    symbol
                    for symbol, trade in tracker.open_trades.items()
                    if trade.buy_time.date() == now.date()
                ]

            closed_trades = []
            if current_prices:
                closed_trades = tracker.check_and_close(
                    current_prices=current_prices,
                    now=now,
                    blocked_symbols=blocked_symbols,
                )

            if closed_trades:
                closed_today += len(closed_trades)
                sell_signals = system._build_sell_signals_from_closed_trades(
                    closed_trades=closed_trades,
                    trade_control=trade_control,
                )
                for signal in sell_signals:
                    details = signal.get("signal_details", {}) or {}
                    sell_signal_rows.append(
                        {
                            "trade_date": trade_date,
                            "signal_time": now.strftime("%Y-%m-%d %H:%M:%S"),
                            "symbol": signal.get("symbol", ""),
                            "name": signal.get("name", ""),
                            "price": _safe_float(signal.get("price")),
                            "signal_type": str(signal.get("signal_type", "")),
                            "sell_reason": str(details.get("sell_reason", "")),
                            "pnl_pct": _safe_float(details.get("pnl_pct")) / 100.0,
                            "hold_minutes": int(_safe_float(details.get("hold_minutes"), 0)),
                        }
                    )

        daily_rows.append(
            {
                "trade_date": trade_date,
                "recommendation_count": len(candidates),
                "buy_signal_count": sum(1 for row in buy_signal_rows if row["trade_date"] == trade_date),
                "executed_buy_count": executed_buys_today,
                "closed_trade_count": closed_today,
                "open_trades_end": len(tracker.open_trades),
            }
        )

    forced_closes = 0
    if tracker.open_trades:
        for symbol, trade in list(tracker.open_trades.items()):
            last_quote = last_seen_quotes.get(symbol)
            if not last_quote:
                continue
            tracker._close_trade(
                trade=trade,
                sell_price=_safe_float(last_quote["price"]),
                reason="forced_end_of_backtest",
                sell_time=pd.Timestamp(last_quote["trade_time"]).to_pydatetime(),
            )
            tracker.open_trades.pop(symbol, None)
            forced_closes += 1

    stats = tracker.get_statistics()
    trade_rows: List[Dict[str, Any]] = []
    for trade in tracker.closed_trades:
        details = trade.details or {}
        hold_minutes = int(trade.hold_duration or 0)
        trade_rows.append(
            {
                "symbol": trade.symbol,
                "name": trade.name,
                "buy_date": trade.buy_time.strftime("%Y-%m-%d"),
                "buy_time": trade.buy_time.strftime("%Y-%m-%d %H:%M:%S"),
                "buy_price": _safe_float(trade.buy_price),
                "buy_signal": str(trade.buy_signal),
                "buy_score": _safe_float(trade.buy_score),
                "buy_route": str(details.get("buy_route", "")),
                "buy_route_label": str(
                    details.get("buy_route_label", details.get("buy_template_source", "unknown"))
                ),
                "buy_template_source": str(details.get("buy_template_source", "")),
                "sell_time": trade.sell_time.strftime("%Y-%m-%d %H:%M:%S") if trade.sell_time else "",
                "sell_price": _safe_float(trade.sell_price),
                "sell_reason": str(trade.sell_reason or ""),
                "pnl_pct": _safe_float(trade.pnl_pct),
                "peak_pnl_pct": _safe_float(trade.highest_pnl_pct),
                "hold_minutes": hold_minutes,
                "hold_hours": round(hold_minutes / 60.0, 2),
                "partial_take_done": bool(getattr(trade, "partial_take_done", False)),
                "risk_profile": str(getattr(trade, "risk_profile", "")),
                "industry": str(details.get("industry", "")),
            }
        )

    trade_rows.sort(key=lambda item: item["buy_time"])
    avg_peak_pnl = float(np.mean([row["peak_pnl_pct"] for row in trade_rows])) if trade_rows else 0.0
    avg_hold_hours = float(np.mean([row["hold_hours"] for row in trade_rows])) if trade_rows else 0.0
    intraday_granularity = _summarize_intraday_granularity(intraday_df)
    summary = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "start_date": start_date,
        "end_date": intraday_last_date,
        "recommendation_end_date": end_date,
        "strategy_profile": args.strategy_profile,
        "intraday_granularity": intraday_granularity,
        "recommendation_count": int(len(rec_df)),
        "recommendation_days": int(len(recommendations_by_date)),
        "intraday_days": int(len(intraday_by_date)),
        "buy_signal_count": int(len(buy_signal_rows)),
        "executed_trade_count": int(sum(1 for row in buy_signal_rows if row["executed"])),
        "closed_trade_count": int(len(trade_rows)),
        "forced_close_count": int(forced_closes),
        "win_rate_pct": float(stats.get("win_rate", 0.0)) * 100.0,
        "avg_pnl_pct": float(stats.get("avg_pnl_pct", 0.0)) * 100.0,
        "cumulative_pnl_pct": float(stats.get("cumulative_pnl", 0.0)) * 100.0,
        "profit_loss_ratio": float(stats.get("profit_loss_ratio", 0.0)),
        "max_drawdown_pct": float(stats.get("max_drawdown", 0.0)) * 100.0,
        "avg_hold_hours": avg_hold_hours,
        "avg_peak_pnl_pct": avg_peak_pnl * 100.0,
        "buy_route_stats": _summarize_route_stats(trade_rows),
        "sell_reason_distribution": dict(stats.get("close_reasons", {})),
        "assumptions": [
            "按历史推荐日期视为当日盘前候选池，并在当日盘中监控买点。",
            "历史推荐库未单独保存 strategy_profile，回放默认按原策略 legacy 解释。",
            "候选池若当日超过10只，则按分数前10只记为 core，其余记为 reserve。",
            "行业确认为历史公平起见，仅使用候选池分钟级聚合，不使用当前实时板块接口。",
            "卖出使用当前虚拟持仓动态退出规则；若启用T+1，则买入当日仅更新峰值，不允许平仓。",
            "回放末日仍未卖出的持仓，会按最后一个可用分时价格强制收口，原因标记为 forced_end_of_backtest。",
        ],
    }
    summary["output_files"] = _write_report_files(
        summary=summary,
        trade_rows=trade_rows,
        buy_signal_rows=buy_signal_rows,
        sell_signal_rows=sell_signal_rows,
        daily_rows=daily_rows,
    )

    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
