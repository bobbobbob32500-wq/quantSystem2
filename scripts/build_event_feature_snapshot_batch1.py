# -*- coding: utf-8 -*-
"""
Build phase-2 batch-1 event feature snapshot.

Scope in this script is strictly limited to:
- f_strength_*
- f_platform_*
- f_vol_*
- f_k_*

No industry aggregation, no chip features, no forward-window fields.
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


MAINBOARD_SH_PREFIXES: Tuple[str, ...] = ("600", "601", "603", "605")
MAINBOARD_SZ_PREFIXES: Tuple[str, ...] = ("000", "001", "002", "003")
INDEX_CODE = "000001.SH"


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


def _load_labeled_events(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"labeled events not found: {path}")
    df = pd.read_parquet(path)
    return df


def _build_or_load_ac_main(
    ac_path: Path,
    labeled_path: Path,
    b_aux_path: Path,
    c_nontradable_path: Path,
) -> pd.DataFrame:
    if ac_path.exists():
        return pd.read_parquet(ac_path)

    labeled = _load_labeled_events(labeled_path)
    required_cols = {
        "trade_date",
        "ts_code",
        "label_abc",
        "analysis_ready",
        "has_full_forward_window",
        "entry_possible",
        "event_type_candidate",
        "name",
        "industry",
    }
    missing = sorted(required_cols - set(labeled.columns))
    if missing:
        raise ValueError(f"labeled_events missing required columns: {missing}")

    base = labeled[
        labeled["analysis_ready"].eq(True) & labeled["has_full_forward_window"].eq(True)
    ].copy()
    ac = base[
        base["label_abc"].isin(["A", "C"]) & base["entry_possible"].eq(True)
    ].copy()
    b_aux = base[base["label_abc"].eq("B")].copy()
    c_nontradable = base[
        base["label_abc"].eq("C") & base["entry_possible"].ne(True)
    ].copy()

    keep_cols = [
        "trade_date",
        "ts_code",
        "label_abc",
        "event_type_candidate",
        "name",
        "industry",
    ]
    ac = (
        ac[keep_cols]
        .drop_duplicates(subset=["ts_code", "trade_date"])
        .sort_values(["trade_date", "ts_code"])
        .reset_index(drop=True)
    )
    b_aux = (
        b_aux[keep_cols]
        .drop_duplicates(subset=["ts_code", "trade_date"])
        .sort_values(["trade_date", "ts_code"])
        .reset_index(drop=True)
    )
    c_nontradable = (
        c_nontradable[keep_cols]
        .drop_duplicates(subset=["ts_code", "trade_date"])
        .sort_values(["trade_date", "ts_code"])
        .reset_index(drop=True)
    )

    ac_path.parent.mkdir(parents=True, exist_ok=True)
    ac.to_parquet(ac_path, index=False)
    b_aux.to_parquet(b_aux_path, index=False)
    c_nontradable.to_parquet(c_nontradable_path, index=False)
    return ac


def _load_daily_panel(
    conn: sqlite3.Connection,
    start_date: str,
    end_date: str,
) -> pd.DataFrame:
    cond = _build_mainboard_condition("ts_code")
    sql = f"""
        SELECT ts_code, trade_date, open, high, low, close, vol, amount, pct_chg
        FROM stock_daily
        WHERE trade_date >= ? AND trade_date <= ?
          AND (({cond}) OR ts_code = ?)
        ORDER BY ts_code ASC, trade_date ASC
    """
    df = pd.read_sql_query(sql, conn, params=(start_date, end_date, INDEX_CODE))
    if df.empty:
        return df
    for c in ["open", "high", "low", "close", "vol", "amount", "pct_chg"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["trade_date"] = pd.to_datetime(df["trade_date"].astype(str), format="%Y%m%d", errors="coerce")
    df = df.dropna(subset=["ts_code", "trade_date", "close", "high", "low"]).copy()
    df = df.sort_values(["ts_code", "trade_date"]).reset_index(drop=True)
    return df


def _calc_consecutive_true(mask: pd.Series) -> pd.Series:
    out = np.zeros(len(mask), dtype=int)
    run = 0
    arr = mask.fillna(False).to_numpy(dtype=bool)
    for i, v in enumerate(arr):
        if v:
            run += 1
        else:
            run = 0
        out[i] = run
    return pd.Series(out, index=mask.index, dtype="int64")


def _build_batch1_features(daily: pd.DataFrame) -> pd.DataFrame:
    if daily.empty:
        return pd.DataFrame()

    stock = daily[daily["ts_code"] != INDEX_CODE].copy()
    index_df = daily[daily["ts_code"] == INDEX_CODE][["trade_date", "close"]].copy()
    index_df = index_df.sort_values("trade_date").reset_index(drop=True)
    index_df["idx_ret20"] = index_df["close"] / index_df["close"].shift(20) - 1.0
    index_df["idx_ret60"] = index_df["close"] / index_df["close"].shift(60) - 1.0
    index_df = index_df[["trade_date", "idx_ret20", "idx_ret60"]]

    g = stock.groupby("ts_code", group_keys=False)

    stock["ma20"] = g["close"].transform(lambda s: s.rolling(20, min_periods=20).mean())
    stock["ma60"] = g["close"].transform(lambda s: s.rolling(60, min_periods=60).mean())
    stock["vol_ma20"] = g["vol"].transform(lambda s: s.rolling(20, min_periods=20).mean())
    stock["vol_ma60"] = g["vol"].transform(lambda s: s.rolling(60, min_periods=60).mean())

    stock["f_strength_ret20"] = stock["close"] / g["close"].shift(20) - 1.0
    stock["f_strength_ret60"] = stock["close"] / g["close"].shift(60) - 1.0
    stock["f_trend_close_ma20_gap"] = stock["close"] / stock["ma20"].replace(0, np.nan) - 1.0
    stock["f_trend_close_ma60_gap"] = stock["close"] / stock["ma60"].replace(0, np.nan) - 1.0
    stock["f_trend_ma20_ma60_gap"] = stock["ma20"] / stock["ma60"].replace(0, np.nan) - 1.0
    stock["f_trend_ma20_slope5"] = stock["ma20"] / g["ma20"].shift(5) - 1.0

    stock = stock.merge(index_df, on="trade_date", how="left")
    stock["f_strength_vs_index20"] = stock["f_strength_ret20"] - stock["idx_ret20"]
    stock["f_strength_vs_index60"] = stock["f_strength_ret60"] - stock["idx_ret60"]

    stock["f_strength_rs20_xsec_q"] = stock.groupby("trade_date")["f_strength_ret20"].rank(
        pct=True, method="average"
    )
    stock["f_strength_rs60_xsec_q"] = stock.groupby("trade_date")["f_strength_ret60"].rank(
        pct=True, method="average"
    )

    prev_close = g["close"].shift(1)
    tr = pd.concat(
        [
            stock["high"] - stock["low"],
            (stock["high"] - prev_close).abs(),
            (stock["low"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    stock["atr14"] = tr.groupby(stock["ts_code"]).transform(lambda s: s.rolling(14, min_periods=14).mean())
    stock["f_atr_ratio"] = _safe_ratio(stock["atr14"], stock["close"])

    stock["pivot20"] = g["high"].transform(lambda s: s.shift(1).rolling(20, min_periods=20).max())
    stock["low20"] = g["low"].transform(lambda s: s.shift(1).rolling(20, min_periods=20).min())
    stock["pivot30"] = g["high"].transform(lambda s: s.shift(1).rolling(30, min_periods=30).max())
    stock["low30"] = g["low"].transform(lambda s: s.shift(1).rolling(30, min_periods=30).min())
    stock["f_platform_range20"] = _safe_ratio(stock["pivot20"] - stock["low20"], stock["pivot20"])
    stock["f_platform_range30"] = _safe_ratio(stock["pivot30"] - stock["low30"], stock["pivot30"])
    stock["f_platform_range_best"] = stock[["f_platform_range20", "f_platform_range30"]].min(axis=1)

    stock["bar_amp"] = _safe_ratio(stock["high"] - stock["low"], stock["close"])
    amp_ma10 = stock.groupby("ts_code")["bar_amp"].transform(lambda s: s.rolling(10, min_periods=10).mean())
    amp_ma20 = stock.groupby("ts_code")["bar_amp"].transform(lambda s: s.rolling(20, min_periods=20).mean())
    stock["f_platform_compress_ratio"] = _safe_ratio(amp_ma10, amp_ma20)

    platform_cond = stock["f_platform_range20"].le(0.18)
    stock["f_platform_len"] = stock.groupby("ts_code", group_keys=False)["f_platform_range20"].transform(
        lambda s: _calc_consecutive_true(s.le(0.18))
    )
    stock.loc[~platform_cond.fillna(False), "f_platform_len"] = 0

    stock["f_near_pivot20"] = _safe_ratio(stock["close"] - stock["pivot20"], stock["pivot20"])

    stock["f_vol20_vol60"] = _safe_ratio(stock["vol_ma20"], stock["vol_ma60"])
    low_vol_flag = stock["vol"] < stock["vol_ma60"]
    stock["f_low_vol_days10"] = low_vol_flag.groupby(stock["ts_code"]).transform(
        lambda s: s.astype(float).rolling(10, min_periods=10).sum()
    )
    vol_std20 = g["vol"].transform(lambda s: s.rolling(20, min_periods=20).std())
    vol_mean20 = g["vol"].transform(lambda s: s.rolling(20, min_periods=20).mean())
    stock["f_vol_stability20"] = _safe_ratio(vol_std20, vol_mean20)
    stock["f_breakout_vol_ratio20"] = _safe_ratio(stock["vol"], stock["vol_ma20"])

    up_vol = stock["vol"].where(stock["pct_chg"] > 0)
    down_vol = stock["vol"].where(stock["pct_chg"] <= 0)
    up_mean20 = up_vol.groupby(stock["ts_code"]).transform(lambda s: s.rolling(20, min_periods=5).mean())
    down_mean20 = down_vol.groupby(stock["ts_code"]).transform(lambda s: s.rolling(20, min_periods=5).mean())
    stock["f_up_down_vol_ratio20"] = _safe_ratio(up_mean20, down_mean20)

    day_range = (stock["high"] - stock["low"]).replace(0, np.nan)
    stock["f_k_pct_chg"] = stock["pct_chg"]
    stock["f_k_body_to_atr"] = _safe_ratio((stock["close"] - stock["open"]).abs(), stock["atr14"])
    stock["f_k_upper_shadow_ratio"] = _safe_ratio(
        stock["high"] - stock[["open", "close"]].max(axis=1),
        day_range,
    )
    stock["f_k_lower_shadow_ratio"] = _safe_ratio(
        stock[["open", "close"]].min(axis=1) - stock["low"],
        day_range,
    )
    stock["f_k_close_pos"] = _safe_ratio(stock["close"] - stock["low"], day_range)
    stock["f_k_break_pivot20_pct"] = _safe_ratio(stock["close"] - stock["pivot20"], stock["pivot20"])

    keep = [
        "ts_code",
        "trade_date",
        "f_strength_ret20",
        "f_strength_ret60",
        "f_strength_vs_index20",
        "f_strength_vs_index60",
        "f_strength_rs20_xsec_q",
        "f_strength_rs60_xsec_q",
        "f_trend_close_ma20_gap",
        "f_trend_close_ma60_gap",
        "f_trend_ma20_ma60_gap",
        "f_trend_ma20_slope5",
        "f_platform_len",
        "f_platform_range20",
        "f_platform_range30",
        "f_platform_range_best",
        "f_platform_compress_ratio",
        "f_atr_ratio",
        "f_near_pivot20",
        "f_vol20_vol60",
        "f_low_vol_days10",
        "f_vol_stability20",
        "f_breakout_vol_ratio20",
        "f_up_down_vol_ratio20",
        "f_k_pct_chg",
        "f_k_body_to_atr",
        "f_k_upper_shadow_ratio",
        "f_k_lower_shadow_ratio",
        "f_k_close_pos",
        "f_k_break_pivot20_pct",
        "idx_ret20",
        "idx_ret60",
    ]
    out = stock[keep].copy()
    out["trade_date"] = out["trade_date"].dt.strftime("%Y%m%d")
    out = out.sort_values(["trade_date", "ts_code"]).reset_index(drop=True)
    return out


def _build_qc_fields(df: pd.DataFrame, feature_cols: List[str]) -> pd.DataFrame:
    out = df.copy()
    out["source_coverage_flag"] = (
        out["idx_ret20"].notna() & out["idx_ret60"].notna()
    ).astype(int)
    out["missing_ratio"] = out[feature_cols].isna().mean(axis=1)
    out["feature_ready_flag"] = (
        out["source_coverage_flag"].eq(1) & out["missing_ratio"].le(0.15)
    ).astype(int)
    out["data_version"] = "pending"
    out["feature_spec_version"] = "fs_v1_batch1"

    notes: List[List[str]] = [[] for _ in range(len(out))]
    idx_missing = out["source_coverage_flag"].eq(0).to_numpy()
    high_missing = out["missing_ratio"].gt(0.15).to_numpy()
    for i in range(len(out)):
        if idx_missing[i]:
            notes[i].append("index_ref_missing")
        if high_missing[i]:
            notes[i].append("missing_ratio_gt_0p15")
    out["qc_note"] = [";".join(x) if x else "ok" for x in notes]
    return out


def _write_quality_reports(
    out_dir: Path,
    snapshot: pd.DataFrame,
    ac_main: pd.DataFrame,
    feature_cols: List[str],
) -> Dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    paths: Dict[str, Path] = {}

    field_file = out_dir / "event_feature_snapshot_batch1_fields.txt"
    field_file.write_text("\n".join(snapshot.columns.tolist()), encoding="utf-8")
    paths["fields"] = field_file

    coverage = pd.DataFrame(
        {
            "feature": feature_cols,
            "non_null_rate": [float(snapshot[c].notna().mean()) for c in feature_cols],
            "null_count": [int(snapshot[c].isna().sum()) for c in feature_cols],
        }
    ).sort_values("non_null_rate", ascending=True)
    coverage_path = out_dir / "event_feature_snapshot_batch1_coverage.csv"
    coverage.to_csv(coverage_path, index=False, encoding="utf-8-sig")
    paths["coverage"] = coverage_path

    qc_sum = snapshot["qc_note"].value_counts(dropna=False).rename_axis("qc_note").reset_index(name="count")
    qc_path = out_dir / "event_feature_snapshot_batch1_qc_summary.csv"
    qc_sum.to_csv(qc_path, index=False, encoding="utf-8-sig")
    paths["qc_summary"] = qc_path

    forbidden_patterns = ["_fwd_", "entry_", "max_favorable_excursion", "max_adverse_excursion", "structure_break"]
    forbidden_cols = [
        c for c in snapshot.columns for p in forbidden_patterns if p in c
    ]

    report = {
        "row_count": int(len(snapshot)),
        "col_count": int(snapshot.shape[1]),
        "pk_duplicate_count": int(snapshot.duplicated(["ts_code", "trade_date"]).sum()),
        "ac_main_rows": int(len(ac_main)),
        "join_coverage_rate": float(len(snapshot) / max(len(ac_main), 1)),
        "missing_events_count": int(max(len(ac_main) - len(snapshot), 0)),
        "forbidden_column_count": int(len(set(forbidden_cols))),
        "forbidden_columns": sorted(set(forbidden_cols)),
        "feature_ready_rate": float(snapshot["feature_ready_flag"].mean()),
    }
    report_path = out_dir / "event_feature_snapshot_batch1_quality_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    paths["quality_json"] = report_path

    md_lines = [
        "# Batch1 Quality Report",
        "",
        f"- row_count: {report['row_count']}",
        f"- col_count: {report['col_count']}",
        f"- pk_duplicate_count: {report['pk_duplicate_count']}",
        f"- ac_main_rows: {report['ac_main_rows']}",
        f"- join_coverage_rate: {report['join_coverage_rate']:.6f}",
        f"- missing_events_count: {report['missing_events_count']}",
        f"- forbidden_column_count: {report['forbidden_column_count']}",
        f"- feature_ready_rate: {report['feature_ready_rate']:.6f}",
        "",
        "## Forbidden Columns",
        "",
    ]
    if report["forbidden_columns"]:
        md_lines.extend([f"- {c}" for c in report["forbidden_columns"]])
    else:
        md_lines.append("- None")
    md_path = out_dir / "event_feature_snapshot_batch1_quality_report.md"
    md_path.write_text("\n".join(md_lines), encoding="utf-8")
    paths["quality_md"] = md_path

    return paths


def main() -> None:
    parser = argparse.ArgumentParser(description="Build event_feature_snapshot_batch1.parquet")
    parser.add_argument(
        "--research-dir",
        type=str,
        default=str(_research_dir()),
    )
    parser.add_argument(
        "--labeled-events",
        type=str,
        default="labeled_events.parquet",
    )
    parser.add_argument(
        "--ac-main",
        type=str,
        default="ac_main_research_set.parquet",
    )
    parser.add_argument(
        "--output",
        type=str,
        default="event_feature_snapshot_batch1.parquet",
    )
    args = parser.parse_args()

    research_dir = Path(args.research_dir)
    labeled_path = research_dir / args.labeled_events
    ac_path = research_dir / args.ac_main
    b_aux_path = research_dir / "b_aux_events.parquet"
    c_nontradable_path = research_dir / "c_nontradable_aux.parquet"
    output_path = research_dir / args.output

    ac_main = _build_or_load_ac_main(ac_path, labeled_path, b_aux_path, c_nontradable_path)
    if ac_main.empty:
        raise ValueError("ac_main_research_set is empty")

    ac_main = ac_main.copy()
    ac_main["trade_date"] = ac_main["trade_date"].astype(str)
    min_dt = datetime.strptime(ac_main["trade_date"].min(), "%Y%m%d")
    max_dt = datetime.strptime(ac_main["trade_date"].max(), "%Y%m%d")
    lookback_start = (min_dt - timedelta(days=420)).strftime("%Y%m%d")
    end_date = max_dt.strftime("%Y%m%d")

    conn = sqlite3.connect(_db_path(), timeout=10)
    try:
        daily = _load_daily_panel(conn, lookback_start, end_date)
    finally:
        conn.close()
    if daily.empty:
        raise ValueError("stock_daily panel is empty for requested window")

    feat = _build_batch1_features(daily)
    merged = ac_main.merge(feat, on=["ts_code", "trade_date"], how="left")

    feature_cols = [
        "f_strength_ret20",
        "f_strength_ret60",
        "f_strength_vs_index20",
        "f_strength_vs_index60",
        "f_strength_rs20_xsec_q",
        "f_strength_rs60_xsec_q",
        "f_trend_close_ma20_gap",
        "f_trend_close_ma60_gap",
        "f_trend_ma20_ma60_gap",
        "f_trend_ma20_slope5",
        "f_platform_len",
        "f_platform_range20",
        "f_platform_range30",
        "f_platform_range_best",
        "f_platform_compress_ratio",
        "f_atr_ratio",
        "f_near_pivot20",
        "f_vol20_vol60",
        "f_low_vol_days10",
        "f_vol_stability20",
        "f_breakout_vol_ratio20",
        "f_up_down_vol_ratio20",
        "f_k_pct_chg",
        "f_k_body_to_atr",
        "f_k_upper_shadow_ratio",
        "f_k_lower_shadow_ratio",
        "f_k_close_pos",
        "f_k_break_pivot20_pct",
    ]

    merged = _build_qc_fields(merged, feature_cols)
    merged = merged.drop(columns=["idx_ret20", "idx_ret60"], errors="ignore")
    merged = merged.sort_values(["trade_date", "ts_code"]).reset_index(drop=True)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    merged.to_parquet(output_path, index=False)

    report_paths = _write_quality_reports(research_dir, merged, ac_main, feature_cols)

    print("=" * 70)
    print("build event_feature_snapshot_batch1 done")
    print("=" * 70)
    print(f"ac_main={ac_path}")
    print(f"output={output_path}")
    print(f"rows={len(merged)} cols={merged.shape[1]}")
    print(f"feature_ready_rate={merged['feature_ready_flag'].mean():.6f}")
    for k, v in report_paths.items():
        print(f"{k}={v}")


if __name__ == "__main__":
    main()
