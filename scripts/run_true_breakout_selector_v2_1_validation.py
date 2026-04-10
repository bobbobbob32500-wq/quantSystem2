from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(r"D:\HuaweiAI\quantSystem2")
BASE = ROOT / "data/research/strong_start_full/v4_scan"
SNAPSHOT = BASE / "true_breakout_feature_snapshot_1y.parquet"

OUT_COMPARE = BASE / "true_breakout_selector_v2_1_vs_v2_compare.csv"
OUT_HEALTH = BASE / "true_breakout_selector_v2_1_rule_health.csv"
OUT_AXIS = BASE / "true_breakout_selector_v2_1_axis_review.csv"
OUT_REVIEW = BASE / "true_breakout_selector_v2_1_validation_review.md"
OUT_DRAFT = BASE / "true_breakout_selector_v2_1_draft.md"
OUT_FIX_NOTE = BASE / "true_breakout_selector_v2_1_fix_note.md"

WINDOW_START = "20251230"
WINDOW_END = "20260330"


def _rank01(s: pd.Series, higher: bool = True) -> pd.Series:
    x = pd.to_numeric(s, errors="coerce")
    if not higher:
        x = -x
    return x.rank(method="average", pct=True)


def _add_rank_and_candidate(x: pd.DataFrame) -> pd.DataFrame:
    x = x.copy()
    x["rank_pct"] = np.nan
    for _, g in x[x["pass_hard_filters"]].groupby("trade_date"):
        x.loc[g.index, "rank_pct"] = g["score_total"].rank(method="first", ascending=False, pct=True)
    x["rank_bucket"] = "other"
    x.loc[x["rank_pct"] <= 0.10, "rank_bucket"] = "top10"
    x.loc[(x["rank_pct"] > 0.10) & (x["rank_pct"] <= 0.20), "rank_bucket"] = "top20"
    x.loc[(x["rank_pct"] > 0.20) & (x["rank_pct"] <= 0.30), "rank_bucket"] = "top30"
    x["is_candidate"] = x["pass_hard_filters"] & (x["rank_pct"] <= 0.30)
    return x


def _build_v2(df: pd.DataFrame) -> pd.DataFrame:
    x = df.copy()
    x["pass_hard_filters"] = (
        (x["f_strength_rs20_xsec_q"] >= 0.72)
        & (x["f_chip_stability_std10"] >= 0.0032)
    )
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
    return _add_rank_and_candidate(x)


def _build_v2_1(df: pd.DataFrame) -> pd.DataFrame:
    x = df.copy()
    # fix-1: move chip stability out of hard filters
    x["pass_hard_filters"] = (x["f_strength_rs20_xsec_q"] >= 0.72)

    # fix-2: trend/industry de-collinearity
    # Trend core: keep rs20 as core, keep ma20 gap as aux only.
    trend_core = _rank01(x["f_strength_rs20_xsec_q"], True)
    trend_aux = _rank01(x["f_trend_close_ma20_gap"], True)
    x["score_trend_axis"] = 0.70 * trend_core + 0.30 * trend_aux

    # fix-3: rebuild platform axis with stable/sign-consistent factors only
    # lower compress/range is better for A in current window
    x["score_platform_axis"] = (
        0.70 * _rank01(x["f_platform_compress_ratio"], higher=False)
        + 0.30 * _rank01(x["f_platform_range30"], higher=False)
    )

    # chip axis: keep winner/position core, chip_stability downgraded to scoring-only aux
    x["score_chip_axis"] = (
        0.45 * _rank01(x["f_chip_winner_rate"], True)
        + 0.35 * _rank01(x["f_chip_low_position120"], True)
        + 0.20 * _rank01(x["f_chip_stability_std10"], True)
    )

    # industry axis as auxiliary purifier (reduced weight downstream)
    x["score_industry_axis"] = (
        0.75 * _rank01(x["f_ind_peer_strong_count"], True)
        + 0.25 * _rank01(x["f_ind_strength_5d"], True)
    )

    x["score_total"] = (
        0.50 * x["score_trend_axis"]
        + 0.10 * x["score_platform_axis"]
        + 0.25 * x["score_chip_axis"]
        + 0.15 * x["score_industry_axis"]
    )
    return _add_rank_and_candidate(x)


def _coverage_metrics(x: pd.DataFrame, tag: str) -> dict:
    a = x[x["label_true_breakout"] == "A"]
    c = x[x["label_true_breakout"] == "C"]
    cand = x[x["is_candidate"]]
    return {
        "model": tag,
        "window_a_share_full": float((x["label_true_breakout"] == "A").mean()),
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
    rows: list[dict] = []
    for p, bucket in [(0.10, "top10"), (0.20, "top20"), (0.30, "top30")]:
        sub = x[x["pass_hard_filters"] & (x["rank_pct"] <= p)]
        n = len(sub)
        a_n = int((sub["label_true_breakout"] == "A").sum())
        c_n = int((sub["label_true_breakout"] == "C").sum())
        a_share = (a_n / n) if n else np.nan
        rows.append(
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
    return rows


def _rule_health(x: pd.DataFrame, tag: str) -> dict:
    axis_cols = ["score_trend_axis", "score_platform_axis", "score_chip_axis", "score_industry_axis"]
    axis_std = x[axis_cols].std(skipna=True)
    dominance = axis_std.idxmax() if len(axis_std) else None
    dominance_share = float(axis_std.max() / axis_std.sum()) if axis_std.sum() and pd.notna(axis_std.sum()) else np.nan
    return {
        "model": tag,
        "hard_filter_elimination_rate": float(1 - x["pass_hard_filters"].mean()),
        "candidate_rate": float(x["is_candidate"].mean()),
        "score_total_unique": int(x["score_total"].nunique(dropna=True)),
        "score_continuous": bool(x["score_total"].nunique(dropna=True) > 200),
        "implicit_hard_filter_risk": "high"
        if x["is_candidate"].mean() < 0.05
        else ("low" if x["is_candidate"].mean() > 0.35 else "moderate"),
        "axis_dominance_proxy": dominance,
        "axis_dominance_share": dominance_share,
        "axis_imbalance_risk": "high" if pd.notna(dominance_share) and dominance_share > 0.45 else ("moderate" if pd.notna(dominance_share) and dominance_share > 0.35 else "low"),
    }


def _axis_review(x: pd.DataFrame, tag: str) -> pd.DataFrame:
    rows = []
    for axis in ["score_trend_axis", "score_platform_axis", "score_chip_axis", "score_industry_axis"]:
        a = pd.to_numeric(x.loc[x["label_true_breakout"] == "A", axis], errors="coerce")
        c = pd.to_numeric(x.loc[x["label_true_breakout"] == "C", axis], errors="coerce")
        sa = pd.to_numeric(x.loc[(x["label_true_breakout"] == "A") & (x["is_candidate"]), axis], errors="coerce")
        sc = pd.to_numeric(x.loc[(x["label_true_breakout"] == "C") & (x["is_candidate"]), axis], errors="coerce")
        am, cm = a.median(skipna=True), c.median(skipna=True)
        sam, scm = sa.median(skipna=True), sc.median(skipna=True)
        rows.append(
            {
                "model": tag,
                "axis": axis,
                "a_median": float(am) if pd.notna(am) else np.nan,
                "c_median": float(cm) if pd.notna(cm) else np.nan,
                "a_minus_c": float(am - cm) if pd.notna(am) and pd.notna(cm) else np.nan,
                "selected_a_median": float(sam) if pd.notna(sam) else np.nan,
                "selected_c_median": float(scm) if pd.notna(scm) else np.nan,
                "selected_a_minus_c": float(sam - scm) if pd.notna(sam) and pd.notna(scm) else np.nan,
            }
        )
    return pd.DataFrame(rows)


def _quadrants(x: pd.DataFrame, tag: str) -> pd.DataFrame:
    q = []
    for name, cond in [
        ("selected_A", (x["is_candidate"]) & (x["label_true_breakout"] == "A")),
        ("selected_C", (x["is_candidate"]) & (x["label_true_breakout"] == "C")),
        ("missed_A", (~x["is_candidate"]) & (x["label_true_breakout"] == "A")),
        ("rejected_C", (~x["is_candidate"]) & (x["label_true_breakout"] == "C")),
    ]:
        q.append({"model": tag, "quadrant": name, "n": int(cond.sum())})
    return pd.DataFrame(q)


def main() -> None:
    snap = pd.read_parquet(SNAPSHOT).copy()
    snap["trade_date"] = snap["trade_date"].astype(str)
    ac = snap[snap["label_true_breakout"].isin(["A", "C"])].copy()
    ac = ac[(ac["trade_date"] >= WINDOW_START) & (ac["trade_date"] <= WINDOW_END)].copy()

    v2 = _build_v2(ac)
    v21 = _build_v2_1(ac)

    cov = pd.DataFrame([_coverage_metrics(v2, "v2_draft"), _coverage_metrics(v21, "v2.1_draft")])
    rank = pd.DataFrame(_ranking_metrics(v2, "v2_draft") + _ranking_metrics(v21, "v2.1_draft"))
    rank_piv = rank.pivot(index="model", columns="bucket", values=["a_share", "a_share_lift_pts_vs_full", "sample_n"])
    rank_piv.columns = [f"{a}_{b}" for a, b in rank_piv.columns]
    rank_piv = rank_piv.reset_index()

    quad = pd.concat([_quadrants(v2, "v2_draft"), _quadrants(v21, "v2.1_draft")], ignore_index=True)
    quad_piv = quad.pivot(index="model", columns="quadrant", values="n").reset_index()
    compare = cov.merge(rank_piv, on="model", how="left").merge(quad_piv, on="model", how="left")
    compare.to_csv(OUT_COMPARE, index=False, encoding="utf-8-sig")

    health = pd.DataFrame([_rule_health(v2, "v2_draft"), _rule_health(v21, "v2.1_draft")])
    health.to_csv(OUT_HEALTH, index=False, encoding="utf-8-sig")

    axis = pd.concat([_axis_review(v2, "v2_draft"), _axis_review(v21, "v2.1_draft")], ignore_index=True)
    axis.to_csv(OUT_AXIS, index=False, encoding="utf-8-sig")

    draft_lines = [
        "# true_breakout_selector_v2_1_draft",
        "",
        "## Universe",
        "- Same as v2 draft (main-board-only, minimum listing days, minimum liquidity, risk-name exclusion).",
        "",
        "## Hard filters (revised)",
        "- Keep: `f_strength_rs20_xsec_q >= 0.72`",
        "- Removed from hard filter: `f_chip_stability_std10` (moved to chip scoring axis).",
        "",
        "## Scoring axes (revised)",
        "- trend axis: core `f_strength_rs20_xsec_q`, aux `f_trend_close_ma20_gap` (de-collinearity by dropping duplicated trend items).",
        "- platform axis: `f_platform_compress_ratio` (lower-better), `f_platform_range30` (lower-better).",
        "- chip axis: `f_chip_winner_rate`, `f_chip_low_position120`, plus downgraded-scoring `f_chip_stability_std10`.",
        "- industry axis: `f_ind_peer_strong_count` + light `f_ind_strength_5d` (auxiliary purifier, reduced amplification).",
        "",
        "## Weights (revised)",
        "- trend: 0.50",
        "- platform: 0.10",
        "- chip: 0.25",
        "- industry: 0.15",
        "",
        "## Candidate output",
        "- Keep rank-based output framework (top10/top20/top30 buckets for selector validation).",
    ]
    OUT_DRAFT.write_text("\n".join(draft_lines), encoding="utf-8")

    fix_lines = [
        "# true_breakout_selector_v2_1_fix_note",
        "",
        "1) Fix-1: `f_chip_stability_std10` removed from hard filter, moved into chip scoring axis.",
        "2) Fix-2: trend/industry de-collinearity: trend kept one core + one aux; industry stays auxiliary and not co-amplified.",
        "3) Fix-3: platform axis rebuilt with sign-consistent, stable positive-separation factors only.",
    ]
    OUT_FIX_NOTE.write_text("\n".join(fix_lines), encoding="utf-8")

    c = compare.set_index("model")
    h = health.set_index("model")
    a_v2 = float(c.loc["v2_draft", "candidate_a_share"])
    a_v21 = float(c.loc["v2.1_draft", "candidate_a_share"])
    mA_v2 = int(c.loc["v2_draft", "missed_A"])
    mA_v21 = int(c.loc["v2.1_draft", "missed_A"])
    sC_v2 = int(c.loc["v2_draft", "selected_C"])
    sC_v21 = int(c.loc["v2.1_draft", "selected_C"])

    review_lines = [
        "# true_breakout_selector_v2_1_validation_review",
        "",
        f"- window: {WINDOW_START} ~ {WINDOW_END}",
        f"- sample_n(A/C): {len(ac)}",
        "",
        "## Core compare (v2 vs v2.1)",
        compare.to_string(index=False),
        "",
        "## Rule health",
        health.to_string(index=False),
        "",
        "## Axis review",
        axis.to_string(index=False),
        "",
        "## Direct answers",
        f"- candidate A share fixed? v2={a_v2:.4f}, v2.1={a_v21:.4f}, delta={a_v21-a_v2:+.4f}",
        f"- missed_A improved? v2={mA_v2}, v2.1={mA_v21}, delta={mA_v21-mA_v2:+d}",
        f"- selected_C reduced? v2={sC_v2}, v2.1={sC_v21}, delta={sC_v21-sC_v2:+d}",
        f"- platform axis selected_A-selected_C (v2.1): "
        f"{axis[(axis.model=='v2.1_draft')&(axis.axis=='score_platform_axis')]['selected_a_minus_c'].iloc[0]:+.4f}",
        f"- ready for candidate-freeze gate? {'yes' if (a_v21 > c.loc['v2.1_draft','window_a_share_full']) else 'no'}",
        "",
        "Note: research-layer validation only; no entry/exit/execution/return backtest.",
    ]
    OUT_REVIEW.write_text("\n".join(review_lines), encoding="utf-8")

    print("Generated:")
    print(" -", OUT_DRAFT)
    print(" -", OUT_COMPARE)
    print(" -", OUT_HEALTH)
    print(" -", OUT_AXIS)
    print(" -", OUT_REVIEW)
    print(" -", OUT_FIX_NOTE)


if __name__ == "__main__":
    main()

