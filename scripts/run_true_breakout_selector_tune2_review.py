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

BASE_COVERAGE = OUT_DIR / "true_breakout_selector_coverage_summary.csv"
BASE_TOPN = OUT_DIR / "true_breakout_selector_top1_2_3_5_compare.csv"
BASE_TOP3_VS_45 = OUT_DIR / "true_breakout_selector_top3_vs_4_5.csv"

OUT_VALIDATION = OUT_DIR / "true_breakout_selector_tune2_validation_set.parquet"
OUT_COVERAGE = OUT_DIR / "true_breakout_selector_tune2_coverage_summary.csv"
OUT_TOPN = OUT_DIR / "true_breakout_selector_tune2_top1_2_3_5_compare.csv"
OUT_TOP3_VS_45 = OUT_DIR / "true_breakout_selector_tune2_top3_vs_4_5.csv"
OUT_COMPARE = OUT_DIR / "true_breakout_selector_tune2_vs_freeze1_compare.csv"
OUT_REVIEW = OUT_DIR / "true_breakout_selector_tune2_review.md"


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
            "n": 0,
            "avg_ret_t1": np.nan,
            "med_ret_t1": np.nan,
            "win_t1": np.nan,
            "avg_ret_t2": np.nan,
            "med_ret_t2": np.nan,
            "win_t2": np.nan,
        }
    return {
        "n": int(len(df)),
        "avg_ret_t1": float(df["ret_close_t1"].mean()),
        "med_ret_t1": float(df["ret_close_t1"].median()),
        "win_t1": float(df["win_t1"].mean()),
        "avg_ret_t2": float(df["ret_close_t2"].mean()),
        "med_ret_t2": float(df["ret_close_t2"].median()),
        "win_t2": float(df["win_t2"].mean()),
    }


def main() -> None:
    raw = pd.read_parquet(SNAPSHOT)
    raw = raw[raw["label_abc"].isin(["A", "C"])].copy()
    raw["trade_date"] = raw["trade_date"].astype(str)

    # same mid-window (~6 months) for consistent comparison
    max_t = pd.to_datetime(raw["trade_date"].max(), format="%Y%m%d")
    start_t = max_t - pd.Timedelta(days=183)
    x = raw[
        (pd.to_datetime(raw["trade_date"], format="%Y%m%d") >= start_t)
        & (pd.to_datetime(raw["trade_date"], format="%Y%m%d") <= max_t)
    ].copy()

    # tune2: only 3 edits
    x["pass_hard_filters"] = (
        (x["f_trend_close_ma20_gap"] >= 0.02)
        & (x["f_strength_rs20_xsec_q"] >= 0.70)
        & (x["f_ind_rank_pctchg"] >= 0.80)
        & (x["f_chip_winner_rate"] >= 0.80)
    )

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

    # tune2 weights: 0.40 / 0.25 / 0.30 / 0.05
    x["score_total"] = (
        0.40 * x["score_strength_axis"]
        + 0.25 * x["score_industry_axis"]
        + 0.30 * x["score_chip_axis"]
        + 0.05 * x["score_platform_axis"]
    )

    x["daily_rank"] = np.nan
    x["rank_pct"] = np.nan
    for d, g in x[x["pass_hard_filters"]].groupby("trade_date"):
        x.loc[g.index, "daily_rank"] = g["score_total"].rank(method="first", ascending=False)
        x.loc[g.index, "rank_pct"] = g["score_total"].rank(method="first", ascending=False, pct=True)
    x["is_candidate"] = x["pass_hard_filters"] & (x["rank_pct"] <= 0.10)  # tune2 cutoff Top10%

    # validation set
    vset = x[
        [
            "ts_code",
            "trade_date",
            "label_abc",
            "pass_hard_filters",
            "score_total",
            "score_strength_axis",
            "score_industry_axis",
            "score_chip_axis",
            "score_platform_axis",
            "is_candidate",
            "rank_pct",
            "daily_rank",
        ]
    ].copy()
    vset.to_parquet(OUT_VALIDATION, index=False)

    # coverage summary
    a = x[x["label_abc"] == "A"]
    c = x[x["label_abc"] == "C"]
    cand = x[x["is_candidate"]]
    full_a_share = (x["label_abc"] == "A").mean() if len(x) else np.nan
    cand_a_share = (cand["label_abc"] == "A").mean() if len(cand) else np.nan
    coverage = pd.DataFrame(
        [
            ("a_total", int(len(a))),
            ("c_total", int(len(c))),
            ("a_pass_hard_filter", int(a["pass_hard_filters"].sum())),
            ("c_pass_hard_filter", int(c["pass_hard_filters"].sum())),
            ("a_pass_hard_filter_rate", float(a["pass_hard_filters"].mean()) if len(a) else np.nan),
            ("c_pass_hard_filter_rate", float(c["pass_hard_filters"].mean()) if len(c) else np.nan),
            ("candidate_a_count", int((cand["label_abc"] == "A").sum())),
            ("candidate_c_count", int((cand["label_abc"] == "C").sum())),
            ("candidate_a_share", float(cand_a_share) if pd.notna(cand_a_share) else np.nan),
            ("full_sample_a_share", float(full_a_share) if pd.notna(full_a_share) else np.nan),
            ("a_share_lift_points", float(cand_a_share - full_a_share) if pd.notna(cand_a_share) and pd.notna(full_a_share) else np.nan),
        ],
        columns=["metric", "value"],
    )
    coverage.to_csv(OUT_COVERAGE, index=False, encoding="utf-8-sig")

    # topN performance on hard-filter pass set
    fwd = _load_daily_forward()
    p = x[x["pass_hard_filters"] & x["daily_rank"].notna()].merge(fwd, on=["ts_code", "trade_date"], how="left")
    p = p.dropna(subset=["buy_open_t1", "close_t1", "close_t2"]).copy()
    p["ret_close_t1"] = p["close_t1"] / p["buy_open_t1"] - 1
    p["ret_close_t2"] = p["close_t2"] / p["buy_open_t1"] - 1
    p["win_t1"] = p["ret_close_t1"] > 0
    p["win_t2"] = p["ret_close_t2"] > 0

    groups = []
    for grp, cond in [
        ("top1", p["daily_rank"] <= 1),
        ("top2", p["daily_rank"] <= 2),
        ("top3", p["daily_rank"] <= 3),
        ("top5", p["daily_rank"] <= 5),
        ("rank6_10", (p["daily_rank"] >= 6) & (p["daily_rank"] <= 10)),
    ]:
        r = _perf(p[cond])
        r["group"] = grp
        groups.append(r)
    topn = pd.DataFrame(groups)[["group", "n", "avg_ret_t1", "med_ret_t1", "win_t1", "avg_ret_t2", "med_ret_t2", "win_t2"]]
    topn.to_csv(OUT_TOPN, index=False, encoding="utf-8-sig")

    # top3 vs top4~5
    top3 = p[p["daily_rank"] <= 3]
    top45 = p[(p["daily_rank"] >= 4) & (p["daily_rank"] <= 5)]
    top3_vs_45 = pd.DataFrame(
        [
            {"group": "top1_3", **_perf(top3)},
            {"group": "top4_5", **_perf(top45)},
        ]
    )[["group", "n", "avg_ret_t1", "med_ret_t1", "win_t1", "avg_ret_t2", "med_ret_t2", "win_t2"]]
    top3_vs_45.to_csv(OUT_TOP3_VS_45, index=False, encoding="utf-8-sig")

    # compare to freeze1 baseline
    base_cov = pd.read_csv(BASE_COVERAGE)
    base_topn = pd.read_csv(BASE_TOPN)
    base_45 = pd.read_csv(BASE_TOP3_VS_45)

    def _m(df: pd.DataFrame, k: str) -> float:
        return float(df.loc[df["metric"] == k, "value"].iloc[0])

    rows = [
        {
            "metric": "candidate_a_share",
            "baseline": _m(base_cov, "candidate_a_share"),
            "tune2": _m(coverage, "candidate_a_share"),
            "delta": _m(coverage, "candidate_a_share") - _m(base_cov, "candidate_a_share"),
        }
    ]
    for grp in ["top2", "top3", "top5"]:
        b = base_topn[base_topn["group"] == grp].iloc[0]
        t = topn[topn["group"] == grp].iloc[0]
        rows.append({"metric": f"{grp}_win_t1", "baseline": float(b["win_t1"]), "tune2": float(t["win_t1"]), "delta": float(t["win_t1"] - b["win_t1"])})
        rows.append({"metric": f"{grp}_win_t2", "baseline": float(b["win_t2"]), "tune2": float(t["win_t2"]), "delta": float(t["win_t2"] - b["win_t2"])})

    b3 = base_45[base_45["group"] == "top1_3"].iloc[0]
    b45 = base_45[base_45["group"] == "top4_5"].iloc[0]
    t3 = top3_vs_45[top3_vs_45["group"] == "top1_3"].iloc[0]
    t45 = top3_vs_45[top3_vs_45["group"] == "top4_5"].iloc[0]
    rows.append(
        {
            "metric": "top1_3_minus_top4_5_win_t2_gap",
            "baseline": float(b3["win_t2"] - b45["win_t2"]),
            "tune2": float(t3["win_t2"] - t45["win_t2"]),
            "delta": float((t3["win_t2"] - t45["win_t2"]) - (b3["win_t2"] - b45["win_t2"])),
        }
    )
    comp = pd.DataFrame(rows)
    comp.to_csv(OUT_COMPARE, index=False, encoding="utf-8-sig")

    # review
    best_t2 = topn.sort_values("win_t2", ascending=False).iloc[0]
    review = [
        "# true_breakout_selector_tune2_review",
        "",
        "Tune2 edits (exactly 3):",
        "- rank_pct_max: 0.30 -> 0.10",
        "- add hard filter: f_chip_winner_rate >= 0.80",
        "- weights: strength 0.40 / industry 0.25 / chip 0.30 / platform 0.05",
        "",
        "## Candidate purity",
        f"- baseline candidate_a_share: {_m(base_cov, 'candidate_a_share'):.4f}",
        f"- tune2 candidate_a_share: {_m(coverage, 'candidate_a_share'):.4f}",
        "",
        "## Top2/3/5 win_t2",
    ]
    for grp in ["top2", "top3", "top5"]:
        b = base_topn[base_topn["group"] == grp].iloc[0]
        t = topn[topn["group"] == grp].iloc[0]
        review.append(f"- {grp}: baseline {float(b['win_t2']):.4f} -> tune2 {float(t['win_t2']):.4f}")
    review += [
        "",
        "## Top3 vs Top4~5 (win_t2 gap)",
        f"- baseline: {float(b3['win_t2'] - b45['win_t2']):.4f}",
        f"- tune2: {float(t3['win_t2'] - t45['win_t2']):.4f}",
        "",
        f"## Best group by win_t2 under tune2: {best_t2['group']} ({float(best_t2['win_t2']):.4f})",
        "## Note",
        "- selector-only comparison; no trading execution optimization, no parameter search.",
    ]
    OUT_REVIEW.write_text("\n".join(review), encoding="utf-8")

    print("Generated:")
    print(" -", OUT_VALIDATION)
    print(" -", OUT_COVERAGE)
    print(" -", OUT_TOPN)
    print(" -", OUT_TOP3_VS_45)
    print(" -", OUT_COMPARE)
    print(" -", OUT_REVIEW)


if __name__ == "__main__":
    main()
