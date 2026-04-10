from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(r"D:\HuaweiAI\quantSystem2")
BASE = ROOT / "data/research/strong_start_full/v4_scan"
SNAPSHOT = BASE / "true_breakout_feature_snapshot_1y.parquet"

OUT_COMPARE = BASE / "true_breakout_selector_v3_path_selection_compare.csv"
OUT_SUMMARY = BASE / "true_breakout_selector_v3_path_selection_summary.json"
OUT_REVIEW = BASE / "true_breakout_selector_v3_path_selection_review.md"
OUT_PATH_INTERNAL = BASE / "true_breakout_selector_v3_path_internal_review.csv"
OUT_SUBTYPE_REVIEW = BASE / "true_breakout_selector_v3_subtype_coverage_review.csv"

NEAR_START = "20251230"
NEAR_END = "20260330"
BASELINE_A_SHARE = 0.3539


def _rank01(s: pd.Series, higher: bool = True) -> pd.Series:
    x = pd.to_numeric(s, errors="coerce")
    if not higher:
        x = -x
    return x.rank(method="average", pct=True)


def _rank_within_day(mask: pd.Series, score: pd.Series, trade_date: pd.Series) -> pd.Series:
    out = pd.Series(np.nan, index=score.index)
    for _, g in score[mask].groupby(trade_date[mask]):
        out.loc[g.index] = g.rank(method="first", ascending=False, pct=True)
    return out


def _model_summary(df: pd.DataFrame, model: str, col: str, baseline: float) -> dict:
    m = df[col]
    n = int(m.sum())
    a_n = int(((df["label_true_breakout"] == "A") & m).sum())
    c_n = int(((df["label_true_breakout"] == "C") & m).sum())
    a_share = (a_n / n) if n else np.nan
    return {
        "model": model,
        "sample_n": n,
        "a_n": a_n,
        "c_n": c_n,
        "a_share": a_share,
        "a_share_lift_vs_baseline_pts": (a_share - baseline) if pd.notna(a_share) else np.nan,
    }


def _monthly_a_share(df: pd.DataFrame, col: str) -> pd.DataFrame:
    x = df.copy()
    x["month"] = x["trade_date"].str.slice(0, 6)
    rows = []
    for m, g in x.groupby("month"):
        sel = g[g[col]]
        n = len(sel)
        a_n = int((sel["label_true_breakout"] == "A").sum())
        rows.append(
            {
                "month": m,
                "sample_n": n,
                "a_share": (a_n / n) if n else np.nan,
            }
        )
    return pd.DataFrame(rows).sort_values("month")


def _build_subtypes_and_modes(df: pd.DataFrame) -> pd.DataFrame:
    x = df.copy()

    a = x[x["label_true_breakout"] == "A"].copy()
    if not a.empty:
        t66 = a["score_trend_axis_single"].quantile(0.66)
        t33 = a["score_trend_axis_single"].quantile(0.33)
        i60 = a["score_industry_axis_single"].quantile(0.60)
        p66 = a["score_platform_axis_single"].quantile(0.66)
        c60 = a["score_chip_axis_single"].quantile(0.60)
        c66 = a["score_chip_axis_single"].quantile(0.66)

        x["a_subtype"] = np.nan
        x.loc[(x["label_true_breakout"] == "A"), "a_subtype"] = "mixed_A"
        x.loc[
            (x["label_true_breakout"] == "A")
            & (x["score_trend_axis_single"] >= t66)
            & (x["score_industry_axis_single"] >= i60),
            "a_subtype",
        ] = "high_momentum_frontline_A"
        x.loc[
            (x["a_subtype"] == "mixed_A")
            & (x["score_platform_axis_single"] >= p66)
            & (x["score_chip_axis_single"] >= c60)
            & (x["score_trend_axis_single"] < t66),
            "a_subtype",
        ] = "steady_structure_A"
        x.loc[
            (x["a_subtype"] == "mixed_A")
            & (x["score_chip_axis_single"] >= c66)
            & (x["score_trend_axis_single"] >= t33)
            & (x["score_trend_axis_single"] < t66),
            "a_subtype",
        ] = "chip_support_A"

    c = x[x["label_true_breakout"] == "C"].copy()
    if not c.empty:
        t66 = c["score_trend_axis_single"].quantile(0.66)
        i66 = c["score_industry_axis_single"].quantile(0.66)
        p33 = c["score_platform_axis_single"].quantile(0.33)
        chip33 = c["score_chip_axis_single"].quantile(0.33)

        x["c_failure_mode"] = np.nan
        x.loc[(x["label_true_breakout"] == "C"), "c_failure_mode"] = "mixed_pseudo_C"
        x.loc[
            (x["label_true_breakout"] == "C")
            & (x["score_industry_axis_single"] >= i66)
            & (x["score_trend_axis_single"] >= t66),
            "c_failure_mode",
        ] = "industry_heat_C"
        x.loc[
            (x["c_failure_mode"] == "mixed_pseudo_C")
            & (pd.to_numeric(x["f_strength_ret20"], errors="coerce") >= pd.to_numeric(c["f_strength_ret20"], errors="coerce").quantile(0.66))
            & (x["score_chip_axis_single"] <= chip33),
            "c_failure_mode",
        ] = "trend_chase_C"
        x.loc[
            (x["c_failure_mode"] == "mixed_pseudo_C")
            & (x["score_platform_axis_single"] <= p33)
            & (x["score_trend_axis_single"] >= c["score_trend_axis_single"].median()),
            "c_failure_mode",
        ] = "platform_false_break_C"
        x.loc[
            (x["c_failure_mode"] == "mixed_pseudo_C")
            & (pd.to_numeric(x["f_chip_stability_std10"], errors="coerce") <= pd.to_numeric(c["f_chip_stability_std10"], errors="coerce").quantile(0.25))
            & (x["score_trend_axis_single"] >= c["score_trend_axis_single"].median()),
            "c_failure_mode",
        ] = "chip_distortion_C"

    return x


def main() -> None:
    snap = pd.read_parquet(SNAPSHOT)
    snap["trade_date"] = snap["trade_date"].astype(str)
    df = snap[
        (snap["trade_date"] >= NEAR_START)
        & (snap["trade_date"] <= NEAR_END)
        & (snap["label_true_breakout"].isin(["A", "C"]))
    ].copy()

    # Shared single-path style axes
    score_trend_axis = (
        0.90 * _rank01(df["f_strength_rs20_xsec_q"], True).clip(upper=0.90)
        + 0.10
        * pd.concat(
            [
                _rank01(df["f_strength_ret20"], True),
                _rank01(df["f_strength_rs60_xsec_q"], True),
                _rank01(df["f_trend_close_ma20_gap"], True),
                _rank01(df["f_trend_ma20_ma60_gap"], True),
                _rank01(df["f_trend_ma20_slope5"], True),
            ],
            axis=1,
        ).mean(axis=1)
    )
    score_platform_axis = 0.70 * _rank01(df["f_platform_compress_ratio"], False) + 0.30 * _rank01(df["f_platform_range30"], False)
    score_chip_axis = (
        0.45 * _rank01(df["f_chip_winner_rate"], True)
        + 0.35 * _rank01(df["f_chip_low_position120"], True)
        + 0.20 * _rank01(df["f_chip_stability_std10"], True)
    )
    score_industry_axis = 0.75 * _rank01(df["f_ind_peer_strong_count"], True) + 0.25 * _rank01(df["f_ind_strength_5d"], True)

    # expose shared axes for subtype/failure-mode analysis
    df["score_trend_axis_single"] = score_trend_axis
    df["score_platform_axis_single"] = score_platform_axis
    df["score_chip_axis_single"] = score_chip_axis
    df["score_industry_axis_single"] = score_industry_axis

    # S0 single_v22
    pass_single = pd.to_numeric(df["f_strength_rs20_xsec_q"], errors="coerce") >= 0.72
    score_single = 0.50 * score_trend_axis + 0.10 * score_platform_axis + 0.25 * score_chip_axis + 0.15 * score_industry_axis
    rank_single = _rank_within_day(pass_single, score_single, df["trade_date"])
    df["S0_single_v22"] = pass_single & (rank_single <= 0.30)

    # Path A/B
    pass_a = (
        (pd.to_numeric(df["f_strength_rs20_xsec_q"], errors="coerce") >= 0.72)
        & (pd.to_numeric(df["f_trend_close_ma20_gap"], errors="coerce") >= 0.02)
    )
    a_trend = _rank01(df["f_strength_rs20_xsec_q"], True).clip(upper=0.90)
    a_ind = _rank01(df["f_ind_peer_strong_count"], True)
    a_chip = _rank01(df["f_chip_winner_rate"], True)
    score_a = 0.65 * a_trend + 0.20 * a_ind + 0.15 * a_chip
    heat_res = (a_trend >= 0.90) & (a_ind >= 0.90)
    score_a = score_a.copy()
    score_a.loc[heat_res] = np.minimum(score_a.loc[heat_res], 0.85) - 0.08
    rank_a = _rank_within_day(pass_a, score_a, df["trade_date"])
    df["S1_path_a_full"] = pass_a & (rank_a <= 0.25)
    df["path_a_controlled"] = pass_a & (rank_a <= 0.15)

    pass_b = (
        (pd.to_numeric(df["f_strength_rs20_xsec_q"], errors="coerce") >= 0.60)
        & (pd.to_numeric(df["f_trend_close_ma20_gap"], errors="coerce") >= 0.00)
    )
    score_b = 0.50 * score_platform_axis + 0.40 * (
        0.60 * _rank01(df["f_chip_winner_rate"], True) + 0.40 * _rank01(df["f_chip_low_position120"], True)
    ) + 0.10 * _rank01(df["f_strength_rs20_xsec_q"], True)
    rank_b = _rank_within_day(pass_b, score_b, df["trade_date"])
    df["S2_path_b_full"] = pass_b & (rank_b <= 0.25)
    df["path_b_controlled"] = pass_b & (rank_b <= 0.15)

    # S3 / S4
    df["S3_dual_merge_naive"] = df["S1_path_a_full"] | df["S2_path_b_full"]
    df["S4_dual_merge_controlled"] = df["path_a_controlled"] | df["path_b_controlled"]

    # S5 path selection: per day choose higher path-level score (top3 mean); then use controlled candidates from chosen path.
    df["S5_path_selection"] = False
    daily_choice_rows = []
    for d, g in df.groupby("trade_date"):
        ga = g[pass_a.loc[g.index]]
        gb = g[pass_b.loc[g.index]]

        a_day_score = np.nan
        b_day_score = np.nan
        if len(ga):
            a_day_score = ga.assign(_s=score_a.loc[ga.index]).nlargest(3, "_s")["_s"].mean()
        if len(gb):
            b_day_score = gb.assign(_s=score_b.loc[gb.index]).nlargest(3, "_s")["_s"].mean()

        if pd.isna(a_day_score) and pd.isna(b_day_score):
            chosen = "none"
        elif pd.isna(b_day_score):
            chosen = "A"
        elif pd.isna(a_day_score):
            chosen = "B"
        else:
            chosen = "A" if a_day_score > b_day_score else "B"

        if chosen == "A":
            idx = g.index[df.loc[g.index, "path_a_controlled"]]
            df.loc[idx, "S5_path_selection"] = True
        elif chosen == "B":
            idx = g.index[df.loc[g.index, "path_b_controlled"]]
            df.loc[idx, "S5_path_selection"] = True

        daily_choice_rows.append(
            {
                "trade_date": d,
                "path_a_day_score": a_day_score,
                "path_b_day_score": b_day_score,
                "chosen_path": chosen,
                "a_selected_n": int(df.loc[g.index, "path_a_controlled"].sum()),
                "b_selected_n": int(df.loc[g.index, "path_b_controlled"].sum()),
            }
        )

    # compare table
    models = ["S0_single_v22", "S1_path_a_full", "S2_path_b_full", "S3_dual_merge_naive", "S4_dual_merge_controlled", "S5_path_selection"]
    compare = pd.DataFrame([_model_summary(df, m, m, BASELINE_A_SHARE) for m in models])
    compare["a_share_lift_vs_S0_pts"] = compare["a_share"] - float(compare.loc[compare["model"] == "S0_single_v22", "a_share"].iloc[0])

    # monthly stability for S3 vs S5 (+S0 ref)
    m_s0 = _monthly_a_share(df, "S0_single_v22").rename(columns={"sample_n": "sample_n_s0", "a_share": "a_share_s0"})
    m_s3 = _monthly_a_share(df, "S3_dual_merge_naive").rename(columns={"sample_n": "sample_n_s3", "a_share": "a_share_s3"})
    m_s5 = _monthly_a_share(df, "S5_path_selection").rename(columns={"sample_n": "sample_n_s5", "a_share": "a_share_s5"})
    monthly = m_s0.merge(m_s3, on="month", how="outer").merge(m_s5, on="month", how="outer").sort_values("month")
    monthly["stability_source"] = "monthly_a_share"

    # Path-internal + subtype review reuse
    path_internal = []
    for path, mask, rank_col in [
        ("path_a_full", pass_a, rank_a),
        ("path_b_full", pass_b, rank_b),
    ]:
        for p, b in [(0.10, "top10"), (0.20, "top20"), (0.30, "top30")]:
            m = mask & (rank_col <= p)
            n = int(m.sum())
            a_n = int(((df["label_true_breakout"] == "A") & m).sum())
            c_n = int(((df["label_true_breakout"] == "C") & m).sum())
            path_internal.append({"path": path, "bucket": b, "sample_n": n, "a_n": a_n, "c_n": c_n, "a_share": (a_n / n) if n else np.nan})
    path_internal_df = pd.DataFrame(path_internal)

    # subtype coverage (A/C mode) for S0,S1,S2,S3,S4,S5
    df = _build_subtypes_and_modes(df)
    rows = []
    for model, col in [
        ("S0_single_v22", "S0_single_v22"),
        ("S1_path_a_full", "S1_path_a_full"),
        ("S2_path_b_full", "S2_path_b_full"),
        ("S3_dual_merge_naive", "S3_dual_merge_naive"),
        ("S4_dual_merge_controlled", "S4_dual_merge_controlled"),
        ("S5_path_selection", "S5_path_selection"),
    ]:
        for subtype in ["high_momentum_frontline_A", "steady_structure_A", "chip_support_A", "mixed_A"]:
            m = (df["label_true_breakout"] == "A") & (df["a_subtype"] == subtype)
            total = int(m.sum())
            sel = int((m & df[col]).sum())
            rows.append(
                {
                    "model": model,
                    "group_type": "A_subtype",
                    "group_name": subtype,
                    "total_n": total,
                    "selected_n": sel,
                    "selected_rate": (sel / total) if total else np.nan,
                }
            )
        for mode in ["industry_heat_C", "trend_chase_C", "platform_false_break_C", "chip_distortion_C", "mixed_pseudo_C"]:
            m = (df["label_true_breakout"] == "C") & (df["c_failure_mode"] == mode)
            total = int(m.sum())
            sel = int((m & df[col]).sum())
            rows.append(
                {
                    "model": model,
                    "group_type": "C_mode",
                    "group_name": mode,
                    "total_n": total,
                    "selected_n": sel,
                    "selected_rate": (sel / total) if total else np.nan,
                }
            )
    subtype_df = pd.DataFrame(rows)

    # Save outputs
    compare.to_csv(OUT_COMPARE, index=False, encoding="utf-8-sig")

    subtype_df.to_csv(OUT_SUBTYPE_REVIEW, index=False, encoding="utf-8-sig")

    summary = {
        "window": {"start": NEAR_START, "end": NEAR_END},
        "baseline_a_share": BASELINE_A_SHARE,
        "models": compare.to_dict(orient="records"),
        "monthly_stability_std": {
            "S3_naive_std": float(monthly["a_share_s3"].std(skipna=True)),
            "S5_path_selection_std": float(monthly["a_share_s5"].std(skipna=True)),
        },
        "path_choice_days": pd.DataFrame(daily_choice_rows)["chosen_path"].value_counts(dropna=False).to_dict(),
    }
    OUT_SUMMARY.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    # review markdown
    s0 = compare[compare["model"] == "S0_single_v22"].iloc[0]
    s3 = compare[compare["model"] == "S3_dual_merge_naive"].iloc[0]
    s4 = compare[compare["model"] == "S4_dual_merge_controlled"].iloc[0]
    s5 = compare[compare["model"] == "S5_path_selection"].iloc[0]
    lines = []
    lines.append("# true_breakout_selector_v3_path_selection_review")
    lines.append("")
    lines.append(f"- near window: {NEAR_START} ~ {NEAR_END}")
    lines.append(f"- baseline A share: {BASELINE_A_SHARE:.4f}")
    lines.append("")
    lines.append("## Path internal")
    lines.append(path_internal_df.to_string(index=False))
    lines.append("")
    lines.append("## S0/S3/S4/S5 compare")
    lines.append(compare.to_string(index=False))
    lines.append("")
    lines.append("## Monthly A-share (S3 vs S5)")
    lines.append(monthly.to_string(index=False))
    lines.append("")
    lines.append("## Key answers")
    lines.append(f"- path_selection > naive? {'yes' if s5['a_share'] > s3['a_share'] else 'no'}")
    lines.append(f"- path_selection >= baseline? {'yes' if s5['a_share'] >= BASELINE_A_SHARE else 'no'}")
    lines.append(f"- path_selection reduces C vs naive? {'yes' if s5['c_n'] < s3['c_n'] else 'no'}")
    lines.append(f"- path_selection better than S0? {'yes' if s5['a_share'] > s0['a_share'] else 'no'}")
    lines.append(f"- path_selection better than S4? {'yes' if s5['a_share'] > s4['a_share'] else 'no'}")
    lines.append("")
    lines.append("Note: selector-only validation; no entry/exit/execution/backtest returns.")
    OUT_REVIEW.write_text("\n".join(lines), encoding="utf-8")

    print("Generated:")
    print(" -", OUT_COMPARE)
    print(" -", OUT_SUMMARY)
    print(" -", OUT_REVIEW)
    print(" -", OUT_PATH_INTERNAL)
    print(" -", OUT_SUBTYPE_REVIEW)

    # overwrite path internal output in requested file
    path_internal_df.to_csv(OUT_PATH_INTERNAL, index=False, encoding="utf-8-sig")


if __name__ == "__main__":
    main()
