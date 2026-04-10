# -*- coding: utf-8 -*-
"""
Fill chip data from BaoStock using CYQ-style calculation.

Output tables:
- stock_chip_perf: recent N trade dates per symbol
- stock_chip_dist: recent M trade-date distributions per symbol
"""

from __future__ import annotations

import argparse
import math
import os
import sys
from datetime import datetime
from typing import List, Optional, Tuple

import baostock as bs
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.core.config import ConfigManager
from src.core.database import DatabaseManager


def _mainboard_symbols(db: DatabaseManager) -> List[str]:
    rows = db.query(
        """
        SELECT ts_code
        FROM stock_basic
        WHERE (
            ts_code LIKE '600%.SH' OR ts_code LIKE '601%.SH' OR ts_code LIKE '603%.SH' OR ts_code LIKE '605%.SH'
            OR ts_code LIKE '000%.SZ' OR ts_code LIKE '001%.SZ' OR ts_code LIKE '002%.SZ' OR ts_code LIKE '003%.SZ'
        )
        ORDER BY ts_code
        """
    )
    return [str(r.get("ts_code") or "").strip().upper() for r in rows if str(r.get("ts_code") or "").strip()]


def _to_bs_code(ts_code: str) -> str:
    code = str(ts_code).strip().upper()
    sym, exch = code.split(".")
    return f"{'sh' if exch == 'SH' else 'sz'}.{sym}"


def _fetch_hist(bs_code: str, start_date: str, end_date: str) -> pd.DataFrame:
    rs = bs.query_history_k_data_plus(
        bs_code,
        "date,code,open,high,low,close,turn",
        start_date=start_date,
        end_date=end_date,
        frequency="d",
        adjustflag="3",
    )
    if rs.error_code != "0":
        return pd.DataFrame()
    rows = []
    while rs.error_code == "0" and rs.next():
        rows.append(rs.get_row_data())
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows, columns=rs.fields)
    for c in ["open", "high", "low", "close", "turn"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date", "open", "high", "low", "close", "turn"]).copy()
    return df.sort_values("date").reset_index(drop=True)


def _calc_triangle_add(
    xdata: np.ndarray,
    min_price: float,
    accuracy: float,
    o: float,
    c: float,
    h: float,
    l: float,
    turnover_rate: float,
) -> None:
    factor = len(xdata)
    avg = (o + c + h + l) / 4.0
    turnover = min(max(turnover_rate / 100.0, 0.0), 1.0)
    if turnover <= 0:
        return

    xdata *= 1.0 - turnover

    if abs(h - l) < 1e-12:
        g1 = int(math.floor((avg - min_price) / accuracy))
        g1 = min(max(g1, 0), factor - 1)
        xdata[g1] += (factor - 1) * turnover / 2.0
        return

    h_idx = int(math.floor((h - min_price) / accuracy))
    l_idx = int(math.ceil((l - min_price) / accuracy))
    h_idx = min(max(h_idx, 0), factor - 1)
    l_idx = min(max(l_idx, 0), factor - 1)
    if l_idx > h_idx:
        l_idx, h_idx = h_idx, l_idx

    g0 = 2.0 / (h - l)
    for j in range(l_idx, h_idx + 1):
        cur = min_price + accuracy * j
        if cur <= avg:
            add = g0 * turnover if abs(avg - l) < 1e-12 else (cur - l) / (avg - l) * g0 * turnover
        else:
            add = g0 * turnover if abs(h - avg) < 1e-12 else (h - cur) / (h - avg) * g0 * turnover
        if add > 0:
            xdata[j] += add


def _chips_quantile(price_grid: np.ndarray, chips: np.ndarray, q: float) -> float:
    target = float(chips.sum()) * q
    if target <= 0:
        return float(price_grid[0])
    acc = 0.0
    for i in range(len(chips)):
        acc += float(chips[i])
        if acc >= target:
            return float(price_grid[i])
    return float(price_grid[-1])


def _calc_symbol_cyq(
    hist: pd.DataFrame,
    out_days: int = 90,
    dist_days: int = 90,
    bins: int = 150,
) -> Tuple[List[dict], List[dict]]:
    if hist is None or hist.empty or len(hist) < 30:
        return [], []

    max_price = float(hist["high"].max())
    min_price = float(hist["low"].min())
    if max_price <= min_price:
        return [], []

    accuracy = max(0.01, (max_price - min_price) / (bins - 1))
    price_grid = np.array([min_price + accuracy * i for i in range(bins)], dtype=float)
    xdata = np.zeros(bins, dtype=float)

    perf_rows: List[dict] = []
    dist_rows: List[dict] = []
    start_collect_idx = max(0, len(hist) - out_days)
    start_dist_idx = max(0, len(hist) - dist_days)

    for i, row in hist.iterrows():
        _calc_triangle_add(
            xdata=xdata,
            min_price=min_price,
            accuracy=accuracy,
            o=float(row["open"]),
            c=float(row["close"]),
            h=float(row["high"]),
            l=float(row["low"]),
            turnover_rate=float(row["turn"]),
        )
        xdata = np.clip(xdata, 0.0, None)
        total = float(xdata.sum())
        if total <= 1e-12:
            continue
        chips = xdata / total
        trade_date = pd.Timestamp(row["date"]).strftime("%Y%m%d")

        if i >= start_collect_idx:
            c5 = _chips_quantile(price_grid, chips, 0.05)
            c15 = _chips_quantile(price_grid, chips, 0.15)
            c50 = _chips_quantile(price_grid, chips, 0.50)
            c85 = _chips_quantile(price_grid, chips, 0.85)
            c95 = _chips_quantile(price_grid, chips, 0.95)
            winner = float(chips[price_grid <= float(row["close"])].sum())
            perf_rows.append(
                {
                    "trade_date": trade_date,
                    "cost_5pct": c5,
                    "cost_15pct": c15,
                    "cost_50pct": c50,
                    "cost_85pct": c85,
                    "cost_95pct": c95,
                    "weight_avg": c50,
                    "winner_rate": winner,
                }
            )
        if i >= start_dist_idx:
            positive_mask = chips > 0
            if np.any(positive_mask):
                prices = price_grid[positive_mask]
                weights = chips[positive_mask]
                for px, wt in zip(prices, weights):
                    dist_rows.append(
                        {
                            "trade_date": trade_date,
                            "price": float(round(px, 2)),
                            "weight": float(wt),
                        }
                    )

    return perf_rows, dist_rows


def main() -> None:
    parser = argparse.ArgumentParser(description="Fill chip data from BaoStock.")
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--limit", type=int, default=200)
    parser.add_argument("--start-date", type=str, default="2024-01-01")
    parser.add_argument("--end-date", type=str, default="")
    parser.add_argument("--out-days", type=int, default=90)
    parser.add_argument("--dist-days", type=int, default=90)
    parser.add_argument("--flush-every", type=int, default=40, help="flush to DB every N symbols")
    args = parser.parse_args()

    cfg = ConfigManager()
    db = DatabaseManager(cfg)

    latest_daily = str(db.get_latest_trade_date("stock_daily") or "")
    if not latest_daily:
        print("No stock_daily data, abort.")
        return

    end_date = args.end_date or f"{latest_daily[:4]}-{latest_daily[4:6]}-{latest_daily[6:]}"
    symbols = _mainboard_symbols(db)
    if args.offset > 0:
        symbols = symbols[args.offset :]
    if args.limit > 0:
        symbols = symbols[: args.limit]
    if not symbols:
        print("No symbols to process.")
        return

    lg = bs.login()
    if lg.error_code != "0":
        print(f"BaoStock login failed: {lg.error_code} {lg.error_msg}")
        return

    print("=" * 70)
    print("Fill chip tables from BaoStock")
    print("=" * 70)
    print(
        f"symbols={len(symbols)} offset={args.offset} limit={args.limit} "
        f"start={args.start_date} end={end_date} out_days={args.out_days} dist_days={args.dist_days}"
    )

    now_text = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    perf_params: List[tuple] = []
    dist_params: List[tuple] = []
    total_perf_rows = 0
    total_dist_rows = 0
    ok_cnt = 0
    fail_cnt = 0
    flush_every = max(int(args.flush_every), 1)

    def _flush_buffers() -> None:
        nonlocal total_perf_rows, total_dist_rows, perf_params, dist_params
        if perf_params:
            db.execute_many(
                """
                REPLACE INTO stock_chip_perf (
                    ts_code, trade_date, cost_5pct, cost_15pct, cost_50pct,
                    cost_85pct, cost_95pct, weight_avg, winner_rate, create_time
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                perf_params,
            )
            total_perf_rows += len(perf_params)
            perf_params = []
        if dist_params:
            db.execute_many(
                """
                REPLACE INTO stock_chip_dist (ts_code, trade_date, price, weight, create_time)
                VALUES (?, ?, ?, ?, ?)
                """,
                dist_params,
            )
            total_dist_rows += len(dist_params)
            dist_params = []

    try:
        for i, ts_code in enumerate(symbols, 1):
            bs_code = _to_bs_code(ts_code)
            hist = _fetch_hist(bs_code, args.start_date, end_date)
            if hist.empty:
                fail_cnt += 1
                continue
            perf_rows, dist_rows = _calc_symbol_cyq(
                hist,
                out_days=max(args.out_days, 30),
                dist_days=max(args.dist_days, 30),
            )
            if not perf_rows or not dist_rows:
                fail_cnt += 1
                continue

            for row in perf_rows:
                perf_params.append(
                    (
                        ts_code,
                        row["trade_date"],
                        row["cost_5pct"],
                        row["cost_15pct"],
                        row["cost_50pct"],
                        row["cost_85pct"],
                        row["cost_95pct"],
                        row["weight_avg"],
                        row["winner_rate"],
                        now_text,
                    )
                )
            for row in dist_rows:
                dist_params.append(
                    (
                        ts_code,
                        str(row["trade_date"]),
                        float(row["price"]),
                        float(row["weight"]),
                        now_text,
                    )
                )
            ok_cnt += 1
            if i % flush_every == 0:
                _flush_buffers()
            if i % 20 == 0 or i == len(symbols):
                print(
                    f"progress {i}/{len(symbols)} ok={ok_cnt} fail={fail_cnt} "
                    f"perf_rows={len(perf_params)} dist_rows={len(dist_params)}"
                )
    finally:
        bs.logout()
    _flush_buffers()

    print("-" * 70)
    print(f"done symbols={len(symbols)} ok={ok_cnt} fail={fail_cnt}")
    print(f"upsert rows: perf={total_perf_rows} dist={total_dist_rows}")
    print(
        "table counts:",
        "chip_perf=", db.get_table_count("stock_chip_perf"),
        "chip_dist=", db.get_table_count("stock_chip_dist"),
    )
    print(
        "latest dates:",
        "chip_perf=", db.get_latest_trade_date("stock_chip_perf"),
        "chip_dist=", db.get_latest_trade_date("stock_chip_dist"),
    )


if __name__ == "__main__":
    main()
