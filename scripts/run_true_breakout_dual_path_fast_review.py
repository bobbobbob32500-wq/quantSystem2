from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from run_true_breakout_core_pool_recall_rebuild import CoreConfig, add_quality_labels, load_universe, run_selector_core


BASE = Path(r"D:\HuaweiAI\quantSystem2\data\research\strong_start_full\v4_scan")

OUT_BREAKDOWN = BASE / "dual_path_miss_breakdown.csv"
OUT_COMPARE = BASE / "dual_path_candidates_compare.csv"
OUT_REVIEW = BASE / "dual_path_fast_review.md"


def _ret_stats_t2(selected: pd.DataFrame) -> tuple[float, float]:
    s = pd.to_numeric(selected["ret_t2_close"], errors="coerce")
    return float(s.mean()) if len(s) else np.nan, float((s > 0).mean()) if len(s) else np.nan


def _metrics(df: pd.DataFrame, scenario: str) -> dict:
    sel = df[df["in_core_pool"] == 1].copy()
    a_total = int((df["label_class"] == "A").sum())
    ah_total = int((df["label_A_high"] == 1).sum())
    a_sel = int((sel["label_class"] == "A").sum())
    ah_sel = int((sel["label_A_high"] == 1).sum())
    c_sel = int((sel["label_class"] == "C").sum())
    mean_t2, win_t2 = _ret_stats_t2(sel)
    return {
        "scenario": scenario,
        "selected_n": int(len(sel)),
        "A_recall_rate": float(a_sel / a_total) if a_total else np.nan,
        "A_high_recall_rate": float(ah_sel / ah_total) if ah_total else np.nan,
        "A_high_over_C": float(ah_sel / c_sel) if c_sel else np.nan,
        "mean_ret_t2": mean_t2,
        "win_t2": win_t2,
    }


def build_step1_breakdown(df: pd.DataFrame) -> pd.DataFrame:
    ah = df[df["label_A_high"] == 1].copy()
    ah_not_core = ah[ah["in_core_pool"] == 0].copy()
    step1 = ah_not_core[(~ah_not_core["path_a_eligible"]) & (~ah_not_core["path_b_eligible"])].copy()

    total_ah = int(len(ah))
    total_step1 = int(len(step1))
    if total_step1 == 0:
        return pd.DataFrame(
            [
                {
                    "sub_condition": "no_step1_miss",
                    "miss_count": 0,
                    "ratio_in_all_A_high": 0.0,
                    "ratio_in_step1_miss": 0.0,
                }
            ]
        )

    # C2A thresholds (frozen baseline for this fast review)
    conds = {
        "fail_pathA_rs20_min": pd.to_numeric(step1["f_strength_rs20_xsec_q"], errors="coerce") < 0.72,
        "fail_pathA_trend_min": pd.to_numeric(step1["f_trend_close_ma20_gap"], errors="coerce") < 0.02,
        "fail_pathB_rs20_min": pd.to_numeric(step1["f_strength_rs20_xsec_q"], errors="coerce") < 0.60,
        "fail_pathB_trend_min": pd.to_numeric(step1["f_trend_close_ma20_gap"], errors="coerce") < 0.00,
    }
    rows = []
    for name, mask in conds.items():
        cnt = int(mask.sum())
        rows.append(
            {
                "sub_condition": name,
                "miss_count": cnt,
                "ratio_in_all_A_high": float(cnt / total_ah) if total_ah else np.nan,
                "ratio_in_step1_miss": float(cnt / total_step1) if total_step1 else np.nan,
            }
        )
    out = pd.DataFrame(rows).sort_values("miss_count", ascending=False).reset_index(drop=True)
    return out


def write_review(breakdown: pd.DataFrame, compare: pd.DataFrame) -> None:
    top = breakdown.iloc[0]
    c2a = compare[compare["scenario"] == "C2A"].iloc[0]
    d1 = compare[compare["scenario"] == "D1"].iloc[0]
    d2 = compare[compare["scenario"] == "D2"].iloc[0]

    # pick by recall-first, then quality
    best = compare.sort_values(["A_high_recall_rate", "A_high_over_C"], ascending=[False, False]).iloc[0]
    space = bool(best["A_high_recall_rate"] > c2a["A_high_recall_rate"])

    md = [
        "# dual path eligibility 快速审计（C2A 基线）",
        "",
        "## 结论摘要",
        f"- step1 最大漏抓子条件：`{top['sub_condition']}`（{int(top['miss_count'])}）",
        f"- 推荐候选：`{best['scenario']}`",
        f"- A_high 召回：C2A {c2a['A_high_recall_rate']:.2%} -> {best['scenario']} {best['A_high_recall_rate']:.2%}",
        "- 当前不应恢复买点开发。",
        "",
        "## D1 vs D2",
        f"- D1: n={int(d1['selected_n'])}, A_high_recall={d1['A_high_recall_rate']:.2%}, "
        f"A_high/C={d1['A_high_over_C']:.4f}, mean_t2={d1['mean_ret_t2']:.4%}, win_t2={d1['win_t2']:.2%}",
        f"- D2: n={int(d2['selected_n'])}, A_high_recall={d2['A_high_recall_rate']:.2%}, "
        f"A_high/C={d2['A_high_over_C']:.4f}, mean_t2={d2['mean_ret_t2']:.4%}, win_t2={d2['win_t2']:.2%}",
        "",
        "## 4 个问题直接回答",
        f"1. 最大漏抓点：{top['sub_condition']}",
        f"2. 更值得落地：{best['scenario']}",
        f"3. 召回是否还有提升空间：{'有' if space else '有限'}",
        "4. 现在是否继续买点开发：不应该",
    ]
    OUT_REVIEW.write_text("\n".join(md), encoding="utf-8")


def main() -> None:
    base = load_universe()
    base = add_quality_labels(base)

    # C2A frozen baseline
    c2a_cfg = CoreConfig(
        name="C2A",
        note="frozen C2A baseline",
        quota_a=2,
        quota_b=3,
        cutoff_a=0.20,
        cutoff_b=0.20,
        path_a_rs20_min=0.72,
        path_a_trend_min=0.02,
        path_b_rs20_min=0.60,
        path_b_trend_min=0.00,
    )
    # D1 minimal relax: only tiny PathA eligibility relax
    d1_cfg = CoreConfig(
        name="D1",
        note="minimal relax on dual-path eligibility",
        quota_a=2,
        quota_b=3,
        cutoff_a=0.20,
        cutoff_b=0.20,
        path_a_rs20_min=0.70,
        path_a_trend_min=0.01,
        path_b_rs20_min=0.60,
        path_b_trend_min=0.00,
    )
    # D2 moderate relax: PathA + mild PathB eligibility relax
    d2_cfg = CoreConfig(
        name="D2",
        note="moderate relax on dual-path eligibility",
        quota_a=2,
        quota_b=3,
        cutoff_a=0.20,
        cutoff_b=0.20,
        path_a_rs20_min=0.68,
        path_a_trend_min=0.00,
        path_b_rs20_min=0.58,
        path_b_trend_min=-0.005,
    )

    c2a = run_selector_core(base, c2a_cfg)
    d1 = run_selector_core(base, d1_cfg)
    d2 = run_selector_core(base, d2_cfg)

    breakdown = build_step1_breakdown(c2a)
    breakdown.to_csv(OUT_BREAKDOWN, index=False, encoding="utf-8-sig")

    compare = pd.DataFrame(
        [
            _metrics(c2a, "C2A"),
            _metrics(d1, "D1"),
            _metrics(d2, "D2"),
        ]
    )
    compare.to_csv(OUT_COMPARE, index=False, encoding="utf-8-sig")

    write_review(breakdown, compare)
    print(str(OUT_BREAKDOWN))
    print(str(OUT_COMPARE))
    print(str(OUT_REVIEW))


if __name__ == "__main__":
    main()

