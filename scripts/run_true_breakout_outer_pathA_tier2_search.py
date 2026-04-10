from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(r"D:\HuaweiAI\quantSystem2")
BASE = ROOT / "data/research/strong_start_full/v4_scan"

IN_MAIN = BASE / "true_breakout_v32_with_priority_tag.csv"
IN_FEAT = BASE / "true_breakout_feature_snapshot_1y.parquet"

OUT_OUTER = BASE / "true_breakout_outer_pathA_pool.csv"
OUT_CAND = BASE / "true_breakout_outer_pathA_candidate_supplement_review.csv"
OUT_MD = BASE / "true_breakout_outer_pathA_tier2_review.md"
OUT_JSON = BASE / "true_breakout_outer_pathA_tier2_summary.json"


def _load() -> pd.DataFrame:
    m = pd.read_csv(IN_MAIN)
    m["ts_code"] = m["ts_code"].astype(str)
    m["trade_date"] = m["trade_date"].astype(str)
    m["window"] = m["window"].astype(str)

    feat = pd.read_parquet(IN_FEAT)[
        ["ts_code", "trade_date", "f_platform_compress_ratio", "f_chip_winner_rate"]
    ].copy()
    feat["ts_code"] = feat["ts_code"].astype(str)
    feat["trade_date"] = feat["trade_date"].astype(str)

    d = m.merge(feat, on=["ts_code", "trade_date"], how="left")
    d = d[d["window"].isin(["main", "confirm"])].copy()
    return d


def _f3_mask(d: pd.DataFrame) -> pd.Series:
    return (
        (d["priority_tag"] == 1)
        & (d["path_source"] == "A")
        & (pd.to_numeric(d["score_platform_axis_single"], errors="coerce") <= 0.64)
        & (pd.to_numeric(d["score_industry_axis_single"], errors="coerce") <= 0.90)
        & (pd.to_numeric(d["f_platform_compress_ratio"], errors="coerce") >= 0.33)
    )


def _stats(df: pd.DataFrame, group: str, window: str) -> dict:
    row: dict[str, str | int | float] = {
        "group": group,
        "window": window,
        "sample_n": int(len(df)),
        "signal_days": int(df["trade_date"].nunique()) if len(df) else 0,
    }
    for l in ["label_A_high", "label_A_mid", "label_A_low", "label_C", "label_G"]:
        row[f"share_{l}"] = float(pd.to_numeric(df[l], errors="coerce").mean()) if len(df) else np.nan
    a = float(pd.to_numeric(df["label_A_high"], errors="coerce").sum()) if len(df) else 0.0
    c = float(pd.to_numeric(df["label_C"], errors="coerce").sum()) if len(df) else 0.0
    row["Ahigh_C_ratio"] = float(a / c) if c > 0 else np.nan

    for h in ["t1", "t2", "t3"]:
        s = pd.to_numeric(df[f"ret_{h}_close"], errors="coerce")
        row[f"mean_ret_{h}"] = float(s.mean()) if len(s) else np.nan
        row[f"median_ret_{h}"] = float(s.median()) if len(s) else np.nan
        row[f"win_{h}"] = float((s > 0).mean()) if len(s) else np.nan
    return row


def main() -> None:
    d = _load()
    f3 = d[_f3_mask(d)].copy()
    outer = d[(d["path_source"] == "A") & (~_f3_mask(d))].copy()

    # Export required outer Path A pool table
    keep_cols = [
        "trade_date",
        "stock_code",
        "stock_name",
        "path_source",
        "priority_tag",
        "score_total",
        "score_platform_axis_single",
        "score_industry_axis_single",
        "f_chip_winner_rate",
        "f_platform_compress_ratio",
        "rank_global_after_merge",
        "selector_explain",
        "ret_t1_close",
        "ret_t2_close",
        "ret_t3_close",
        "label_A_high",
        "label_A_mid",
        "label_A_low",
        "label_C",
        "label_G",
        "window",
    ]
    for c in keep_cols:
        if c not in outer.columns:
            outer[c] = np.nan
    outer = outer[keep_cols].sort_values(["trade_date", "score_total"], ascending=[True, False]).reset_index(drop=True)
    outer.to_csv(OUT_OUTER, index=False, encoding="utf-8-sig")

    # Candidate Tier-2 layers (strictly from outer Path A)
    # S1: precision-first
    s1 = outer[
        (pd.to_numeric(outer["priority_tag"], errors="coerce") == 0)
        & (pd.to_numeric(outer["score_total"], errors="coerce") >= 0.80)
        & (pd.to_numeric(outer["score_platform_axis_single"], errors="coerce") <= 0.66)
        & (pd.to_numeric(outer["score_industry_axis_single"], errors="coerce") <= 0.70)
        & (pd.to_numeric(outer["f_platform_compress_ratio"], errors="coerce") >= 0.40)
    ].copy()

    # S2: balanced supplement
    s2 = outer[
        (pd.to_numeric(outer["score_total"], errors="coerce") >= 0.80)
        & (pd.to_numeric(outer["score_platform_axis_single"], errors="coerce") <= 0.66)
        & (pd.to_numeric(outer["score_industry_axis_single"], errors="coerce") <= 0.90)
        & (pd.to_numeric(outer["f_platform_compress_ratio"], errors="coerce") >= 0.30)
    ].copy()

    # S3: frequency-oriented but still Path A and non-missing compression
    s3 = outer[
        (pd.to_numeric(outer["score_total"], errors="coerce") >= 0.78)
        & (pd.to_numeric(outer["score_platform_axis_single"], errors="coerce") <= 0.80)
        & (pd.to_numeric(outer["score_industry_axis_single"], errors="coerce") <= 1.00)
        & (pd.to_numeric(outer["f_platform_compress_ratio"], errors="coerce") >= 0.00)
    ].copy()

    groups = {
        "F3_baseline": f3,
        "outer_pathA_pool": outer,
        "S1_precision": s1,
        "S2_balanced": s2,
        "S3_frequency": s3,
    }

    rows = []
    for gname, gdf in groups.items():
        rows.append(_stats(gdf, gname, "all"))
        rows.append(_stats(gdf[gdf["window"] == "main"], gname, "main"))
        rows.append(_stats(gdf[gdf["window"] == "confirm"], gname, "confirm"))
    cand = pd.DataFrame(rows)
    cand.to_csv(OUT_CAND, index=False, encoding="utf-8-sig")

    # Build decision summary
    all_rows = cand[cand["window"] == "all"].copy()
    s1_row = all_rows[all_rows["group"] == "S1_precision"].iloc[0]
    s2_row = all_rows[all_rows["group"] == "S2_balanced"].iloc[0]
    s3_row = all_rows[all_rows["group"] == "S3_frequency"].iloc[0]
    f3_row = all_rows[all_rows["group"] == "F3_baseline"].iloc[0]
    outer_row = all_rows[all_rows["group"] == "outer_pathA_pool"].iloc[0]

    # Recommendation logic:
    # choose the candidate that keeps reasonable quality while adding frequency.
    # here we use a simple utility score to avoid manual bias.
    choose = all_rows[all_rows["group"].isin(["S1_precision", "S2_balanced", "S3_frequency"])].copy()
    choose["utility_score"] = (
        0.40 * choose["share_label_A_high"].fillna(0)
        - 0.20 * choose["share_label_C"].fillna(0)
        - 0.15 * choose["share_label_A_low"].fillna(0)
        - 0.10 * choose["share_label_G"].fillna(0)
        + 0.20 * choose["win_t2"].fillna(0)
        + 0.05 * (choose["signal_days"] / max(int(outer_row["signal_days"]), 1))
    )
    best = choose.sort_values("utility_score", ascending=False).iloc[0]
    best_name = str(best["group"])

    md = [
        "# Outer Path A Tier-2 Rebuild Review",
        "",
        "This round only rebuilds Tier-2 source from outer Path A (outside F3 strict pool).",
        "",
        "## Frozen premise",
        "- F3 is kept unchanged as high-purity Tier-1",
        "- No selector structure changes",
        "- No buy-point/sell-point/full backtest",
        "",
        "## Search space",
        "- outer_pathA_pool = path_source='A' and not(F3)",
        f"- outer_pathA_pool size: {int(outer_row['sample_n'])}, days: {int(outer_row['signal_days'])}",
        "",
        "## Candidate tiers",
        "- S1_precision: priority_tag=0 + score/platform/industry/compress strict gate",
        "- S2_balanced: score/platform/industry/compress moderate gate",
        "- S3_frequency: score/platform/industry + non-missing compression gate",
        "",
        "## All-window quick compare",
        f"- F3: n={int(f3_row['sample_n'])}, days={int(f3_row['signal_days'])}, A_high={f3_row['share_label_A_high']:.2%}, C={f3_row['share_label_C']:.2%}, win_t2={f3_row['win_t2']:.2%}",
        f"- outer_pathA_pool: n={int(outer_row['sample_n'])}, days={int(outer_row['signal_days'])}, A_high={outer_row['share_label_A_high']:.2%}, C={outer_row['share_label_C']:.2%}, win_t2={outer_row['win_t2']:.2%}",
        f"- S1: n={int(s1_row['sample_n'])}, days={int(s1_row['signal_days'])}, A_high={s1_row['share_label_A_high']:.2%}, C={s1_row['share_label_C']:.2%}, win_t2={s1_row['win_t2']:.2%}",
        f"- S2: n={int(s2_row['sample_n'])}, days={int(s2_row['signal_days'])}, A_high={s2_row['share_label_A_high']:.2%}, C={s2_row['share_label_C']:.2%}, win_t2={s2_row['win_t2']:.2%}",
        f"- S3: n={int(s3_row['sample_n'])}, days={int(s3_row['signal_days'])}, A_high={s3_row['share_label_A_high']:.2%}, C={s3_row['share_label_C']:.2%}, win_t2={s3_row['win_t2']:.2%}",
        "",
        "## Recommendation",
        f"- Best Tier-2 candidate this round: {best_name}",
        "- Reason: best trade-off between quality and usable frequency under current tiny outer Path A sample.",
        "",
        "## Boundary",
        "- This is candidate-layer judgment only; no new controller/buy-point run in this round.",
    ]
    OUT_MD.write_text("\n".join(md), encoding="utf-8")

    OUT_JSON.write_text(
        json.dumps(
            {
                "outer_pool": _stats(outer, "outer_pathA_pool", "all"),
                "f3_baseline": _stats(f3, "F3_baseline", "all"),
                "candidates_all": choose.sort_values("utility_score", ascending=False).to_dict("records"),
                "recommended_tier2": best_name,
                "files": {
                    "outer_pool": str(OUT_OUTER),
                    "candidate_review": str(OUT_CAND),
                    "review_md": str(OUT_MD),
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print(
        {
            "outer_pathA_n": int(outer_row["sample_n"]),
            "outer_pathA_days": int(outer_row["signal_days"]),
            "best_tier2_candidate": best_name,
        }
    )
    print(str(OUT_OUTER))
    print(str(OUT_CAND))
    print(str(OUT_MD))


if __name__ == "__main__":
    main()
