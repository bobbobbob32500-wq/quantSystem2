from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(r"D:\HuaweiAI\quantSystem2")
BASE = ROOT / "data/research/strong_start_full/v4_scan"
SNAPSHOT = BASE / "true_breakout_feature_snapshot_1y.parquet"

OUT_DRIFT = BASE / "true_breakout_regime_drift_audit.csv"
OUT_A_SUBTYPES = BASE / "true_breakout_near_window_A_subtypes.csv"
OUT_A_SEL_MISS = BASE / "true_breakout_selectedA_vs_missedA_subtypes.csv"
OUT_C_FAIL = BASE / "true_breakout_selectedC_failure_modes.csv"
OUT_REPORT = BASE / "true_breakout_regime_mismatch_report.md"

NEAR_START = "20251230"
NEAR_END = "20260330"


def _rank01(s: pd.Series, higher: bool = True) -> pd.Series:
    x = pd.to_numeric(s, errors="coerce")
    if not higher:
        x = -x
    return x.rank(method="average", pct=True)


def _cliffs_delta(a: pd.Series, c: pd.Series) -> float:
    x = pd.to_numeric(a, errors="coerce").dropna().values
    y = pd.to_numeric(c, errors="coerce").dropna().values
    if len(x) == 0 or len(y) == 0:
        return np.nan
    gt = 0
    lt = 0
    for v in x:
        gt += np.sum(v > y)
        lt += np.sum(v < y)
    return (gt - lt) / (len(x) * len(y))


def _build_v22_selector(ac: pd.DataFrame) -> pd.DataFrame:
    x = ac.copy()
    x["pass_hard_filters"] = (pd.to_numeric(x["f_strength_rs20_xsec_q"], errors="coerce") >= 0.72)

    core = _rank01(x["f_strength_rs20_xsec_q"], True).clip(upper=0.90)
    weak_aux_cols = [
        "f_strength_ret20",
        "f_strength_rs60_xsec_q",
        "f_trend_close_ma20_gap",
        "f_trend_ma20_ma60_gap",
        "f_trend_ma20_slope5",
    ]
    weak_aux_cols = [c for c in weak_aux_cols if c in x.columns]
    if weak_aux_cols:
        aux = pd.concat([_rank01(x[c], True) for c in weak_aux_cols], axis=1).mean(axis=1)
    else:
        aux = pd.Series(0.0, index=x.index)
    x["score_trend_axis"] = 0.90 * core + 0.10 * aux

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

    x["rank_pct"] = np.nan
    for _, g in x[x["pass_hard_filters"]].groupby("trade_date"):
        x.loc[g.index, "rank_pct"] = g["score_total"].rank(method="first", ascending=False, pct=True)
    x["is_candidate"] = x["pass_hard_filters"] & (x["rank_pct"] <= 0.30)
    x["quadrant"] = "other"
    x.loc[x["is_candidate"] & (x["label_true_breakout"] == "A"), "quadrant"] = "selected_A"
    x.loc[x["is_candidate"] & (x["label_true_breakout"] == "C"), "quadrant"] = "selected_C"
    x.loc[(~x["is_candidate"]) & (x["label_true_breakout"] == "A"), "quadrant"] = "missed_A"
    x.loc[(~x["is_candidate"]) & (x["label_true_breakout"] == "C"), "quadrant"] = "rejected_C"
    return x


def _drift_audit(df_year: pd.DataFrame, df_near: pd.DataFrame, factors: list[tuple[str, str]]) -> pd.DataFrame:
    rows: list[dict] = []
    for f, family in factors:
        if f not in df_year.columns:
            continue
        y_a = pd.to_numeric(df_year.loc[df_year["label_true_breakout"] == "A", f], errors="coerce")
        y_c = pd.to_numeric(df_year.loc[df_year["label_true_breakout"] == "C", f], errors="coerce")
        n_a = pd.to_numeric(df_near.loc[df_near["label_true_breakout"] == "A", f], errors="coerce")
        n_c = pd.to_numeric(df_near.loc[df_near["label_true_breakout"] == "C", f], errors="coerce")

        y_gap = y_a.median(skipna=True) - y_c.median(skipna=True)
        n_gap = n_a.median(skipna=True) - n_c.median(skipna=True)
        y_eff = _cliffs_delta(y_a, y_c)
        n_eff = _cliffs_delta(n_a, n_c)

        if pd.notna(y_gap) and pd.notna(n_gap) and np.sign(y_gap) != 0 and np.sign(n_gap) != 0 and np.sign(y_gap) != np.sign(n_gap):
            state = "direction_flip"
        elif pd.notna(y_gap) and pd.notna(n_gap) and abs(n_gap) < 0.5 * abs(y_gap):
            state = "weakened_near"
        else:
            state = "stable_or_stronger"

        rows.append(
            {
                "feature": f,
                "family": family,
                "year_a_median": y_a.median(skipna=True),
                "year_c_median": y_c.median(skipna=True),
                "year_gap_a_minus_c": y_gap,
                "year_effect_cliff": y_eff,
                "near_a_median": n_a.median(skipna=True),
                "near_c_median": n_c.median(skipna=True),
                "near_gap_a_minus_c": n_gap,
                "near_effect_cliff": n_eff,
                "drift_state": state,
            }
        )
    out = pd.DataFrame(rows)
    out.to_csv(OUT_DRIFT, index=False, encoding="utf-8-sig")
    return out


def _near_a_subtypes(near: pd.DataFrame) -> pd.DataFrame:
    a = near[near["label_true_breakout"] == "A"].copy()
    if a.empty:
        return a
    t66 = a["score_trend_axis"].quantile(0.66)
    t33 = a["score_trend_axis"].quantile(0.33)
    i60 = a["score_industry_axis"].quantile(0.60)
    p66 = a["score_platform_axis"].quantile(0.66)
    c60 = a["score_chip_axis"].quantile(0.60)
    c66 = a["score_chip_axis"].quantile(0.66)

    a["a_subtype"] = "mixed_A"
    a.loc[(a["score_trend_axis"] >= t66) & (a["score_industry_axis"] >= i60), "a_subtype"] = "high_momentum_frontline_A"
    a.loc[
        (a["a_subtype"] == "mixed_A")
        & (a["score_platform_axis"] >= p66)
        & (a["score_chip_axis"] >= c60)
        & (a["score_trend_axis"] < t66),
        "a_subtype",
    ] = "steady_structure_A"
    a.loc[
        (a["a_subtype"] == "mixed_A")
        & (a["score_chip_axis"] >= c66)
        & (a["score_trend_axis"] >= t33)
        & (a["score_trend_axis"] < t66),
        "a_subtype",
    ] = "chip_support_A"
    return a


def _selected_c_failure_modes(near: pd.DataFrame) -> pd.DataFrame:
    c = near[near["quadrant"] == "selected_C"].copy()
    if c.empty:
        return c
    t66 = c["score_trend_axis"].quantile(0.66)
    i66 = c["score_industry_axis"].quantile(0.66)
    p33 = c["score_platform_axis"].quantile(0.33)
    chip33 = c["score_chip_axis"].quantile(0.33)
    c["c_failure_mode"] = "mixed_pseudo_C"

    c.loc[(c["score_industry_axis"] >= i66) & (c["score_trend_axis"] >= t66), "c_failure_mode"] = "industry_heat_C"
    c.loc[
        (c["c_failure_mode"] == "mixed_pseudo_C")
        & (pd.to_numeric(c["f_strength_ret20"], errors="coerce") >= pd.to_numeric(c["f_strength_ret20"], errors="coerce").quantile(0.66))
        & (c["score_chip_axis"] <= chip33),
        "c_failure_mode",
    ] = "trend_chase_C"
    c.loc[
        (c["c_failure_mode"] == "mixed_pseudo_C")
        & (c["score_platform_axis"] <= p33)
        & (c["score_trend_axis"] >= c["score_trend_axis"].median()),
        "c_failure_mode",
    ] = "platform_false_break_C"
    c.loc[
        (c["c_failure_mode"] == "mixed_pseudo_C")
        & (pd.to_numeric(c["f_chip_stability_std10"], errors="coerce") <= pd.to_numeric(c["f_chip_stability_std10"], errors="coerce").quantile(0.25))
        & (c["score_trend_axis"] >= c["score_trend_axis"].median()),
        "c_failure_mode",
    ] = "chip_distortion_C"
    return c


def main() -> None:
    snap = pd.read_parquet(SNAPSHOT).copy()
    snap["trade_date"] = snap["trade_date"].astype(str)
    ac = snap[snap["label_true_breakout"].isin(["A", "C"])].copy()

    year = ac.copy()
    near = ac[(ac["trade_date"] >= NEAR_START) & (ac["trade_date"] <= NEAR_END)].copy()
    near = _build_v22_selector(near)

    factors = [
        ("f_strength_rs20_xsec_q", "trend"),
        ("f_strength_ret20", "trend"),
        ("f_strength_ret60", "trend"),
        ("f_strength_vs_index20", "trend"),
        ("f_strength_rs60_xsec_q", "trend"),
        ("f_trend_close_ma20_gap", "trend"),
        ("f_trend_close_ma60_gap", "trend"),
        ("f_trend_ma20_ma60_gap", "trend"),
        ("f_trend_ma20_slope5", "trend"),
        ("f_platform_compress_ratio", "platform"),
        ("f_platform_range20", "platform"),
        ("f_platform_range30", "platform"),
        ("f_chip_winner_rate", "chip"),
        ("f_chip_low_position120", "chip"),
        ("f_chip_stability_std10", "chip"),
        ("f_ind_peer_strong_count", "industry"),
        ("f_ind_strength_5d", "industry"),
        ("f_ind_rank_pctchg", "industry"),
    ]
    drift = _drift_audit(year, near, factors)

    # near A subtypes + selected/missed overlay
    a_sub = _near_a_subtypes(near)
    a_sub["selection_state"] = np.where(a_sub["quadrant"] == "selected_A", "selected_A", "missed_A")
    a_sub_out_cols = [
        "ts_code",
        "trade_date",
        "quadrant",
        "selection_state",
        "a_subtype",
        "score_trend_axis",
        "score_platform_axis",
        "score_chip_axis",
        "score_industry_axis",
        "score_total",
    ]
    a_sub[a_sub_out_cols].to_csv(OUT_A_SUBTYPES, index=False, encoding="utf-8-sig")

    a_sub_stat = (
        a_sub.groupby(["a_subtype", "selection_state"], dropna=False)
        .size()
        .reset_index(name="n")
        .pivot(index="a_subtype", columns="selection_state", values="n")
        .fillna(0)
        .reset_index()
    )
    if "selected_A" not in a_sub_stat.columns:
        a_sub_stat["selected_A"] = 0
    if "missed_A" not in a_sub_stat.columns:
        a_sub_stat["missed_A"] = 0
    a_sub_stat["selected_rate"] = a_sub_stat["selected_A"] / (a_sub_stat["selected_A"] + a_sub_stat["missed_A"]).replace(0, np.nan)
    a_sub_stat.to_csv(OUT_A_SEL_MISS, index=False, encoding="utf-8-sig")

    # selected C failure modes
    c_mode = _selected_c_failure_modes(near)
    c_mode_stat = (
        c_mode.groupby("c_failure_mode", dropna=False)
        .size()
        .reset_index(name="n")
        .sort_values("n", ascending=False)
    )
    axis_c_lift = []
    for ax in ["score_trend_axis", "score_platform_axis", "score_chip_axis", "score_industry_axis"]:
        sc = near.loc[near["quadrant"] == "selected_C", ax].median(skipna=True)
        rc = near.loc[near["quadrant"] == "rejected_C", ax].median(skipna=True)
        axis_c_lift.append({"axis": ax, "selectedC_minus_rejectedC": sc - rc})
    axis_c_lift_df = pd.DataFrame(axis_c_lift).sort_values("selectedC_minus_rejectedC", ascending=False)
    c_mode_stat.to_csv(OUT_C_FAIL, index=False, encoding="utf-8-sig")

    # summarize drift groups
    stable = drift[drift["drift_state"] == "stable_or_stronger"]
    weak = drift[drift["drift_state"] == "weakened_near"]
    flip = drift[drift["drift_state"] == "direction_flip"]
    fam = drift.groupby(["family", "drift_state"]).size().reset_index(name="n")

    lines = []
    lines.append("# true_breakout_regime_mismatch_report")
    lines.append("")
    lines.append(f"- near window: {NEAR_START} ~ {NEAR_END}")
    lines.append(f"- near A/C sample: {len(near)}")
    lines.append(f"- selected_A={int((near['quadrant']=='selected_A').sum())}, selected_C={int((near['quadrant']=='selected_C').sum())}, missed_A={int((near['quadrant']=='missed_A').sum())}, rejected_C={int((near['quadrant']=='rejected_C').sum())}")
    lines.append("")
    lines.append("## Regime drift (year vs near)")
    lines.append(f"- stable_or_stronger: {len(stable)}")
    lines.append(f"- weakened_near: {len(weak)}")
    lines.append(f"- direction_flip: {len(flip)}")
    lines.append("")
    lines.append("family drift counts:")
    lines.append(fam.to_string(index=False))
    lines.append("")
    lines.append("top flipped/weakened factors:")
    lines.append(drift[drift["drift_state"] != "stable_or_stronger"][["feature", "family", "year_gap_a_minus_c", "near_gap_a_minus_c", "drift_state"]].to_string(index=False))
    lines.append("")
    lines.append("## Near A subtypes")
    lines.append(a_sub_stat.to_string(index=False))
    lines.append("")
    lines.append("## selected_C failure modes")
    lines.append(c_mode_stat.to_string(index=False))
    lines.append("")
    lines.append("axis likely amplifying selected_C:")
    lines.append(axis_c_lift_df.to_string(index=False))
    lines.append("")
    lines.append("## Repair directions (no new selector version)")
    lines.append("1) Split selector into dual-path scoring (momentum-frontline path + steady-structure path) to recover missed_A in non-extreme trend regime. [solve missed A]")
    lines.append("2) Add anti-hotness guard on trend/industry joint extremes (cap co-amplification) to block industry_heat_C and trend_chase_C spill-in. [solve selected C]")
    lines.append("3) Make platform/chip conditional by subtype (not global linear sum), because near-window A is multi-modal and single-axis additive ranking under-fits subtype diversity. [solve both]")
    OUT_REPORT.write_text("\n".join(lines), encoding="utf-8")

    print("Generated:")
    print(" -", OUT_DRIFT)
    print(" -", OUT_A_SUBTYPES)
    print(" -", OUT_A_SEL_MISS)
    print(" -", OUT_C_FAIL)
    print(" -", OUT_REPORT)


if __name__ == "__main__":
    main()

