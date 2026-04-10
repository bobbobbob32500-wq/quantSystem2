from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(r"D:\HuaweiAI\quantSystem2")
BASE = ROOT / "data/research/strong_start_full/v4_scan"
SNAPSHOT = BASE / "true_breakout_feature_snapshot_1y.parquet"

OUT_V2_SET = BASE / "true_breakout_selector_v2_validation_set.parquet"
OUT_COMPARE = BASE / "true_breakout_selector_v2_vs_v1_compare.csv"
OUT_HEALTH = BASE / "true_breakout_selector_v2_rule_health.csv"
OUT_AXIS = BASE / "true_breakout_selector_v2_axis_review.csv"
OUT_REVIEW = BASE / "true_breakout_selector_v2_validation_review.md"
OUT_SUMMARY = BASE / "true_breakout_selector_v2_candidate_summary.json"


def _rank01(s: pd.Series, higher: bool = True) -> pd.Series:
    x = pd.to_numeric(s, errors="coerce")
    if not higher:
        x = -x
    return x.rank(method="average", pct=True)


def _build_common_window(ac: pd.DataFrame) -> tuple[pd.DataFrame, str, str, int]:
    max_d = pd.to_datetime(ac["trade_date"].max(), format="%Y%m%d")
    start_90 = max_d - pd.Timedelta(days=90)
    w = ac[pd.to_datetime(ac["trade_date"], format="%Y%m%d") >= start_90].copy()
    a_n = int((w["label_true_breakout"] == "A").sum())
    c_n = int((w["label_true_breakout"] == "C").sum())
    # fallback to 120 days only if too small
    if min(a_n, c_n) < 300:
        start_120 = max_d - pd.Timedelta(days=120)
        w = ac[pd.to_datetime(ac["trade_date"], format="%Y%m%d") >= start_120].copy()
    start = str(w["trade_date"].min())
    end = str(w["trade_date"].max())
    return w, start, end, int(w["trade_date"].nunique())


def _build_v1(df: pd.DataFrame) -> pd.DataFrame:
    x = df.copy()
    x["pass_hard_filters"] = (
        (x["f_trend_close_ma20_gap"] >= 0.02)
        & (x["f_strength_rs20_xsec_q"] >= 0.70)
        & (x["f_ind_rank_pctchg"] >= 0.80)
    )

    x["score_strength_axis"] = pd.concat(
        [
            _rank01(x["f_strength_ret20"], True),
            _rank01(x["f_strength_ret60"], True),
            _rank01(x["f_trend_ma20_ma60_gap"], True),
        ],
        axis=1,
    ).mean(axis=1)
    x["score_industry_axis"] = pd.concat(
        [
            _rank01(x["f_ind_strength_3d"], True),
            _rank01(x["f_ind_strength_5d"], True),
            _rank01(x["f_ind_rank_pctchg"], True),
        ],
        axis=1,
    ).mean(axis=1)
    x["score_chip_axis"] = pd.concat(
        [
            _rank01(x["f_chip_concentration"], True),
            _rank01(x["f_chip_winner_rate"], True),
            _rank01(x["f_chip_stability_std10"], True),
        ],
        axis=1,
    ).mean(axis=1)
    x["score_platform_axis"] = pd.concat(
        [
            _rank01(x["f_platform_range_best"], True),
            _rank01(x["f_platform_compress_ratio"], True),
        ],
        axis=1,
    ).mean(axis=1)
    x["score_total"] = (
        0.40 * x["score_strength_axis"]
        + 0.35 * x["score_industry_axis"]
        + 0.20 * x["score_chip_axis"]
        + 0.05 * x["score_platform_axis"]
    )
    return x


def _build_v2(df: pd.DataFrame) -> pd.DataFrame:
    x = df.copy()
    # v2 hard filters from refinement result
    x["pass_hard_filters"] = (
        (x["f_strength_rs20_xsec_q"] >= 0.72)
        & (x["f_chip_stability_std10"] >= 0.0032)
    )
    x["selector_reject_reason"] = ""
    x.loc[~(x["f_strength_rs20_xsec_q"] >= 0.72), "selector_reject_reason"] += "rs20_q_low|"
    x.loc[~(x["f_chip_stability_std10"] >= 0.0032), "selector_reject_reason"] += "chip_stability_low|"
    x["selector_reject_reason"] = x["selector_reject_reason"].str.strip("|")

    # v2 axes (trend主轴、平台辅助、筹码与行业跟随)
    x["score_trend_axis"] = pd.concat(
        [
            _rank01(x["f_strength_rs20_xsec_q"], True),
            _rank01(x["f_trend_close_ma20_gap"], True),
            _rank01(x["f_trend_close_ma60_gap"], True),
            _rank01(x["f_strength_rs60_xsec_q"], True),
        ],
        axis=1,
    ).mean(axis=1)
    x["score_platform_axis"] = pd.concat(
        [
            _rank01(x["f_platform_range20"], True),
            _rank01(x["f_platform_len"], True),
        ],
        axis=1,
    ).mean(axis=1)
    x["score_chip_axis"] = pd.concat(
        [
            _rank01(x["f_chip_winner_rate"], True),
            _rank01(x["f_chip_low_position120"], True),
            _rank01(x["f_chip_peak_count_sig"], True),
        ],
        axis=1,
    ).mean(axis=1)
    x["score_industry_axis"] = pd.concat(
        [
            _rank01(x["f_ind_peer_strong_count"], True),
            _rank01(x["f_ind_strength_5d"], True),
        ],
        axis=1,
    ).mean(axis=1)

    x["score_total"] = (
        0.45 * x["score_trend_axis"]
        + 0.15 * x["score_platform_axis"]
        + 0.25 * x["score_chip_axis"]
        + 0.15 * x["score_industry_axis"]
    )
    x["selector_explain"] = (
        "hf=" + x["pass_hard_filters"].astype(str)
        + ";trend=" + x["score_trend_axis"].round(3).astype(str)
        + ";platform=" + x["score_platform_axis"].round(3).astype(str)
        + ";chip=" + x["score_chip_axis"].round(3).astype(str)
        + ";industry=" + x["score_industry_axis"].round(3).astype(str)
    )
    return x


def _add_rank_and_candidate(x: pd.DataFrame) -> pd.DataFrame:
    x = x.copy()
    x["rank_pct"] = np.nan
    for d, g in x[x["pass_hard_filters"]].groupby("trade_date"):
        x.loc[g.index, "rank_pct"] = g["score_total"].rank(method="first", ascending=False, pct=True)
    x["rank_bucket"] = "other"
    x.loc[x["rank_pct"] <= 0.10, "rank_bucket"] = "top10"
    x.loc[(x["rank_pct"] > 0.10) & (x["rank_pct"] <= 0.20), "rank_bucket"] = "top20"
    x.loc[(x["rank_pct"] > 0.20) & (x["rank_pct"] <= 0.30), "rank_bucket"] = "top30"
    x["is_candidate"] = x["pass_hard_filters"] & (x["rank_pct"] <= 0.30)
    return x


def _coverage_metrics(x: pd.DataFrame, tag: str) -> dict:
    a = x[x["label_true_breakout"] == "A"]
    c = x[x["label_true_breakout"] == "C"]
    cand = x[x["is_candidate"]]
    return {
        "model": tag,
        "a_total": int(len(a)),
        "c_total": int(len(c)),
        "a_hard_pass_rate": float(a["pass_hard_filters"].mean()) if len(a) else np.nan,
        "c_hard_pass_rate": float(c["pass_hard_filters"].mean()) if len(c) else np.nan,
        "candidate_n": int(len(cand)),
        "candidate_a_n": int((cand["label_true_breakout"] == "A").sum()),
        "candidate_c_n": int((cand["label_true_breakout"] == "C").sum()),
        "candidate_a_share": float((cand["label_true_breakout"] == "A").mean()) if len(cand) else np.nan,
        "candidate_c_share": float((cand["label_true_breakout"] == "C").mean()) if len(cand) else np.nan,
    }


def _ranking_metrics(x: pd.DataFrame, tag: str) -> list[dict]:
    full_a_share = float((x["label_true_breakout"] == "A").mean())
    out = []
    for p, bucket in [(0.10, "top10"), (0.20, "top20"), (0.30, "top30")]:
        sub = x[x["pass_hard_filters"] & (x["rank_pct"] <= p)]
        n = len(sub)
        a_n = int((sub["label_true_breakout"] == "A").sum())
        c_n = int((sub["label_true_breakout"] == "C").sum())
        a_share = (a_n / n) if n else np.nan
        out.append(
            {
                "model": tag,
                "bucket": bucket,
                "sample_n": n,
                "a_n": a_n,
                "c_n": c_n,
                "a_share": a_share,
                "a_share_lift_pts_vs_full": (a_share - full_a_share) if pd.notna(a_share) else np.nan,
            }
        )
    return out


def _rule_health(x: pd.DataFrame, tag: str, axis_cols: list[str]) -> dict:
    axis_std = x[axis_cols].std(skipna=True)
    dominance = axis_std.idxmax() if len(axis_std) else None
    return {
        "model": tag,
        "hard_filter_elimination_rate": float(1 - x["pass_hard_filters"].mean()),
        "score_total_unique": int(x["score_total"].nunique(dropna=True)),
        "score_continuous": bool(x["score_total"].nunique(dropna=True) > 200),
        "candidate_rate": float(x["is_candidate"].mean()),
        "implicit_hard_filter_risk": "high" if x["is_candidate"].mean() < 0.05 else ("low" if x["is_candidate"].mean() > 0.35 else "moderate"),
        "axis_dominance_proxy": dominance,
    }


def _axis_review_v2(x: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for axis in ["score_trend_axis", "score_platform_axis", "score_chip_axis", "score_industry_axis"]:
        a = pd.to_numeric(x.loc[x["label_true_breakout"] == "A", axis], errors="coerce")
        c = pd.to_numeric(x.loc[x["label_true_breakout"] == "C", axis], errors="coerce")
        am, cm = a.median(skipna=True), c.median(skipna=True)
        rows.append(
            {
                "axis": axis,
                "a_median": float(am) if pd.notna(am) else np.nan,
                "c_median": float(cm) if pd.notna(cm) else np.nan,
                "median_gap_a_minus_c": float(am - cm) if pd.notna(am) and pd.notna(cm) else np.nan,
                "direction": "A_higher" if pd.notna(am) and pd.notna(cm) and am > cm else "A_lower_or_flat",
            }
        )
    return pd.DataFrame(rows).sort_values("median_gap_a_minus_c", ascending=False)


def main() -> None:
    snap = pd.read_parquet(SNAPSHOT).copy()
    snap["trade_date"] = snap["trade_date"].astype(str)
    ac = snap[snap["label_true_breakout"].isin(["A", "C"])].copy()
    ac, start, end, days = _build_common_window(ac)

    v1 = _add_rank_and_candidate(_build_v1(ac))
    v2 = _add_rank_and_candidate(_build_v2(ac))

    # v2 validation set output
    v2_out = v2[
        [
            "ts_code",
            "trade_date",
            "label_true_breakout",
            "pass_hard_filters",
            "score_total",
            "score_trend_axis",
            "score_platform_axis",
            "score_chip_axis",
            "score_industry_axis",
            "is_candidate",
            "rank_pct",
            "rank_bucket",
            "selector_reject_reason",
            "selector_explain",
        ]
    ].copy()
    v2_out.to_parquet(OUT_V2_SET, index=False)

    # compare metrics
    cov_rows = [_coverage_metrics(v1, "v1_freeze1"), _coverage_metrics(v2, "v2_draft")]
    rank_rows = _ranking_metrics(v1, "v1_freeze1") + _ranking_metrics(v2, "v2_draft")
    rank_piv = pd.DataFrame(rank_rows).pivot(
        index="model",
        columns="bucket",
        values=["a_share", "a_share_lift_pts_vs_full", "sample_n"],
    )
    rank_piv.columns = [f"{a}_{b}" for a, b in rank_piv.columns]
    rank_piv = rank_piv.reset_index()
    cmp_df = pd.DataFrame(cov_rows).merge(rank_piv, on="model", how="left")
    cmp_df.to_csv(OUT_COMPARE, index=False, encoding="utf-8-sig")

    # rule health
    h1 = _rule_health(v1, "v1_freeze1", ["score_strength_axis", "score_industry_axis", "score_chip_axis", "score_platform_axis"])
    h2 = _rule_health(v2, "v2_draft", ["score_trend_axis", "score_platform_axis", "score_chip_axis", "score_industry_axis"])
    health = pd.DataFrame([h1, h2])
    health.to_csv(OUT_HEALTH, index=False, encoding="utf-8-sig")

    # axis review (v2 only)
    axis = _axis_review_v2(v2)
    axis.to_csv(OUT_AXIS, index=False, encoding="utf-8-sig")

    # summary json
    summary = {
        "window": {"start": start, "end": end, "trade_days": days, "sample_n_ac": int(len(ac))},
        "conclusion": {
            "v2_candidate_a_share": float(cov_rows[1]["candidate_a_share"]),
            "v1_candidate_a_share": float(cov_rows[0]["candidate_a_share"]),
            "v2_better_on_purity": bool(cov_rows[1]["candidate_a_share"] > cov_rows[0]["candidate_a_share"]),
        },
    }
    OUT_SUMMARY.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    # review md
    c = cmp_df.set_index("model")
    top10_v1 = float(c.loc["v1_freeze1", "a_share_top10"])
    top10_v2 = float(c.loc["v2_draft", "a_share_top10"])
    top20_v1 = float(c.loc["v1_freeze1", "a_share_top20"])
    top20_v2 = float(c.loc["v2_draft", "a_share_top20"])
    top30_v1 = float(c.loc["v1_freeze1", "a_share_top30"])
    top30_v2 = float(c.loc["v2_draft", "a_share_top30"])
    strongest_axis = axis.iloc[0]["axis"] if len(axis) else "n/a"
    weakest_axis = axis.iloc[-1]["axis"] if len(axis) else "n/a"
    lines = [
        "# true_breakout_selector_v2_validation_review",
        "",
        f"- window: {start} ~ {end} ({days} trading days)",
        f"- A/C sample: {len(ac)}",
        "",
        "## Purity and coverage",
        f"- v1 candidate A share: {cov_rows[0]['candidate_a_share']:.4f}",
        f"- v2 candidate A share: {cov_rows[1]['candidate_a_share']:.4f}",
        f"- v1 candidate size: {cov_rows[0]['candidate_n']}",
        f"- v2 candidate size: {cov_rows[1]['candidate_n']}",
        "",
        "## Top-bucket A share",
        f"- Top10: v1 {top10_v1:.4f} -> v2 {top10_v2:.4f}",
        f"- Top20: v1 {top20_v1:.4f} -> v2 {top20_v2:.4f}",
        f"- Top30: v1 {top30_v1:.4f} -> v2 {top30_v2:.4f}",
        "",
        "## Rule health",
        health.to_string(index=False),
        "",
        "## Axis review (v2)",
        axis.to_string(index=False),
        "",
        f"- strongest axis: {strongest_axis}",
        f"- weakest axis: {weakest_axis}",
        "",
        "Conclusion: selector-only validation; no entry/exit/execution assumptions.",
    ]
    OUT_REVIEW.write_text("\n".join(lines), encoding="utf-8")

    print("Generated:")
    print(" -", OUT_V2_SET)
    print(" -", OUT_COMPARE)
    print(" -", OUT_HEALTH)
    print(" -", OUT_AXIS)
    print(" -", OUT_REVIEW)
    print(" -", OUT_SUMMARY)


if __name__ == "__main__":
    main()
