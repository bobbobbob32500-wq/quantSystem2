# -*- coding: utf-8 -*-
"""Backfill 1-minute intraday bars for historical recommendation windows."""

from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import sys
import time as time_module
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.core.config import ConfigManager
from src.core.logger import get_logger
from src.modules.backtest.history_recommendation_db import HistoryRecommendationDB
from src.modules.backtest.intraday_data_downloader import IntradayDataDownloader

logger = get_logger("backfill_recommendation_intraday_1m")


@dataclass
class SymbolWindow:
    symbol: str
    start_date: str
    end_date: str
    recommendation_count: int


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Backfill 1-minute intraday data for historical recommendation windows."
    )
    parser.add_argument("--start-date", default="2026-02-05")
    parser.add_argument("--end-date", default="2026-03-25")
    parser.add_argument(
        "--window-calendar-days",
        type=int,
        default=12,
        help="Calendar days to preserve after each recommendation date.",
    )
    parser.add_argument(
        "--limit-symbols",
        type=int,
        default=0,
        help="Only process first N merged symbol windows, 0 means all.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force re-download even if window already looks like 1-minute data.",
    )
    parser.add_argument(
        "--only-low-open",
        action="store_true",
        help="Only backfill windows whose recommendation-day open gap was below threshold in existing history.",
    )
    parser.add_argument(
        "--low-open-threshold-pct",
        type=float,
        default=-2.0,
        help="Threshold for recommendation-day open gap when --only-low-open is enabled.",
    )
    parser.add_argument(
        "--pause-seconds",
        type=float,
        default=31.0,
        help="Pause between download requests to respect public data limits.",
    )
    parser.add_argument(
        "--no-backup",
        action="store_true",
        help="Skip backup of history_recommendation.db before writing.",
    )
    return parser.parse_args()


def _normalize_date_text(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if len(text) == 8 and text.isdigit():
        return f"{text[:4]}-{text[4:6]}-{text[6:]}"
    return text


def _load_recommendations(
    db_path: Path,
    start_date: str,
    end_date: str,
) -> pd.DataFrame:
    conn = sqlite3.connect(db_path)
    try:
        query = """
        SELECT symbol, recommendation_date
        FROM recommendations
        WHERE recommendation_date >= ? AND recommendation_date <= ?
        ORDER BY recommendation_date ASC, symbol ASC
        """
        df = pd.read_sql_query(query, conn, params=(start_date, end_date))
    finally:
        conn.close()

    if df.empty:
        return df
    df["symbol"] = df["symbol"].astype(str)
    df["recommendation_date"] = df["recommendation_date"].astype(str).map(_normalize_date_text)
    return df


def _merge_symbol_windows(
    recommendations: pd.DataFrame,
    window_calendar_days: int,
) -> List[SymbolWindow]:
    windows: List[SymbolWindow] = []
    if recommendations.empty:
        return windows

    for symbol, group in recommendations.groupby("symbol", sort=True):
        ranges: List[Tuple[datetime, datetime]] = []
        for recommendation_date in sorted(group["recommendation_date"].unique().tolist()):
            start_dt = datetime.strptime(recommendation_date, "%Y-%m-%d")
            end_dt = start_dt + timedelta(days=int(window_calendar_days))
            ranges.append((start_dt, end_dt))

        if not ranges:
            continue

        ranges.sort(key=lambda item: item[0])
        merged: List[Tuple[datetime, datetime, int]] = []
        for start_dt, end_dt in ranges:
            if not merged:
                merged.append((start_dt, end_dt, 1))
                continue
            last_start, last_end, count = merged[-1]
            if start_dt <= last_end + timedelta(days=1):
                merged[-1] = (last_start, max(last_end, end_dt), count + 1)
            else:
                merged.append((start_dt, end_dt, 1))

        for start_dt, end_dt, count in merged:
            windows.append(
                SymbolWindow(
                    symbol=symbol,
                    start_date=start_dt.strftime("%Y-%m-%d"),
                    end_date=end_dt.strftime("%Y-%m-%d"),
                    recommendation_count=count,
                )
            )

    windows.sort(key=lambda item: (item.start_date, item.symbol))
    return windows


def _filter_low_open_recommendations(
    recommendations: pd.DataFrame,
    history_db_path: Path,
    daily_db_path: Path,
    threshold_pct: float,
) -> pd.DataFrame:
    if recommendations.empty:
        return recommendations

    conn_history = sqlite3.connect(history_db_path)
    try:
        first_intraday = pd.read_sql_query(
            """
            SELECT d.symbol, d.trade_date AS recommendation_date, d.open
            FROM intraday_data d
            JOIN (
                SELECT symbol, trade_date, MIN(trade_time) AS first_time
                FROM intraday_data
                WHERE trade_date >= ? AND trade_date <= ?
                GROUP BY symbol, trade_date
            ) f
              ON d.symbol = f.symbol
             AND d.trade_date = f.trade_date
             AND d.trade_time = f.first_time
            """,
            conn_history,
            params=(
                recommendations["recommendation_date"].min(),
                recommendations["recommendation_date"].max(),
            ),
        )
    finally:
        conn_history.close()

    conn_daily = sqlite3.connect(daily_db_path)
    try:
        daily_df = pd.read_sql_query(
            """
            SELECT ts_code AS symbol, trade_date, close
            FROM stock_daily
            WHERE trade_date >= ? AND trade_date <= ?
            """,
            conn_daily,
            params=(
                (
                    datetime.strptime(recommendations["recommendation_date"].min(), "%Y-%m-%d")
                    - timedelta(days=20)
                ).strftime("%Y%m%d"),
                datetime.strptime(recommendations["recommendation_date"].max(), "%Y-%m-%d").strftime("%Y%m%d"),
            ),
        )
    finally:
        conn_daily.close()

    daily_df["trade_date"] = daily_df["trade_date"].astype(str)
    daily_df = daily_df.sort_values(["symbol", "trade_date"]).reset_index(drop=True)
    daily_df["prev_close"] = pd.to_numeric(daily_df["close"], errors="coerce").groupby(
        daily_df["symbol"]
    ).shift(1)
    daily_df["recommendation_date"] = pd.to_datetime(daily_df["trade_date"]).dt.strftime("%Y-%m-%d")
    prev_close_df = daily_df[["symbol", "recommendation_date", "prev_close"]]

    merged = recommendations.merge(
        first_intraday[["symbol", "recommendation_date", "open"]],
        on=["symbol", "recommendation_date"],
        how="left",
    ).merge(
        prev_close_df,
        on=["symbol", "recommendation_date"],
        how="left",
    )
    merged["open_pct"] = (
        pd.to_numeric(merged["open"], errors="coerce")
        / pd.to_numeric(merged["prev_close"], errors="coerce")
        - 1.0
    ) * 100.0
    filtered = merged[pd.to_numeric(merged["open_pct"], errors="coerce") <= float(threshold_pct)].copy()
    return filtered[["symbol", "recommendation_date"]].drop_duplicates().reset_index(drop=True)


def _analyze_interval_minutes(df: pd.DataFrame) -> Dict[str, Optional[float]]:
    if df is None or df.empty or "trade_time" not in df.columns:
        return {"median_interval_minutes": None, "bars_per_day": 0.0, "trade_days": 0}

    ordered = df.copy()
    ordered["trade_time"] = pd.to_datetime(ordered["trade_time"])
    ordered["trade_date"] = pd.to_datetime(ordered["trade_time"]).dt.strftime("%Y-%m-%d")

    intervals: List[float] = []
    for _, group in ordered.groupby("trade_date", sort=True):
        diffs = (
            group.sort_values("trade_time")["trade_time"]
            .diff()
            .dropna()
            .dt.total_seconds()
            .div(60.0)
        )
        if not diffs.empty:
            intervals.extend(diffs.tolist())

    trade_days = int(ordered["trade_date"].nunique())
    bars_per_day = float(len(ordered) / trade_days) if trade_days else 0.0
    median_interval = float(pd.Series(intervals).median()) if intervals else None
    return {
        "median_interval_minutes": median_interval,
        "bars_per_day": bars_per_day,
        "trade_days": trade_days,
    }


def _window_already_1m(existing_df: pd.DataFrame) -> bool:
    summary = _analyze_interval_minutes(existing_df)
    median_interval = summary["median_interval_minutes"]
    bars_per_day = summary["bars_per_day"] or 0.0
    return (
        median_interval is not None
        and median_interval <= 1.5
        and bars_per_day >= 180
        and int(summary["trade_days"] or 0) >= 1
    )


def _backup_db_if_needed(db_path: Path, enabled: bool) -> Optional[Path]:
    if not enabled:
        return None
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = db_path.with_name(f"{db_path.stem}_backup_before_1m_{timestamp}{db_path.suffix}")
    shutil.copy2(db_path, backup_path)
    return backup_path


def _report_path() -> Path:
    reports_dir = ROOT / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return reports_dir / f"intraday_1m_backfill_{timestamp}.json"


def main() -> int:
    args = parse_args()
    config = ConfigManager()
    history_db = HistoryRecommendationDB()
    downloader = IntradayDataDownloader(token=config.get("data_source.tushare_token"))

    db_path = ROOT / "data" / "history_recommendation.db"
    recommendations = _load_recommendations(
        db_path=db_path,
        start_date=_normalize_date_text(args.start_date),
        end_date=_normalize_date_text(args.end_date),
    )
    if recommendations.empty:
        logger.error("No historical recommendations found in the requested range.")
        return 1

    raw_recommendation_count = int(len(recommendations))
    if args.only_low_open:
        recommendations = _filter_low_open_recommendations(
            recommendations=recommendations,
            history_db_path=db_path,
            daily_db_path=ROOT / "data" / "database" / "quant_system.db",
            threshold_pct=float(args.low_open_threshold_pct),
        )
        logger.info(
            "Filtered to low-open recommendation subset: %s / %s",
            len(recommendations),
            raw_recommendation_count,
        )
        if recommendations.empty:
            logger.error("No low-open recommendations matched the requested threshold.")
            return 1

    windows = _merge_symbol_windows(
        recommendations=recommendations,
        window_calendar_days=int(args.window_calendar_days),
    )
    if args.limit_symbols and int(args.limit_symbols) > 0:
        windows = windows[: int(args.limit_symbols)]

    backup_path = _backup_db_if_needed(db_path, enabled=not args.no_backup)
    if backup_path:
        logger.info("Database backup created: %s", backup_path)

    results: List[Dict[str, object]] = []
    downloaded_count = 0
    skipped_count = 0
    failed_count = 0

    logger.info(
        "Backfilling %s merged symbol windows covering %s recommendations.",
        len(windows),
        len(recommendations),
    )

    for index, window in enumerate(windows, start=1):
        logger.info(
            "[%s/%s] %s %s -> %s (recs=%s)",
            index,
            len(windows),
            window.symbol,
            window.start_date,
            window.end_date,
            window.recommendation_count,
        )

        existing_df = history_db.get_intraday_data(
            window.symbol,
            start_time=f"{window.start_date} 00:00:00",
            end_time=f"{window.end_date} 23:59:59",
        )
        before_summary = _analyze_interval_minutes(existing_df)
        should_skip = (not args.force) and _window_already_1m(existing_df)
        if should_skip:
            skipped_count += 1
            results.append(
                {
                    "symbol": window.symbol,
                    "start_date": window.start_date,
                    "end_date": window.end_date,
                    "status": "skipped_already_1m",
                    "recommendation_count": window.recommendation_count,
                    "before": before_summary,
                    "after": before_summary,
                    "rows_written": 0,
                }
            )
            continue

        if index > 1 and float(args.pause_seconds) > 0:
            time_module.sleep(float(args.pause_seconds))

        downloaded_df = downloader.download_intraday_data(
            symbol=window.symbol,
            start_date=window.start_date,
            end_date=window.end_date,
            freq="1min",
            use_cache=not args.force,
        )
        if downloaded_df.empty:
            failed_count += 1
            results.append(
                {
                    "symbol": window.symbol,
                    "start_date": window.start_date,
                    "end_date": window.end_date,
                    "status": "download_failed",
                    "recommendation_count": window.recommendation_count,
                    "before": before_summary,
                    "after": before_summary,
                    "rows_written": 0,
                }
            )
            continue

        write_ok = history_db.add_intraday_data(window.symbol, downloaded_df)
        after_df = history_db.get_intraday_data(
            window.symbol,
            start_time=f"{window.start_date} 00:00:00",
            end_time=f"{window.end_date} 23:59:59",
        )
        after_summary = _analyze_interval_minutes(after_df)

        if write_ok:
            downloaded_count += 1
            status = "downloaded"
        else:
            failed_count += 1
            status = "write_failed"

        results.append(
            {
                "symbol": window.symbol,
                "start_date": window.start_date,
                "end_date": window.end_date,
                "status": status,
                "recommendation_count": window.recommendation_count,
                "before": before_summary,
                "after": after_summary,
                "rows_written": int(len(downloaded_df)),
            }
        )

    report = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "start_date": _normalize_date_text(args.start_date),
        "end_date": _normalize_date_text(args.end_date),
        "window_calendar_days": int(args.window_calendar_days),
        "force": bool(args.force),
        "backup_path": str(backup_path) if backup_path else None,
        "recommendation_count": int(len(recommendations)),
        "raw_recommendation_count": raw_recommendation_count,
        "unique_symbols": int(recommendations["symbol"].nunique()),
        "merged_windows": int(len(windows)),
        "downloaded_windows": int(downloaded_count),
        "skipped_windows": int(skipped_count),
        "failed_windows": int(failed_count),
        "only_low_open": bool(args.only_low_open),
        "low_open_threshold_pct": float(args.low_open_threshold_pct),
        "pause_seconds": float(args.pause_seconds),
        "results": results,
    }

    report_path = _report_path()
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("Backfill report saved to %s", report_path)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
