from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(r"D:\HuaweiAI\quantSystem2")
BASE = ROOT / "data/research/strong_start_full/v4_scan"
SNAPSHOT = BASE / "true_breakout_feature_snapshot_1y.parquet"

OUT_COMPARE = BASE / "true_breakout_selector_v3_fast_coarse_tuning_compare.csv"
OUT_SUMMARY = BASE / "true_breakout_selector_v3_fast_coarse_tuning_summary.json"
OUT_REVIEW = BASE / "true_breakout_selector_v3_fast_coarse_tuning_review.md"
OUT_FREEZE2 = BASE / "true_breakout_selector_v3_freeze_candidate_2.md"
OUT_MONTHLY = BASE / "true_breakout_selector_v3_fast_coarse_tuning_monthly.csv"

MAIN_START = "20251230"
MAIN_END = "20260330"
CONFIRM_START = "20250929"
CONFIRM_END = "20251229"
BASELINE_A_SHARE = 0.3539


@dataclass
class HeatCapConfig:
    name: str
    trend_extreme_q: float
    ind_extreme_q: float
    score_cap: float
    penalty: float


HEAT_CAPS = [
    HeatCapConfig("low", 0.95, 0.95, 0.90, 0.03),
    HeatCapConfig("medium", 0.90, 0.90, 0.85, 0.08),
    HeatCapConfig("high", 0.85, 0.85, 0.80, 0.12),
]


def _rank01(s: pd.Series, higher: bool = True) -> pd.Series:
    x = pd.to_numeric(s, errors="coerce")
    if not higher:
        x = -x
    return x.rank(method="average", pct=True)


def _rank_within_day(mask: pd.Series, score: pd.Series, trade_date: pd.Series) -> pd.Series:
    out = pd.Series(np.nan, index=score.index)
    for d in trade_date[mask].unique():
        idx = trade_date.index[(trade_date == d) & mask]
        out.loc[idx] = score.loc[idx].rank(method="first", ascending=False, pct=True)
    return out


def _build_c_failure_mode(df: pd.DataFrame) -> pd.Series:
    c = df[df["label_true_breakout"] == "C"].copy()
    out = pd.Series(np.nan, index=df.index, dtype=object)
    if c.empty:
        return out
    t66 = c["score_trend_axis_single"].quantile(0.66)
    i66 = c["score_industry_axis_single"].quantile(0.66)
    p33 = c["score_platform_axis_single"].quantile(0.33)
    chip33 = c["score_chip_axis_single"].quantile(0.33)
    ret20_66 = pd.to_numeric(c["f_strength_ret20"], errors="coerce").quantile(0.66)
    chip_stab_25 = pd.to_numeric(c["f_chip_stability_std10"], errors="coerce").quantile(0.25)
    trend_med = c["score_trend_axis_single"].median()

    out.loc[df["label_true_breakout"] == "C"] = "mixed_pseudo_C"
    out.loc[
        (df["label_true_breakout"] == "C")
        & (df["score_industry_axis_single"] >= i66)
        & (df["score_trend_axis_single"] >= t66)
    ] = "industry_heat_C"
    out.loc[
        (out == "mixed_pseudo_C")
        & (pd.to_numeric(df["f_strength_ret20"], errors="coerce") >= ret20_66)
        & (df["score_chip_axis_single"] <= chip33)
    ] = "trend_chase_C"
    out.loc[
        (out == "mixed_pseudo_C")
        & (df["score_platform_axis_single"] <= p33)
        & (df["score_trend_axis_single"] >= trend_med)
    ] = "platform_false_break_C"
    out.loc[
        (out == "mixed_pseudo_C")
        & (pd.to_numeric(df["f_chip_stability_std10"], errors="coerce") <= chip_stab_25)
        & (df["score_trend_axis_single"] >= trend_med)
    ] = "chip_distortion_C"
    return out


def _prepare_window_df(start: str, end: str) -> pd.DataFrame:
    df = pd.read_parquet(SNAPSHOT).copy()
    df["trade_date"] = df["trade_date"].astype(str)
    df = df[
        (df["trade_date"] >= start)
        & (df["trade_date"] <= end)
        & (df["label_true_breakout"].isin(["A", "C"]))
    ].copy()
    # Common axis scores aligned to frozen v3
    df["score_trend_axis_single"] = (
        0.90 * _rank01(df["f_strength_rs20_xsec_q"], True).clip(upper=0.90)
        + 0.10
        * pd.concat(
            [
                _rank01(df["f_strength_ret20"], True),
                _rank01(df["f_strength_rs60_xsec_q"], True),
                _rank01(df["f_trend_close_ma20_gap"], True),
                _rank01(df["f_trend_ma20_ma60_gap"], True),
                _rank01(df["f_trend_ma20_slope5"], True),
            ],
            axis=1,
        ).mean(axis=1)
    )
    df["score_platform_axis_single"] = 0.70 * _rank01(df["f_platform_compress_ratio"], False) + 0.30 * _rank01(df["f_platform_range30"], False)
    df["score_chip_axis_single"] = (
        0.45 * _rank01(df["f_chip_winner_rate"], True)
        + 0.35 * _rank01(df["f_chip_low_position120"], True)
        + 0.20 * _rank01(df["f_chip_stability_std10"], True)
    )
    df["score_industry_axis_single"] = 0.75 * _rank01(df["f_ind_peer_strong_count"], True) + 0.25 * _rank01(df["f_ind_strength_5d"], True)
    df["c_failure_mode"] = _build_c_failure_mode(df)
    return df


def _run_model(
    df: pd.DataFrame,
    quota_a: int,
    quota_b: int,
    cutoff_a: float,
    cutoff_b: float,
    heat_cfg: HeatCapConfig,
    model_name: str,
) -> tuple[dict, pd.DataFrame]:
    d = df.copy()

    pass_a = (
        (pd.to_numeric(d["f_strength_rs20_xsec_q"], errors="coerce") >= 0.72)
        & (pd.to_numeric(d["f_trend_close_ma20_gap"], errors="coerce") >= 0.02)
    )
    a_trend = _rank01(d["f_strength_rs20_xsec_q"], True).clip(upper=0.90)
    a_ind = _rank01(d["f_ind_peer_strong_count"], True)
    a_chip = _rank01(d["f_chip_winner_rate"], True)
    score_a = 0.65 * a_trend + 0.20 * a_ind + 0.15 * a_chip

    heat_res = (a_trend >= heat_cfg.trend_extreme_q) & (a_ind >= heat_cfg.ind_extreme_q)
    score_a = score_a.copy()
    score_a.loc[heat_res] = np.minimum(score_a.loc[heat_res], heat_cfg.score_cap) - heat_cfg.penalty
    rank_a = _rank_within_day(pass_a, score_a, d["trade_date"])

    pass_b = (
        (pd.to_numeric(d["f_strength_rs20_xsec_q"], errors="coerce") >= 0.60)
        & (pd.to_numeric(d["f_trend_close_ma20_gap"], errors="coerce") >= 0.00)
    )
    score_b = 0.50 * d["score_platform_axis_single"] + 0.40 * (
        0.60 * _rank01(d["f_chip_winner_rate"], True) + 0.40 * _rank01(d["f_chip_low_position120"], True)
    ) + 0.10 * _rank01(d["f_strength_rs20_xsec_q"], True)
    rank_b = _rank_within_day(pass_b, score_b, d["trade_date"])

    d["path_a_pass"] = pass_a & (rank_a <= cutoff_a)
    d["path_b_pass"] = pass_b & (rank_b <= cutoff_b)
    d["rank_a"] = rank_a
    d["rank_b"] = rank_b

    d["selected"] = False
    path_a_picks = 0
    path_b_picks = 0
    for day, g in d.groupby("trade_date"):
        idx_a = g.index[d.loc[g.index, "path_a_pass"]]
        idx_b = g.index[d.loc[g.index, "path_b_pass"]]
        pick_a = d.loc[idx_a].sort_values("rank_a", ascending=True).head(quota_a).index
        pick_b = d.loc[idx_b].sort_values("rank_b", ascending=True).head(quota_b).index
        picks = pick_a.union(pick_b)
        d.loc[picks, "selected"] = True
        path_a_picks += len(pick_a)
        path_b_picks += len(pick_b)

    sel = d["selected"]
    n = int(sel.sum())
    a_n = int(((d["label_true_breakout"] == "A") & sel).sum())
    c_n = int(((d["label_true_breakout"] == "C") & sel).sum())
    a_share = (a_n / n) if n else np.nan
    c_share = (c_n / n) if n else np.nan

    mode_rows = []
    c_all = d[d["label_true_breakout"] == "C"]
    c_sel = c_all[c_all["selected"]]
    for mode in ["industry_heat_C", "trend_chase_C", "platform_false_break_C", "chip_distortion_C", "mixed_pseudo_C"]:
        total = int((c_all["c_failure_mode"] == mode).sum())
        sel_n = int((c_sel["c_failure_mode"] == mode).sum())
        mode_rows.append(
            {
                "model": model_name,
                "c_mode": mode,
                "total_c_n": total,
                "selected_c_n": sel_n,
                "selected_rate_in_mode": (sel_n / total) if total else np.nan,
            }
        )

    monthly = (
        d[sel]
        .assign(month=lambda x: x["trade_date"].str.slice(0, 6))
        .groupby("month")
        .apply(lambda g: pd.Series({"sample_n": len(g), "a_n": int((g["label_true_breakout"] == "A").sum()), "a_share": (g["label_true_breakout"] == "A").mean()}))
        .reset_index()
    )
    monthly["model"] = model_name

    summary = {
        "model": model_name,
        "quota_a": quota_a,
        "quota_b": quota_b,
        "cutoff_a": cutoff_a,
        "cutoff_b": cutoff_b,
        "heat_cap": heat_cfg.name,
        "sample_n": n,
        "a_n": a_n,
        "c_n": c_n,
        "a_share": a_share,
        "c_share": c_share,
        "above_baseline": bool(pd.notna(a_share) and a_share > BASELINE_A_SHARE),
        "a_share_lift_vs_baseline_pts": (a_share - BASELINE_A_SHARE) if pd.notna(a_share) else np.nan,
        "path_a_picks": int(path_a_picks),
        "path_b_picks": int(path_b_picks),
        "path_a_share_in_output": (path_a_picks / (path_a_picks + path_b_picks)) if (path_a_picks + path_b_picks) else np.nan,
        "path_b_share_in_output": (path_b_picks / (path_a_picks + path_b_picks)) if (path_a_picks + path_b_picks) else np.nan,
        "monthly_a_share_std": monthly["a_share"].std(ddof=0) if len(monthly) else np.nan,
    }
    c_mode_df = pd.DataFrame(mode_rows)
    return summary, monthly, c_mode_df


def _pick_best_stage_a(rows: list[dict]) -> dict:
    df = pd.DataFrame(rows)
    # primary: A-share, secondary: sample size, tertiary: lower monthly std
    df = df.sort_values(
        by=["a_share", "sample_n", "monthly_a_share_std"],
        ascending=[False, False, True],
    )
    return df.iloc[0].to_dict()


def _pick_best_stage_b(rows: list[dict]) -> dict:
    df = pd.DataFrame(rows)
    df = df.sort_values(
        by=["a_share", "sample_n", "monthly_a_share_std"],
        ascending=[False, False, True],
    )
    return df.iloc[0].to_dict()


def main() -> None:
    df_main = _prepare_window_df(MAIN_START, MAIN_END)
    all_rows: list[dict] = []
    all_monthly: list[pd.DataFrame] = []
    all_cmode: list[pd.DataFrame] = []

    # Stage A: quota + heat (cutoff fixed at frozen default 0.15/0.15)
    stage_a_rows: list[dict] = []
    for qa, qb in [(2, 2), (2, 1), (1, 2)]:
        for h in HEAT_CAPS:
            name = f"stageA_q{qa}{qb}_h{h.name}"
            s, m, cdf = _run_model(df_main, qa, qb, 0.15, 0.15, h, name)
            s["stage"] = "A"
            stage_a_rows.append(s)
            all_rows.append(s)
            all_monthly.append(m)
            all_cmode.append(cdf)

    winner_a = _pick_best_stage_a(stage_a_rows)
    win_qa = int(winner_a["quota_a"])
    win_qb = int(winner_a["quota_b"])
    win_heat = str(winner_a["heat_cap"])
    heat_cfg = next(x for x in HEAT_CAPS if x.name == win_heat)

    # Stage B: cutoff refinement on winner quota+heat, heuristic reduced combos (A:10/20/30, B:20/30)
    stage_b_rows: list[dict] = []
    for ca in [0.10, 0.20, 0.30]:
        for cb in [0.20, 0.30]:
            name = f"stageB_q{win_qa}{win_qb}_h{win_heat}_a{int(ca*100)}_b{int(cb*100)}"
            s, m, cdf = _run_model(df_main, win_qa, win_qb, ca, cb, heat_cfg, name)
            s["stage"] = "B"
            stage_b_rows.append(s)
            all_rows.append(s)
            all_monthly.append(m)
            all_cmode.append(cdf)

    winner_b = _pick_best_stage_b(stage_b_rows)

    # Quick confirm: only final winner in adjacent non-overlap window
    df_confirm = _prepare_window_df(CONFIRM_START, CONFIRM_END)
    qa = int(winner_b["quota_a"])
    qb = int(winner_b["quota_b"])
    ca = float(winner_b["cutoff_a"])
    cb = float(winner_b["cutoff_b"])
    hname = str(winner_b["heat_cap"])
    hcfg = next(x for x in HEAT_CAPS if x.name == hname)
    confirm_name = f"confirm_q{qa}{qb}_h{hname}_a{int(ca*100)}_b{int(cb*100)}"
    s_confirm, m_confirm, c_confirm = _run_model(df_confirm, qa, qb, ca, cb, hcfg, confirm_name)
    s_confirm["stage"] = "CONFIRM"
    all_rows.append(s_confirm)
    all_monthly.append(m_confirm)
    all_cmode.append(c_confirm)

    compare = pd.DataFrame(all_rows)
    compare.to_csv(OUT_COMPARE, index=False, encoding="utf-8-sig")

    monthly = pd.concat(all_monthly, ignore_index=True) if all_monthly else pd.DataFrame()
    if not monthly.empty:
        monthly.to_csv(OUT_MONTHLY, index=False, encoding="utf-8-sig")

    c_mode = pd.concat(all_cmode, ignore_index=True) if all_cmode else pd.DataFrame()
    c_mode_path = BASE / "true_breakout_selector_v3_fast_coarse_tuning_cmode.csv"
    if not c_mode.empty:
        c_mode.to_csv(c_mode_path, index=False, encoding="utf-8-sig")

    summary = {
        "baseline_a_share": BASELINE_A_SHARE,
        "main_window": {"start": MAIN_START, "end": MAIN_END},
        "confirm_window": {"start": CONFIRM_START, "end": CONFIRM_END},
        "stage_a_best": winner_a,
        "stage_b_best": winner_b,
        "confirm_result": s_confirm,
        "final_winner": {
            "quota_a": qa,
            "quota_b": qb,
            "heat_cap": hname,
            "cutoff_a": ca,
            "cutoff_b": cb,
            "main_a_share": float(winner_b["a_share"]),
            "main_sample_n": int(winner_b["sample_n"]),
            "main_path_a_picks": int(winner_b["path_a_picks"]),
            "main_path_b_picks": int(winner_b["path_b_picks"]),
            "confirm_a_share": float(s_confirm["a_share"]) if pd.notna(s_confirm["a_share"]) else None,
            "confirm_sample_n": int(s_confirm["sample_n"]),
        },
    }
    OUT_SUMMARY.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    review = [
        "# true_breakout_selector_v3_fast_coarse_tuning_review",
        "",
        "## Stage A (quota + heat-cap, fixed cutoff A/B=15%)",
        f"- Best: quota {win_qa}:{win_qb}, heat-cap `{win_heat}`",
        f"- A-share: {winner_a['a_share']:.4f} (baseline {BASELINE_A_SHARE:.4f})",
        f"- Sample n: {int(winner_a['sample_n'])}",
        "",
        "## Stage B (cutoff refine on Stage-A winner)",
        f"- Best cutoff: PathA {int(float(winner_b['cutoff_a'])*100)}%, PathB {int(float(winner_b['cutoff_b'])*100)}%",
        f"- A-share: {winner_b['a_share']:.4f}",
        f"- Sample n: {int(winner_b['sample_n'])}",
        f"- Path contribution A/B: {int(winner_b['path_a_picks'])}/{int(winner_b['path_b_picks'])}",
        "",
        "## Quick confirm (adjacent non-overlap window)",
        f"- Window: {CONFIRM_START} ~ {CONFIRM_END}",
        f"- A-share: {s_confirm['a_share']:.4f}" if pd.notna(s_confirm["a_share"]) else "- A-share: NaN",
        f"- Sample n: {int(s_confirm['sample_n'])}",
        "",
        "## Final candidate",
        f"- quota: {qa}:{qb}",
        f"- heat-cap: {hname}",
        f"- cutoff A/B: {int(ca*100)}% / {int(cb*100)}%",
    ]
    OUT_REVIEW.write_text("\n".join(review), encoding="utf-8")

    freeze2 = [
        "# true_breakout_selector_v3_freeze_candidate_2",
        "",
        "## Positioning",
        "- Coarse-parameter candidate on frozen v3 structure (no structure change).",
        "",
        "## Fixed structure",
        "- Dual-path remains unchanged.",
        "- Output mechanism remains `M1_quota_merge`.",
        "",
        "## Coarse parameters (winner)",
        f"- quota_a: {qa}",
        f"- quota_b: {qb}",
        f"- heat_cap: {hname}",
        f"- path_a_cutoff_pct: {int(ca*100)}",
        f"- path_b_cutoff_pct: {int(cb*100)}",
        "",
        "## Validation snapshot",
        f"- Main window A-share: {winner_b['a_share']:.4f}",
        f"- Main window sample n: {int(winner_b['sample_n'])}",
        f"- Baseline A-share: {BASELINE_A_SHARE:.4f}",
        f"- Confirm window A-share: {s_confirm['a_share']:.4f}" if pd.notna(s_confirm["a_share"]) else "- Confirm window A-share: NaN",
        f"- Confirm window sample n: {int(s_confirm['sample_n'])}",
        "",
        "## Scope boundary",
        "- This file freezes only coarse selector parameters.",
        "- It does NOT include buy-point/sell-point/execution/backtest optimization.",
    ]
    OUT_FREEZE2.write_text("\n".join(freeze2), encoding="utf-8")


if __name__ == "__main__":
    main()
