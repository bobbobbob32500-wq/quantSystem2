# -*- coding: utf-8 -*-
"""
Patch batch3 chip features:
- winner_rate unit/out-of-range handling
- low_position120 missing/abnormal reason split
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import List

import numpy as np
import pandas as pd


def _research_dir() -> Path:
    return Path("data/research/strong_start_full")


def _append_qc_note(base_note: pd.Series, add_note: pd.Series) -> pd.Series:
    out: List[str] = []
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


def main() -> None:
    parser = argparse.ArgumentParser(description="Patch batch3 basic chip features.")
    parser.add_argument("--research-dir", type=str, default=str(_research_dir()))
    parser.add_argument("--batch3-input", type=str, default="event_feature_snapshot_batch3.parquet")
    parser.add_argument("--output", type=str, default="event_feature_snapshot_batch3_patch1.parquet")
    args = parser.parse_args()

    root = Path(args.research_dir)
    in_path = root / args.batch3_input
    out_path = root / args.output
    if not in_path.exists():
        raise FileNotFoundError(f"batch3 input not found: {in_path}")

    old = pd.read_parquet(in_path).sort_values(["trade_date", "ts_code"]).reset_index(drop=True)
    new = old.copy()

    # ===== winner_rate patch =====
    # raw source columns persisted in batch3
    # winner_rate value may be in [0,1] or percent-point [0,100].
    raw_wr = pd.to_numeric(new["winner_rate"], errors="coerce")
    wr_before = pd.to_numeric(new["f_chip_winner_rate"], errors="coerce")
    wr_before_oob = wr_before.lt(0) | wr_before.gt(1)

    # detect percent-like rows / float epsilon overflow / dirty rows
    wr_percent_like = raw_wr.gt(2) & raw_wr.le(100)
    wr_eps_overflow = raw_wr.gt(1) & raw_wr.le(1 + 1e-8)
    wr_dirty = (raw_wr.lt(0)) | (raw_wr.gt(100)) | ((raw_wr.gt(1 + 1e-8)) & (raw_wr.le(2)))

    wr_after = raw_wr.copy()
    wr_after.loc[wr_percent_like] = wr_after.loc[wr_percent_like] / 100.0
    wr_after.loc[wr_eps_overflow] = 1.0
    wr_after.loc[wr_dirty] = np.nan
    new["f_chip_winner_rate"] = wr_after
    wr_after_oob = new["f_chip_winner_rate"].lt(0) | new["f_chip_winner_rate"].gt(1)

    # ===== low_position120 patch =====
    c50 = pd.to_numeric(new["cost_50pct"], errors="coerce")
    lo = pd.to_numeric(new["range_low_120"], errors="coerce")
    hi = pd.to_numeric(new["range_high_120"], errors="coerce")
    denom = hi - lo

    reason_window = lo.isna() | hi.isna()
    reason_denom0 = (~reason_window) & denom.abs().le(1e-9)
    reason_center = c50.isna() | c50.le(0)

    lowpos_before = pd.to_numeric(new["f_chip_low_position120"], errors="coerce")
    lowpos_before_oob = lowpos_before.lt(-0.05) | lowpos_before.gt(1.05)

    lowpos_after = (c50 - lo) / denom.replace(0, np.nan)
    lowpos_after.loc[reason_window | reason_denom0 | reason_center] = np.nan
    new["f_chip_low_position120"] = lowpos_after
    lowpos_after_oob = new["f_chip_low_position120"].lt(-0.05) | new["f_chip_low_position120"].gt(1.05)

    # ===== qc enrichment =====
    add_note = np.select(
        [
            wr_percent_like,
            wr_eps_overflow,
            wr_dirty,
            reason_window,
            reason_denom0,
            reason_center,
            lowpos_after_oob.fillna(False),
            wr_after_oob.fillna(False),
        ],
        [
            "chip_winner_rate_unit_percent",
            "chip_winner_rate_float_epsilon_clipped",
            "chip_winner_rate_out_of_range_raw",
            "chip_window_insufficient_120",
            "chip_range_denominator_near_zero",
            "chip_center_invalid",
            "chip_low_position_out_of_range",
            "chip_value_out_of_range",
        ],
        default="ok",
    )
    new["qc_note"] = _append_qc_note(new["qc_note"], pd.Series(add_note))

    # refresh readiness
    feature_cols = [c for c in new.columns if c.startswith("f_")]
    new["missing_ratio"] = new[feature_cols].isna().mean(axis=1)
    new["feature_ready_flag"] = (
        new["source_coverage_flag"].fillna(0).astype(int).eq(1)
        & new["missing_ratio"].le(0.15)
    ).astype(int)
    new["data_version"] = "pending_batch3_patch1"
    new["feature_spec_version"] = "fs_v1_batch3_patch1"

    new = new.sort_values(["trade_date", "ts_code"]).reset_index(drop=True)
    new.to_parquet(out_path, index=False)

    # ===== reports =====
    winner_summary = {
        "before": {
            "min": None if wr_before.dropna().empty else float(wr_before.min()),
            "max": None if wr_before.dropna().empty else float(wr_before.max()),
            "q01": None if wr_before.dropna().empty else float(wr_before.quantile(0.01)),
            "q50": None if wr_before.dropna().empty else float(wr_before.quantile(0.50)),
            "q99": None if wr_before.dropna().empty else float(wr_before.quantile(0.99)),
            "oob_count": int(wr_before_oob.fillna(False).sum()),
            "non_null_rate": float(wr_before.notna().mean()),
        },
        "after": {
            "min": None if new["f_chip_winner_rate"].dropna().empty else float(new["f_chip_winner_rate"].min()),
            "max": None if new["f_chip_winner_rate"].dropna().empty else float(new["f_chip_winner_rate"].max()),
            "q01": None if new["f_chip_winner_rate"].dropna().empty else float(new["f_chip_winner_rate"].quantile(0.01)),
            "q50": None if new["f_chip_winner_rate"].dropna().empty else float(new["f_chip_winner_rate"].quantile(0.50)),
            "q99": None if new["f_chip_winner_rate"].dropna().empty else float(new["f_chip_winner_rate"].quantile(0.99)),
            "oob_count": int(wr_after_oob.fillna(False).sum()),
            "non_null_rate": float(new["f_chip_winner_rate"].notna().mean()),
        },
        "unit_percent_rows": int(wr_percent_like.sum()),
        "epsilon_clip_rows": int(wr_eps_overflow.sum()),
        "dirty_rows_to_nan": int(wr_dirty.sum()),
    }
    winner_path = root / "event_feature_snapshot_batch3_patch1_winner_rate_compare.json"
    winner_path.write_text(json.dumps(winner_summary, ensure_ascii=False, indent=2), encoding="utf-8")

    # top concentration of winner outliers before patch
    winner_oob_rows = old.loc[wr_before_oob.fillna(False), ["trade_date", "ts_code", "f_chip_winner_rate"]].copy()
    winner_date = winner_oob_rows["trade_date"].value_counts().head(20).rename_axis("trade_date").reset_index(name="count")
    winner_code = winner_oob_rows["ts_code"].value_counts().head(20).rename_axis("ts_code").reset_index(name="count")
    winner_date_path = root / "event_feature_snapshot_batch3_patch1_winner_oob_by_date.csv"
    winner_code_path = root / "event_feature_snapshot_batch3_patch1_winner_oob_by_code.csv"
    winner_date.to_csv(winner_date_path, index=False, encoding="utf-8-sig")
    winner_code.to_csv(winner_code_path, index=False, encoding="utf-8-sig")

    low_summary = {
        "before": {
            "non_null_rate": float(lowpos_before.notna().mean()),
            "oob_count": int(lowpos_before_oob.fillna(False).sum()),
        },
        "after": {
            "non_null_rate": float(new["f_chip_low_position120"].notna().mean()),
            "oob_count": int(lowpos_after_oob.fillna(False).sum()),
        },
        "missing_reason_counts": {
            "chip_window_insufficient_120": int(reason_window.sum()),
            "chip_range_denominator_near_zero": int(reason_denom0.sum()),
            "chip_center_invalid": int(reason_center.sum()),
            "other_missing": int(
                new["f_chip_low_position120"].isna().sum() - (reason_window | reason_denom0 | reason_center).sum()
            ),
        },
    }
    low_path = root / "event_feature_snapshot_batch3_patch1_lowpos_compare.json"
    low_path.write_text(json.dumps(low_summary, ensure_ascii=False, indent=2), encoding="utf-8")

    ready_cmp = {
        "ready_rate_before": float(old["feature_ready_flag"].mean()),
        "ready_rate_after": float(new["feature_ready_flag"].mean()),
        "ready_count_before": int(old["feature_ready_flag"].sum()),
        "ready_count_after": int(new["feature_ready_flag"].sum()),
    }
    ready_path = root / "event_feature_snapshot_batch3_patch1_ready_compare.json"
    ready_path.write_text(json.dumps(ready_cmp, ensure_ascii=False, indent=2), encoding="utf-8")

    qc_before = old["qc_note"].value_counts(dropna=False).rename_axis("qc_note").reset_index(name="count_before")
    qc_after = new["qc_note"].value_counts(dropna=False).rename_axis("qc_note").reset_index(name="count_after")
    qc_cmp = qc_before.merge(qc_after, on="qc_note", how="outer").fillna(0)
    qc_cmp["count_before"] = qc_cmp["count_before"].astype(int)
    qc_cmp["count_after"] = qc_cmp["count_after"].astype(int)
    qc_cmp["delta"] = qc_cmp["count_after"] - qc_cmp["count_before"]
    qc_path = root / "event_feature_snapshot_batch3_patch1_qc_compare.csv"
    qc_cmp.to_csv(qc_path, index=False, encoding="utf-8-sig")

    quality = {
        "row_count": int(len(new)),
        "pk_duplicate_count": int(new.duplicated(["ts_code", "trade_date"]).sum()),
        "forbidden_columns": [
            c
            for c in new.columns
            if ("_fwd_" in c)
            or c.startswith("entry_")
            or c in ("max_favorable_excursion", "max_adverse_excursion", "structure_break")
        ],
        "winner_rate_oob_before": int(wr_before_oob.fillna(False).sum()),
        "winner_rate_oob_after": int(wr_after_oob.fillna(False).sum()),
        "lowpos_oob_before": int(lowpos_before_oob.fillna(False).sum()),
        "lowpos_oob_after": int(lowpos_after_oob.fillna(False).sum()),
        "feature_ready_rate_after": float(new["feature_ready_flag"].mean()),
    }
    quality_path = root / "event_feature_snapshot_batch3_patch1_quality_report.json"
    quality_path.write_text(json.dumps(quality, ensure_ascii=False, indent=2), encoding="utf-8")

    print("=" * 70)
    print("patch batch3 done")
    print("=" * 70)
    print(f"output={out_path}")
    print(f"rows={len(new)} cols={new.shape[1]}")
    print(f"winner_oob_before={quality['winner_rate_oob_before']} after={quality['winner_rate_oob_after']}")
    print(f"lowpos_oob_before={quality['lowpos_oob_before']} after={quality['lowpos_oob_after']}")
    print(f"ready_before={ready_cmp['ready_rate_before']:.6f} ready_after={ready_cmp['ready_rate_after']:.6f}")
    print(f"winner_compare={winner_path}")
    print(f"lowpos_compare={low_path}")
    print(f"qc_compare={qc_path}")
    print(f"quality={quality_path}")


if __name__ == "__main__":
    main()
