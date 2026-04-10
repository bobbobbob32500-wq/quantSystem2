# -*- coding: utf-8 -*-
"""Run strong_start_research_v4 structural scan (no backtest metrics)."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Dict, Iterable, List
import sys

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.core.database import DatabaseManager
from src.modules.strong_start_research_v4 import StrongStartResearchV4


def _chunked(items: List[str], size: int) -> Iterable[List[str]]:
    for i in range(0, len(items), size):
        yield items[i : i + size]


def _fetch_daily_enrichment(
    db: DatabaseManager,
    ts_codes: List[str],
    start_date: str,
    end_date: str,
) -> pd.DataFrame:
    if not ts_codes:
        return pd.DataFrame(columns=["ts_code", "trade_date", "close", "amount", "amount_ma20"])

    frames = []
    for part in _chunked(sorted(set(ts_codes)), 400):
        placeholders = ",".join("?" for _ in part)
        sql = f"""
            SELECT ts_code, trade_date, close, amount
            FROM stock_daily
            WHERE ts_code IN ({placeholders})
              AND trade_date >= ? AND trade_date <= ?
            ORDER BY ts_code ASC, trade_date ASC
        """
        params = tuple(part) + (start_date, end_date)
        frame = db.query_to_dataframe(sql, params)
        if not frame.empty:
            frames.append(frame)
    if not frames:
        return pd.DataFrame(columns=["ts_code", "trade_date", "close", "amount", "amount_ma20"])

    daily = pd.concat(frames, ignore_index=True)
    daily["amount"] = pd.to_numeric(daily["amount"], errors="coerce")
    daily["close"] = pd.to_numeric(daily["close"], errors="coerce")
    daily = daily.sort_values(["ts_code", "trade_date"]).reset_index(drop=True)
    daily["amount_ma20"] = (
        daily.groupby("ts_code")["amount"].transform(lambda s: s.rolling(20, min_periods=10).mean())
    )
    return daily


def _fetch_basic_enrichment(db: DatabaseManager) -> pd.DataFrame:
    sql = "SELECT ts_code, name, industry, list_date FROM stock_basic"
    base = db.query_to_dataframe(sql)
    if base.empty:
        return pd.DataFrame(columns=["ts_code", "name", "industry", "list_date"])
    base["list_date"] = pd.to_datetime(base["list_date"].astype(str), format="%Y%m%d", errors="coerce")
    return base


def _parse_reason_list(series: pd.Series) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for raw in series.dropna().astype(str):
        try:
            arr = json.loads(raw)
        except Exception:
            continue
        if not isinstance(arr, list):
            continue
        for item in arr:
            key = str(item)
            counts[key] = counts.get(key, 0) + 1
    return counts


def _parse_trigger_failures(series: pd.Series) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for raw in series.dropna().astype(str):
        try:
            obj = json.loads(raw)
        except Exception:
            continue
        if not isinstance(obj, dict):
            continue
        for group_name, payload in obj.items():
            if not isinstance(payload, dict):
                continue
            for rid in payload.get("failed_rules", []) or []:
                key = f"{group_name}:{rid}"
                counts[key] = counts.get(key, 0) + 1
    return counts


def main() -> None:
    parser = argparse.ArgumentParser(description="Structure scan for strong_start_research_v4.")
    parser.add_argument(
        "--snapshot",
        type=str,
        default="data/research/strong_start_full/event_feature_snapshot_batch4.parquet",
    )
    parser.add_argument("--start-date", type=str, default="")
    parser.add_argument("--end-date", type=str, default="")
    parser.add_argument("--profile", type=str, default="neutral", choices=["loose", "neutral", "strict"])
    parser.add_argument("--config", type=str, default="config/strong_start_research_v4_config.yaml")
    parser.add_argument("--output-dir", type=str, default="data/research/strong_start_full/v4_scan")
    args = parser.parse_args()

    snapshot_path = Path(args.snapshot)
    if not snapshot_path.exists():
        raise FileNotFoundError(f"snapshot not found: {snapshot_path}")

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    data = pd.read_parquet(snapshot_path)
    data["trade_date"] = data["trade_date"].astype(str)
    if args.start_date:
        data = data[data["trade_date"] >= str(args.start_date)]
    if args.end_date:
        data = data[data["trade_date"] <= str(args.end_date)]
    data = data.sort_values(["trade_date", "ts_code"]).reset_index(drop=True)
    if data.empty:
        raise ValueError("no rows in selected date range")

    db = DatabaseManager()
    start_buffer = (pd.to_datetime(data["trade_date"].min(), format="%Y%m%d") - pd.Timedelta(days=60)).strftime("%Y%m%d")
    end_date = data["trade_date"].max()
    ts_codes = sorted(data["ts_code"].astype(str).unique().tolist())

    basic = _fetch_basic_enrichment(db)
    daily = _fetch_daily_enrichment(db, ts_codes, start_buffer, end_date)

    enriched = data.merge(
        basic[["ts_code", "name", "industry", "list_date"]],
        on="ts_code",
        how="left",
        suffixes=("", "_basic"),
    )
    enriched["name"] = enriched["name"].fillna(enriched.get("name_basic")).fillna("")
    enriched["industry"] = enriched["industry"].fillna(enriched.get("industry_basic")).fillna("UNKNOWN")
    enriched = enriched.drop(columns=[c for c in ["name_basic", "industry_basic"] if c in enriched.columns])

    if not daily.empty:
        enriched = enriched.merge(
            daily[["ts_code", "trade_date", "close", "amount_ma20"]],
            on=["ts_code", "trade_date"],
            how="left",
            suffixes=("", "_daily"),
        )
        if "close_daily" in enriched.columns:
            enriched["close"] = pd.to_numeric(enriched["close"], errors="coerce").fillna(
                pd.to_numeric(enriched["close_daily"], errors="coerce")
            )
            enriched = enriched.drop(columns=["close_daily"])

    trade_dt = pd.to_datetime(enriched["trade_date"], format="%Y%m%d", errors="coerce")
    enriched["list_days"] = (trade_dt - pd.to_datetime(enriched["list_date"], errors="coerce")).dt.days

    strategy = StrongStartResearchV4(config_path=args.config)
    result = strategy.run_on_dataframe(enriched, profile=args.profile)

    # structural statistics only
    by_day = (
        result.groupby("trade_date")
        .agg(
            total_events=("ts_code", "count"),
            after_filters=("is_candidate_after_filters", "sum"),
            trigger_pass=("trigger_status", "sum"),
            ready_signals=("signal_ready", "sum"),
            score_median=("score_total", "median"),
            score_p75=("score_total", lambda s: s.quantile(0.75)),
            score_p90=("score_total", lambda s: s.quantile(0.90)),
        )
        .reset_index()
        .sort_values("trade_date")
    )

    filter_reason_counts = _parse_reason_list(result["filter_reject_reasons"])
    trigger_fail_counts = _parse_trigger_failures(result["trigger_details"])
    filter_reason_df = pd.DataFrame(
        [{"reason": k, "count": v} for k, v in sorted(filter_reason_counts.items(), key=lambda x: x[1], reverse=True)]
    )
    trigger_fail_df = pd.DataFrame(
        [{"trigger_rule": k, "count": v} for k, v in sorted(trigger_fail_counts.items(), key=lambda x: x[1], reverse=True)]
    )

    out_signal = out_dir / f"strong_start_research_v4_scan_{args.profile}.parquet"
    out_day = out_dir / f"strong_start_research_v4_scan_daily_{args.profile}.csv"
    out_filter = out_dir / f"strong_start_research_v4_filter_reasons_{args.profile}.csv"
    out_trigger = out_dir / f"strong_start_research_v4_trigger_fails_{args.profile}.csv"
    out_summary = out_dir / f"strong_start_research_v4_scan_summary_{args.profile}.json"

    result.to_parquet(out_signal, index=False)
    by_day.to_csv(out_day, index=False, encoding="utf-8-sig")
    filter_reason_df.to_csv(out_filter, index=False, encoding="utf-8-sig")
    trigger_fail_df.to_csv(out_trigger, index=False, encoding="utf-8-sig")

    summary = {
        "profile": args.profile,
        "rows": int(len(result)),
        "days": int(result["trade_date"].nunique()),
        "after_filters_rate": float(result["is_candidate_after_filters"].mean()),
        "trigger_pass_rate": float(result["trigger_status"].mean()),
        "ready_rate": float(result["signal_ready"].mean()),
        "top_filter_reasons": filter_reason_df.head(10).to_dict(orient="records"),
        "top_trigger_fail_rules": trigger_fail_df.head(10).to_dict(orient="records"),
    }
    out_summary.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print("=" * 72)
    print("strong_start_research_v4 structural scan complete")
    print("=" * 72)
    print(f"signal_scan={out_signal}")
    print(f"daily_stats={out_day}")
    print(f"filter_reasons={out_filter}")
    print(f"trigger_fails={out_trigger}")
    print(f"summary={out_summary}")


if __name__ == "__main__":
    main()
