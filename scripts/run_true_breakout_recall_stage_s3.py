from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from run_true_breakout_core_pool_recall_rebuild import CoreConfig, add_quality_labels, load_universe, run_selector_core
from run_ech2_scope_expansion_fast_review import build_ech2_mask, apply_q2_gate
from run_true_breakout_dual_channel_fast_review import assign_archetype


BASE = Path(r"D:\HuaweiAI\quantSystem2\data\research\strong_start_full\v4_scan")

OUT_MAP = BASE / "true_breakout_recall_stage_s3_mapping.csv"
OUT_COMPARE = BASE / "true_breakout_recall_stage_s3_compare.csv"
OUT_MISS = BASE / "true_breakout_recall_stage_s3_miss_reason.csv"
OUT_REVIEW = BASE / "true_breakout_recall_stage_s3_review.md"

MAIN_FROM = "2025-12-30"
MAIN_TO = "2026-03-30"
CONFIRM_FROM = "2025-09-29"
CONFIRM_TO = "2025-12-29"


def _window_mask(df: pd.DataFrame, dfrom: str, dto: str) -> pd.Series:
    td = pd.to_datetime(df["trade_date"], errors="coerce")
    return (td >= pd.Timestamp(dfrom)) & (td <= pd.Timestamp(dto))


def _metric(df: pd.DataFrame, scope: str, scenario: str, mask: pd.Series) -> dict:
    g = df[mask].copy()
    a_total = int((df["label_class"] == "A").sum())
    ah_total = int((df["label_A_high"] == 1).sum())
    a_sel = int((g["label_class"] == "A").sum())
    ah_sel = int((g["label_A_high"] == 1).sum())
    c_sel = int((g["label_class"] == "C").sum())
    low_sel = int((g["label_A_low"] == 1).sum())

    t2 = pd.to_numeric(g["ret_t2_close"], errors="coerce")
    out = {
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

    for arche in ["A3_early_structure_low_rs20", "A5_mixed_other"]:
        base = (df["label_A_high"] == 1) & (df["archetype"] == arche)
        n = int(base.sum())
        out[f"{arche}_recall"] = float((mask & base).sum() / n) if n else np.nan
    return out


def miss_reason(df: pd.DataFrame, mask: pd.Series) -> pd.DataFrame:
    ah = df[df["label_A_high"] == 1].copy()
    miss = ah[~mask.loc[ah.index]].copy()
    total_ah = len(ah)
    total_miss = len(miss)

    miss["reason"] = np.where(
        ~miss["path_a_eligible"].fillna(False),
        np.where(miss["path_b_eligible"].fillna(False), "not_in_path_A_but_pathB_eligible", "not_in_path_A"),
        "not_in_ECH2_scope_or_q2",
    )
    out = miss.groupby("reason", as_index=False).size().rename(columns={"size": "miss_count"})
    out["miss_share_in_remaining_A_high"] = out["miss_count"] / total_miss if total_miss else np.nan
    out["miss_share_in_total_A_high"] = out["miss_count"] / total_ah if total_ah else np.nan
    return out.sort_values("miss_count", ascending=False)


def write_review(cmp: pd.DataFrame, miss: pd.DataFrame) -> None:
    full = cmp[cmp["scope"] == "full_year"].copy()
    base = full[full["scenario"] == "mainline_s2_er1"].iloc[0]
    s3 = full[full["scenario"] == "mainline_s3_er1"].iloc[0]
    s3e2 = full[full["scenario"] == "mainline_s3_er1_er2"].iloc[0]

    best = max(
        [base, s3, s3e2],
        key=lambda r: (
            float(r["A_high_recall_rate"]) * 4.0
            + float(r["A3_early_structure_low_rs20_recall"]) * 1.2
            + float(r["A5_mixed_other_recall"]) * 0.8
            + float(r["A_high_over_C"]) * 0.8
            - float(r["A_low_plus_C_share"]) * 1.0
            + float(r["win_t2"]) * 0.2
        ),
    )
    top_reason = miss.iloc[0]["reason"] if not miss.empty else "NA"

    lines = [
        "# 召回阶段 S3 快速验证",
        "",
        "## 结论摘要",
        f"- 当前最优方案：{best['scenario']}",
        f"- 全年 A_high 召回（vs mainline_s2_er1）: {base['A_high_recall_rate']:.2%} -> {best['A_high_recall_rate']:.2%}",
        f"- 全年 A_high/C（vs base）: {base['A_high_over_C']:.4f} -> {best['A_high_over_C']:.4f}",
        f"- 全年 T+2 win（vs base）: {base['win_t2']:.2%} -> {best['win_t2']:.2%}",
        f"- 剩余最大漏抓源：{top_reason}",
        "- 推进判断：继续修召回，不恢复买点开发。",
    ]
    OUT_REVIEW.write_text("\n".join(lines), encoding="utf-8")


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

    # shared quant anchors
    plat_all = pd.to_numeric(d["score_platform_axis_single"], errors="coerce")
    comp_all = pd.to_numeric(d["f_platform_compress_ratio"], errors="coerce")
    chip_all = pd.to_numeric(d["f_chip_winner_rate"], errors="coerce")
    ind_all = pd.to_numeric(d["score_industry_axis_single"], errors="coerce")
    score_all = pd.to_numeric(d["score_total"], errors="coerce")
    rs20 = pd.to_numeric(d["f_strength_rs20_xsec_q"], errors="coerce")
    trend = pd.to_numeric(d["f_trend_close_ma20_gap"], errors="coerce")
    rank_b = pd.to_numeric(d["rank_b"], errors="coerce")

    q_ind_55 = float(ind_all.quantile(0.55))
    q_chip_50 = float(chip_all.quantile(0.50))
    q_score_60 = float(score_all.quantile(0.60))

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

    # ER1 (existing)
    q_plat_50 = float(plat_all.quantile(0.50))
    q_comp_60 = float(comp_all.quantile(0.60))
    q_chip_35 = float(chip_all.quantile(0.35))
    q_ind_45 = float(ind_all.quantile(0.45))
    er1 = (
        (~in_main_s2)
        & (~d["path_a_eligible"].fillna(False))
        & d["path_b_eligible"].fillna(False)
        & (trend >= 0.005)
        & (rs20 >= 0.52)
        & (rs20 < 0.72)
        & (plat_all >= q_plat_50)
        & (comp_all <= q_comp_60)
        & (chip_all >= q_chip_35)
        & (ind_all >= q_ind_45)
        & (rank_b <= 0.25)
    )
    m_s2_er1 = in_main_s2 | er1

    # S3 (expand ECH2 scope slightly + overheat veto)
    q_plat_50_s3 = float(plat_all.quantile(0.50))
    q_comp_60_s3 = float(comp_all.quantile(0.60))
    q_chip_45_s3 = float(chip_all.quantile(0.45))
    q_ind_50_s3 = float(ind_all.quantile(0.50))
    q_score_55_s3 = float(score_all.quantile(0.55))
    ech2_s3_base = (
        d["in_core_pool"].eq(0)
        & (trend >= 0.005)
        & (rs20 >= 0.56)
        & (rs20 < 0.72)
        & (plat_all >= q_plat_50_s3)
        & (comp_all <= q_comp_60_s3)
        & (chip_all >= q_chip_45_s3)
        & ((ind_all >= q_ind_50_s3) | (score_all >= q_score_55_s3))
    )
    in_ech2_s3 = apply_q2_gate(d, d["in_C2A"], ech2_s3_base)
    # overheat veto
    heat = (ind_all >= ind_all.quantile(0.90)) & (rs20 >= rs20.quantile(0.90)) & (comp_all >= comp_all.quantile(0.70))
    in_ech2_s3 = in_ech2_s3 & (~heat)
    m_s3_er1 = d["in_C2A"] | in_ech2_s3 | er1

    # ER2 (momentum-structure rescue for pathA-eligible names still outside S3+ER1)
    q_rs80_er2 = float(rs20.quantile(0.80))
    q_score_70_er2 = float(score_all.quantile(0.70))
    q_ind_75_er2 = float(ind_all.quantile(0.75))
    q_plat_25_er2 = float(plat_all.quantile(0.25))
    q_comp_75_er2 = float(comp_all.quantile(0.75))
    er2 = (
        (~m_s3_er1)
        & d["path_a_eligible"].fillna(False)
        & (rs20 >= q_rs80_er2)
        & (trend >= 0.04)
        & (score_all >= q_score_70_er2)
        & (ind_all <= q_ind_75_er2)
        & (plat_all >= q_plat_25_er2)
        & (comp_all <= q_comp_75_er2)
    )
    m_s3_er1_er2 = m_s3_er1 | er2

    rows = []
    scenarios = {
        "mainline_s2_er1": m_s2_er1,
        "mainline_s3_er1": m_s3_er1,
        "mainline_s3_er1_er2": m_s3_er1_er2,
    }
    scope_masks = {
        "full_year": pd.Series(True, index=d.index),
        "main_window": _window_mask(d, MAIN_FROM, MAIN_TO),
        "confirm_window": _window_mask(d, CONFIRM_FROM, CONFIRM_TO),
    }
    for scope, sm in scope_masks.items():
        sdf = d[sm]
        for scen, m in scenarios.items():
            rows.append(_metric(sdf, scope, scen, m.loc[sdf.index]))
    cmp_df = pd.DataFrame(rows)
    cmp_df.to_csv(OUT_COMPARE, index=False, encoding="utf-8-sig")

    miss_df = miss_reason(d, m_s3_er1_er2)
    miss_df.to_csv(OUT_MISS, index=False, encoding="utf-8-sig")

    d["in_mainline_s2_er1"] = m_s2_er1
    d["in_mainline_s3_er1"] = m_s3_er1
    d["in_mainline_s3_er1_er2"] = m_s3_er1_er2
    keep_cols = [
        "trade_date",
        "stock_code",
        "stock_name",
        "label_class",
        "label_A_high",
        "archetype",
        "in_mainline_s2_er1",
        "in_mainline_s3_er1",
        "in_mainline_s3_er1_er2",
        "in_C2A",
        "path_source",
        "score_total",
        "score_platform_axis_single",
        "score_industry_axis_single",
        "f_chip_winner_rate",
        "f_platform_compress_ratio",
        "f_strength_rs20_xsec_q",
        "rank_global_after_merge",
        "ret_t2_close",
    ]
    d[keep_cols].to_csv(OUT_MAP, index=False, encoding="utf-8-sig")

    write_review(cmp_df, miss_df)

    print(str(OUT_MAP))
    print(str(OUT_COMPARE))
    print(str(OUT_MISS))
    print(str(OUT_REVIEW))


if __name__ == "__main__":
    main()
