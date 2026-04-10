from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from run_true_breakout_core_pool_recall_rebuild import CoreConfig, add_quality_labels, load_universe, run_selector_core
from run_true_breakout_dual_channel_fast_review import assign_archetype


BASE = Path(r"D:\HuaweiAI\quantSystem2\data\research\strong_start_full\v4_scan")

OUT_VALIDATION = BASE / "dual_channel_mainline_v1_validation.csv"
OUT_ARCHETYPE = BASE / "dual_channel_mainline_v1_archetype_review.csv"
OUT_REVIEW = BASE / "dual_channel_mainline_v1_final_review.md"

MAIN_FROM = "2025-12-30"
MAIN_TO = "2026-03-30"
CONFIRM_FROM = "2025-09-29"
CONFIRM_TO = "2025-12-29"


def _window_slice(df: pd.DataFrame, dfrom: str, dto: str) -> pd.DataFrame:
    td = pd.to_datetime(df["trade_date"], errors="coerce")
    return df[(td >= pd.Timestamp(dfrom)) & (td <= pd.Timestamp(dto))].copy()


def build_ech2_mask(d: pd.DataFrame) -> pd.Series:
    rs20 = pd.to_numeric(d["f_strength_rs20_xsec_q"], errors="coerce")
    plat = pd.to_numeric(d["score_platform_axis_single"], errors="coerce")
    ind = pd.to_numeric(d["score_industry_axis_single"], errors="coerce")
    chip = pd.to_numeric(d["f_chip_winner_rate"], errors="coerce")
    comp = pd.to_numeric(d["f_platform_compress_ratio"], errors="coerce")
    trend = pd.to_numeric(d["f_trend_close_ma20_gap"], errors="coerce")
    score = pd.to_numeric(d["score_total"], errors="coerce")

    q_plat_65 = plat.quantile(0.65)
    q_comp_45 = comp.quantile(0.45)
    q_chip_50 = chip.quantile(0.50)
    q_ind_55 = ind.quantile(0.55)
    q_score_60 = score.quantile(0.60)

    base_rescue_scope = d["in_core_pool"].eq(0)
    ech2 = (
        base_rescue_scope
        & (trend >= 0.005)
        & (rs20 >= 0.58)
        & (rs20 < 0.72)
        & (plat >= q_plat_65)
        & (comp <= q_comp_45)
        & (chip >= q_chip_50)
        & ((ind >= q_ind_55) | (score >= q_score_60))
    )
    return ech2


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

    t1m, t1d, t1w = _ret_stats(sel["ret_t1_close"])
    t2m, t2d, t2w = _ret_stats(sel["ret_t2_close"])
    t3m, t3d, t3w = _ret_stats(sel["ret_t3_close"])

    return {
        "scope": scope,
        "scenario": scenario,
        "selected_n": int(len(sel)),
        "A_recall_rate": float(a_sel / a_total) if a_total else np.nan,
        "A_high_recall_rate": float(ah_sel / ah_total) if ah_total else np.nan,
        "A_high_over_C": float(ah_sel / c_sel) if c_sel else np.nan,
        "A_low_plus_C_share": float((low_sel + c_sel) / len(sel)) if len(sel) else np.nan,
        "mean_ret_t1": t1m,
        "median_ret_t1": t1d,
        "win_t1": t1w,
        "mean_ret_t2": t2m,
        "median_ret_t2": t2d,
        "win_t2": t2w,
        "mean_ret_t3": t3m,
        "median_ret_t3": t3d,
        "win_t3": t3w,
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


def write_review(validation_df: pd.DataFrame, arche_df: pd.DataFrame) -> None:
    def pick(scope: str, scen: str) -> pd.Series:
        return validation_df[(validation_df["scope"] == scope) & (validation_df["scenario"] == scen)].iloc[0]

    full_c2a = pick("full_year", "C2A")
    full_dual = pick("full_year", "dual_channel_mainline_v1")
    main_c2a = pick("main_window", "C2A")
    main_dual = pick("main_window", "dual_channel_mainline_v1")
    conf_c2a = pick("confirm_window", "C2A")
    conf_dual = pick("confirm_window", "dual_channel_mainline_v1")

    d_ah = float(full_dual["A_high_recall_rate"] - full_c2a["A_high_recall_rate"])
    d_ratio = float(full_dual["A_high_over_C"] - full_c2a["A_high_over_C"])
    d_lowc = float(full_dual["A_low_plus_C_share"] - full_c2a["A_low_plus_C_share"])
    d_win2 = float(full_dual["win_t2"] - full_c2a["win_t2"])

    # replacement decision: recall gain meaningful and quality degradation controllable
    replace = (d_ah >= 0.008) and (d_ratio >= -0.03) and (d_lowc <= 0.05) and (d_win2 >= -0.015)

    def cov(scen: str, arche: str) -> float:
        r = arche_df[(arche_df["scenario"] == scen) & (arche_df["archetype"] == arche)]
        return float(r.iloc[0]["archetype_recall_rate"]) if not r.empty else np.nan

    md = [
        "# dual_channel_mainline_v1 正式落地验证",
        "",
        "## 版本冻结",
        "- main_channel = C2A_rank_relax",
        "- early_structure_channel = ECH2",
        "- dual_channel_mainline_v1 = C2A OR ECH2",
        "",
        "## 结论摘要",
        f"- 双通道是否值得正式替代单通道：{'是' if replace else '否'}",
        f"- 全年 A_high 召回：{full_c2a['A_high_recall_rate']:.2%} -> {full_dual['A_high_recall_rate']:.2%} (Δ {d_ah:+.2%})",
        f"- 全年 A_high/C：{full_c2a['A_high_over_C']:.4f} -> {full_dual['A_high_over_C']:.4f} (Δ {d_ratio:+.4f})",
        f"- 全年 A_low+C 占比：{full_c2a['A_low_plus_C_share']:.2%} -> {full_dual['A_low_plus_C_share']:.2%} (Δ {d_lowc:+.2%})",
        f"- 全年 win_t2：{full_c2a['win_t2']:.2%} -> {full_dual['win_t2']:.2%} (Δ {d_win2:+.2%})",
        "- 当前不应恢复买点开发。",
        "",
        "## archetype 覆盖变化（A_high）",
        f"- A2_structure_chip: {cov('C2A','A2_structure_chip'):.2%} -> {cov('dual_channel_mainline_v1','A2_structure_chip'):.2%}",
        f"- A3_early_structure_low_rs20: {cov('C2A','A3_early_structure_low_rs20'):.2%} -> {cov('dual_channel_mainline_v1','A3_early_structure_low_rs20'):.2%}",
        f"- A4_balanced_highscore: {cov('C2A','A4_balanced_highscore'):.2%} -> {cov('dual_channel_mainline_v1','A4_balanced_highscore'):.2%}",
        f"- A5_mixed_other: {cov('C2A','A5_mixed_other'):.2%} -> {cov('dual_channel_mainline_v1','A5_mixed_other'):.2%}",
        "",
        "## 推进判断",
        f"- {'建议正式替代 C2A（进入新主线）' if replace else '暂不正式替代，保留为候选并继续结构修正'}",
        "- 当前是否继续买点开发：不应该",
        "",
        "## 窗口快照",
        f"- 主窗口 A_high/C: {main_c2a['A_high_over_C']:.4f} -> {main_dual['A_high_over_C']:.4f}；win_t2: {main_c2a['win_t2']:.2%} -> {main_dual['win_t2']:.2%}",
        f"- 确认窗口 A_high/C: {conf_c2a['A_high_over_C']:.4f} -> {conf_dual['A_high_over_C']:.4f}；win_t2: {conf_c2a['win_t2']:.2%} -> {conf_dual['win_t2']:.2%}",
    ]
    OUT_REVIEW.write_text("\n".join(md), encoding="utf-8")


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
    d["ech2"] = build_ech2_mask(d)

    mask_c2a = d["in_core_pool"].eq(1)
    mask_dual = mask_c2a | d["ech2"].fillna(False)

    rows = []
    for scope, sdf in [
        ("full_year", d),
        ("main_window", _window_slice(d, MAIN_FROM, MAIN_TO)),
        ("confirm_window", _window_slice(d, CONFIRM_FROM, CONFIRM_TO)),
    ]:
        rows.append(metric_for_mask(sdf, "C2A", scope, mask_c2a.loc[sdf.index]))
        rows.append(metric_for_mask(sdf, "dual_channel_mainline_v1", scope, mask_dual.loc[sdf.index]))
    val_df = pd.DataFrame(rows)
    val_df.to_csv(OUT_VALIDATION, index=False, encoding="utf-8-sig")

    arche_df = archetype_coverage(d, {"C2A": mask_c2a, "dual_channel_mainline_v1": mask_dual})
    arche_df.to_csv(OUT_ARCHETYPE, index=False, encoding="utf-8-sig")

    write_review(val_df, arche_df)
    print(str(OUT_VALIDATION))
    print(str(OUT_ARCHETYPE))
    print(str(OUT_REVIEW))


if __name__ == "__main__":
    main()

