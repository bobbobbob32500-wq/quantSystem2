from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

import run_true_breakout_buy_signal_v1 as v1
import run_true_breakout_buy_signal_v1_1 as v11
from run_ech2_scope_expansion_fast_review import apply_q2_gate, build_ech2_mask
from run_true_breakout_core_pool_recall_rebuild import CoreConfig, add_quality_labels, load_universe, run_selector_core


ROOT = Path(r"D:\HuaweiAI\quantSystem2")
BASE = ROOT / "data/research/strong_start_full/v4_scan"

OUT_MAINLINE_MAP = BASE / "true_breakout_mainline_current_mapping.csv"
OUT_STAGEA = BASE / "true_breakout_stageA_metrics.csv"
OUT_STAGEB_COMPARE = BASE / "true_breakout_stageB_quality_gate_compare.csv"
OUT_STAGEB_CONSTRAINT = BASE / "true_breakout_stageB_constraints_check.csv"
OUT_PROD_POOL = BASE / "true_breakout_production_input_pool_v1.csv"
OUT_BUY_BASE = BASE / "true_breakout_buy_signal_baseline_v2.csv"
OUT_BUY_PROD = BASE / "true_breakout_buy_signal_prod_v2.csv"
OUT_BUY_COMPARE = BASE / "true_breakout_buy_signal_v2_compare.csv"
OUT_REVIEW = BASE / "true_breakout_acceleration_execution_review.md"
OUT_SUMMARY = BASE / "true_breakout_acceleration_execution_summary.json"

MAIN_FROM = "2025-12-30"
MAIN_TO = "2026-03-30"
CONFIRM_FROM = "2025-09-29"
CONFIRM_TO = "2025-12-29"


@dataclass
class StageBGateConfig:
    name: str
    apply_industry_cap: bool
    apply_rs20_floor: bool


def _window_mask(df: pd.DataFrame, dfrom: str, dto: str) -> pd.Series:
    td = pd.to_datetime(df["trade_date"], errors="coerce")
    return (td >= pd.Timestamp(dfrom)) & (td <= pd.Timestamp(dto))


def _ret_stats(s: pd.Series) -> tuple[float, float, float]:
    x = pd.to_numeric(s, errors="coerce")
    if x.empty:
        return np.nan, np.nan, np.nan
    return float(x.mean()), float(x.median()), float((x > 0).mean())


def _scope_metrics(df_scope: pd.DataFrame, selected_mask: pd.Series, scenario: str, scope: str) -> dict:
    g = df_scope[selected_mask].copy()
    a_total = int((df_scope["label_class"] == "A").sum())
    ah_total = int((df_scope["label_A_high"] == 1).sum())
    a_sel = int((g["label_class"] == "A").sum())
    ah_sel = int((g["label_A_high"] == 1).sum())
    c_sel = int((g["label_class"] == "C").sum())
    low_sel = int((g["label_A_low"] == 1).sum())
    t2m, t2d, t2w = _ret_stats(g["ret_t2_close"])

    trade_days = int(df_scope["trade_date"].nunique())
    signal_days = int(g["trade_date"].nunique()) if len(g) else 0
    blank_days = trade_days - signal_days
    return {
        "scope": scope,
        "scenario": scenario,
        "selected_n": int(len(g)),
        "A_recall_rate": float(a_sel / a_total) if a_total else np.nan,
        "A_high_recall_rate": float(ah_sel / ah_total) if ah_total else np.nan,
        "A_high_over_C": float(ah_sel / c_sel) if c_sel else np.nan,
        "A_low_plus_C_share": float((low_sel + c_sel) / len(g)) if len(g) else np.nan,
        "mean_ret_t2": t2m,
        "median_ret_t2": t2d,
        "win_t2": t2w,
        "signal_days": signal_days,
        "trade_days": trade_days,
        "blank_days": blank_days,
        "blank_day_ratio": float(blank_days / trade_days) if trade_days else np.nan,
        "avg_days_per_signal": float(trade_days / signal_days) if signal_days else np.nan,
    }


def _build_mainline_current() -> pd.DataFrame:
    base = load_universe()
    d = add_quality_labels(base)

    cfg_c2a = CoreConfig(
        name="C2A",
        note="frozen baseline",
        quota_a=2,
        quota_b=3,
        cutoff_a=0.20,
        cutoff_b=0.20,
        path_a_rs20_min=0.72,
        path_a_trend_min=0.02,
        path_b_rs20_min=0.60,
        path_b_trend_min=0.00,
    )
    d = run_selector_core(d, cfg_c2a)
    d["in_C2A"] = d["in_core_pool"].eq(1)

    # S2 scope: relaxed platform floor + relaxed compression ceiling
    plat_all = pd.to_numeric(d["score_platform_axis_single"], errors="coerce")
    comp_all = pd.to_numeric(d["f_platform_compress_ratio"], errors="coerce")
    chip_all = pd.to_numeric(d["f_chip_winner_rate"], errors="coerce")
    ind_all = pd.to_numeric(d["score_industry_axis_single"], errors="coerce")
    score_all = pd.to_numeric(d["score_total"], errors="coerce")

    q_plat_55 = float(plat_all.quantile(0.55))
    q_comp_55 = float(comp_all.quantile(0.55))
    q_chip_50 = float(chip_all.quantile(0.50))
    q_ind_55 = float(ind_all.quantile(0.55))
    q_score_60 = float(score_all.quantile(0.60))

    ech2_s2_base = build_ech2_mask(
        d,
        plat_floor=q_plat_55,
        comp_ceiling=q_comp_55,
        q_ind_55=q_ind_55,
        q_chip_50=q_chip_50,
        q_score_60=q_score_60,
    )
    in_ech2_s2 = apply_q2_gate(d, d["in_C2A"], ech2_s2_base)

    d["in_ech2_s2_base"] = ech2_s2_base
    d["in_ech2_s2"] = in_ech2_s2
    d["in_mainline_current"] = d["in_C2A"] | d["in_ech2_s2"]
    d["mainline_channel"] = np.where(d["in_C2A"], "main_channel", np.where(d["in_ech2_s2"], "early_channel", "none"))

    # stable stock identifiers for downstream
    d["stock_code"] = d["ts_code"].astype(str)
    d["stock_name"] = d["name"].astype(str)
    return d


def _export_stagea_mapping(d: pd.DataFrame) -> None:
    cols = [
        "trade_date",
        "stock_code",
        "stock_name",
        "ts_code",
        "label_class",
        "label_A_high",
        "label_A_mid",
        "label_A_low",
        "label_C",
        "label_G",
        "path_source",
        "in_C2A",
        "in_ech2_s2",
        "in_mainline_current",
        "mainline_channel",
        "score_total",
        "score_platform_axis_single",
        "score_industry_axis_single",
        "f_chip_winner_rate",
        "f_platform_compress_ratio",
        "f_strength_rs20_xsec_q",
        "rank_global_after_merge",
        "ret_t1_close",
        "ret_t2_close",
        "ret_t3_close",
    ]
    out = d.copy()
    for c in cols:
        if c not in out.columns:
            out[c] = pd.NA
    out[cols].to_csv(OUT_MAINLINE_MAP, index=False, encoding="utf-8-sig")


def _run_stagea_metrics(d: pd.DataFrame) -> pd.DataFrame:
    rows = []
    rows.append(_scope_metrics(d, d["in_mainline_current"], "mainline_current", "full_year"))

    main_mask = _window_mask(d, MAIN_FROM, MAIN_TO)
    confirm_mask = _window_mask(d, CONFIRM_FROM, CONFIRM_TO)

    rows.append(_scope_metrics(d[main_mask], d.loc[main_mask, "in_mainline_current"], "mainline_current", "main_window"))
    rows.append(
        _scope_metrics(
            d[confirm_mask],
            d.loc[confirm_mask, "in_mainline_current"],
            "mainline_current",
            "confirm_window",
        )
    )
    df = pd.DataFrame(rows)
    df.to_csv(OUT_STAGEA, index=False, encoding="utf-8-sig")
    return df


def _apply_stageb_gate(d: pd.DataFrame, cfg: StageBGateConfig) -> pd.Series:
    mask = d["in_mainline_current"].copy()
    increment = d["in_ech2_s2"] & (~d["in_C2A"])
    if not increment.any():
        return mask

    inc_df = d[increment].copy()
    q_ind_75 = float(pd.to_numeric(inc_df["score_industry_axis_single"], errors="coerce").quantile(0.75))
    q_rs20_40 = float(pd.to_numeric(inc_df["f_strength_rs20_xsec_q"], errors="coerce").quantile(0.40))

    gate = pd.Series(True, index=d.index)
    if cfg.apply_industry_cap:
        gate &= pd.to_numeric(d["score_industry_axis_single"], errors="coerce") <= q_ind_75
    if cfg.apply_rs20_floor:
        gate &= pd.to_numeric(d["f_strength_rs20_xsec_q"], errors="coerce") >= q_rs20_40

    # C2A stays always in; gate only applied to ECH2 increment
    selected = d["in_C2A"] | (increment & gate)
    return selected


def _run_stageb(d: pd.DataFrame) -> tuple[pd.DataFrame, pd.Series, str]:
    candidates = [
        StageBGateConfig(name="G0_no_extra_gate", apply_industry_cap=False, apply_rs20_floor=False),
        StageBGateConfig(name="G1_industry_cap", apply_industry_cap=True, apply_rs20_floor=False),
        StageBGateConfig(name="G2_industry_cap_rs20_floor", apply_industry_cap=True, apply_rs20_floor=True),
    ]

    rows = []
    masks: dict[str, pd.Series] = {}
    for c in candidates:
        m = _apply_stageb_gate(d, c)
        masks[c.name] = m
        rows.append(_scope_metrics(d, m, c.name, "full_year"))
        main_mask = _window_mask(d, MAIN_FROM, MAIN_TO)
        rows.append(_scope_metrics(d[main_mask], m.loc[main_mask], c.name, "main_window"))
        confirm_mask = _window_mask(d, CONFIRM_FROM, CONFIRM_TO)
        rows.append(_scope_metrics(d[confirm_mask], m.loc[confirm_mask], c.name, "confirm_window"))

    cmp_df = pd.DataFrame(rows)
    cmp_df.to_csv(OUT_STAGEB_COMPARE, index=False, encoding="utf-8-sig")

    # baseline for constraint comparison
    base = cmp_df[(cmp_df["scope"] == "full_year") & (cmp_df["scenario"] == "G0_no_extra_gate")].iloc[0]
    checks = []
    best_score = -1e9
    best_name = "G0_no_extra_gate"
    for c in candidates:
        r = cmp_df[(cmp_df["scope"] == "full_year") & (cmp_df["scenario"] == c.name)].iloc[0]
        quality_ok = (
            (r["A_high_over_C"] >= float(base["A_high_over_C"]) - 0.015)
            and (r["A_low_plus_C_share"] <= float(base["A_low_plus_C_share"]) + 0.015)
            and (r["win_t2"] >= float(base["win_t2"]) - 0.01)
        )
        frequency_ok = pd.notna(r["avg_days_per_signal"]) and float(r["avg_days_per_signal"]) <= 3.0
        # utility: recall first, then quality/frequency stability
        score = (
            4.0 * float(r["A_high_recall_rate"])
            + 1.0 * float(r["A_high_over_C"])
            - 1.2 * float(r["A_low_plus_C_share"])
            + 0.6 * float(r["win_t2"])
            + 0.2 * (1.0 / float(r["avg_days_per_signal"])) if pd.notna(r["avg_days_per_signal"]) and float(r["avg_days_per_signal"]) > 0 else 0.0
        )
        if quality_ok and frequency_ok:
            score += 0.5
        if score > best_score:
            best_score = score
            best_name = c.name
        checks.append(
            {
                "scenario": c.name,
                "quality_ok": bool(quality_ok),
                "frequency_ok_avg_days_le_3": bool(frequency_ok),
                "utility_score": float(score),
            }
        )
    check_df = pd.DataFrame(checks)
    check_df.to_csv(OUT_STAGEB_CONSTRAINT, index=False, encoding="utf-8-sig")
    return cmp_df, masks[best_name], best_name


def _build_production_pool_v1(d: pd.DataFrame, selected_mask: pd.Series) -> pd.DataFrame:
    sel = d[selected_mask].copy()
    sel["input_tier"] = np.where(sel["in_C2A"], "main_channel", "early_channel")

    # one-stock-per-day production pick (highest score_total)
    picks = []
    for td, g in sel.groupby("trade_date"):
        gg = g.copy()
        gg["_score"] = pd.to_numeric(gg["score_total"], errors="coerce")
        pick = gg.sort_values("_score", ascending=False).head(1)
        picks.append(pick)
    pool = pd.concat(picks, ignore_index=True) if picks else sel.head(0).copy()
    pool = pool.drop(columns=[c for c in ["_score"] if c in pool.columns])

    cols = [
        "trade_date",
        "stock_code",
        "stock_name",
        "ts_code",
        "input_tier",
        "path_source",
        "in_C2A",
        "in_ech2_s2",
        "in_mainline_current",
        "score_total",
        "score_platform_axis_single",
        "score_industry_axis_single",
        "f_chip_winner_rate",
        "f_platform_compress_ratio",
        "f_strength_rs20_xsec_q",
        "rank_global_after_merge",
        "label_A_high",
        "label_A_mid",
        "label_A_low",
        "label_C",
        "label_G",
        "ret_t1_close",
        "ret_t2_close",
        "ret_t3_close",
    ]
    for c in cols:
        if c not in pool.columns:
            pool[c] = pd.NA
    pool = pool[cols].copy()
    pool.to_csv(OUT_PROD_POOL, index=False, encoding="utf-8-sig")
    return pool


def _non_trigger_row(row: pd.Series, reason: str) -> dict:
    return {
        "trade_date": str(row.get("trade_date", "")),
        "stock_code": str(row.get("stock_code", "")),
        "stock_name": row.get("stock_name", ""),
        "signal_triggered": 0,
        "signal_type": "",
        "signal_time": "",
        "signal_price": np.nan,
        "signal_reason": "",
        "non_trigger_reason": reason,
    }


def _prep_signal_candidates(row: pd.Series, intraday_df: pd.DataFrame, cfg_v11: v11.SignalConfigV11) -> tuple[pd.DataFrame, list[dict]]:
    d = v1._prep_intraday(intraday_df)
    if d.empty or len(d) < cfg_v11.min_bars_required:
        return d, []
    path_source = str(row.get("path_source", "A"))
    sig_pull = v1._detect_pullback(d, cfg_v11)
    sig_break = v11._detect_breakout_pathaware(d, cfg_v11, path_source)
    sig_range = v11._detect_range_break_pathaware(d, cfg_v11, path_source)
    cands = [x for x in [sig_pull, sig_break, sig_range] if x is not None]
    return d, cands


def _pick_by_priority(cands: list[dict], priority: dict[str, int]) -> Optional[dict]:
    if not cands:
        return None
    ranked = sorted(cands, key=lambda x: (x["trigger_idx"], priority.get(x["signal_type"], 99)))
    return ranked[0]


def _early_gate(candidate: dict, d: pd.DataFrame, row: pd.Series) -> tuple[bool, str]:
    idx = int(candidate["trigger_idx"])
    signal_type = str(candidate["signal_type"])
    score_total = float(pd.to_numeric(row.get("score_total", np.nan), errors="coerce"))
    rank_global = float(pd.to_numeric(row.get("rank_global_after_merge", np.nan), errors="coerce"))
    vol_ratio = float(pd.to_numeric(d.at[idx, "vol_ratio_20"], errors="coerce")) if idx < len(d) else np.nan
    chg = float(pd.to_numeric(d.at[idx, "chg_from_open"], errors="coerce")) if idx < len(d) else np.nan

    if not pd.isna(rank_global) and rank_global > 5:
        return False, "early_gate_rank_gt_5"
    if not pd.isna(score_total) and score_total < 0.80:
        return False, "early_gate_score_lt_0.80"
    if signal_type == "range_break_confirm":
        return False, "early_gate_disable_range"
    if signal_type == "breakout_confirm":
        if pd.isna(vol_ratio) or vol_ratio < 1.25:
            return False, "early_gate_breakout_vol_lt_1.25"
        if pd.isna(chg) or chg > 0.07:
            return False, "early_gate_breakout_chg_gt_0.07"
    return True, "early_gate_pass"


def _detect_baseline(row: pd.Series, intraday_df: pd.DataFrame, cfg_v11: v11.SignalConfigV11) -> dict:
    # unified baseline uses existing v1.1 logic
    return v11.detect_buy_signal_v1_1(row, intraday_df, cfg_v11)


def _detect_prod_v2(row: pd.Series, intraday_df: pd.DataFrame, cfg_v11: v11.SignalConfigV11) -> dict:
    if intraday_df.empty:
        return _non_trigger_row(row, "missing_intraday_data")
    d, cands = _prep_signal_candidates(row, intraday_df, cfg_v11)
    if d.empty or len(d) < cfg_v11.min_bars_required:
        return _non_trigger_row(row, "insufficient_intraday_bars")
    if not cands:
        return _non_trigger_row(row, "no_prod_v2_pattern_triggered")

    tier = str(row.get("input_tier", "main_channel"))
    if tier == "main_channel":
        # F3-like aggressive routing
        priority = {"breakout_confirm": 1, "range_break_confirm": 2, "pullback_confirm": 3}
        pick = _pick_by_priority(cands, priority)
        if pick is None:
            return _non_trigger_row(row, "main_channel_no_pick")
        return {
            "trade_date": str(row.get("trade_date", "")),
            "stock_code": str(row.get("stock_code", "")),
            "stock_name": row.get("stock_name", ""),
            "signal_triggered": 1,
            "signal_type": pick["signal_type"],
            "signal_time": pd.Timestamp(pick["trigger_time"]).strftime("%Y-%m-%d %H:%M:%S"),
            "signal_price": float(pick["trigger_price"]),
            "signal_reason": f"prod_v2_main::{pick['reason']}",
            "non_trigger_reason": "",
        }

    # early_channel: conservative gate
    priority = {"pullback_confirm": 1, "breakout_confirm": 2, "range_break_confirm": 3}
    ranked = sorted(cands, key=lambda x: (x["trigger_idx"], priority.get(x["signal_type"], 99)))
    reasons: list[str] = []
    for cand in ranked:
        ok, reason = _early_gate(cand, d, row)
        if ok:
            return {
                "trade_date": str(row.get("trade_date", "")),
                "stock_code": str(row.get("stock_code", "")),
                "stock_name": row.get("stock_name", ""),
                "signal_triggered": 1,
                "signal_type": cand["signal_type"],
                "signal_time": pd.Timestamp(cand["trigger_time"]).strftime("%Y-%m-%d %H:%M:%S"),
                "signal_price": float(cand["trigger_price"]),
                "signal_reason": f"prod_v2_early::{cand['reason']}::{reason}",
                "non_trigger_reason": "",
            }
        reasons.append(reason)
    return _non_trigger_row(row, "early_channel_blocked::" + "|".join(dict.fromkeys(reasons)))


def _run_buy_signal(pool: pd.DataFrame, mode: str) -> pd.DataFrame:
    cfg_v11 = v11.SignalConfigV11()
    nxt = v1._load_next_trade_date().rename(columns={"ts_code": "stock_code"})
    p = pool.copy()
    p = p.merge(nxt, on=["stock_code", "trade_date"], how="left")
    p["buy_date"] = p["buy_date"].astype(str)

    rows = []
    for r in p.itertuples(index=False):
        row = pd.Series(r._asdict())
        intraday = v1._load_intraday(str(row.get("stock_code", "")), str(row.get("trade_date", "")))
        sig = _detect_baseline(row, intraday, cfg_v11) if mode == "baseline" else _detect_prod_v2(row, intraday, cfg_v11)
        rows.append({**row.to_dict(), **sig})
    return pd.DataFrame(rows)


def _buy_summary(df: pd.DataFrame, version: str) -> pd.DataFrame:
    groups = {
        "all": df.index == df.index,
        "main_channel": df["input_tier"] == "main_channel",
        "early_channel": df["input_tier"] == "early_channel",
    }
    rows = []
    for gname, mask in groups.items():
        g = df[mask].copy()
        trig = g[g["signal_triggered"] == 1].copy()
        row: dict[str, int | float | str] = {
            "version": version,
            "group": gname,
            "sample_n": int(len(g)),
            "trigger_n": int(len(trig)),
            "trigger_rate": float(len(trig) / len(g)) if len(g) else np.nan,
            "pullback_confirm_n": int((trig["signal_type"] == "pullback_confirm").sum()) if len(trig) else 0,
            "breakout_confirm_n": int((trig["signal_type"] == "breakout_confirm").sum()) if len(trig) else 0,
            "range_break_confirm_n": int((trig["signal_type"] == "range_break_confirm").sum()) if len(trig) else 0,
        }
        for h in ["t1", "t2", "t3"]:
            s = pd.to_numeric(trig[f"ret_{h}_close"], errors="coerce")
            row[f"mean_ret_{h}"] = float(s.mean()) if len(s) else np.nan
            row[f"median_ret_{h}"] = float(s.median()) if len(s) else np.nan
            row[f"win_{h}"] = float((s > 0).mean()) if len(s) else np.nan
        rows.append(row)
    return pd.DataFrame(rows)


def _compare_buy(base_sum: pd.DataFrame, prod_sum: pd.DataFrame) -> pd.DataFrame:
    b = base_sum.set_index("group")
    p = prod_sum.set_index("group")
    rows = []
    for g in sorted(set(b.index.tolist()) | set(p.index.tolist())):
        row: dict[str, float | str] = {"group": g}
        for col in [c for c in b.columns if c not in ("version",)]:
            bv = b.at[g, col] if g in b.index and col in b.columns else np.nan
            pv = p.at[g, col] if g in p.index and col in p.columns else np.nan
            row[f"baseline_{col}"] = bv
            row[f"prod_v2_{col}"] = pv
            try:
                row[f"delta_{col}"] = float(pv) - float(bv)
            except Exception:
                row[f"delta_{col}"] = np.nan
        rows.append(row)
    return pd.DataFrame(rows)


def _write_review(stagea: pd.DataFrame, stageb: pd.DataFrame, checks: pd.DataFrame, best_gate: str, buy_cmp: pd.DataFrame) -> None:
    fy_a = stagea[stagea["scope"] == "full_year"].iloc[0]
    fy_b = stageb[(stageb["scope"] == "full_year") & (stageb["scenario"] == best_gate)].iloc[0]
    buy_all = buy_cmp[buy_cmp["group"] == "all"].iloc[0] if not buy_cmp[buy_cmp["group"] == "all"].empty else None

    lines = [
        "# True Breakout Acceleration Execution (A/B/C)",
        "",
        "## Stage A - Mainline fixed",
        "- mainline_current fixed to: C2A + ECH2_S2",
        f"- full_year A_high_recall_rate={fy_a['A_high_recall_rate']:.2%}, A_high/C={fy_a['A_high_over_C']:.4f}, win_t2={fy_a['win_t2']:.2%}",
        "",
        "## Stage B - Quality gate + production constraints",
        f"- selected gate scenario: {best_gate}",
        f"- full_year A_high_recall_rate={fy_b['A_high_recall_rate']:.2%}, A_high/C={fy_b['A_high_over_C']:.4f}, "
        f"A_low+C={fy_b['A_low_plus_C_share']:.2%}, avg_days_per_signal={fy_b['avg_days_per_signal']:.2f}",
        "",
        "## Stage C - Buy signal baseline vs prod_v2",
    ]
    if buy_all is not None:
        lines.append(
            f"- all win_t2: baseline={buy_all['baseline_win_t2']:.2%} -> prod_v2={buy_all['prod_v2_win_t2']:.2%} "
            f"(delta={buy_all['delta_win_t2']:+.2%})"
        )
        lines.append(
            f"- all trigger_rate: baseline={buy_all['baseline_trigger_rate']:.2%} -> prod_v2={buy_all['prod_v2_trigger_rate']:.2%}"
        )
    lines.extend(
        [
            "",
            "## Decision gates",
            "- Keep recall-first order: yes",
            "- Frequency floor target (>= one signal every 2-3 trading days): tracked in stageB constraints",
            "- Buypoint stage should start only after two consecutive selector rounds pass quality+frequency constraints",
        ]
    )
    OUT_REVIEW.write_text("\n".join(lines), encoding="utf-8")

    payload = {
        "stageA_full_year": fy_a.to_dict(),
        "stageB_best_gate": best_gate,
        "stageB_constraints": checks.to_dict("records"),
        "stageB_full_year_best": fy_b.to_dict(),
        "buy_compare_all": buy_all.to_dict() if buy_all is not None else {},
        "outputs": {
            "mapping": str(OUT_MAINLINE_MAP),
            "stageA_metrics": str(OUT_STAGEA),
            "stageB_compare": str(OUT_STAGEB_COMPARE),
            "stageB_constraints": str(OUT_STAGEB_CONSTRAINT),
            "production_pool_v1": str(OUT_PROD_POOL),
            "buy_baseline_v2": str(OUT_BUY_BASE),
            "buy_prod_v2": str(OUT_BUY_PROD),
            "buy_compare": str(OUT_BUY_COMPARE),
            "review": str(OUT_REVIEW),
        },
    }
    OUT_SUMMARY.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    # Stage A
    d = _build_mainline_current()
    _export_stagea_mapping(d)
    stagea_df = _run_stagea_metrics(d)

    # Stage B
    stageb_cmp, stageb_best_mask, best_gate = _run_stageb(d)
    prod_pool = _build_production_pool_v1(d, stageb_best_mask)

    # Stage C
    baseline = _run_buy_signal(prod_pool, mode="baseline")
    prod = _run_buy_signal(prod_pool, mode="prod_v2")

    base_cols = list(prod_pool.columns) + [
        "buy_date",
        "signal_triggered",
        "signal_type",
        "signal_time",
        "signal_price",
        "signal_reason",
        "non_trigger_reason",
    ]
    for frame in [baseline, prod]:
        for c in base_cols:
            if c not in frame.columns:
                frame[c] = pd.NA
    baseline = baseline[base_cols].copy()
    prod = prod[base_cols].copy()

    baseline.to_csv(OUT_BUY_BASE, index=False, encoding="utf-8-sig")
    prod.to_csv(OUT_BUY_PROD, index=False, encoding="utf-8-sig")

    base_sum = _buy_summary(baseline, "baseline_v11")
    prod_sum = _buy_summary(prod, "prod_v2")
    cmp_buy = _compare_buy(base_sum, prod_sum)
    cmp_buy.to_csv(OUT_BUY_COMPARE, index=False, encoding="utf-8-sig")

    checks = pd.read_csv(OUT_STAGEB_CONSTRAINT)
    _write_review(stagea_df, stageb_cmp, checks, best_gate, cmp_buy)

    print(str(OUT_MAINLINE_MAP))
    print(str(OUT_STAGEA))
    print(str(OUT_STAGEB_COMPARE))
    print(str(OUT_STAGEB_CONSTRAINT))
    print(str(OUT_PROD_POOL))
    print(str(OUT_BUY_BASE))
    print(str(OUT_BUY_PROD))
    print(str(OUT_BUY_COMPARE))
    print(str(OUT_REVIEW))
    print(str(OUT_SUMMARY))


if __name__ == "__main__":
    main()

