from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from run_true_breakout_core_pool_recall_rebuild import (
    CoreConfig,
    add_quality_labels,
    load_universe,
    rank01,
    rank_within_day,
)


BASE = Path(r"D:\HuaweiAI\quantSystem2\data\research\strong_start_full\v4_scan")

OUT_GAP = BASE / "rs20_gap_compare.csv"
OUT_COMPARE = BASE / "rs20_candidates_compare.csv"
OUT_REVIEW = BASE / "rs20_fast_review.md"

HEAT_TREND_Q = 0.85
HEAT_IND_Q = 0.85
HEAT_SCORE_CAP = 0.80
HEAT_PENALTY = 0.12


def run_core_with_rs20_override(base: pd.DataFrame, cfg: CoreConfig, mode: str) -> pd.DataFrame:
    d = base.copy()

    # same scoring backbone as frozen core
    d["score_trend_axis_single"] = (
        0.90 * rank01(d["f_strength_rs20_xsec_q"], True).clip(upper=0.90)
        + 0.10
        * pd.concat(
            [
                rank01(d["f_strength_ret20"], True),
                rank01(d["f_strength_rs60_xsec_q"], True),
                rank01(d["f_trend_close_ma20_gap"], True),
                rank01(d["f_trend_ma20_ma60_gap"], True),
                rank01(d["f_trend_ma20_slope5"], True),
            ],
            axis=1,
        ).mean(axis=1)
    )
    d["score_platform_axis_single"] = (
        0.70 * rank01(d["f_platform_compress_ratio"], False) + 0.30 * rank01(d["f_platform_range30"], False)
    )
    d["score_chip_axis_single"] = (
        0.45 * rank01(d["f_chip_winner_rate"], True)
        + 0.35 * rank01(d["f_chip_low_position120"], True)
        + 0.20 * rank01(d["f_chip_stability_std10"], True)
    )
    d["score_industry_axis_single"] = (
        0.75 * rank01(d["f_ind_peer_strong_count"], True) + 0.25 * rank01(d["f_ind_strength_5d"], True)
    )

    rs20 = pd.to_numeric(d["f_strength_rs20_xsec_q"], errors="coerce")
    trend = pd.to_numeric(d["f_trend_close_ma20_gap"], errors="coerce")

    if mode == "C2A":
        pass_a_rs20 = rs20 >= cfg.path_a_rs20_min
        pass_b_rs20 = rs20 >= cfg.path_b_rs20_min
    elif mode == "R1":
        # Minimal precise loosen (only rs20 thresholds slightly lower)
        pass_a_rs20 = rs20 >= 0.70
        pass_b_rs20 = rs20 >= 0.58
    elif mode == "R2":
        # rs20 substitute channel: rs20 slightly lower but stronger platform/chip/industry profile.
        q_platform = d["score_platform_axis_single"].quantile(0.60)
        q_chip = d["f_chip_winner_rate"].quantile(0.60)
        q_industry = d["score_industry_axis_single"].quantile(0.55)
        q_compress = d["f_platform_compress_ratio"].quantile(0.45)

        strong_combo_a = (
            (d["score_platform_axis_single"] >= q_platform)
            & (d["f_chip_winner_rate"] >= q_chip)
            & (d["f_platform_compress_ratio"] <= q_compress)
        )
        strong_combo_b = (
            (d["score_platform_axis_single"] >= q_platform)
            & (d["f_chip_winner_rate"] >= q_chip)
            & (d["score_industry_axis_single"] >= q_industry)
        )

        pass_a_rs20 = (rs20 >= cfg.path_a_rs20_min) | ((rs20 >= 0.68) & strong_combo_a)
        pass_b_rs20 = (rs20 >= cfg.path_b_rs20_min) | ((rs20 >= 0.56) & strong_combo_b)
    else:
        raise ValueError(mode)

    d["path_a_eligible"] = pass_a_rs20 & (trend >= cfg.path_a_trend_min)
    d["path_b_eligible"] = pass_b_rs20 & (trend >= cfg.path_b_trend_min)

    # same path scoring + heat cap
    a_trend = rank01(d["f_strength_rs20_xsec_q"], True).clip(upper=0.90)
    a_ind = rank01(d["f_ind_peer_strong_count"], True)
    a_chip = rank01(d["f_chip_winner_rate"], True)
    d["pathA_score"] = 0.65 * a_trend + 0.20 * a_ind + 0.15 * a_chip
    heat = (a_trend >= HEAT_TREND_Q) & (a_ind >= HEAT_IND_Q)
    d.loc[heat, "pathA_score"] = np.minimum(d.loc[heat, "pathA_score"], HEAT_SCORE_CAP) - HEAT_PENALTY
    d["rank_a"] = rank_within_day(d["path_a_eligible"], d["pathA_score"], d["trade_date"])
    d["path_a_pass"] = d["path_a_eligible"] & (d["rank_a"] <= cfg.cutoff_a)

    b_chip = 0.60 * rank01(d["f_chip_winner_rate"], True) + 0.40 * rank01(d["f_chip_low_position120"], True)
    d["pathB_score"] = 0.50 * d["score_platform_axis_single"] + 0.40 * b_chip + 0.10 * rank01(
        d["f_strength_rs20_xsec_q"], True
    )
    d["rank_b"] = rank_within_day(d["path_b_eligible"], d["pathB_score"], d["trade_date"])
    d["path_b_pass"] = d["path_b_eligible"] & (d["rank_b"] <= cfg.cutoff_b)

    # same quota (C2A fixed): A=2, B=3
    d["selected_base"] = False
    d["path_source"] = ""
    d["score_total"] = np.nan
    d["rank_global_after_merge"] = np.nan
    for td, g in d.groupby("trade_date"):
        idx_a = g.index[d.loc[g.index, "path_a_pass"]]
        idx_b = g.index[d.loc[g.index, "path_b_pass"]]
        pick_a = d.loc[idx_a].assign(_s=d.loc[idx_a, "pathA_score"]).sort_values("_s", ascending=False).head(cfg.quota_a).index
        pick_b = d.loc[idx_b].assign(_s=d.loc[idx_b, "pathB_score"]).sort_values("_s", ascending=False).head(cfg.quota_b).index
        picks = pick_a.union(pick_b)
        if len(picks) == 0:
            continue
        d.loc[picks, "selected_base"] = True
        d.loc[pick_a, "path_source"] = "A"
        d.loc[pick_a, "score_total"] = d.loc[pick_a, "pathA_score"]
        b_only = [i for i in pick_b if i not in set(pick_a)]
        d.loc[b_only, "path_source"] = "B"
        d.loc[b_only, "score_total"] = d.loc[b_only, "pathB_score"]
        both = [i for i in pick_b if i in set(pick_a)]
        for i in both:
            sa = float(d.at[i, "pathA_score"])
            sb = float(d.at[i, "pathB_score"])
            if pd.notna(sa) and (pd.isna(sb) or sa >= sb):
                d.at[i, "path_source"] = "A"
                d.at[i, "score_total"] = sa
            else:
                d.at[i, "path_source"] = "B"
                d.at[i, "score_total"] = sb
        gsel = d.loc[picks, "score_total"]
        d.loc[picks, "rank_global_after_merge"] = gsel.rank(method="first", ascending=False).astype(int)

    # unchanged core_pool post-gate
    s = d[d["selected_base"]].copy()
    if s.empty:
        d["in_core_pool"] = 0
        return d
    q_ind_60 = s["score_industry_axis_single"].quantile(0.60)
    q_chip_65 = s["f_chip_winner_rate"].quantile(0.65)
    q_platform_35 = s["score_platform_axis_single"].quantile(0.35)
    q_comp_65 = s["f_platform_compress_ratio"].quantile(0.65)
    r2 = ~((d["score_industry_axis_single"] >= q_ind_60) & (d["f_chip_winner_rate"] >= q_chip_65))
    r3 = ~((d["score_platform_axis_single"] <= q_platform_35) & (d["f_platform_compress_ratio"] >= q_comp_65))
    d["in_core_pool"] = (d["selected_base"] & r2 & r3).astype(int)
    return d


def build_gap_compare(c2a_df: pd.DataFrame) -> pd.DataFrame:
    ah = c2a_df[c2a_df["label_A_high"] == 1].copy()
    miss_step1 = ah[
        (ah["in_core_pool"] == 0) & (~ah["path_a_eligible"]) & (~ah["path_b_eligible"])
    ].copy()

    rs20_fail = miss_step1[
        (pd.to_numeric(miss_step1["f_strength_rs20_xsec_q"], errors="coerce") < 0.72)
        | (pd.to_numeric(miss_step1["f_strength_rs20_xsec_q"], errors="coerce") < 0.60)
    ].copy()
    in_core = ah[ah["in_core_pool"] == 1].copy()

    fields = [
        "f_strength_rs20_xsec_q",
        "score_platform_axis_single",
        "score_industry_axis_single",
        "f_chip_winner_rate",
        "f_platform_compress_ratio",
        "score_total",
    ]

    rows = []
    for gname, gdf in [
        ("A_high_miss_step1_rs20_fail", rs20_fail),
        ("A_high_in_core_pool", in_core),
    ]:
        for f in fields:
            s = pd.to_numeric(gdf[f], errors="coerce").dropna()
            rows.append(
                {
                    "group": gname,
                    "field": f,
                    "count": int(len(s)),
                    "mean": float(s.mean()) if len(s) else np.nan,
                    "median": float(s.median()) if len(s) else np.nan,
                    "p25": float(s.quantile(0.25)) if len(s) else np.nan,
                    "p75": float(s.quantile(0.75)) if len(s) else np.nan,
                }
            )
    return pd.DataFrame(rows)


def metrics(df: pd.DataFrame, name: str) -> dict:
    sel = df[df["in_core_pool"] == 1].copy()
    a_total = int((df["label_class"] == "A").sum())
    ah_total = int((df["label_A_high"] == 1).sum())
    a_sel = int((sel["label_class"] == "A").sum())
    ah_sel = int((sel["label_A_high"] == 1).sum())
    c_sel = int((sel["label_class"] == "C").sum())
    t2 = pd.to_numeric(sel["ret_t2_close"], errors="coerce")
    return {
        "scenario": name,
        "selected_n": int(len(sel)),
        "A_recall_rate": float(a_sel / a_total) if a_total else np.nan,
        "A_high_recall_rate": float(ah_sel / ah_total) if ah_total else np.nan,
        "A_high_over_C": float(ah_sel / c_sel) if c_sel else np.nan,
        "mean_ret_t2": float(t2.mean()) if len(t2) else np.nan,
        "win_t2": float((t2 > 0).mean()) if len(t2) else np.nan,
    }


def write_review(gap: pd.DataFrame, cmp_df: pd.DataFrame) -> None:
    c2a = cmp_df[cmp_df["scenario"] == "C2A"].iloc[0]
    r1 = cmp_df[cmp_df["scenario"] == "R1"].iloc[0]
    r2 = cmp_df[cmp_df["scenario"] == "R2"].iloc[0]
    best = cmp_df.sort_values(["A_high_recall_rate", "A_high_over_C"], ascending=[False, False]).iloc[0]

    # quick rescue signal
    pivot = gap.pivot(index="field", columns="group", values="median")
    rs20_miss = pivot.loc["f_strength_rs20_xsec_q", "A_high_miss_step1_rs20_fail"]
    rs20_in = pivot.loc["f_strength_rs20_xsec_q", "A_high_in_core_pool"]
    platform_miss = pivot.loc["score_platform_axis_single", "A_high_miss_step1_rs20_fail"]
    platform_in = pivot.loc["score_platform_axis_single", "A_high_in_core_pool"]

    md = [
        "# rs20 eligibility 最短路径快审",
        "",
        "## 结论摘要",
        f"- rs20 漏抓 A_high 特征：rs20中位数 miss={rs20_miss:.4f} vs in_core={rs20_in:.4f}；"
        f"platform中位数 miss={platform_miss:.4f} vs in_core={platform_in:.4f}。",
        f"- 推荐候选：`{best['scenario']}`",
        "- 当前不应恢复买点开发。",
        "",
        "## R1 vs R2 对比",
        f"- C2A: n={int(c2a['selected_n'])}, A_high_recall={c2a['A_high_recall_rate']:.2%}, "
        f"A_high/C={c2a['A_high_over_C']:.4f}, mean_t2={c2a['mean_ret_t2']:.4%}, win_t2={c2a['win_t2']:.2%}",
        f"- R1: n={int(r1['selected_n'])}, A_high_recall={r1['A_high_recall_rate']:.2%}, "
        f"A_high/C={r1['A_high_over_C']:.4f}, mean_t2={r1['mean_ret_t2']:.4%}, win_t2={r1['win_t2']:.2%}",
        f"- R2: n={int(r2['selected_n'])}, A_high_recall={r2['A_high_recall_rate']:.2%}, "
        f"A_high/C={r2['A_high_over_C']:.4f}, mean_t2={r2['mean_ret_t2']:.4%}, win_t2={r2['win_t2']:.2%}",
        "",
        "## 4 个问题直接回答",
        "1. rs20漏抓A_high是否可挽救：是，存在“rs20略低但平台/筹码不差”的样本。",
        f"2. R1/R2更值得落地：{best['scenario']}",
        f"3. 是否实质优于C2A：{'是' if best['scenario']!='C2A' else '否'}",
        "4. 现在是否继续买点开发：不应该",
    ]
    OUT_REVIEW.write_text("\n".join(md), encoding="utf-8")


def main() -> None:
    base = load_universe()
    base = add_quality_labels(base)

    c2a_cfg = CoreConfig(
        name="C2A",
        note="current frozen recall-mainline version",
        quota_a=2,
        quota_b=3,
        cutoff_a=0.20,
        cutoff_b=0.20,
        path_a_rs20_min=0.72,
        path_a_trend_min=0.02,
        path_b_rs20_min=0.60,
        path_b_trend_min=0.00,
    )
    c2a = run_core_with_rs20_override(base, c2a_cfg, "C2A")
    r1 = run_core_with_rs20_override(base, c2a_cfg, "R1")
    r2 = run_core_with_rs20_override(base, c2a_cfg, "R2")

    gap = build_gap_compare(c2a)
    gap.to_csv(OUT_GAP, index=False, encoding="utf-8-sig")

    cmp_df = pd.DataFrame([metrics(c2a, "C2A"), metrics(r1, "R1"), metrics(r2, "R2")])
    cmp_df.to_csv(OUT_COMPARE, index=False, encoding="utf-8-sig")

    write_review(gap, cmp_df)
    print(str(OUT_GAP))
    print(str(OUT_COMPARE))
    print(str(OUT_REVIEW))


if __name__ == "__main__":
    main()

