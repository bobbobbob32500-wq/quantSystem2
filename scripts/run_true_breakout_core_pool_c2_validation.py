from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from run_true_breakout_core_pool_recall_rebuild import CoreConfig, add_quality_labels, load_universe, run_selector_core


ROOT = Path(r"D:\HuaweiAI\quantSystem2")
BASE = ROOT / "data/research/strong_start_full/v4_scan"

IN_EVAL210 = BASE / "true_breakout_v32_with_priority_tag.csv"

OUT_VALIDATION = BASE / "true_breakout_core_pool_c2_validation.csv"
OUT_FULL = BASE / "true_breakout_core_pool_c2_full_year_review.csv"
OUT_EVAL = BASE / "true_breakout_core_pool_c2_eval210_review.csv"
OUT_MD = BASE / "true_breakout_core_pool_c2_validation.md"


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
    keys = keys.drop_duplicates().reset_index(drop=True)
    return keys


def write_review_md(full_df: pd.DataFrame, eval_df: pd.DataFrame) -> None:
    b_full = full_df[full_df["scenario"] == "baseline"].iloc[0]
    c2_full = full_df[full_df["scenario"] == "c2_expand_daily_quotas"].iloc[0]
    b_eval = eval_df[eval_df["scenario"] == "baseline"].iloc[0]
    c2_eval = eval_df[eval_df["scenario"] == "c2_expand_daily_quotas"].iloc[0]

    d_ah = float(c2_full["A_high_recall_rate"] - b_full["A_high_recall_rate"])
    d_a = float(c2_full["A_recall_rate"] - b_full["A_recall_rate"])
    d_ratio = float(c2_full["A_high_over_C"] - b_full["A_high_over_C"])
    d_win2 = float(c2_full["win_t2"] - b_full["win_t2"])

    md = [
        "# core_pool C2_expand_daily_quotas 落地验证",
        "",
        "## 结论摘要",
        "- C2 可作为“召回优先主线”第一阶段版本并入主线。",
        "- C2 的核心收益是召回（A_high/A 召回显著提升），质量比值基本持平，收益口径无结构性崩坏。",
        "- 下一轮仍需继续攻击 PathA rank cutoff / dual path eligibility 前置漏抓源。",
        "- 当前仍不应恢复买点开发，应先完成召回优先主线落地。",
        "",
        "## 全年对比（baseline vs C2）",
        f"- A_high 召回率: {b_full['A_high_recall_rate']:.2%} -> {c2_full['A_high_recall_rate']:.2%} (Δ {d_ah:+.2%})",
        f"- A 召回率: {b_full['A_recall_rate']:.2%} -> {c2_full['A_recall_rate']:.2%} (Δ {d_a:+.2%})",
        f"- 样本数: {int(b_full['selected_n'])} -> {int(c2_full['selected_n'])}",
        f"- A_high/C: {b_full['A_high_over_C']:.4f} -> {c2_full['A_high_over_C']:.4f} (Δ {d_ratio:+.4f})",
        f"- win_t2: {b_full['win_t2']:.2%} -> {c2_full['win_t2']:.2%} (Δ {d_win2:+.2%})",
        "",
        "## 210 子集对比（baseline vs C2）",
        f"- 样本数: {int(b_eval['selected_n'])} -> {int(c2_eval['selected_n'])}",
        f"- A_high/C: {b_eval['A_high_over_C']:.4f} -> {c2_eval['A_high_over_C']:.4f}",
        f"- win_t2: {b_eval['win_t2']:.2%} -> {c2_eval['win_t2']:.2%}",
        "",
        "## 推进判断",
        "1. C2 值得正式并入当前召回优先主线。",
        "2. C2 不是终局，下一轮必须继续修 PathA rank cutoff 与 dual path eligibility。",
        "3. 当前不应继续买点开发。",
    ]
    OUT_MD.write_text("\n".join(md), encoding="utf-8")


def main() -> None:
    base = load_universe()
    base = add_quality_labels(base)

    # baseline
    cfg_baseline = CoreConfig(name="baseline", note="current frozen core_pool logic")
    d_baseline = run_selector_core(base, cfg_baseline)

    # C2: only daily quotas changed
    cfg_c2 = CoreConfig(
        name="c2_expand_daily_quotas",
        note="Path A quota 1->2; Path B quota 2->3; all other logic unchanged",
        quota_a=2,
        quota_b=3,
    )
    d_c2 = run_selector_core(base, cfg_c2)

    # full-year metrics
    full_rows = [
        build_metrics(d_baseline, "baseline", "full_year"),
        build_metrics(d_c2, "c2_expand_daily_quotas", "full_year"),
    ]
    full_df = pd.DataFrame(full_rows)
    full_df.to_csv(OUT_FULL, index=False, encoding="utf-8-sig")

    # eval210 metrics
    keys = load_eval210_keys()
    d_baseline_210 = d_baseline.merge(keys, on=["ts_code", "trade_date"], how="inner")
    d_c2_210 = d_c2.merge(keys, on=["ts_code", "trade_date"], how="inner")

    eval_rows = [
        build_metrics(d_baseline_210, "baseline", "eval210"),
        build_metrics(d_c2_210, "c2_expand_daily_quotas", "eval210"),
    ]
    eval_df = pd.DataFrame(eval_rows)
    eval_df.to_csv(OUT_EVAL, index=False, encoding="utf-8-sig")

    # joined validation
    validation = pd.concat([full_df, eval_df], axis=0, ignore_index=True)
    validation.to_csv(OUT_VALIDATION, index=False, encoding="utf-8-sig")

    write_review_md(full_df, eval_df)

    summary = {
        "full_year": full_df.to_dict("records"),
        "eval210": eval_df.to_dict("records"),
        "decision": {
            "adopt_c2_as_recall_priority_version": True,
            "must_continue_fix_pathA_rank_and_eligibility": True,
            "continue_buy_signal_development": False,
        },
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(str(OUT_VALIDATION))
    print(str(OUT_FULL))
    print(str(OUT_EVAL))
    print(str(OUT_MD))


if __name__ == "__main__":
    main()

