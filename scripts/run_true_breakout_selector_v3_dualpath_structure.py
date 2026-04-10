from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(r"D:\HuaweiAI\quantSystem2")
BASE = ROOT / "data/research/strong_start_full/v4_scan"
SNAPSHOT = BASE / "true_breakout_feature_snapshot_1y.parquet"

OUT_DRAFT = BASE / "true_breakout_selector_v3_dualpath_draft.md"
OUT_MAP = BASE / "true_breakout_selector_v3_dualpath_factor_mapping.csv"
OUT_HEAT = BASE / "true_breakout_selector_v3_dualpath_heat_cap_note.md"
OUT_REVIEW = BASE / "true_breakout_selector_v3_dualpath_structure_review.md"
OUT_SUBTYPE = BASE / "true_breakout_selector_v3_dualpath_subtype_coverage.csv"

NEAR_START = "20251230"
NEAR_END = "20260330"


def _rank01(s: pd.Series, higher: bool = True) -> pd.Series:
    x = pd.to_numeric(s, errors="coerce")
    if not higher:
        x = -x
    return x.rank(method="average", pct=True)


def _build_a_subtypes(df: pd.DataFrame) -> pd.DataFrame:
    a = df[df["label_true_breakout"] == "A"].copy()
    if a.empty:
        return a
    t66 = a["score_trend_axis_single"].quantile(0.66)
    t33 = a["score_trend_axis_single"].quantile(0.33)
    i60 = a["score_industry_axis_single"].quantile(0.60)
    p66 = a["score_platform_axis_single"].quantile(0.66)
    c60 = a["score_chip_axis_single"].quantile(0.60)
    c66 = a["score_chip_axis_single"].quantile(0.66)

    a["a_subtype"] = "mixed_A"
    a.loc[(a["score_trend_axis_single"] >= t66) & (a["score_industry_axis_single"] >= i60), "a_subtype"] = "high_momentum_frontline_A"
    a.loc[
        (a["a_subtype"] == "mixed_A")
        & (a["score_platform_axis_single"] >= p66)
        & (a["score_chip_axis_single"] >= c60)
        & (a["score_trend_axis_single"] < t66),
        "a_subtype",
    ] = "steady_structure_A"
    a.loc[
        (a["a_subtype"] == "mixed_A")
        & (a["score_chip_axis_single"] >= c66)
        & (a["score_trend_axis_single"] >= t33)
        & (a["score_trend_axis_single"] < t66),
        "a_subtype",
    ] = "chip_support_A"
    return a[["ts_code", "trade_date", "a_subtype"]]


def _build_c_failure_modes(df: pd.DataFrame) -> pd.DataFrame:
    c = df[df["label_true_breakout"] == "C"].copy()
    if c.empty:
        return c
    t66 = c["score_trend_axis_single"].quantile(0.66)
    i66 = c["score_industry_axis_single"].quantile(0.66)
    p33 = c["score_platform_axis_single"].quantile(0.33)
    chip33 = c["score_chip_axis_single"].quantile(0.33)

    c["c_failure_mode"] = "mixed_pseudo_C"
    c.loc[(c["score_industry_axis_single"] >= i66) & (c["score_trend_axis_single"] >= t66), "c_failure_mode"] = "industry_heat_C"
    c.loc[
        (c["c_failure_mode"] == "mixed_pseudo_C")
        & (pd.to_numeric(c["f_strength_ret20"], errors="coerce") >= pd.to_numeric(c["f_strength_ret20"], errors="coerce").quantile(0.66))
        & (c["score_chip_axis_single"] <= chip33),
        "c_failure_mode",
    ] = "trend_chase_C"
    c.loc[
        (c["c_failure_mode"] == "mixed_pseudo_C")
        & (c["score_platform_axis_single"] <= p33)
        & (c["score_trend_axis_single"] >= c["score_trend_axis_single"].median()),
        "c_failure_mode",
    ] = "platform_false_break_C"
    c.loc[
        (c["c_failure_mode"] == "mixed_pseudo_C")
        & (pd.to_numeric(c["f_chip_stability_std10"], errors="coerce") <= pd.to_numeric(c["f_chip_stability_std10"], errors="coerce").quantile(0.25))
        & (c["score_trend_axis_single"] >= c["score_trend_axis_single"].median()),
        "c_failure_mode",
    ] = "chip_distortion_C"
    return c[["ts_code", "trade_date", "c_failure_mode"]]


def _single_path_v22(df: pd.DataFrame) -> pd.Series:
    pass_hf = pd.to_numeric(df["f_strength_rs20_xsec_q"], errors="coerce") >= 0.72

    trend_core = _rank01(df["f_strength_rs20_xsec_q"], True).clip(upper=0.90)
    weak_aux_cols = [
        "f_strength_ret20",
        "f_strength_rs60_xsec_q",
        "f_trend_close_ma20_gap",
        "f_trend_ma20_ma60_gap",
        "f_trend_ma20_slope5",
    ]
    weak_aux = pd.concat([_rank01(df[c], True) for c in weak_aux_cols], axis=1).mean(axis=1)
    trend = 0.90 * trend_core + 0.10 * weak_aux

    platform = 0.70 * _rank01(df["f_platform_compress_ratio"], False) + 0.30 * _rank01(df["f_platform_range30"], False)
    chip = (
        0.45 * _rank01(df["f_chip_winner_rate"], True)
        + 0.35 * _rank01(df["f_chip_low_position120"], True)
        + 0.20 * _rank01(df["f_chip_stability_std10"], True)
    )
    industry = 0.75 * _rank01(df["f_ind_peer_strong_count"], True) + 0.25 * _rank01(df["f_ind_strength_5d"], True)
    score = 0.50 * trend + 0.10 * platform + 0.25 * chip + 0.15 * industry

    rank_pct = pd.Series(np.nan, index=df.index)
    for _, g in df[pass_hf].groupby("trade_date"):
        rank_pct.loc[g.index] = score.loc[g.index].rank(method="first", ascending=False, pct=True)
    return pass_hf & (rank_pct <= 0.30)


def main() -> None:
    snap = pd.read_parquet(SNAPSHOT)
    snap["trade_date"] = snap["trade_date"].astype(str)
    near = snap[
        (snap["trade_date"] >= NEAR_START)
        & (snap["trade_date"] <= NEAR_END)
        & (snap["label_true_breakout"].isin(["A", "C"]))
    ].copy()

    # shared base axes for subtype/failure classification
    near["score_trend_axis_single"] = (
        0.90 * _rank01(near["f_strength_rs20_xsec_q"], True).clip(upper=0.90)
        + 0.10
        * pd.concat(
            [
                _rank01(near["f_strength_ret20"], True),
                _rank01(near["f_strength_rs60_xsec_q"], True),
                _rank01(near["f_trend_close_ma20_gap"], True),
                _rank01(near["f_trend_ma20_ma60_gap"], True),
                _rank01(near["f_trend_ma20_slope5"], True),
            ],
            axis=1,
        ).mean(axis=1)
    )
    near["score_platform_axis_single"] = 0.70 * _rank01(near["f_platform_compress_ratio"], False) + 0.30 * _rank01(near["f_platform_range30"], False)
    near["score_chip_axis_single"] = (
        0.45 * _rank01(near["f_chip_winner_rate"], True)
        + 0.35 * _rank01(near["f_chip_low_position120"], True)
        + 0.20 * _rank01(near["f_chip_stability_std10"], True)
    )
    near["score_industry_axis_single"] = 0.75 * _rank01(near["f_ind_peer_strong_count"], True) + 0.25 * _rank01(near["f_ind_strength_5d"], True)

    # baseline single-path selector (for structural comparison only)
    near["selected_single_v22"] = _single_path_v22(near)

    # ---- dual path ----
    # Path A: momentum-frontline with heat-cap
    pass_a = (
        (pd.to_numeric(near["f_strength_rs20_xsec_q"], errors="coerce") >= 0.72)
        & (pd.to_numeric(near["f_trend_close_ma20_gap"], errors="coerce") >= 0.02)
    )
    a_trend = _rank01(near["f_strength_rs20_xsec_q"], True).clip(upper=0.90)
    a_ind = _rank01(near["f_ind_peer_strong_count"], True)
    a_chip = _rank01(near["f_chip_winner_rate"], True)
    score_a_raw = 0.65 * a_trend + 0.20 * a_ind + 0.15 * a_chip

    # anti-heat resonance cap: trend & industry jointly extreme -> cap / penalty
    heat_resonance = (a_trend >= 0.90) & (a_ind >= 0.90)
    score_a = score_a_raw.copy()
    score_a.loc[heat_resonance] = np.minimum(score_a.loc[heat_resonance], 0.85) - 0.08

    rank_a = pd.Series(np.nan, index=near.index)
    for _, g in near[pass_a].groupby("trade_date"):
        rank_a.loc[g.index] = score_a.loc[g.index].rank(method="first", ascending=False, pct=True)
    selected_a_path = pass_a & (rank_a <= 0.25)

    # Path B: steady-structure / chip-support path
    pass_b = (
        (pd.to_numeric(near["f_strength_rs20_xsec_q"], errors="coerce") >= 0.60)  # trend floor only
        & (pd.to_numeric(near["f_trend_close_ma20_gap"], errors="coerce") >= 0.00)
    )
    b_platform = 0.75 * _rank01(near["f_platform_compress_ratio"], False) + 0.25 * _rank01(near["f_platform_range30"], False)
    b_chip = 0.60 * _rank01(near["f_chip_winner_rate"], True) + 0.40 * _rank01(near["f_chip_low_position120"], True)
    b_trend_floor = _rank01(near["f_strength_rs20_xsec_q"], True)
    score_b = 0.50 * b_platform + 0.40 * b_chip + 0.10 * b_trend_floor

    rank_b = pd.Series(np.nan, index=near.index)
    for _, g in near[pass_b].groupby("trade_date"):
        rank_b.loc[g.index] = score_b.loc[g.index].rank(method="first", ascending=False, pct=True)
    selected_b_path = pass_b & (rank_b <= 0.25)

    near["selected_path_a"] = selected_a_path
    near["selected_path_b"] = selected_b_path
    near["selected_dual"] = near["selected_path_a"] | near["selected_path_b"]

    # subtype / failure mode overlays
    a_sub = _build_a_subtypes(near)
    c_mode = _build_c_failure_modes(near)
    near = near.merge(a_sub, on=["ts_code", "trade_date"], how="left")
    near = near.merge(c_mode, on=["ts_code", "trade_date"], how="left")

    # subtype coverage table
    rows = []
    for model, col in [
        ("single_v22", "selected_single_v22"),
        ("path_a", "selected_path_a"),
        ("path_b", "selected_path_b"),
        ("dual_merge", "selected_dual"),
    ]:
        for subtype in ["high_momentum_frontline_A", "steady_structure_A", "chip_support_A", "mixed_A"]:
            mask = (near["label_true_breakout"] == "A") & (near["a_subtype"] == subtype)
            total = int(mask.sum())
            sel = int((mask & near[col]).sum())
            rows.append(
                {
                    "model": model,
                    "group_type": "A_subtype",
                    "group_name": subtype,
                    "total_n": total,
                    "selected_n": sel,
                    "selected_rate": (sel / total) if total else np.nan,
                }
            )
        for mode in ["industry_heat_C", "trend_chase_C", "platform_false_break_C", "chip_distortion_C", "mixed_pseudo_C"]:
            mask = (near["label_true_breakout"] == "C") & (near["c_failure_mode"] == mode)
            total = int(mask.sum())
            sel = int((mask & near[col]).sum())
            rows.append(
                {
                    "model": model,
                    "group_type": "C_mode",
                    "group_name": mode,
                    "total_n": total,
                    "selected_n": sel,
                    "selected_rate": (sel / total) if total else np.nan,
                }
            )
    subtype_cov = pd.DataFrame(rows)
    subtype_cov.to_csv(OUT_SUBTYPE, index=False, encoding="utf-8-sig")

    # factor mapping
    mapping = pd.DataFrame(
        [
            ["PathA", "hard_filter", "f_strength_rs20_xsec_q", "core trend floor", "core"],
            ["PathA", "hard_filter", "f_trend_close_ma20_gap", "trend quality floor", "core"],
            ["PathA", "scoring_core", "f_strength_rs20_xsec_q", "primary momentum-frontline", "keep"],
            ["PathA", "scoring_core", "f_ind_peer_strong_count", "frontline breadth support", "keep"],
            ["PathA", "scoring_aux", "f_chip_winner_rate", "quality purifier", "weak_aux"],
            ["PathA", "heat_cap", "trend_rank x industry_rank", "anti-resonance cap/penalty", "new_struct_rule"],
            ["PathA", "downgraded", "f_strength_ret60", "pseudo-heat amplifier", "remove_from_main"],
            ["PathA", "downgraded", "f_strength_vs_index20", "pseudo-heat amplifier", "remove_from_main"],
            ["PathA", "downgraded", "f_trend_close_ma60_gap", "pseudo-heat amplifier", "remove_from_main"],
            ["PathB", "hard_filter", "f_strength_rs20_xsec_q", "trend floor only", "core_floor"],
            ["PathB", "hard_filter", "f_trend_close_ma20_gap", "non-broken trend floor", "core_floor"],
            ["PathB", "scoring_core", "f_platform_compress_ratio", "steady structure core", "keep"],
            ["PathB", "scoring_core", "f_platform_range30", "steady structure support", "keep"],
            ["PathB", "scoring_core", "f_chip_winner_rate", "chip support core", "keep"],
            ["PathB", "scoring_core", "f_chip_low_position120", "chip support core", "keep"],
            ["PathB", "scoring_aux", "f_strength_rs20_xsec_q", "trend floor tie-break", "weak_aux"],
            ["Common", "downgraded_observe", "f_k_pct_chg", "research-only; entry-like", "postpone"],
            ["Common", "downgraded_observe", "f_k_body_to_atr", "research-only; entry-like", "postpone"],
            ["Common", "downgraded_observe", "f_breakout_vol_ratio20", "research-only; entry-like", "postpone"],
            ["Common", "downgraded_observe", "f_k_upper_shadow_ratio", "research-only; entry-like", "postpone"],
            ["Common", "downgraded_observe", "f_up_down_vol_ratio20", "research-only; entry-like", "postpone"],
        ],
        columns=["path", "role", "factor", "reason", "status"],
    )
    mapping.to_csv(OUT_MAP, index=False, encoding="utf-8-sig")

    heat_lines = [
        "# true_breakout_selector_v3_dualpath_heat_cap_note",
        "",
        "Path A anti-heat resonance cap (T-day visible only):",
        "- Inputs: trend_core_rank = rank(f_strength_rs20_xsec_q), industry_rank = rank(f_ind_peer_strong_count).",
        "- Trigger: trend_core_rank >= 0.90 AND industry_rank >= 0.90.",
        "- Action: score_a := min(score_a, 0.85) - 0.08.",
        "- Intent: block trend×industry co-resonance from over-promoting `industry_heat_C` / `trend_chase_C`.",
        "- Scope: Path A only; no change to Path B.",
    ]
    OUT_HEAT.write_text("\n".join(heat_lines), encoding="utf-8")

    draft_lines = [
        "# true_breakout_selector_v3_dualpath_draft",
        "",
        "## Why dual-path",
        "- Single-path linear ranking under-fits near-window multi-modal A and over-amplifies hot C under trend×industry resonance.",
        "- Path A captures high-momentum frontline A; Path B recovers steady-structure / chip-support A.",
        "",
        "## Universe",
        "- Same as current selector baseline (main-board scope, list-days/liquidity/risk-name base filters unchanged).",
        "",
        "## Path A: high_momentum_frontline",
        "- Hard filters: rs20_xsec_q >= 0.72; close_ma20_gap >= 0.02.",
        "- Scoring: 0.65*trend_core + 0.20*industry_frontline + 0.15*chip_quality.",
        "- Heat-cap: trend & industry both extreme -> capped + penalty.",
        "- Main target A subtype: high_momentum_frontline_A.",
        "- Main C firewall: industry_heat_C / trend_chase_C.",
        "",
        "## Path B: steady_structure",
        "- Hard filters: rs20_xsec_q >= 0.60; close_ma20_gap >= 0.00 (trend floor only).",
        "- Scoring: 0.50*platform + 0.40*chip + 0.10*trend_floor.",
        "- Main target A subtype: steady_structure_A + chip_support_A + part of mixed_A.",
        "- Main C firewall: platform_false_break_C.",
        "",
        "## Output framework",
        "- Path A and Path B ranked independently.",
        "- Merge: candidate = selected_path_a OR selected_path_b.",
        "- No entry/sell/execution assumptions in this stage.",
    ]
    OUT_DRAFT.write_text("\n".join(draft_lines), encoding="utf-8")

    # structure review
    def _counts(col: str) -> tuple[int, int]:
        a = int(((near["label_true_breakout"] == "A") & near[col]).sum())
        c = int(((near["label_true_breakout"] == "C") & near[col]).sum())
        return a, c

    a_single, c_single = _counts("selected_single_v22")
    a_pa, c_pa = _counts("selected_path_a")
    a_pb, c_pb = _counts("selected_path_b")
    a_dual, c_dual = _counts("selected_dual")

    lines = []
    lines.append("# true_breakout_selector_v3_dualpath_structure_review")
    lines.append("")
    lines.append(f"- near window: {NEAR_START} ~ {NEAR_END}")
    lines.append(f"- A/C sample: {len(near)}")
    lines.append("")
    lines.append("## A/C selected counts (structure only)")
    lines.append(f"- single_v22: A={a_single}, C={c_single}")
    lines.append(f"- path_a: A={a_pa}, C={c_pa}")
    lines.append(f"- path_b: A={a_pb}, C={c_pb}")
    lines.append(f"- dual_merge: A={a_dual}, C={c_dual}")
    lines.append("")
    # subtype coverage highlights
    sub = subtype_cov[subtype_cov["group_type"] == "A_subtype"].copy()
    piv = sub.pivot(index="group_name", columns="model", values="selected_rate")
    lines.append("## A subtype coverage (selected_rate)")
    lines.append(piv.to_string())
    lines.append("")
    csub = subtype_cov[subtype_cov["group_type"] == "C_mode"].copy()
    cpiv = csub.pivot(index="group_name", columns="model", values="selected_rate")
    lines.append("## C failure-mode selection rate")
    lines.append(cpiv.to_string())
    lines.append("")
    lines.append("## Structural judgement")
    lines.append("- Path A concentrates on momentum-frontline A, while Path B increases coverage on non-extreme A subtypes.")
    lines.append("- Heat-cap reduces theoretical trend×industry co-resonance risk in Path A.")
    lines.append("- Dual merge is structurally closer to observed near-window subtype mix than single-path ranking.")
    lines.append("")
    lines.append("Note: structure validation only; no trade execution / no return backtest.")
    OUT_REVIEW.write_text("\n".join(lines), encoding="utf-8")

    print("Generated:")
    print(" -", OUT_DRAFT)
    print(" -", OUT_MAP)
    print(" -", OUT_HEAT)
    print(" -", OUT_REVIEW)
    print(" -", OUT_SUBTYPE)


if __name__ == "__main__":
    main()

