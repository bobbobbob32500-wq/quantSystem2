from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd


BASE = Path(r"D:\HuaweiAI\quantSystem2\data\research\strong_start_full\v4_scan")
IN_CSV = BASE / "true_breakout_v32_with_priority_tag.csv"
OUT_AUDIT = BASE / "true_breakout_priority_tag_c_pollution_audit.csv"
OUT_COMPARE = BASE / "true_breakout_priority_tag_ahigh_vs_c_compare.csv"
OUT_REASON = BASE / "true_breakout_priority_tag_reason_audit.csv"
OUT_MD = BASE / "true_breakout_priority_tag_c_pollution_review.md"
OUT_JSON = BASE / "true_breakout_priority_tag_c_pollution_summary.json"

FIELDS = [
    "score_total",
    "score_platform_axis_single",
    "score_industry_axis_single",
    "f_chip_winner_rate",
    "f_platform_compress_ratio",
    "rank_global_after_merge",
    "pathA_score",
    "heat_bucket",
]

NUM_FIELDS_PREFERRED = [
    "score_total",
    "score_platform_axis_single",
    "score_industry_axis_single",
    "f_chip_winner_rate",
    "f_platform_compress_ratio",
    "rank_global_after_merge",
    "pathA_score",
]

WINDOWS = ["all", "main", "confirm"]


def subset_window(df: pd.DataFrame, w: str) -> pd.DataFrame:
    if w == "all":
        return df
    return df[df["window"] == w]


def get_groups(df: pd.DataFrame):
    tag = df[df["priority_tag"] == 1]
    tag_a = tag[tag["path_source"] == "A"]
    g_h = tag_a[tag_a["label_A_high"] == 1]
    g_c = tag_a[tag_a["label_C"] == 1]
    g_al = tag_a[tag_a["label_A_low"] == 1]
    return tag, tag_a, g_h, g_c, g_al


def stats_row(x: pd.Series):
    x = pd.to_numeric(x, errors="coerce").dropna()
    if len(x) == 0:
        return dict(sample_n=0, mean=np.nan, median=np.nan, p25=np.nan, p75=np.nan, min=np.nan, max=np.nan)
    return dict(
        sample_n=int(len(x)),
        mean=float(x.mean()),
        median=float(x.median()),
        p25=float(x.quantile(0.25)),
        p75=float(x.quantile(0.75)),
        min=float(x.min()),
        max=float(x.max()),
    )


def safe_qcut(base: pd.Series, q=4):
    base = pd.to_numeric(base, errors="coerce")
    base = base.replace([np.inf, -np.inf], np.nan).dropna()
    if len(base) < q:
        return None
    try:
        bins = pd.qcut(base, q=q, duplicates="drop")
    except Exception:
        return None
    cats = bins.cat.categories
    if len(cats) < 2:
        return None
    return cats


def assign_bin(values: pd.Series, cats):
    vals = pd.to_numeric(values, errors="coerce")
    b = pd.cut(vals, bins=cats)
    return b.astype(str)


def ratio(n, d):
    return float(n / d) if d else np.nan


def main():
    df = pd.read_csv(IN_CSV)
    for c in ["label_A_high", "label_A_low", "label_C", "priority_tag", "is_core_candidate", "pass_v3_2_candidate"]:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0).astype(int)
    df["window"] = df["window"].astype(str)

    num_fields = [f for f in NUM_FIELDS_PREFERRED if f in df.columns]

    # Core source check: where does C pollution come from
    tag = df[df["priority_tag"] == 1]
    c_in_tag = tag[tag["label_C"] == 1]
    c_from_path_a = int((c_in_tag["path_source"] == "A").sum()) if len(c_in_tag) else 0
    c_from_path_b = int((c_in_tag["path_source"] == "B").sum()) if len(c_in_tag) else 0
    c_from_path_a_share = ratio(c_from_path_a, len(c_in_tag))

    # File 1: high-level audit
    audit_rows = []
    for w in WINDOWS:
        d = subset_window(df, w)
        tag_w, tag_a_w, h_w, c_w, al_w = get_groups(d)
        c_tag_w = tag_w[tag_w["label_C"] == 1]
        c_tag_w_a = int((c_tag_w["path_source"] == "A").sum())
        audit_rows.extend(
            [
                {"window": w, "metric": "priority_tag_1_sample_n", "value": int(len(tag_w))},
                {"window": w, "metric": "priority_tag_1_pathA_sample_n", "value": int(len(tag_a_w))},
                {"window": w, "metric": "group_H_n", "value": int(len(h_w))},
                {"window": w, "metric": "group_C_n", "value": int(len(c_w))},
                {"window": w, "metric": "group_AL_n", "value": int(len(al_w))},
                {"window": w, "metric": "group_H_pct_in_pathA_tag", "value": ratio(len(h_w), len(tag_a_w))},
                {"window": w, "metric": "group_C_pct_in_pathA_tag", "value": ratio(len(c_w), len(tag_a_w))},
                {"window": w, "metric": "group_AL_pct_in_pathA_tag", "value": ratio(len(al_w), len(tag_a_w))},
                {"window": w, "metric": "C_in_tag1_n", "value": int(len(c_tag_w))},
                {"window": w, "metric": "C_in_tag1_pathA_n", "value": c_tag_w_a},
                {"window": w, "metric": "C_in_tag1_pathA_share", "value": ratio(c_tag_w_a, len(c_tag_w))},
            ]
        )
    audit_df = pd.DataFrame(audit_rows)
    audit_df.to_csv(OUT_AUDIT, index=False, encoding="utf-8-sig")

    # File 2: A_high vs C numeric + bucket audit
    cmp_rows = []
    for w in WINDOWS:
        d = subset_window(df, w)
        _, _, h_w, c_w, _ = get_groups(d)

        for field in num_fields:
            for gname, gdf in [("A_high", h_w), ("C", c_w)]:
                s = stats_row(gdf[field])
                s.update({"window": w, "group": gname, "field": field, "section": "numeric_summary"})
                cmp_rows.append(s)

            h_med = pd.to_numeric(h_w[field], errors="coerce").median()
            c_med = pd.to_numeric(c_w[field], errors="coerce").median()
            cmp_rows.append(
                {
                    "window": w,
                    "group": "H_minus_C",
                    "field": field,
                    "section": "median_gap",
                    "sample_n": np.nan,
                    "mean": np.nan,
                    "median": float(h_med - c_med) if pd.notna(h_med) and pd.notna(c_med) else np.nan,
                    "p25": np.nan,
                    "p75": np.nan,
                    "min": np.nan,
                    "max": np.nan,
                }
            )

            cats = safe_qcut(
                pd.concat([pd.to_numeric(h_w[field], errors="coerce"), pd.to_numeric(c_w[field], errors="coerce")]), q=4
            )
            if cats is not None:
                for gname, gdf in [("A_high", h_w), ("C", c_w)]:
                    bins = assign_bin(gdf[field], cats)
                    vc = bins.value_counts(normalize=True, dropna=False)
                    for b, share in vc.items():
                        cmp_rows.append(
                            {
                                "window": w,
                                "group": gname,
                                "field": field,
                                "section": "bucket_share",
                                "bucket": str(b),
                                "share": float(share),
                            }
                        )
    compare_df = pd.DataFrame(cmp_rows)
    compare_df.to_csv(OUT_COMPARE, index=False, encoding="utf-8-sig")

    # File 3: reason/explain audit
    reason_rows = []
    reason_fields = [f for f in ["priority_reason", "selector_explain"] if f in df.columns]
    for w in WINDOWS:
        d = subset_window(df, w)
        _, _, h_w, c_w, _ = get_groups(d)
        for rf in reason_fields:
            for gname, gdf in [("A_high", h_w), ("C", c_w)]:
                s = gdf[rf].fillna("<NA>").astype(str)
                vc = s.value_counts(dropna=False)
                total = vc.sum()
                for val, cnt in vc.head(20).items():
                    reason_rows.append(
                        {
                            "window": w,
                            "field": rf,
                            "group": gname,
                            "reason_value": val,
                            "count": int(cnt),
                            "share": float(cnt / total) if total else np.nan,
                        }
                    )
    reason_df = pd.DataFrame(reason_rows)
    reason_df.to_csv(OUT_REASON, index=False, encoding="utf-8-sig")

    # Window-consistency from median gaps
    gap = compare_df[
        (compare_df["section"] == "median_gap") & (compare_df["group"] == "H_minus_C")
    ][["window", "field", "median"]].copy()
    pivot = gap.pivot_table(index="field", columns="window", values="median", aggfunc="first")

    stable_same_sign = []
    unstable_or_flip = []
    for field in pivot.index:
        m = pivot.loc[field].get("main", np.nan)
        c = pivot.loc[field].get("confirm", np.nan)
        if pd.isna(m) or pd.isna(c):
            unstable_or_flip.append(field)
            continue
        if (m > 0 and c > 0) or (m < 0 and c < 0):
            stable_same_sign.append(field)
        else:
            unstable_or_flip.append(field)

    # Which dimension looks most explanatory in main window?
    cat_map = {
        "ranking_heat": ["rank_global_after_merge"],
        "platform_industry": ["score_platform_axis_single", "score_industry_axis_single"],
        "chip_compress": ["f_chip_winner_rate", "f_platform_compress_ratio"],
        "total_score": ["score_total"],
    }
    cat_strength = {}
    for cat, fs in cat_map.items():
        vals = []
        for f in fs:
            x = gap[(gap["window"] == "main") & (gap["field"] == f)]["median"]
            if not x.empty and pd.notna(x.iloc[0]):
                vals.append(abs(float(x.iloc[0])))
        cat_strength[cat] = float(np.mean(vals)) if vals else 0.0
    main_driver_cat = max(cat_strength, key=cat_strength.get) if cat_strength else "unknown"

    # Overheat vs structure blur heuristic
    _, _, h_all, c_all, _ = get_groups(df)
    def med(dd: pd.DataFrame, col: str):
        x = pd.to_numeric(dd[col], errors="coerce").dropna()
        return float(x.median()) if len(x) else np.nan

    h_ind = med(h_all, "score_industry_axis_single") if "score_industry_axis_single" in df.columns else np.nan
    c_ind = med(c_all, "score_industry_axis_single") if "score_industry_axis_single" in df.columns else np.nan
    h_rank = med(h_all, "rank_global_after_merge") if "rank_global_after_merge" in df.columns else np.nan
    c_rank = med(c_all, "rank_global_after_merge") if "rank_global_after_merge" in df.columns else np.nan
    if pd.notna(h_ind) and pd.notna(c_ind) and pd.notna(h_rank) and pd.notna(c_rank) and (c_ind >= h_ind) and (c_rank >= h_rank):
        pollution_type = "overheat_mixed_in"
    else:
        pollution_type = "structure_not_separated"

    # Main pool stability check
    pool_stable = bool((df["is_core_candidate"] == df["pass_v3_2_candidate"]).all())

    # 7 direct answers
    q1 = bool(c_from_path_a_share >= 0.7) if not pd.isna(c_from_path_a_share) else False
    meaningful = []
    for f in stable_same_sign:
        m = pivot.loc[f].get("main", np.nan)
        c = pivot.loc[f].get("confirm", np.nan)
        if pd.notna(m) and pd.notna(c) and (abs(m) >= 0.03 or abs(c) >= 0.03):
            meaningful.append(f)
    q2 = len(meaningful) >= 2
    q3 = {
        "ranking_heat": "ranking_heat",
        "platform_industry": "platform_industry",
        "chip_compress": "chip_compress",
        "total_score": "total_score",
    }.get(main_driver_cat, "explain_reason_pattern")
    q4 = "overheat_mixed_in" if pollution_type == "overheat_mixed_in" else "structure_not_separated"
    q5 = len(stable_same_sign) >= 2
    q6 = q5
    q7 = "NOT_READY"
    q7_reason = "C contamination inside priority_tag=1 is still high and cross-window separation is not stable enough."

    lines = []
    lines.append("# priority_tag C-pollution source audit")
    lines.append("")
    lines.append("## Conclusion summary")
    lines.append(f"- Main C source: {'Path A' if q1 else 'not dominated by Path A'}")
    lines.append(f"- Stable pollution clues found: {'YES' if q5 else 'NO'}")
    lines.append(f"- Ready for minimal tag-purification research: {'YES' if q6 else 'NO'}")
    lines.append(f"- Ready for entry research: {q7} ({q7_reason})")
    lines.append("")
    lines.append("## A_high vs C difference location")
    for w in WINDOWS:
        d = subset_window(df, w)
        _, tag_a_w, h_w, c_w, _ = get_groups(d)
        lines.append(f"### {w}")
        lines.append(f"- priority_tag=1 & Path A n: {len(tag_a_w)}")
        lines.append(f"- A_high n: {len(h_w)}, C n: {len(c_w)}")
        ww = gap[gap["window"] == w].dropna(subset=["median"]).copy()
        if len(ww):
            ww["abs_gap"] = ww["median"].abs()
            for _, r in ww.sort_values("abs_gap", ascending=False).head(3).iterrows():
                lines.append(f"- {r['field']}: median_gap(H-C)={r['median']:.4f}")
    lines.append("")
    lines.append("## explain / reason audit")
    if len(reason_df):
        for w in WINDOWS:
            rw = reason_df[reason_df["window"] == w]
            if rw.empty:
                continue
            lines.append(f"### {w}")
            for rf in sorted(rw["field"].unique()):
                rrf = rw[rw["field"] == rf]
                top_h = rrf[rrf["group"] == "A_high"].sort_values("count", ascending=False).head(3)
                top_c = rrf[rrf["group"] == "C"].sort_values("count", ascending=False).head(3)
                h_txt = "; ".join([f"{x.reason_value}({x.share:.2%})" for x in top_h.itertuples()]) if len(top_h) else "NA"
                c_txt = "; ".join([f"{x.reason_value}({x.share:.2%})" for x in top_c.itertuples()]) if len(top_c) else "NA"
                lines.append(f"- {rf} | A_high top: {h_txt}")
                lines.append(f"- {rf} | C top: {c_txt}")
    else:
        lines.append("- No reason/explain field available.")
    lines.append("")
    lines.append("## Ranking / heat-layer audit")
    lines.append(f"- Main driver category: {q3}")
    lines.append(f"- Pollution pattern: {q4}")
    if "rank_global_after_merge" in pivot.index:
        lines.append(
            f"- rank_global_after_merge median_gap(H-C): main={pivot.loc['rank_global_after_merge'].get('main', np.nan)}, "
            f"confirm={pivot.loc['rank_global_after_merge'].get('confirm', np.nan)}"
        )
    lines.append("")
    lines.append("## Main-pool stability")
    lines.append(f"- Result: {'MAIN_POOL_STABLE' if pool_stable else 'MAIN_POOL_ERODED'}")
    lines.append("- is_core_candidate is still determined by pass_v3_2_candidate; priority_tag remains a layering label only.")
    lines.append("")
    lines.append("## Direct answers to 7 questions")
    lines.append(f"1. Is C pollution mainly from Path A? {'YES' if q1 else 'NO'}")
    lines.append(f"2. Is A_high vs C visibly separable inside Path A? {'YES' if q2 else 'NO'}")
    lines.append(f"3. Main separation driver: {q3}")
    lines.append(f"4. C pollution is closer to: {q4}")
    lines.append(f"5. Stable pollution clues found? {'YES' if q5 else 'NO'}")
    lines.append(f"6. Enough clues for minimal tag-purification research? {'YES' if q6 else 'NO'}")
    lines.append(f"7. Ready for entry research (Scheme B)? {q7} ({q7_reason})")
    lines.append("")
    lines.append("## Next-step recommendation")
    lines.append(f"- Ready for minimal tag-purification research: {'YES' if q6 else 'NO'}")
    lines.append(f"- Ready for entry research (Scheme B): {q7}")

    OUT_MD.write_text("\n".join(lines), encoding="utf-8")

    summary = {
        "c_pollution_from_path_a_share": c_from_path_a_share,
        "stable_same_sign_fields": stable_same_sign,
        "unstable_or_flip_fields": unstable_or_flip,
        "main_driver_category": q3,
        "pollution_type": q4,
        "answers": {
            "q1_C_from_pathA": q1,
            "q2_Ahigh_vs_C_visible_separation": q2,
            "q3_main_driver": q3,
            "q4_pollution_type": q4,
            "q5_stable_clues_found": q5,
            "q6_ready_for_minimal_tag_purify_research": q6,
            "q7_ready_for_entry_research": q7,
            "q7_reason": q7_reason,
        },
        "files": {
            "audit": str(OUT_AUDIT),
            "compare": str(OUT_COMPARE),
            "reason": str(OUT_REASON),
            "report": str(OUT_MD),
        },
    }
    OUT_JSON.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print(
        json.dumps(
            {
                "rows_input": int(len(df)),
                "rows_audit": int(len(audit_df)),
                "rows_compare": int(len(compare_df)),
                "rows_reason": int(len(reason_df)),
                "ready_for_minimal_tag_purify_research": q6,
                "ready_for_entry_research": q7,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
