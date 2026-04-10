from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(r"D:\HuaweiAI\quantSystem2")
BASE = ROOT / "data/research/strong_start_full/v4_scan"

IN_MAIN = BASE / "true_breakout_v32_with_priority_tag.csv"
IN_FEAT = BASE / "true_breakout_feature_snapshot_1y.parquet"

OUT_CONSTRAINTS = BASE / "true_breakout_dual_objective_constraints.md"
OUT_CAND_REVIEW = BASE / "true_breakout_tier2_candidate_review.csv"
OUT_COMPARE = BASE / "true_breakout_tier2_quality_frequency_compare.csv"
OUT_REVIEW = BASE / "true_breakout_production_input_layer_review.md"
OUT_JSON = BASE / "true_breakout_production_input_layer_summary.json"


def _load() -> pd.DataFrame:
    m = pd.read_csv(IN_MAIN)
    m["ts_code"] = m["ts_code"].astype(str)
    m["trade_date"] = m["trade_date"].astype(str)
    m["window"] = m["window"].astype(str)
    m = m[m["window"].isin(["main", "confirm"])].copy()

    feat = pd.read_parquet(IN_FEAT)[["ts_code", "trade_date", "f_platform_compress_ratio", "f_chip_winner_rate"]]
    feat["ts_code"] = feat["ts_code"].astype(str)
    feat["trade_date"] = feat["trade_date"].astype(str)
    return m.merge(feat, on=["ts_code", "trade_date"], how="left")


def _f3_mask(d: pd.DataFrame) -> pd.Series:
    return (
        (d["priority_tag"] == 1)
        & (d["path_source"] == "A")
        & (pd.to_numeric(d["score_platform_axis_single"], errors="coerce") <= 0.64)
        & (pd.to_numeric(d["score_industry_axis_single"], errors="coerce") <= 0.90)
        & (pd.to_numeric(d["f_platform_compress_ratio"], errors="coerce") >= 0.33)
    )


def _metrics(df: pd.DataFrame, name: str, window: str, trading_days: int) -> dict:
    n = len(df)
    signal_days = int(df["trade_date"].nunique()) if n else 0
    row: dict[str, str | float | int] = {
        "group": name,
        "window": window,
        "sample_n": int(n),
        "signal_days": signal_days,
        "signal_day_ratio": float(signal_days / trading_days) if trading_days else np.nan,
        "blank_days": int(trading_days - signal_days) if trading_days else np.nan,
        "blank_day_ratio": float((trading_days - signal_days) / trading_days) if trading_days else np.nan,
        "avg_days_per_signal": float(trading_days / signal_days) if signal_days > 0 else np.nan,
    }
    for l in ["label_A_high", "label_A_mid", "label_A_low", "label_C", "label_G"]:
        row[f"share_{l}"] = float(pd.to_numeric(df[l], errors="coerce").mean()) if n else np.nan
    row["share_A_low_plus_C"] = (
        float(row["share_label_A_low"] + row["share_label_C"])
        if pd.notna(row["share_label_A_low"]) and pd.notna(row["share_label_C"])
        else np.nan
    )
    ah = float(pd.to_numeric(df["label_A_high"], errors="coerce").sum()) if n else 0.0
    c = float(pd.to_numeric(df["label_C"], errors="coerce").sum()) if n else 0.0
    row["Ahigh_C_ratio"] = float(ah / c) if c > 0 else (np.inf if ah > 0 else np.nan)

    for h in ["t1", "t2", "t3"]:
        s = pd.to_numeric(df[f"ret_{h}_close"], errors="coerce")
        row[f"mean_ret_{h}"] = float(s.mean()) if n else np.nan
        row[f"median_ret_{h}"] = float(s.median()) if n else np.nan
        row[f"win_{h}"] = float((s > 0).mean()) if n else np.nan
    return row


def _apply_constraints(row: pd.Series, window: str) -> tuple[bool, dict]:
    # Realistic production floor for current sample scale.
    if window == "all":
        freq_ratio_min = 0.10
        avg_days_max = 10.0
        win_t2_min = 0.60
    else:
        freq_ratio_min = 0.08
        avg_days_max = 12.0
        win_t2_min = 0.55

    quality_ok = (
        pd.notna(row["Ahigh_C_ratio"])
        and row["Ahigh_C_ratio"] >= 1.5
        and pd.notna(row["share_A_low_plus_C"])
        and row["share_A_low_plus_C"] <= 0.45
        and pd.notna(row["win_t2"])
        and row["win_t2"] >= win_t2_min
    )
    frequency_ok = (
        pd.notna(row["signal_day_ratio"])
        and row["signal_day_ratio"] >= freq_ratio_min
        and pd.notna(row["avg_days_per_signal"])
        and row["avg_days_per_signal"] <= avg_days_max
    )
    return bool(quality_ok and frequency_ok), {
        "quality_ok": bool(quality_ok),
        "frequency_ok": bool(frequency_ok),
        "freq_ratio_min": freq_ratio_min,
        "avg_days_max": avg_days_max,
        "win_t2_min": win_t2_min,
    }


def main() -> None:
    d = _load()
    f3 = d[_f3_mask(d)].copy()
    outer = d[(d["path_source"] == "A") & (~_f3_mask(d))].copy()

    candidates = {
        "T2_S1_precision": outer[
            (outer["priority_tag"] == 0)
            & (pd.to_numeric(outer["score_total"], errors="coerce") >= 0.80)
            & (pd.to_numeric(outer["score_platform_axis_single"], errors="coerce") <= 0.66)
            & (pd.to_numeric(outer["score_industry_axis_single"], errors="coerce") <= 0.70)
            & (pd.to_numeric(outer["f_platform_compress_ratio"], errors="coerce") >= 0.40)
        ].copy(),
        "T2_S2_balanced": outer[
            (pd.to_numeric(outer["score_total"], errors="coerce") >= 0.80)
            & (pd.to_numeric(outer["score_platform_axis_single"], errors="coerce") <= 0.66)
            & (pd.to_numeric(outer["score_industry_axis_single"], errors="coerce") <= 0.90)
            & (pd.to_numeric(outer["f_platform_compress_ratio"], errors="coerce") >= 0.30)
        ].copy(),
        "T2_S3_frequency": outer[
            (pd.to_numeric(outer["score_total"], errors="coerce") >= 0.78)
            & (pd.to_numeric(outer["score_platform_axis_single"], errors="coerce") <= 0.80)
            & (pd.to_numeric(outer["score_industry_axis_single"], errors="coerce") <= 1.00)
            & (pd.to_numeric(outer["f_platform_compress_ratio"], errors="coerce") >= 0.00)
        ].copy(),
        "T2_S4_pri0_breadth": outer[
            (outer["priority_tag"] == 0)
            & (pd.to_numeric(outer["score_total"], errors="coerce") >= 0.80)
            & (pd.to_numeric(outer["score_industry_axis_single"], errors="coerce") <= 0.90)
        ].copy(),
    }

    # Candidate-only review
    candidate_rows = []
    compare_rows = []
    windows = ["all", "main", "confirm"]
    trading_days_map = {
        "all": int(d["trade_date"].nunique()),
        "main": int(d[d["window"] == "main"]["trade_date"].nunique()),
        "confirm": int(d[d["window"] == "confirm"]["trade_date"].nunique()),
    }

    base_groups = {"F3": f3, "outer_pathA_pool": outer}

    for gname, gdf in candidates.items():
        for w in windows:
            x = gdf if w == "all" else gdf[gdf["window"] == w]
            row = _metrics(x, gname, w, trading_days_map[w])
            ok, detail = _apply_constraints(pd.Series(row), w)
            row["dual_objective_pass"] = ok
            row.update({f"constraint_{k}": v for k, v in detail.items()})
            candidate_rows.append(row)

    # Full compare: F3, each T2, and F3+T2 union
    all_groups = dict(base_groups)
    all_groups.update(candidates)
    for cname, cdf in candidates.items():
        all_groups[f"F3_plus_{cname}"] = pd.concat([f3, cdf], ignore_index=True)

    for gname, gdf in all_groups.items():
        for w in windows:
            x = gdf if w == "all" else gdf[gdf["window"] == w]
            row = _metrics(x, gname, w, trading_days_map[w])
            ok, detail = _apply_constraints(pd.Series(row), w)
            row["dual_objective_pass"] = ok
            row.update({f"constraint_{k}": v for k, v in detail.items()})
            compare_rows.append(row)

    candidate_df = pd.DataFrame(candidate_rows)
    compare_df = pd.DataFrame(compare_rows)
    candidate_df.to_csv(OUT_CAND_REVIEW, index=False, encoding="utf-8-sig")
    compare_df.to_csv(OUT_COMPARE, index=False, encoding="utf-8-sig")

    # choose best T2 candidate by all-window union utility under dual objective preference
    unions = compare_df[(compare_df["window"] == "all") & (compare_df["group"].str.startswith("F3_plus_T2_"))].copy()
    if unions.empty:
        best_union_name = ""
        best_t2_name = ""
    else:
        unions["utility_score"] = (
            0.28 * unions["share_label_A_high"].fillna(0)
            - 0.18 * unions["share_label_C"].fillna(0)
            - 0.12 * unions["share_label_A_low"].fillna(0)
            - 0.08 * unions["share_label_G"].fillna(0)
            + 0.18 * unions["win_t2"].fillna(0)
            + 0.10 * unions["signal_day_ratio"].fillna(0)
            + 0.06 * unions["mean_ret_t2"].fillna(0)
        )
        # Reward rows that pass all-window dual objective.
        unions.loc[unions["dual_objective_pass"] == True, "utility_score"] += 0.15
        best_row = unions.sort_values("utility_score", ascending=False).iloc[0]
        best_union_name = str(best_row["group"])
        best_t2_name = best_union_name.replace("F3_plus_", "")

    # Write constraints markdown
    constraints_md = [
        "# Dual Objective Constraints (Production-Oriented)",
        "",
        "Current phase requires both quality floor and frequency floor.",
        "",
        "## Quality Floor",
        "- Ahigh/C ratio >= 1.5",
        "- A_low + C share <= 45%",
        "- T+2 win rate floor:",
        "  - all window >= 60%",
        "  - main/confirm window >= 55%",
        "",
        "## Frequency Floor",
        "- signal-day ratio floor:",
        "  - all window >= 10%",
        "  - main/confirm window >= 8%",
        "- avg days per signal ceiling:",
        "  - all window <= 10 days",
        "  - main/confirm window <= 12 days",
        "",
        "## Why this floor is realistic now",
        "- Current Path A sample is sparse (17 events total in eval window).",
        "- A too-tight floor would force empty output and block production progression.",
    ]
    OUT_CONSTRAINTS.write_text("\n".join(constraints_md), encoding="utf-8")

    # review markdown
    f3_all = compare_df[(compare_df["group"] == "F3") & (compare_df["window"] == "all")].iloc[0]
    out_all = compare_df[(compare_df["group"] == "outer_pathA_pool") & (compare_df["window"] == "all")].iloc[0]
    best_all = (
        compare_df[(compare_df["group"] == best_union_name) & (compare_df["window"] == "all")].iloc[0]
        if best_union_name
        else None
    )

    md = [
        "# Production Input Layer Rebuild (Dual Objective)",
        "",
        "This round rebuilds input layer with quality+frequency constraints, selector structure unchanged.",
        "",
        "## Headline",
        f"- F3 Tier-1 stays fixed: n={int(f3_all['sample_n'])}, days={int(f3_all['signal_days'])}, "
        f"A_high={f3_all['share_label_A_high']:.2%}, C={f3_all['share_label_C']:.2%}, win_t2={f3_all['win_t2']:.2%}",
        f"- outer PathA pool: n={int(out_all['sample_n'])}, days={int(out_all['signal_days'])}, "
        f"A_high={out_all['share_label_A_high']:.2%}, C={out_all['share_label_C']:.2%}, win_t2={out_all['win_t2']:.2%}",
    ]
    if best_all is not None:
        md.extend(
            [
                f"- best union candidate: {best_union_name}",
                f"  - n={int(best_all['sample_n'])}, days={int(best_all['signal_days'])}, "
                f"signal_day_ratio={best_all['signal_day_ratio']:.2%}, avg_days_per_signal={best_all['avg_days_per_signal']:.2f}",
                f"  - A_high={best_all['share_label_A_high']:.2%}, C={best_all['share_label_C']:.2%}, "
                f"A_low={best_all['share_label_A_low']:.2%}, Ahigh/C={best_all['Ahigh_C_ratio']:.2f}",
                f"  - win_t2={best_all['win_t2']:.2%}, mean_t2={best_all['mean_ret_t2']:.2%}",
                f"  - dual_objective_pass(all)={bool(best_all['dual_objective_pass'])}",
            ]
        )
    md.extend(
        [
            "",
            "## Decision framing",
            "- Keep F3 as Tier-1 high-purity pool.",
            f"- Tier-2 candidate recommendation: {best_t2_name if best_t2_name else 'N/A'}",
            "- Buy-point development remains paused in this round; this is input-layer decision only.",
        ]
    )
    OUT_REVIEW.write_text("\n".join(md), encoding="utf-8")

    OUT_JSON.write_text(
        json.dumps(
            {
                "recommended_tier2": best_t2_name,
                "recommended_union": best_union_name,
                "f3_all": f3_all.to_dict(),
                "outer_all": out_all.to_dict(),
                "union_all_candidates": unions.to_dict("records") if not unions.empty else [],
                "files": {
                    "constraints": str(OUT_CONSTRAINTS),
                    "candidate_review": str(OUT_CAND_REVIEW),
                    "compare": str(OUT_COMPARE),
                    "review": str(OUT_REVIEW),
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print(
        {
            "recommended_tier2": best_t2_name,
            "recommended_union": best_union_name,
            "f3_days": int(f3_all["signal_days"]),
            "f3_plus_best_days": int(best_all["signal_days"]) if best_all is not None else 0,
        }
    )
    print(str(OUT_CONSTRAINTS))
    print(str(OUT_CAND_REVIEW))
    print(str(OUT_COMPARE))
    print(str(OUT_REVIEW))


if __name__ == "__main__":
    main()
