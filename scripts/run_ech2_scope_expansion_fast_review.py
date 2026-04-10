from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from run_true_breakout_core_pool_recall_rebuild import CoreConfig, add_quality_labels, load_universe, run_selector_core
from run_true_breakout_dual_channel_fast_review import assign_archetype


BASE = Path(r"D:\HuaweiAI\quantSystem2\data\research\strong_start_full\v4_scan")

OUT_GAP = BASE / "ech2_scope_gap_compare.csv"
OUT_COMPARE = BASE / "ech2_scope_expansion_compare.csv"
OUT_REVIEW = BASE / "ech2_scope_fast_review.md"


def _stats(df: pd.DataFrame, group_name: str, fields: list[str]) -> list[dict]:
    rows: list[dict] = []
    for col in fields:
        s = pd.to_numeric(df[col], errors="coerce").dropna()
        rows.append(
            {
                "group": group_name,
                "field": col,
                "count": int(s.shape[0]),
                "mean": float(s.mean()) if len(s) else np.nan,
                "median": float(s.median()) if len(s) else np.nan,
                "p25": float(s.quantile(0.25)) if len(s) else np.nan,
                "p75": float(s.quantile(0.75)) if len(s) else np.nan,
            }
        )
    return rows


def _ret_stats_t2(s: pd.Series) -> tuple[float, float]:
    x = pd.to_numeric(s, errors="coerce")
    if x.empty:
        return np.nan, np.nan
    return float(x.mean()), float((x > 0).mean())


def build_ech2_mask(
    d: pd.DataFrame,
    *,
    plat_floor: float,
    comp_ceiling: float,
    q_ind_55: float,
    q_chip_50: float,
    q_score_60: float,
) -> pd.Series:
    rs20 = pd.to_numeric(d["f_strength_rs20_xsec_q"], errors="coerce")
    trend = pd.to_numeric(d["f_trend_close_ma20_gap"], errors="coerce")
    plat = pd.to_numeric(d["score_platform_axis_single"], errors="coerce")
    comp = pd.to_numeric(d["f_platform_compress_ratio"], errors="coerce")
    chip = pd.to_numeric(d["f_chip_winner_rate"], errors="coerce")
    ind = pd.to_numeric(d["score_industry_axis_single"], errors="coerce")
    score = pd.to_numeric(d["score_total"], errors="coerce")

    base_rescue_scope = d["in_core_pool"].eq(0)
    return (
        base_rescue_scope
        & (trend >= 0.005)
        & (rs20 >= 0.58)
        & (rs20 < 0.72)
        & (plat >= plat_floor)
        & (comp <= comp_ceiling)
        & (chip >= q_chip_50)
        & ((ind >= q_ind_55) | (score >= q_score_60))
    )


def apply_q2_gate(d: pd.DataFrame, in_c2a: pd.Series, ech2_base: pd.Series) -> pd.Series:
    ind = pd.to_numeric(d["score_industry_axis_single"], errors="coerce")
    rs20 = pd.to_numeric(d["f_strength_rs20_xsec_q"], errors="coerce")
    increment = ech2_base & (~in_c2a)
    if int(increment.sum()) == 0:
        return pd.Series(False, index=d.index)
    q_ind_75 = float(ind[increment].quantile(0.75))
    q_rs20_40 = float(rs20[increment].quantile(0.40))
    return ech2_base & (ind <= q_ind_75) & (rs20 >= q_rs20_40)


def scenario_metrics(
    d: pd.DataFrame,
    name: str,
    in_mainline: pd.Series,
    archetype_col: str,
) -> dict:
    sel = d[in_mainline].copy()
    a_total = int((d["label_class"] == "A").sum())
    ah_total = int((d["label_A_high"] == 1).sum())
    a_sel = int((sel["label_class"] == "A").sum())
    ah_sel = int((sel["label_A_high"] == 1).sum())
    c_sel = int((sel["label_class"] == "C").sum())
    low_sel = int((sel["label_A_low"] == 1).sum())
    t2_mean, t2_win = _ret_stats_t2(sel["ret_t2_close"])

    a3_total = int(((d["label_A_high"] == 1) & (d[archetype_col] == "A3_early_structure_low_rs20")).sum())
    a5_total = int(((d["label_A_high"] == 1) & (d[archetype_col] == "A5_mixed_other")).sum())
    a3_cap = int((in_mainline & (d["label_A_high"] == 1) & (d[archetype_col] == "A3_early_structure_low_rs20")).sum())
    a5_cap = int((in_mainline & (d["label_A_high"] == 1) & (d[archetype_col] == "A5_mixed_other")).sum())

    return {
        "scenario": name,
        "selected_n": int(len(sel)),
        "A_recall_rate": float(a_sel / a_total) if a_total else np.nan,
        "A_high_recall_rate": float(ah_sel / ah_total) if ah_total else np.nan,
        "A_high_over_C": float(ah_sel / c_sel) if c_sel else np.nan,
        "A_low_plus_C_share": float((low_sel + c_sel) / len(sel)) if len(sel) else np.nan,
        "mean_ret_t2": t2_mean,
        "win_t2": t2_win,
        "A3_recall_rate": float(a3_cap / a3_total) if a3_total else np.nan,
        "A5_recall_rate": float(a5_cap / a5_total) if a5_total else np.nan,
    }


def write_review(df_cmp: pd.DataFrame, top_scope_signal: str) -> None:
    q2 = df_cmp[df_cmp["scenario"] == "C2A+ECH2_Q2"].iloc[0]
    s1 = df_cmp[df_cmp["scenario"] == "C2A+ECH2_S1"].iloc[0]
    s2 = df_cmp[df_cmp["scenario"] == "C2A+ECH2_S2"].iloc[0]

    def score(r: pd.Series) -> float:
        # recall-first but penalize quality decay
        return (
            4.0 * float(r["A_high_recall_rate"])
            + 1.5 * float(r["A3_recall_rate"])
            + 1.0 * float(r["A5_recall_rate"])
            + 0.8 * float(r["A_high_over_C"])
            - 1.2 * float(r["A_low_plus_C_share"])
            + 0.3 * float(r["win_t2"])
        )

    scores = {
        "C2A+ECH2_Q2": score(q2),
        "C2A+ECH2_S1": score(s1),
        "C2A+ECH2_S2": score(s2),
    }
    best = max(scores, key=scores.get)

    lines = [
        "# ECH2 通道覆盖扩张验证（快速版）",
        "",
        "## 结论摘要",
        f"- ECH2 当前最该扩的 scope 条件：{top_scope_signal}",
        f"- S1 vs S2 最优：{best}",
        f"- 是否较当前 Q2 有实质提升：{'是' if best != 'C2A+ECH2_Q2' else '否'}",
        "- 当前是否继续买点开发：不应该",
        "",
        "## S1 vs S2 对比（全年）",
        f"- Q2: n={int(q2['selected_n'])}, A_high_recall={q2['A_high_recall_rate']:.2%}, A_high/C={q2['A_high_over_C']:.4f}, A_low+C={q2['A_low_plus_C_share']:.2%}, T+2 mean={q2['mean_ret_t2']:.2%}, T+2 win={q2['win_t2']:.2%}, A3={q2['A3_recall_rate']:.2%}, A5={q2['A5_recall_rate']:.2%}",
        f"- S1: n={int(s1['selected_n'])}, A_high_recall={s1['A_high_recall_rate']:.2%}, A_high/C={s1['A_high_over_C']:.4f}, A_low+C={s1['A_low_plus_C_share']:.2%}, T+2 mean={s1['mean_ret_t2']:.2%}, T+2 win={s1['win_t2']:.2%}, A3={s1['A3_recall_rate']:.2%}, A5={s1['A5_recall_rate']:.2%}",
        f"- S2: n={int(s2['selected_n'])}, A_high_recall={s2['A_high_recall_rate']:.2%}, A_high/C={s2['A_high_over_C']:.4f}, A_low+C={s2['A_low_plus_C_share']:.2%}, T+2 mean={s2['mean_ret_t2']:.2%}, T+2 win={s2['win_t2']:.2%}, A3={s2['A3_recall_rate']:.2%}, A5={s2['A5_recall_rate']:.2%}",
        "",
        "## 4 个问题的直接回答",
        f"1. ECH2 当前最该扩的 scope 条件是什么：{top_scope_signal}",
        f"2. S1 / S2 哪个更值得进入下一轮正式验证：{best.split('+')[-1]}",
        f"3. C2A+ECH2_S* 是否比当前 C2A+ECH2_Q2 有实质提升：{'是' if best != 'C2A+ECH2_Q2' else '否'}",
        "4. 当前是否还应该继续买点开发：不应该",
    ]
    OUT_REVIEW.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    base = load_universe()
    base = add_quality_labels(base)

    cfg_c2a = CoreConfig(
        name="C2A",
        note="frozen single-channel baseline",
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
    d["in_C2A"] = d["in_core_pool"].eq(1)

    ah = d[d["label_A_high"] == 1].copy()
    ah["archetype"] = assign_archetype(ah)
    d = d.merge(ah[["ts_code", "trade_date", "archetype"]], on=["ts_code", "trade_date"], how="left")

    # Common quantile anchors (same family as current ECH2)
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

    # Current ECH2_Q2
    ech2_q2_base = build_ech2_mask(
        d,
        plat_floor=q_plat_65,
        comp_ceiling=q_comp_45,
        q_ind_55=q_ind_55,
        q_chip_50=q_chip_50,
        q_score_60=q_score_60,
    )
    in_ech2_q2 = apply_q2_gate(d, d["in_C2A"], ech2_q2_base)
    in_main_q2 = d["in_C2A"] | in_ech2_q2

    # S1: relax only platform floor (one key scope condition)
    ech2_s1_base = build_ech2_mask(
        d,
        plat_floor=q_plat_55,
        comp_ceiling=q_comp_45,
        q_ind_55=q_ind_55,
        q_chip_50=q_chip_50,
        q_score_60=q_score_60,
    )
    in_ech2_s1 = apply_q2_gate(d, d["in_C2A"], ech2_s1_base)
    in_main_s1 = d["in_C2A"] | in_ech2_s1

    # S2: relax platform floor + compression ceiling (two structure conditions)
    ech2_s2_base = build_ech2_mask(
        d,
        plat_floor=q_plat_55,
        comp_ceiling=q_comp_55,
        q_ind_55=q_ind_55,
        q_chip_50=q_chip_50,
        q_score_60=q_score_60,
    )
    in_ech2_s2 = apply_q2_gate(d, d["in_C2A"], ech2_s2_base)
    in_main_s2 = d["in_C2A"] | in_ech2_s2

    d["in_ECH2_Q2"] = in_ech2_q2
    d["in_mainline_current"] = in_main_q2

    # Gap compare: target missed A3/A5 out of scope vs captured in ECH2_Q2
    target = d[
        (d["label_A_high"] == 1)
        & (~d["in_mainline_current"])
        & (d["archetype"].isin(["A3_early_structure_low_rs20", "A5_mixed_other"]))
        & (~ech2_q2_base)
    ].copy()
    captured = d[(d["label_A_high"] == 1) & (d["in_ECH2_Q2"])].copy()

    gap_fields = [
        "score_platform_axis_single",
        "f_platform_compress_ratio",
        "score_total",
        "f_strength_rs20_xsec_q",
        "f_chip_winner_rate",
        "score_industry_axis_single",
        "rank_global_after_merge",
    ]
    gap_rows = []
    gap_rows.extend(_stats(target, "A_high_missed_A3A5_not_in_ECH2_scope", gap_fields))
    gap_rows.extend(_stats(captured, "A_high_captured_in_ECH2_Q2", gap_fields))
    gap_df = pd.DataFrame(gap_rows)
    gap_df.to_csv(OUT_GAP, index=False, encoding="utf-8-sig")

    cmp_rows = [
        scenario_metrics(d, "C2A+ECH2_Q2", in_main_q2, "archetype"),
        scenario_metrics(d, "C2A+ECH2_S1", in_main_s1, "archetype"),
        scenario_metrics(d, "C2A+ECH2_S2", in_main_s2, "archetype"),
    ]
    cmp_df = pd.DataFrame(cmp_rows)
    cmp_df.to_csv(OUT_COMPARE, index=False, encoding="utf-8-sig")

    # pick top scope signal from gap
    # Compare median and p75 gaps between missed-target and captured; prioritize largest absolute median gap.
    piv = gap_df.pivot(index="field", columns="group", values="median")
    top_signal = "platform/compression scope too tight"
    if (
        "A_high_missed_A3A5_not_in_ECH2_scope" in piv.columns
        and "A_high_captured_in_ECH2_Q2" in piv.columns
        and not piv.empty
    ):
        delta = (piv["A_high_missed_A3A5_not_in_ECH2_scope"] - piv["A_high_captured_in_ECH2_Q2"]).abs().sort_values(ascending=False)
        if len(delta):
            top_signal = f"{delta.index[0]} 差异最大"

    write_review(cmp_df, top_signal)

    print(str(OUT_GAP))
    print(str(OUT_COMPARE))
    print(str(OUT_REVIEW))


if __name__ == "__main__":
    main()

