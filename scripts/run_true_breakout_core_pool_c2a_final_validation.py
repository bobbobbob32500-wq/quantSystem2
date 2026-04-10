from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from run_true_breakout_core_pool_recall_rebuild import CoreConfig, add_quality_labels, load_universe, run_selector_core


ROOT = Path(r"D:\HuaweiAI\quantSystem2")
BASE = ROOT / "data/research/strong_start_full/v4_scan"

OUT_VALIDATION = BASE / "true_breakout_core_pool_c2a_final_validation.csv"
OUT_FULL = BASE / "true_breakout_core_pool_c2a_full_year_review.csv"
OUT_WINDOW = BASE / "true_breakout_core_pool_c2a_window_review.csv"
OUT_MD = BASE / "true_breakout_core_pool_c2a_final_review.md"

MAIN_FROM = "2025-12-30"
MAIN_TO = "2026-03-30"
CONFIRM_FROM = "2025-09-29"
CONFIRM_TO = "2025-12-29"


def _ret_stats(s: pd.Series) -> tuple[float, float, float]:
    x = pd.to_numeric(s, errors="coerce")
    if x.empty:
        return np.nan, np.nan, np.nan
    return float(x.mean()), float(x.median()), float((x > 0).mean())


def _metrics(df: pd.DataFrame, scenario: str, scope: str) -> dict:
    sel = df[df["in_core_pool"] == 1].copy()
    a_total = int((df["label_class"] == "A").sum())
    ah_total = int((df["label_A_high"] == 1).sum())
    c_total = int((df["label_class"] == "C").sum())

    a_sel = int((sel["label_class"] == "A").sum())
    ah_sel = int((sel["label_A_high"] == 1).sum())
    c_sel = int((sel["label_class"] == "C").sum())
    low_sel = int((sel["label_A_low"] == 1).sum())

    m1, d1, w1 = _ret_stats(sel["ret_t1_close"])
    m2, d2, w2 = _ret_stats(sel["ret_t2_close"])
    m3, d3, w3 = _ret_stats(sel["ret_t3_close"])

    return {
        "scope": scope,
        "scenario": scenario,
        "selected_n": int(len(sel)),
        "A_recall_rate": float(a_sel / a_total) if a_total else np.nan,
        "A_high_recall_rate": float(ah_sel / ah_total) if ah_total else np.nan,
        "A_high_over_C": float(ah_sel / c_sel) if c_sel else np.nan,
        "A_low_plus_C_share": float((low_sel + c_sel) / len(sel)) if len(sel) else np.nan,
        "mean_ret_t1": m1,
        "median_ret_t1": d1,
        "win_t1": w1,
        "mean_ret_t2": m2,
        "median_ret_t2": d2,
        "win_t2": w2,
        "mean_ret_t3": m3,
        "median_ret_t3": d3,
        "win_t3": w3,
    }


def _window_slice(df: pd.DataFrame, dfrom: str, dto: str) -> pd.DataFrame:
    td = pd.to_datetime(df["trade_date"], errors="coerce")
    return df[(td >= pd.Timestamp(dfrom)) & (td <= pd.Timestamp(dto))].copy()


def write_review(full_df: pd.DataFrame, win_df: pd.DataFrame) -> None:
    c2 = full_df[full_df["scenario"] == "C2"].iloc[0]
    c2a = full_df[full_df["scenario"] == "C2A_rank_relax"].iloc[0]

    d_ah = float(c2a["A_high_recall_rate"] - c2["A_high_recall_rate"])
    d_a = float(c2a["A_recall_rate"] - c2["A_recall_rate"])
    d_ratio = float(c2a["A_high_over_C"] - c2["A_high_over_C"])
    d_lowc = float(c2a["A_low_plus_C_share"] - c2["A_low_plus_C_share"])
    d_win2 = float(c2a["win_t2"] - c2["win_t2"])

    main_c2 = win_df[(win_df["scope"] == "main_window") & (win_df["scenario"] == "C2")].iloc[0]
    main_c2a = win_df[(win_df["scope"] == "main_window") & (win_df["scenario"] == "C2A_rank_relax")].iloc[0]
    conf_c2 = win_df[(win_df["scope"] == "confirm_window") & (win_df["scenario"] == "C2")].iloc[0]
    conf_c2a = win_df[(win_df["scope"] == "confirm_window") & (win_df["scenario"] == "C2A_rank_relax")].iloc[0]

    # Replace decision rule: prioritize recall uplift with no directional break in win_t2 on both windows.
    win_dir_ok = (main_c2a["win_t2"] >= main_c2["win_t2"]) and (conf_c2a["win_t2"] >= conf_c2["win_t2"])
    adopt = bool((d_ah >= 0) and (d_a >= 0) and win_dir_ok)

    md = [
        "# C2A_rank_relax 第三阶段落地验证",
        "",
        "## 口径冻结",
        "- C2（当前主线）: Path A/B quota = 2/3, PathA cutoff=10%, PathB cutoff=20%",
        "- C2A_rank_relax（本轮候选）: 在 C2 基础上仅放宽 PathA cutoff=20%，其余逻辑不变",
        "",
        "## 结论摘要",
        f"- C2A 是否值得正式替代 C2: {'是' if adopt else '否'}",
        f"- 全年 A_high 召回率变化: {c2['A_high_recall_rate']:.2%} -> {c2a['A_high_recall_rate']:.2%} (Δ {d_ah:+.2%})",
        f"- 全年 A 召回率变化: {c2['A_recall_rate']:.2%} -> {c2a['A_recall_rate']:.2%} (Δ {d_a:+.2%})",
        f"- 全年 A_high/C 变化: {c2['A_high_over_C']:.4f} -> {c2a['A_high_over_C']:.4f} (Δ {d_ratio:+.4f})",
        f"- 全年 A_low+C 占比变化: {c2['A_low_plus_C_share']:.2%} -> {c2a['A_low_plus_C_share']:.2%} (Δ {d_lowc:+.2%})",
        f"- 全年 win_t2 变化: {c2['win_t2']:.2%} -> {c2a['win_t2']:.2%} (Δ {d_win2:+.2%})",
        "",
        "## 双窗口稳健性",
        f"- 主窗口 win_t2: {main_c2['win_t2']:.2%} -> {main_c2a['win_t2']:.2%}",
        f"- 确认窗口 win_t2: {conf_c2['win_t2']:.2%} -> {conf_c2a['win_t2']:.2%}",
        f"- 双窗方向一致性（win_t2 不反向）: {'通过' if win_dir_ok else '未通过'}",
        "",
        "## 推进判断",
        f"- {'建议正式替代 C2，进入下一轮召回主线修复。' if adopt else '暂不正式替代 C2，需继续验证。'}",
        "- 下一轮主修方向：PathA rank cutoff（继续细化）",
        "- 当前仍不应继续买点开发。",
    ]
    OUT_MD.write_text("\n".join(md), encoding="utf-8")


def main() -> None:
    base = load_universe()
    base = add_quality_labels(base)

    cfg_c2 = CoreConfig(
        name="C2",
        note="frozen stage1 recall version",
        quota_a=2,
        quota_b=3,
        cutoff_a=0.10,
        cutoff_b=0.20,
    )
    cfg_c2a = CoreConfig(
        name="C2A_rank_relax",
        note="C2 + relax PathA rank cutoff only",
        quota_a=2,
        quota_b=3,
        cutoff_a=0.20,
        cutoff_b=0.20,
    )

    d_c2 = run_selector_core(base, cfg_c2)
    d_c2a = run_selector_core(base, cfg_c2a)

    full_rows = [
        _metrics(d_c2, "C2", "full_year"),
        _metrics(d_c2a, "C2A_rank_relax", "full_year"),
    ]
    full_df = pd.DataFrame(full_rows)
    full_df.to_csv(OUT_FULL, index=False, encoding="utf-8-sig")

    win_rows = []
    for scope, dfrom, dto in [
        ("main_window", MAIN_FROM, MAIN_TO),
        ("confirm_window", CONFIRM_FROM, CONFIRM_TO),
    ]:
        win_rows.append(_metrics(_window_slice(d_c2, dfrom, dto), "C2", scope))
        win_rows.append(_metrics(_window_slice(d_c2a, dfrom, dto), "C2A_rank_relax", scope))
    win_df = pd.DataFrame(win_rows)
    win_df.to_csv(OUT_WINDOW, index=False, encoding="utf-8-sig")

    validation_df = pd.concat([full_df, win_df], ignore_index=True)
    validation_df.to_csv(OUT_VALIDATION, index=False, encoding="utf-8-sig")

    write_review(full_df, win_df)

    print(str(OUT_VALIDATION))
    print(str(OUT_FULL))
    print(str(OUT_WINDOW))
    print(str(OUT_MD))


if __name__ == "__main__":
    main()

