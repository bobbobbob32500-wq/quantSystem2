from __future__ import annotations

from pathlib import Path
import numpy as np
import pandas as pd


ROOT = Path(r"D:\HuaweiAI\quantSystem2")
BASE = ROOT / "data/research/strong_start_full/v4_scan"

V2_SET = BASE / "true_breakout_selector_v2_validation_set.parquet"
SNAPSHOT = BASE / "true_breakout_feature_snapshot_1y.parquet"

OUT_QUADS = BASE / "true_breakout_selector_v2_failure_quadrants.csv"
OUT_FILTER = BASE / "true_breakout_selector_v2_filter_error_audit.csv"
OUT_AXIS = BASE / "true_breakout_selector_v2_axis_failure_audit.csv"
OUT_A_MISSED = BASE / "true_breakout_selector_v2_selectedA_vs_missedA.csv"
OUT_C_SELECTED = BASE / "true_breakout_selector_v2_selectedC_vs_rejectedC.csv"
OUT_MD = BASE / "true_breakout_selector_v2_failure_diagnosis.md"


def _safe_med(s: pd.Series) -> float:
    x = pd.to_numeric(s, errors="coerce")
    return float(x.median()) if x.notna().any() else np.nan


def _summarize_quad(df: pd.DataFrame) -> pd.DataFrame:
    total = len(df)
    a_n = int((df["label_true_breakout"] == "A").sum())
    c_n = int((df["label_true_breakout"] == "C").sum())
    selected = df[df["is_candidate"]]
    selected_a = int((selected["label_true_breakout"] == "A").sum())
    selected_c = int((selected["label_true_breakout"] == "C").sum())

    quads = [
        ("selected_A", (df["is_candidate"]) & (df["label_true_breakout"] == "A")),
        ("selected_C", (df["is_candidate"]) & (df["label_true_breakout"] == "C")),
        ("missed_A", (~df["is_candidate"]) & (df["label_true_breakout"] == "A")),
        ("rejected_C", (~df["is_candidate"]) & (df["label_true_breakout"] == "C")),
    ]
    rows = []
    for name, cond in quads:
        n = int(cond.sum())
        rows.append(
            {
                "quadrant": name,
                "n": n,
                "share_in_window": n / total if total else np.nan,
                "share_within_A_or_C": (
                    n / a_n if "A" in name and a_n else n / c_n if "C" in name and c_n else np.nan
                ),
            }
        )
    rows.append(
        {
            "quadrant": "window_overall",
            "n": total,
            "share_in_window": 1.0,
            "share_within_A_or_C": np.nan,
            "a_share_full": a_n / total if total else np.nan,
            "a_share_selected": selected_a / len(selected) if len(selected) else np.nan,
            "selected_n": len(selected),
            "selected_a": selected_a,
            "selected_c": selected_c,
        }
    )
    return pd.DataFrame(rows)


def _filter_audit(df: pd.DataFrame) -> pd.DataFrame:
    # v2 hard filters
    r1 = "f_strength_rs20_xsec_q >= 0.72"
    r2 = "f_chip_stability_std10 >= 0.0032"
    conds = {
        r1: pd.to_numeric(df["f_strength_rs20_xsec_q"], errors="coerce") >= 0.72,
        r2: pd.to_numeric(df["f_chip_stability_std10"], errors="coerce") >= 0.0032,
    }
    quads = {
        "selected_A": (df["is_candidate"]) & (df["label_true_breakout"] == "A"),
        "selected_C": (df["is_candidate"]) & (df["label_true_breakout"] == "C"),
        "missed_A": (~df["is_candidate"]) & (df["label_true_breakout"] == "A"),
        "rejected_C": (~df["is_candidate"]) & (df["label_true_breakout"] == "C"),
    }

    rows = []
    for rule, c in conds.items():
        for qname, qmask in quads.items():
            qn = int(qmask.sum())
            hit = int((c & qmask).sum())
            rows.append(
                {
                    "rule": rule,
                    "quadrant": qname,
                    "n_quadrant": qn,
                    "hit_n": hit,
                    "hit_rate_in_quadrant": hit / qn if qn else np.nan,
                }
            )

    # combined pass behavior
    pass_all = conds[r1] & conds[r2]
    for qname, qmask in quads.items():
        qn = int(qmask.sum())
        hit = int((pass_all & qmask).sum())
        rows.append(
            {
                "rule": "combined_hard_filters",
                "quadrant": qname,
                "n_quadrant": qn,
                "hit_n": hit,
                "hit_rate_in_quadrant": hit / qn if qn else np.nan,
            }
        )
    return pd.DataFrame(rows)


def _axis_audit(df: pd.DataFrame) -> pd.DataFrame:
    axes = [
        "score_trend_axis",
        "score_platform_axis",
        "score_chip_axis",
        "score_industry_axis",
    ]
    quads = {
        "selected_A": (df["is_candidate"]) & (df["label_true_breakout"] == "A"),
        "selected_C": (df["is_candidate"]) & (df["label_true_breakout"] == "C"),
        "missed_A": (~df["is_candidate"]) & (df["label_true_breakout"] == "A"),
        "rejected_C": (~df["is_candidate"]) & (df["label_true_breakout"] == "C"),
    }
    rows = []
    for a in axes:
        vals = {k: _safe_med(df.loc[m, a]) for k, m in quads.items()}
        rows.append(
            {
                "axis": a,
                **vals,
                "selected_A_minus_selected_C": vals["selected_A"] - vals["selected_C"],
                "selected_A_minus_missed_A": vals["selected_A"] - vals["missed_A"],
                "selected_C_minus_rejected_C": vals["selected_C"] - vals["rejected_C"],
            }
        )
    return pd.DataFrame(rows).sort_values("selected_A_minus_selected_C", ascending=False)


def _pair_compare(df: pd.DataFrame, left_mask: pd.Series, right_mask: pd.Series, out_path: Path) -> pd.DataFrame:
    feats = [
        "f_strength_rs20_xsec_q",
        "f_strength_ret20",
        "f_trend_close_ma20_gap",
        "f_trend_close_ma60_gap",
        "f_platform_range20",
        "f_platform_range_best",
        "f_platform_len",
        "f_chip_stability_std10",
        "f_chip_winner_rate",
        "f_chip_low_position120",
        "f_ind_peer_strong_count",
        "f_ind_strength_5d",
        "score_trend_axis",
        "score_platform_axis",
        "score_chip_axis",
        "score_industry_axis",
    ]
    rows = []
    for f in feats:
        l = pd.to_numeric(df.loc[left_mask, f], errors="coerce")
        r = pd.to_numeric(df.loc[right_mask, f], errors="coerce")
        rows.append(
            {
                "feature": f,
                "left_n": int(l.notna().sum()),
                "right_n": int(r.notna().sum()),
                "left_median": _safe_med(l),
                "right_median": _safe_med(r),
                "median_gap_left_minus_right": _safe_med(l) - _safe_med(r),
            }
        )
    out = pd.DataFrame(rows).sort_values("median_gap_left_minus_right", ascending=False)
    out.to_csv(out_path, index=False, encoding="utf-8-sig")
    return out


def main() -> None:
    v2 = pd.read_parquet(V2_SET).copy()
    snap = pd.read_parquet(SNAPSHOT).copy()
    v2["trade_date"] = v2["trade_date"].astype(str)
    snap["trade_date"] = snap["trade_date"].astype(str)

    # join raw feature fields needed for failure attribution
    need_cols = [
        "ts_code",
        "trade_date",
        "f_strength_rs20_xsec_q",
        "f_chip_stability_std10",
        "f_strength_ret20",
        "f_trend_close_ma20_gap",
        "f_trend_close_ma60_gap",
        "f_platform_range20",
        "f_platform_range_best",
        "f_platform_len",
        "f_chip_winner_rate",
        "f_chip_low_position120",
        "f_ind_peer_strong_count",
        "f_ind_strength_5d",
    ]
    d = v2.merge(snap[need_cols], on=["ts_code", "trade_date"], how="left", suffixes=("", "_y"))
    for c in [x for x in d.columns if x.endswith("_y")]:
        base = c[:-2]
        if base in d.columns:
            d[base] = d[base].fillna(d[c])
            d = d.drop(columns=[c])
        else:
            d = d.rename(columns={c: base})

    # 4 quadrants
    quads = _summarize_quad(d)
    quads.to_csv(OUT_QUADS, index=False, encoding="utf-8-sig")

    # filter error audit
    filt = _filter_audit(d)
    filt.to_csv(OUT_FILTER, index=False, encoding="utf-8-sig")

    # axis failure audit
    axis = _axis_audit(d)
    axis.to_csv(OUT_AXIS, index=False, encoding="utf-8-sig")

    # selected_A vs missed_A
    selected_a = (d["is_candidate"]) & (d["label_true_breakout"] == "A")
    missed_a = (~d["is_candidate"]) & (d["label_true_breakout"] == "A")
    selA_vs_missA = _pair_compare(d, selected_a, missed_a, OUT_A_MISSED)

    # selected_C vs rejected_C
    selected_c = (d["is_candidate"]) & (d["label_true_breakout"] == "C")
    rejected_c = (~d["is_candidate"]) & (d["label_true_breakout"] == "C")
    selC_vs_rejC = _pair_compare(d, selected_c, rejected_c, OUT_C_SELECTED)

    # diagnosis markdown
    full_a_share = float((d["label_true_breakout"] == "A").mean())
    sel = d[d["is_candidate"]]
    sel_a_share = float((sel["label_true_breakout"] == "A").mean()) if len(sel) else np.nan

    # identify key failure points
    # most A-killing hard rule = lower hit rate in missed_A than selected_A gap
    r = filt[filt["rule"].isin(["f_strength_rs20_xsec_q >= 0.72", "f_chip_stability_std10 >= 0.0032"])]
    pivot = r.pivot(index="rule", columns="quadrant", values="hit_rate_in_quadrant")
    pivot["a_kill_gap"] = pivot["selected_A"] - pivot["missed_A"]
    pivot["c_leak_gap"] = pivot["selected_C"] - pivot["rejected_C"]
    a_killer = pivot["a_kill_gap"].idxmax()
    c_leaker = pivot["c_leak_gap"].idxmax()

    best_push_c = axis.sort_values("selected_C_minus_rejected_C", ascending=False).iloc[0]["axis"]
    best_help_a = axis.sort_values("selected_A_minus_missed_A", ascending=False).iloc[0]["axis"]
    worst_for_a = axis.sort_values("selected_A_minus_missed_A", ascending=True).iloc[0]["axis"]

    lines = [
        "# true_breakout_selector_v2_failure_diagnosis",
        "",
        f"- full-sample A share: {full_a_share:.4f}",
        f"- selected-sample A share: {sel_a_share:.4f}",
        "- why A share is below baseline: selected_C remains too high while many A are filtered out by combined hard filters and axis mix near the cut line.",
        "",
        "## Four quadrants",
        quads.to_string(index=False),
        "",
        "## Hard-filter error findings",
        f"- most A-killing rule: {a_killer}",
        f"- most C-leaking rule: {c_leaker}",
        "",
        "## Axis failure findings",
        f"- axis helping A most (selected_A vs missed_A): {best_help_a}",
        f"- axis pushing C most (selected_C vs rejected_C): {best_push_c}",
        f"- axis suppressing A most: {worst_for_a}",
        "",
        "## selected_A vs missed_A (top gaps)",
        selA_vs_missA.head(10).to_string(index=False),
        "",
        "## selected_C vs rejected_C (top gaps)",
        selC_vs_rejC.head(10).to_string(index=False),
        "",
        "## Repair directions (no new version yet)",
        "1) Re-check hard-filter role split: move one borderline hard rule into scoring if it mainly causes A misses.",
        "2) Constrain C-pushing axis contribution near candidate cut line (reduce false promotion of C).",
        "3) Strengthen A-recovery axis in scoring tie-break (for selected_A vs missed_A positive gaps).",
    ]
    OUT_MD.write_text("\n".join(lines), encoding="utf-8")

    print("Generated:")
    print(" -", OUT_QUADS)
    print(" -", OUT_FILTER)
    print(" -", OUT_AXIS)
    print(" -", OUT_A_MISSED)
    print(" -", OUT_C_SELECTED)
    print(" -", OUT_MD)


if __name__ == "__main__":
    main()
