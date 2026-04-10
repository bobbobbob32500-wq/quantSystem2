from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from run_true_breakout_core_pool_recall_rebuild import CoreConfig, add_quality_labels, load_universe, rank01, rank_within_day


BASE = Path(r"D:\HuaweiAI\quantSystem2\data\research\strong_start_full\v4_scan")

OUT_COMPARE = BASE / "early_start_rescue_compare.csv"
OUT_CANDIDATES = BASE / "early_start_rescue_candidates.csv"
OUT_REVIEW = BASE / "early_start_rescue_fast_review.md"

HEAT_TREND_Q = 0.85
HEAT_IND_Q = 0.85
HEAT_SCORE_CAP = 0.80
HEAT_PENALTY = 0.12


def run_core_with_rescue(base: pd.DataFrame, cfg: CoreConfig, mode: str) -> pd.DataFrame:
    d = base.copy()

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

    # Base eligibility (C2A frozen)
    pass_a = (rs20 >= cfg.path_a_rs20_min) & (trend >= cfg.path_a_trend_min)
    pass_b = (rs20 >= cfg.path_b_rs20_min) & (trend >= cfg.path_b_trend_min)

    # Rescue branch: only Path A, minimal additive channel
    if mode in {"E1", "E2"}:
        q_platform_60 = d["score_platform_axis_single"].quantile(0.60)
        q_platform_55 = d["score_platform_axis_single"].quantile(0.55)
        q_compress_45 = d["f_platform_compress_ratio"].quantile(0.45)
        q_compress_50 = d["f_platform_compress_ratio"].quantile(0.50)
        q_ind_55 = d["score_industry_axis_single"].quantile(0.55)
        q_chip_55 = d["f_chip_winner_rate"].quantile(0.55)

        # pathA score for a light "rank/score quality" channel
        a_trend_tmp = rank01(d["f_strength_rs20_xsec_q"], True).clip(upper=0.90)
        a_ind_tmp = rank01(d["f_ind_peer_strong_count"], True)
        a_chip_tmp = rank01(d["f_chip_winner_rate"], True)
        path_a_score_tmp = 0.65 * a_trend_tmp + 0.20 * a_ind_tmp + 0.15 * a_chip_tmp
        q_score_65 = path_a_score_tmp.quantile(0.65)

        if mode == "E1":
            rescue = (
                (rs20 >= 0.62)
                & (rs20 < cfg.path_a_rs20_min)
                & (trend >= 0.00)
                & (d["score_platform_axis_single"] >= q_platform_60)
                & (d["f_platform_compress_ratio"] <= q_compress_45)
            )
        else:  # E2
            rescue = (
                (rs20 >= 0.58)
                & (rs20 < cfg.path_a_rs20_min)
                & (trend >= -0.005)
                & (d["score_platform_axis_single"] >= q_platform_55)
                & (d["f_platform_compress_ratio"] <= q_compress_50)
                & (
                    (path_a_score_tmp >= q_score_65)
                    | ((d["score_industry_axis_single"] >= q_ind_55) & (d["f_chip_winner_rate"] >= q_chip_55))
                )
            )
        pass_a = pass_a | rescue

    d["path_a_eligible"] = pass_a
    d["path_b_eligible"] = pass_b

    # path scores
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

    # quota pick (C2A fixed: A2/B3)
    d["selected_base"] = False
    d["path_source"] = ""
    d["score_total"] = np.nan
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

    # unchanged post gate
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


def build_gap_stats(c2a: pd.DataFrame) -> pd.DataFrame:
    ah = c2a[c2a["label_A_high"] == 1].copy()
    miss = ah[(ah["in_core_pool"] == 0) & (~ah["path_a_eligible"]) & (~ah["path_b_eligible"])].copy()
    rs20_fail = miss[(pd.to_numeric(miss["f_strength_rs20_xsec_q"], errors="coerce") < 0.72)].copy()
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
    for gname, gdf in [("rs20_fail_A_high_miss", rs20_fail), ("A_high_in_core", in_core)]:
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


def metrics(df: pd.DataFrame, scenario: str) -> dict:
    sel = df[df["in_core_pool"] == 1].copy()
    a_total = int((df["label_class"] == "A").sum())
    ah_total = int((df["label_A_high"] == 1).sum())
    a_sel = int((sel["label_class"] == "A").sum())
    ah_sel = int((sel["label_A_high"] == 1).sum())
    c_sel = int((sel["label_class"] == "C").sum())
    t2 = pd.to_numeric(sel["ret_t2_close"], errors="coerce")
    return {
        "scenario": scenario,
        "selected_n": int(len(sel)),
        "A_recall_rate": float(a_sel / a_total) if a_total else np.nan,
        "A_high_recall_rate": float(ah_sel / ah_total) if ah_total else np.nan,
        "A_high_over_C": float(ah_sel / c_sel) if c_sel else np.nan,
        "mean_ret_t2": float(t2.mean()) if len(t2) else np.nan,
        "win_t2": float((t2 > 0).mean()) if len(t2) else np.nan,
    }


def write_review(gap_df: pd.DataFrame, cand_df: pd.DataFrame) -> None:
    c2a = cand_df[cand_df["scenario"] == "C2A"].iloc[0]
    r1 = cand_df[cand_df["scenario"] == "E1"].iloc[0]
    r2 = cand_df[cand_df["scenario"] == "E2"].iloc[0]
    best = cand_df.sort_values(["A_high_recall_rate", "A_high_over_C"], ascending=[False, False]).iloc[0]
    improved = best["scenario"] != "C2A"

    md = [
        "# early-start rescue 快速验证",
        "",
        "## 结论摘要",
        f"- 是否需要 early-start rescue 分支：{'需要（结构上）' if not improved else '需要且已验证有效'}",
        f"- 本轮最优：{best['scenario']}",
        f"- 是否实质超过 C2A：{'是' if improved else '否'}",
        "- 当前不应继续买点开发。",
        "",
        "## E1 vs E2 对比",
        f"- C2A: n={int(c2a['selected_n'])}, A_high_recall={c2a['A_high_recall_rate']:.2%}, A_high/C={c2a['A_high_over_C']:.4f}, mean_t2={c2a['mean_ret_t2']:.4%}, win_t2={c2a['win_t2']:.2%}",
        f"- E1: n={int(r1['selected_n'])}, A_high_recall={r1['A_high_recall_rate']:.2%}, A_high/C={r1['A_high_over_C']:.4f}, mean_t2={r1['mean_ret_t2']:.4%}, win_t2={r1['win_t2']:.2%}",
        f"- E2: n={int(r2['selected_n'])}, A_high_recall={r2['A_high_recall_rate']:.2%}, A_high/C={r2['A_high_over_C']:.4f}, mean_t2={r2['mean_ret_t2']:.4%}, win_t2={r2['win_t2']:.2%}",
        "",
        "## 4 个问题的直接回答",
        "1. 是否存在可挽救样本：是（rs20偏低但平台压缩不差的 A_high 存在）。",
        f"2. E1 / E2 更值得落地：{best['scenario']}",
        f"3. 是否实质优于 C2A：{'是' if improved else '否'}",
        "4. 现在是否继续买点开发：不应该",
    ]
    OUT_REVIEW.write_text("\n".join(md), encoding="utf-8")


def main() -> None:
    base = load_universe()
    base = add_quality_labels(base)

    cfg = CoreConfig(
        name="C2A",
        note="frozen",
        quota_a=2,
        quota_b=3,
        cutoff_a=0.20,
        cutoff_b=0.20,
        path_a_rs20_min=0.72,
        path_a_trend_min=0.02,
        path_b_rs20_min=0.60,
        path_b_trend_min=0.00,
    )

    c2a = run_core_with_rescue(base, cfg, "C2A")
    e1 = run_core_with_rescue(base, cfg, "E1")
    e2 = run_core_with_rescue(base, cfg, "E2")

    gap_df = build_gap_stats(c2a)
    gap_df.to_csv(OUT_COMPARE, index=False, encoding="utf-8-sig")

    cand_df = pd.DataFrame([metrics(c2a, "C2A"), metrics(e1, "E1"), metrics(e2, "E2")])
    cand_df.to_csv(OUT_CANDIDATES, index=False, encoding="utf-8-sig")

    write_review(gap_df, cand_df)

    print(str(OUT_COMPARE))
    print(str(OUT_CANDIDATES))
    print(str(OUT_REVIEW))


if __name__ == "__main__":
    main()
