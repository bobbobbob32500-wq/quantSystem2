# -*- coding: utf-8 -*-
"""
Build batch2 industry aggregation features on top of batch1 patch.

Allowed fields:
- f_ind_strength_today
- f_ind_strength_3d
- f_ind_strength_5d
- f_ind_breadth
- f_ind_peer_strong_count
- f_ind_rank_pctchg
- f_ind_rank_amount
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


def _build_mainboard_condition(alias: str = "d.ts_code") -> str:
    sh_like = " OR ".join(f"{alias} LIKE '{p}%.SH'" for p in MAINBOARD_SH_PREFIXES)
    sz_like = " OR ".join(f"{alias} LIKE '{p}%.SZ'" for p in MAINBOARD_SZ_PREFIXES)
    return f"({sh_like} OR {sz_like})"


def _load_daily_with_industry(conn: sqlite3.Connection, start_date: str, end_date: str) -> pd.DataFrame:
    cond = _build_mainboard_condition("d.ts_code")
    sql = f"""
        SELECT
            d.ts_code,
            d.trade_date,
            d.close,
            d.vol,
            d.amount,
            d.pct_chg,
            b.industry
        FROM stock_daily d
        LEFT JOIN stock_basic b
          ON d.ts_code = b.ts_code
        WHERE d.trade_date >= ? AND d.trade_date <= ?
          AND ({cond} OR d.ts_code = ?)
        ORDER BY d.ts_code ASC, d.trade_date ASC
    """
    df = pd.read_sql_query(sql, conn, params=(start_date, end_date, INDEX_CODE))
    if df.empty:
        return df
    for c in ["close", "vol", "amount", "pct_chg"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["industry"] = df["industry"].fillna("UNKNOWN").astype(str).replace("", "UNKNOWN")
    df["trade_date"] = pd.to_datetime(df["trade_date"].astype(str), format="%Y%m%d", errors="coerce")
    df = df.dropna(subset=["ts_code", "trade_date", "close"]).copy()
    df = df.sort_values(["ts_code", "trade_date"]).reset_index(drop=True)
    return df


def _build_industry_features(panel: pd.DataFrame) -> pd.DataFrame:
    if panel.empty:
        return pd.DataFrame()
    stock = panel[panel["ts_code"] != INDEX_CODE].copy()
    g = stock.groupby("ts_code", group_keys=False)
    stock["prev_close"] = g["close"].shift(1)
    stock["ret1"] = stock["close"] / stock["prev_close"] - 1.0
    stock["vol_ma20"] = g["vol"].transform(lambda s: s.rolling(20, min_periods=20).mean())
    stock["vol_ratio20"] = stock["vol"] / stock["vol_ma20"].replace(0, np.nan)
    stock["strong_flag"] = (
        stock["ret1"].fillna(-np.inf).ge(0.03) & stock["vol_ratio20"].fillna(0.0).ge(1.2)
    ).astype(int)
    stock["up_flag"] = stock["ret1"].fillna(0.0).gt(0.0).astype(int)

    # Use decimal returns uniformly
    ind = (
        stock.groupby(["trade_date", "industry"], as_index=False)
        .agg(
            ind_ret_today=("ret1", "mean"),
            f_ind_breadth=("up_flag", "mean"),
            f_ind_peer_strong_count=("strong_flag", "sum"),
            ind_amount_sum=("amount", "sum"),
        )
        .sort_values(["industry", "trade_date"])
        .reset_index(drop=True)
    )

    ind["ind_ret3"] = ind.groupby("industry")["ind_ret_today"].transform(
        lambda s: s.rolling(3, min_periods=1).mean()
    )
    ind["ind_ret5"] = ind.groupby("industry")["ind_ret_today"].transform(
        lambda s: s.rolling(5, min_periods=1).mean()
    )

    ind["f_ind_strength_today"] = ind.groupby("trade_date")["ind_ret_today"].rank(
        pct=True, method="average"
    )
    ind["f_ind_strength_3d"] = ind.groupby("trade_date")["ind_ret3"].rank(
        pct=True, method="average"
    )
    ind["f_ind_strength_5d"] = ind.groupby("trade_date")["ind_ret5"].rank(
        pct=True, method="average"
    )

    stock["f_ind_rank_pctchg"] = stock.groupby(["trade_date", "industry"])["ret1"].rank(
        pct=True, method="average"
    )
    stock["f_ind_rank_amount"] = stock.groupby(["trade_date", "industry"])["amount"].rank(
        pct=True, method="average"
    )

    out = stock.merge(
        ind[
            [
                "trade_date",
                "industry",
                "f_ind_strength_today",
                "f_ind_strength_3d",
                "f_ind_strength_5d",
                "f_ind_breadth",
                "f_ind_peer_strong_count",
            ]
        ],
        on=["trade_date", "industry"],
        how="left",
    )
    out = out[
        [
            "ts_code",
            "trade_date",
            "industry",
            "f_ind_strength_today",
            "f_ind_strength_3d",
            "f_ind_strength_5d",
            "f_ind_breadth",
            "f_ind_peer_strong_count",
            "f_ind_rank_pctchg",
            "f_ind_rank_amount",
        ]
    ].copy()
    out["trade_date"] = out["trade_date"].dt.strftime("%Y%m%d")
    return out


def _append_qc_note(base_note: pd.Series, append_note: pd.Series) -> pd.Series:
    notes = []
    for old, add in zip(base_note.fillna("").astype(str), append_note.fillna("").astype(str)):
        old_clean = "" if old in ("", "ok", "nan", "None") else old
        add_clean = "" if add in ("", "ok", "nan", "None") else add
        if old_clean and add_clean:
            notes.append(f"{old_clean};{add_clean}")
        elif old_clean:
            notes.append(old_clean)
        elif add_clean:
            notes.append(add_clean)
        else:
            notes.append("ok")
    return pd.Series(notes)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build batch2 industry features.")
    parser.add_argument(
        "--research-dir",
        type=str,
        default=str(_research_dir()),
    )
    parser.add_argument(
        "--batch1-patch-input",
        type=str,
        default="event_feature_snapshot_batch1_patch1.parquet",
    )
    parser.add_argument(
        "--ac-main",
        type=str,
        default="ac_main_research_set.parquet",
    )
    parser.add_argument(
        "--output",
        type=str,
        default="event_feature_snapshot_batch2.parquet",
    )
    args = parser.parse_args()

    root = Path(args.research_dir)
    in_path = root / args.batch1_patch_input
    ac_path = root / args.ac_main
    out_path = root / args.output
    if not in_path.exists():
        raise FileNotFoundError(f"batch1 patch input not found: {in_path}")
    if not ac_path.exists():
        raise FileNotFoundError(f"ac_main not found: {ac_path}")

    base = pd.read_parquet(in_path).sort_values(["trade_date", "ts_code"]).reset_index(drop=True)
    ac = pd.read_parquet(ac_path).sort_values(["trade_date", "ts_code"]).reset_index(drop=True)
    base["trade_date"] = base["trade_date"].astype(str)
    ac["trade_date"] = ac["trade_date"].astype(str)

    min_dt = datetime.strptime(base["trade_date"].min(), "%Y%m%d")
    max_dt = datetime.strptime(base["trade_date"].max(), "%Y%m%d")
    start_date = (min_dt - timedelta(days=120)).strftime("%Y%m%d")
    end_date = max_dt.strftime("%Y%m%d")

    conn = sqlite3.connect(_db_path(), timeout=10)
    try:
        panel = _load_daily_with_industry(conn, start_date, end_date)
    finally:
        conn.close()
    if panel.empty:
        raise ValueError("daily+industry panel empty for batch2")

    indf = _build_industry_features(panel)
    merged = base.merge(indf, on=["ts_code", "trade_date"], how="left", suffixes=("", "_ind"))
    if "industry_ind" in merged.columns:
        merged["industry"] = merged["industry"].fillna(merged["industry_ind"])
        merged = merged.drop(columns=["industry_ind"], errors="ignore")
    merged["industry"] = merged["industry"].fillna("UNKNOWN").astype(str).replace("", "UNKNOWN")

    ind_cols = [
        "f_ind_strength_today",
        "f_ind_strength_3d",
        "f_ind_strength_5d",
        "f_ind_breadth",
        "f_ind_peer_strong_count",
        "f_ind_rank_pctchg",
        "f_ind_rank_amount",
    ]

    industry_unknown = merged["industry"].eq("UNKNOWN")
    ind_missing = merged[ind_cols].isna().any(axis=1)
    add_note = np.select(
        [industry_unknown & ind_missing, industry_unknown, ind_missing],
        ["industry_unknown;industry_feature_missing", "industry_unknown", "industry_feature_missing"],
        default="ok",
    )
    merged["qc_note"] = _append_qc_note(merged["qc_note"], pd.Series(add_note))

    # refresh coverage/readiness at batch2 scope
    feature_cols = [c for c in merged.columns if c.startswith("f_")]
    merged["source_coverage_flag"] = (
        merged["source_coverage_flag"].fillna(0).astype(int).eq(1) & (~industry_unknown)
    ).astype(int)
    merged["missing_ratio"] = merged[feature_cols].isna().mean(axis=1)
    merged["feature_ready_flag"] = (
        merged["source_coverage_flag"].eq(1) & merged["missing_ratio"].le(0.15)
    ).astype(int)
    merged["data_version"] = "pending_batch2"
    merged["feature_spec_version"] = "fs_v1_batch2"

    merged = merged.sort_values(["trade_date", "ts_code"]).reset_index(drop=True)
    merged.to_parquet(out_path, index=False)

    # reports
    fields_path = root / "event_feature_snapshot_batch2_fields.txt"
    fields_path.write_text("\n".join(merged.columns.tolist()), encoding="utf-8")

    cov = pd.DataFrame(
        {
            "feature": feature_cols,
            "non_null_rate": [float(merged[c].notna().mean()) for c in feature_cols],
            "null_count": [int(merged[c].isna().sum()) for c in feature_cols],
        }
    ).sort_values("non_null_rate", ascending=True)
    cov_path = root / "event_feature_snapshot_batch2_coverage.csv"
    cov.to_csv(cov_path, index=False, encoding="utf-8-sig")

    ind_cov = pd.DataFrame(
        {
            "feature": ind_cols,
            "non_null_rate": [float(merged[c].notna().mean()) for c in ind_cols],
            "null_count": [int(merged[c].isna().sum()) for c in ind_cols],
        }
    )
    ind_cov_path = root / "event_feature_snapshot_batch2_ind_coverage.csv"
    ind_cov.to_csv(ind_cov_path, index=False, encoding="utf-8-sig")

    qc_sum = merged["qc_note"].value_counts(dropna=False).rename_axis("qc_note").reset_index(name="count")
    qc_path = root / "event_feature_snapshot_batch2_qc_summary.csv"
    qc_sum.to_csv(qc_path, index=False, encoding="utf-8-sig")

    forbidden_patterns = ["_fwd_", "entry_", "max_favorable_excursion", "max_adverse_excursion", "structure_break"]
    forbidden_cols = [c for c in merged.columns if any(p in c for p in forbidden_patterns)]

    # small-industry counts for risk check
    ind_size = (
        panel[panel["ts_code"] != INDEX_CODE]
        .groupby(["trade_date", "industry"])["ts_code"]
        .nunique()
        .reset_index(name="industry_member_count")
    )
    small_ind = ind_size[ind_size["industry_member_count"] <= 2]

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
        "industry_unknown_count": int(merged["industry"].eq("UNKNOWN").sum()),
        "industry_missing_feature_rows": int(ind_missing.sum()),
        "small_industry_rows_le2_members": int(len(small_ind)),
    }
    quality_path = root / "event_feature_snapshot_batch2_quality_report.json"
    quality_path.write_text(json.dumps(quality, ensure_ascii=False, indent=2), encoding="utf-8")

    print("=" * 70)
    print("build batch2 done")
    print("=" * 70)
    print(f"input={in_path}")
    print(f"output={out_path}")
    print(f"rows={len(merged)} cols={merged.shape[1]}")
    print(f"ready_rate={quality['feature_ready_rate']:.6f}")
    print(f"industry_unknown={quality['industry_unknown_count']}")
    print(f"fields={fields_path}")
    print(f"coverage={cov_path}")
    print(f"ind_coverage={ind_cov_path}")
    print(f"qc_summary={qc_path}")
    print(f"quality={quality_path}")


if __name__ == "__main__":
    main()
