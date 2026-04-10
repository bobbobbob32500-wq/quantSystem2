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

OUT_AUDIT = BASE / "true_breakout_rule_robustness_audit.csv"
OUT_COMBO = BASE / "true_breakout_rule_combo_compare.csv"
OUT_THRESH = BASE / "true_breakout_rule_threshold_robust_candidates.csv"
OUT_REPORT = BASE / "true_breakout_rule_robustness_report.md"
OUT_DRAFT = BASE / "true_breakout_v31_rules_robust_draft.md"

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


def build_v3_freeze_candidate_2(snapshot: pd.DataFrame) -> pd.DataFrame:
    d = snapshot.copy()
    d["trade_date"] = d["trade_date"].astype(str)
    d = d[(d["trade_date"] >= ALL_START) & (d["trade_date"] <= ALL_END)].copy()
    d = d[d["label_true_breakout"].isin(["A", "C", "G"])].copy()

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
    return selected


def add_quality_layer(x: pd.DataFrame) -> pd.DataFrame:
    d = x.copy()
    a = d[d["label_true_breakout"] == "A"].copy()
    if a.empty:
        d["a_quality_layer"] = ""
        return d
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
    d["a_quality_layer"] = ""
    d.loc[a.index, "a_quality_layer"] = layer
    return d


def add_windows(df: pd.DataFrame) -> pd.DataFrame:
    d = df.copy()
    d["window"] = "other"
    d.loc[(d["trade_date"] >= MAIN_START) & (d["trade_date"] <= MAIN_END), "window"] = "main"
    d.loc[(d["trade_date"] >= CONF_START) & (d["trade_date"] <= CONF_END), "window"] = "confirm"
    return d[d["window"].isin(["main", "confirm"])].copy()


def metrics(df: pd.DataFrame, rule_name: str, window: str) -> dict:
    d = df[(df["window"] == window)].copy()
    n = len(d)
    ah = int(((d["label_true_breakout"] == "A") & (d["a_quality_layer"] == "A_high")).sum())
    c = int((d["label_true_breakout"] == "C").sum())
    return {
        "rule_set": rule_name,
        "window": window,
        "sample_n": n,
        "Ahigh_n": ah,
        "Ahigh_pct": ah / n if n else np.nan,
        "C_n": c,
        "C_pct": c / n if n else np.nan,
        "Ahigh_over_C": ah / c if c else np.nan,
        "win_t1": float((d["ret_t1"] > 0).mean()) if n else np.nan,
        "win_t2": float((d["ret_t2"] > 0).mean()) if n else np.nan,
        "win_t3": float((d["ret_t3"] > 0).mean()) if n else np.nan,
        "mean_ret_t1": float(d["ret_t1"].mean()) if n else np.nan,
        "mean_ret_t2": float(d["ret_t2"].mean()) if n else np.nan,
        "mean_ret_t3": float(d["ret_t3"].mean()) if n else np.nan,
    }


def main() -> None:
    snapshot = pd.read_parquet(SNAPSHOT)
    selected = build_v3_freeze_candidate_2(snapshot)
    fwd = load_forward_daily()
    selected = selected.merge(fwd, on=["ts_code", "trade_date"], how="left")
    selected = selected.dropna(subset=["buy_open_t1", "close_t1", "close_t2", "close_t3"]).copy()
    selected["ret_t1"] = selected["close_t1"] / selected["buy_open_t1"] - 1
    selected["ret_t2"] = selected["close_t2"] / selected["buy_open_t1"] - 1
    selected["ret_t3"] = selected["close_t3"] / selected["buy_open_t1"] - 1
    selected = add_quality_layer(selected)
    selected = add_windows(selected)

    # exact rules
    r1 = (selected["score_total"] >= 0.8377) & (selected["score_platform_axis_single"] >= 0.3080)
    r2 = ~((selected["score_industry_axis_single"] >= 0.6460) & (selected["f_chip_winner_rate"] >= 0.9925))
    r3 = ~((selected["score_platform_axis_single"] <= 0.3080) & (selected["f_platform_compress_ratio"] >= 0.6772))

    rule_sets = {
        "BASELINE": pd.Series(True, index=selected.index),
        "R1": r1,
        "R2": r2,
        "R3": r3,
        "R1_R2": r1 & r2,
        "R1_R3": r1 & r3,
        "R2_R3": r2 & r3,
        "R1_R2_R3": r1 & r2 & r3,
    }

    audit_rows = []
    for rn, mask in rule_sets.items():
        d = selected[mask].copy()
        audit_rows.append(metrics(d, rn, "main"))
        audit_rows.append(metrics(d, rn, "confirm"))
    audit = pd.DataFrame(audit_rows)
    audit.to_csv(OUT_AUDIT, index=False, encoding="utf-8-sig")

    # robust threshold candidates per rule: conservative vs relaxed
    q = selected[[
        "score_total",
        "score_platform_axis_single",
        "score_industry_axis_single",
        "f_chip_winner_rate",
        "f_platform_compress_ratio",
    ]].quantile([0.35, 0.40, 0.45, 0.55, 0.60, 0.65, 0.70, 0.75])

    cand_defs: dict[str, tuple[str, pd.Series]] = {}
    # R1
    cand_defs["R1_conservative"] = (
        "score_total>=q55 & score_platform_axis_single>=q45",
        (selected["score_total"] >= q.loc[0.55, "score_total"]) & (selected["score_platform_axis_single"] >= q.loc[0.45, "score_platform_axis_single"]),
    )
    cand_defs["R1_relaxed"] = (
        "score_total>=q50(~q55 proxied by q45) & score_platform_axis_single>=q40",
        (selected["score_total"] >= q.loc[0.45, "score_total"]) & (selected["score_platform_axis_single"] >= q.loc[0.40, "score_platform_axis_single"]),
    )
    # R2
    cand_defs["R2_conservative"] = (
        "NOT(industry>=q60 & chip>=q65)",
        ~((selected["score_industry_axis_single"] >= q.loc[0.60, "score_industry_axis_single"]) & (selected["f_chip_winner_rate"] >= q.loc[0.65, "f_chip_winner_rate"])),
    )
    cand_defs["R2_relaxed"] = (
        "NOT(industry>=q70 & chip>=q75)",
        ~((selected["score_industry_axis_single"] >= q.loc[0.70, "score_industry_axis_single"]) & (selected["f_chip_winner_rate"] >= q.loc[0.75, "f_chip_winner_rate"])),
    )
    # R3
    cand_defs["R3_conservative"] = (
        "NOT(platform<=q45 & compress>=q60)",
        ~((selected["score_platform_axis_single"] <= q.loc[0.45, "score_platform_axis_single"]) & (selected["f_platform_compress_ratio"] >= q.loc[0.60, "f_platform_compress_ratio"])),
    )
    cand_defs["R3_relaxed"] = (
        "NOT(platform<=q35 & compress>=q65)",
        ~((selected["score_platform_axis_single"] <= q.loc[0.35, "score_platform_axis_single"]) & (selected["f_platform_compress_ratio"] >= q.loc[0.65, "f_platform_compress_ratio"])),
    )

    thresh_rows = []
    for name, (expr, mask) in cand_defs.items():
        for w in ["main", "confirm"]:
            m = metrics(selected[mask], name, w)
            m["candidate_expr"] = expr
            thresh_rows.append(m)
    thresh = pd.DataFrame(thresh_rows)

    # combine to labels keep/candidate_keep/drop
    base_main = audit[(audit["rule_set"] == "BASELINE") & (audit["window"] == "main")].iloc[0]
    base_conf = audit[(audit["rule_set"] == "BASELINE") & (audit["window"] == "confirm")].iloc[0]

    combo_rows = []
    for rn in audit["rule_set"].unique():
        m = audit[(audit["rule_set"] == rn) & (audit["window"] == "main")]
        c = audit[(audit["rule_set"] == rn) & (audit["window"] == "confirm")]
        if m.empty or c.empty:
            continue
        m = m.iloc[0]
        c = c.iloc[0]
        improved_both = (m["Ahigh_over_C"] > base_main["Ahigh_over_C"]) and (c["Ahigh_over_C"] > base_conf["Ahigh_over_C"])
        sample_ok = (m["sample_n"] >= 12) and (c["sample_n"] >= 12)
        c_control = (m["C_pct"] <= base_main["C_pct"]) and (c["C_pct"] <= base_conf["C_pct"])
        returns_not_flip = (m["mean_ret_t2"] > -0.01) and (c["mean_ret_t2"] > -0.01)
        if rn == "BASELINE":
            label = "keep"
        elif improved_both and sample_ok and c_control and returns_not_flip:
            label = "keep"
        elif improved_both and returns_not_flip:
            label = "candidate_keep"
        else:
            label = "drop"
        combo_rows.append(
            {
                "rule_set": rn,
                "main_sample_n": int(m["sample_n"]),
                "main_Ahigh_pct": float(m["Ahigh_pct"]),
                "main_C_pct": float(m["C_pct"]),
                "main_Ahigh_over_C": float(m["Ahigh_over_C"]) if pd.notna(m["Ahigh_over_C"]) else np.nan,
                "main_win_t2": float(m["win_t2"]),
                "main_mean_ret_t2": float(m["mean_ret_t2"]),
                "confirm_sample_n": int(c["sample_n"]),
                "confirm_Ahigh_pct": float(c["Ahigh_pct"]),
                "confirm_C_pct": float(c["C_pct"]),
                "confirm_Ahigh_over_C": float(c["Ahigh_over_C"]) if pd.notna(c["Ahigh_over_C"]) else np.nan,
                "confirm_win_t2": float(c["win_t2"]),
                "confirm_mean_ret_t2": float(c["mean_ret_t2"]),
                "direction_consistent": bool(improved_both),
                "sample_ok": bool(sample_ok),
                "c_control": bool(c_control),
                "returns_not_flip": bool(returns_not_flip),
                "robust_label": label,
            }
        )
    combo = pd.DataFrame(combo_rows).sort_values(["robust_label", "main_Ahigh_over_C"], ascending=[True, False])
    combo.to_csv(OUT_COMBO, index=False, encoding="utf-8-sig")

    # add labels to threshold candidates (single-rule robustness)
    thresh_labeled_rows = []
    for rn in sorted(cand_defs.keys()):
        m = thresh[(thresh["rule_set"] == rn) & (thresh["window"] == "main")]
        c = thresh[(thresh["rule_set"] == rn) & (thresh["window"] == "confirm")]
        if m.empty or c.empty:
            continue
        m = m.iloc[0]
        c = c.iloc[0]
        improved_both = (m["Ahigh_over_C"] > base_main["Ahigh_over_C"]) and (c["Ahigh_over_C"] > base_conf["Ahigh_over_C"])
        sample_ok = (m["sample_n"] >= 12) and (c["sample_n"] >= 12)
        returns_not_flip = (m["mean_ret_t2"] > -0.01) and (c["mean_ret_t2"] > -0.01)
        if improved_both and sample_ok and returns_not_flip:
            label = "keep"
        elif improved_both and returns_not_flip:
            label = "candidate_keep"
        else:
            label = "drop"
        thresh_labeled_rows.append(
            {
                "rule_candidate": rn,
                "candidate_expr": m["candidate_expr"],
                "main_sample_n": int(m["sample_n"]),
                "main_Ahigh_over_C": float(m["Ahigh_over_C"]) if pd.notna(m["Ahigh_over_C"]) else np.nan,
                "main_C_pct": float(m["C_pct"]),
                "main_mean_ret_t2": float(m["mean_ret_t2"]),
                "confirm_sample_n": int(c["sample_n"]),
                "confirm_Ahigh_over_C": float(c["Ahigh_over_C"]) if pd.notna(c["Ahigh_over_C"]) else np.nan,
                "confirm_C_pct": float(c["C_pct"]),
                "confirm_mean_ret_t2": float(c["mean_ret_t2"]),
                "robust_label": label,
            }
        )
    thresh_labeled = pd.DataFrame(thresh_labeled_rows)
    thresh_labeled.to_csv(OUT_THRESH, index=False, encoding="utf-8-sig")

    # report
    top_keep = combo[combo["robust_label"] == "keep"]["rule_set"].tolist()
    top_cand = combo[combo["robust_label"] == "candidate_keep"]["rule_set"].tolist()
    top_drop = combo[combo["robust_label"] == "drop"]["rule_set"].tolist()

    lines = []
    lines.append("# Rule Robustness Audit")
    lines.append("")
    lines.append("## Key Findings")
    lines.append(f"- keep: {top_keep}")
    lines.append(f"- candidate_keep: {top_cand}")
    lines.append(f"- drop: {top_drop}")
    lines.append("")
    lines.append("## Most stable single rule candidates")
    if len(thresh_labeled):
        lines.append(thresh_labeled.sort_values(["robust_label", "main_Ahigh_over_C"], ascending=[True, False]).head(8).to_string(index=False))
    else:
        lines.append("- none")
    lines.append("")
    lines.append("## Draft decision")
    lines.append("- Preserve baseline structure, keep only cross-window-consistent rule combinations.")
    lines.append("- Convert precise constants to percentile-band candidates before selector upgrade.")
    OUT_REPORT.write_text("\n".join(lines), encoding="utf-8")

    # robust draft document
    draft = []
    draft.append("# v3.1 Rules Robust Draft")
    draft.append("")
    draft.append("## keep")
    if top_keep:
        for x in top_keep:
            draft.append(f"- {x}")
    else:
        draft.append("- none")
    draft.append("")
    draft.append("## candidate_keep")
    if top_cand:
        for x in top_cand:
            draft.append(f"- {x}")
    else:
        draft.append("- none")
    draft.append("")
    draft.append("## drop")
    if top_drop:
        for x in top_drop:
            draft.append(f"- {x}")
    else:
        draft.append("- none")
    draft.append("")
    draft.append("## threshold robustness candidates")
    if len(thresh_labeled):
        for _, r in thresh_labeled.sort_values(["robust_label", "main_Ahigh_over_C"], ascending=[True, False]).iterrows():
            draft.append(
                f"- {r['rule_candidate']} [{r['robust_label']}]: {r['candidate_expr']} "
                f"(main A/C={r['main_Ahigh_over_C']:.3f}, confirm A/C={r['confirm_Ahigh_over_C']:.3f})"
            )
    OUT_DRAFT.write_text("\n".join(draft), encoding="utf-8")

    summary = {
        "audit_rows": len(audit),
        "combo_rows": len(combo),
        "threshold_rows": len(thresh_labeled),
        "keep_rule_sets": top_keep,
        "candidate_keep_rule_sets": top_cand,
        "drop_rule_sets": top_drop,
        "outputs": [str(OUT_AUDIT), str(OUT_COMBO), str(OUT_THRESH), str(OUT_REPORT), str(OUT_DRAFT)],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

