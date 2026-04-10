from __future__ import annotations

from pathlib import Path
import sqlite3
import json

import numpy as np
import pandas as pd


ROOT = Path(r"D:\HuaweiAI\quantSystem2")
BASE = ROOT / "data/research/strong_start_full/v4_scan"
SNAPSHOT = BASE / "true_breakout_feature_snapshot_1y.parquet"
DB_PATH = ROOT / "data/database/quant_system.db"

OUT_LAYERS = BASE / "true_breakout_selected_quality_layers.csv"
OUT_A_SPLIT = BASE / "true_breakout_selectedA_quality_split.csv"
OUT_C_FAIL = BASE / "true_breakout_selectedC_failure_reasons.csv"
OUT_G_OBS = BASE / "true_breakout_selectedG_observation_reasons.csv"
OUT_DIFF = BASE / "true_breakout_Ahigh_vs_CG_diff.csv"
OUT_REPORT = BASE / "true_breakout_selected_quality_diagnosis.md"

WINDOW_START = "20251230"
WINDOW_END = "20260330"

# frozen candidate-2 params
QUOTA_A = 1
QUOTA_B = 2
CUTOFF_A = 0.10
CUTOFF_B = 0.20
HEAT_TREND_Q = 0.85
HEAT_IND_Q = 0.85
HEAT_SCORE_CAP = 0.80
HEAT_PENALTY = 0.12


def rank01(s: pd.Series, higher: bool = True) -> pd.Series:
    x = pd.to_numeric(s, errors="coerce")
    if not higher:
        x = -x
    return x.rank(method="average", pct=True)


def rank_within_day(mask: pd.Series, score: pd.Series, trade_date: pd.Series) -> pd.Series:
    out = pd.Series(np.nan, index=score.index)
    for d in trade_date[mask].unique():
        idx = trade_date.index[(trade_date == d) & mask]
        out.loc[idx] = score.loc[idx].rank(method="first", ascending=False, pct=True)
    return out


def load_forward_daily() -> pd.DataFrame:
    conn = sqlite3.connect(DB_PATH)
    try:
        daily = pd.read_sql_query("select ts_code, trade_date, open, close from stock_daily", conn)
    finally:
        conn.close()
    daily["trade_date"] = daily["trade_date"].astype(str)
    for c in ["open", "close"]:
        daily[c] = pd.to_numeric(daily[c], errors="coerce")
    daily = daily.sort_values(["ts_code", "trade_date"]).reset_index(drop=True)
    daily["buy_date"] = daily.groupby("ts_code")["trade_date"].shift(-1)
    daily["buy_open_t1"] = daily.groupby("ts_code")["open"].shift(-1)
    daily["close_t1"] = daily.groupby("ts_code")["close"].shift(-1)
    daily["close_t2"] = daily.groupby("ts_code")["close"].shift(-2)
    daily["close_t3"] = daily.groupby("ts_code")["close"].shift(-3)
    return daily[["ts_code", "trade_date", "buy_date", "buy_open_t1", "close_t1", "close_t2", "close_t3"]]


def build_selected_v3(df: pd.DataFrame) -> pd.DataFrame:
    d = df.copy()
    d["trade_date"] = d["trade_date"].astype(str)
    d = d[(d["trade_date"] >= WINDOW_START) & (d["trade_date"] <= WINDOW_END)].copy()
    d = d[d["label_true_breakout"].isin(["A", "C", "G"])].copy()

    # shared single-axis scores for diagnosis
    d["score_trend_axis_single"] = (
        0.90 * rank01(d["f_strength_rs20_xsec_q"], True).clip(upper=0.90)
        + 0.10
        * pd.concat(
            [
                rank01(d["f_strength_ret20"], True),
                rank01(d["f_strength_rs60_xsec_q"], True),
                rank01(d["f_trend_close_ma20_gap"], True),
                rank01(d["f_trend_ma20_ma60_gap"], True),
                rank01(d["f_trend_ma20_slope5"], True),
            ],
            axis=1,
        ).mean(axis=1)
    )
    d["score_platform_axis_single"] = 0.70 * rank01(d["f_platform_compress_ratio"], False) + 0.30 * rank01(d["f_platform_range30"], False)
    d["score_chip_axis_single"] = (
        0.45 * rank01(d["f_chip_winner_rate"], True)
        + 0.35 * rank01(d["f_chip_low_position120"], True)
        + 0.20 * rank01(d["f_chip_stability_std10"], True)
    )
    d["score_industry_axis_single"] = 0.75 * rank01(d["f_ind_peer_strong_count"], True) + 0.25 * rank01(d["f_ind_strength_5d"], True)

    # Path A
    pass_a = (pd.to_numeric(d["f_strength_rs20_xsec_q"], errors="coerce") >= 0.72) & (
        pd.to_numeric(d["f_trend_close_ma20_gap"], errors="coerce") >= 0.02
    )
    a_trend = rank01(d["f_strength_rs20_xsec_q"], True).clip(upper=0.90)
    a_ind = rank01(d["f_ind_peer_strong_count"], True)
    a_chip = rank01(d["f_chip_winner_rate"], True)
    score_a = 0.65 * a_trend + 0.20 * a_ind + 0.15 * a_chip
    heat_res = (a_trend >= HEAT_TREND_Q) & (a_ind >= HEAT_IND_Q)
    score_a = score_a.copy()
    score_a.loc[heat_res] = np.minimum(score_a.loc[heat_res], HEAT_SCORE_CAP) - HEAT_PENALTY
    rank_a = rank_within_day(pass_a, score_a, d["trade_date"])

    # Path B
    pass_b = (pd.to_numeric(d["f_strength_rs20_xsec_q"], errors="coerce") >= 0.60) & (
        pd.to_numeric(d["f_trend_close_ma20_gap"], errors="coerce") >= 0.00
    )
    score_b = (
        0.50 * d["score_platform_axis_single"]
        + 0.40 * (0.60 * rank01(d["f_chip_winner_rate"], True) + 0.40 * rank01(d["f_chip_low_position120"], True))
        + 0.10 * rank01(d["f_strength_rs20_xsec_q"], True)
    )
    rank_b = rank_within_day(pass_b, score_b, d["trade_date"])

    d["path_a_pass"] = pass_a & (rank_a <= CUTOFF_A)
    d["path_b_pass"] = pass_b & (rank_b <= CUTOFF_B)
    d["rank_a"] = rank_a
    d["rank_b"] = rank_b
    d["score_a"] = score_a
    d["score_b"] = score_b
    d["selected"] = False
    d["path_source"] = ""

    for td, g in d.groupby("trade_date"):
        idx_a = g.index[d.loc[g.index, "path_a_pass"]]
        idx_b = g.index[d.loc[g.index, "path_b_pass"]]
        pick_a = d.loc[idx_a].sort_values("rank_a", ascending=True).head(QUOTA_A).index
        pick_b = d.loc[idx_b].sort_values("rank_b", ascending=True).head(QUOTA_B).index
        picks = pick_a.union(pick_b)
        d.loc[picks, "selected"] = True
        d.loc[pick_a, "path_source"] = "A"
        b_only = [x for x in pick_b if x not in set(pick_a)]
        d.loc[b_only, "path_source"] = "B"
        both = [x for x in pick_b if x in set(pick_a)]
        for idx in both:
            ra = d.at[idx, "rank_a"]
            rb = d.at[idx, "rank_b"]
            d.at[idx, "path_source"] = "A" if (pd.notna(ra) and (pd.isna(rb) or ra <= rb)) else "B"

    d = d[d["selected"]].copy()
    d["score_total"] = np.where(d["path_source"] == "A", d["score_a"], d["score_b"])
    d["rank_global_after_merge"] = np.nan
    for td, g in d.groupby("trade_date"):
        d.loc[g.index, "rank_global_after_merge"] = g["score_total"].rank(method="first", ascending=False).astype(int)
    d["rank_global_after_merge"] = d["rank_global_after_merge"].astype(int)
    return d


def label_a_quality(selected: pd.DataFrame) -> pd.DataFrame:
    x = selected.copy()
    a = x[x["label_true_breakout"] == "A"].copy()
    if a.empty:
        x["a_quality_layer"] = np.where(x["label_true_breakout"] == "A", "A_mid", "")
        x["a_quality_score"] = np.nan
        return x

    win_t1 = (a["ret_t1"] > 0).astype(float)
    win_t2 = (a["ret_t2"] > 0).astype(float)
    win_t3 = (a["ret_t3"] > 0).astype(float)
    a_score = (
        0.35 * rank01(a["ret_t2"], True)
        + 0.35 * rank01(a["ret_t3"], True)
        + 0.15 * rank01(a["ret_t1"], True)
        + 0.10 * win_t2
        + 0.05 * win_t3
    )
    q_low = a_score.quantile(0.33)
    q_high = a_score.quantile(0.67)

    a_layer = pd.Series("A_mid", index=a.index, dtype=object)
    a_layer.loc[a_score <= q_low] = "A_low"
    a_layer.loc[a_score >= q_high] = "A_high"

    x["a_quality_layer"] = ""
    x["a_quality_score"] = np.nan
    x.loc[a.index, "a_quality_layer"] = a_layer
    x.loc[a.index, "a_quality_score"] = a_score
    return x


def classify_selected_c(selected: pd.DataFrame) -> pd.Series:
    c = selected[selected["label_true_breakout"] == "C"].copy()
    out = pd.Series("", index=selected.index, dtype=object)
    if c.empty:
        return out
    t66 = c["score_trend_axis_single"].quantile(0.66)
    i66 = c["score_industry_axis_single"].quantile(0.66)
    p33 = c["score_platform_axis_single"].quantile(0.33)
    chip33 = c["score_chip_axis_single"].quantile(0.33)
    ret20_66 = pd.to_numeric(c["f_strength_ret20"], errors="coerce").quantile(0.66)
    chip_stab_25 = pd.to_numeric(c["f_chip_stability_std10"], errors="coerce").quantile(0.25)
    trend_med = c["score_trend_axis_single"].median()

    out.loc[c.index] = "mixed_pseudo_C"
    out.loc[
        c.index[
            (c["score_industry_axis_single"] >= i66) & (c["score_trend_axis_single"] >= t66)
        ]
    ] = "industry_heat_C"
    out.loc[
        c.index[
            (out.loc[c.index] == "mixed_pseudo_C")
            & (pd.to_numeric(c["f_strength_ret20"], errors="coerce") >= ret20_66)
            & (c["score_chip_axis_single"] <= chip33)
        ]
    ] = "trend_chase_C"
    out.loc[
        c.index[
            (out.loc[c.index] == "mixed_pseudo_C")
            & (c["score_platform_axis_single"] <= p33)
            & (c["score_trend_axis_single"] >= trend_med)
        ]
    ] = "platform_false_break_C"
    out.loc[
        c.index[
            (out.loc[c.index] == "mixed_pseudo_C")
            & (pd.to_numeric(c["f_chip_stability_std10"], errors="coerce") <= chip_stab_25)
            & (c["score_trend_axis_single"] >= trend_med)
        ]
    ] = "chip_distortion_C"
    return out


def classify_selected_g(selected: pd.DataFrame) -> pd.Series:
    g = selected[selected["label_true_breakout"] == "G"].copy()
    out = pd.Series("", index=selected.index, dtype=object)
    if g.empty:
        return out
    out.loc[g.index] = "grey_uncertain"
    weak = (g["ret_t1"].abs() <= 0.015) & (g["ret_t2"].abs() <= 0.020) & (g["ret_t3"].abs() <= 0.025)
    out.loc[g.index[weak]] = "weak_continuation"
    buy_sensitive = (g["ret_t1"] < 0) & (g["ret_t2"] > 0)
    out.loc[g.index[buy_sensitive]] = "buypoint_sensitive_recovery"
    early_fade = (g["ret_t1"] > 0) & (g["ret_t2"] < 0)
    out.loc[g.index[early_fade]] = "early_spike_fade"
    path_mixed = ((g["ret_t2"] > 0) & (g["ret_t3"] < 0)) | ((g["ret_t2"] < 0) & (g["ret_t3"] > 0))
    out.loc[g.index[path_mixed]] = "path_mixed_unclear"
    return out


def main() -> None:
    snapshot = pd.read_parquet(SNAPSHOT)
    selected = build_selected_v3(snapshot)
    fwd = load_forward_daily()
    selected = selected.merge(fwd, on=["ts_code", "trade_date"], how="left")
    selected = selected.dropna(subset=["buy_open_t1", "close_t1", "close_t2", "close_t3"]).copy()
    selected["ret_t1"] = selected["close_t1"] / selected["buy_open_t1"] - 1
    selected["ret_t2"] = selected["close_t2"] / selected["buy_open_t1"] - 1
    selected["ret_t3"] = selected["close_t3"] / selected["buy_open_t1"] - 1

    selected = label_a_quality(selected)
    selected["selected_c_reason"] = classify_selected_c(selected)
    selected["selected_g_reason"] = classify_selected_g(selected)

    selected["selected_class"] = np.select(
        [
            selected["label_true_breakout"] == "A",
            selected["label_true_breakout"] == "C",
            selected["label_true_breakout"] == "G",
        ],
        ["selected_A", "selected_C", "selected_G"],
        default="other",
    )

    out_cols = [
        "ts_code",
        "trade_date",
        "name",
        "industry",
        "label_true_breakout",
        "selected_class",
        "path_source",
        "score_total",
        "rank_global_after_merge",
        "score_trend_axis_single",
        "score_platform_axis_single",
        "score_chip_axis_single",
        "score_industry_axis_single",
        "ret_t1",
        "ret_t2",
        "ret_t3",
        "a_quality_layer",
        "a_quality_score",
        "selected_c_reason",
        "selected_g_reason",
    ]
    selected[out_cols].to_csv(OUT_LAYERS, index=False, encoding="utf-8-sig")

    # selected A split
    a = selected[selected["label_true_breakout"] == "A"].copy()
    a_rows = []
    for layer, g in a.groupby("a_quality_layer"):
        a_rows.append(
            {
                "a_quality_layer": layer,
                "sample_n": int(len(g)),
                "mean_ret_t1": float(g["ret_t1"].mean()),
                "mean_ret_t2": float(g["ret_t2"].mean()),
                "mean_ret_t3": float(g["ret_t3"].mean()),
                "median_ret_t1": float(g["ret_t1"].median()),
                "median_ret_t2": float(g["ret_t2"].median()),
                "median_ret_t3": float(g["ret_t3"].median()),
                "win_t1": float((g["ret_t1"] > 0).mean()),
                "win_t2": float((g["ret_t2"] > 0).mean()),
                "win_t3": float((g["ret_t3"] > 0).mean()),
            }
        )
    a_split = pd.DataFrame(a_rows).sort_values("a_quality_layer")
    a_split.to_csv(OUT_A_SPLIT, index=False, encoding="utf-8-sig")

    # selected C failure reasons
    c = selected[selected["label_true_breakout"] == "C"].copy()
    c_reason = (
        c.groupby("selected_c_reason")
        .apply(
            lambda g: pd.Series(
                {
                    "sample_n": int(len(g)),
                    "share_in_selected_c": float(len(g) / len(c)) if len(c) else np.nan,
                    "mean_ret_t2": float(g["ret_t2"].mean()),
                    "win_t2": float((g["ret_t2"] > 0).mean()),
                }
            )
        )
        .reset_index()
        .sort_values("sample_n", ascending=False)
    )
    c_reason.to_csv(OUT_C_FAIL, index=False, encoding="utf-8-sig")

    # selected G observation reasons
    g = selected[selected["label_true_breakout"] == "G"].copy()
    g_reason = (
        g.groupby("selected_g_reason")
        .apply(
            lambda x: pd.Series(
                {
                    "sample_n": int(len(x)),
                    "share_in_selected_g": float(len(x) / len(g)) if len(g) else np.nan,
                    "mean_ret_t2": float(x["ret_t2"].mean()) if len(x) else np.nan,
                    "win_t2": float((x["ret_t2"] > 0).mean()) if len(x) else np.nan,
                }
            )
        )
        .reset_index()
        .sort_values("sample_n", ascending=False)
    )
    g_reason.to_csv(OUT_G_OBS, index=False, encoding="utf-8-sig")

    # A_high vs selected_C/G core diff
    ah = selected[(selected["label_true_breakout"] == "A") & (selected["a_quality_layer"] == "A_high")]
    sc = selected[selected["label_true_breakout"] == "C"]
    sg = selected[selected["label_true_breakout"] == "G"]
    key_factors = [
        "score_trend_axis_single",
        "score_platform_axis_single",
        "score_chip_axis_single",
        "score_industry_axis_single",
        "f_strength_rs20_xsec_q",
        "f_platform_compress_ratio",
        "f_chip_winner_rate",
        "f_ind_peer_strong_count",
    ]
    rows = []
    for f in key_factors:
        ah_med = pd.to_numeric(ah[f], errors="coerce").median() if len(ah) else np.nan
        c_med = pd.to_numeric(sc[f], errors="coerce").median() if len(sc) else np.nan
        g_med = pd.to_numeric(sg[f], errors="coerce").median() if len(sg) else np.nan
        rows.append(
            {
                "factor": f,
                "A_high_median": ah_med,
                "selected_C_median": c_med,
                "selected_G_median": g_med,
                "A_high_minus_C": ah_med - c_med if pd.notna(ah_med) and pd.notna(c_med) else np.nan,
                "A_high_minus_G": ah_med - g_med if pd.notna(ah_med) and pd.notna(g_med) else np.nan,
            }
        )
    diff = pd.DataFrame(rows).sort_values("A_high_minus_C", ascending=False)
    diff.to_csv(OUT_DIFF, index=False, encoding="utf-8-sig")

    # report
    sel_counts = selected["selected_class"].value_counts(dropna=False).to_dict()
    a_high_n = int(((selected["label_true_breakout"] == "A") & (selected["a_quality_layer"] == "A_high")).sum())
    a_mid_n = int(((selected["label_true_breakout"] == "A") & (selected["a_quality_layer"] == "A_mid")).sum())
    a_low_n = int(((selected["label_true_breakout"] == "A") & (selected["a_quality_layer"] == "A_low")).sum())

    lines = [
        "# true_breakout_selected_quality_diagnosis",
        "",
        f"- window: {WINDOW_START} ~ {WINDOW_END}",
        f"- selected_A: {sel_counts.get('selected_A', 0)}",
        f"- selected_C: {sel_counts.get('selected_C', 0)}",
        f"- selected_G: {sel_counts.get('selected_G', 0)}",
        "",
        "## selected_A quality split",
        f"- A_high: {a_high_n}",
        f"- A_mid: {a_mid_n}",
        f"- A_low: {a_low_n}",
        "",
        "## C mixed-in drivers (top)",
        c_reason.head(5).to_string(index=False) if len(c_reason) else "- no selected_C",
        "",
        "## G observation reasons (top)",
        g_reason.head(5).to_string(index=False) if len(g_reason) else "- no selected_G",
        "",
        "## A_high vs C/G strongest separators",
        diff.head(8).to_string(index=False) if len(diff) else "- no diff rows",
        "",
        "## diagnosis",
        "- Main issue is not only A/C separation; A-high vs A-mid/A-low separation is also insufficient.",
        "- selected_C is dominated by heat/chase-like pseudo-strength modes in this window.",
        "- selected_G contains mixed/uncertain path cases that should stay outside core candidate intent.",
    ]
    OUT_REPORT.write_text("\n".join(lines), encoding="utf-8")

    # small summary print
    summary = {
        "window": {"start": WINDOW_START, "end": WINDOW_END},
        "selected_counts": sel_counts,
        "a_quality": {"A_high": a_high_n, "A_mid": a_mid_n, "A_low": a_low_n},
    }
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
