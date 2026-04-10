from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(r"D:\HuaweiAI\quantSystem2")
BASE = ROOT / "data/research/strong_start_full/v4_scan"

IN_MAP = BASE / "true_breakout_mainline_current_mapping.csv"

OUT_TAGGED = BASE / "true_breakout_stage2_mainline_with_quality_tag.csv"
OUT_METRICS = BASE / "true_breakout_stage2_quality_tag_metrics.csv"
OUT_REVIEW = BASE / "true_breakout_stage2_quality_tag_review.md"
OUT_SUMMARY = BASE / "true_breakout_stage2_quality_tag_summary.json"

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


def _group_metrics(selected_df: pd.DataFrame, denom_df: pd.DataFrame, scope: str, group: str) -> dict:
    g = selected_df.copy()
    a_total = int((denom_df["label_class"] == "A").sum())
    ah_total = int((denom_df["label_A_high"] == 1).sum())
    a_sel = int((g["label_class"] == "A").sum())
    ah_sel = int((g["label_A_high"] == 1).sum())
    c_sel = int((g["label_class"] == "C").sum())
    low_sel = int((g["label_A_low"] == 1).sum())
    t2m, t2d, t2w = _ret_stats(g["ret_t2_close"])
    t1m, t1d, t1w = _ret_stats(g["ret_t1_close"])
    t3m, t3d, t3w = _ret_stats(g["ret_t3_close"])

    trade_days = int(denom_df["trade_date"].nunique()) if not denom_df.empty else 0
    signal_days = int(g["trade_date"].nunique()) if len(g) else 0
    return {
        "scope": scope,
        "group": group,
        "selected_n": int(len(g)),
        "signal_days": signal_days,
        "avg_days_per_signal": float(trade_days / signal_days) if signal_days else np.nan,
        "A_recall_rate": float(a_sel / a_total) if a_total else np.nan,
        "A_high_recall_rate": float(ah_sel / ah_total) if ah_total else np.nan,
        "A_high_over_C": float(ah_sel / c_sel) if c_sel else np.nan,
        "A_low_plus_C_share": float((low_sel + c_sel) / len(g)) if len(g) else np.nan,
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


def main() -> None:
    d_all = pd.read_csv(IN_MAP)
    d_all["trade_date"] = d_all["trade_date"].astype(str)
    main_col = "in_mainline_s2" if "in_mainline_s2" in d_all.columns else "in_mainline_current"

    d = d_all[d_all[main_col] == True].copy()
    d["_score"] = pd.to_numeric(d["score_total"], errors="coerce")
    top1 = d.sort_values(["trade_date", "_score"], ascending=[True, False]).groupby("trade_date").head(1).copy()
    top1 = top1.drop(columns=["_score"])

    # quality-tag rule from round2 winner: R2_ind55_rs20q30
    ind = pd.to_numeric(top1["score_industry_axis_single"], errors="coerce")
    rs20 = pd.to_numeric(top1["f_strength_rs20_xsec_q"], errors="coerce")
    ind_q55 = float(ind.quantile(0.55))
    rs20_q30 = float(rs20.quantile(0.30))

    tag_mask = (ind <= ind_q55) & (rs20 >= rs20_q30)
    top1["quality_tag"] = tag_mask.fillna(False)
    top1["quality_tag_reason"] = np.where(top1["quality_tag"], "ind_le_q55_and_rs20_ge_q30", "baseline_only")
    top1["quality_tag_industry_cap"] = ind_q55
    top1["quality_tag_rs20_floor"] = rs20_q30

    # export tagged mainline output
    out_cols = [
        "trade_date",
        "stock_code",
        "stock_name",
        "ts_code",
        "path_source",
        "label_class",
        "label_A_high",
        "label_A_mid",
        "label_A_low",
        "label_C",
        "label_G",
        "score_total",
        "score_platform_axis_single",
        "score_industry_axis_single",
        "f_chip_winner_rate",
        "f_platform_compress_ratio",
        "f_strength_rs20_xsec_q",
        "rank_global_after_merge",
        "ret_t1_close",
        "ret_t2_close",
        "ret_t3_close",
        "quality_tag",
        "quality_tag_reason",
        "quality_tag_industry_cap",
        "quality_tag_rs20_floor",
    ]
    for c in out_cols:
        if c not in top1.columns:
            top1[c] = pd.NA
    top1[out_cols].to_csv(OUT_TAGGED, index=False, encoding="utf-8-sig")

    # metrics by group and scope
    rows = []
    scopes = [
        ("full_year", d_all, top1),
        ("main_window", d_all[_window_mask(d_all, MAIN_FROM, MAIN_TO)], top1[_window_mask(top1, MAIN_FROM, MAIN_TO)]),
        ("confirm_window", d_all[_window_mask(d_all, CONFIRM_FROM, CONFIRM_TO)], top1[_window_mask(top1, CONFIRM_FROM, CONFIRM_TO)]),
    ]
    for scope_name, denom, sel in scopes:
        rows.append(_group_metrics(sel, denom, scope_name, "mainline_top1_all"))
        rows.append(_group_metrics(sel[sel["quality_tag"] == True], denom, scope_name, "quality_tag_1"))
        rows.append(_group_metrics(sel[sel["quality_tag"] != True], denom, scope_name, "quality_tag_0"))
    met = pd.DataFrame(rows)
    met.to_csv(OUT_METRICS, index=False, encoding="utf-8-sig")

    fy_all = met[(met["scope"] == "full_year") & (met["group"] == "mainline_top1_all")].iloc[0]
    fy_tag = met[(met["scope"] == "full_year") & (met["group"] == "quality_tag_1")].iloc[0]
    fy_not = met[(met["scope"] == "full_year") & (met["group"] == "quality_tag_0")].iloc[0]

    lines = [
        "# Stage2 Mainline Quality Tag Layer",
        "",
        "## Rule",
        "- Baseline selection remains `mainline_top1` (no replacement).",
        "- `quality_tag = (score_industry_axis_single <= q55) AND (f_strength_rs20_xsec_q >= q30)`.",
        f"- q55(industry)={ind_q55:.6f}, q30(rs20)={rs20_q30:.6f}",
        "",
        "## Full-year quick check",
        f"- mainline_top1: n={int(fy_all['selected_n'])}, A_high/C={fy_all['A_high_over_C']:.4f}, win_t2={fy_all['win_t2']:.2%}, mean_t2={fy_all['mean_ret_t2']:.2%}",
        f"- quality_tag=1: n={int(fy_tag['selected_n'])}, A_high/C={fy_tag['A_high_over_C']:.4f}, win_t2={fy_tag['win_t2']:.2%}, mean_t2={fy_tag['mean_ret_t2']:.2%}",
        f"- quality_tag=0: n={int(fy_not['selected_n'])}, A_high/C={fy_not['A_high_over_C']:.4f}, win_t2={fy_not['win_t2']:.2%}, mean_t2={fy_not['mean_ret_t2']:.2%}",
        "",
        "## Decision",
        "- Keep baseline mainline unchanged; use quality_tag as enhancement layer for next-stage gating.",
    ]
    OUT_REVIEW.write_text("\n".join(lines), encoding="utf-8")

    payload = {
        "rule": {
            "quality_tag": "score_industry_axis_single <= q55 and f_strength_rs20_xsec_q >= q30",
            "industry_cap_q55": ind_q55,
            "rs20_floor_q30": rs20_q30,
        },
        "full_year": {
            "mainline_top1_all": fy_all.to_dict(),
            "quality_tag_1": fy_tag.to_dict(),
            "quality_tag_0": fy_not.to_dict(),
        },
        "files": {
            "tagged_output": str(OUT_TAGGED),
            "metrics": str(OUT_METRICS),
            "review": str(OUT_REVIEW),
        },
    }
    OUT_SUMMARY.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print(str(OUT_TAGGED))
    print(str(OUT_METRICS))
    print(str(OUT_REVIEW))
    print(str(OUT_SUMMARY))


if __name__ == "__main__":
    main()

