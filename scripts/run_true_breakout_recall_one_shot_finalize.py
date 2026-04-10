from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from run_true_breakout_core_pool_recall_rebuild import CoreConfig, add_quality_labels, load_universe, run_selector_core
from run_ech2_scope_expansion_fast_review import build_ech2_mask, apply_q2_gate
from run_true_breakout_dual_channel_fast_review import assign_archetype


BASE = Path(r"D:\HuaweiAI\quantSystem2\data\research\strong_start_full\v4_scan")

OUT_MAP = BASE / "true_breakout_recall_one_shot_mapping.csv"
OUT_CMP = BASE / "true_breakout_recall_one_shot_compare.csv"
OUT_MISS = BASE / "true_breakout_recall_one_shot_miss_reason.csv"
OUT_MD = BASE / "true_breakout_recall_one_shot_review.md"

MAIN_FROM = "2025-12-30"
MAIN_TO = "2026-03-30"
CONFIRM_FROM = "2025-09-29"
CONFIRM_TO = "2025-12-29"


def _window_mask(df: pd.DataFrame, dfrom: str, dto: str) -> pd.Series:
    td = pd.to_datetime(df["trade_date"], errors="coerce")
    return (td >= pd.Timestamp(dfrom)) & (td <= pd.Timestamp(dto))


def _metrics(df: pd.DataFrame, scope: str, scenario: str, mask: pd.Series) -> dict:
    g = df[mask].copy()
    a_total = int((df["label_class"] == "A").sum())
    ah_total = int((df["label_A_high"] == 1).sum())
    a_sel = int((g["label_class"] == "A").sum())
    ah_sel = int((g["label_A_high"] == 1).sum())
    c_sel = int((g["label_class"] == "C").sum())
    low_sel = int((g["label_A_low"] == 1).sum())
    t2 = pd.to_numeric(g["ret_t2_close"], errors="coerce")
    return {
        "scope": scope,
        "scenario": scenario,
        "selected_n": int(len(g)),
        "A_recall_rate": float(a_sel / a_total) if a_total else np.nan,
        "A_high_recall_rate": float(ah_sel / ah_total) if ah_total else np.nan,
        "A_high_over_C": float(ah_sel / c_sel) if c_sel else np.nan,
        "A_low_plus_C_share": float((low_sel + c_sel) / len(g)) if len(g) else np.nan,
        "mean_ret_t2": float(t2.mean()) if len(t2) else np.nan,
        "median_ret_t2": float(t2.median()) if len(t2) else np.nan,
        "win_t2": float((t2 > 0).mean()) if len(t2) else np.nan,
    }


def _archetype_recall(df: pd.DataFrame, mask: pd.Series, arche: str) -> float:
    ah = df[(df["label_A_high"] == 1) & (df["archetype"] == arche)]
    if len(ah) == 0:
        return np.nan
    return float(mask.loc[ah.index].mean())


def build_mainline_masks(d: pd.DataFrame) -> dict[str, pd.Series]:
    d["in_C2A"] = d["in_core_pool"].eq(1)

    plat_all = pd.to_numeric(d["score_platform_axis_single"], errors="coerce")
    comp_all = pd.to_numeric(d["f_platform_compress_ratio"], errors="coerce")
    chip_all = pd.to_numeric(d["f_chip_winner_rate"], errors="coerce")
    ind_all = pd.to_numeric(d["score_industry_axis_single"], errors="coerce")
    score_all = pd.to_numeric(d["score_total"], errors="coerce")

    q_ind_55 = float(ind_all.quantile(0.55))
    q_chip_50 = float(chip_all.quantile(0.50))
    q_score_60 = float(score_all.quantile(0.60))

    # Q2 (old current)
    q_plat_65 = float(plat_all.quantile(0.65))
    q_comp_45 = float(comp_all.quantile(0.45))
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

    # S2
    q_plat_55 = float(plat_all.quantile(0.55))
    q_comp_55 = float(comp_all.quantile(0.55))
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

    # ER1: minimal rescue for not_in_path_A but pathB near-cut strong structure
    rs20 = pd.to_numeric(d["f_strength_rs20_xsec_q"], errors="coerce")
    trend = pd.to_numeric(d["f_trend_close_ma20_gap"], errors="coerce")
    plat = pd.to_numeric(d["score_platform_axis_single"], errors="coerce")
    comp = pd.to_numeric(d["f_platform_compress_ratio"], errors="coerce")
    chip = pd.to_numeric(d["f_chip_winner_rate"], errors="coerce")
    ind = pd.to_numeric(d["score_industry_axis_single"], errors="coerce")
    rank_b = pd.to_numeric(d["rank_b"], errors="coerce")

    q_plat_50 = float(plat.quantile(0.50))
    q_comp_60 = float(comp.quantile(0.60))
    q_chip_35 = float(chip.quantile(0.35))
    q_ind_45 = float(ind.quantile(0.45))

    er1 = (
        (~in_main_s2)
        & (~d["path_a_eligible"].fillna(False))
        & d["path_b_eligible"].fillna(False)
        & (trend >= 0.005)
        & (rs20 >= 0.52)
        & (rs20 < 0.72)
        & (plat >= q_plat_50)
        & (comp <= q_comp_60)
        & (chip >= q_chip_35)
        & (ind >= q_ind_45)
        & (rank_b <= 0.25)
    )
    in_main_s2_er1 = in_main_s2 | er1

    d["in_ech2_q2"] = in_ech2_q2
    d["in_ech2_s2"] = in_ech2_s2
    d["in_er1"] = er1
    d["in_mainline_s2_er1"] = in_main_s2_er1
    d["in_mainline_s2"] = in_main_s2
    d["in_mainline_q2"] = in_main_q2

    return {
        "C2A+ECH2_Q2": in_main_q2,
        "C2A+ECH2_S2": in_main_s2,
        "C2A+ECH2_S2+ER1": in_main_s2_er1,
    }


def miss_reason(df: pd.DataFrame, mask: pd.Series) -> pd.DataFrame:
    ah = df[df["label_A_high"] == 1].copy()
    miss = ah[~mask.loc[ah.index]].copy()
    total_ah = len(ah)
    total_miss = len(miss)

    miss["reason"] = np.where(
        ~miss["path_a_eligible"].fillna(False),
        np.where(miss["path_b_eligible"].fillna(False), "not_in_path_A_but_pathB_eligible", "not_in_path_A"),
        np.where(~miss["in_ech2_s2"].fillna(False), "not_in_ECH2_scope_or_q2", "other"),
    )
    out = miss.groupby("reason", as_index=False).size().rename(columns={"size": "miss_count"})
    out["miss_share_in_remaining_A_high"] = out["miss_count"] / total_miss if total_miss else np.nan
    out["miss_share_in_total_A_high"] = out["miss_count"] / total_ah if total_ah else np.nan
    return out.sort_values("miss_count", ascending=False)


def write_review(cmp_df: pd.DataFrame, miss_df: pd.DataFrame, d: pd.DataFrame, masks: dict[str, pd.Series]) -> None:
    full = cmp_df[cmp_df["scope"] == "full_year"].copy()
    q2 = full[full["scenario"] == "C2A+ECH2_Q2"].iloc[0]
    s2 = full[full["scenario"] == "C2A+ECH2_S2"].iloc[0]
    er = full[full["scenario"] == "C2A+ECH2_S2+ER1"].iloc[0]

    d_ah = float(er["A_high_recall_rate"] - s2["A_high_recall_rate"])
    d_ratio = float(er["A_high_over_C"] - s2["A_high_over_C"])
    d_win = float(er["win_t2"] - s2["win_t2"])

    a3_s2 = _archetype_recall(d, masks["C2A+ECH2_S2"], "A3_early_structure_low_rs20")
    a3_er = _archetype_recall(d, masks["C2A+ECH2_S2+ER1"], "A3_early_structure_low_rs20")
    a5_s2 = _archetype_recall(d, masks["C2A+ECH2_S2"], "A5_mixed_other")
    a5_er = _archetype_recall(d, masks["C2A+ECH2_S2+ER1"], "A5_mixed_other")

    top_reason = miss_df.iloc[0]["reason"] if not miss_df.empty else "NA"
    lines = [
        "# 召回主线一口气收口（S2+ER1）",
        "",
        "## 结论摘要",
        f"- 在 S2 基础上加入最小补漏通道 ER1 后，全年 A_high 召回：{s2['A_high_recall_rate']:.2%} -> {er['A_high_recall_rate']:.2%} (Δ {d_ah:+.2%})",
        f"- 质量变化：A_high/C {s2['A_high_over_C']:.4f} -> {er['A_high_over_C']:.4f} (Δ {d_ratio:+.4f}), T+2 win {s2['win_t2']:.2%} -> {er['win_t2']:.2%} (Δ {d_win:+.2%})",
        f"- A3 覆盖：{a3_s2:.2%} -> {a3_er:.2%}; A5 覆盖：{a5_s2:.2%} -> {a5_er:.2%}",
        f"- 当前剩余最大漏抓源：{top_reason}",
        "- 推进判断：继续召回主线修复，不恢复买点开发。",
        "",
        "## 快速对比（全年）",
        f"- Q2: A_high_recall={q2['A_high_recall_rate']:.2%}, A_high/C={q2['A_high_over_C']:.4f}, T+2 win={q2['win_t2']:.2%}",
        f"- S2: A_high_recall={s2['A_high_recall_rate']:.2%}, A_high/C={s2['A_high_over_C']:.4f}, T+2 win={s2['win_t2']:.2%}",
        f"- S2+ER1: A_high_recall={er['A_high_recall_rate']:.2%}, A_high/C={er['A_high_over_C']:.4f}, T+2 win={er['win_t2']:.2%}",
    ]
    OUT_MD.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    base = load_universe()
    base = add_quality_labels(base)

    cfg = CoreConfig(
        name="C2A",
        note="frozen c2a baseline",
        quota_a=2,
        quota_b=3,
        cutoff_a=0.20,
        cutoff_b=0.20,
        path_a_rs20_min=0.72,
        path_a_trend_min=0.02,
        path_b_rs20_min=0.60,
        path_b_trend_min=0.00,
    )
    d = run_selector_core(base, cfg)
    d["in_C2A"] = d["in_core_pool"].eq(1)

    ah = d[d["label_A_high"] == 1].copy()
    ah["archetype"] = assign_archetype(ah)
    d = d.merge(ah[["ts_code", "trade_date", "archetype"]], on=["ts_code", "trade_date"], how="left")

    masks = build_mainline_masks(d)

    # mapping
    map_cols = [
        "trade_date",
        "stock_code",
        "stock_name",
        "label_class",
        "label_A_high",
        "archetype",
        "path_source",
        "in_C2A",
        "in_mainline_q2",
        "in_mainline_s2",
        "in_er1",
        "in_mainline_s2_er1",
        "score_total",
        "score_platform_axis_single",
        "score_industry_axis_single",
        "f_chip_winner_rate",
        "f_platform_compress_ratio",
        "f_strength_rs20_xsec_q",
        "rank_global_after_merge",
        "ret_t2_close",
    ]
    d[map_cols].to_csv(OUT_MAP, index=False, encoding="utf-8-sig")

    rows = []
    scope_masks = {
        "full_year": pd.Series(True, index=d.index),
        "main_window": _window_mask(d, MAIN_FROM, MAIN_TO),
        "confirm_window": _window_mask(d, CONFIRM_FROM, CONFIRM_TO),
    }
    for scope, sm in scope_masks.items():
        sdf = d[sm]
        for scen, m in masks.items():
            rows.append(_metrics(sdf, scope, scen, m.loc[sdf.index]))
    cmp_df = pd.DataFrame(rows)
    cmp_df.to_csv(OUT_CMP, index=False, encoding="utf-8-sig")

    miss_df = miss_reason(d, masks["C2A+ECH2_S2+ER1"])
    miss_df.to_csv(OUT_MISS, index=False, encoding="utf-8-sig")

    write_review(cmp_df, miss_df, d, masks)

    print(str(OUT_MAP))
    print(str(OUT_CMP))
    print(str(OUT_MISS))
    print(str(OUT_MD))


if __name__ == "__main__":
    main()
