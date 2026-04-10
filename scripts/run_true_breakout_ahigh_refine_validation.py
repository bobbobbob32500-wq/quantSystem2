from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(r"D:\HuaweiAI\quantSystem2")
BASE = ROOT / "data/research/strong_start_full/v4_scan"
IN_SELECTED = BASE / "true_breakout_selected_quality_layers.csv"
SNAPSHOT = BASE / "true_breakout_feature_snapshot_1y.parquet"

OUT_COMPARE = BASE / "true_breakout_ahigh_refine_compare.csv"
OUT_SUMMARY = BASE / "true_breakout_ahigh_refine_summary.json"
OUT_RETURN = BASE / "true_breakout_ahigh_refine_return_review.csv"
OUT_REVIEW = BASE / "true_breakout_ahigh_refine_review.md"
OUT_G_EFFECT = BASE / "true_breakout_G_demotion_effect.csv"
OUT_C_FIREWALL = BASE / "true_breakout_selectedC_firewall_effect.csv"


def _rank01(s: pd.Series, higher: bool = True) -> pd.Series:
    x = pd.to_numeric(s, errors="coerce")
    if not higher:
        x = -x
    return x.rank(method="average", pct=True)


def _dist_stats(df: pd.DataFrame, name: str) -> dict:
    n = len(df)
    if n == 0:
        return {
            "variant": name,
            "sample_n": 0,
            "A_high_n": 0,
            "A_mid_n": 0,
            "A_low_n": 0,
            "C_n": 0,
            "G_n": 0,
            "A_high_share": np.nan,
            "A_mid_share": np.nan,
            "A_low_share": np.nan,
            "C_share": np.nan,
            "G_share": np.nan,
        }
    return {
        "variant": name,
        "sample_n": int(n),
        "A_high_n": int(((df["label_true_breakout"] == "A") & (df["a_quality_layer"] == "A_high")).sum()),
        "A_mid_n": int(((df["label_true_breakout"] == "A") & (df["a_quality_layer"] == "A_mid")).sum()),
        "A_low_n": int(((df["label_true_breakout"] == "A") & (df["a_quality_layer"] == "A_low")).sum()),
        "C_n": int((df["label_true_breakout"] == "C").sum()),
        "G_n": int((df["label_true_breakout"] == "G").sum()),
        "A_high_share": float(((df["label_true_breakout"] == "A") & (df["a_quality_layer"] == "A_high")).mean()),
        "A_mid_share": float(((df["label_true_breakout"] == "A") & (df["a_quality_layer"] == "A_mid")).mean()),
        "A_low_share": float(((df["label_true_breakout"] == "A") & (df["a_quality_layer"] == "A_low")).mean()),
        "C_share": float((df["label_true_breakout"] == "C").mean()),
        "G_share": float((df["label_true_breakout"] == "G").mean()),
    }


def _ret_stats(df: pd.DataFrame, name: str) -> dict:
    n = len(df)
    if n == 0:
        return {
            "variant": name,
            "sample_n": 0,
            "mean_ret_t1": np.nan,
            "mean_ret_t2": np.nan,
            "mean_ret_t3": np.nan,
            "median_ret_t1": np.nan,
            "median_ret_t2": np.nan,
            "median_ret_t3": np.nan,
            "win_t1": np.nan,
            "win_t2": np.nan,
            "win_t3": np.nan,
        }
    return {
        "variant": name,
        "sample_n": int(n),
        "mean_ret_t1": float(pd.to_numeric(df["ret_t1"], errors="coerce").mean()),
        "mean_ret_t2": float(pd.to_numeric(df["ret_t2"], errors="coerce").mean()),
        "mean_ret_t3": float(pd.to_numeric(df["ret_t3"], errors="coerce").mean()),
        "median_ret_t1": float(pd.to_numeric(df["ret_t1"], errors="coerce").median()),
        "median_ret_t2": float(pd.to_numeric(df["ret_t2"], errors="coerce").median()),
        "median_ret_t3": float(pd.to_numeric(df["ret_t3"], errors="coerce").median()),
        "win_t1": float((pd.to_numeric(df["ret_t1"], errors="coerce") > 0).mean()),
        "win_t2": float((pd.to_numeric(df["ret_t2"], errors="coerce") > 0).mean()),
        "win_t3": float((pd.to_numeric(df["ret_t3"], errors="coerce") > 0).mean()),
    }


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
    ).copy()
    snap["trade_date"] = snap["trade_date"].astype(str)
    df["trade_date"] = df["trade_date"].astype(str)
    df = df.merge(snap, on=["ts_code", "trade_date"], how="left")

    old_core = df.copy()
    old_core_no_g = old_core[old_core["label_true_breakout"] != "G"].copy()

    # ----- A_high-targeted lightweight refinement -----
    x = old_core_no_g.copy()

    # strengthen Ahigh-positive factors
    trend = _rank01(x["score_trend_axis_single"], True)
    platform_comp = _rank01(x["f_platform_compress_ratio"], True)
    ind_peer = _rank01(x["f_ind_peer_strong_count"], True)
    chip = _rank01(x["score_chip_axis_single"], True)
    base_score = 0.35 * trend + 0.30 * platform_comp + 0.20 * ind_peer + 0.15 * chip

    # downgrade Ahigh-unfriendly terms
    pen_ind = _rank01(x["score_industry_axis_single"], True)
    pen_platform_agg = _rank01(x["score_platform_axis_single"], True)
    pen_chip_winner = _rank01(x["f_chip_winner_rate"], True)
    penalty = 0.08 * pen_ind + 0.05 * pen_platform_agg + 0.04 * pen_chip_winner

    x["ahigh_refine_score"] = base_score - penalty

    # lightweight C firewall (T-day features only)
    q = {}
    for c, p in [
        ("score_trend_axis_single", 0.80),
        ("score_industry_axis_single", 0.80),
        ("f_platform_compress_ratio", 0.40),
        ("score_chip_axis_single", 0.35),
        ("f_platform_compress_ratio_low", 0.25),
    ]:
        col = c if c != "f_platform_compress_ratio_low" else "f_platform_compress_ratio"
        q[c] = pd.to_numeric(x[col], errors="coerce").quantile(p)

    cond_heat = (
        (pd.to_numeric(x["score_trend_axis_single"], errors="coerce") >= q["score_trend_axis_single"])
        & (pd.to_numeric(x["score_industry_axis_single"], errors="coerce") >= q["score_industry_axis_single"])
        & (pd.to_numeric(x["f_platform_compress_ratio"], errors="coerce") <= q["f_platform_compress_ratio"])
    )
    cond_platform_false = pd.to_numeric(x["f_platform_compress_ratio"], errors="coerce") <= q["f_platform_compress_ratio_low"]
    cond_mixed = (
        (pd.to_numeric(x["score_trend_axis_single"], errors="coerce") >= pd.to_numeric(x["score_trend_axis_single"], errors="coerce").quantile(0.70))
        & (
            (pd.to_numeric(x["score_chip_axis_single"], errors="coerce") <= q["score_chip_axis_single"])
            | (pd.to_numeric(x["f_platform_compress_ratio"], errors="coerce") <= q["f_platform_compress_ratio"])
        )
    )

    x["firewall_reason"] = ""
    x.loc[cond_heat, "firewall_reason"] = "industry_heat_firewall"
    x.loc[(x["firewall_reason"] == "") & cond_platform_false, "firewall_reason"] = "platform_integrity_firewall"
    x.loc[(x["firewall_reason"] == "") & cond_mixed, "firewall_reason"] = "mixed_pseudo_firewall"

    # core keep rule: pass firewall + score above median
    score_floor = pd.to_numeric(x["ahigh_refine_score"], errors="coerce").median()
    x["core_keep"] = (x["firewall_reason"] == "") & (pd.to_numeric(x["ahigh_refine_score"], errors="coerce") >= score_floor)

    refined_core = x[x["core_keep"]].copy()

    # ----- outputs -----
    compare_rows = [
        _dist_stats(old_core, "old_selector_core_with_G"),
        _dist_stats(old_core_no_g, "old_selector_core_no_G"),
        _dist_stats(refined_core, "ahigh_refine_core"),
    ]
    compare = pd.DataFrame(compare_rows)
    compare.to_csv(OUT_COMPARE, index=False, encoding="utf-8-sig")

    ret_rows = [
        _ret_stats(old_core, "old_selector_core_with_G"),
        _ret_stats(old_core_no_g, "old_selector_core_no_G"),
        _ret_stats(refined_core, "ahigh_refine_core"),
    ]
    ret_df = pd.DataFrame(ret_rows)
    ret_df.to_csv(OUT_RETURN, index=False, encoding="utf-8-sig")

    g_effect = pd.DataFrame(
        [
            {
                "step": "before_demotion",
                "sample_n": int(len(old_core)),
                "g_n": int((old_core["label_true_breakout"] == "G").sum()),
                "g_share": float((old_core["label_true_breakout"] == "G").mean()),
                "ahigh_share": float(((old_core["label_true_breakout"] == "A") & (old_core["a_quality_layer"] == "A_high")).mean()),
            },
            {
                "step": "after_demotion",
                "sample_n": int(len(old_core_no_g)),
                "g_n": 0,
                "g_share": 0.0,
                "ahigh_share": float(((old_core_no_g["label_true_breakout"] == "A") & (old_core_no_g["a_quality_layer"] == "A_high")).mean()),
            },
        ]
    )
    g_effect.to_csv(OUT_G_EFFECT, index=False, encoding="utf-8-sig")

    c_in = old_core_no_g[old_core_no_g["label_true_breakout"] == "C"]
    c_out = refined_core[refined_core["label_true_breakout"] == "C"]
    c_fire_rows = []
    for r in ["industry_heat_firewall", "platform_integrity_firewall", "mixed_pseudo_firewall"]:
        hit = x[x["firewall_reason"] == r]
        c_hit = hit[hit["label_true_breakout"] == "C"]
        c_fire_rows.append(
            {
                "firewall_reason": r,
                "hit_total_n": int(len(hit)),
                "hit_c_n": int(len(c_hit)),
                "hit_c_share": float(len(c_hit) / len(hit)) if len(hit) else np.nan,
            }
        )
    c_fire_rows.append(
        {
            "firewall_reason": "overall",
            "hit_total_n": int((x["firewall_reason"] != "").sum()),
            "hit_c_n": int((x.loc[x["firewall_reason"] != "", "label_true_breakout"] == "C").sum()),
            "hit_c_share": float((x.loc[x["firewall_reason"] != "", "label_true_breakout"] == "C").mean())
            if int((x["firewall_reason"] != "").sum()) > 0
            else np.nan,
        }
    )
    c_fire = pd.DataFrame(c_fire_rows)
    c_fire["c_share_before"] = float((c_in["label_true_breakout"] == "C").mean()) if len(c_in) else np.nan
    c_fire["c_share_after"] = float((c_out["label_true_breakout"] == "C").mean()) if len(c_out) else np.nan
    c_fire.to_csv(OUT_C_FIREWALL, index=False, encoding="utf-8-sig")

    summary = {
        "goal": "A_high_enrichment",
        "old_core_with_g": compare_rows[0],
        "old_core_no_g": compare_rows[1],
        "ahigh_refine_core": compare_rows[2],
        "return_old_with_g": ret_rows[0],
        "return_old_no_g": ret_rows[1],
        "return_ahigh_refine": ret_rows[2],
        "firewall_hit_n": int((x["firewall_reason"] != "").sum()),
    }
    OUT_SUMMARY.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        "# true_breakout_ahigh_refine_review",
        "",
        "## Objective shift",
        "- old: maximize A share",
        "- new: maximize A_high share, suppress selected_C, demote selected_G",
        "",
        "## Core quality compare",
        compare.to_string(index=False),
        "",
        "## Fixed return lens (T day select -> T+1 open -> T+1/T+2/T+3 close)",
        ret_df.to_string(index=False),
        "",
        "## G demotion effect",
        g_effect.to_string(index=False),
        "",
        "## C firewall effect",
        c_fire.to_string(index=False),
        "",
        "## Verdict",
        "- Check whether A_high share rises and C share falls after refine.",
        "- Keep this as selector-layer validation only (not execution/buy-point strategy).",
    ]
    OUT_REVIEW.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()
