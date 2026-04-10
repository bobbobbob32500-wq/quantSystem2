from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(r"D:\HuaweiAI\quantSystem2")
BASE = ROOT / "data/research/strong_start_full/v4_scan"
SNAPSHOT = BASE / "true_breakout_feature_snapshot_1y.parquet"

OUT_DRAFT = BASE / "true_breakout_selector_v2_2_draft.md"
OUT_COMPARE = BASE / "true_breakout_selector_v2_2_vs_v2_1_compare.csv"
OUT_HEALTH = BASE / "true_breakout_selector_v2_2_rule_health.csv"
OUT_REVIEW = BASE / "true_breakout_selector_v2_2_validation_review.md"
OUT_FIX_NOTE = BASE / "true_breakout_selector_v2_2_trend_fix_note.md"

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


def _build_v2_1(df: pd.DataFrame) -> pd.DataFrame:
    x = df.copy()
    x["pass_hard_filters"] = (x["f_strength_rs20_xsec_q"] >= 0.72)

    trend_core = _rank01(x["f_strength_rs20_xsec_q"], True)
    trend_aux = _rank01(x["f_trend_close_ma20_gap"], True)
    x["score_trend_axis"] = 0.70 * trend_core + 0.30 * trend_aux

    x["score_platform_axis"] = (
        0.70 * _rank01(x["f_platform_compress_ratio"], higher=False)
        + 0.30 * _rank01(x["f_platform_range30"], higher=False)
    )
    x["score_chip_axis"] = (
        0.45 * _rank01(x["f_chip_winner_rate"], True)
        + 0.35 * _rank01(x["f_chip_low_position120"], True)
        + 0.20 * _rank01(x["f_chip_stability_std10"], True)
    )
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


def _build_v2_2(df: pd.DataFrame) -> pd.DataFrame:
    x = df.copy()
    # keep hard filters exactly as v2.1
    x["pass_hard_filters"] = (x["f_strength_rs20_xsec_q"] >= 0.72)

    # trend fix-1: single core with cap
    core = _rank01(x["f_strength_rs20_xsec_q"], True).clip(upper=0.90)

    # trend fix-2/3: remove three misleading factors from main sort,
    # remaining trend atoms only weak auxiliary
    weak_aux_cols = [
        "f_strength_ret20",
        "f_strength_rs60_xsec_q",
        "f_trend_close_ma20_gap",
        "f_trend_ma20_ma60_gap",
        "f_trend_ma20_slope5",
    ]
    aux = pd.concat([_rank01(x[c], True) for c in weak_aux_cols], axis=1).mean(axis=1)
    x["score_trend_axis"] = 0.90 * core + 0.10 * aux

    # keep other axes unchanged from v2.1
    x["score_platform_axis"] = (
        0.70 * _rank01(x["f_platform_compress_ratio"], higher=False)
        + 0.30 * _rank01(x["f_platform_range30"], higher=False)
    )
    x["score_chip_axis"] = (
        0.45 * _rank01(x["f_chip_winner_rate"], True)
        + 0.35 * _rank01(x["f_chip_low_position120"], True)
        + 0.20 * _rank01(x["f_chip_stability_std10"], True)
    )
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
        "candidate_n": int(len(cand)),
        "candidate_a_n": int((cand["label_true_breakout"] == "A").sum()),
        "candidate_c_n": int((cand["label_true_breakout"] == "C").sum()),
        "candidate_a_share": float((cand["label_true_breakout"] == "A").mean()) if len(cand) else np.nan,
        "candidate_c_share": float((cand["label_true_breakout"] == "C").mean()) if len(cand) else np.nan,
        "selected_A": int(((x["is_candidate"]) & (x["label_true_breakout"] == "A")).sum()),
        "selected_C": int(((x["is_candidate"]) & (x["label_true_breakout"] == "C")).sum()),
        "missed_A": int(((~x["is_candidate"]) & (x["label_true_breakout"] == "A")).sum()),
        "rejected_C": int(((~x["is_candidate"]) & (x["label_true_breakout"] == "C")).sum()),
    }


def _ranking_metrics(x: pd.DataFrame, tag: str) -> list[dict]:
    full_a_share = float((x["label_true_breakout"] == "A").mean())
    rows = []
    for p, bucket in [(0.10, "top10"), (0.20, "top20"), (0.30, "top30")]:
        sub = x[x["pass_hard_filters"] & (x["rank_pct"] <= p)]
        n = len(sub)
        a_n = int((sub["label_true_breakout"] == "A").sum())
        a_share = (a_n / n) if n else np.nan
        rows.append(
            {
                "model": tag,
                "bucket": bucket,
                "sample_n": n,
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

    sa = x[(x["is_candidate"]) & (x["label_true_breakout"] == "A")]["score_trend_axis"].median(skipna=True)
    sc = x[(x["is_candidate"]) & (x["label_true_breakout"] == "C")]["score_trend_axis"].median(skipna=True)
    trend_selected_a_minus_c = float(sa - sc) if pd.notna(sa) and pd.notna(sc) else np.nan

    return {
        "model": tag,
        "hard_filter_elimination_rate": float(1 - x["pass_hard_filters"].mean()),
        "score_total_unique": int(x["score_total"].nunique(dropna=True)),
        "score_continuous": bool(x["score_total"].nunique(dropna=True) > 200),
        "axis_dominance_proxy": dominance,
        "axis_dominance_share": dominance_share,
        "axis_imbalance_risk": "high" if pd.notna(dominance_share) and dominance_share > 0.45 else ("moderate" if pd.notna(dominance_share) and dominance_share > 0.35 else "low"),
        "trend_selectedA_minus_selectedC": trend_selected_a_minus_c,
        "trend_wrong_ranking_risk": "high" if pd.notna(trend_selected_a_minus_c) and trend_selected_a_minus_c < 0 else "low",
    }


def main() -> None:
    snap = pd.read_parquet(SNAPSHOT).copy()
    snap["trade_date"] = snap["trade_date"].astype(str)
    ac = snap[snap["label_true_breakout"].isin(["A", "C"])].copy()
    ac = ac[(ac["trade_date"] >= WINDOW_START) & (ac["trade_date"] <= WINDOW_END)].copy()

    v21 = _build_v2_1(ac)
    v22 = _build_v2_2(ac)

    cov = pd.DataFrame([_coverage_metrics(v21, "v2.1_draft"), _coverage_metrics(v22, "v2.2_draft")])
    rank = pd.DataFrame(_ranking_metrics(v21, "v2.1_draft") + _ranking_metrics(v22, "v2.2_draft"))
    rank_piv = rank.pivot(index="model", columns="bucket", values=["a_share", "a_share_lift_pts_vs_full", "sample_n"])
    rank_piv.columns = [f"{a}_{b}" for a, b in rank_piv.columns]
    rank_piv = rank_piv.reset_index()
    compare = cov.merge(rank_piv, on="model", how="left")
    compare.to_csv(OUT_COMPARE, index=False, encoding="utf-8-sig")

    health = pd.DataFrame([_rule_health(v21, "v2.1_draft"), _rule_health(v22, "v2.2_draft")])
    health.to_csv(OUT_HEALTH, index=False, encoding="utf-8-sig")

    draft_lines = [
        "# true_breakout_selector_v2_2_draft",
        "",
        "## Scope",
        "- Only trend-axis repaired from v2.1; universe/hard filters/platform/chip/industry unchanged.",
        "",
        "## Hard filters",
        "- `f_strength_rs20_xsec_q >= 0.72` (unchanged)",
        "",
        "## Trend axis (repaired)",
        "- Core kept: `f_strength_rs20_xsec_q` (rank-capped upper=0.90).",
        "- Removed from trend main sorting: `f_strength_ret60`, `f_strength_vs_index20`, `f_trend_close_ma60_gap`.",
        "- Remaining trend atoms downgraded to weak auxiliary:",
        "  `f_strength_ret20`, `f_strength_rs60_xsec_q`, `f_trend_close_ma20_gap`,",
        "  `f_trend_ma20_ma60_gap`, `f_trend_ma20_slope5`.",
        "- Trend formula: `0.90*core + 0.10*weak_aux_mean`.",
        "",
        "## Other axes (unchanged from v2.1)",
        "- platform axis: compress_ratio(lower-better), range30(lower-better)",
        "- chip axis: winner_rate, low_position120, chip_stability_std10(scoring only)",
        "- industry axis: peer_strong_count + strength_5d auxiliary",
    ]
    OUT_DRAFT.write_text("\n".join(draft_lines), encoding="utf-8")

    fix_note_lines = [
        "# true_breakout_selector_v2_2_trend_fix_note",
        "",
        "1) Single-core trend axis with cap: keep rs20 quantile only as core to stop momentum over-amplification.",
        "2) Remove three misleading trend atoms from main sort: ret60 / vs_index20 / close_ma60_gap.",
        "3) Keep remaining trend atoms only as weak auxiliary (10% total contribution).",
    ]
    OUT_FIX_NOTE.write_text("\n".join(fix_note_lines), encoding="utf-8")

    c = compare.set_index("model")
    h = health.set_index("model")
    lines = [
        "# true_breakout_selector_v2_2_validation_review",
        "",
        f"- window: {WINDOW_START} ~ {WINDOW_END}",
        f"- sample_n(A/C): {len(ac)}",
        "",
        "## Core compare (v2.2 vs v2.1)",
        compare.to_string(index=False),
        "",
        "## Rule health",
        health.to_string(index=False),
        "",
        "## Direct checks",
        f"- candidate A share: v2.1={float(c.loc['v2.1_draft','candidate_a_share']):.4f}, v2.2={float(c.loc['v2.2_draft','candidate_a_share']):.4f}",
        f"- selected_C: v2.1={int(c.loc['v2.1_draft','selected_C'])}, v2.2={int(c.loc['v2.2_draft','selected_C'])}",
        f"- selected_A: v2.1={int(c.loc['v2.1_draft','selected_A'])}, v2.2={int(c.loc['v2.2_draft','selected_A'])}",
        f"- trend_selectedA_minus_selectedC: v2.1={float(h.loc['v2.1_draft','trend_selectedA_minus_selectedC']):+.4f}, "
        f"v2.2={float(h.loc['v2.2_draft','trend_selectedA_minus_selectedC']):+.4f}",
        "",
        "Note: selector-only research validation; no entry/exit/execution/return backtest.",
    ]
    OUT_REVIEW.write_text("\n".join(lines), encoding="utf-8")

    print("Generated:")
    print(" -", OUT_DRAFT)
    print(" -", OUT_COMPARE)
    print(" -", OUT_HEALTH)
    print(" -", OUT_REVIEW)
    print(" -", OUT_FIX_NOTE)


if __name__ == "__main__":
    main()

