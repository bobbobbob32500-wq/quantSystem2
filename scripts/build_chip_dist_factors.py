# -*- coding: utf-8 -*-
"""
Build daily chip-distribution shape factors from stock_chip_dist.

The output table stock_chip_dist_factor_profile stores one row per
(ts_code, trade_date, profile_key), so strategy presets can use
profile-consistent factor values.
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from datetime import datetime
from typing import List, Optional, Tuple

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.core.config import ConfigManager
from src.core.database import DatabaseManager
from src.modules.strong_start_strategy import StrongStartParams


def _find_local_peak_indexes(weights: np.ndarray) -> np.ndarray:
    if weights.size == 0:
        return np.array([], dtype=int)
    if weights.size == 1:
        return np.array([0], dtype=int)
    peaks: List[int] = []
    for i in range(weights.size):
        left = weights[i - 1] if i > 0 else -np.inf
        right = weights[i + 1] if i < weights.size - 1 else -np.inf
        if weights[i] >= left and weights[i] >= right:
            peaks.append(i)
    return np.array(peaks, dtype=int)


def _calc_factor_row(
    ts_code: str,
    trade_date: str,
    prices: np.ndarray,
    weights: np.ndarray,
    significant_ratio: float,
    secondary_ratio_max: float,
    dominance_min: float,
    band_pct: float,
    single_peak_score_min: float,
    min_rows: int,
) -> Optional[Tuple]:
    if prices.size < max(min_rows, 3):
        return None
    w = np.nan_to_num(weights.astype(float), nan=0.0, posinf=0.0, neginf=0.0)
    w = np.maximum(w, 0.0)
    weight_sum = float(w.sum())
    if weight_sum <= 0:
        return None
    w = w / weight_sum
    px = prices.astype(float)

    peak_idx = _find_local_peak_indexes(w)
    if peak_idx.size == 0:
        peak_idx = np.array([int(np.argmax(w))], dtype=int)
    peak_w = w[peak_idx]
    peak_px = px[peak_idx]
    order = np.argsort(-peak_w)
    peak_w = peak_w[order]
    peak_px = peak_px[order]

    primary_weight = float(peak_w[0]) if peak_w.size >= 1 else 0.0
    secondary_weight = float(peak_w[1]) if peak_w.size >= 2 else 0.0
    secondary_ratio = secondary_weight / max(primary_weight, 1e-9)
    dominance = max(1.0 - secondary_ratio, 0.0)
    dominant_price = float(peak_px[0]) if peak_px.size >= 1 else float(px[np.argmax(w)])

    significant_count = int(np.sum(peak_w >= primary_weight * significant_ratio))
    band_mask = np.abs(px - dominant_price) <= max(dominant_price, 1e-9) * band_pct
    main_band_weight = float(w[band_mask].sum())

    dist_std = float(np.sqrt(np.sum(w * np.square(px - dominant_price))))
    norm_std = dist_std / max(dominant_price, 1e-9)
    spread_penalty = min(norm_std / max(band_pct * 1.5, 1e-9), 1.0)
    density_score = max(main_band_weight * (1.0 - 0.6 * spread_penalty), 0.0)
    secondary_score = 1.0 - min(secondary_ratio / max(secondary_ratio_max, 1e-9), 1.0)
    peak_count_score = max(1.0 - max(significant_count - 1, 0) / 3.0, 0.0)

    single_peak_dense_score = min(
        max(
            0.40 * secondary_score
            + 0.30 * main_band_weight
            + 0.20 * density_score
            + 0.10 * peak_count_score,
            0.0,
        ),
        1.0,
    )
    is_single_peak_dense = (
        significant_count <= 1
        and secondary_ratio <= secondary_ratio_max
        and dominance >= dominance_min
        and single_peak_dense_score >= single_peak_score_min
    )
    now_text = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return (
        str(ts_code),
        str(trade_date),
        int(significant_count),
        float(primary_weight),
        float(secondary_ratio),
        float(dominance),
        float(main_band_weight),
        int(px.size),
        float(single_peak_dense_score),
        1 if bool(is_single_peak_dense) else 0,
        now_text,
    )


def _ensure_output_table(db: DatabaseManager) -> None:
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS stock_chip_dist_factor_profile (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts_code TEXT NOT NULL,
            trade_date TEXT NOT NULL,
            profile_key TEXT NOT NULL,
            chip_peak_count_sig INTEGER,
            chip_primary_peak_weight REAL,
            chip_secondary_peak_ratio REAL,
            chip_peak_dominance REAL,
            chip_main_band_weight REAL,
            chip_dist_points INTEGER,
            single_peak_dense_score REAL,
            chip_single_peak_dense INTEGER,
            create_time TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(ts_code, trade_date, profile_key)
        )
        """
    )
    db.execute(
        "CREATE INDEX IF NOT EXISTS idx_chip_factor_profile_code_date ON stock_chip_dist_factor_profile(profile_key, ts_code, trade_date)"
    )
    db.execute(
        "CREATE INDEX IF NOT EXISTS idx_chip_factor_profile_date ON stock_chip_dist_factor_profile(profile_key, trade_date)"
    )


def _preset_params(preset: str) -> StrongStartParams:
    name = str(preset or "").strip().lower()
    if name == "tradeable_v1":
        return StrongStartParams.tradeable_v1()
    if name == "tradeable_v2":
        return StrongStartParams.tradeable_v2()
    if name == "tradeable_v3_research":
        return StrongStartParams.tradeable_v3_research()
    return StrongStartParams()


def main() -> None:
    parser = argparse.ArgumentParser(description="Build stock_chip_dist_factor from stock_chip_dist.")
    parser.add_argument("--start-date", type=str, default="2025-04-03", help="YYYYMMDD")
    parser.add_argument("--end-date", type=str, default="2026-04-03", help="YYYYMMDD")
    parser.add_argument("--chunk-size", type=int, default=200000)
    parser.add_argument("--flush-groups", type=int, default=2000)
    parser.add_argument(
        "--preset",
        type=str,
        default="tradeable_v2",
        choices=["default", "tradeable_v1", "tradeable_v2", "tradeable_v3_research", "custom"],
        help="preset for chip-factor thresholds",
    )
    parser.add_argument("--profile-key", type=str, default="", help="custom factor profile key")
    parser.add_argument("--chip-dist-min-rows", type=int, default=10)
    parser.add_argument("--chip-peak-significant-ratio", type=float, default=0.75)
    parser.add_argument("--chip-peak-secondary-ratio-max", type=float, default=1.0)
    parser.add_argument("--chip-peak-dominance-min", type=float, default=0.0)
    parser.add_argument("--chip-peak-band-pct", type=float, default=0.03)
    parser.add_argument("--chip-single-peak-score-min", type=float, default=0.08)
    args = parser.parse_args()

    if args.preset != "custom":
        preset_params = _preset_params(args.preset)
        args.chip_dist_min_rows = int(preset_params.chip_dist_min_rows)
        args.chip_peak_significant_ratio = float(preset_params.chip_peak_significant_ratio)
        args.chip_peak_secondary_ratio_max = float(preset_params.chip_peak_secondary_ratio_max)
        args.chip_peak_dominance_min = float(preset_params.chip_peak_dominance_min)
        args.chip_peak_band_pct = float(preset_params.chip_peak_band_pct)
        args.chip_single_peak_score_min = float(preset_params.chip_single_peak_score_min)
        args.profile_key = str(preset_params.chip_factor_profile_key or args.preset)
    elif not str(args.profile_key or "").strip():
        args.profile_key = (
            "custom_sig{sig:.3f}_sec{sec:.3f}_dom{dom:.3f}_band{band:.3f}_score{score:.3f}_rows{rows}"
        ).format(
            sig=float(args.chip_peak_significant_ratio),
            sec=float(args.chip_peak_secondary_ratio_max),
            dom=float(args.chip_peak_dominance_min),
            band=float(args.chip_peak_band_pct),
            score=float(args.chip_single_peak_score_min),
            rows=int(args.chip_dist_min_rows),
        ).replace(".", "p")

    cfg = ConfigManager()
    db = DatabaseManager(cfg)
    _ensure_output_table(db)

    db_path = db.db_path
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute(
        """
        SELECT ts_code, trade_date, price, weight
        FROM stock_chip_dist
        WHERE trade_date >= ? AND trade_date <= ?
        ORDER BY ts_code ASC, trade_date ASC, price ASC
        """,
        (args.start_date, args.end_date),
    )

    upsert_sql = """
        INSERT OR REPLACE INTO stock_chip_dist_factor_profile (
            ts_code, trade_date, profile_key, chip_peak_count_sig, chip_primary_peak_weight,
            chip_secondary_peak_ratio, chip_peak_dominance, chip_main_band_weight,
            chip_dist_points, single_peak_dense_score, chip_single_peak_dense, create_time
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """

    cur_ts: Optional[str] = None
    cur_td: Optional[str] = None
    px_buf: List[float] = []
    wt_buf: List[float] = []
    upsert_params: List[Tuple] = []
    group_count = 0
    row_count = 0

    def flush_group() -> None:
        nonlocal cur_ts, cur_td, px_buf, wt_buf, group_count
        if not cur_ts or not cur_td or not px_buf:
            return
        row = _calc_factor_row(
            ts_code=cur_ts,
            trade_date=cur_td,
            prices=np.array(px_buf, dtype=float),
            weights=np.array(wt_buf, dtype=float),
            significant_ratio=float(args.chip_peak_significant_ratio),
            secondary_ratio_max=float(args.chip_peak_secondary_ratio_max),
            dominance_min=float(args.chip_peak_dominance_min),
            band_pct=float(args.chip_peak_band_pct),
            single_peak_score_min=float(args.chip_single_peak_score_min),
            min_rows=int(args.chip_dist_min_rows),
        )
        if row:
            upsert_params.append((row[0], row[1], str(args.profile_key), *row[2:]))
        group_count += 1
        px_buf = []
        wt_buf = []

    try:
        print("=" * 70)
        print("Build stock_chip_dist_factor")
        print("=" * 70)
        print(f"window={args.start_date}..{args.end_date}")
        print(f"profile_key={args.profile_key} preset={args.preset}")
        print(f"db={db_path}")

        while True:
            rows = cur.fetchmany(max(int(args.chunk_size), 10000))
            if not rows:
                break
            for r in rows:
                row_count += 1
                ts = str(r["ts_code"])
                td = str(r["trade_date"])
                if cur_ts is None:
                    cur_ts, cur_td = ts, td
                if ts != cur_ts or td != cur_td:
                    flush_group()
                    cur_ts, cur_td = ts, td
                px_buf.append(float(r["price"]))
                wt_buf.append(float(r["weight"]))

                if len(upsert_params) >= max(int(args.flush_groups), 100):
                    conn.executemany(upsert_sql, upsert_params)
                    conn.commit()
                    print(f"progress rows={row_count} groups={group_count} upsert={len(upsert_params)}")
                    upsert_params = []

        flush_group()
        if upsert_params:
            conn.executemany(upsert_sql, upsert_params)
            conn.commit()
            print(f"final flush rows={row_count} groups={group_count} upsert={len(upsert_params)}")

        cnt = db.query(
            """
            SELECT COUNT(*) c
            FROM stock_chip_dist_factor_profile
            WHERE profile_key = ?
              AND trade_date>=? AND trade_date<=?
            """,
            (str(args.profile_key), args.start_date, args.end_date),
        )[0]["c"]
        print("-" * 70)
        print(f"done row_scan={row_count} group_done={group_count} factor_rows_in_window={cnt}")
    finally:
        try:
            cur.close()
        except Exception:
            pass
        conn.close()


if __name__ == "__main__":
    main()
