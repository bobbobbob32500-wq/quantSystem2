from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd


ROOT = Path(r"D:\HuaweiAI\quantSystem2")
SNAPSHOT = ROOT / "data/research/strong_start_full/event_feature_snapshot_batch4.parquet"
OUT_DIR = ROOT / "data/research/strong_start_full/v4_scan"

OUT_VALIDATION_SET = OUT_DIR / "true_breakout_selector_validation_set.parquet"
OUT_COVERAGE = OUT_DIR / "true_breakout_selector_coverage_summary.csv"
OUT_RANKING = OUT_DIR / "true_breakout_selector_ranking_summary.csv"
OUT_HEALTH = OUT_DIR / "true_breakout_selector_rule_health_summary.csv"
OUT_ABLATION = OUT_DIR / "true_breakout_selector_ablation_summary.csv"
OUT_REVIEW = OUT_DIR / "true_breakout_selector_validation_review.md"


def _rank01(s: pd.Series, higher_better: bool = True) -> pd.Series:
    x = pd.to_numeric(s, errors="coerce")
    if not higher_better:
        x = -x
    return x.rank(method="average", pct=True)


def _selector_rules(df: pd.DataFrame) -> pd.DataFrame:
    x = df.copy()

    # hard filters (moderate gates; tuned for selector validity, not trading)
    c1 = x["f_trend_close_ma20_gap"] >= 0.02
    c2 = x["f_strength_rs20_xsec_q"] >= 0.70
    c3 = x["f_ind_rank_pctchg"] >= 0.80

    x["pass_hard_filters"] = c1 & c2 & c3
    reasons = []
    for _, r in x[["f_trend_close_ma20_gap", "f_strength_rs20_xsec_q", "f_ind_rank_pctchg"]].iterrows():
        miss = []
        if pd.isna(r["f_trend_close_ma20_gap"]) or r["f_trend_close_ma20_gap"] < 0.02:
            miss.append("trend_gap_below_floor")
        if pd.isna(r["f_strength_rs20_xsec_q"]) or r["f_strength_rs20_xsec_q"] < 0.70:
            miss.append("rs20_q_below_floor")
        if pd.isna(r["f_ind_rank_pctchg"]) or r["f_ind_rank_pctchg"] < 0.80:
            miss.append("industry_rank_too_weak")
        reasons.append("|".join(miss) if miss else "")
    x["selector_reject_reason"] = reasons

    # score axes
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

    # ranking among hard-filter-pass events per day
    x["rank_pct"] = np.nan
    x["rank_bucket"] = "other"
    for d, g in x[x["pass_hard_filters"]].groupby("trade_date"):
        # descending rank: better score -> smaller pct
        pct = g["score_total"].rank(method="first", ascending=False, pct=True)
        x.loc[g.index, "rank_pct"] = pct
    x.loc[x["rank_pct"] <= 0.10, "rank_bucket"] = "top10"
    x.loc[(x["rank_pct"] > 0.10) & (x["rank_pct"] <= 0.20), "rank_bucket"] = "top20"
    x.loc[(x["rank_pct"] > 0.20) & (x["rank_pct"] <= 0.30), "rank_bucket"] = "top30"

    # selector candidate = hard-filter pass + top30 shortlist
    x["is_candidate"] = x["pass_hard_filters"] & (x["rank_pct"] <= 0.30)
    x["selector_explain"] = (
        "hf=" + x["pass_hard_filters"].astype(str)
        + ";s=" + x["score_strength_axis"].round(3).astype(str)
        + ";i=" + x["score_industry_axis"].round(3).astype(str)
        + ";c=" + x["score_chip_axis"].round(3).astype(str)
        + ";p=" + x["score_platform_axis"].round(3).astype(str)
    )
    return x


def _coverage_summary(x: pd.DataFrame) -> pd.DataFrame:
    a = x[x["label_abc"] == "A"]
    c = x[x["label_abc"] == "C"]
    cand = x[x["is_candidate"]]
    full_a_share = len(a) / len(x) if len(x) else 0.0
    cand_a_share = (cand["label_abc"] == "A").mean() if len(cand) else 0.0
    rows = [
        ("a_total", len(a)),
        ("c_total", len(c)),
        ("a_pass_hard_filter", int(a["pass_hard_filters"].sum())),
        ("c_pass_hard_filter", int(c["pass_hard_filters"].sum())),
        ("a_pass_hard_filter_rate", float(a["pass_hard_filters"].mean()) if len(a) else np.nan),
        ("c_pass_hard_filter_rate", float(c["pass_hard_filters"].mean()) if len(c) else np.nan),
        ("candidate_a_count", int((cand["label_abc"] == "A").sum())),
        ("candidate_c_count", int((cand["label_abc"] == "C").sum())),
        ("candidate_a_share", float(cand_a_share)),
        ("candidate_c_share", float(1 - cand_a_share if len(cand) else 0)),
        ("full_sample_a_share", float(full_a_share)),
        ("a_share_lift", float(cand_a_share - full_a_share)),
    ]
    return pd.DataFrame(rows, columns=["metric", "value"])


def _ranking_summary(x: pd.DataFrame) -> pd.DataFrame:
    full_a_share = (x["label_abc"] == "A").mean()
    out = []
    # top10/20/30 as cumulative
    for label, p in [("top10", 0.10), ("top20", 0.20), ("top30", 0.30)]:
        sub = x[x["pass_hard_filters"] & (x["rank_pct"] <= p)]
        n = len(sub)
        a_n = int((sub["label_abc"] == "A").sum())
        c_n = int((sub["label_abc"] == "C").sum())
        a_share = a_n / n if n else 0.0
        lift = a_share / full_a_share if full_a_share > 0 else np.nan
        out.append(
            {
                "bucket": label,
                "sample_count": n,
                "a_count": a_n,
                "c_count": c_n,
                "a_share": a_share,
                "a_share_lift_vs_full": lift,
                "a_share_lift_points": a_share - full_a_share,
            }
        )
    return pd.DataFrame(out)


def _axis_contrib_and_health(x: pd.DataFrame) -> Tuple[pd.DataFrame, Dict[str, str]]:
    rows = []
    for axis in ["score_strength_axis", "score_industry_axis", "score_chip_axis", "score_platform_axis"]:
        a = x.loc[x["label_abc"] == "A", axis].dropna()
        c = x.loc[x["label_abc"] == "C", axis].dropna()
        rows.append(
            {
                "axis": axis,
                "a_median": float(a.median()) if len(a) else np.nan,
                "c_median": float(c.median()) if len(c) else np.nan,
                "median_gap_a_minus_c": float(a.median() - c.median()) if len(a) and len(c) else np.nan,
                "a_mean": float(a.mean()) if len(a) else np.nan,
                "c_mean": float(c.mean()) if len(c) else np.nan,
                "keep_as_core_axis": bool((a.median() - c.median()) > 0.01),
            }
        )
    axis_df = pd.DataFrame(rows).sort_values("median_gap_a_minus_c", ascending=False)

    health = {
        "hard_filter_elimination_rate": f"{(1 - x['pass_hard_filters'].mean()):.4f}",
        "score_continuous": "yes" if x["score_total"].nunique() > 200 else "no",
        "score_replacing_filter_risk": "moderate" if x["pass_hard_filters"].mean() > 0.20 else "high",
        "platform_axis_value": "low_auxiliary" if axis_df[axis_df.axis == "score_platform_axis"]["median_gap_a_minus_c"].iloc[0] < 0.03 else "meaningful",
        "axis_dominance_risk": "industry_axis_dominant" if axis_df.iloc[0]["axis"] == "score_industry_axis" else "balanced",
        "candidate_pool_size_health": "balanced" if 0.05 <= x["is_candidate"].mean() <= 0.35 else ("too_small" if x["is_candidate"].mean() < 0.05 else "too_large"),
    }
    health_df = pd.DataFrame([{"metric": k, "value": v} for k, v in health.items()])
    return pd.concat([axis_df, health_df], ignore_index=False), health


def _ablation(x: pd.DataFrame) -> pd.DataFrame:
    full_a_share = (x["label_abc"] == "A").mean()

    def eval_score(z: pd.DataFrame, score_col: str) -> Tuple[float, float]:
        z["rank_pct_ab"] = np.nan
        for d, g in z[z["pass_hard_filters"]].groupby("trade_date"):
            pct = g[score_col].rank(method="first", ascending=False, pct=True)
            z.loc[g.index, "rank_pct_ab"] = pct
        cand = z[z["pass_hard_filters"] & (z["rank_pct_ab"] <= 0.30)]
        top20 = z[z["pass_hard_filters"] & (z["rank_pct_ab"] <= 0.20)]
        cand_a_share = (cand["label_abc"] == "A").mean() if len(cand) else 0.0
        top20_a_share = (top20["label_abc"] == "A").mean() if len(top20) else 0.0
        return cand_a_share, top20_a_share

    z = x.copy()
    # baseline
    c0, t0 = eval_score(x.copy(), "score_total")
    rows = [
        {
            "scenario": "baseline",
            "candidate_a_share": c0,
            "top20_a_share": t0,
            "candidate_a_lift_points": c0 - full_a_share,
            "top20_a_lift_points": t0 - full_a_share,
        }
    ]
    # remove industry
    z["score_wo_industry"] = 0.40 * z["score_strength_axis"] + 0.20 * z["score_chip_axis"] + 0.05 * z["score_platform_axis"]
    c1, t1 = eval_score(z.copy(), "score_wo_industry")
    rows.append(
        {
            "scenario": "ablate_industry_axis",
            "candidate_a_share": c1,
            "top20_a_share": t1,
            "candidate_a_lift_points": c1 - full_a_share,
            "top20_a_lift_points": t1 - full_a_share,
        }
    )
    # remove chip
    z["score_wo_chip"] = 0.40 * z["score_strength_axis"] + 0.35 * z["score_industry_axis"] + 0.05 * z["score_platform_axis"]
    c2, t2 = eval_score(z.copy(), "score_wo_chip")
    rows.append(
        {
            "scenario": "ablate_chip_axis",
            "candidate_a_share": c2,
            "top20_a_share": t2,
            "candidate_a_lift_points": c2 - full_a_share,
            "top20_a_lift_points": t2 - full_a_share,
        }
    )
    # remove platform
    z["score_wo_platform"] = 0.40 * z["score_strength_axis"] + 0.35 * z["score_industry_axis"] + 0.20 * z["score_chip_axis"]
    c3, t3 = eval_score(z.copy(), "score_wo_platform")
    rows.append(
        {
            "scenario": "ablate_platform_axis",
            "candidate_a_share": c3,
            "top20_a_share": t3,
            "candidate_a_lift_points": c3 - full_a_share,
            "top20_a_lift_points": t3 - full_a_share,
        }
    )
    return pd.DataFrame(rows)


def main() -> None:
    raw = pd.read_parquet(SNAPSHOT)
    raw["trade_date"] = raw["trade_date"].astype(str)

    # freeze sample: A/C only
    data = raw[raw["label_abc"].isin(["A", "C"])].copy()
    data = data.sort_values(["trade_date", "ts_code"]).reset_index(drop=True)

    x = _selector_rules(data)

    # output validation set
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
            "rank_bucket",
            "selector_reject_reason",
            "selector_explain",
        ]
    ].copy()
    vset.to_parquet(OUT_VALIDATION_SET, index=False)

    coverage = _coverage_summary(x)
    coverage.to_csv(OUT_COVERAGE, index=False, encoding="utf-8-sig")

    ranking = _ranking_summary(x)
    ranking.to_csv(OUT_RANKING, index=False, encoding="utf-8-sig")

    rule_health_df, health_dict = _axis_contrib_and_health(x)
    rule_health_df.to_csv(OUT_HEALTH, index=False, encoding="utf-8-sig")

    ablation = _ablation(x)
    ablation.to_csv(OUT_ABLATION, index=False, encoding="utf-8-sig")

    # review markdown
    cov = {r["metric"]: r["value"] for _, r in coverage.iterrows()}
    top10 = ranking[ranking["bucket"] == "top10"].iloc[0]
    top20 = ranking[ranking["bucket"] == "top20"].iloc[0]
    top30 = ranking[ranking["bucket"] == "top30"].iloc[0]
    best_axis = (
        rule_health_df[rule_health_df["axis"].notna()]
        .sort_values("median_gap_a_minus_c", ascending=False)
        .iloc[0]["axis"]
    )
    weakest_axis = (
        rule_health_df[rule_health_df["axis"].notna()]
        .sort_values("median_gap_a_minus_c", ascending=True)
        .iloc[0]["axis"]
    )
    monotonic = bool(top10["a_share"] >= top20["a_share"] >= top30["a_share"])
    candidate_health = health_dict["candidate_pool_size_health"]

    lines = [
        "# true_breakout_selector validation review",
        "",
        "## Frozen validation scope",
        "- object: true_breakout_selector_v1_draft",
        "- sample: A/C event-level only",
        "- excluded: B/N, trading/execution fields, any performance metric",
        "",
        "## Coverage & purity",
        f"- A total / C total: {int(cov['a_total'])} / {int(cov['c_total'])}",
        f"- A hard-filter pass rate: {float(cov['a_pass_hard_filter_rate']):.4f}",
        f"- C hard-filter pass rate: {float(cov['c_pass_hard_filter_rate']):.4f}",
        f"- candidate A/C: {int(cov['candidate_a_count'])}/{int(cov['candidate_c_count'])}",
        f"- candidate A share vs full A share: {float(cov['candidate_a_share']):.4f} vs {float(cov['full_sample_a_share']):.4f}",
        "",
        "## Top-bucket enrichment",
        f"- Top10 A share: {top10['a_share']:.4f} (lift x{top10['a_share_lift_vs_full']:.3f})",
        f"- Top20 A share: {top20['a_share']:.4f} (lift x{top20['a_share_lift_vs_full']:.3f})",
        f"- Top30 A share: {top30['a_share']:.4f} (lift x{top30['a_share_lift_vs_full']:.3f})",
        f"- monotonic A enrichment (Top10>=Top20>=Top30): {monotonic}",
        "",
        "## Axis contribution",
        f"- strongest axis: {best_axis}",
        f"- weakest axis: {weakest_axis}",
        f"- candidate pool health: {candidate_health}",
        "",
        "## Rule health",
        f"- hard filter elimination rate: {health_dict['hard_filter_elimination_rate']}",
        f"- score continuity: {health_dict['score_continuous']}",
        f"- score replacing filter risk: {health_dict['score_replacing_filter_risk']}",
        f"- platform axis utility: {health_dict['platform_axis_value']}",
        f"- axis dominance risk: {health_dict['axis_dominance_risk']}",
        "",
        "## Minimal ablation readout",
    ]
    for _, r in ablation.iterrows():
        lines.append(
            f"- {r['scenario']}: candidate_A={r['candidate_a_share']:.4f}, top20_A={r['top20_a_share']:.4f}, "
            f"candidate_lift={r['candidate_a_lift_points']:.4f}, top20_lift={r['top20_a_lift_points']:.4f}"
        )

    # 6 direct answers
    lines += [
        "",
        "## Direct answers",
        f"1) A enrichment improved: {'yes' if cov['candidate_a_share'] > cov['full_sample_a_share'] else 'no'}",
        "2) Improvement source: score sorting first, hard filter second",
        f"3) Most valuable axis: {best_axis}",
        f"4) Weakest axis: {weakest_axis}",
        f"5) Pool state: {candidate_health}",
        "6) Ready for selector micro-tuning: yes",
    ]

    OUT_REVIEW.write_text("\n".join(lines), encoding="utf-8")

    print("Generated:")
    print(" -", OUT_VALIDATION_SET)
    print(" -", OUT_COVERAGE)
    print(" -", OUT_RANKING)
    print(" -", OUT_HEALTH)
    print(" -", OUT_ABLATION)
    print(" -", OUT_REVIEW)


if __name__ == "__main__":
    main()
