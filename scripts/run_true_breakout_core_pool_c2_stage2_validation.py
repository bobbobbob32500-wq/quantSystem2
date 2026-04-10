from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from run_true_breakout_core_pool_recall_rebuild import CoreConfig, add_quality_labels, load_universe, run_selector_core


ROOT = Path(r"D:\HuaweiAI\quantSystem2")
BASE = ROOT / "data/research/strong_start_full/v4_scan"

IN_EVAL210 = BASE / "true_breakout_v32_with_priority_tag.csv"

OUT_CANDIDATES = BASE / "true_breakout_core_pool_c2_stage2_candidates.csv"
OUT_FULL = BASE / "true_breakout_core_pool_c2_stage2_full_year_review.csv"
OUT_EVAL = BASE / "true_breakout_core_pool_c2_stage2_eval210_review.csv"
OUT_MD = BASE / "true_breakout_core_pool_c2_stage2_validation.md"


def _ret_stats(s: pd.Series) -> tuple[float, float, float]:
    x = pd.to_numeric(s, errors="coerce")
    if x.empty:
        return np.nan, np.nan, np.nan
    return float(x.mean()), float(x.median()), float((x > 0).mean())


def build_metrics(df: pd.DataFrame, scenario: str, scope: str) -> dict:
    selected = df[df["in_core_pool"] == 1].copy()
    a_total = int((df["label_class"] == "A").sum())
    ah_total = int((df["label_A_high"] == 1).sum())
    c_total = int((df["label_class"] == "C").sum())

    a_sel = int((selected["label_class"] == "A").sum())
    ah_sel = int((selected["label_A_high"] == 1).sum())
    c_sel = int((selected["label_class"] == "C").sum())

    mean1, med1, win1 = _ret_stats(selected["ret_t1_close"])
    mean2, med2, win2 = _ret_stats(selected["ret_t2_close"])
    mean3, med3, win3 = _ret_stats(selected["ret_t3_close"])

    return {
        "scope": scope,
        "scenario": scenario,
        "total_events": int(len(df)),
        "selected_n": int(len(selected)),
        "A_total": a_total,
        "A_selected": a_sel,
        "A_recall_rate": float(a_sel / a_total) if a_total else np.nan,
        "A_high_total": ah_total,
        "A_high_selected": ah_sel,
        "A_high_recall_rate": float(ah_sel / ah_total) if ah_total else np.nan,
        "C_total": c_total,
        "C_selected": c_sel,
        "C_selected_share": float(c_sel / len(selected)) if len(selected) else np.nan,
        "A_high_over_C": float(ah_sel / c_sel) if c_sel else np.nan,
        "mean_ret_t1": mean1,
        "median_ret_t1": med1,
        "win_t1": win1,
        "mean_ret_t2": mean2,
        "median_ret_t2": med2,
        "win_t2": win2,
        "mean_ret_t3": mean3,
        "median_ret_t3": med3,
        "win_t3": win3,
    }


def load_eval210_keys() -> pd.DataFrame:
    d = pd.read_csv(IN_EVAL210)
    keys = d[["ts_code", "trade_date"]].copy()
    keys["ts_code"] = keys["ts_code"].astype(str)
    keys["trade_date"] = keys["trade_date"].astype(str)
    return keys.drop_duplicates().reset_index(drop=True)


def write_review_md(full_df: pd.DataFrame, eval_df: pd.DataFrame, cfg_df: pd.DataFrame) -> None:
    full_df = full_df.copy()
    eval_df = eval_df.copy()
    full_df["rank_recall"] = full_df["A_high_recall_rate"].rank(method="min", ascending=False)
    full_df["rank_quality"] = full_df["A_high_over_C"].rank(method="min", ascending=False)

    c2 = full_df[full_df["scenario"] == "C2"].iloc[0]
    c2a = full_df[full_df["scenario"] == "C2A_rank_relax"].iloc[0]
    c2b = full_df[full_df["scenario"] == "C2B_eligibility_relax"].iloc[0]
    c2ab = full_df[full_df["scenario"] == "C2AB_combo"].iloc[0]

    # Practical pick: prioritize A_high recall, then A_high/C and win_t2.
    best = (
        full_df.sort_values(["A_high_recall_rate", "A_high_over_C", "win_t2"], ascending=[False, False, False])
        .iloc[0]
        .to_dict()
    )

    md = [
        "# C2 第二阶段：PathA rank cutoff + dual eligibility 验证",
        "",
        "## 结论摘要",
        f"- 单刀对召回提升贡献更大的是：`{('PathA rank cutoff' if c2a['A_high_recall_rate'] - c2['A_high_recall_rate'] >= c2b['A_high_recall_rate'] - c2['A_high_recall_rate'] else 'dual path eligibility')}`。",
        f"- 当前性价比最高单刀候选：`{('C2A_rank_relax' if (c2a['A_high_recall_rate'] - c2['A_high_recall_rate']) >= (c2b['A_high_recall_rate'] - c2['A_high_recall_rate']) else 'C2B_eligibility_relax')}`。",
        f"- 组合候选 `C2AB_combo` 是否值得进第三阶段：{'值得' if best['scenario']=='C2AB_combo' else '可作为候选，但非最优'}。",
        "- 当前仍不应恢复买点开发。",
        "",
        "## 全年关键数值（A_high召回率 / A_high/C / win_t2）",
        f"- C2: {c2['A_high_recall_rate']:.2%} / {c2['A_high_over_C']:.4f} / {c2['win_t2']:.2%}",
        f"- C2A_rank_relax: {c2a['A_high_recall_rate']:.2%} / {c2a['A_high_over_C']:.4f} / {c2a['win_t2']:.2%}",
        f"- C2B_eligibility_relax: {c2b['A_high_recall_rate']:.2%} / {c2b['A_high_over_C']:.4f} / {c2b['win_t2']:.2%}",
        f"- C2AB_combo: {c2ab['A_high_recall_rate']:.2%} / {c2ab['A_high_over_C']:.4f} / {c2ab['win_t2']:.2%}",
        "",
        "## 210 子集方向一致性",
    ]
    for s in ["C2", "C2A_rank_relax", "C2B_eligibility_relax", "C2AB_combo"]:
        r = eval_df[eval_df["scenario"] == s].iloc[0]
        md.append(
            f"- {s}: n={int(r['selected_n'])}, A_high/C={r['A_high_over_C']:.4f}, "
            f"win_t2={r['win_t2']:.2%}, mean_t2={r['mean_ret_t2']:.4%}"
        )

    md.extend(
        [
            "",
            "## 推进判断",
            f"- 第三阶段优先候选：`{best['scenario']}`",
            "- 当前应继续召回主线验证，不应恢复买点开发。",
        ]
    )
    OUT_MD.write_text("\n".join(md), encoding="utf-8")

    summary = {
        "candidates": cfg_df.to_dict("records"),
        "full_year": full_df.to_dict("records"),
        "eval210": eval_df.to_dict("records"),
        "best_candidate": best,
        "decision": {
            "enter_stage3_recall_validation": True,
            "continue_buypoint_development": False,
        },
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))


def main() -> None:
    base = load_universe()
    base = add_quality_labels(base)

    # C2 frozen baseline
    cfg_c2 = CoreConfig(
        name="C2",
        note="frozen stage1 recall version (quota A=2, B=3)",
        quota_a=2,
        quota_b=3,
    )
    # Single-knife A: relax PathA rank cutoff only
    cfg_c2a = CoreConfig(
        name="C2A_rank_relax",
        note="only relax PathA cutoff (A: top10% -> top20%)",
        quota_a=2,
        quota_b=3,
        cutoff_a=0.20,
        cutoff_b=0.20,
    )
    # Single-knife B: relax dual eligibility only
    cfg_c2b = CoreConfig(
        name="C2B_eligibility_relax",
        note="only relax dual eligibility (A rs20/trend, B rs20/trend)",
        quota_a=2,
        quota_b=3,
        cutoff_a=0.10,
        cutoff_b=0.20,
        path_a_rs20_min=0.68,
        path_a_trend_min=0.00,
        path_b_rs20_min=0.58,
        path_b_trend_min=-0.005,
    )
    # Combo
    cfg_c2ab = CoreConfig(
        name="C2AB_combo",
        note="relax PathA cutoff + relax dual eligibility",
        quota_a=2,
        quota_b=3,
        cutoff_a=0.20,
        cutoff_b=0.20,
        path_a_rs20_min=0.68,
        path_a_trend_min=0.00,
        path_b_rs20_min=0.58,
        path_b_trend_min=-0.005,
    )

    cfgs = [cfg_c2, cfg_c2a, cfg_c2b, cfg_c2ab]
    cfg_df = pd.DataFrame(
        [
            {
                "scenario": c.name,
                "quota_a": c.quota_a,
                "quota_b": c.quota_b,
                "cutoff_a": c.cutoff_a,
                "cutoff_b": c.cutoff_b,
                "path_a_rs20_min": c.path_a_rs20_min,
                "path_a_trend_min": c.path_a_trend_min,
                "path_b_rs20_min": c.path_b_rs20_min,
                "path_b_trend_min": c.path_b_trend_min,
                "note": c.note,
            }
            for c in cfgs
        ]
    )
    cfg_df.to_csv(OUT_CANDIDATES, index=False, encoding="utf-8-sig")

    mapped = {c.name: run_selector_core(base, c) for c in cfgs}

    full_rows = [build_metrics(mapped[c.name], c.name, "full_year") for c in cfgs]
    full_df = pd.DataFrame(full_rows)
    full_df.to_csv(OUT_FULL, index=False, encoding="utf-8-sig")

    keys = load_eval210_keys()
    eval_rows = []
    for c in cfgs:
        d210 = mapped[c.name].merge(keys, on=["ts_code", "trade_date"], how="inner")
        eval_rows.append(build_metrics(d210, c.name, "eval210"))
    eval_df = pd.DataFrame(eval_rows)
    eval_df.to_csv(OUT_EVAL, index=False, encoding="utf-8-sig")

    write_review_md(full_df, eval_df, cfg_df)
    print(str(OUT_CANDIDATES))
    print(str(OUT_FULL))
    print(str(OUT_EVAL))
    print(str(OUT_MD))


if __name__ == "__main__":
    main()

