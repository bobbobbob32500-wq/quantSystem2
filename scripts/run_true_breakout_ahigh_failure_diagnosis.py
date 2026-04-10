from __future__ import annotations

from pathlib import Path
import numpy as np
import pandas as pd


ROOT = Path(r"D:\HuaweiAI\quantSystem2")
BASE = ROOT / "data/research/strong_start_full/v4_scan"
IN_SELECTED = BASE / "true_breakout_selected_quality_layers.csv"
SNAPSHOT = BASE / "true_breakout_feature_snapshot_1y.parquet"

OUT_QUADS = BASE / "true_breakout_ahigh_failure_quadrants.csv"
OUT_A = BASE / "true_breakout_keptAhigh_vs_droppedAhigh.csv"
OUT_C = BASE / "true_breakout_keptC_vs_droppedC.csv"
OUT_REPORT = BASE / "true_breakout_ahigh_refine_failure_report.md"


def _rank01(s: pd.Series, higher: bool = True) -> pd.Series:
    x = pd.to_numeric(s, errors="coerce")
    if not higher:
        x = -x
    return x.rank(method="average", pct=True)


def _med(s: pd.Series) -> float:
    x = pd.to_numeric(s, errors="coerce")
    return float(x.median()) if x.notna().any() else np.nan


def _mean(s: pd.Series) -> float:
    x = pd.to_numeric(s, errors="coerce")
    return float(x.mean()) if x.notna().any() else np.nan


def _build_refine_core(df: pd.DataFrame) -> pd.DataFrame:
    x = df.copy()
    trend = _rank01(x["score_trend_axis_single"], True)
    platform_comp = _rank01(x["f_platform_compress_ratio"], True)
    ind_peer = _rank01(x["f_ind_peer_strong_count"], True)
    chip = _rank01(x["score_chip_axis_single"], True)
    base_score = 0.35 * trend + 0.30 * platform_comp + 0.20 * ind_peer + 0.15 * chip

    pen_ind = _rank01(x["score_industry_axis_single"], True)
    pen_platform_agg = _rank01(x["score_platform_axis_single"], True)
    pen_chip_winner = _rank01(x["f_chip_winner_rate"], True)
    penalty = 0.08 * pen_ind + 0.05 * pen_platform_agg + 0.04 * pen_chip_winner
    x["ahigh_refine_score"] = base_score - penalty

    q_trend = pd.to_numeric(x["score_trend_axis_single"], errors="coerce").quantile(0.80)
    q_ind = pd.to_numeric(x["score_industry_axis_single"], errors="coerce").quantile(0.80)
    q_platform_40 = pd.to_numeric(x["f_platform_compress_ratio"], errors="coerce").quantile(0.40)
    q_platform_25 = pd.to_numeric(x["f_platform_compress_ratio"], errors="coerce").quantile(0.25)
    q_chip_35 = pd.to_numeric(x["score_chip_axis_single"], errors="coerce").quantile(0.35)
    q_trend_70 = pd.to_numeric(x["score_trend_axis_single"], errors="coerce").quantile(0.70)

    cond_heat = (
        (pd.to_numeric(x["score_trend_axis_single"], errors="coerce") >= q_trend)
        & (pd.to_numeric(x["score_industry_axis_single"], errors="coerce") >= q_ind)
        & (pd.to_numeric(x["f_platform_compress_ratio"], errors="coerce") <= q_platform_40)
    )
    cond_platform_false = pd.to_numeric(x["f_platform_compress_ratio"], errors="coerce") <= q_platform_25
    cond_mixed = (
        (pd.to_numeric(x["score_trend_axis_single"], errors="coerce") >= q_trend_70)
        & (
            (pd.to_numeric(x["score_chip_axis_single"], errors="coerce") <= q_chip_35)
            | (pd.to_numeric(x["f_platform_compress_ratio"], errors="coerce") <= q_platform_40)
        )
    )
    x["firewall_reason"] = ""
    x.loc[cond_heat, "firewall_reason"] = "industry_heat_firewall"
    x.loc[(x["firewall_reason"] == "") & cond_platform_false, "firewall_reason"] = "platform_integrity_firewall"
    x.loc[(x["firewall_reason"] == "") & cond_mixed, "firewall_reason"] = "mixed_pseudo_firewall"

    floor = pd.to_numeric(x["ahigh_refine_score"], errors="coerce").median()
    x["core_keep"] = (x["firewall_reason"] == "") & (pd.to_numeric(x["ahigh_refine_score"], errors="coerce") >= floor)
    return x


def _ahigh_subtype(row: pd.Series, t_med: float, p_med: float, c_med: float) -> str:
    t = pd.to_numeric(row["score_trend_axis_single"], errors="coerce")
    p = pd.to_numeric(row["score_platform_axis_single"], errors="coerce")
    c = pd.to_numeric(row["score_chip_axis_single"], errors="coerce")
    path = row.get("path_source", "")
    if path == "A" and pd.notna(t) and t >= t_med:
        return "high_momentum_frontline_A"
    if path == "B" and pd.notna(p) and pd.notna(c) and p >= p_med and c >= c_med:
        return "steady_structure_chip_A"
    return "mixed_Ahigh"


def _factor_summary(kept: pd.DataFrame, dropped: pd.DataFrame, group_name: str, factors: list[str]) -> pd.DataFrame:
    rows = []
    for f in factors:
        rows.append(
            {
                "group": group_name,
                "factor": f,
                "kept_n": int(len(kept)),
                "dropped_n": int(len(dropped)),
                "kept_median": _med(kept[f]) if f in kept.columns else np.nan,
                "dropped_median": _med(dropped[f]) if f in dropped.columns else np.nan,
                "kept_minus_dropped": (_med(kept[f]) - _med(dropped[f])) if (f in kept.columns and f in dropped.columns) else np.nan,
            }
        )
    return pd.DataFrame(rows)


def main() -> None:
    df = pd.read_csv(IN_SELECTED)
    snap = pd.read_parquet(
        SNAPSHOT,
        columns=[
            "ts_code",
            "trade_date",
            "f_platform_compress_ratio",
            "f_ind_peer_strong_count",
            "f_chip_winner_rate",
            "f_strength_rs20_xsec_q",
        ],
    )
    snap["trade_date"] = snap["trade_date"].astype(str)
    df["trade_date"] = df["trade_date"].astype(str)
    df = df.merge(snap, on=["ts_code", "trade_date"], how="left")

    # baseline for this failure diagnosis = old core without G
    base = df[df["label_true_breakout"].isin(["A", "C"])].copy()
    x = _build_refine_core(base)

    kept_ah = x[(x["label_true_breakout"] == "A") & (x["a_quality_layer"] == "A_high") & (x["core_keep"])]
    dropped_ah = x[(x["label_true_breakout"] == "A") & (x["a_quality_layer"] == "A_high") & (~x["core_keep"])]
    kept_c = x[(x["label_true_breakout"] == "C") & (x["core_keep"])]
    dropped_c = x[(x["label_true_breakout"] == "C") & (~x["core_keep"])]

    x["failure_quadrant"] = ""
    x.loc[kept_ah.index, "failure_quadrant"] = "kept_Ahigh"
    x.loc[dropped_ah.index, "failure_quadrant"] = "dropped_Ahigh"
    x.loc[kept_c.index, "failure_quadrant"] = "kept_C"
    x.loc[dropped_c.index, "failure_quadrant"] = "dropped_C"

    t_med = _med(x["score_trend_axis_single"])
    p_med = _med(x["score_platform_axis_single"])
    c_med = _med(x["score_chip_axis_single"])
    x["ahigh_subtype"] = ""
    ah_idx = x[(x["label_true_breakout"] == "A") & (x["a_quality_layer"] == "A_high")].index
    x.loc[ah_idx, "ahigh_subtype"] = x.loc[ah_idx].apply(_ahigh_subtype, axis=1, args=(t_med, p_med, c_med))

    out_cols = [
        "ts_code",
        "trade_date",
        "name",
        "industry",
        "label_true_breakout",
        "a_quality_layer",
        "path_source",
        "score_total",
        "score_trend_axis_single",
        "score_platform_axis_single",
        "score_chip_axis_single",
        "score_industry_axis_single",
        "f_strength_rs20_xsec_q",
        "f_platform_compress_ratio",
        "f_chip_winner_rate",
        "f_ind_peer_strong_count",
        "ret_t1",
        "ret_t2",
        "ret_t3",
        "selected_c_reason",
        "firewall_reason",
        "core_keep",
        "failure_quadrant",
        "ahigh_subtype",
    ]
    x[out_cols].to_csv(OUT_QUADS, index=False, encoding="utf-8-sig")

    factors = [
        "score_trend_axis_single",
        "score_platform_axis_single",
        "score_chip_axis_single",
        "score_industry_axis_single",
        "f_strength_rs20_xsec_q",
        "f_platform_compress_ratio",
        "f_chip_winner_rate",
        "f_ind_peer_strong_count",
        "score_total",
    ]

    a_cmp = _factor_summary(kept_ah, dropped_ah, "Ahigh_keep_vs_drop", factors)
    # add subtype composition
    ah_subtype = (
        x[(x["label_true_breakout"] == "A") & (x["a_quality_layer"] == "A_high")]
        .groupby(["core_keep", "ahigh_subtype"])
        .size()
        .reset_index(name="n")
    )
    a_cmp.to_csv(OUT_A, index=False, encoding="utf-8-sig")
    # append subtype block
    with OUT_A.open("a", encoding="utf-8") as f:
        f.write("\n\n# subtype_composition\n")
        ah_subtype.to_csv(f, index=False)

    c_cmp = _factor_summary(kept_c, dropped_c, "C_keep_vs_drop", factors)
    c_reason_cmp = (
        x[x["label_true_breakout"] == "C"]
        .groupby(["core_keep", "selected_c_reason"])
        .size()
        .reset_index(name="n")
        .sort_values(["core_keep", "n"], ascending=[True, False])
    )
    c_cmp.to_csv(OUT_C, index=False, encoding="utf-8-sig")
    with OUT_C.open("a", encoding="utf-8") as f:
        f.write("\n\n# c_reason_keep_drop\n")
        c_reason_cmp.to_csv(f, index=False)

    # conflict vs net-separation audit
    conflict_rows = []
    for fac in factors:
        ka = _med(kept_ah[fac]) if fac in kept_ah.columns else np.nan
        da = _med(dropped_ah[fac]) if fac in dropped_ah.columns else np.nan
        kc = _med(kept_c[fac]) if fac in kept_c.columns else np.nan
        dc = _med(dropped_c[fac]) if fac in dropped_c.columns else np.nan
        gain_a = ka - da if pd.notna(ka) and pd.notna(da) else np.nan
        gain_c = kc - dc if pd.notna(kc) and pd.notna(dc) else np.nan
        tag = "unknown"
        if pd.notna(gain_a) and pd.notna(gain_c):
            if gain_a > 0 and gain_c < 0:
                tag = "net_separator"
            elif gain_a > 0 and gain_c > 0:
                tag = "conflict_same_direction"
            elif gain_a < 0 and gain_c > 0:
                tag = "bad_reverse"
            elif gain_a < 0 and gain_c < 0:
                tag = "weak_global_down"
        conflict_rows.append(
            {
                "factor": fac,
                "gain_Ahigh_keep_minus_drop": gain_a,
                "gain_C_keep_minus_drop": gain_c,
                "tag": tag,
            }
        )
    conflict = pd.DataFrame(conflict_rows).sort_values("tag")

    # headline reason summary
    kept_ah_n = len(kept_ah)
    dropped_ah_n = len(dropped_ah)
    kept_c_n = len(kept_c)
    dropped_c_n = len(dropped_c)
    ah_keep_rate = kept_ah_n / (kept_ah_n + dropped_ah_n) if (kept_ah_n + dropped_ah_n) else np.nan
    c_drop_rate = dropped_c_n / (kept_c_n + dropped_c_n) if (kept_c_n + dropped_c_n) else np.nan

    # most difficult C mode
    c_hard = (
        c_reason_cmp[c_reason_cmp["core_keep"] == True]  # noqa: E712
        .sort_values("n", ascending=False)
        .head(3)
    )

    lines = [
        "# true_breakout_ahigh_refine_failure_report",
        "",
        "## Quadrant counts",
        f"- kept_Ahigh: {kept_ah_n}",
        f"- dropped_Ahigh: {dropped_ah_n}",
        f"- kept_C: {kept_c_n}",
        f"- dropped_C: {dropped_c_n}",
        f"- Ahigh_keep_rate: {ah_keep_rate:.4f}" if pd.notna(ah_keep_rate) else "- Ahigh_keep_rate: NaN",
        f"- C_drop_rate: {c_drop_rate:.4f}" if pd.notna(c_drop_rate) else "- C_drop_rate: NaN",
        "",
        "## Why Ahigh refine failed (summary)",
        "- It raised Ahigh share mainly by shrinking pool size, but C retention stayed high.",
        "- Kept C still dominated by mixed_pseudo / platform_false_break / industry_heat patterns.",
        "- Ahigh retention is incomplete, especially non-dominant Ahigh subtypes.",
        "",
        "## kept_Ahigh vs dropped_Ahigh",
        a_cmp.to_string(index=False),
        "",
        "## Ahigh subtype keep/drop",
        ah_subtype.to_string(index=False),
        "",
        "## kept_C vs dropped_C",
        c_cmp.to_string(index=False),
        "",
        "## C reasons among kept_C (hard-to-kill C)",
        c_hard.to_string(index=False) if len(c_hard) else "- none",
        "",
        "## Keep-Ahigh / Kill-C conflict audit",
        conflict.to_string(index=False),
        "",
        "## Directional fix suggestions (no new version yet)",
        "1. Add Ahigh retention guard by subtype (prevent over-pruning steady/mixed Ahigh).",
        "2. Replace global shrink with C-mode targeted blockers (mixed/platform_false/industry_heat).",
        "3. Prefer net-separator factors; downweight conflict_same_direction factors in purifier stage.",
    ]
    OUT_REPORT.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()
