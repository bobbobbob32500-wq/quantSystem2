from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(r"D:\HuaweiAI\quantSystem2")
BASE = ROOT / "data/research/strong_start_full/v4_scan"

IN_MAP = BASE / "true_breakout_mainline_current_mapping.csv"

OUT_R1 = BASE / "true_breakout_limited_rescue_round1_compare.csv"
OUT_R2 = BASE / "true_breakout_limited_rescue_round2_compare.csv"
OUT_DECISION = BASE / "true_breakout_limited_rescue_decision.md"
OUT_SUMMARY = BASE / "true_breakout_limited_rescue_summary.json"

MAIN_FROM = "2025-12-30"
MAIN_TO = "2026-03-30"
CONFIRM_FROM = "2025-09-29"
CONFIRM_TO = "2025-12-29"


def _mask_window(df: pd.DataFrame, dfrom: str, dto: str) -> pd.Series:
    td = pd.to_datetime(df["trade_date"], errors="coerce")
    return (td >= pd.Timestamp(dfrom)) & (td <= pd.Timestamp(dto))


def _ret_stats(s: pd.Series) -> tuple[float, float, float]:
    x = pd.to_numeric(s, errors="coerce")
    if x.empty:
        return np.nan, np.nan, np.nan
    return float(x.mean()), float(x.median()), float((x > 0).mean())


def _metrics(selected_df: pd.DataFrame, denom_df: pd.DataFrame, scenario: str, scope: str) -> dict:
    g = selected_df.copy()
    a_total = int((denom_df["label_class"] == "A").sum())
    ah_total = int((denom_df["label_A_high"] == 1).sum())
    a_sel = int((g["label_class"] == "A").sum())
    ah_sel = int((g["label_A_high"] == 1).sum())
    c_sel = int((g["label_class"] == "C").sum())
    low_sel = int((g["label_A_low"] == 1).sum())

    m2, d2, w2 = _ret_stats(g["ret_t2_close"])
    trade_days = int(denom_df["trade_date"].nunique()) if not denom_df.empty else 0
    signal_days = int(g["trade_date"].nunique()) if len(g) else 0

    return {
        "scope": scope,
        "scenario": scenario,
        "selected_n": int(len(g)),
        "signal_days": signal_days,
        "avg_days_per_signal": float(trade_days / signal_days) if signal_days else np.nan,
        "A_recall_rate": float(a_sel / a_total) if a_total else np.nan,
        "A_high_recall_rate": float(ah_sel / ah_total) if ah_total else np.nan,
        "A_high_over_C": float(ah_sel / c_sel) if c_sel else np.nan,
        "A_low_plus_C_share": float((low_sel + c_sel) / len(g)) if len(g) else np.nan,
        "mean_ret_t2": m2,
        "median_ret_t2": d2,
        "win_t2": w2,
    }


def _build_daily_top1(df_all: pd.DataFrame) -> pd.DataFrame:
    main_col = "in_mainline_s2" if "in_mainline_s2" in df_all.columns else "in_mainline_current"
    d = df_all[df_all[main_col] == True].copy()
    d["_score"] = pd.to_numeric(d["score_total"], errors="coerce")
    out = d.sort_values(["trade_date", "_score"], ascending=[True, False]).groupby("trade_date").head(1).copy()
    return out.drop(columns=["_score"])


def _calc_candidate_metrics(df_all: pd.DataFrame, best: pd.DataFrame, scenario: str, mask: pd.Series) -> list[dict]:
    g = best[mask.fillna(False)].copy()
    rows = [_metrics(g, df_all, scenario, "full_year")]

    mw_g = g[_mask_window(g, MAIN_FROM, MAIN_TO)]
    mw_d = df_all[_mask_window(df_all, MAIN_FROM, MAIN_TO)]
    rows.append(_metrics(mw_g, mw_d, scenario, "main_window"))

    cw_g = g[_mask_window(g, CONFIRM_FROM, CONFIRM_TO)]
    cw_d = df_all[_mask_window(df_all, CONFIRM_FROM, CONFIRM_TO)]
    rows.append(_metrics(cw_g, cw_d, scenario, "confirm_window"))
    return rows


def _round1(df_all: pd.DataFrame, best: pd.DataFrame) -> pd.DataFrame:
    ind = pd.to_numeric(best["score_industry_axis_single"], errors="coerce")
    rs20 = pd.to_numeric(best["f_strength_rs20_xsec_q"], errors="coerce")
    chip = pd.to_numeric(best["f_chip_winner_rate"], errors="coerce")
    score = pd.to_numeric(best["score_total"], errors="coerce")
    plat = pd.to_numeric(best["score_platform_axis_single"], errors="coerce")

    q = {
        "ind50": float(ind.quantile(0.50)),
        "ind55": float(ind.quantile(0.55)),
        "ind60": float(ind.quantile(0.60)),
        "rs30": float(rs20.quantile(0.30)),
        "rs35": float(rs20.quantile(0.35)),
        "rs40": float(rs20.quantile(0.40)),
        "chip50": float(chip.quantile(0.50)),
        "score45": float(score.quantile(0.45)),
        "score50": float(score.quantile(0.50)),
        "plat75": float(plat.quantile(0.75)),
    }

    masks = {
        "R1_baseline_top1": pd.Series(True, index=best.index),
        "R1_ind55_rs30": (ind <= q["ind55"]) & (rs20 >= q["rs30"]),
        "R1_ind60_rs40": (ind <= q["ind60"]) & (rs20 >= q["rs40"]),
        "R1_ind55_rs30_score45": (ind <= q["ind55"]) & (rs20 >= q["rs30"]) & (score >= q["score45"]),
        "R1_ind60_rs35_chip50": (ind <= q["ind60"]) & (rs20 >= q["rs35"]) & (chip >= q["chip50"]),
        "R1_ind55_rs30_plat75": (ind <= q["ind55"]) & (rs20 >= q["rs30"]) & (plat <= q["plat75"]),
        "R1_ind50_score50": (ind <= q["ind50"]) & (score >= q["score50"]),
    }

    rows: list[dict] = []
    for name, m in masks.items():
        rows.extend(_calc_candidate_metrics(df_all, best, name, m))
    r1 = pd.DataFrame(rows)
    r1.to_csv(OUT_R1, index=False, encoding="utf-8-sig")
    return r1


def _pick_round1_best(r1: pd.DataFrame) -> str:
    fy = r1[r1["scope"] == "full_year"].copy()
    # hard floor: frequency must be 2~3.2 days per signal
    fy = fy[(fy["avg_days_per_signal"] >= 2.0) & (fy["avg_days_per_signal"] <= 3.2)].copy()
    if fy.empty:
        return "R1_baseline_top1"
    fy["utility"] = (
        1.4 * fy["win_t2"].fillna(0)
        + 0.6 * fy["A_high_over_C"].replace([np.inf, -np.inf], np.nan).fillna(0)
        - 0.5 * fy["A_low_plus_C_share"].fillna(1)
        + 0.25 * fy["A_high_recall_rate"].fillna(0)
        + 0.2 * fy["mean_ret_t2"].fillna(0)
    )
    return str(fy.sort_values(["utility", "win_t2"], ascending=False).iloc[0]["scenario"])


def _round2(df_all: pd.DataFrame, best: pd.DataFrame, winner_mask: pd.Series, winner_name: str) -> pd.DataFrame:
    # Round2: local refinement around winner (limited two tweaks)
    ind = pd.to_numeric(best["score_industry_axis_single"], errors="coerce")
    rs20 = pd.to_numeric(best["f_strength_rs20_xsec_q"], errors="coerce")
    chip = pd.to_numeric(best["f_chip_winner_rate"], errors="coerce")
    score = pd.to_numeric(best["score_total"], errors="coerce")
    plat = pd.to_numeric(best["score_platform_axis_single"], errors="coerce")

    q_ind60 = float(ind.quantile(0.60))
    q_chip55 = float(chip.quantile(0.55))
    q_score50 = float(score.quantile(0.50))
    q_plat70 = float(plat.quantile(0.70))
    q_rs35 = float(rs20.quantile(0.35))

    masks = {
        f"R2_base_{winner_name}": winner_mask,
        f"R2_{winner_name}_chip55": winner_mask & (chip >= q_chip55),
        f"R2_{winner_name}_score50": winner_mask & (score >= q_score50),
        f"R2_{winner_name}_plat70": winner_mask & (plat <= q_plat70),
        f"R2_{winner_name}_ind60_rs35": winner_mask & (ind <= q_ind60) & (rs20 >= q_rs35),
    }
    rows: list[dict] = []
    for name, m in masks.items():
        rows.extend(_calc_candidate_metrics(df_all, best, name, m))
    r2 = pd.DataFrame(rows)
    r2.to_csv(OUT_R2, index=False, encoding="utf-8-sig")
    return r2


def _pick_round2_best(r2: pd.DataFrame) -> str:
    fy = r2[r2["scope"] == "full_year"].copy()
    fy = fy[(fy["avg_days_per_signal"] >= 2.0) & (fy["avg_days_per_signal"] <= 3.2)].copy()
    if fy.empty:
        return str(r2[r2["scope"] == "full_year"].iloc[0]["scenario"])
    fy["utility"] = (
        1.5 * fy["win_t2"].fillna(0)
        + 0.7 * fy["A_high_over_C"].replace([np.inf, -np.inf], np.nan).fillna(0)
        - 0.6 * fy["A_low_plus_C_share"].fillna(1)
        + 0.2 * fy["A_high_recall_rate"].fillna(0)
        + 0.2 * fy["mean_ret_t2"].fillna(0)
    )
    return str(fy.sort_values(["utility", "win_t2"], ascending=False).iloc[0]["scenario"])


def _final_decision(r2: pd.DataFrame, best_name: str) -> tuple[bool, dict]:
    fy = r2[(r2["scope"] == "full_year") & (r2["scenario"] == best_name)].iloc[0]
    mw = r2[(r2["scope"] == "main_window") & (r2["scenario"] == best_name)].iloc[0]
    cw = r2[(r2["scope"] == "confirm_window") & (r2["scenario"] == best_name)].iloc[0]

    # two-round rescue acceptance floor
    cond_freq = 2.0 <= float(fy["avg_days_per_signal"]) <= 3.2
    cond_quality = float(fy["A_high_over_C"]) >= 0.45 and float(fy["A_low_plus_C_share"]) <= 0.48
    cond_win = float(fy["win_t2"]) >= 0.55
    cond_window = float(mw["win_t2"]) >= 0.50 and float(cw["win_t2"]) >= 0.50
    passed = bool(cond_freq and cond_quality and cond_win and cond_window)
    checks = {
        "cond_freq_2_to_3d": bool(cond_freq),
        "cond_quality": bool(cond_quality),
        "cond_win_t2_ge_55": bool(cond_win),
        "cond_window_no_reverse": bool(cond_window),
        "passed": passed,
    }
    return passed, checks


def main() -> None:
    d_all = pd.read_csv(IN_MAP)
    d_all["trade_date"] = d_all["trade_date"].astype(str)

    best = _build_daily_top1(d_all)

    r1 = _round1(d_all, best)
    winner1 = _pick_round1_best(r1)
    winner1_mask = pd.Series(True, index=best.index) if winner1 == "R1_baseline_top1" else (
        r1[(r1["scope"] == "full_year") & (r1["scenario"] == winner1)].shape[0] > 0
    )
    # rebuild winner mask directly from scenario expression for round2
    # lightweight and explicit
    ind = pd.to_numeric(best["score_industry_axis_single"], errors="coerce")
    rs20 = pd.to_numeric(best["f_strength_rs20_xsec_q"], errors="coerce")
    chip = pd.to_numeric(best["f_chip_winner_rate"], errors="coerce")
    score = pd.to_numeric(best["score_total"], errors="coerce")
    plat = pd.to_numeric(best["score_platform_axis_single"], errors="coerce")
    q_ind50 = float(ind.quantile(0.50))
    q_ind55 = float(ind.quantile(0.55))
    q_ind60 = float(ind.quantile(0.60))
    q_rs30 = float(rs20.quantile(0.30))
    q_rs35 = float(rs20.quantile(0.35))
    q_rs40 = float(rs20.quantile(0.40))
    q_chip50 = float(chip.quantile(0.50))
    q_score45 = float(score.quantile(0.45))
    q_score50 = float(score.quantile(0.50))
    q_plat75 = float(plat.quantile(0.75))
    winner_map = {
        "R1_baseline_top1": pd.Series(True, index=best.index),
        "R1_ind55_rs30": (ind <= q_ind55) & (rs20 >= q_rs30),
        "R1_ind60_rs40": (ind <= q_ind60) & (rs20 >= q_rs40),
        "R1_ind55_rs30_score45": (ind <= q_ind55) & (rs20 >= q_rs30) & (score >= q_score45),
        "R1_ind60_rs35_chip50": (ind <= q_ind60) & (rs20 >= q_rs35) & (chip >= q_chip50),
        "R1_ind55_rs30_plat75": (ind <= q_ind55) & (rs20 >= q_rs30) & (plat <= q_plat75),
        "R1_ind50_score50": (ind <= q_ind50) & (score >= q_score50),
    }
    winner1_mask = winner_map.get(winner1, pd.Series(True, index=best.index))

    r2 = _round2(d_all, best, winner1_mask, winner1)
    winner2 = _pick_round2_best(r2)
    passed, checks = _final_decision(r2, winner2)

    fy = r2[(r2["scope"] == "full_year") & (r2["scenario"] == winner2)].iloc[0]
    mw = r2[(r2["scope"] == "main_window") & (r2["scenario"] == winner2)].iloc[0]
    cw = r2[(r2["scope"] == "confirm_window") & (r2["scenario"] == winner2)].iloc[0]

    decision_lines = [
        "# Limited Rescue Decision (2 rounds)",
        "",
        f"- round1_winner: `{winner1}`",
        f"- round2_winner: `{winner2}`",
        "",
        "## Full-year winner metrics",
        f"- selected_n={int(fy['selected_n'])}, avg_days_per_signal={fy['avg_days_per_signal']:.2f}",
        f"- A_high_recall_rate={fy['A_high_recall_rate']:.2%}, A_high/C={fy['A_high_over_C']:.4f}, A_low+C={fy['A_low_plus_C_share']:.2%}",
        f"- T+2 mean={fy['mean_ret_t2']:.2%}, median={fy['median_ret_t2']:.2%}, win={fy['win_t2']:.2%}",
        "",
        "## Window check",
        f"- main_window win_t2={mw['win_t2']:.2%}",
        f"- confirm_window win_t2={cw['win_t2']:.2%}",
        "",
        "## Hard checks",
        f"- freq(2~3.2d): {checks['cond_freq_2_to_3d']}",
        f"- quality floor: {checks['cond_quality']}",
        f"- win_t2 >= 55%: {checks['cond_win_t2_ge_55']}",
        f"- window non-reverse: {checks['cond_window_no_reverse']}",
        "",
        f"## Final: {'PASS' if passed else 'FAIL'}",
        "- Decision rule: two-round rescue fails => cut this line and do not move to buy-point.",
    ]
    OUT_DECISION.write_text("\n".join(decision_lines), encoding="utf-8")

    payload = {
        "round1_winner": winner1,
        "round2_winner": winner2,
        "checks": checks,
        "final": "PASS" if passed else "FAIL",
        "files": {
            "round1_compare": str(OUT_R1),
            "round2_compare": str(OUT_R2),
            "decision": str(OUT_DECISION),
        },
    }
    OUT_SUMMARY.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print(str(OUT_R1))
    print(str(OUT_R2))
    print(str(OUT_DECISION))
    print(str(OUT_SUMMARY))


if __name__ == "__main__":
    main()

