from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(r"D:\HuaweiAI\quantSystem2")
SNAPSHOT = ROOT / "data/research/strong_start_full/event_feature_snapshot_batch4.parquet"
DB_PATH = ROOT / "data/database/quant_system.db"
OUT_DIR = ROOT / "data/research/strong_start_full/v4_scan"

OUT_COMPARE = OUT_DIR / "true_breakout_selector_tune21_compare.csv"
OUT_SUMMARY = OUT_DIR / "true_breakout_selector_tune21_summary.json"
OUT_REVIEW = OUT_DIR / "true_breakout_selector_tune21_review.md"


def _rank01(s: pd.Series, higher: bool = True) -> pd.Series:
    x = pd.to_numeric(s, errors="coerce")
    if not higher:
        x = -x
    return x.rank(method="average", pct=True)


def _load_daily_forward() -> pd.DataFrame:
    conn = sqlite3.connect(DB_PATH)
    try:
        daily = pd.read_sql_query("select ts_code, trade_date, open, close from stock_daily", conn)
    finally:
        conn.close()
    daily["trade_date"] = daily["trade_date"].astype(str)
    daily["open"] = pd.to_numeric(daily["open"], errors="coerce")
    daily["close"] = pd.to_numeric(daily["close"], errors="coerce")
    daily = daily.sort_values(["ts_code", "trade_date"]).reset_index(drop=True)
    daily["buy_date"] = daily.groupby("ts_code")["trade_date"].shift(-1)
    daily["buy_open_t1"] = daily.groupby("ts_code")["open"].shift(-1)
    daily["close_t1"] = daily.groupby("ts_code")["close"].shift(-1)
    daily["close_t2"] = daily.groupby("ts_code")["close"].shift(-2)
    return daily[["ts_code", "trade_date", "buy_date", "buy_open_t1", "close_t1", "close_t2"]]


def _perf(df: pd.DataFrame) -> dict:
    if len(df) == 0:
        return {
            "sample_n": 0,
            "a_share": np.nan,
            "avg_ret_t1": np.nan,
            "med_ret_t1": np.nan,
            "win_t1": np.nan,
            "avg_ret_t2": np.nan,
            "med_ret_t2": np.nan,
            "win_t2": np.nan,
        }
    return {
        "sample_n": int(len(df)),
        "a_share": float((df["label_abc"] == "A").mean()) if "label_abc" in df.columns else np.nan,
        "avg_ret_t1": float(df["ret_close_t1"].mean()),
        "med_ret_t1": float(df["ret_close_t1"].median()),
        "win_t1": float((df["ret_close_t1"] > 0).mean()),
        "avg_ret_t2": float(df["ret_close_t2"].mean()),
        "med_ret_t2": float(df["ret_close_t2"].median()),
        "win_t2": float((df["ret_close_t2"] > 0).mean()),
    }


def main() -> None:
    raw = pd.read_parquet(SNAPSHOT)
    raw = raw[raw["label_abc"].isin(["A", "C"])].copy()
    raw["trade_date"] = raw["trade_date"].astype(str)

    # align with recent mid-window used in current selector reviews
    max_t = pd.to_datetime(raw["trade_date"].max(), format="%Y%m%d")
    start_t = max_t - pd.Timedelta(days=183)
    x = raw[
        (pd.to_datetime(raw["trade_date"], format="%Y%m%d") >= start_t)
        & (pd.to_datetime(raw["trade_date"], format="%Y%m%d") <= max_t)
    ].copy()

    # freeze1 hard filters
    x["pass_hard_filters"] = (
        (x["f_trend_close_ma20_gap"] >= 0.02)
        & (x["f_strength_rs20_xsec_q"] >= 0.70)
        & (x["f_ind_rank_pctchg"] >= 0.80)
    )

    # freeze1 scores
    x["score_strength_axis"] = (
        _rank01(x["f_strength_ret20"], True)
        + _rank01(x["f_strength_ret60"], True)
        + _rank01(x["f_trend_ma20_ma60_gap"], True)
    ) / 3.0
    x["score_industry_axis"] = (
        _rank01(x["f_ind_strength_3d"], True)
        + _rank01(x["f_ind_strength_5d"], True)
        + _rank01(x["f_ind_rank_pctchg"], True)
    ) / 3.0
    x["score_chip_axis"] = (
        _rank01(x["f_chip_concentration"], True)
        + _rank01(x["f_chip_winner_rate"], True)
        + _rank01(x["f_chip_stability_std10"], True)
    ) / 3.0
    x["score_platform_axis"] = (
        _rank01(x["f_platform_range_best"], True)
        + _rank01(x["f_platform_compress_ratio"], True)
    ) / 2.0
    x["score_total"] = (
        0.40 * x["score_strength_axis"]
        + 0.35 * x["score_industry_axis"]
        + 0.20 * x["score_chip_axis"]
        + 0.05 * x["score_platform_axis"]
    )

    # daily rank/rank_pct in hard-filter-pass set
    x["daily_rank"] = np.nan
    x["rank_pct"] = np.nan
    for d, g in x[x["pass_hard_filters"]].groupby("trade_date"):
        x.loc[g.index, "daily_rank"] = g["score_total"].rank(method="first", ascending=False)
        x.loc[g.index, "rank_pct"] = g["score_total"].rank(method="first", ascending=False, pct=True)

    # add forward observation (non-backtest, selector-effect only)
    fwd = _load_daily_forward()
    z = x.merge(fwd, on=["ts_code", "trade_date"], how="left")
    z = z.dropna(subset=["buy_open_t1", "close_t1", "close_t2"]).copy()
    z["ret_close_t1"] = z["close_t1"] / z["buy_open_t1"] - 1
    z["ret_close_t2"] = z["close_t2"] / z["buy_open_t1"] - 1

    # three fixed groups (single-point tune21 comparison)
    g_freeze1 = z[z["pass_hard_filters"] & (z["rank_pct"] <= 0.30)].copy()
    g_top3 = z[z["pass_hard_filters"] & (z["daily_rank"] <= 3)].copy()
    g_top2 = z[z["pass_hard_filters"] & (z["daily_rank"] <= 2)].copy()

    rows = []
    for name, df in [
        ("freeze1_original_top30pct", g_freeze1),
        ("tune21_top3", g_top3),
        ("reference_top2", g_top2),
    ]:
        p = _perf(df)
        p["group"] = name
        rows.append(p)
    compare = pd.DataFrame(rows)[
        ["group", "sample_n", "a_share", "avg_ret_t1", "med_ret_t1", "win_t1", "avg_ret_t2", "med_ret_t2", "win_t2"]
    ]
    compare.to_csv(OUT_COMPARE, index=False, encoding="utf-8-sig")

    c = compare.set_index("group")
    summary = {
        "window": {
            "start": str(z["trade_date"].min()) if len(z) else None,
            "end": str(z["trade_date"].max()) if len(z) else None,
            "trade_days": int(z["trade_date"].nunique()),
        },
        "groups": compare.to_dict(orient="records"),
        "direct_answers": {
            "q1_top3_vs_top30_more_reasonable": bool(
                (c.loc["tune21_top3", "a_share"] > c.loc["freeze1_original_top30pct", "a_share"])
                and (c.loc["tune21_top3", "win_t2"] >= c.loc["freeze1_original_top30pct", "win_t2"])
            ),
            "q2_top3_vs_top2_for_formal_pool": "top3_if_balance_priority" if c.loc["reference_top2", "sample_n"] < c.loc["tune21_top3", "sample_n"] * 0.75 else "top2_if_purity_priority",
            "q3_main_issue_is_pool_too_wide": bool(c.loc["tune21_top3", "a_share"] > c.loc["freeze1_original_top30pct", "a_share"]),
            "q4_tune21_worth_next_baseline_candidate": bool(
                (c.loc["tune21_top3", "a_share"] > c.loc["freeze1_original_top30pct", "a_share"])
                and (c.loc["tune21_top3", "win_t2"] >= c.loc["freeze1_original_top30pct", "win_t2"])
            ),
        },
    }
    OUT_SUMMARY.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    review = [
        "# true_breakout_selector_tune21_review",
        "",
        "Only one change vs freeze1: output-layer candidate pool from top30% -> daily top3.",
        "Top2 is reference only.",
        "",
        "## Window",
        f"- {summary['window']['start']} ~ {summary['window']['end']} ({summary['window']['trade_days']} trading days)",
        "",
        "## Key compare",
        compare.to_string(index=False),
        "",
        "## 4 direct answers",
        f"1) Top3 vs Top30 more reasonable: {summary['direct_answers']['q1_top3_vs_top30_more_reasonable']}",
        f"2) Top3 vs Top2 for formal pool: {summary['direct_answers']['q2_top3_vs_top2_for_formal_pool']}",
        f"3) Main issue is pool too wide: {summary['direct_answers']['q3_main_issue_is_pool_too_wide']}",
        f"4) tune2.1 worth as next baseline candidate: {summary['direct_answers']['q4_tune21_worth_next_baseline_candidate']}",
    ]
    OUT_REVIEW.write_text("\n".join(review), encoding="utf-8")

    print("Generated:")
    print(" -", OUT_COMPARE)
    print(" -", OUT_SUMMARY)
    print(" -", OUT_REVIEW)


if __name__ == "__main__":
    main()
