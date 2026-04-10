from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from run_ech2_scope_expansion_fast_review import apply_q2_gate, build_ech2_mask
from run_true_breakout_core_pool_recall_rebuild import CoreConfig, add_quality_labels, load_universe, run_selector_core
from run_true_breakout_dual_channel_fast_review import assign_archetype


BASE = Path(r"D:\HuaweiAI\quantSystem2\data\research\strong_start_full\v4_scan")

OUT_COMPARE = BASE / "dual_channel_s2_final_replacement_review.csv"
OUT_ARCHETYPE = BASE / "dual_channel_s2_archetype_review.csv"
OUT_REVIEW = BASE / "dual_channel_s2_final_replacement.md"

MAIN_FROM = "2025-12-30"
MAIN_TO = "2026-03-30"
CONFIRM_FROM = "2025-09-29"
CONFIRM_TO = "2025-12-29"


def _window_slice(df: pd.DataFrame, dfrom: str, dto: str) -> pd.DataFrame:
    td = pd.to_datetime(df["trade_date"], errors="coerce")
    return df[(td >= pd.Timestamp(dfrom)) & (td <= pd.Timestamp(dto))].copy()


def _ret_stats(s: pd.Series) -> tuple[float, float, float]:
    x = pd.to_numeric(s, errors="coerce")
    if x.empty:
        return np.nan, np.nan, np.nan
    return float(x.mean()), float(x.median()), float((x > 0).mean())


def metric_for_mask(df: pd.DataFrame, scenario: str, scope: str, mask: pd.Series) -> dict:
    sel = df[mask].copy()
    a_total = int((df["label_class"] == "A").sum())
    ah_total = int((df["label_A_high"] == 1).sum())
    a_sel = int((sel["label_class"] == "A").sum())
    ah_sel = int((sel["label_A_high"] == 1).sum())
    c_sel = int((sel["label_class"] == "C").sum())
    low_sel = int((sel["label_A_low"] == 1).sum())

    t2m, t2d, t2w = _ret_stats(sel["ret_t2_close"])
    return {
        "scope": scope,
        "scenario": scenario,
        "selected_n": int(len(sel)),
        "A_recall_rate": float(a_sel / a_total) if a_total else np.nan,
        "A_high_recall_rate": float(ah_sel / ah_total) if ah_total else np.nan,
        "A_high_over_C": float(ah_sel / c_sel) if c_sel else np.nan,
        "A_low_plus_C_share": float((low_sel + c_sel) / len(sel)) if len(sel) else np.nan,
        "mean_ret_t2": t2m,
        "median_ret_t2": t2d,
        "win_t2": t2w,
    }


def archetype_coverage(df: pd.DataFrame, scen_mask: dict[str, pd.Series]) -> pd.DataFrame:
    ah = df[df["label_A_high"] == 1].copy()
    ah["archetype"] = assign_archetype(ah)

    keep_archetypes = [
        "A1_momentum_frontline",
        "A2_structure_chip",
        "A3_early_structure_low_rs20",
        "A4_balanced_highscore",
        "A5_mixed_other",
    ]
    rows = []
    for scen, mask in scen_mask.items():
        for arche in keep_archetypes:
            g = ah[ah["archetype"] == arche]
            total = len(g)
            caught = int(mask.loc[g.index].sum())
            rows.append(
                {
                    "scenario": scen,
                    "archetype": arche,
                    "archetype_total": total,
                    "archetype_captured": caught,
                    "archetype_recall_rate": float(caught / total) if total else np.nan,
                }
            )
    return pd.DataFrame(rows)


def write_review(df: pd.DataFrame, arche: pd.DataFrame) -> None:
    def pick(scope: str, scen: str) -> pd.Series:
        return df[(df["scope"] == scope) & (df["scenario"] == scen)].iloc[0]

    fy_q2 = pick("full_year", "C2A+ECH2_Q2")
    fy_s2 = pick("full_year", "C2A+ECH2_S2")
    mw_q2 = pick("main_window", "C2A+ECH2_Q2")
    mw_s2 = pick("main_window", "C2A+ECH2_S2")
    cw_q2 = pick("confirm_window", "C2A+ECH2_Q2")
    cw_s2 = pick("confirm_window", "C2A+ECH2_S2")

    d_ah = float(fy_s2["A_high_recall_rate"] - fy_q2["A_high_recall_rate"])
    d_ratio = float(fy_s2["A_high_over_C"] - fy_q2["A_high_over_C"])
    d_win2 = float(fy_s2["win_t2"] - fy_q2["win_t2"])
    d_lowc = float(fy_s2["A_low_plus_C_share"] - fy_q2["A_low_plus_C_share"])

    # Formal replacement rule (fast gate):
    # 1) meaningful recall lift
    # 2) quality not clearly worse
    # 3) main/confirm window should not both reverse
    cond1 = d_ah >= 0.002
    cond2 = d_ratio >= -0.01 and d_lowc <= 0.01
    cond3 = not ((mw_s2["A_high_over_C"] < mw_q2["A_high_over_C"]) and (cw_s2["A_high_over_C"] < cw_q2["A_high_over_C"]))
    replace = cond1 and cond2 and cond3

    def cov(scen: str, archetype: str) -> float:
        r = arche[(arche["scenario"] == scen) & (arche["archetype"] == archetype)]
        return float(r.iloc[0]["archetype_recall_rate"]) if not r.empty else np.nan

    lines = [
        "# Q2 -> S2 formal replacement review",
        "",
        "## Decision",
        f"- Replace Q2 with S2: {'YES' if replace else 'NO'}",
        f"- Full-year A_high recall: {fy_q2['A_high_recall_rate']:.2%} -> {fy_s2['A_high_recall_rate']:.2%} ({d_ah:+.2%})",
        f"- Full-year A_high/C: {fy_q2['A_high_over_C']:.4f} -> {fy_s2['A_high_over_C']:.4f} ({d_ratio:+.4f})",
        f"- Full-year A_low+C share: {fy_q2['A_low_plus_C_share']:.2%} -> {fy_s2['A_low_plus_C_share']:.2%} ({d_lowc:+.2%})",
        f"- Full-year T+2 win: {fy_q2['win_t2']:.2%} -> {fy_s2['win_t2']:.2%} ({d_win2:+.2%})",
        "",
        "## Window check",
        f"- Main window A_high/C: {mw_q2['A_high_over_C']:.4f} -> {mw_s2['A_high_over_C']:.4f}; T+2 win: {mw_q2['win_t2']:.2%} -> {mw_s2['win_t2']:.2%}",
        f"- Confirm window A_high/C: {cw_q2['A_high_over_C']:.4f} -> {cw_s2['A_high_over_C']:.4f}; T+2 win: {cw_q2['win_t2']:.2%} -> {cw_s2['win_t2']:.2%}",
        "",
        "## Archetype coverage delta (Q2 -> S2)",
        f"- A2_structure_chip: {cov('C2A+ECH2_Q2', 'A2_structure_chip'):.2%} -> {cov('C2A+ECH2_S2', 'A2_structure_chip'):.2%}",
        f"- A3_early_structure_low_rs20: {cov('C2A+ECH2_Q2', 'A3_early_structure_low_rs20'):.2%} -> {cov('C2A+ECH2_S2', 'A3_early_structure_low_rs20'):.2%}",
        f"- A4_balanced_highscore: {cov('C2A+ECH2_Q2', 'A4_balanced_highscore'):.2%} -> {cov('C2A+ECH2_S2', 'A4_balanced_highscore'):.2%}",
        f"- A5_mixed_other: {cov('C2A+ECH2_Q2', 'A5_mixed_other'):.2%} -> {cov('C2A+ECH2_S2', 'A5_mixed_other'):.2%}",
    ]
    OUT_REVIEW.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    base = load_universe()
    base = add_quality_labels(base)

    cfg_c2a = CoreConfig(
        name="C2A",
        note="frozen baseline",
        quota_a=2,
        quota_b=3,
        cutoff_a=0.20,
        cutoff_b=0.20,
        path_a_rs20_min=0.72,
        path_a_trend_min=0.02,
        path_b_rs20_min=0.60,
        path_b_trend_min=0.00,
    )
    d = run_selector_core(base, cfg_c2a)
    in_c2a = d["in_core_pool"].eq(1)

    plat_all = pd.to_numeric(d["score_platform_axis_single"], errors="coerce")
    comp_all = pd.to_numeric(d["f_platform_compress_ratio"], errors="coerce")
    chip_all = pd.to_numeric(d["f_chip_winner_rate"], errors="coerce")
    ind_all = pd.to_numeric(d["score_industry_axis_single"], errors="coerce")
    score_all = pd.to_numeric(d["score_total"], errors="coerce")

    q_plat_65 = float(plat_all.quantile(0.65))
    q_plat_55 = float(plat_all.quantile(0.55))
    q_comp_45 = float(comp_all.quantile(0.45))
    q_comp_55 = float(comp_all.quantile(0.55))
    q_chip_50 = float(chip_all.quantile(0.50))
    q_ind_55 = float(ind_all.quantile(0.55))
    q_score_60 = float(score_all.quantile(0.60))

    ech2_q2_base = build_ech2_mask(
        d,
        plat_floor=q_plat_65,
        comp_ceiling=q_comp_45,
        q_ind_55=q_ind_55,
        q_chip_50=q_chip_50,
        q_score_60=q_score_60,
    )
    in_ech2_q2 = apply_q2_gate(d, in_c2a, ech2_q2_base)
    in_main_q2 = in_c2a | in_ech2_q2

    ech2_s2_base = build_ech2_mask(
        d,
        plat_floor=q_plat_55,
        comp_ceiling=q_comp_55,
        q_ind_55=q_ind_55,
        q_chip_50=q_chip_50,
        q_score_60=q_score_60,
    )
    in_ech2_s2 = apply_q2_gate(d, in_c2a, ech2_s2_base)
    in_main_s2 = in_c2a | in_ech2_s2

    rows = []
    for scope, sdf in [
        ("full_year", d),
        ("main_window", _window_slice(d, MAIN_FROM, MAIN_TO)),
        ("confirm_window", _window_slice(d, CONFIRM_FROM, CONFIRM_TO)),
    ]:
        idx = sdf.index
        rows.append(metric_for_mask(sdf, "C2A+ECH2_Q2", scope, in_main_q2.loc[idx]))
        rows.append(metric_for_mask(sdf, "C2A+ECH2_S2", scope, in_main_s2.loc[idx]))
    cmp_df = pd.DataFrame(rows)
    cmp_df.to_csv(OUT_COMPARE, index=False, encoding="utf-8-sig")

    d_ah = d[d["label_A_high"] == 1].copy()
    d_ah["archetype"] = assign_archetype(d_ah)
    arche_df = archetype_coverage(
        d_ah,
        {
            "C2A+ECH2_Q2": in_main_q2.loc[d_ah.index],
            "C2A+ECH2_S2": in_main_s2.loc[d_ah.index],
        },
    )
    arche_df.to_csv(OUT_ARCHETYPE, index=False, encoding="utf-8-sig")

    write_review(cmp_df, arche_df)
    print(str(OUT_COMPARE))
    print(str(OUT_ARCHETYPE))
    print(str(OUT_REVIEW))


if __name__ == "__main__":
    main()

