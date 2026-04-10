from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(r"D:\HuaweiAI\quantSystem2")
BASE = ROOT / "data/research/strong_start_full/v4_scan"
SNAPSHOT = BASE / "true_breakout_feature_snapshot_1y.parquet"

OUT_PATH_INTERNAL = BASE / "true_breakout_selector_v3_path_internal_review.csv"
OUT_MERGE_COMPARE = BASE / "true_breakout_selector_v3_merge_compare.csv"
OUT_SUBTYPE_REVIEW = BASE / "true_breakout_selector_v3_subtype_coverage_review.csv"
OUT_REVIEW = BASE / "true_breakout_selector_v3_effectiveness_review.md"
OUT_CONTROLLED_NOTE = BASE / "true_breakout_selector_v3_controlled_merge_note.md"

NEAR_START = "20251230"
NEAR_END = "20260330"


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


def _build_common_axes(df: pd.DataFrame) -> pd.DataFrame:
    x = df.copy()
    x["score_trend_axis_single"] = (
        0.90 * _rank01(x["f_strength_rs20_xsec_q"], True).clip(upper=0.90)
        + 0.10
        * pd.concat(
            [
                _rank01(x["f_strength_ret20"], True),
                _rank01(x["f_strength_rs60_xsec_q"], True),
                _rank01(x["f_trend_close_ma20_gap"], True),
                _rank01(x["f_trend_ma20_ma60_gap"], True),
                _rank01(x["f_trend_ma20_slope5"], True),
            ],
            axis=1,
        ).mean(axis=1)
    )
    x["score_platform_axis_single"] = 0.70 * _rank01(x["f_platform_compress_ratio"], False) + 0.30 * _rank01(
        x["f_platform_range30"], False
    )
    x["score_chip_axis_single"] = (
        0.45 * _rank01(x["f_chip_winner_rate"], True)
        + 0.35 * _rank01(x["f_chip_low_position120"], True)
        + 0.20 * _rank01(x["f_chip_stability_std10"], True)
    )
    x["score_industry_axis_single"] = 0.75 * _rank01(x["f_ind_peer_strong_count"], True) + 0.25 * _rank01(
        x["f_ind_strength_5d"], True
    )
    return x


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


def _build_models(df: pd.DataFrame) -> pd.DataFrame:
    x = df.copy()

    # S0 single_v22
    pass_single = pd.to_numeric(x["f_strength_rs20_xsec_q"], errors="coerce") >= 0.72
    rank_single = _rank_within_day(pass_single, 0.50 * x["score_trend_axis_single"] + 0.10 * x["score_platform_axis_single"] + 0.25 * x["score_chip_axis_single"] + 0.15 * x["score_industry_axis_single"], x["trade_date"])
    x["selected_single_v22"] = pass_single & (rank_single <= 0.30)

    # S1 path_a_full
    pass_a = (
        (pd.to_numeric(x["f_strength_rs20_xsec_q"], errors="coerce") >= 0.72)
        & (pd.to_numeric(x["f_trend_close_ma20_gap"], errors="coerce") >= 0.02)
    )
    a_trend = _rank01(x["f_strength_rs20_xsec_q"], True).clip(upper=0.90)
    a_ind = _rank01(x["f_ind_peer_strong_count"], True)
    a_chip = _rank01(x["f_chip_winner_rate"], True)
    score_a = 0.65 * a_trend + 0.20 * a_ind + 0.15 * a_chip
    heat_resonance = (a_trend >= 0.90) & (a_ind >= 0.90)
    score_a = score_a.copy()
    score_a.loc[heat_resonance] = np.minimum(score_a.loc[heat_resonance], 0.85) - 0.08
    rank_a = _rank_within_day(pass_a, score_a, x["trade_date"])
    x["selected_path_a"] = pass_a & (rank_a <= 0.25)
    x["rank_a"] = rank_a

    # S2 path_b_full
    pass_b = (
        (pd.to_numeric(x["f_strength_rs20_xsec_q"], errors="coerce") >= 0.60)
        & (pd.to_numeric(x["f_trend_close_ma20_gap"], errors="coerce") >= 0.00)
    )
    score_b = 0.50 * x["score_platform_axis_single"] + 0.40 * (
        0.60 * _rank01(x["f_chip_winner_rate"], True) + 0.40 * _rank01(x["f_chip_low_position120"], True)
    ) + 0.10 * _rank01(x["f_strength_rs20_xsec_q"], True)
    rank_b = _rank_within_day(pass_b, score_b, x["trade_date"])
    x["selected_path_b"] = pass_b & (rank_b <= 0.25)
    x["rank_b"] = rank_b

    # S3 naive merge
    x["selected_dual_naive"] = x["selected_path_a"] | x["selected_path_b"]

    # S4 controlled merge (chosen: each path front 15%, then union)
    x["selected_dual_controlled"] = (pass_a & (rank_a <= 0.15)) | (pass_b & (rank_b <= 0.15))

    return x


def _a_share(mask: pd.Series, label: pd.Series) -> float:
    sub = label[mask]
    return float((sub == "A").mean()) if len(sub) else np.nan


def _path_internal(df: pd.DataFrame, path_name: str, pass_mask: pd.Series, rank_col: str) -> list[dict]:
    rows = []
    for p, b in [(0.10, "top10"), (0.20, "top20"), (0.30, "top30")]:
        m = pass_mask & (df[rank_col] <= p)
        n = int(m.sum())
        a_n = int(((df["label_true_breakout"] == "A") & m).sum())
        c_n = int(((df["label_true_breakout"] == "C") & m).sum())
        rows.append(
            {
                "path": path_name,
                "bucket": b,
                "sample_n": n,
                "a_n": a_n,
                "c_n": c_n,
                "a_share": (a_n / n) if n else np.nan,
            }
        )
    return rows


def _model_summary(df: pd.DataFrame, model: str, col: str, full_a_share: float) -> dict:
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
        "a_share_lift_vs_full_pts": (a_share - full_a_share) if pd.notna(a_share) else np.nan,
    }


def main() -> None:
    snap = pd.read_parquet(SNAPSHOT)
    snap["trade_date"] = snap["trade_date"].astype(str)
    near = snap[
        (snap["trade_date"] >= NEAR_START)
        & (snap["trade_date"] <= NEAR_END)
        & (snap["label_true_breakout"].isin(["A", "C"]))
    ].copy()
    near = _build_common_axes(near)
    near = _build_subtypes_and_modes(near)
    near = _build_models(near)

    full_a_share = float((near["label_true_breakout"] == "A").mean())

    # Task 3: path internal review
    pass_a = (
        (pd.to_numeric(near["f_strength_rs20_xsec_q"], errors="coerce") >= 0.72)
        & (pd.to_numeric(near["f_trend_close_ma20_gap"], errors="coerce") >= 0.02)
    )
    pass_b = (
        (pd.to_numeric(near["f_strength_rs20_xsec_q"], errors="coerce") >= 0.60)
        & (pd.to_numeric(near["f_trend_close_ma20_gap"], errors="coerce") >= 0.00)
    )
    internal_rows = _path_internal(near, "path_a_full", pass_a, "rank_a") + _path_internal(near, "path_b_full", pass_b, "rank_b")
    internal_df = pd.DataFrame(internal_rows)
    internal_df.to_csv(OUT_PATH_INTERNAL, index=False, encoding="utf-8-sig")

    # Task 4: merge compare
    merge_rows = [
        _model_summary(near, "S0_single_v22", "selected_single_v22", full_a_share),
        _model_summary(near, "S1_path_a_full", "selected_path_a", full_a_share),
        _model_summary(near, "S2_path_b_full", "selected_path_b", full_a_share),
        _model_summary(near, "S3_dual_merge_naive", "selected_dual_naive", full_a_share),
        _model_summary(near, "S4_dual_merge_controlled", "selected_dual_controlled", full_a_share),
    ]
    merge_df = pd.DataFrame(merge_rows)
    s0_share = float(merge_df.loc[merge_df["model"] == "S0_single_v22", "a_share"].iloc[0])
    merge_df["a_share_lift_vs_S0_pts"] = merge_df["a_share"] - s0_share
    merge_df.to_csv(OUT_MERGE_COMPARE, index=False, encoding="utf-8-sig")

    # Task 5: subtype coverage review
    rows = []
    for model, col in [
        ("S0_single_v22", "selected_single_v22"),
        ("S1_path_a_full", "selected_path_a"),
        ("S2_path_b_full", "selected_path_b"),
        ("S3_dual_merge_naive", "selected_dual_naive"),
        ("S4_dual_merge_controlled", "selected_dual_controlled"),
    ]:
        for subtype in ["high_momentum_frontline_A", "steady_structure_A", "chip_support_A", "mixed_A"]:
            m = (near["label_true_breakout"] == "A") & (near["a_subtype"] == subtype)
            total = int(m.sum())
            sel = int((m & near[col]).sum())
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
            m = (near["label_true_breakout"] == "C") & (near["c_failure_mode"] == mode)
            total = int(m.sum())
            sel = int((m & near[col]).sum())
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
    subtype_df.to_csv(OUT_SUBTYPE_REVIEW, index=False, encoding="utf-8-sig")

    # controlled merge note
    note_lines = [
        "# true_breakout_selector_v3_controlled_merge_note",
        "",
        "Selected controlled merge scheme: Scheme C (path-internal front-segment union).",
        "- Path A keep: rank_a <= 0.15",
        "- Path B keep: rank_b <= 0.15",
        "- Merge: selected = A_front OR B_front",
        "Reason: simple, interpretable, reduces naive full-union C amplification without introducing complex model.",
    ]
    OUT_CONTROLLED_NOTE.write_text("\n".join(note_lines), encoding="utf-8")

    # effectiveness review markdown
    p = internal_df.pivot(index="path", columns="bucket", values="a_share")
    lines = []
    lines.append("# true_breakout_selector_v3_effectiveness_review")
    lines.append("")
    lines.append(f"- near window: {NEAR_START} ~ {NEAR_END}")
    lines.append(f"- full-sample A share baseline: {full_a_share:.4f}")
    lines.append("")
    lines.append("## Path internal A-share")
    lines.append(p.to_string())
    lines.append("")
    lines.append("## Merge compare")
    lines.append(merge_df.to_string(index=False))
    lines.append("")
    # quick structured judgements
    pa_top10 = float(internal_df[(internal_df["path"] == "path_a_full") & (internal_df["bucket"] == "top10")]["a_share"].iloc[0])
    pa_top30 = float(internal_df[(internal_df["path"] == "path_a_full") & (internal_df["bucket"] == "top30")]["a_share"].iloc[0])
    pb_top10 = float(internal_df[(internal_df["path"] == "path_b_full") & (internal_df["bucket"] == "top10")]["a_share"].iloc[0])
    pb_top30 = float(internal_df[(internal_df["path"] == "path_b_full") & (internal_df["bucket"] == "top30")]["a_share"].iloc[0])
    s3 = merge_df[merge_df["model"] == "S3_dual_merge_naive"].iloc[0]
    s4 = merge_df[merge_df["model"] == "S4_dual_merge_controlled"].iloc[0]
    lines.append("## Judgement")
    lines.append(f"- Path A internal ranking effective: {'yes' if pa_top10 > pa_top30 else 'no'}")
    lines.append(f"- Path B internal ranking effective: {'yes' if pb_top10 > pb_top30 else 'no'}")
    lines.append(f"- Controlled merge better than naive: {'yes' if s4['a_share'] > s3['a_share'] else 'no'}")
    lines.append(f"- Controlled merge above full-sample baseline: {'yes' if s4['a_share'] > full_a_share else 'no'}")
    lines.append(f"- Controlled merge above S0: {'yes' if s4['a_share'] > s0_share else 'no'}")
    lines.append("")
    lines.append("Note: selector-only validation; no entry/exit/execution/backtest returns.")
    OUT_REVIEW.write_text("\n".join(lines), encoding="utf-8")

    print("Generated:")
    print(" -", OUT_PATH_INTERNAL)
    print(" -", OUT_MERGE_COMPARE)
    print(" -", OUT_SUBTYPE_REVIEW)
    print(" -", OUT_REVIEW)
    print(" -", OUT_CONTROLLED_NOTE)


if __name__ == "__main__":
    main()

