# -*- coding: utf-8 -*-
"""
Patch Batch1 snapshot:
1) Repair f_k_pct_chg missing via T close/prev close fallback.
2) Freeze return-unit to decimal.
3) Refine source_coverage_flag + qc_note categories.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd


INDEX_CODE = "000001.SH"
MAINBOARD_SH_PREFIXES: Tuple[str, ...] = ("600", "601", "603", "605")
MAINBOARD_SZ_PREFIXES: Tuple[str, ...] = ("000", "001", "002", "003")


def _safe_ratio(num: pd.Series, den: pd.Series) -> pd.Series:
    return num / den.replace(0, np.nan)


def _db_path() -> Path:
    return Path("data/database/quant_system.db")


def _research_dir() -> Path:
    return Path("data/research/strong_start_full")


def _build_mainboard_condition(alias: str = "ts_code") -> str:
    sh_like = " OR ".join(f"{alias} LIKE '{p}%.SH'" for p in MAINBOARD_SH_PREFIXES)
    sz_like = " OR ".join(f"{alias} LIKE '{p}%.SZ'" for p in MAINBOARD_SZ_PREFIXES)
    return f"({sh_like} OR {sz_like})"


def _load_daily_panel(conn: sqlite3.Connection, start_date: str, end_date: str) -> pd.DataFrame:
    cond = _build_mainboard_condition("ts_code")
    sql = f"""
        SELECT ts_code, trade_date, close, pct_chg
        FROM stock_daily
        WHERE trade_date >= ? AND trade_date <= ?
          AND (({cond}) OR ts_code = ?)
        ORDER BY ts_code ASC, trade_date ASC
    """
    df = pd.read_sql_query(sql, conn, params=(start_date, end_date, INDEX_CODE))
    if df.empty:
        return df
    df["close"] = pd.to_numeric(df["close"], errors="coerce")
    df["pct_chg"] = pd.to_numeric(df["pct_chg"], errors="coerce")
    df["trade_date"] = pd.to_datetime(df["trade_date"].astype(str), format="%Y%m%d", errors="coerce")
    df = df.dropna(subset=["ts_code", "trade_date", "close"]).copy()
    df = df.sort_values(["ts_code", "trade_date"]).reset_index(drop=True)
    return df


def _feature_columns(df: pd.DataFrame) -> List[str]:
    return [c for c in df.columns if c.startswith("f_")]


def _classify_qc_row(
    join_missing: bool,
    index_missing: bool,
    win20_insufficient: bool,
    win60_insufficient: bool,
    pct_chg_missing_source: bool,
) -> str:
    notes: List[str] = []
    if join_missing:
        notes.append("join_missing")
    if index_missing:
        notes.append("index_missing")
    if win20_insufficient:
        notes.append("window_insufficient_20")
    if win60_insufficient:
        notes.append("window_insufficient_60")
    if pct_chg_missing_source:
        notes.append("pct_chg_missing_source")
    return ";".join(notes) if notes else "ok"


def main() -> None:
    parser = argparse.ArgumentParser(description="Patch batch1 feature snapshot.")
    parser.add_argument(
        "--research-dir",
        type=str,
        default=str(_research_dir()),
    )
    parser.add_argument(
        "--batch1-input",
        type=str,
        default="event_feature_snapshot_batch1.parquet",
    )
    parser.add_argument(
        "--ac-main",
        type=str,
        default="ac_main_research_set.parquet",
    )
    parser.add_argument(
        "--output",
        type=str,
        default="event_feature_snapshot_batch1_patch1.parquet",
    )
    args = parser.parse_args()

    root = Path(args.research_dir)
    batch1_path = root / args.batch1_input
    ac_path = root / args.ac_main
    out_path = root / args.output

    if not batch1_path.exists():
        raise FileNotFoundError(f"batch1 input not found: {batch1_path}")
    if not ac_path.exists():
        raise FileNotFoundError(f"ac_main not found: {ac_path}")

    old = pd.read_parquet(batch1_path)
    ac = pd.read_parquet(ac_path)
    old = old.sort_values(["trade_date", "ts_code"]).reset_index(drop=True)
    ac = ac.sort_values(["trade_date", "ts_code"]).reset_index(drop=True)
    old["trade_date"] = old["trade_date"].astype(str)
    ac["trade_date"] = ac["trade_date"].astype(str)

    min_dt = datetime.strptime(ac["trade_date"].min(), "%Y%m%d")
    max_dt = datetime.strptime(ac["trade_date"].max(), "%Y%m%d")
    start_date = (min_dt - timedelta(days=420)).strftime("%Y%m%d")
    end_date = max_dt.strftime("%Y%m%d")

    conn = sqlite3.connect(_db_path(), timeout=10)
    try:
        panel = _load_daily_panel(conn, start_date, end_date)
    finally:
        conn.close()
    if panel.empty:
        raise ValueError("daily panel empty while patching batch1")

    stock = panel[panel["ts_code"] != INDEX_CODE].copy()
    idx = panel[panel["ts_code"] == INDEX_CODE][["trade_date", "close"]].copy()
    idx = idx.sort_values("trade_date").reset_index(drop=True)
    idx["idx_ret20"] = idx["close"] / idx["close"].shift(20) - 1.0
    idx["idx_ret60"] = idx["close"] / idx["close"].shift(60) - 1.0
    idx = idx[["trade_date", "idx_ret20", "idx_ret60"]]

    g = stock.groupby("ts_code", group_keys=False)
    stock["prev_close"] = g["close"].shift(1)
    stock["ret1_calc"] = stock["close"] / stock["prev_close"] - 1.0
    stock["has_hist_20"] = g["close"].shift(20).notna()
    stock["has_hist_60"] = g["close"].shift(60).notna()
    stock["pct_chg_missing_source"] = stock["pct_chg"].isna()

    pct_source = stock["pct_chg"].copy()
    use_percent_point = bool(pct_source.dropna().abs().quantile(0.95) > 1.0) if pct_source.notna().any() else True
    if use_percent_point:
        pct_source_decimal = pct_source / 100.0
    else:
        pct_source_decimal = pct_source
    stock["f_k_pct_chg_recalc"] = pct_source_decimal.fillna(stock["ret1_calc"])

    stock = stock.merge(idx, on="trade_date", how="left")
    stock["index_missing"] = stock["idx_ret20"].isna() | stock["idx_ret60"].isna()

    patch_cols = [
        "ts_code",
        "trade_date",
        "f_k_pct_chg_recalc",
        "pct_chg_missing_source",
        "has_hist_20",
        "has_hist_60",
        "index_missing",
    ]
    patch = stock[patch_cols].copy()
    patch["trade_date"] = patch["trade_date"].dt.strftime("%Y%m%d")

    old_value_cols = [c for c in old.columns if c not in ac.columns]
    merged = ac.merge(
        old[["ts_code", "trade_date", *old_value_cols]],
        on=["ts_code", "trade_date"],
        how="left",
        indicator="merge_old",
    )
    merged = merged.merge(patch, on=["ts_code", "trade_date"], how="left", indicator="merge_patch")

    # Patch f_k_pct_chg
    merged["f_k_pct_chg"] = merged["f_k_pct_chg_recalc"]

    feature_cols = _feature_columns(merged)

    join_missing = merged["merge_old"].ne("both") | merged["merge_patch"].ne("both")
    win20_ins = merged["has_hist_20"].ne(True)
    win60_ins = merged["has_hist_60"].ne(True)
    idx_missing = merged["index_missing"].eq(True)
    pct_missing = merged["pct_chg_missing_source"].eq(True)

    merged["source_coverage_flag"] = (~join_missing & ~idx_missing).astype(int)
    merged["missing_ratio"] = merged[feature_cols].isna().mean(axis=1)
    merged["feature_ready_flag"] = (
        merged["source_coverage_flag"].eq(1) & merged["missing_ratio"].le(0.15)
    ).astype(int)
    merged["data_version"] = "pending_patch1"
    merged["feature_spec_version"] = "fs_v1_batch1_patch1"

    merged["qc_note"] = [
        _classify_qc_row(
            bool(join_missing.iloc[i]),
            bool(idx_missing.iloc[i]),
            bool(win20_ins.iloc[i]),
            bool(win60_ins.iloc[i]),
            bool(pct_missing.iloc[i]),
        )
        for i in range(len(merged))
    ]

    drop_cols = [
        "merge_old",
        "merge_patch",
        "f_k_pct_chg_recalc",
        "pct_chg_missing_source",
        "has_hist_20",
        "has_hist_60",
        "index_missing",
    ]
    merged = merged.drop(columns=[c for c in drop_cols if c in merged.columns], errors="ignore")
    merged = merged.sort_values(["trade_date", "ts_code"]).reset_index(drop=True)
    merged.to_parquet(out_path, index=False)

    # Compare report
    old_feature_cols = _feature_columns(old)
    common_features = [c for c in old_feature_cols if c in merged.columns and c.startswith("f_")]
    compare = pd.DataFrame(
        {
            "feature": common_features,
            "non_null_rate_before": [float(old[c].notna().mean()) for c in common_features],
            "non_null_rate_after": [float(merged[c].notna().mean()) for c in common_features],
        }
    )
    compare["delta"] = compare["non_null_rate_after"] - compare["non_null_rate_before"]
    compare = compare.sort_values("delta", ascending=False)
    compare_path = root / "event_feature_snapshot_batch1_patch1_nonnull_compare.csv"
    compare.to_csv(compare_path, index=False, encoding="utf-8-sig")

    qc_before = old["qc_note"].value_counts(dropna=False).rename_axis("qc_note").reset_index(name="count_before")
    qc_after = merged["qc_note"].value_counts(dropna=False).rename_axis("qc_note").reset_index(name="count_after")
    qc_cmp = qc_before.merge(qc_after, on="qc_note", how="outer").fillna(0)
    qc_cmp["count_before"] = qc_cmp["count_before"].astype(int)
    qc_cmp["count_after"] = qc_cmp["count_after"].astype(int)
    qc_cmp["delta"] = qc_cmp["count_after"] - qc_cmp["count_before"]
    qc_cmp_path = root / "event_feature_snapshot_batch1_patch1_qc_compare.csv"
    qc_cmp.to_csv(qc_cmp_path, index=False, encoding="utf-8-sig")

    ready_cmp = {
        "ready_rate_before": float(old["feature_ready_flag"].mean()),
        "ready_rate_after": float(merged["feature_ready_flag"].mean()),
        "ready_count_before": int(old["feature_ready_flag"].sum()),
        "ready_count_after": int(merged["feature_ready_flag"].sum()),
    }
    ready_cmp_path = root / "event_feature_snapshot_batch1_patch1_ready_compare.json"
    ready_cmp_path.write_text(json.dumps(ready_cmp, ensure_ascii=False, indent=2), encoding="utf-8")

    # Unit note
    unit_note = {
        "return_unit_freeze": "all return/pct features in decimal",
        "affected_feature": "f_k_pct_chg",
        "source_pct_chg_unit_detected": "percent_point" if use_percent_point else "decimal",
        "f_k_pct_chg_formula_after_patch": "pct_chg/100 if source in percent-point else pct_chg; fallback to close(T)/close(T-1)-1 when source missing",
    }
    unit_path = root / "event_feature_snapshot_batch1_patch1_unit_note.json"
    unit_path.write_text(json.dumps(unit_note, ensure_ascii=False, indent=2), encoding="utf-8")

    # quality report
    forbidden_patterns = ["_fwd_", "entry_", "max_favorable_excursion", "max_adverse_excursion", "structure_break"]
    forbidden_cols = [c for c in merged.columns if any(p in c for p in forbidden_patterns)]
    quality = {
        "row_count": int(len(merged)),
        "pk_duplicate_count": int(merged.duplicated(["ts_code", "trade_date"]).sum()),
        "join_coverage_rate": float(
            1.0
            - (
                ac.merge(merged[["ts_code", "trade_date"]], on=["ts_code", "trade_date"], how="left", indicator=True)["_merge"]
                .ne("both")
                .sum()
                / max(len(ac), 1)
            )
        ),
        "forbidden_column_count": int(len(forbidden_cols)),
        "forbidden_columns": forbidden_cols,
        "feature_ready_rate": float(merged["feature_ready_flag"].mean()),
    }
    quality_path = root / "event_feature_snapshot_batch1_patch1_quality_report.json"
    quality_path.write_text(json.dumps(quality, ensure_ascii=False, indent=2), encoding="utf-8")

    print("=" * 70)
    print("patch batch1 done")
    print("=" * 70)
    print(f"output={out_path}")
    print(f"rows={len(merged)} cols={merged.shape[1]}")
    print(f"f_k_pct_chg_non_null_before={old['f_k_pct_chg'].notna().mean():.6f}")
    print(f"f_k_pct_chg_non_null_after={merged['f_k_pct_chg'].notna().mean():.6f}")
    print(f"ready_before={ready_cmp['ready_rate_before']:.6f}")
    print(f"ready_after={ready_cmp['ready_rate_after']:.6f}")
    print(f"compare={compare_path}")
    print(f"qc_compare={qc_cmp_path}")
    print(f"ready_compare={ready_cmp_path}")
    print(f"unit_note={unit_path}")
    print(f"quality={quality_path}")


if __name__ == "__main__":
    main()
