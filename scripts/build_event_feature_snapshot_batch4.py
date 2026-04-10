# -*- coding: utf-8 -*-
"""
Build batch4 chip peak-structure enhancement features.

Strict constraints:
- only from stock_chip_dist_factor_profile
- fixed profile_key = tradeable_v3_research
- no fallback to legacy factor table
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import List

import numpy as np
import pandas as pd


PROFILE_KEY = "tradeable_v3_research"


def _research_dir() -> Path:
    return Path("data/research/strong_start_full")


def _db_path() -> Path:
    return Path("data/database/quant_system.db")


def _append_qc_note(base_note: pd.Series, add_note: pd.Series) -> pd.Series:
    out = []
    for old, add in zip(base_note.fillna("").astype(str), add_note.fillna("").astype(str)):
        old_clean = "" if old in ("", "ok", "nan", "None") else old
        add_clean = "" if add in ("", "ok", "nan", "None") else add
        if old_clean and add_clean:
            out.append(f"{old_clean};{add_clean}")
        elif old_clean:
            out.append(old_clean)
        elif add_clean:
            out.append(add_clean)
        else:
            out.append("ok")
    return pd.Series(out)


def _load_profile_rows(conn: sqlite3.Connection, start_date: str, end_date: str, profile_key: str) -> pd.DataFrame:
    sql = """
        SELECT
            ts_code,
            trade_date,
            profile_key,
            chip_peak_count_sig,
            chip_secondary_peak_ratio,
            chip_peak_dominance,
            single_peak_dense_score
        FROM stock_chip_dist_factor_profile
        WHERE trade_date >= ? AND trade_date <= ?
          AND profile_key = ?
        ORDER BY ts_code ASC, trade_date ASC
    """
    df = pd.read_sql_query(sql, conn, params=(start_date, end_date, profile_key))
    if df.empty:
        return df
    for c in [
        "chip_peak_count_sig",
        "chip_secondary_peak_ratio",
        "chip_peak_dominance",
        "single_peak_dense_score",
    ]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


def _load_profile_presence_all_keys(conn: sqlite3.Connection, start_date: str, end_date: str) -> pd.DataFrame:
    sql = """
        SELECT
            ts_code,
            trade_date,
            MAX(CASE WHEN profile_key = ? THEN 1 ELSE 0 END) AS has_target_key,
            COUNT(*) AS profile_rows_any_key
        FROM stock_chip_dist_factor_profile
        WHERE trade_date >= ? AND trade_date <= ?
        GROUP BY ts_code, trade_date
    """
    df = pd.read_sql_query(sql, conn, params=(PROFILE_KEY, start_date, end_date))
    return df


def main() -> None:
    parser = argparse.ArgumentParser(description="Build batch4 chip-profile features.")
    parser.add_argument("--research-dir", type=str, default=str(_research_dir()))
    parser.add_argument("--batch3-patch1-input", type=str, default="event_feature_snapshot_batch3_patch1.parquet")
    parser.add_argument("--ac-main", type=str, default="ac_main_research_set.parquet")
    parser.add_argument("--output", type=str, default="event_feature_snapshot_batch4.parquet")
    parser.add_argument("--profile-key", type=str, default=PROFILE_KEY)
    parser.add_argument("--coverage-threshold", type=float, default=0.95)
    args = parser.parse_args()

    if args.profile_key != PROFILE_KEY:
        raise ValueError(f"profile_key must be fixed to {PROFILE_KEY}")

    root = Path(args.research_dir)
    in_path = root / args.batch3_patch1_input
    ac_path = root / args.ac_main
    out_path = root / args.output
    if not in_path.exists():
        raise FileNotFoundError(f"batch3 patch1 input not found: {in_path}")
    if not ac_path.exists():
        raise FileNotFoundError(f"ac_main not found: {ac_path}")

    base = pd.read_parquet(in_path).sort_values(["trade_date", "ts_code"]).reset_index(drop=True)
    ac = pd.read_parquet(ac_path).sort_values(["trade_date", "ts_code"]).reset_index(drop=True)
    base["trade_date"] = base["trade_date"].astype(str)
    ac["trade_date"] = ac["trade_date"].astype(str)

    start_date = str(base["trade_date"].min())
    end_date = str(base["trade_date"].max())

    conn = sqlite3.connect(_db_path(), timeout=15)
    try:
        profile = _load_profile_rows(conn, start_date, end_date, args.profile_key)
        presence = _load_profile_presence_all_keys(conn, start_date, end_date)
    finally:
        conn.close()

    # profile coverage audit before build
    profile_key_cols = [
        "chip_peak_count_sig",
        "chip_secondary_peak_ratio",
        "chip_peak_dominance",
        "single_peak_dense_score",
    ]
    raw_null = {
        c: int(profile[c].isna().sum()) if (not profile.empty and c in profile.columns) else None
        for c in profile_key_cols
    }

    if profile.empty:
        raise ValueError(f"No profile rows found for key={args.profile_key} in window {start_date}..{end_date}")

    prof = profile.rename(
        columns={
            "chip_peak_count_sig": "f_chip_peak_count_sig",
            "chip_secondary_peak_ratio": "f_chip_secondary_peak_ratio",
            "chip_peak_dominance": "f_chip_peak_dominance",
            "single_peak_dense_score": "f_chip_single_peak_score",
        }
    )[
        [
            "ts_code",
            "trade_date",
            "f_chip_peak_count_sig",
            "f_chip_secondary_peak_ratio",
            "f_chip_peak_dominance",
            "f_chip_single_peak_score",
        ]
    ].copy()
    prof["trade_date"] = prof["trade_date"].astype(str)
    prof = prof.drop_duplicates(subset=["ts_code", "trade_date"], keep="last")

    merged = base.merge(prof, on=["ts_code", "trade_date"], how="left")
    merged = merged.merge(presence, on=["ts_code", "trade_date"], how="left")
    merged["has_target_key"] = merged["has_target_key"].fillna(0).astype(int)
    merged["profile_rows_any_key"] = merged["profile_rows_any_key"].fillna(0).astype(int)

    # QC flags
    profile_missing = merged["has_target_key"].eq(0) & merged["profile_rows_any_key"].eq(0)
    key_mismatch = merged["has_target_key"].eq(0) & merged["profile_rows_any_key"].gt(0)

    # value range checks (keep values, only QC-tag)
    value_oob = (
        merged["f_chip_peak_count_sig"].lt(0)
        | merged["f_chip_secondary_peak_ratio"].lt(0)
        | merged["f_chip_secondary_peak_ratio"].gt(5)
        | merged["f_chip_peak_dominance"].lt(0)
        | merged["f_chip_peak_dominance"].gt(1.5)
        | merged["f_chip_single_peak_score"].lt(0)
        | merged["f_chip_single_peak_score"].gt(1.5)
    )
    value_oob = value_oob.fillna(False)

    coverage_rate = float(
        ac.merge(
            merged[["ts_code", "trade_date", "has_target_key"]],
            on=["ts_code", "trade_date"],
            how="left",
        )["has_target_key"].fillna(0).eq(1).mean()
    )
    coverage_low = coverage_rate < float(args.coverage_threshold)

    add_note = np.select(
        [
            profile_missing,
            key_mismatch,
            value_oob,
            (profile_missing | key_mismatch) & coverage_low,
        ],
        [
            "chip_profile_missing",
            "chip_profile_key_mismatch",
            "chip_profile_value_out_of_range",
            "chip_profile_coverage_low",
        ],
        default="ok",
    )
    merged["qc_note"] = _append_qc_note(merged["qc_note"], pd.Series(add_note))

    # refresh readiness
    feature_cols = [c for c in merged.columns if c.startswith("f_")]
    merged["missing_ratio"] = merged[feature_cols].isna().mean(axis=1)
    merged["feature_ready_flag"] = (
        merged["source_coverage_flag"].fillna(0).astype(int).eq(1)
        & merged["missing_ratio"].le(0.15)
    ).astype(int)
    merged["data_version"] = "pending_batch4"
    merged["feature_spec_version"] = "fs_v1_batch4"

    merged = merged.drop(columns=["has_target_key", "profile_rows_any_key"], errors="ignore")
    merged = merged.sort_values(["trade_date", "ts_code"]).reset_index(drop=True)
    merged.to_parquet(out_path, index=False)

    # audit/report files
    fields_path = root / "event_feature_snapshot_batch4_fields.txt"
    fields_path.write_text("\n".join(merged.columns.tolist()), encoding="utf-8")

    peak_cols = [
        "f_chip_peak_count_sig",
        "f_chip_secondary_peak_ratio",
        "f_chip_peak_dominance",
        "f_chip_single_peak_score",
    ]
    peak_cov = pd.DataFrame(
        {
            "feature": peak_cols,
            "non_null_rate": [float(merged[c].notna().mean()) for c in peak_cols],
            "null_count": [int(merged[c].isna().sum()) for c in peak_cols],
        }
    )
    peak_cov_path = root / "event_feature_snapshot_batch4_peak_coverage.csv"
    peak_cov.to_csv(peak_cov_path, index=False, encoding="utf-8-sig")

    qc_sum = merged["qc_note"].value_counts(dropna=False).rename_axis("qc_note").reset_index(name="count")
    qc_path = root / "event_feature_snapshot_batch4_qc_summary.csv"
    qc_sum.to_csv(qc_path, index=False, encoding="utf-8-sig")

    forbidden_patterns = ["_fwd_", "entry_", "max_favorable_excursion", "max_adverse_excursion", "structure_break"]
    forbidden_cols = [c for c in merged.columns if any(p in c for p in forbidden_patterns)]

    # A/C missing imbalance for new peak fields
    tmp = merged.copy()
    tmp["peak_missing_any"] = tmp[peak_cols].isna().any(axis=1)
    miss_by_label = tmp.groupby("label_abc")["peak_missing_any"].mean().reset_index(name="missing_rate")
    miss_label_path = root / "event_feature_snapshot_batch4_peak_missing_by_label.csv"
    miss_by_label.to_csv(miss_label_path, index=False, encoding="utf-8-sig")

    quality = {
        "profile_key_frozen": args.profile_key,
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
        "profile_coverage_rate": coverage_rate,
        "profile_missing_events": int(profile_missing.sum()),
        "profile_key_mismatch_events": int(key_mismatch.sum()),
        "profile_coverage_low_flag": bool(coverage_low),
        "peak_raw_null": raw_null,
        "peak_value_out_of_range_count": int(value_oob.sum()),
        "forbidden_column_count": int(len(forbidden_cols)),
        "forbidden_columns": forbidden_cols,
        "feature_ready_rate": float(merged["feature_ready_flag"].mean()),
    }
    quality_path = root / "event_feature_snapshot_batch4_quality_report.json"
    quality_path.write_text(json.dumps(quality, ensure_ascii=False, indent=2), encoding="utf-8")

    ready_cmp = {
        "ready_rate_batch3_patch1": float(base["feature_ready_flag"].mean()),
        "ready_rate_batch4": float(merged["feature_ready_flag"].mean()),
        "ready_count_batch3_patch1": int(base["feature_ready_flag"].sum()),
        "ready_count_batch4": int(merged["feature_ready_flag"].sum()),
    }
    ready_cmp_path = root / "event_feature_snapshot_batch4_ready_compare.json"
    ready_cmp_path.write_text(json.dumps(ready_cmp, ensure_ascii=False, indent=2), encoding="utf-8")

    profile_audit = {
        "profile_key": args.profile_key,
        "window": {"start_date": start_date, "end_date": end_date},
        "coverage_rate": coverage_rate,
        "missing_events": int(profile_missing.sum()),
        "key_mismatch_events": int(key_mismatch.sum()),
        "raw_null": raw_null,
        "value_out_of_range_count": int(value_oob.sum()),
    }
    audit_path = root / "event_feature_snapshot_batch4_profile_audit.json"
    audit_path.write_text(json.dumps(profile_audit, ensure_ascii=False, indent=2), encoding="utf-8")

    print("=" * 70)
    print("build batch4 done")
    print("=" * 70)
    print(f"input={in_path}")
    print(f"output={out_path}")
    print(f"rows={len(merged)} cols={merged.shape[1]}")
    print(f"profile_key={args.profile_key}")
    print(f"profile_coverage_rate={coverage_rate:.6f}")
    print(f"profile_missing_events={int(profile_missing.sum())}")
    print(f"profile_key_mismatch_events={int(key_mismatch.sum())}")
    print(f"fields={fields_path}")
    print(f"peak_coverage={peak_cov_path}")
    print(f"qc_summary={qc_path}")
    print(f"quality={quality_path}")
    print(f"profile_audit={audit_path}")
    print(f"ready_compare={ready_cmp_path}")


if __name__ == "__main__":
    main()
