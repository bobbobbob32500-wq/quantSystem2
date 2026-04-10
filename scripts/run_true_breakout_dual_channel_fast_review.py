from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from run_true_breakout_core_pool_recall_rebuild import CoreConfig, add_quality_labels, load_universe, run_selector_core


BASE = Path(r"D:\HuaweiAI\quantSystem2\data\research\strong_start_full\v4_scan")

OUT_ARCH = BASE / "dual_channel_architecture.md"
OUT_CAND = BASE / "early_structure_channel_candidates.csv"
OUT_COVER = BASE / "dual_channel_archetype_coverage.csv"
OUT_REVIEW = BASE / "dual_channel_fast_review.md"


def assign_archetype(a: pd.DataFrame) -> pd.Series:
    rs20 = pd.to_numeric(a["f_strength_rs20_xsec_q"], errors="coerce")
    plat = pd.to_numeric(a["score_platform_axis_single"], errors="coerce")
    ind = pd.to_numeric(a["score_industry_axis_single"], errors="coerce")
    chip = pd.to_numeric(a["f_chip_winner_rate"], errors="coerce")
    comp = pd.to_numeric(a["f_platform_compress_ratio"], errors="coerce")
    score = pd.to_numeric(a["score_total"], errors="coerce")

    q_rs20_hi = rs20.quantile(0.70)
    q_rs20_lo = rs20.quantile(0.35)
    q_ind_hi = ind.quantile(0.70)
    q_plat_hi = plat.quantile(0.65)
    q_chip_hi = chip.quantile(0.65)
    q_comp_tight = comp.quantile(0.40)
    q_score_hi = score.quantile(0.65)

    out = pd.Series("A5_mixed_other", index=a.index, dtype="object")
    m1 = (rs20 >= q_rs20_hi) & (ind >= q_ind_hi)
    out[m1] = "A1_momentum_frontline"
    m2 = (out == "A5_mixed_other") & (plat >= q_plat_hi) & (chip >= q_chip_hi) & (comp <= q_comp_tight)
    out[m2] = "A2_structure_chip"
    m3 = (out == "A5_mixed_other") & (rs20 <= q_rs20_lo) & (plat >= plat.quantile(0.50)) & (comp <= comp.quantile(0.55))
    out[m3] = "A3_early_structure_low_rs20"
    m4 = (out == "A5_mixed_other") & (score >= q_score_hi)
    out[m4] = "A4_balanced_highscore"
    return out


def build_early_channels(d: pd.DataFrame) -> pd.DataFrame:
    x = d.copy()
    rs20 = pd.to_numeric(x["f_strength_rs20_xsec_q"], errors="coerce")
    plat = pd.to_numeric(x["score_platform_axis_single"], errors="coerce")
    ind = pd.to_numeric(x["score_industry_axis_single"], errors="coerce")
    chip = pd.to_numeric(x["f_chip_winner_rate"], errors="coerce")
    comp = pd.to_numeric(x["f_platform_compress_ratio"], errors="coerce")
    trend = pd.to_numeric(x["f_trend_close_ma20_gap"], errors="coerce")

    # Quantile anchors keep rules simple and self-adaptive.
    q_plat_55 = plat.quantile(0.55)
    q_plat_65 = plat.quantile(0.65)
    q_comp_50 = comp.quantile(0.50)
    q_comp_45 = comp.quantile(0.45)
    q_chip_40 = chip.quantile(0.40)
    q_chip_50 = chip.quantile(0.50)
    q_ind_55 = ind.quantile(0.55)
    q_score_60 = pd.to_numeric(x["score_total"], errors="coerce").quantile(0.60)

    # Only rescue from out-of-core universe; keep path-A orientation.
    base_rescue_scope = (x["in_core_pool"] == 0)

    # ECH1: structure-first, allow lower rs20 and weaker chip maturity.
    x["ech1"] = (
        base_rescue_scope
        & (trend >= 0.00)
        & (rs20 >= 0.52)
        & (rs20 < 0.72)
        & (plat >= q_plat_55)
        & (comp <= q_comp_50)
        & (chip >= q_chip_40)
    )

    # ECH2: structure + light trend confirm (slightly stricter than ECH1).
    x["ech2"] = (
        base_rescue_scope
        & (trend >= 0.005)
        & (rs20 >= 0.58)
        & (rs20 < 0.72)
        & (plat >= q_plat_65)
        & (comp <= q_comp_45)
        & (chip >= q_chip_50)
        & ((ind >= q_ind_55) | (pd.to_numeric(x["score_total"], errors="coerce") >= q_score_60))
    )
    return x


def metric_for_mask(d: pd.DataFrame, name: str, mask: pd.Series) -> dict:
    sel = d[mask].copy()
    a_total = int((d["label_class"] == "A").sum())
    ah_total = int((d["label_A_high"] == 1).sum())
    a_sel = int((sel["label_class"] == "A").sum())
    ah_sel = int((sel["label_A_high"] == 1).sum())
    c_sel = int((sel["label_class"] == "C").sum())
    t1 = pd.to_numeric(sel["ret_t1_close"], errors="coerce")
    t2 = pd.to_numeric(sel["ret_t2_close"], errors="coerce")
    t3 = pd.to_numeric(sel["ret_t3_close"], errors="coerce")
    return {
        "scenario": name,
        "selected_n": int(len(sel)),
        "A_recall_rate": float(a_sel / a_total) if a_total else np.nan,
        "A_high_recall_rate": float(ah_sel / ah_total) if ah_total else np.nan,
        "A_high_over_C": float(ah_sel / c_sel) if c_sel else np.nan,
        "mean_ret_t1": float(t1.mean()) if len(t1) else np.nan,
        "median_ret_t1": float(t1.median()) if len(t1) else np.nan,
        "win_t1": float((t1 > 0).mean()) if len(t1) else np.nan,
        "mean_ret_t2": float(t2.mean()) if len(t2) else np.nan,
        "median_ret_t2": float(t2.median()) if len(t2) else np.nan,
        "win_t2": float((t2 > 0).mean()) if len(t2) else np.nan,
        "mean_ret_t3": float(t3.mean()) if len(t3) else np.nan,
        "median_ret_t3": float(t3.median()) if len(t3) else np.nan,
        "win_t3": float((t3 > 0).mean()) if len(t3) else np.nan,
    }


def build_archetype_coverage(d: pd.DataFrame, scenarios: dict[str, pd.Series]) -> pd.DataFrame:
    ah = d[d["label_A_high"] == 1].copy()
    rows = []
    for scen, mask in scenarios.items():
        cap = ah[mask.loc[ah.index]].copy()
        for arche, g in ah.groupby("archetype"):
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


def write_architecture_md() -> None:
    md = [
        "# 双通道主线结构（冻结草图）",
        "",
        "## main_channel（沿用 C2A_rank_relax）",
        "- 负责覆盖：A2_structure_chip、A4_balanced_highscore",
        "- 风格：趋势成熟 + 结构/筹码较完整",
        "",
        "## early_structure_channel（新候选）",
        "- 负责补抓：A3_early_structure_low_rs20 + A5 中结构可但趋势未成熟子群",
        "- 风格：结构优先、压缩优先、允许 rs20 偏低",
        "",
    ]
    OUT_ARCH.write_text("\n".join(md), encoding="utf-8")


def write_review(cand_df: pd.DataFrame, cover_df: pd.DataFrame) -> None:
    c2a = cand_df[cand_df["scenario"] == "C2A"].iloc[0]
    e1 = cand_df[cand_df["scenario"] == "C2A+ECH1"].iloc[0]
    e2 = cand_df[cand_df["scenario"] == "C2A+ECH2"].iloc[0]
    best = cand_df.sort_values(["A_high_recall_rate", "A_high_over_C"], ascending=[False, False]).iloc[0]

    def _get_cov(scenario: str, arche: str) -> float:
        r = cover_df[(cover_df["scenario"] == scenario) & (cover_df["archetype"] == arche)]
        return float(r.iloc[0]["archetype_recall_rate"]) if not r.empty else np.nan

    md = [
        "# 双通道主线快审",
        "",
        "## 结论摘要",
        f"- ECH 对 A3/A5 的覆盖改善：A3 recall C2A={_get_cov('C2A','A3_early_structure_low_rs20'):.2%}, "
        f"最佳双通道={_get_cov(best['scenario'],'A3_early_structure_low_rs20'):.2%}",
        f"- 当前最优候选：`{best['scenario']}`",
        f"- 是否明显优于单通道 C2A：{'是' if best['scenario'] != 'C2A' else '否'}",
        "",
        "## ECH1 vs ECH2 对比",
        f"- C2A: n={int(c2a['selected_n'])}, A_high_recall={c2a['A_high_recall_rate']:.2%}, A_high/C={c2a['A_high_over_C']:.4f}, mean_t2={c2a['mean_ret_t2']:.4%}, win_t2={c2a['win_t2']:.2%}",
        f"- C2A+ECH1: n={int(e1['selected_n'])}, A_high_recall={e1['A_high_recall_rate']:.2%}, A_high/C={e1['A_high_over_C']:.4f}, mean_t2={e1['mean_ret_t2']:.4%}, win_t2={e1['win_t2']:.2%}",
        f"- C2A+ECH2: n={int(e2['selected_n'])}, A_high_recall={e2['A_high_recall_rate']:.2%}, A_high/C={e2['A_high_over_C']:.4f}, mean_t2={e2['mean_ret_t2']:.4%}, win_t2={e2['win_t2']:.2%}",
        "",
        "## 单通道 vs 双通道覆盖对比（A_high archetype）",
        f"- A2_structure_chip: C2A={_get_cov('C2A','A2_structure_chip'):.2%}, best={_get_cov(best['scenario'],'A2_structure_chip'):.2%}",
        f"- A3_early_structure_low_rs20: C2A={_get_cov('C2A','A3_early_structure_low_rs20'):.2%}, best={_get_cov(best['scenario'],'A3_early_structure_low_rs20'):.2%}",
        f"- A5_mixed_other: C2A={_get_cov('C2A','A5_mixed_other'):.2%}, best={_get_cov(best['scenario'],'A5_mixed_other'):.2%}",
        "",
        "## 4 个问题的直接回答",
        f"1. 双通道是否优于单通道微调：{'是' if best['scenario'] != 'C2A' else '当前未充分证明'}",
        f"2. ECH1 / ECH2 更适合作为早启动通道：{('ECH1' if best['scenario']=='C2A+ECH1' else ('ECH2' if best['scenario']=='C2A+ECH2' else '暂无'))}",
        f"3. C2A+最优 ECH 是否明显优于 C2A：{'是' if best['scenario'] != 'C2A' else '否'}",
        "4. 当前是否继续买点开发：不应该",
    ]
    OUT_REVIEW.write_text("\n".join(md), encoding="utf-8")


def main() -> None:
    base = load_universe()
    base = add_quality_labels(base)

    cfg = CoreConfig(
        name="C2A",
        note="frozen mainline",
        quota_a=2,
        quota_b=3,
        cutoff_a=0.20,
        cutoff_b=0.20,
        path_a_rs20_min=0.72,
        path_a_trend_min=0.02,
        path_b_rs20_min=0.60,
        path_b_trend_min=0.00,
    )

    c2a_df = run_selector_core(base, cfg)
    c2a_df = build_early_channels(c2a_df)

    ah = c2a_df[c2a_df["label_A_high"] == 1].copy()
    ah["archetype"] = assign_archetype(ah)
    c2a_df = c2a_df.merge(ah[["ts_code", "trade_date", "archetype"]], on=["ts_code", "trade_date"], how="left")

    m_c2a = c2a_df["in_core_pool"] == 1
    m_ech1 = m_c2a | c2a_df["ech1"].fillna(False)
    m_ech2 = m_c2a | c2a_df["ech2"].fillna(False)

    cand_df = pd.DataFrame(
        [
            metric_for_mask(c2a_df, "C2A", m_c2a),
            metric_for_mask(c2a_df, "C2A+ECH1", m_ech1),
            metric_for_mask(c2a_df, "C2A+ECH2", m_ech2),
        ]
    )
    cand_df.to_csv(OUT_CAND, index=False, encoding="utf-8-sig")

    scenarios = {"C2A": m_c2a, "C2A+ECH1": m_ech1, "C2A+ECH2": m_ech2}
    cover_df = build_archetype_coverage(c2a_df, scenarios)
    cover_df.to_csv(OUT_COVER, index=False, encoding="utf-8-sig")

    write_architecture_md()
    write_review(cand_df, cover_df)

    print(str(OUT_ARCH))
    print(str(OUT_CAND))
    print(str(OUT_COVER))
    print(str(OUT_REVIEW))


if __name__ == "__main__":
    main()

