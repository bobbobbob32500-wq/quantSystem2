from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(r"D:\HuaweiAI\quantSystem2")
BASE = ROOT / "data/research/strong_start_full/v4_scan"

IN_MAP = BASE / "true_breakout_mainline_current_mapping.csv"

OUT_COMPARE = BASE / "true_breakout_stage2_selector_round2_compare.csv"
OUT_BEST = BASE / "true_breakout_stage2_selector_round2_best.csv"
OUT_REVIEW = BASE / "true_breakout_stage2_selector_round2_review.md"
OUT_SUMMARY = BASE / "true_breakout_stage2_selector_round2_summary.json"

MAIN_FROM = "2025-12-30"
MAIN_TO = "2026-03-30"
CONFIRM_FROM = "2025-09-29"
CONFIRM_TO = "2025-12-29"


def _window_mask(df: pd.DataFrame, dfrom: str, dto: str) -> pd.Series:
    td = pd.to_datetime(df["trade_date"], errors="coerce")
    return (td >= pd.Timestamp(dfrom)) & (td <= pd.Timestamp(dto))


def _ret_stats(s: pd.Series) -> tuple[float, float, float]:
    x = pd.to_numeric(s, errors="coerce")
    if x.empty:
        return np.nan, np.nan, np.nan
    return float(x.mean()), float(x.median()), float((x > 0).mean())


def _metrics(selected_df: pd.DataFrame, denom_df: pd.DataFrame, scenario: str) -> dict:
    g = selected_df.copy()
    a_total = int((denom_df["label_class"] == "A").sum())
    ah_total = int((denom_df["label_A_high"] == 1).sum())
    a_sel = int((g["label_class"] == "A").sum())
    ah_sel = int((g["label_A_high"] == 1).sum())
    c_sel = int((g["label_class"] == "C").sum())
    low_sel = int((g["label_A_low"] == 1).sum())
    t2m, t2d, t2w = _ret_stats(g["ret_t2_close"])

    trade_days = int(denom_df["trade_date"].nunique()) if not denom_df.empty else 0
    signal_days = int(g["trade_date"].nunique()) if len(g) else 0
    return {
        "scenario": scenario,
        "selected_n": int(len(g)),
        "signal_days": signal_days,
        "avg_days_per_signal": float(trade_days / signal_days) if signal_days else np.nan,
        "A_recall_rate": float(a_sel / a_total) if a_total else np.nan,
        "A_high_recall_rate": float(ah_sel / ah_total) if ah_total else np.nan,
        "A_high_over_C": float(ah_sel / c_sel) if c_sel else np.nan,
        "A_low_plus_C_share": float((low_sel + c_sel) / len(g)) if len(g) else np.nan,
        "mean_ret_t2": t2m,
        "median_ret_t2": t2d,
        "win_t2": t2w,
    }


def _candidate_masks(best: pd.DataFrame) -> dict[str, pd.Series]:
    ind = pd.to_numeric(best["score_industry_axis_single"], errors="coerce")
    plat = pd.to_numeric(best["score_platform_axis_single"], errors="coerce")
    chip = pd.to_numeric(best["f_chip_winner_rate"], errors="coerce")
    score = pd.to_numeric(best["score_total"], errors="coerce")
    rs20 = pd.to_numeric(best["f_strength_rs20_xsec_q"], errors="coerce")

    q_ind_70 = float(ind.quantile(0.70))
    q_ind_60 = float(ind.quantile(0.60))
    q_ind_55 = float(ind.quantile(0.55))
    q_ind_50 = float(ind.quantile(0.50))
    q_ind_75 = float(ind.quantile(0.75))
    q_plat_75 = float(plat.quantile(0.75))
    q_chip_50 = float(chip.quantile(0.50))
    q_score_45 = float(score.quantile(0.45))
    q_rs20_30 = float(rs20.quantile(0.30))
    q_rs20_40 = float(rs20.quantile(0.40))

    return {
        "R2_base_daily_top1": pd.Series(True, index=best.index),
        "R2_ind_cap70": ind <= q_ind_70,
        "R2_ind_cap60": ind <= q_ind_60,
        "R2_ind_cap50": ind <= q_ind_50,
        "R2_ind60_chip50": (ind <= q_ind_60) & (chip >= q_chip_50),
        "R2_ind60_plat75": (ind <= q_ind_60) & (plat <= q_plat_75),
        "R2_ind55_score45": (ind <= q_ind_55) & (score >= q_score_45),
        "R2_ind55_rs20q30": (ind <= q_ind_55) & (rs20 >= q_rs20_30),
        "R2_ind60_rs20q30": (ind <= q_ind_60) & (rs20 >= q_rs20_30),
        "R2_ind75_rs20q30": (ind <= q_ind_75) & (rs20 >= q_rs20_30),
        "R2_ind60_rs20q40": (ind <= q_ind_60) & (rs20 >= q_rs20_40),
    }


def main() -> None:
    d_all = pd.read_csv(IN_MAP)
    d_all["trade_date"] = d_all["trade_date"].astype(str)
    main_col = "in_mainline_s2" if "in_mainline_s2" in d_all.columns else "in_mainline_current"
    d = d_all[d_all[main_col] == True].copy()

    # stage2 target: one stock per day baseline, then apply quality gates
    d["_score"] = pd.to_numeric(d["score_total"], errors="coerce")
    best = d.sort_values(["trade_date", "_score"], ascending=[True, False]).groupby("trade_date").head(1).copy()
    best = best.drop(columns=["_score"])

    masks = _candidate_masks(best)

    rows = []
    for name, mask in masks.items():
        g = best[mask.fillna(False)].copy()
        rows.append({"scope": "full_year", **_metrics(g, d_all, name)})

        mw = _window_mask(g, MAIN_FROM, MAIN_TO)
        mw_den = _window_mask(d_all, MAIN_FROM, MAIN_TO)
        rows.append({"scope": "main_window", **_metrics(g[mw], d_all[mw_den], name)})

        cw = _window_mask(g, CONFIRM_FROM, CONFIRM_TO)
        cw_den = _window_mask(d_all, CONFIRM_FROM, CONFIRM_TO)
        rows.append({"scope": "confirm_window", **_metrics(g[cw], d_all[cw_den], name)})

    cmp_df = pd.DataFrame(rows)
    cmp_df.to_csv(OUT_COMPARE, index=False, encoding="utf-8-sig")

    full = cmp_df[cmp_df["scope"] == "full_year"].copy()
    # hard frequency floor: at least one every 3 days
    full["frequency_ok"] = full["avg_days_per_signal"] <= 3.0
    # pace target band for the current sprint: around every 2~3 days
    full["pace_target_ok"] = (full["avg_days_per_signal"] >= 2.0) & (full["avg_days_per_signal"] <= 3.0)
    # utility: quality first while honoring recall and pace constraints
    full["utility"] = (
        1.4 * full["win_t2"].fillna(0)
        + 0.6 * full["A_high_over_C"].replace([np.inf, -np.inf], np.nan).fillna(0)
        - 0.6 * full["A_low_plus_C_share"].fillna(1)
        + 0.20 * full["mean_ret_t2"].fillna(0)
        + 0.30 * full["A_high_recall_rate"].fillna(0)
    )
    full.loc[full["frequency_ok"], "utility"] += 0.10
    full.loc[full["pace_target_ok"], "utility"] += 0.35
    best_row = full.sort_values(["utility", "win_t2"], ascending=[False, False]).iloc[0]
    best_name = str(best_row["scenario"])
    best_out = cmp_df[cmp_df["scenario"] == best_name].copy()
    best_out.to_csv(OUT_BEST, index=False, encoding="utf-8-sig")

    lines = [
        "# Stage2 Selector Round2 (Recall-first then quality gate)",
        "",
        "## Summary",
        "- Baseline uses mainline_current daily top1 as selected set.",
        "- Recall denominator is full-universe mapping (not selected subset).",
        "- This round only tests lightweight quality gates on top of daily top1.",
        f"- Best candidate: {best_name}",
        "",
    ]
    fr = cmp_df[(cmp_df["scope"] == "full_year") & (cmp_df["scenario"] == best_name)].iloc[0]
    lines.extend(
        [
            "## Best full-year metrics",
            f"- selected_n={int(fr['selected_n'])}, signal_days={int(fr['signal_days'])}, avg_days_per_signal={fr['avg_days_per_signal']:.2f}",
            f"- A_high_recall_rate={fr['A_high_recall_rate']:.2%}, A_high/C={fr['A_high_over_C']:.4f}, A_low+C={fr['A_low_plus_C_share']:.2%}",
            f"- mean_ret_t2={fr['mean_ret_t2']:.2%}, median_ret_t2={fr['median_ret_t2']:.2%}, win_t2={fr['win_t2']:.2%}",
            "",
            "## Decision",
            "- Keep selector optimization on this stage; buy-point strengthening should remain after selector crosses target line.",
        ]
    )
    OUT_REVIEW.write_text("\n".join(lines), encoding="utf-8")

    payload = {
        "best_candidate": best_name,
        "full_year_best": fr.to_dict(),
        "files": {
            "compare": str(OUT_COMPARE),
            "best": str(OUT_BEST),
            "review": str(OUT_REVIEW),
        },
    }
    OUT_SUMMARY.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print(str(OUT_COMPARE))
    print(str(OUT_BEST))
    print(str(OUT_REVIEW))
    print(str(OUT_SUMMARY))


if __name__ == "__main__":
    main()
