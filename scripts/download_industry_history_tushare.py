# -*- coding: utf-8 -*-
"""Download board-strength history via Tushare with local-aggregation fallback.

Modes:
- tushare: only use Tushare THS board data
- local: only use local stock_daily + stock_basic industry aggregation
- auto: try tushare first, fallback to local when unavailable
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from typing import Dict, List, Optional, Tuple

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.core.config import ConfigManager  # noqa: E402
from src.core.database import DatabaseManager  # noqa: E402


def _mainboard_cond() -> str:
    return (
        "(d.ts_code LIKE '600%.SH' OR d.ts_code LIKE '601%.SH' OR d.ts_code LIKE '603%.SH' OR d.ts_code LIKE '605%.SH' "
        "OR d.ts_code LIKE '000%.SZ' OR d.ts_code LIKE '001%.SZ' OR d.ts_code LIKE '002%.SZ' OR d.ts_code LIKE '003%.SZ')"
    )


def _load_tushare_pro(token: str):
    import tushare as ts  # lazy import

    ts.set_token(token)
    return ts.pro_api()


def _pick_pct_col(df: pd.DataFrame) -> Optional[str]:
    for c in ["pct_change", "change", "涨跌幅", "PCT_CHANGE"]:
        if c in df.columns:
            return c
    for c in df.columns:
        if "pct" in str(c).lower() or "涨跌" in str(c):
            return c
    return None


def _fetch_ths_rows(
    pro,
    start_date: str,
    end_date: str,
    max_boards: int,
    sleep_ms: int,
) -> List[tuple]:
    rows: List[tuple] = []
    idx = pro.ths_index(fields="ts_code,name")
    if idx is None or idx.empty:
        return rows
    idx = idx.dropna(subset=["ts_code", "name"]).copy()
    idx["ts_code"] = idx["ts_code"].astype(str).str.strip()
    idx["name"] = idx["name"].astype(str).str.strip()
    idx = idx[idx["ts_code"] != ""]
    if max_boards > 0:
        idx = idx.head(max_boards)

    for i, (_, board) in enumerate(idx.iterrows(), start=1):
        ts_code = str(board["ts_code"])
        name = str(board["name"]) or ts_code
        try:
            daily = pro.ths_daily(ts_code=ts_code, start_date=start_date, end_date=end_date)
        except Exception:
            daily = None
        if daily is None or daily.empty:
            print(f"[{i}/{len(idx)}] {name}({ts_code}) rows=0")
            if sleep_ms > 0:
                time.sleep(sleep_ms / 1000.0)
            continue

        pct_col = _pick_pct_col(daily)
        if pct_col is None or "trade_date" not in daily.columns:
            print(f"[{i}/{len(idx)}] {name}({ts_code}) rows=0 (missing pct/trade_date col)")
            if sleep_ms > 0:
                time.sleep(sleep_ms / 1000.0)
            continue

        use = daily[["trade_date", pct_col]].copy()
        use["trade_date"] = use["trade_date"].astype(str).str.replace("-", "", regex=False)
        use[pct_col] = pd.to_numeric(use[pct_col], errors="coerce")
        use = use.dropna(subset=["trade_date", pct_col])
        use = use[use["trade_date"].str.len() == 8]
        added = 0
        for _, r in use.iterrows():
            rows.append((name, "ths_index_daily", ts_code, float(r[pct_col]), str(r["trade_date"])))
            added += 1

        print(f"[{i}/{len(idx)}] {name}({ts_code}) rows={added}")
        if sleep_ms > 0:
            time.sleep(sleep_ms / 1000.0)
    return rows


def _build_local_industry_rows(
    db: DatabaseManager,
    start_date: str,
    end_date: str,
    mainboard_only: bool,
) -> List[tuple]:
    where_mainboard = f" AND {_mainboard_cond()} " if mainboard_only else ""
    sql = f"""
        SELECT d.trade_date, b.industry, AVG(d.pct_chg) AS avg_pct
        FROM stock_daily d
        JOIN stock_basic b ON d.ts_code = b.ts_code
        WHERE d.trade_date >= ? AND d.trade_date <= ?
          AND b.industry IS NOT NULL
          AND b.industry <> ''
          {where_mainboard}
        GROUP BY d.trade_date, b.industry
        ORDER BY d.trade_date, b.industry
    """
    data = db.query(sql, (start_date, end_date))
    if not data:
        return []
    rows: List[tuple] = []
    for r in data:
        trade_date = str(r.get("trade_date") or "").replace("-", "")
        industry = str(r.get("industry") or "").strip()
        avg_pct = pd.to_numeric(r.get("avg_pct"), errors="coerce")
        if not industry or len(trade_date) != 8 or pd.isna(avg_pct):
            continue
        rows.append((industry, "industry_agg_daily", f"IND:{industry}", float(avg_pct), trade_date))
    return rows


def _upsert_rows(db: DatabaseManager, rows: List[tuple], chunk_size: int, dry_run: bool) -> int:
    if not rows:
        return 0
    if dry_run:
        return len(rows)
    sql = """
        INSERT OR REPLACE INTO block_data
        (block_name, block_type, ts_code, block_rise, trade_date)
        VALUES (?, ?, ?, ?, ?)
    """
    total = 0
    chunk = max(int(chunk_size), 100)
    for i in range(0, len(rows), chunk):
        part = rows[i : i + chunk]
        db.execute_many(sql, part)
        total += len(part)
    return total


def _detect_tushare_token(config: ConfigManager) -> str:
    token = str(config.get("data_source.tushare_token", "") or "").strip()
    if token and "your_tushare_token" not in token.lower():
        return token
    return ""


def main() -> None:
    parser = argparse.ArgumentParser(description="Download board history with Tushare/local fallback.")
    parser.add_argument("--start-date", required=True, help="YYYYMMDD")
    parser.add_argument("--end-date", required=True, help="YYYYMMDD")
    parser.add_argument("--mode", default="auto", choices=["auto", "tushare", "local"])
    parser.add_argument("--max-boards", type=int, default=0, help="0 means all (tushare mode)")
    parser.add_argument("--sleep-ms", type=int, default=120, help="request interval for tushare mode")
    parser.add_argument("--chunk-size", type=int, default=2000)
    parser.add_argument("--mainboard-only", action="store_true", default=False)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    cfg = ConfigManager()
    db = DatabaseManager(cfg)
    token = _detect_tushare_token(cfg)

    used_source = ""
    rows: List[tuple] = []

    if args.mode in {"auto", "tushare"}:
        if not token:
            if args.mode == "tushare":
                raise RuntimeError("Tushare token missing; cannot run in tushare mode.")
            print("Tushare token missing; fallback to local aggregation.")
        else:
            try:
                pro = _load_tushare_pro(token)
                rows = _fetch_ths_rows(
                    pro=pro,
                    start_date=args.start_date,
                    end_date=args.end_date,
                    max_boards=int(args.max_boards),
                    sleep_ms=int(args.sleep_ms),
                )
                if rows:
                    used_source = "tushare_ths"
            except Exception as e:
                if args.mode == "tushare":
                    raise
                print(f"Tushare THS failed, fallback to local aggregation: {e}")

    if (not rows) and args.mode in {"auto", "local"}:
        rows = _build_local_industry_rows(
            db=db,
            start_date=args.start_date,
            end_date=args.end_date,
            mainboard_only=bool(args.mainboard_only),
        )
        used_source = "local_industry_agg"

    inserted = _upsert_rows(db, rows, chunk_size=int(args.chunk_size), dry_run=bool(args.dry_run))
    print("=" * 70)
    print("board history load done")
    print("=" * 70)
    print(f"window={args.start_date}..{args.end_date}")
    print(f"source={used_source or 'none'}")
    print(f"rows_prepared={len(rows)}")
    print(f"rows_written={inserted}")
    print(f"dry_run={bool(args.dry_run)}")


if __name__ == "__main__":
    main()
