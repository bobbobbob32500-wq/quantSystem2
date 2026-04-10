# -*- coding: utf-8 -*-
"""
Build batch3 basic chip features on top of batch2 snapshot.

Allowed in this script:
- f_chip_concentration
- f_chip_stability_std10
- f_chip_low_position120
- f_chip_winner_rate

Forbidden in this script:
- any peak/profile enhancement features.
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


def _db_path() -> Path:
    return Path("data/database/quant_system.db")


def _research_dir() -> Path:
    return Path("data/research/strong_start_full")


def _safe_ratio(num: pd.Series, den: pd.Series) -> pd.Series:
    return num / den.replace(0, np.nan)


def _build_mainboard_condition(alias: str = "ts_code") -> str:
    sh_like = " OR ".join(f"{alias} LIKE '{p}%.SH'" for p in MAINBOARD_SH_PREFIXES)
    sz_like = " OR ".join(f"{alias} LIKE '{p}%.SZ'" for p in MAINBOARD_SZ_PREFIXES)
    return f"({sh_like} OR {sz_like})"


def _load_chip_perf(conn: sqlite3.Connection, start_date: str, end_date: str) -> pd.DataFrame:
    cond = _build_mainboard_condition("ts_code")
    sql = f"""
        SELECT
            ts_code, trade_date,
            cost_5pct, cost_15pct, cost_50pct, cost_85pct, cost_95pct,
            winner_rate
        FROM stock_chip_perf
        WHERE trade_date >= ? AND trade_date <= ?
          AND ({cond})
        ORDER BY ts_code ASC, trade_date ASC
    """
    df = pd.read_sql_query(sql, conn, params=(start_date, end_date))
    if df.empty:
        return df
    for c in ["cost_5pct", "cost_15pct", "cost_50pct", "cost_85pct", "cost_95pct", "winner_rate"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["trade_date"] = pd.to_datetime(df["trade_date"].astype(str), format="%Y%m%d", errors="coerce")
    df = df.dropna(subset=["ts_code", "trade_date"]).copy()
    df = df.sort_values(["ts_code", "trade_date"]).reset_index(drop=True)
    return df


def _load_daily_range120(conn: sqlite3.Connection, start_date: str, end_date: str) -> pd.DataFrame:
    cond = _build_mainboard_condition("ts_code")
    sql = f"""
        SELECT ts_code, trade_date, high, low
        FROM stock_daily
        WHERE trade_date >= ? AND trade_date <= ?
          AND ({cond})
        ORDER BY ts_code ASC, trade_date ASC
    """
    df = pd.read_sql_query(sql, conn, params=(start_date, end_date))
    if df.empty:
        return df
    df["high"] = pd.to_numeric(df["high"], errors="coerce")
    df["low"] = pd.to_numeric(df["low"], errors="coerce")
    df["trade_date"] = pd.to_datetime(df["trade_date"].astype(str), format="%Y%m%d", errors="coerce")
    df = df.dropna(subset=["ts_code", "trade_date", "high", "low"]).copy()
    df = df.sort_values(["ts_code", "trade_date"]).reset_index(drop=True)
    g = df.groupby("ts_code", group_keys=False)
    df["range_low_120"] = g["low"].transform(lambda s: s.rolling(120, min_periods=120).min())
    df["range_high_120"] = g["high"].transform(lambda s: s.rolling(120, min_periods=120).max())
    return df[["ts_code", "trade_date", "range_low_120", "range_high_120"]]


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


def _build_chip_features(chip: pd.DataFrame, daily_range: pd.DataFrame) -> pd.DataFrame:
    if chip.empty:
        return pd.DataFrame()

    out = chip.copy()
    out["f_chip_concentration"] = _safe_ratio(
        out["cost_95pct"] - out["cost_5pct"],
        out["cost_95pct"] + out["cost_5pct"],
    )
    # Freeze center definition at cost_50pct for robust and interpretable median-cost center.
    out["chip_center"] = out["cost_50pct"]

    g = out.groupby("ts_code", group_keys=False)
    out["f_chip_stability_std10"] = g["f_chip_concentration"].transform(
        lambda s: s.rolling(10, min_periods=10).std()
    )
    out["f_chip_winner_rate"] = out["winner_rate"]
    out = out.merge(daily_range, on=["ts_code", "trade_date"], how="left")
    out["f_chip_low_position120"] = _safe_ratio(
        out["chip_center"] - out["range_low_120"],
        out["range_high_120"] - out["range_low_120"],
    )
    out["trade_date"] = out["trade_date"].dt.strftime("%Y%m%d")
    keep = [
        "ts_code",
        "trade_date",
        "f_chip_concentration",
        "f_chip_stability_std10",
        "f_chip_low_position120",
        "f_chip_winner_rate",
        "cost_5pct",
        "cost_50pct",
        "cost_95pct",
        "winner_rate",
        "range_low_120",
        "range_high_120",
    ]
    return out[keep]


def main() -> None:
    parser = argparse.ArgumentParser(description="Build batch3 basic chip features.")
    parser.add_argument("--research-dir", type=str, default=str(_research_dir()))
    parser.add_argument("--batch2-input", type=str, default="event_feature_snapshot_batch2.parquet")
    parser.add_argument("--ac-main", type=str, default="ac_main_research_set.parquet")
    parser.add_argument("--output", type=str, default="event_feature_snapshot_batch3.parquet")
    args = parser.parse_args()

    root = Path(args.research_dir)
    in_path = root / args.batch2_input
    ac_path = root / args.ac_main
    out_path = root / args.output
    if not in_path.exists():
        raise FileNotFoundError(f"batch2 input not found: {in_path}")
    if not ac_path.exists():
        raise FileNotFoundError(f"ac_main not found: {ac_path}")

    base = pd.read_parquet(in_path).sort_values(["trade_date", "ts_code"]).reset_index(drop=True)
    ac = pd.read_parquet(ac_path).sort_values(["trade_date", "ts_code"]).reset_index(drop=True)
    base["trade_date"] = base["trade_date"].astype(str)
    ac["trade_date"] = ac["trade_date"].astype(str)

    min_dt = datetime.strptime(base["trade_date"].min(), "%Y%m%d")
    max_dt = datetime.strptime(base["trade_date"].max(), "%Y%m%d")
    start_date = (min_dt - timedelta(days=420)).strftime("%Y%m%d")
    end_date = max_dt.strftime("%Y%m%d")

    conn = sqlite3.connect(_db_path(), timeout=10)
    try:
        chip = _load_chip_perf(conn, start_date, end_date)
        daily_range = _load_daily_range120(conn, start_date, end_date)
    finally:
        conn.close()
    if chip.empty:
        raise ValueError("stock_chip_perf empty for batch3 window")
    if daily_range.empty:
        raise ValueError("stock_daily range panel empty for batch3 window")

    chip_feat = _build_chip_features(chip, daily_range)
    merged = base.merge(chip_feat, on=["ts_code", "trade_date"], how="left")

    chip_cols = [
        "f_chip_concentration",
        "f_chip_stability_std10",
        "f_chip_low_position120",
        "f_chip_winner_rate",
    ]

    # Coverage & QC enrichment
    chip_missing = merged["f_chip_concentration"].isna() | merged["f_chip_winner_rate"].isna()
    chip_win10_ins = merged["f_chip_stability_std10"].isna()
    chip_win120_ins = merged["f_chip_low_position120"].isna()
    chip_out_range = (
        merged["f_chip_concentration"].lt(0)
        | merged["f_chip_concentration"].gt(1)
        | merged["f_chip_winner_rate"].lt(0)
        | merged["f_chip_winner_rate"].gt(1)
        | merged["f_chip_low_position120"].lt(-0.05)
        | merged["f_chip_low_position120"].gt(1.05)
    )

    add_note = np.select(
        [chip_missing, chip_win10_ins, chip_win120_ins, chip_out_range],
        ["chip_missing", "chip_window_insufficient_10", "chip_window_insufficient_120", "chip_value_out_of_range"],
        default="ok",
    )
    merged["qc_note"] = _append_qc_note(merged["qc_note"], pd.Series(add_note))

    feature_cols = [c for c in merged.columns if c.startswith("f_")]
    merged["missing_ratio"] = merged[feature_cols].isna().mean(axis=1)
    merged["feature_ready_flag"] = (
        merged["source_coverage_flag"].fillna(0).astype(int).eq(1)
        & merged["missing_ratio"].le(0.15)
    ).astype(int)
    merged["data_version"] = "pending_batch3"
    merged["feature_spec_version"] = "fs_v1_batch3"
    merged = merged.sort_values(["trade_date", "ts_code"]).reset_index(drop=True)
    merged.to_parquet(out_path, index=False)

    # Audits
    align = ac.merge(
        chip_feat[["ts_code", "trade_date"]],
        on=["ts_code", "trade_date"],
        how="left",
        indicator=True,
    )
    chip_align_rate = float((align["_merge"] == "both").mean())
    missing_events = align.loc[align["_merge"] != "both", ["ts_code", "trade_date"]].copy()
    missing_top_date = (
        missing_events["trade_date"].value_counts().head(20).rename_axis("trade_date").reset_index(name="missing_count")
        if not missing_events.empty
        else pd.DataFrame(columns=["trade_date", "missing_count"])
    )
    missing_top_code = (
        missing_events["ts_code"].value_counts().head(20).rename_axis("ts_code").reset_index(name="missing_count")
        if not missing_events.empty
        else pd.DataFrame(columns=["ts_code", "missing_count"])
    )
    miss_date_path = root / "event_feature_snapshot_batch3_chip_missing_by_date.csv"
    miss_code_path = root / "event_feature_snapshot_batch3_chip_missing_by_code.csv"
    missing_top_date.to_csv(miss_date_path, index=False, encoding="utf-8-sig")
    missing_top_code.to_csv(miss_code_path, index=False, encoding="utf-8-sig")

    chip_raw_null = {
        "cost_5pct_null": int(chip["cost_5pct"].isna().sum()),
        "cost_95pct_null": int(chip["cost_95pct"].isna().sum()),
        "winner_rate_null": int(chip["winner_rate"].isna().sum()),
    }

    # A/C imbalance check for chip missing
    ac_with = ac.merge(
        merged[["ts_code", "trade_date", "label_abc", *chip_cols]],
        on=["ts_code", "trade_date", "label_abc"],
        how="left",
    )
    ac_with["chip_missing_any"] = ac_with[chip_cols].isna().any(axis=1)
    chip_missing_by_label = (
        ac_with.groupby("label_abc")["chip_missing_any"].mean().rename("missing_rate").reset_index()
    )
    chip_missing_by_label_path = root / "event_feature_snapshot_batch3_chip_missing_by_label.csv"
    chip_missing_by_label.to_csv(chip_missing_by_label_path, index=False, encoding="utf-8-sig")

    # field / coverage files
    fields_path = root / "event_feature_snapshot_batch3_fields.txt"
    fields_path.write_text("\n".join(merged.columns.tolist()), encoding="utf-8")
    cov = pd.DataFrame(
        {
            "feature": feature_cols,
            "non_null_rate": [float(merged[c].notna().mean()) for c in feature_cols],
            "null_count": [int(merged[c].isna().sum()) for c in feature_cols],
        }
    ).sort_values("non_null_rate", ascending=True)
    cov_path = root / "event_feature_snapshot_batch3_coverage.csv"
    cov.to_csv(cov_path, index=False, encoding="utf-8-sig")
    chip_cov = pd.DataFrame(
        {
            "feature": chip_cols,
            "non_null_rate": [float(merged[c].notna().mean()) for c in chip_cols],
            "null_count": [int(merged[c].isna().sum()) for c in chip_cols],
        }
    )
    chip_cov_path = root / "event_feature_snapshot_batch3_chip_coverage.csv"
    chip_cov.to_csv(chip_cov_path, index=False, encoding="utf-8-sig")
    qc_sum = merged["qc_note"].value_counts(dropna=False).rename_axis("qc_note").reset_index(name="count")
    qc_path = root / "event_feature_snapshot_batch3_qc_summary.csv"
    qc_sum.to_csv(qc_path, index=False, encoding="utf-8-sig")

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
        "chip_align_rate": chip_align_rate,
        "chip_missing_events": int((align["_merge"] != "both").sum()),
        "chip_raw_null": chip_raw_null,
        "chip_value_out_of_range_count": int(chip_out_range.fillna(False).sum()),
    }
    quality_path = root / "event_feature_snapshot_batch3_quality_report.json"
    quality_path.write_text(json.dumps(quality, ensure_ascii=False, indent=2), encoding="utf-8")

    # batch2 to batch3 ready compare
    ready_cmp = {
        "ready_rate_batch2": float(base["feature_ready_flag"].mean()),
        "ready_rate_batch3": float(merged["feature_ready_flag"].mean()),
        "ready_count_batch2": int(base["feature_ready_flag"].sum()),
        "ready_count_batch3": int(merged["feature_ready_flag"].sum()),
    }
    ready_cmp_path = root / "event_feature_snapshot_batch3_ready_compare.json"
    ready_cmp_path.write_text(json.dumps(ready_cmp, ensure_ascii=False, indent=2), encoding="utf-8")

    # chip audit summary
    chip_audit = {
        "chip_align_rate": chip_align_rate,
        "missing_chip_events": int((align["_merge"] != "both").sum()),
        "missing_by_date_file": str(miss_date_path),
        "missing_by_code_file": str(miss_code_path),
        "chip_raw_null": chip_raw_null,
        "chip_missing_by_label_file": str(chip_missing_by_label_path),
        "center_definition": "cost_50pct",
        "low_position_formula": "(chip_center - range_low_120) / (range_high_120 - range_low_120)",
    }
    chip_audit_path = root / "event_feature_snapshot_batch3_chip_audit.json"
    chip_audit_path.write_text(json.dumps(chip_audit, ensure_ascii=False, indent=2), encoding="utf-8")

    print("=" * 70)
    print("build batch3 done")
    print("=" * 70)
    print(f"input={in_path}")
    print(f"output={out_path}")
    print(f"rows={len(merged)} cols={merged.shape[1]}")
    print(f"ready_rate_batch3={quality['feature_ready_rate']:.6f}")
    print(f"chip_align_rate={chip_align_rate:.6f}")
    print(f"chip_missing_events={quality['chip_missing_events']}")
    print(f"fields={fields_path}")
    print(f"coverage={cov_path}")
    print(f"chip_coverage={chip_cov_path}")
    print(f"qc_summary={qc_path}")
    print(f"quality={quality_path}")
    print(f"chip_audit={chip_audit_path}")
    print(f"ready_compare={ready_cmp_path}")


if __name__ == "__main__":
    main()
