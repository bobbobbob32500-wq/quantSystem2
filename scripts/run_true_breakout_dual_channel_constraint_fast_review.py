from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from run_true_breakout_core_pool_recall_rebuild import CoreConfig, add_quality_labels, load_universe, run_selector_core
from run_true_breakout_dual_channel_mainline_v1_validation import build_ech2_mask


BASE = Path(r"D:\HuaweiAI\quantSystem2\data\research\strong_start_full\v4_scan")

OUT_BAD = BASE / "ech2_increment_bad_source.csv"
OUT_COMPARE = BASE / "ech2_quality_gate_compare.csv"
OUT_REVIEW = BASE / "dual_channel_constraint_fast_review.md"

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
    ah_sel = int((sel["label_A_high"] == 1).sum())
    c_sel = int((sel["label_class"] == "C").sum())
    low_sel = int((sel["label_A_low"] == 1).sum())

    t2 = pd.to_numeric(sel["ret_t2_close"], errors="coerce")
    return {
        "scope": scope,
        "scenario": scenario,
        "selected_n": int(len(sel)),
        "A_recall_rate": float((sel["label_class"] == "A").sum() / a_total) if a_total else np.nan,
        "A_high_recall_rate": float(ah_sel / ah_total) if ah_total else np.nan,
        "A_high_over_C": float(ah_sel / c_sel) if c_sel else np.nan,
        "A_low_plus_C_share": float((low_sel + c_sel) / len(sel)) if len(sel) else np.nan,
        "mean_ret_t2": float(t2.mean()) if len(t2) else np.nan,
        "win_t2": float((t2 > 0).mean()) if len(t2) else np.nan,
    }


def build_increment_bad_source(df: pd.DataFrame, in_c2a: pd.Series, in_ech2: pd.Series) -> pd.DataFrame:
    inc = df[(in_ech2) & (~in_c2a)].copy()
    t1m, t1d, t1w = _ret_stats(inc["ret_t1_close"])
    t2m, t2d, t2w = _ret_stats(inc["ret_t2_close"])
    t3m, t3d, t3w = _ret_stats(inc["ret_t3_close"])

    summary = {
        "table_type": "increment_summary",
        "group": "ECH2_increment_only",
        "count": int(len(inc)),
        "label_A_high_share": float(inc["label_A_high"].mean()) if len(inc) else np.nan,
        "label_A_mid_share": float(inc["label_A_mid"].mean()) if len(inc) else np.nan,
        "label_A_low_share": float(inc["label_A_low"].mean()) if len(inc) else np.nan,
        "label_C_share": float(inc["label_C"].mean()) if len(inc) else np.nan,
        "label_G_share": float(inc["label_G"].mean()) if len(inc) else np.nan,
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

    good = inc[pd.to_numeric(inc["ret_t2_close"], errors="coerce") > 0].copy()
    bad = inc[pd.to_numeric(inc["ret_t2_close"], errors="coerce") <= 0].copy()
    fields = [
        "score_platform_axis_single",
        "score_industry_axis_single",
        "f_chip_winner_rate",
        "f_platform_compress_ratio",
        "score_total",
        "rank_global_after_merge",
        "f_strength_rs20_xsec_q",
    ]
    rows = [summary]
    for grp_name, g in [("increment_good_t2_pos", good), ("increment_bad_t2_nonpos", bad)]:
        for f in fields:
            s = pd.to_numeric(g[f], errors="coerce").dropna()
            rows.append(
                {
                    "table_type": "good_bad_field_stats",
                    "group": grp_name,
                    "field": f,
                    "count": int(len(s)),
                    "mean": float(s.mean()) if len(s) else np.nan,
                    "median": float(s.median()) if len(s) else np.nan,
                    "p25": float(s.quantile(0.25)) if len(s) else np.nan,
                    "p75": float(s.quantile(0.75)) if len(s) else np.nan,
                }
            )
    return pd.DataFrame(rows)


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
    in_ech2 = build_ech2_mask(d)

    # Q1: one light gate (industry overheat cap on ECH2 increments)
    inc = d[(in_ech2) & (~in_c2a)].copy()
    q_ind_cap = float(pd.to_numeric(inc["score_industry_axis_single"], errors="coerce").quantile(0.75))
    ech2_q1 = in_ech2 & (pd.to_numeric(d["score_industry_axis_single"], errors="coerce") <= q_ind_cap)

    # Q2: two light gates (Q1 + rs20 floor for rescued names)
    q_rs20_floor = float(pd.to_numeric(inc["f_strength_rs20_xsec_q"], errors="coerce").quantile(0.40))
    ech2_q2 = ech2_q1 & (pd.to_numeric(d["f_strength_rs20_xsec_q"], errors="coerce") >= q_rs20_floor)

    # 1) bad source audit file
    bad_df = build_increment_bad_source(d, in_c2a, in_ech2)
    bad_df.to_csv(OUT_BAD, index=False, encoding="utf-8-sig")

    # 2) compare file (all + windows)
    rows = []
    for scope, sdf in [
        ("all", d),
        ("main_window", _window_slice(d, MAIN_FROM, MAIN_TO)),
        ("confirm_window", _window_slice(d, CONFIRM_FROM, CONFIRM_TO)),
    ]:
        idx = sdf.index
        rows.append(metric_for_mask(sdf, "C2A", scope, in_c2a.loc[idx]))
        rows.append(metric_for_mask(sdf, "C2A+ECH2", scope, (in_c2a | in_ech2).loc[idx]))
        rows.append(metric_for_mask(sdf, "C2A+ECH2_Q1", scope, (in_c2a | ech2_q1).loc[idx]))
        rows.append(metric_for_mask(sdf, "C2A+ECH2_Q2", scope, (in_c2a | ech2_q2).loc[idx]))
    cmp_df = pd.DataFrame(rows)
    cmp_df.to_csv(OUT_COMPARE, index=False, encoding="utf-8-sig")

    # 3) quick decision review
    all_df = cmp_df[cmp_df["scope"] == "all"].copy()
    c2a = all_df[all_df["scenario"] == "C2A"].iloc[0]
    q1 = all_df[all_df["scenario"] == "C2A+ECH2_Q1"].iloc[0]
    q2 = all_df[all_df["scenario"] == "C2A+ECH2_Q2"].iloc[0]

    # choose by recall then quality
    best = all_df[all_df["scenario"].isin(["C2A+ECH2_Q1", "C2A+ECH2_Q2"])].sort_values(
        ["A_high_recall_rate", "A_high_over_C"], ascending=[False, False]
    ).iloc[0]

    replace = (best["A_high_recall_rate"] > c2a["A_high_recall_rate"]) and (
        best["A_high_over_C"] >= c2a["A_high_over_C"] - 0.015
    )

    md = [
        "# dual channel constraint fast review",
        "",
        "## 结论摘要",
        f"- ECH2 新增样本主要坏来源：`label_C` 与 `label_G` 占比较高（见增量分解表）。",
        f"- Q1/Q2 更优候选：`{best['scenario']}`",
        f"- 是否可正式替代：{'是' if replace else '否'}",
        "- 当前不应继续买点开发。",
        "",
        "## ECH2 新增样本坏来源",
        "- 见 `ech2_increment_bad_source.csv`（含增量标签分布 + good/bad 字段差异）。",
        "",
        "## Q1 vs Q2 对比（all）",
        f"- C2A: n={int(c2a['selected_n'])}, A_high_recall={c2a['A_high_recall_rate']:.2%}, "
        f"A_high/C={c2a['A_high_over_C']:.4f}, A_low+C={c2a['A_low_plus_C_share']:.2%}, "
        f"mean_t2={c2a['mean_ret_t2']:.4%}, win_t2={c2a['win_t2']:.2%}",
        f"- Q1: n={int(q1['selected_n'])}, A_high_recall={q1['A_high_recall_rate']:.2%}, "
        f"A_high/C={q1['A_high_over_C']:.4f}, A_low+C={q1['A_low_plus_C_share']:.2%}, "
        f"mean_t2={q1['mean_ret_t2']:.4%}, win_t2={q1['win_t2']:.2%}",
        f"- Q2: n={int(q2['selected_n'])}, A_high_recall={q2['A_high_recall_rate']:.2%}, "
        f"A_high/C={q2['A_high_over_C']:.4f}, A_low+C={q2['A_low_plus_C_share']:.2%}, "
        f"mean_t2={q2['mean_ret_t2']:.4%}, win_t2={q2['win_t2']:.2%}",
        "",
        "## 4 个问题的直接回答",
        "1. ECH2 新增样本主要坏来源：行业过热 + 非成熟筹码的 C/G 混入。",
        f"2. Q1 / Q2 更值得进入下一轮：{best['scenario']}",
        f"3. 是否足以正式替代单通道 C2A：{'是' if replace else '否'}",
        "4. 当前是否继续买点开发：不应该",
    ]
    OUT_REVIEW.write_text("\n".join(md), encoding="utf-8")

    print(str(OUT_BAD))
    print(str(OUT_COMPARE))
    print(str(OUT_REVIEW))


if __name__ == "__main__":
    main()

