# -*- coding: utf-8 -*-
"""
Fill missing chip tables from AkShare (Eastmoney source).

Outputs:
- stock_chip_perf: recent CYQ summary rows (about 90 days per symbol)
- stock_chip_dist: latest trade-date price distribution (150 bins per symbol)
"""

from __future__ import annotations

import argparse
import math
import os
import sys
from datetime import datetime
from typing import List, Optional, Tuple

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


def _to_symbol(ts_code: str) -> str:
    code = str(ts_code or "").strip().upper()
    if "." in code:
        code = code.split(".", 1)[0]
    return code


def _safe_numeric(value: object, default: float = np.nan) -> float:
    try:
        return float(value)
    except Exception:
        return float(default)


def _normalize_hist(hist: pd.DataFrame) -> pd.DataFrame:
    """AkShare stock_zh_a_hist -> trade_date/open/close/high/low/hsl"""
    if hist is None or hist.empty:
        return pd.DataFrame(columns=["trade_date", "open", "close", "high", "low", "hsl"])

    cols = list(hist.columns)
    col_map = {str(c).strip(): c for c in cols}
    required = {
        "date": col_map.get("日期"),
        "open": col_map.get("开盘"),
        "close": col_map.get("收盘"),
        "high": col_map.get("最高"),
        "low": col_map.get("最低"),
        "hsl": col_map.get("换手率"),
    }
    if not all(required.values()):
        return pd.DataFrame(columns=["trade_date", "open", "close", "high", "low", "hsl"])

    df = hist[
        [
            required["date"],
            required["open"],
            required["close"],
            required["high"],
            required["low"],
            required["hsl"],
        ]
    ].copy()
    df.columns = ["trade_date", "open", "close", "high", "low", "hsl"]
    df["trade_date"] = pd.to_datetime(df["trade_date"], errors="coerce")
    for c in ["open", "close", "high", "low", "hsl"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df.dropna(subset=["trade_date", "open", "close", "high", "low", "hsl"]).copy()


def _calc_cyq_distribution_latest(hist_df: pd.DataFrame) -> Optional[pd.DataFrame]:
    """
    Python port of CYQ core for latest bar only.
    Returns DataFrame with columns: price, weight
    """
    if hist_df is None or hist_df.empty or len(hist_df) < 20:
        return None

    df = hist_df.copy().sort_values("trade_date").reset_index(drop=True)
    idx = len(df) - 1
    start = max(0, idx - 120 + 1)
    kdata = df.iloc[start : idx + 1].copy()
    if kdata.empty:
        return None

    max_price = float(kdata["high"].max())
    min_price = float(kdata["low"].min())
    factor = 150
    accuracy = max(0.01, (max_price - min_price) / (factor - 1))
    xdata = np.zeros(factor, dtype=float)
    yrange = np.array([min_price + accuracy * i for i in range(factor)], dtype=float)

    for _, row in kdata.iterrows():
        o = float(row["open"])
        c = float(row["close"])
        h = float(row["high"])
        l = float(row["low"])
        hsl = max(float(row["hsl"]), 0.0)
        avg = (o + c + h + l) / 4.0
        turnover = min(1.0, hsl / 100.0)
        if turnover <= 0:
            continue

        xdata *= (1.0 - turnover)

        if abs(h - l) < 1e-12:
            g1 = int(math.floor((avg - min_price) / accuracy))
            g1 = min(max(g1, 0), factor - 1)
            xdata[g1] += (factor - 1) * turnover / 2.0
            continue

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
                if abs(avg - l) < 1e-12:
                    add = g0 * turnover
                else:
                    add = (cur - l) / (avg - l) * g0 * turnover
            else:
                if abs(h - avg) < 1e-12:
                    add = g0 * turnover
                else:
                    add = (h - cur) / (h - avg) * g0 * turnover
            if add > 0:
                xdata[j] += add

    xdata = np.clip(xdata, 0.0, None)
    total = float(xdata.sum())
    if total <= 1e-12:
        return None
    out = pd.DataFrame({"price": yrange.round(2), "weight": xdata / total})
    out = out[out["weight"] > 0].copy()
    return out if not out.empty else None


def main() -> None:
    parser = argparse.ArgumentParser(description="Fill chip tables from AkShare.")
    parser.add_argument("--max-symbols", type=int, default=0, help="0 means all")
    parser.add_argument("--start-date", type=str, default="", help="chip_perf start YYYYMMDD")
    parser.add_argument("--end-date", type=str, default="", help="chip_perf end YYYYMMDD")
    parser.add_argument("--workers", type=int, default=1, help="thread workers (recommend 1)")
    parser.add_argument("--offset", type=int, default=0, help="start offset in mainboard symbol list")
    parser.add_argument("--limit", type=int, default=0, help="number of symbols to process from offset; 0 means all")
    args = parser.parse_args()

    cfg = ConfigManager()
    db = DatabaseManager(cfg)
    import akshare as ak

    latest_daily = str(db.get_latest_trade_date("stock_daily") or "")
    if not latest_daily:
        print("No stock_daily data, abort.")
        return
    end_date = (args.end_date or latest_daily).replace("-", "")
    start_date = (args.start_date or "").replace("-", "")

    symbols = _mainboard_symbols(db)
    if args.offset and int(args.offset) > 0:
        symbols = symbols[int(args.offset) :]
    if args.limit and int(args.limit) > 0:
        symbols = symbols[: int(args.limit)]
    if args.max_symbols and int(args.max_symbols) > 0:
        symbols = symbols[: int(args.max_symbols)]
    if not symbols:
        print("No symbols, abort.")
        return

    print("=" * 70)
    print("Fill chip tables from AkShare")
    print("=" * 70)
    print(f"symbols={len(symbols)} perf_range={start_date or '(auto 90d)'}->{end_date}")

    now_text = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def _process_one(ts_code: str) -> Tuple[List[tuple], List[tuple], bool]:
        symbol = _to_symbol(ts_code)
        perf_rows: List[tuple] = []
        dist_rows: List[tuple] = []
        try:
            perf_df = ak.stock_cyq_em(symbol=symbol, adjust="")
            if perf_df is not None and not perf_df.empty:
                c = list(perf_df.columns)
                date_col, winner_col, avg_col = c[0], c[1], c[2]
                c90_low, c90_high = c[3], c[4]
                c70_low, c70_high = c[6], c[7]
                p = perf_df.copy()
                p["trade_date"] = pd.to_datetime(p[date_col], errors="coerce").dt.strftime("%Y%m%d")
                if start_date:
                    p = p[p["trade_date"] >= start_date]
                p = p[p["trade_date"] <= end_date]
                for _, row in p.iterrows():
                    t = str(row.get("trade_date") or "")
                    if not t:
                        continue
                    cost_5 = _safe_numeric(row.get(c90_low))
                    cost_95 = _safe_numeric(row.get(c90_high))
                    cost_15 = _safe_numeric(row.get(c70_low))
                    cost_85 = _safe_numeric(row.get(c70_high))
                    avg_cost = _safe_numeric(row.get(avg_col))
                    winner_rate = _safe_numeric(row.get(winner_col))
                    if np.isnan(cost_5) or np.isnan(cost_95):
                        continue
                    perf_rows.append(
                        (
                            ts_code,
                            t,
                            cost_5,
                            cost_15 if not np.isnan(cost_15) else cost_5,
                            avg_cost if not np.isnan(avg_cost) else (cost_5 + cost_95) / 2.0,
                            cost_85 if not np.isnan(cost_85) else cost_95,
                            cost_95,
                            avg_cost if not np.isnan(avg_cost) else (cost_5 + cost_95) / 2.0,
                            winner_rate if not np.isnan(winner_rate) else None,
                            now_text,
                        )
                    )

            hist = ak.stock_zh_a_hist(
                symbol=symbol,
                period="daily",
                start_date="20240101",
                end_date=end_date,
                adjust="",
            )
            hist_df = _normalize_hist(hist)
            hist_df = hist_df[hist_df["trade_date"] <= pd.to_datetime(end_date)]
            dist = _calc_cyq_distribution_latest(hist_df)
            if dist is not None and not dist.empty:
                for _, row in dist.iterrows():
                    dist_rows.append(
                        (
                            ts_code,
                            end_date,
                            float(row["price"]),
                            float(row["weight"]),
                            now_text,
                        )
                    )
            return perf_rows, dist_rows, True
        except Exception:
            return [], [], False

    all_perf: List[tuple] = []
    all_dist: List[tuple] = []
    ok_cnt = 0
    fail_cnt = 0
    workers = max(1, int(args.workers or 1))

    if workers <= 1:
        total = len(symbols)
        for idx, ts in enumerate(symbols, 1):
            perf_rows, dist_rows, ok = _process_one(ts)
            if ok:
                ok_cnt += 1
            else:
                fail_cnt += 1
            if perf_rows:
                all_perf.extend(perf_rows)
            if dist_rows:
                all_dist.extend(dist_rows)
            if idx % 50 == 0 or idx == total:
                print(
                    f"progress {idx}/{total} ok={ok_cnt} fail={fail_cnt} "
                    f"perf_rows={len(all_perf)} dist_rows={len(all_dist)}"
                )
    else:
        # Note: some akshare internals are not fully thread-safe in some envs.
        # Keep this branch optional.
        from concurrent.futures import ThreadPoolExecutor, as_completed

        with ThreadPoolExecutor(max_workers=workers) as ex:
            futures = [ex.submit(_process_one, ts) for ts in symbols]
            total = len(futures)
            done = 0
            for fut in as_completed(futures):
                done += 1
                perf_rows, dist_rows, ok = fut.result()
                if ok:
                    ok_cnt += 1
                else:
                    fail_cnt += 1
                if perf_rows:
                    all_perf.extend(perf_rows)
                if dist_rows:
                    all_dist.extend(dist_rows)
                if done % 50 == 0 or done == total:
                    print(
                        f"progress {done}/{total} ok={ok_cnt} fail={fail_cnt} "
                        f"perf_rows={len(all_perf)} dist_rows={len(all_dist)}"
                    )

    if all_perf:
        db.execute_many(
            """
            REPLACE INTO stock_chip_perf (
                ts_code, trade_date, cost_5pct, cost_15pct, cost_50pct,
                cost_85pct, cost_95pct, weight_avg, winner_rate, create_time
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            all_perf,
        )
    if all_dist:
        db.execute_many(
            """
            REPLACE INTO stock_chip_dist (ts_code, trade_date, price, weight, create_time)
            VALUES (?, ?, ?, ?, ?)
            """,
            all_dist,
        )

    print("-" * 70)
    print(f"done symbols={len(symbols)} ok={ok_cnt} fail={fail_cnt}")
    print(f"upsert rows: perf={len(all_perf)} dist={len(all_dist)}")
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
