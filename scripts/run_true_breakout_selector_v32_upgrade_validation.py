from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(r"D:\HuaweiAI\quantSystem2")
BASE = ROOT / "data/research/strong_start_full/v4_scan"
SNAPSHOT = BASE / "true_breakout_feature_snapshot_1y.parquet"
DB_PATH = ROOT / "data/database/quant_system.db"

OUT_COMPARE = BASE / "true_breakout_selector_v32_compare.csv"
OUT_QUALITY = BASE / "true_breakout_selector_v32_quality_review.csv"
OUT_RETURN = BASE / "true_breakout_selector_v32_return_review.csv"
OUT_REPORT = BASE / "true_breakout_selector_v32_upgrade_report.md"
OUT_EMBED = BASE / "true_breakout_selector_v32_rule_embed_note.md"

MAIN_START, MAIN_END = "20251230", "20260330"
CONF_START, CONF_END = "20250929", "20251229"
ALL_START, ALL_END = CONF_START, MAIN_END

# frozen v3_freeze_candidate_2 structure params
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


def build_base_selector(snapshot: pd.DataFrame) -> pd.DataFrame:
    d = snapshot.copy()
    d["trade_date"] = d["trade_date"].astype(str)
    d = d[(d["trade_date"] >= ALL_START) & (d["trade_date"] <= ALL_END)].copy()
    d = d[d["label_true_breakout"].isin(["A", "C", "G"])].copy()

    # single-axis scores
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
    d["score_platform_axis_single"] = (
        0.70 * rank01(d["f_platform_compress_ratio"], False) + 0.30 * rank01(d["f_platform_range30"], False)
    )
    d["score_chip_axis_single"] = (
        0.45 * rank01(d["f_chip_winner_rate"], True)
        + 0.35 * rank01(d["f_chip_low_position120"], True)
        + 0.20 * rank01(d["f_chip_stability_std10"], True)
    )
    d["score_industry_axis_single"] = (
        0.75 * rank01(d["f_ind_peer_strong_count"], True) + 0.25 * rank01(d["f_ind_strength_5d"], True)
    )

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

    selected = d[d["selected"]].copy()
    selected["score_total"] = np.where(selected["path_source"] == "A", selected["score_a"], selected["score_b"])
    selected["window"] = "other"
    selected.loc[(selected["trade_date"] >= MAIN_START) & (selected["trade_date"] <= MAIN_END), "window"] = "main"
    selected.loc[(selected["trade_date"] >= CONF_START) & (selected["trade_date"] <= CONF_END), "window"] = "confirm"
    selected = selected[selected["window"].isin(["main", "confirm"])].copy()
    return selected


def assign_a_quality_by_baseline_ret(df: pd.DataFrame) -> pd.Series:
    a = df[df["label_true_breakout"] == "A"].copy()
    out = pd.Series("", index=df.index, dtype=object)
    if a.empty:
        return out
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
    layer = pd.Series("A_mid", index=a.index, dtype=object)
    layer.loc[a_score <= q_low] = "A_low"
    layer.loc[a_score >= q_high] = "A_high"
    out.loc[a.index] = layer
    return out


def apply_rule_variant(selected: pd.DataFrame, variant: str) -> pd.DataFrame:
    d = selected.copy()
    if variant == "v3_freeze_candidate_2":
        mask = pd.Series(True, index=d.index)
    elif variant == "v3.1_relaxed":
        r1 = (d["score_total"] >= 0.8300) & (d["score_platform_axis_single"] >= 0.2950)
        r2 = ~((d["score_industry_axis_single"] >= 0.6650) & (d["f_chip_winner_rate"] >= 0.9940))
        r3 = ~((d["score_platform_axis_single"] <= 0.2950) & (d["f_platform_compress_ratio"] >= 0.6900))
        mask = r1 & r2 & r3
    elif variant == "v3.2_candidate":
        # robust R2_R3 only (drop R1), thresholds in quantile-band style
        q_ind_60 = d["score_industry_axis_single"].quantile(0.60)
        q_chip_65 = d["f_chip_winner_rate"].quantile(0.65)
        q_platform_35 = d["score_platform_axis_single"].quantile(0.35)
        q_comp_65 = d["f_platform_compress_ratio"].quantile(0.65)
        r2 = ~((d["score_industry_axis_single"] >= q_ind_60) & (d["f_chip_winner_rate"] >= q_chip_65))
        r3 = ~((d["score_platform_axis_single"] <= q_platform_35) & (d["f_platform_compress_ratio"] >= q_comp_65))
        mask = r2 & r3
    else:
        raise ValueError(variant)
    out = d[mask].copy()
    out["variant"] = variant
    return out


def summarize(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    q_rows = []
    r_rows = []
    for v in sorted(df["variant"].unique()):
        for w in ["main", "confirm"]:
            d = df[(df["variant"] == v) & (df["window"] == w)].copy()
            if d.empty:
                continue
            n = len(d)
            n_ah = int(((d["label_true_breakout"] == "A") & (d["a_quality_layer"] == "A_high")).sum())
            n_am = int(((d["label_true_breakout"] == "A") & (d["a_quality_layer"] == "A_mid")).sum())
            n_al = int(((d["label_true_breakout"] == "A") & (d["a_quality_layer"] == "A_low")).sum())
            n_c = int((d["label_true_breakout"] == "C").sum())
            n_g = int((d["label_true_breakout"] == "G").sum())
            q_rows.append(
                {
                    "variant": v,
                    "window": w,
                    "sample_n": n,
                    "Ahigh_n": n_ah,
                    "Ahigh_pct": n_ah / n,
                    "Amid_n": n_am,
                    "Amid_pct": n_am / n,
                    "Alow_n": n_al,
                    "Alow_pct": n_al / n,
                    "C_n": n_c,
                    "C_pct": n_c / n,
                    "G_n": n_g,
                    "G_pct": n_g / n,
                    "Ahigh_over_C": n_ah / n_c if n_c else np.nan,
                }
            )
            r_rows.append(
                {
                    "variant": v,
                    "window": w,
                    "sample_n": n,
                    "win_t1": float((d["ret_t1"] > 0).mean()),
                    "win_t2": float((d["ret_t2"] > 0).mean()),
                    "win_t3": float((d["ret_t3"] > 0).mean()),
                    "mean_ret_t1": float(d["ret_t1"].mean()),
                    "mean_ret_t2": float(d["ret_t2"].mean()),
                    "mean_ret_t3": float(d["ret_t3"].mean()),
                    "median_ret_t1": float(d["ret_t1"].median()),
                    "median_ret_t2": float(d["ret_t2"].median()),
                    "median_ret_t3": float(d["ret_t3"].median()),
                }
            )
    return pd.DataFrame(q_rows), pd.DataFrame(r_rows)


def main() -> None:
    snapshot = pd.read_parquet(SNAPSHOT)
    selected = build_base_selector(snapshot)
    fwd = load_forward_daily()
    selected = selected.merge(fwd, on=["ts_code", "trade_date"], how="left")
    selected = selected.dropna(subset=["buy_open_t1", "close_t1", "close_t2", "close_t3"]).copy()
    selected["ret_t1"] = selected["close_t1"] / selected["buy_open_t1"] - 1
    selected["ret_t2"] = selected["close_t2"] / selected["buy_open_t1"] - 1
    selected["ret_t3"] = selected["close_t3"] / selected["buy_open_t1"] - 1
    selected["a_quality_layer"] = assign_a_quality_by_baseline_ret(selected)

    v_base = apply_rule_variant(selected, "v3_freeze_candidate_2")
    v31 = apply_rule_variant(selected, "v3.1_relaxed")
    v32 = apply_rule_variant(selected, "v3.2_candidate")
    allv = pd.concat([v_base, v31, v32], ignore_index=True)

    quality, returns = summarize(allv)
    quality.to_csv(OUT_QUALITY, index=False, encoding="utf-8-sig")
    returns.to_csv(OUT_RETURN, index=False, encoding="utf-8-sig")

    # compare table with retention vs baseline
    comp_rows = []
    for w in ["main", "confirm"]:
        b = quality[(quality["variant"] == "v3_freeze_candidate_2") & (quality["window"] == w)].iloc[0]
        for v in ["v3.1_relaxed", "v3.2_candidate"]:
            x = quality[(quality["variant"] == v) & (quality["window"] == w)].iloc[0]
            comp_rows.append(
                {
                    "window": w,
                    "variant": v,
                    "sample_n": int(x["sample_n"]),
                    "Ahigh_n": int(x["Ahigh_n"]),
                    "C_n": int(x["C_n"]),
                    "Ahigh_pct": float(x["Ahigh_pct"]),
                    "C_pct": float(x["C_pct"]),
                    "Ahigh_over_C": float(x["Ahigh_over_C"]) if pd.notna(x["Ahigh_over_C"]) else np.nan,
                    "Ahigh_retention_vs_base": float(x["Ahigh_n"] / b["Ahigh_n"]) if b["Ahigh_n"] else np.nan,
                    "C_retention_vs_base": float(x["C_n"] / b["C_n"]) if b["C_n"] else np.nan,
                    "Ahigh_over_C_delta_vs_base": float(x["Ahigh_over_C"] - b["Ahigh_over_C"])
                    if pd.notna(x["Ahigh_over_C"]) and pd.notna(b["Ahigh_over_C"])
                    else np.nan,
                }
            )
    compare = pd.DataFrame(comp_rows)
    compare.to_csv(OUT_COMPARE, index=False, encoding="utf-8-sig")

    # note/report
    note_lines = [
        "# v3.2 Rule Embed Note",
        "",
        "v3.2 embeds robust R2_R3 only (R1 removed):",
        "- R2 robust band: NOT(industry_axis >= q60 AND chip_winner >= q65)",
        "- R3 robust band: NOT(platform_axis <= q35 AND platform_compress >= q65)",
        "Quantiles are computed on the selected-universe (main+confirm) T-day visible scores.",
    ]
    OUT_EMBED.write_text("\n".join(note_lines), encoding="utf-8")

    def q(v: str, w: str) -> dict:
        return quality[(quality["variant"] == v) & (quality["window"] == w)].iloc[0].to_dict()

    def r(v: str, w: str) -> dict:
        return returns[(returns["variant"] == v) & (returns["window"] == w)].iloc[0].to_dict()

    lines = ["# true_breakout_selector_v32_upgrade_report", ""]
    for w in ["main", "confirm"]:
        lines.append(f"## {w}")
        for v in ["v3_freeze_candidate_2", "v3.1_relaxed", "v3.2_candidate"]:
            qv, rv = q(v, w), r(v, w)
            lines.append(
                f"- {v}: n={int(qv['sample_n'])}, Ahigh={int(qv['Ahigh_n'])} ({qv['Ahigh_pct']:.2%}), "
                f"C={int(qv['C_n'])} ({qv['C_pct']:.2%}), Ahigh/C={qv['Ahigh_over_C']:.3f}; "
                f"win_t2={rv['win_t2']:.2%}, mean_ret_t2={rv['mean_ret_t2']:.4f}, median_ret_t2={rv['median_ret_t2']:.4f}"
            )
        lines.append("")
    OUT_REPORT.write_text("\n".join(lines), encoding="utf-8")

    summary = {
        "rows": {"base": len(v_base), "v31_relaxed": len(v31), "v32": len(v32)},
        "outputs": [str(OUT_COMPARE), str(OUT_QUALITY), str(OUT_RETURN), str(OUT_REPORT), str(OUT_EMBED)],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

