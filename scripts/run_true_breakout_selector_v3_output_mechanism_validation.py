from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(r"D:\HuaweiAI\quantSystem2")
BASE = ROOT / "data/research/strong_start_full/v4_scan"
SNAPSHOT = BASE / "true_breakout_feature_snapshot_1y.parquet"

OUT_COMPARE = BASE / "true_breakout_selector_v3_output_mechanism_compare.csv"
OUT_SUMMARY = BASE / "true_breakout_selector_v3_output_mechanism_summary.json"
OUT_REVIEW = BASE / "true_breakout_selector_v3_output_mechanism_review.md"
OUT_PATH_CONTRIB = BASE / "true_breakout_selector_v3_output_mechanism_path_contribution.csv"
OUT_C_CONTROL = BASE / "true_breakout_selector_v3_output_mechanism_c_failure_control.csv"

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
    for d in trade_date[mask].unique():
        idx = trade_date.index[(trade_date == d) & mask]
        out.loc[idx] = score.loc[idx].rank(method="first", ascending=False, pct=True)
    return out


def _build_c_failure_mode(df: pd.DataFrame) -> pd.Series:
    c = df[df["label_true_breakout"] == "C"].copy()
    out = pd.Series(np.nan, index=df.index, dtype=object)
    if c.empty:
        return out
    t66 = c["score_trend_axis_single"].quantile(0.66)
    i66 = c["score_industry_axis_single"].quantile(0.66)
    p33 = c["score_platform_axis_single"].quantile(0.33)
    chip33 = c["score_chip_axis_single"].quantile(0.33)

    out.loc[df["label_true_breakout"] == "C"] = "mixed_pseudo_C"
    out.loc[
        (df["label_true_breakout"] == "C")
        & (df["score_industry_axis_single"] >= i66)
        & (df["score_trend_axis_single"] >= t66)
    ] = "industry_heat_C"
    out.loc[
        (out == "mixed_pseudo_C")
        & (pd.to_numeric(df["f_strength_ret20"], errors="coerce") >= pd.to_numeric(c["f_strength_ret20"], errors="coerce").quantile(0.66))
        & (df["score_chip_axis_single"] <= chip33)
    ] = "trend_chase_C"
    out.loc[
        (out == "mixed_pseudo_C")
        & (df["score_platform_axis_single"] <= p33)
        & (df["score_trend_axis_single"] >= c["score_trend_axis_single"].median())
    ] = "platform_false_break_C"
    out.loc[
        (out == "mixed_pseudo_C")
        & (pd.to_numeric(df["f_chip_stability_std10"], errors="coerce") <= pd.to_numeric(c["f_chip_stability_std10"], errors="coerce").quantile(0.25))
        & (df["score_trend_axis_single"] >= c["score_trend_axis_single"].median())
    ] = "chip_distortion_C"
    return out


def _model_summary(df: pd.DataFrame, col: str, model: str) -> dict:
    sel = df[col]
    n = int(sel.sum())
    a_n = int(((df["label_true_breakout"] == "A") & sel).sum())
    c_n = int(((df["label_true_breakout"] == "C") & sel).sum())
    a_share = (a_n / n) if n else np.nan
    return {
        "model": model,
        "sample_n": n,
        "a_n": a_n,
        "c_n": c_n,
        "a_share": a_share,
        "a_share_lift_vs_baseline_pts": (a_share - BASELINE_A_SHARE) if pd.notna(a_share) else np.nan,
    }


def _path_contribution(df: pd.DataFrame, col: str, model: str) -> dict:
    sel = df[col]
    pa = df["path_a_full"]
    pb = df["path_b_full"]
    both = int((sel & pa & pb).sum())
    a_only = int((sel & pa & ~pb).sum())
    b_only = int((sel & pb & ~pa).sum())
    sel_n = int(sel.sum())
    return {
        "model": model,
        "selected_n": sel_n,
        "path_a_only_n": a_only,
        "path_b_only_n": b_only,
        "path_both_n": both,
        "path_a_any_share": ((a_only + both) / sel_n) if sel_n else np.nan,
        "path_b_any_share": ((b_only + both) / sel_n) if sel_n else np.nan,
    }


def _c_failure_control(df: pd.DataFrame, col: str, model: str) -> pd.DataFrame:
    rows = []
    c_all = df[df["label_true_breakout"] == "C"]
    c_sel = c_all[c_all[col]]
    for m in ["industry_heat_C", "trend_chase_C", "platform_false_break_C", "chip_distortion_C", "mixed_pseudo_C"]:
        total = int((c_all["c_failure_mode"] == m).sum())
        sel = int((c_sel["c_failure_mode"] == m).sum())
        rows.append(
            {
                "model": model,
                "c_mode": m,
                "total_c_n": total,
                "selected_c_n": sel,
                "selected_rate_in_mode": (sel / total) if total else np.nan,
            }
        )
    return pd.DataFrame(rows)


def main() -> None:
    df = pd.read_parquet(SNAPSHOT).copy()
    df["trade_date"] = df["trade_date"].astype(str)
    df = df[
        (df["trade_date"] >= NEAR_START)
        & (df["trade_date"] <= NEAR_END)
        & (df["label_true_breakout"].isin(["A", "C"]))
    ].copy()

    # shared axes
    df["score_trend_axis_single"] = (
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
    df["score_platform_axis_single"] = 0.70 * _rank01(df["f_platform_compress_ratio"], False) + 0.30 * _rank01(df["f_platform_range30"], False)
    df["score_chip_axis_single"] = (
        0.45 * _rank01(df["f_chip_winner_rate"], True)
        + 0.35 * _rank01(df["f_chip_low_position120"], True)
        + 0.20 * _rank01(df["f_chip_stability_std10"], True)
    )
    df["score_industry_axis_single"] = 0.75 * _rank01(df["f_ind_peer_strong_count"], True) + 0.25 * _rank01(df["f_ind_strength_5d"], True)

    # path A/B
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

    pass_b = (
        (pd.to_numeric(df["f_strength_rs20_xsec_q"], errors="coerce") >= 0.60)
        & (pd.to_numeric(df["f_trend_close_ma20_gap"], errors="coerce") >= 0.00)
    )
    score_b = 0.50 * df["score_platform_axis_single"] + 0.40 * (
        0.60 * _rank01(df["f_chip_winner_rate"], True) + 0.40 * _rank01(df["f_chip_low_position120"], True)
    ) + 0.10 * _rank01(df["f_strength_rs20_xsec_q"], True)
    rank_b = _rank_within_day(pass_b, score_b, df["trade_date"])

    df["path_a_full"] = pass_a & (rank_a <= 0.25)
    df["path_b_full"] = pass_b & (rank_b <= 0.25)
    df["path_a_ctrl"] = pass_a & (rank_a <= 0.15)
    df["path_b_ctrl"] = pass_b & (rank_b <= 0.15)
    df["rank_a"] = rank_a
    df["rank_b"] = rank_b
    df["score_a"] = score_a
    df["score_b"] = score_b

    # S0/S3/S4/S5
    pass_s0 = pd.to_numeric(df["f_strength_rs20_xsec_q"], errors="coerce") >= 0.72
    score_s0 = 0.50 * df["score_trend_axis_single"] + 0.10 * df["score_platform_axis_single"] + 0.25 * df["score_chip_axis_single"] + 0.15 * df["score_industry_axis_single"]
    rank_s0 = _rank_within_day(pass_s0, score_s0, df["trade_date"])
    df["S0_single_v22"] = pass_s0 & (rank_s0 <= 0.30)
    df["S3_dual_merge_naive"] = df["path_a_full"] | df["path_b_full"]
    df["S4_dual_merge_controlled"] = df["path_a_ctrl"] | df["path_b_ctrl"]

    # S5 winner-take-all (previous style)
    df["S5_path_selection"] = False
    for d, g in df.groupby("trade_date"):
        ga = g[pass_a.loc[g.index]]
        gb = g[pass_b.loc[g.index]]
        a_day = ga.nlargest(3, "score_a")["score_a"].mean() if len(ga) else np.nan
        b_day = gb.nlargest(3, "score_b")["score_b"].mean() if len(gb) else np.nan
        if pd.isna(a_day) and pd.isna(b_day):
            continue
        choose_a = (not pd.isna(a_day)) and (pd.isna(b_day) or a_day > b_day)
        if choose_a:
            idx = g.index[df.loc[g.index, "path_a_ctrl"]]
            df.loc[idx, "S5_path_selection"] = True
        else:
            idx = g.index[df.loc[g.index, "path_b_ctrl"]]
            df.loc[idx, "S5_path_selection"] = True

    # M1 quota merge: each day max A2 + B2 from controlled pools
    df["M1_quota_merge"] = False
    for d, g in df.groupby("trade_date"):
        idx_a = g.index[df.loc[g.index, "path_a_ctrl"]]
        idx_b = g.index[df.loc[g.index, "path_b_ctrl"]]
        pick_a = df.loc[idx_a].sort_values("rank_a", ascending=True).head(2).index
        pick_b = df.loc[idx_b].sort_values("rank_b", ascending=True).head(2).index
        df.loc[pick_a.union(pick_b), "M1_quota_merge"] = True

    # M2 primary + supplement: choose stronger path by day-score, plus 1 from the other
    df["M2_primary_supplement"] = False
    for d, g in df.groupby("trade_date"):
        ga = g[g["path_a_ctrl"]]
        gb = g[g["path_b_ctrl"]]
        a_day = ga.nlargest(3, "score_a")["score_a"].mean() if len(ga) else np.nan
        b_day = gb.nlargest(3, "score_b")["score_b"].mean() if len(gb) else np.nan
        if pd.isna(a_day) and pd.isna(b_day):
            continue
        if pd.isna(b_day) or (not pd.isna(a_day) and a_day > b_day):
            primary = ga
            supplement = gb
            primary_rank = "rank_a"
            supplement_rank = "rank_b"
        else:
            primary = gb
            supplement = ga
            primary_rank = "rank_b"
            supplement_rank = "rank_a"
        p_idx = primary.sort_values(primary_rank, ascending=True).head(2).index
        s_idx = supplement.sort_values(supplement_rank, ascending=True).head(1).index
        df.loc[p_idx.union(s_idx), "M2_primary_supplement"] = True

    # M3 rank-normalized merge: path front20% + normalized top4/day
    df["M3_rank_normalized_merge"] = False
    for d, g in df.groupby("trade_date"):
        cand_idx = g.index[(df.loc[g.index, "path_a_full"] & (df.loc[g.index, "rank_a"] <= 0.20)) | (df.loc[g.index, "path_b_full"] & (df.loc[g.index, "rank_b"] <= 0.20))]
        if len(cand_idx) == 0:
            continue
        gg = df.loc[cand_idx].copy()
        ra = pd.to_numeric(gg["rank_a"], errors="coerce")
        rb = pd.to_numeric(gg["rank_b"], errors="coerce")
        gg["norm_score"] = np.nanmax(np.vstack([1 - ra.fillna(-1).values, 1 - rb.fillna(-1).values]), axis=0)
        pick = gg.sort_values("norm_score", ascending=False).head(4).index
        df.loc[pick, "M3_rank_normalized_merge"] = True

    # failure modes
    df["c_failure_mode"] = _build_c_failure_mode(df)

    models = [
        "S0_single_v22",
        "S3_dual_merge_naive",
        "S4_dual_merge_controlled",
        "S5_path_selection",
        "M1_quota_merge",
        "M2_primary_supplement",
        "M3_rank_normalized_merge",
    ]
    compare = pd.DataFrame([_model_summary(df, m, m) for m in models])
    s0_share = float(compare.loc[compare["model"] == "S0_single_v22", "a_share"].iloc[0])
    s3_share = float(compare.loc[compare["model"] == "S3_dual_merge_naive", "a_share"].iloc[0])
    compare["a_share_lift_vs_S0_pts"] = compare["a_share"] - s0_share
    compare["a_share_lift_vs_S3_pts"] = compare["a_share"] - s3_share
    compare.to_csv(OUT_COMPARE, index=False, encoding="utf-8-sig")

    # path contribution + C control
    contrib_rows = []
    c_rows = []
    for m in models:
        contrib_rows.append(_path_contribution(df, m, m))
        c_rows.append(_c_failure_control(df, m, m))
    contrib = pd.DataFrame(contrib_rows)
    contrib.to_csv(OUT_PATH_CONTRIB, index=False, encoding="utf-8-sig")
    c_control = pd.concat(c_rows, ignore_index=True)
    c_control.to_csv(OUT_C_CONTROL, index=False, encoding="utf-8-sig")

    # monthly stability S3 vs new mechanisms
    def monthly_a(col: str) -> pd.DataFrame:
        x = df.copy()
        x["month"] = x["trade_date"].str.slice(0, 6)
        rows = []
        for mo, g in x.groupby("month"):
            sel = g[g[col]]
            n = len(sel)
            a_n = int((sel["label_true_breakout"] == "A").sum())
            rows.append({"month": mo, "model": col, "sample_n": n, "a_share": (a_n / n) if n else np.nan})
        return pd.DataFrame(rows)

    monthly = pd.concat([monthly_a("S3_dual_merge_naive"), monthly_a("M1_quota_merge"), monthly_a("M2_primary_supplement"), monthly_a("M3_rank_normalized_merge"), monthly_a("S5_path_selection")], ignore_index=True)

    summary = {
        "window": {"start": NEAR_START, "end": NEAR_END},
        "baseline_a_share": BASELINE_A_SHARE,
        "model_compare": compare.to_dict(orient="records"),
        "monthly_a_share_std": {m: float(monthly.loc[monthly["model"] == m, "a_share"].std(skipna=True)) for m in monthly["model"].unique()},
        "best_model_by_a_share": compare.sort_values("a_share", ascending=False).iloc[0]["model"],
    }
    OUT_SUMMARY.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    # review
    best = compare.sort_values("a_share", ascending=False).iloc[0]
    lines = []
    lines.append("# true_breakout_selector_v3_output_mechanism_review")
    lines.append("")
    lines.append("## Frozen facts")
    lines.append("1) Path A internal ranking effective")
    lines.append("2) Path B internal ranking effective")
    lines.append("3) Naive merge amplifies C")
    lines.append("4) Winner-take-all path selection suppresses Path B expression")
    lines.append("5) Core bottleneck is output mechanism, not factor list")
    lines.append("")
    lines.append(f"- near window: {NEAR_START} ~ {NEAR_END}")
    lines.append(f"- full-sample A baseline: {BASELINE_A_SHARE:.4f}")
    lines.append("")
    lines.append("## Model compare")
    lines.append(compare.to_string(index=False))
    lines.append("")
    lines.append("## Path contribution")
    lines.append(contrib.to_string(index=False))
    lines.append("")
    lines.append("## C failure-mode control")
    lines.append(c_control.to_string(index=False))
    lines.append("")
    lines.append("## Monthly stability (A share)")
    lines.append(monthly.to_string(index=False))
    lines.append("")
    lines.append("## Key judgement")
    lines.append(f"- best by A-share: {best['model']} ({best['a_share']:.4f})")
    lines.append(f"- above baseline? {'yes' if float(best['a_share']) > BASELINE_A_SHARE else 'no'}")
    lines.append("Note: selector-only structure validation; no buy/sell/exec/backtest return metrics.")
    OUT_REVIEW.write_text("\n".join(lines), encoding="utf-8")

    print("Generated:")
    print(" -", OUT_COMPARE)
    print(" -", OUT_SUMMARY)
    print(" -", OUT_REVIEW)
    print(" -", OUT_PATH_CONTRIB)
    print(" -", OUT_C_CONTROL)


if __name__ == "__main__":
    main()

