from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from run_true_breakout_core_pool_recall_rebuild import CoreConfig, add_quality_labels, load_universe, run_selector_core
from run_ech2_scope_expansion_fast_review import build_ech2_mask, apply_q2_gate


BASE = Path(r"D:\HuaweiAI\quantSystem2\data\research\strong_start_full\v4_scan")

OUT_COMPARE = BASE / "true_breakout_recall_v3_compare.csv"
OUT_MISS = BASE / "true_breakout_recall_v3_miss_reason.csv"
OUT_REVIEW = BASE / "true_breakout_recall_v3_review.md"

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
    old = full[full["scenario"] == "mainline_v2"].iloc[0]
    new = full[full["scenario"] == "mainline_v3"].iloc[0]
    top_reason = miss.iloc[0]["reason"] if not miss.empty else "NA"
    lines = [
        "# 召回主线 v3 最终验证",
        "",
        "## 结论摘要",
        f"- A_high 召回：{old['A_high_recall_rate']:.2%} -> {new['A_high_recall_rate']:.2%}",
        f"- A_high/C：{old['A_high_over_C']:.4f} -> {new['A_high_over_C']:.4f}",
        f"- A_low+C：{old['A_low_plus_C_share']:.2%} -> {new['A_low_plus_C_share']:.2%}",
        f"- T+2 win：{old['win_t2']:.2%} -> {new['win_t2']:.2%}",
        f"- 剩余最大漏抓源：{top_reason}",
        "- 推进判断：召回主线继续有效，但当前仍不恢复买点开发。",
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

    plat = pd.to_numeric(d["score_platform_axis_single"], errors="coerce")
    comp = pd.to_numeric(d["f_platform_compress_ratio"], errors="coerce")
    chip = pd.to_numeric(d["f_chip_winner_rate"], errors="coerce")
    ind = pd.to_numeric(d["score_industry_axis_single"], errors="coerce")
    score = pd.to_numeric(d["score_total"], errors="coerce")
    rs20 = pd.to_numeric(d["f_strength_rs20_xsec_q"], errors="coerce")
    trend = pd.to_numeric(d["f_trend_close_ma20_gap"], errors="coerce")
    rank_b = pd.to_numeric(d["rank_b"], errors="coerce")

    # mainline_v2 (= s3+er1+er2+er3)
    q_ind55 = float(ind.quantile(0.55))
    q_chip50 = float(chip.quantile(0.50))
    q_score60 = float(score.quantile(0.60))
    q_plat55 = float(plat.quantile(0.55))
    q_comp55 = float(comp.quantile(0.55))
    ech2_s2 = build_ech2_mask(
        d,
        plat_floor=q_plat55,
        comp_ceiling=q_comp55,
        q_ind_55=q_ind55,
        q_chip_50=q_chip50,
        q_score_60=q_score60,
    )
    in_ech2_s2 = apply_q2_gate(d, d["in_C2A"], ech2_s2)
    in_main_s2 = d["in_C2A"] | in_ech2_s2

    q_plat50 = float(plat.quantile(0.50))
    q_comp60 = float(comp.quantile(0.60))
    q_chip35 = float(chip.quantile(0.35))
    q_ind45 = float(ind.quantile(0.45))
    er1 = (
        (~in_main_s2)
        & (~d["path_a_eligible"].fillna(False))
        & d["path_b_eligible"].fillna(False)
        & (trend >= 0.005)
        & (rs20 >= 0.52)
        & (rs20 < 0.72)
        & (plat >= q_plat50)
        & (comp <= q_comp60)
        & (chip >= q_chip35)
        & (ind >= q_ind45)
        & (rank_b <= 0.25)
    )
    q_chip45 = float(chip.quantile(0.45))
    q_ind50 = float(ind.quantile(0.50))
    q_score55 = float(score.quantile(0.55))
    ech2_s3 = (
        d["in_core_pool"].eq(0)
        & (trend >= 0.005)
        & (rs20 >= 0.56)
        & (rs20 < 0.72)
        & (plat >= q_plat50)
        & (comp <= q_comp60)
        & (chip >= q_chip45)
        & ((ind >= q_ind50) | (score >= q_score55))
    )
    in_ech2_s3 = apply_q2_gate(d, d["in_C2A"], ech2_s3)
    heat = (ind >= ind.quantile(0.90)) & (rs20 >= rs20.quantile(0.90)) & (comp >= comp.quantile(0.70))
    in_ech2_s3 = in_ech2_s3 & (~heat)
    m_s3_er1 = d["in_C2A"] | in_ech2_s3 | er1

    q_rs80 = float(rs20.quantile(0.80))
    q_score70 = float(score.quantile(0.70))
    q_ind75 = float(ind.quantile(0.75))
    q_plat25 = float(plat.quantile(0.25))
    q_comp75 = float(comp.quantile(0.75))
    er2 = (
        (~m_s3_er1)
        & d["path_a_eligible"].fillna(False)
        & (rs20 >= q_rs80)
        & (trend >= 0.04)
        & (score >= q_score70)
        & (ind <= q_ind75)
        & (plat >= q_plat25)
        & (comp <= q_comp75)
    )
    m_old = m_s3_er1 | er2

    q_plat45 = float(plat.quantile(0.45))
    q_chip40 = float(chip.quantile(0.40))
    q_ind70 = float(ind.quantile(0.70))
    q_ind85 = float(ind.quantile(0.85))
    q_score65 = float(score.quantile(0.65))
    er3 = (
        (~m_old)
        & d["path_a_eligible"].fillna(False)
        & (trend >= 0.03)
        & (plat >= q_plat45)
        & (comp <= q_comp75)
        & (chip >= q_chip40)
        & ((ind >= q_ind70) | (score >= q_score65))
        & (ind <= q_ind85)
    )
    mainline_v2 = m_old | er3

    # v3: one extra focused high-rs structure rescue on top of v2
    er4 = (
        (~mainline_v2)
        & d["path_a_eligible"].fillna(False)
        & (rs20 >= 0.72)
        & (trend >= 0.025)
        & (plat >= q_plat45)
        & (comp <= q_comp75)
        & (chip >= q_chip40)
        & ((ind >= q_ind70) | (score >= q_score65))
        & (ind <= q_ind85)
    )
    mainline_v3 = mainline_v2 | er4

    rows = []
    scope_masks = {
        "full_year": pd.Series(True, index=d.index),
        "main_window": _window_mask(d, MAIN_FROM, MAIN_TO),
        "confirm_window": _window_mask(d, CONFIRM_FROM, CONFIRM_TO),
    }
    for scope, sm in scope_masks.items():
        sdf = d[sm]
        rows.append(_metric(sdf, scope, "mainline_v2", mainline_v2.loc[sdf.index]))
        rows.append(_metric(sdf, scope, "mainline_v3", mainline_v3.loc[sdf.index]))
    cmp = pd.DataFrame(rows)
    cmp.to_csv(OUT_COMPARE, index=False, encoding="utf-8-sig")

    miss = miss_reason(d, mainline_v3)
    miss.to_csv(OUT_MISS, index=False, encoding="utf-8-sig")

    write_review(cmp, miss)

    print(str(OUT_COMPARE))
    print(str(OUT_MISS))
    print(str(OUT_REVIEW))


if __name__ == "__main__":
    main()

