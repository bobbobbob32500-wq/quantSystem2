from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from run_true_breakout_core_pool_recall_rebuild import CoreConfig, add_quality_labels, load_universe, run_selector_core


BASE = Path(r"D:\HuaweiAI\quantSystem2\data\research\strong_start_full\v4_scan")

OUT_SPLIT = BASE / "ahigh_archetype_split.csv"
OUT_COMPARE = BASE / "ahigh_in_vs_out_archetype_compare.csv"
OUT_REVIEW = BASE / "ahigh_archetype_review.md"


def assign_archetype(a: pd.DataFrame) -> pd.Series:
    """
    Rule-based archetype split (3~5 classes), only using existing selector fields.
    Priority order keeps classes mutually exclusive and interpretable.
    """
    rs20 = pd.to_numeric(a["f_strength_rs20_xsec_q"], errors="coerce")
    plat = pd.to_numeric(a["score_platform_axis_single"], errors="coerce")
    ind = pd.to_numeric(a["score_industry_axis_single"], errors="coerce")
    chip = pd.to_numeric(a["f_chip_winner_rate"], errors="coerce")
    comp = pd.to_numeric(a["f_platform_compress_ratio"], errors="coerce")
    score = pd.to_numeric(a["score_total"], errors="coerce")

    # data-driven cut points on A_high universe
    q_rs20_hi = rs20.quantile(0.70)
    q_rs20_lo = rs20.quantile(0.35)
    q_ind_hi = ind.quantile(0.70)
    q_plat_hi = plat.quantile(0.65)
    q_chip_hi = chip.quantile(0.65)
    q_comp_tight = comp.quantile(0.40)  # lower=more compressed
    q_score_hi = score.quantile(0.65)

    out = pd.Series("A5_mixed_other", index=a.index, dtype="object")

    # A1: high momentum + industry frontline
    m1 = (rs20 >= q_rs20_hi) & (ind >= q_ind_hi)
    out[m1] = "A1_momentum_frontline"

    # A2: structure-chip supported (tight platform + chip)
    m2 = (out == "A5_mixed_other") & (plat >= q_plat_hi) & (chip >= q_chip_hi) & (comp <= q_comp_tight)
    out[m2] = "A2_structure_chip"

    # A3: early-structure starter (rs20 lower, but structure still decent)
    m3 = (out == "A5_mixed_other") & (rs20 <= q_rs20_lo) & (plat >= plat.quantile(0.50)) & (comp <= comp.quantile(0.55))
    out[m3] = "A3_early_structure_low_rs20"

    # A4: broad-score balanced (score high but not captured above)
    m4 = (out == "A5_mixed_other") & (score >= q_score_hi)
    out[m4] = "A4_balanced_highscore"

    return out


def archetype_summary(a: pd.DataFrame) -> pd.DataFrame:
    rows = []
    total = len(a)
    for t, g in a.groupby("archetype"):
        n = len(g)
        in_n = int(g["in_C2A"].sum())
        out_n = int((1 - g["in_C2A"]).sum())
        rows.append(
            {
                "archetype": t,
                "sample_n": n,
                "share_in_all_A_high": float(n / total) if total else np.nan,
                "in_count": in_n,
                "out_count": out_n,
                "in_rate_within_type": float(in_n / n) if n else np.nan,
                "out_rate_within_type": float(out_n / n) if n else np.nan,
                "median_rs20": float(pd.to_numeric(g["f_strength_rs20_xsec_q"], errors="coerce").median()),
                "median_platform": float(pd.to_numeric(g["score_platform_axis_single"], errors="coerce").median()),
                "median_industry": float(pd.to_numeric(g["score_industry_axis_single"], errors="coerce").median()),
                "median_chip": float(pd.to_numeric(g["f_chip_winner_rate"], errors="coerce").median()),
                "median_compress": float(pd.to_numeric(g["f_platform_compress_ratio"], errors="coerce").median()),
                "median_score_total": float(pd.to_numeric(g["score_total"], errors="coerce").median()),
            }
        )
    return pd.DataFrame(rows).sort_values("sample_n", ascending=False).reset_index(drop=True)


def in_out_compare(a: pd.DataFrame) -> pd.DataFrame:
    grp = (
        a.groupby(["archetype", "in_C2A"], as_index=False)
        .size()
        .rename(columns={"size": "count"})
        .sort_values(["archetype", "in_C2A"], ascending=[True, False])
    )
    total_by_type = grp.groupby("archetype")["count"].transform("sum")
    grp["share_within_type"] = grp["count"] / total_by_type
    grp["group"] = np.where(grp["in_C2A"] == 1, "IN", "OUT")
    return grp[["archetype", "group", "count", "share_within_type"]]


def write_review(summary_df: pd.DataFrame, cmp_df: pd.DataFrame) -> None:
    # main missed type = OUT count highest
    out_rows = cmp_df[cmp_df["group"] == "OUT"].sort_values("count", ascending=False)
    top_missed = out_rows.iloc[0]["archetype"] if not out_rows.empty else "NA"

    # main captured type = IN count highest
    in_rows = cmp_df[cmp_df["group"] == "IN"].sort_values("count", ascending=False)
    top_captured = in_rows.iloc[0]["archetype"] if not in_rows.empty else "NA"

    md = [
        "# 全年 A_high 类型拆分（C2A 主线）",
        "",
        "## 结论摘要",
        f"- 全年 A_high 可拆为 5 类（4个主 archetype + 1个混合类）。",
        f"- C2A 当前主抓类型：`{top_captured}`。",
        f"- C2A 当前主漏类型：`{top_missed}`。",
        "- 当前问题已从单阈值问题升级为“类型通道覆盖不足”。",
        "",
        "## 下一版主线结构方向（仅方向）",
        "1. 保留现有 C2A 主通道用于 momentum_frontline + balanced_highscore，不动主干。",
        "2. 新增一个“early_structure_low_rs20”专用通道（结构/压缩优先，趋势门槛后移），作为第二通道而非阈值微调。",
    ]
    OUT_REVIEW.write_text("\n".join(md), encoding="utf-8")


def main() -> None:
    base = load_universe()
    base = add_quality_labels(base)

    cfg_c2a = CoreConfig(
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
    mapped = run_selector_core(base, cfg_c2a)
    mapped["in_C2A"] = mapped["in_core_pool"].astype(int)

    ah = mapped[mapped["label_A_high"] == 1].copy()
    ah["archetype"] = assign_archetype(ah)

    summary_df = archetype_summary(ah)
    summary_df.to_csv(OUT_SPLIT, index=False, encoding="utf-8-sig")

    cmp_df = in_out_compare(ah)
    cmp_df.to_csv(OUT_COMPARE, index=False, encoding="utf-8-sig")

    write_review(summary_df, cmp_df)

    print(str(OUT_SPLIT))
    print(str(OUT_COMPARE))
    print(str(OUT_REVIEW))


if __name__ == "__main__":
    main()

