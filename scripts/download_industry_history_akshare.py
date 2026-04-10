# -*- coding: utf-8 -*-
"""Download industry historical strength from AKShare and upsert into block_data."""

from __future__ import annotations

import argparse
import os
import sys
import time
from typing import List, Optional, Tuple

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.core.config import ConfigManager  # noqa: E402
from src.core.database import DatabaseManager  # noqa: E402

try:
    import akshare as ak  # type: ignore
except Exception as exc:  # pragma: no cover
    raise RuntimeError(f"akshare import failed: {exc}")


def _pick_col(df: pd.DataFrame, candidates: List[str]) -> Optional[str]:
    cols = list(df.columns)
    for c in candidates:
        if c in cols:
            return c
    for col in cols:
        for c in candidates:
            if c in str(col):
                return col
    return None


def _load_industry_names() -> List[Tuple[str, str]]:
    try:
        name_df = ak.stock_board_industry_name_em()
    except Exception:
        return []
    if name_df is None or name_df.empty:
        return []
    name_col = _pick_col(name_df, ["板块名称", "名称"])
    code_col = _pick_col(name_df, ["板块代码", "代码"])
    if name_col is None:
        return []
    pairs: List[Tuple[str, str]] = []
    for _, row in name_df.iterrows():
        n = str(row.get(name_col, "")).strip()
        if not n:
            continue
        code = str(row.get(code_col, n)).strip() if code_col else n
        pairs.append((n, code or n))
    return pairs


def _history_to_rows(
    industry_name: str,
    industry_code: str,
    start_date: str,
    end_date: str,
) -> List[tuple]:
    try:
        hist = ak.stock_board_industry_hist_em(
            symbol=industry_name,
            start_date=start_date,
            end_date=end_date,
            period="日k",
            adjust="",
        )
    except Exception:
        return []
    if hist is None or hist.empty:
        return []

    date_col = _pick_col(hist, ["日期", "时间", "trade_date"])
    pct_col = _pick_col(hist, ["涨跌幅", "pct_chg", "涨跌"])
    if date_col is None or pct_col is None:
        return []

    rows: List[tuple] = []
    for _, row in hist.iterrows():
        d = str(row.get(date_col, "")).strip()
        if not d:
            continue
        trade_date = d.replace("-", "")
        if len(trade_date) != 8 or not trade_date.isdigit():
            continue
        rise = pd.to_numeric(row.get(pct_col), errors="coerce")
        if pd.isna(rise):
            continue
        rows.append((industry_name, "industry_hist", industry_code, float(rise), trade_date))
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description="Download industry historical data to block_data.")
    parser.add_argument("--start-date", required=True, help="YYYYMMDD")
    parser.add_argument("--end-date", required=True, help="YYYYMMDD")
    parser.add_argument("--max-boards", type=int, default=0, help="0 means all")
    parser.add_argument("--sleep-ms", type=int, default=120)
    args = parser.parse_args()

    cfg = ConfigManager()
    db = DatabaseManager(cfg)
    upsert_sql = """
        INSERT OR REPLACE INTO block_data
        (block_name, block_type, ts_code, block_rise, trade_date)
        VALUES (?, ?, ?, ?, ?)
    """

    boards = _load_industry_names()
    if not boards:
        print("industry_boards=0 (failed to fetch board list; check network/proxy)")
        return
    if args.max_boards and args.max_boards > 0:
        boards = boards[: int(args.max_boards)]
    print(f"industry_boards={len(boards)}")

    total_rows = 0
    for idx, (name, code) in enumerate(boards, start=1):
        rows = _history_to_rows(name, code, args.start_date, args.end_date)
        if rows:
            db.execute_many(upsert_sql, rows)
            total_rows += len(rows)
        print(f"[{idx}/{len(boards)}] {name} rows={len(rows)} total={total_rows}")
        if args.sleep_ms > 0:
            time.sleep(max(args.sleep_ms, 0) / 1000.0)

    print("=" * 70)
    print("industry history download done")
    print("=" * 70)
    print(f"window={args.start_date}..{args.end_date}")
    print(f"insert_rows={total_rows}")


if __name__ == "__main__":
    main()
