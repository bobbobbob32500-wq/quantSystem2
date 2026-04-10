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

OUT_MAIN = BASE / "true_breakout_v32_with_priority_tag.csv"
OUT_QUALITY = BASE / "true_breakout_priority_tag_quality_review.csv"
OUT_RETURN = BASE / "true_breakout_priority_tag_return_review.csv"
OUT_REVIEW = BASE / "true_breakout_schemeB_review.md"
OUT_SUMMARY = BASE / "true_breakout_priority_tag_summary.json"

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


def build_base_selected(snapshot: pd.DataFrame) -> pd.DataFrame:
    d = snapshot.copy()
    d["trade_date"] = d["trade_date"].astype(str)
    d = d[(d["trade_date"] >= ALL_START) & (d["trade_date"] <= ALL_END)].copy()
    d = d[d["label_true_breakout"].isin(["A", "C", "G"])].copy()

    # Axis scores (same as v3 freeze branch)
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
    d["rank_in_path"] = np.nan
    d["selected"] = False
    d["path_source"] = ""
    d["score_total"] = np.nan

    for td, g in d.groupby("trade_date"):
        idx_a = g.index[d.loc[g.index, "path_a_pass"]]
        idx_b = g.index[d.loc[g.index, "path_b_pass"]]
        pick_a = d.loc[idx_a].sort_values("path_a_pass", ascending=False).head(QUOTA_A).index
        # path rank from score
        pick_a = d.loc[idx_a].sort_values(score_a.loc[idx_a].name if False else "ts_code").index if False else pick_a
        pick_a = d.loc[idx_a].assign(_s=score_a.loc[idx_a]).sort_values("_s", ascending=False).head(QUOTA_A).index
        pick_b = d.loc[idx_b].assign(_s=score_b.loc[idx_b]).sort_values("_s", ascending=False).head(QUOTA_B).index
        picks = pick_a.union(pick_b)
        d.loc[picks, "selected"] = True
        d.loc[pick_a, "path_source"] = "A"
        d.loc[pick_a, "score_total"] = score_a.loc[pick_a]
        d.loc[pick_a, "rank_in_path"] = d.loc[pick_a].assign(_s=score_a.loc[pick_a])["_s"].rank(method="first", ascending=False)
        b_only = [x for x in pick_b if x not in set(pick_a)]
        d.loc[b_only, "path_source"] = "B"
        d.loc[b_only, "score_total"] = score_b.loc[b_only]
        d.loc[b_only, "rank_in_path"] = d.loc[b_only].assign(_s=score_b.loc[b_only])["_s"].rank(method="first", ascending=False)
        both = [x for x in pick_b if x in set(pick_a)]
        for idx in both:
            ra = score_a.loc[idx]
            rb = score_b.loc[idx]
            if pd.notna(ra) and (pd.isna(rb) or ra >= rb):
                d.at[idx, "path_source"] = "A"
                d.at[idx, "score_total"] = ra
            else:
                d.at[idx, "path_source"] = "B"
                d.at[idx, "score_total"] = rb
            d.at[idx, "rank_in_path"] = 1

    selected = d[d["selected"]].copy()
    selected["rank_global_after_merge"] = np.nan
    for td, g in selected.groupby("trade_date"):
        selected.loc[g.index, "rank_global_after_merge"] = g["score_total"].rank(method="first", ascending=False).astype(int)
    selected["rank_global_after_merge"] = selected["rank_global_after_merge"].astype(int)
    selected["window"] = "other"
    selected.loc[(selected["trade_date"] >= MAIN_START) & (selected["trade_date"] <= MAIN_END), "window"] = "main"
    selected.loc[(selected["trade_date"] >= CONF_START) & (selected["trade_date"] <= CONF_END), "window"] = "confirm"
    return selected[selected["window"].isin(["main", "confirm"])].copy()


def add_returns_and_quality(base_selected: pd.DataFrame) -> pd.DataFrame:
    fwd = load_forward_daily()
    d = base_selected.merge(fwd, on=["ts_code", "trade_date"], how="left")
    d = d.dropna(subset=["buy_open_t1", "close_t1", "close_t2", "close_t3"]).copy()
    d["ret_t1"] = d["close_t1"] / d["buy_open_t1"] - 1
    d["ret_t2"] = d["close_t2"] / d["buy_open_t1"] - 1
    d["ret_t3"] = d["close_t3"] / d["buy_open_t1"] - 1

    a = d[d["label_true_breakout"] == "A"].copy()
    d["a_quality_layer"] = ""
    if not a.empty:
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
        d.loc[a.index, "a_quality_layer"] = layer
    return d


def apply_v31_relaxed_mask(d: pd.DataFrame) -> pd.Series:
    r1 = (d["score_total"] >= 0.8300) & (d["score_platform_axis_single"] >= 0.2950)
    r2 = ~((d["score_industry_axis_single"] >= 0.6650) & (d["f_chip_winner_rate"] >= 0.9940))
    r3 = ~((d["score_platform_axis_single"] <= 0.2950) & (d["f_platform_compress_ratio"] >= 0.6900))
    return r1 & r2 & r3


def apply_v32_mask(d: pd.DataFrame) -> pd.Series:
    # robust R2_R3 in quantile-band style
    q_ind_60 = d["score_industry_axis_single"].quantile(0.60)
    q_chip_65 = d["f_chip_winner_rate"].quantile(0.65)
    q_platform_35 = d["score_platform_axis_single"].quantile(0.35)
    q_comp_65 = d["f_platform_compress_ratio"].quantile(0.65)
    r2 = ~((d["score_industry_axis_single"] >= q_ind_60) & (d["f_chip_winner_rate"] >= q_chip_65))
    r3 = ~((d["score_platform_axis_single"] <= q_platform_35) & (d["f_platform_compress_ratio"] >= q_comp_65))
    return r2 & r3


def summarize_quality(d: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for w in ["main", "confirm", "all"]:
        dw = d if w == "all" else d[d["window"] == w]
        if dw.empty:
            continue
        for pool_name, mask in [
            ("core_pool", dw["is_core_candidate"] == 1),
            ("priority_tag_1", dw["priority_tag"] == 1),
            ("priority_tag_0", dw["priority_tag"] == 0),
        ]:
            g = dw[mask]
            if g.empty:
                continue
            n = len(g)
            ah = int(((g["label_true_breakout"] == "A") & (g["a_quality_layer"] == "A_high")).sum())
            am = int(((g["label_true_breakout"] == "A") & (g["a_quality_layer"] == "A_mid")).sum())
            al = int(((g["label_true_breakout"] == "A") & (g["a_quality_layer"] == "A_low")).sum())
            c = int((g["label_true_breakout"] == "C").sum())
            gg = int((g["label_true_breakout"] == "G").sum())
            rows.append(
                {
                    "window": w,
                    "pool": pool_name,
                    "sample_n": n,
                    "Ahigh_n": ah,
                    "Ahigh_pct": ah / n,
                    "Amid_n": am,
                    "Amid_pct": am / n,
                    "Alow_n": al,
                    "Alow_pct": al / n,
                    "C_n": c,
                    "C_pct": c / n,
                    "G_n": gg,
                    "G_pct": gg / n,
                }
            )
    return pd.DataFrame(rows)


def summarize_returns(d: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for w in ["main", "confirm", "all"]:
        dw = d if w == "all" else d[d["window"] == w]
        if dw.empty:
            continue
        for pool_name, mask in [
            ("core_pool", dw["is_core_candidate"] == 1),
            ("priority_tag_1", dw["priority_tag"] == 1),
            ("priority_tag_0", dw["priority_tag"] == 0),
        ]:
            g = dw[mask]
            if g.empty:
                continue
            rows.append(
                {
                    "window": w,
                    "pool": pool_name,
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
    return pd.DataFrame(rows)


def main() -> None:
    snapshot = pd.read_parquet(SNAPSHOT)
    base_selected = build_base_selected(snapshot)
    enriched = add_returns_and_quality(base_selected)

    v32_mask = apply_v32_mask(enriched)
    v31_relaxed_mask = apply_v31_relaxed_mask(enriched)

    core = enriched[v32_mask].copy()
    core["is_core_candidate"] = 1
    core["pass_v3_2_candidate"] = 1
    core["pass_v3_1_relaxed"] = v31_relaxed_mask.loc[core.index].astype(int)
    core["priority_tag"] = ((v31_relaxed_mask.loc[core.index]) & (core["is_core_candidate"] == 1)).astype(int)
    core["priority_reason"] = np.where(
        core["priority_tag"] == 1,
        "in_v32_core_and_hit_v31_relaxed",
        "in_v32_core_only",
    )
    core["selector_reject_reason"] = ""
    core["selector_explain"] = (
        "schemeB:v32_core;"
        + "path="
        + core["path_source"].astype(str)
        + ";priority_tag="
        + core["priority_tag"].astype(str)
    )
    core["stock_code"] = core["ts_code"]
    core["stock_name"] = core["name"]
    core["ret_t1_close"] = core["ret_t1"]
    core["ret_t2_close"] = core["ret_t2"]
    core["ret_t3_close"] = core["ret_t3"]
    core["label_A_high"] = ((core["label_true_breakout"] == "A") & (core["a_quality_layer"] == "A_high")).astype(int)
    core["label_A_mid"] = ((core["label_true_breakout"] == "A") & (core["a_quality_layer"] == "A_mid")).astype(int)
    core["label_A_low"] = ((core["label_true_breakout"] == "A") & (core["a_quality_layer"] == "A_low")).astype(int)
    core["label_C"] = (core["label_true_breakout"] == "C").astype(int)
    core["label_G"] = (core["label_true_breakout"] == "G").astype(int)

    out_cols = [
        "stock_code",
        "stock_name",
        "ts_code",
        "trade_date",
        "name",
        "industry",
        "label_true_breakout",
        "a_quality_layer",
        "window",
        "path_source",
        "is_core_candidate",
        "pass_v3_2_candidate",
        "pass_v3_1_relaxed",
        "priority_tag",
        "priority_reason",
        "score_total",
        "score_trend_axis_single",
        "score_platform_axis_single",
        "score_chip_axis_single",
        "score_industry_axis_single",
        "rank_in_path",
        "rank_global_after_merge",
        "selector_reject_reason",
        "selector_explain",
        "buy_date",
        "buy_open_t1",
        "close_t1",
        "close_t2",
        "close_t3",
        "ret_t1",
        "ret_t2",
        "ret_t3",
        "ret_t1_close",
        "ret_t2_close",
        "ret_t3_close",
        "label_A_high",
        "label_A_mid",
        "label_A_low",
        "label_C",
        "label_G",
    ]
    core[out_cols].to_csv(OUT_MAIN, index=False, encoding="utf-8-sig")

    quality = summarize_quality(core)
    quality.to_csv(OUT_QUALITY, index=False, encoding="utf-8-sig")

    ret = summarize_returns(core)
    ret.to_csv(OUT_RETURN, index=False, encoding="utf-8-sig")

    # review md
    def q(window: str, pool: str) -> dict:
        x = quality[(quality["window"] == window) & (quality["pool"] == pool)]
        return {} if x.empty else x.iloc[0].to_dict()

    def r(window: str, pool: str) -> dict:
        x = ret[(ret["window"] == window) & (ret["pool"] == pool)]
        return {} if x.empty else x.iloc[0].to_dict()

    lines = [
        "# Scheme B Review",
        "",
        "## Frozen dual-layer roles",
        "- Main system: `v3.2_candidate`（唯一正式出票基础，决定能否进入核心候选池）。",
        "- Enhancement tag: `v3.1_relaxed`（仅在已入 v3.2 主池样本上加优先级标签，不能单独出票）。",
        "- Why 3.2 is main: 跨窗口稳定性更好、样本规模更可用。",
        "- Why 3.1 is tag-only: 主窗强但留出波动较大，更适合作为“超强提示层”。",
        "- Why 3.1 cannot be standalone: 易放大样本内效应，削弱主池稳定性。",
        "",
    ]
    for w in ["main", "confirm", "all"]:
        lines.append(f"## {w}")
        for pool in ["core_pool", "priority_tag_1", "priority_tag_0"]:
            qq = q(w, pool)
            rr = r(w, pool)
            if not qq:
                continue
            lines.append(
                f"- {pool}: n={int(qq['sample_n'])}, Ahigh={qq['Ahigh_pct']:.2%}, C={qq['C_pct']:.2%}, G={qq['G_pct']:.2%}; "
                f"win_t2={rr['win_t2']:.2%}, mean_ret_t2={rr['mean_ret_t2']:.4f}, median_ret_t2={rr['median_ret_t2']:.4f}"
            )
        lines.append("")
    OUT_REVIEW.write_text("\n".join(lines), encoding="utf-8")

    summary = {
        "scheme": "B",
        "core_pool_n": int(len(core)),
        "priority_tag_n": int((core["priority_tag"] == 1).sum()),
        "non_priority_n": int((core["priority_tag"] == 0).sum()),
        "outputs": [str(OUT_MAIN), str(OUT_QUALITY), str(OUT_RETURN), str(OUT_REVIEW), str(OUT_SUMMARY)],
    }
    OUT_SUMMARY.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
