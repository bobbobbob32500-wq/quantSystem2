from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from run_true_breakout_core_pool_recall_rebuild import CoreConfig, add_quality_labels, load_universe, run_selector_core
from run_true_breakout_dual_channel_fast_review import assign_archetype
from run_ech2_scope_expansion_fast_review import build_ech2_mask, apply_q2_gate


BASE = Path(r"D:\HuaweiAI\quantSystem2\data\research\strong_start_full\v4_scan")

OUT_MAPPING = BASE / "true_breakout_mainline_s2_full_mapping.csv"
OUT_RECALL = BASE / "true_breakout_mainline_s2_recall_recheck.csv"
OUT_MISS = BASE / "true_breakout_mainline_s2_ahigh_miss_reason.csv"
OUT_REVIEW = BASE / "true_breakout_mainline_s2_finalize.md"

MAIN_FROM = "2025-12-30"
MAIN_TO = "2026-03-30"
CONFIRM_FROM = "2025-09-29"
CONFIRM_TO = "2025-12-29"


def _window_mask(df: pd.DataFrame, dfrom: str, dto: str) -> pd.Series:
    td = pd.to_datetime(df["trade_date"], errors="coerce")
    return (td >= pd.Timestamp(dfrom)) & (td <= pd.Timestamp(dto))


def _ret_t2_stats(sel: pd.DataFrame) -> tuple[float, float, float]:
    x = pd.to_numeric(sel["ret_t2_close"], errors="coerce")
    if x.empty:
        return np.nan, np.nan, np.nan
    return float(x.mean()), float(x.median()), float((x > 0).mean())


def scenario_metrics(df: pd.DataFrame, scope: str, scenario: str, mask: pd.Series) -> dict:
    g = df[mask].copy()
    a_total = int((df["label_class"] == "A").sum())
    ah_total = int((df["label_A_high"] == 1).sum())
    a_sel = int((g["label_class"] == "A").sum())
    ah_sel = int((g["label_A_high"] == 1).sum())
    c_sel = int((g["label_class"] == "C").sum())
    low_sel = int((g["label_A_low"] == 1).sum())
    t2m, t2d, t2w = _ret_t2_stats(g)

    return {
        "scope": scope,
        "scenario": scenario,
        "selected_n": int(len(g)),
        "A_recall_rate": float(a_sel / a_total) if a_total else np.nan,
        "A_high_recall_rate": float(ah_sel / ah_total) if ah_total else np.nan,
        "A_high_over_C": float(ah_sel / c_sel) if c_sel else np.nan,
        "A_low_plus_C_share": float((low_sel + c_sel) / len(g)) if len(g) else np.nan,
        "mean_ret_t2": t2m,
        "median_ret_t2": t2d,
        "win_t2": t2w,
    }


def miss_breakdown_for_current(df: pd.DataFrame) -> pd.DataFrame:
    ah = df[df["label_A_high"] == 1].copy()
    miss = ah[~ah["in_mainline_s2"]].copy()
    total_ah = len(ah)
    total_miss = len(miss)

    miss["reason"] = np.where(
        ~miss["path_a_eligible"].fillna(False),
        "not_in_path_A",
        np.where(~miss["in_ech2_s2_base"].fillna(False), "not_in_ECH2_scope", "not_in_ECH2_q2_gate"),
    )

    out = miss.groupby("reason", as_index=False).size().rename(columns={"size": "miss_count"})
    out["miss_share_in_remaining_A_high"] = out["miss_count"] / total_miss if total_miss else np.nan
    out["miss_share_in_total_A_high"] = out["miss_count"] / total_ah if total_ah else np.nan
    return out.sort_values("miss_count", ascending=False).reset_index(drop=True)


def write_review(recall_df: pd.DataFrame, miss_df: pd.DataFrame) -> None:
    full_q2 = recall_df[(recall_df["scope"] == "full_year") & (recall_df["scenario"] == "C2A+ECH2_Q2")].iloc[0]
    full_s2 = recall_df[(recall_df["scope"] == "full_year") & (recall_df["scenario"] == "C2A+ECH2_S2")].iloc[0]
    d_ah = float(full_s2["A_high_recall_rate"] - full_q2["A_high_recall_rate"])
    d_ratio = float(full_s2["A_high_over_C"] - full_q2["A_high_over_C"])
    d_win = float(full_s2["win_t2"] - full_q2["win_t2"])

    top_reason = miss_df.iloc[0]["reason"] if not miss_df.empty else "NA"

    lines = [
        "# 主线阶段收口（C2A+ECH2_S2）",
        "",
        "## 结论摘要",
        "- 本阶段按最短路径完成：ECH2 扩张验证后，S2 作为当前主线通道版本收口。",
        f"- 全年 A_high 召回（相对 Q2）: {full_q2['A_high_recall_rate']:.2%} -> {full_s2['A_high_recall_rate']:.2%} (Δ {d_ah:+.2%})",
        f"- A_high/C 变化: {full_q2['A_high_over_C']:.4f} -> {full_s2['A_high_over_C']:.4f} (Δ {d_ratio:+.4f})",
        f"- T+2 win 变化: {full_q2['win_t2']:.2%} -> {full_s2['win_t2']:.2%} (Δ {d_win:+.2%})",
        f"- 当前剩余最大漏抓源: {top_reason}",
        "- 当前阶段结论：继续召回主线，不恢复买点开发。",
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

    # quantile anchors
    plat_all = pd.to_numeric(d["score_platform_axis_single"], errors="coerce")
    comp_all = pd.to_numeric(d["f_platform_compress_ratio"], errors="coerce")
    chip_all = pd.to_numeric(d["f_chip_winner_rate"], errors="coerce")
    ind_all = pd.to_numeric(d["score_industry_axis_single"], errors="coerce")
    score_all = pd.to_numeric(d["score_total"], errors="coerce")
    q_ind_55 = float(ind_all.quantile(0.55))
    q_chip_50 = float(chip_all.quantile(0.50))
    q_score_60 = float(score_all.quantile(0.60))
    q_plat_65 = float(plat_all.quantile(0.65))
    q_comp_45 = float(comp_all.quantile(0.45))
    q_plat_55 = float(plat_all.quantile(0.55))
    q_comp_55 = float(comp_all.quantile(0.55))

    # Q2 (previous current)
    ech2_q2_base = build_ech2_mask(
        d,
        plat_floor=q_plat_65,
        comp_ceiling=q_comp_45,
        q_ind_55=q_ind_55,
        q_chip_50=q_chip_50,
        q_score_60=q_score_60,
    )
    in_ech2_q2 = apply_q2_gate(d, d["in_C2A"], ech2_q2_base)
    d["in_mainline_q2"] = d["in_C2A"] | in_ech2_q2

    # S2 (new current in this stage)
    ech2_s2_base = build_ech2_mask(
        d,
        plat_floor=q_plat_55,
        comp_ceiling=q_comp_55,
        q_ind_55=q_ind_55,
        q_chip_50=q_chip_50,
        q_score_60=q_score_60,
    )
    in_ech2_s2 = apply_q2_gate(d, d["in_C2A"], ech2_s2_base)
    d["in_ech2_s2_base"] = ech2_s2_base
    d["in_ech2_s2"] = in_ech2_s2
    d["in_mainline_s2"] = d["in_C2A"] | in_ech2_s2

    # archetype for context
    ah = d[d["label_A_high"] == 1].copy()
    ah["archetype"] = assign_archetype(ah)
    d = d.merge(ah[["ts_code", "trade_date", "archetype"]], on=["ts_code", "trade_date"], how="left")

    # mapping
    map_cols = [
        "trade_date",
        "stock_code",
        "stock_name",
        "label_class",
        "label_A_high",
        "path_source",
        "in_C2A",
        "in_mainline_q2",
        "in_ech2_s2",
        "in_mainline_s2",
        "archetype",
        "score_total",
        "score_platform_axis_single",
        "score_industry_axis_single",
        "f_chip_winner_rate",
        "f_platform_compress_ratio",
        "rank_global_after_merge",
        "ret_t2_close",
    ]
    d[map_cols].to_csv(OUT_MAPPING, index=False, encoding="utf-8-sig")

    # recall compare
    rows = []
    rows.append(scenario_metrics(d, "full_year", "C2A+ECH2_Q2", d["in_mainline_q2"]))
    rows.append(scenario_metrics(d, "full_year", "C2A+ECH2_S2", d["in_mainline_s2"]))
    for scope, mask in [
        ("main_window", _window_mask(d, MAIN_FROM, MAIN_TO)),
        ("confirm_window", _window_mask(d, CONFIRM_FROM, CONFIRM_TO)),
    ]:
        rows.append(scenario_metrics(d[mask], scope, "C2A+ECH2_Q2", d.loc[mask, "in_mainline_q2"]))
        rows.append(scenario_metrics(d[mask], scope, "C2A+ECH2_S2", d.loc[mask, "in_mainline_s2"]))
    recall_df = pd.DataFrame(rows)
    recall_df.to_csv(OUT_RECALL, index=False, encoding="utf-8-sig")

    miss_df = miss_breakdown_for_current(d)
    miss_df.to_csv(OUT_MISS, index=False, encoding="utf-8-sig")

    write_review(recall_df, miss_df)

    print(str(OUT_MAPPING))
    print(str(OUT_RECALL))
    print(str(OUT_MISS))
    print(str(OUT_REVIEW))


if __name__ == "__main__":
    main()

