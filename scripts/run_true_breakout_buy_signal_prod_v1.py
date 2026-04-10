from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

import run_true_breakout_buy_signal_v1 as v1
import run_true_breakout_buy_signal_v1_1 as v11


ROOT = Path(r"D:\HuaweiAI\quantSystem2")
BASE = ROOT / "data/research/strong_start_full/v4_scan"

IN_MAIN = BASE / "true_breakout_v32_with_priority_tag.csv"
IN_FEAT = BASE / "true_breakout_feature_snapshot_1y.parquet"

OUT_POOL = BASE / "true_breakout_production_input_pool.csv"
OUT_BASELINE = BASE / "true_breakout_buy_signal_baseline_on_production_pool.csv"
OUT_BASELINE_SUM = BASE / "true_breakout_buy_signal_baseline_on_production_pool_summary.csv"
OUT_PROD = BASE / "true_breakout_buy_signal_prod_v1.csv"
OUT_PROD_SUM = BASE / "true_breakout_buy_signal_prod_v1_summary.csv"
OUT_COMPARE = BASE / "true_breakout_buy_signal_baseline_vs_prod_v1_compare.csv"
OUT_REVIEW = BASE / "true_breakout_buy_signal_prod_v1_review.md"
OUT_SUMMARY_JSON = BASE / "true_breakout_buy_signal_prod_v1_summary.json"


@dataclass
class ProdV1Config:
    # Frozen F3 definition
    f3_platform_axis_max: float = 0.64
    f3_industry_axis_max: float = 0.90
    f3_compress_min: float = 0.33

    # Frozen T2_S4 definition (outer Path A supplement)
    t2_score_total_min: float = 0.80
    t2_industry_axis_max: float = 0.90

    # Tier-2 conservative execution gate (minimal and explainable)
    t2_max_rank: int = 10
    t2_breakout_vol_ratio_min: float = 1.25
    t2_breakout_max_chg_from_open: float = 0.075
    t2_pullback_drawdown_min: float = 0.006
    t2_pullback_drawdown_max: float = 0.030
    t2_pullback_close_vs_vwap_min: float = 0.998
    t2_allow_range_break: bool = False


def _load_source() -> pd.DataFrame:
    main = pd.read_csv(IN_MAIN)
    main["ts_code"] = main["ts_code"].astype(str)
    main["trade_date"] = main["trade_date"].astype(str)

    feat = pd.read_parquet(IN_FEAT)[["ts_code", "trade_date", "f_platform_compress_ratio", "f_chip_winner_rate"]].copy()
    feat["ts_code"] = feat["ts_code"].astype(str)
    feat["trade_date"] = feat["trade_date"].astype(str)

    d = main.merge(feat, on=["ts_code", "trade_date"], how="left")
    if "stock_code" not in d.columns:
        d["stock_code"] = d["ts_code"]
    d["stock_code"] = d["stock_code"].fillna(d["ts_code"]).astype(str)
    if "stock_name" not in d.columns:
        d["stock_name"] = d.get("name", "")
    d["stock_name"] = d["stock_name"].fillna(d.get("name", "")).astype(str)
    return d


def _f3_mask(d: pd.DataFrame, cfg: ProdV1Config) -> pd.Series:
    return (
        (pd.to_numeric(d["priority_tag"], errors="coerce") == 1)
        & (d["path_source"].astype(str) == "A")
        & (pd.to_numeric(d["score_platform_axis_single"], errors="coerce") <= cfg.f3_platform_axis_max)
        & (pd.to_numeric(d["score_industry_axis_single"], errors="coerce") <= cfg.f3_industry_axis_max)
        & (pd.to_numeric(d["f_platform_compress_ratio"], errors="coerce") >= cfg.f3_compress_min)
    )


def _t2_s4_mask(d: pd.DataFrame, cfg: ProdV1Config, f3_mask: pd.Series) -> pd.Series:
    outer_path_a = (d["path_source"].astype(str) == "A") & (~f3_mask)
    return (
        outer_path_a
        & (pd.to_numeric(d["priority_tag"], errors="coerce") == 0)
        & (pd.to_numeric(d["score_total"], errors="coerce") >= cfg.t2_score_total_min)
        & (pd.to_numeric(d["score_industry_axis_single"], errors="coerce") <= cfg.t2_industry_axis_max)
    )


def _build_production_pool(cfg: ProdV1Config) -> pd.DataFrame:
    d = _load_source()
    f3 = _f3_mask(d, cfg)
    t2 = _t2_s4_mask(d, cfg, f3)

    pool = d[f3 | t2].copy()
    pool["in_f3"] = f3[f3 | t2].astype(int).values
    pool["in_t2_s4"] = t2[f3 | t2].astype(int).values
    pool["input_tier"] = np.where(pool["in_f3"] == 1, "F3", "T2_S4")
    pool["is_core_candidate"] = 1

    ordered_cols = [
        "trade_date",
        "stock_code",
        "stock_name",
        "ts_code",
        "input_tier",
        "in_f3",
        "in_t2_s4",
        "pass_v3_2_candidate",
        "pass_v3_1_relaxed",
        "is_core_candidate",
        "priority_tag",
        "priority_reason",
        "path_source",
        "rank_in_path",
        "rank_global_after_merge",
        "score_total",
        "score_trend_axis_single",
        "score_platform_axis_single",
        "score_chip_axis_single",
        "score_industry_axis_single",
        "f_chip_winner_rate",
        "f_platform_compress_ratio",
        "selector_explain",
        "ret_t1_close",
        "ret_t2_close",
        "ret_t3_close",
        "label_A_high",
        "label_A_mid",
        "label_A_low",
        "label_C",
        "label_G",
    ]
    for c in ordered_cols:
        if c not in pool.columns:
            pool[c] = pd.NA
    pool = pool[ordered_cols].copy()
    pool.to_csv(OUT_POOL, index=False, encoding="utf-8-sig")
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

    sig_pull = v1._detect_pullback(d, cfg_v11)
    sig_break = v11._detect_breakout_pathaware(d, cfg_v11, "A")
    sig_range = v11._detect_range_break_pathaware(d, cfg_v11, "A")
    cands = [x for x in [sig_pull, sig_break, sig_range] if x is not None]
    return d, cands


def _pick_by_priority(cands: list[dict], priority: dict[str, int]) -> Optional[dict]:
    if not cands:
        return None
    ranked = sorted(cands, key=lambda x: (x["trigger_idx"], priority.get(x["signal_type"], 99)))
    return ranked[0]


def _tier2_gate(candidate: dict, d: pd.DataFrame, row: pd.Series, cfg: ProdV1Config) -> tuple[bool, str]:
    idx = int(candidate["trigger_idx"])
    signal_type = str(candidate["signal_type"])
    score_total = float(pd.to_numeric(row.get("score_total", np.nan), errors="coerce"))
    rank_global = float(pd.to_numeric(row.get("rank_global_after_merge", np.nan), errors="coerce"))
    vol_ratio = float(pd.to_numeric(d.at[idx, "vol_ratio_20"], errors="coerce")) if idx < len(d) else np.nan
    chg = float(pd.to_numeric(d.at[idx, "chg_from_open"], errors="coerce")) if idx < len(d) else np.nan
    drawdown = abs(float(pd.to_numeric(d.at[idx, "drawdown_from_session_high"], errors="coerce"))) if idx < len(d) else np.nan
    close_i = float(pd.to_numeric(d.at[idx, "close"], errors="coerce")) if idx < len(d) else np.nan
    vwap_i = float(pd.to_numeric(d.at[idx, "vwap"], errors="coerce")) if idx < len(d) else np.nan

    if not pd.isna(rank_global) and rank_global > cfg.t2_max_rank:
        return False, f"tier2_gate_rank_gt_{cfg.t2_max_rank}"
    if not pd.isna(score_total) and score_total < cfg.t2_score_total_min:
        return False, f"tier2_gate_score_total_lt_{cfg.t2_score_total_min:.2f}"

    if signal_type == "range_break_confirm" and not cfg.t2_allow_range_break:
        return False, "tier2_gate_disable_range_break"

    if signal_type == "breakout_confirm":
        if pd.isna(vol_ratio) or vol_ratio < cfg.t2_breakout_vol_ratio_min:
            return False, f"tier2_gate_breakout_vol_lt_{cfg.t2_breakout_vol_ratio_min:.2f}"
        if pd.isna(chg) or chg > cfg.t2_breakout_max_chg_from_open:
            return False, f"tier2_gate_breakout_chg_gt_{cfg.t2_breakout_max_chg_from_open:.3f}"
        if not pd.isna(vwap_i) and not pd.isna(close_i) and close_i < vwap_i:
            return False, "tier2_gate_breakout_below_vwap"

    if signal_type == "pullback_confirm":
        if pd.isna(drawdown) or drawdown < cfg.t2_pullback_drawdown_min:
            return False, f"tier2_gate_pullback_drawdown_lt_{cfg.t2_pullback_drawdown_min:.3f}"
        if pd.isna(drawdown) or drawdown > cfg.t2_pullback_drawdown_max:
            return False, f"tier2_gate_pullback_drawdown_gt_{cfg.t2_pullback_drawdown_max:.3f}"
        if not pd.isna(vwap_i) and not pd.isna(close_i) and close_i < vwap_i * cfg.t2_pullback_close_vs_vwap_min:
            return False, f"tier2_gate_pullback_close_below_vwapx{cfg.t2_pullback_close_vs_vwap_min:.3f}"

    return True, "tier2_gate_pass"


def _detect_baseline(row: pd.Series, intraday_df: pd.DataFrame, cfg_v11: v11.SignalConfigV11) -> dict:
    return v11.detect_buy_signal_v1_1(row, intraday_df, cfg_v11)


def _detect_prod_v1(row: pd.Series, intraday_df: pd.DataFrame, cfg_v11: v11.SignalConfigV11, cfg: ProdV1Config) -> dict:
    if intraday_df.empty:
        return _non_trigger_row(row, "missing_intraday_data")

    d, cands = _prep_signal_candidates(row, intraday_df, cfg_v11)
    if d.empty or len(d) < cfg_v11.min_bars_required:
        return _non_trigger_row(row, "insufficient_intraday_bars")
    if not cands:
        return _non_trigger_row(row, "no_prod_v1_pattern_triggered")

    tier = str(row.get("input_tier", ""))
    if tier == "F3":
        priority = {"breakout_confirm": 1, "range_break_confirm": 2, "pullback_confirm": 3}
        pick = _pick_by_priority(cands, priority)
        if pick is None:
            return _non_trigger_row(row, "f3_no_pick")
        return {
            "trade_date": str(row.get("trade_date", "")),
            "stock_code": str(row.get("stock_code", "")),
            "stock_name": row.get("stock_name", ""),
            "signal_triggered": 1,
            "signal_type": pick["signal_type"],
            "signal_time": pd.Timestamp(pick["trigger_time"]).strftime("%Y-%m-%d %H:%M:%S"),
            "signal_price": float(pick["trigger_price"]),
            "signal_reason": f"prod_v1_f3::{pick['reason']}",
            "non_trigger_reason": "",
        }

    # T2_S4: conservative gate and priority.
    priority = {"pullback_confirm": 1, "breakout_confirm": 2, "range_break_confirm": 3}
    ranked = sorted(cands, key=lambda x: (x["trigger_idx"], priority.get(x["signal_type"], 99)))
    block_reasons: list[str] = []
    for cand in ranked:
        ok, gate_reason = _tier2_gate(cand, d, row, cfg)
        if ok:
            return {
                "trade_date": str(row.get("trade_date", "")),
                "stock_code": str(row.get("stock_code", "")),
                "stock_name": row.get("stock_name", ""),
                "signal_triggered": 1,
                "signal_type": cand["signal_type"],
                "signal_time": pd.Timestamp(cand["trigger_time"]).strftime("%Y-%m-%d %H:%M:%S"),
                "signal_price": float(cand["trigger_price"]),
                "signal_reason": f"prod_v1_t2::{cand['reason']}::{gate_reason}",
                "non_trigger_reason": "",
            }
        block_reasons.append(gate_reason)
    if block_reasons:
        uniq = "|".join(dict.fromkeys(block_reasons))
        return _non_trigger_row(row, f"tier2_gate_blocked::{uniq}")
    return _non_trigger_row(row, "tier2_no_pick")


def _run_signals(pool: pd.DataFrame, mode: str, cfg: ProdV1Config) -> pd.DataFrame:
    cfg_v11 = v11.SignalConfigV11()
    rows = []
    for r in pool.itertuples(index=False):
        row = pd.Series(r._asdict())
        intraday = v1._load_intraday(str(row.get("stock_code", "")), str(row.get("trade_date", "")))
        if mode == "baseline":
            sig = _detect_baseline(row, intraday, cfg_v11)
        else:
            sig = _detect_prod_v1(row, intraday, cfg_v11, cfg)
        rows.append({**row.to_dict(), **sig})
    return pd.DataFrame(rows)


def _group_stats(df: pd.DataFrame, group_name: str) -> dict:
    g = df.copy()
    trig = g[g["signal_triggered"] == 1].copy()
    row: dict[str, int | float | str] = {
        "group": group_name,
        "sample_n": int(len(g)),
        "trigger_n": int(len(trig)),
        "trigger_rate": float(len(trig) / len(g)) if len(g) else np.nan,
        "pullback_confirm_n": int((trig["signal_type"] == "pullback_confirm").sum()) if len(trig) else 0,
        "breakout_confirm_n": int((trig["signal_type"] == "breakout_confirm").sum()) if len(trig) else 0,
        "range_break_confirm_n": int((trig["signal_type"] == "range_break_confirm").sum()) if len(trig) else 0,
    }

    # Triggered returns (primary for buy-signal evaluation)
    for h in ["t1", "t2", "t3"]:
        s_trig = pd.to_numeric(trig[f"ret_{h}_close"], errors="coerce")
        row[f"mean_ret_{h}"] = float(s_trig.mean()) if len(s_trig) else np.nan
        row[f"median_ret_{h}"] = float(s_trig.median()) if len(s_trig) else np.nan
        row[f"win_{h}"] = float((s_trig > 0).mean()) if len(s_trig) else np.nan

    # Pool-level reference returns (kept for context)
    for h in ["t1", "t2", "t3"]:
        s_all = pd.to_numeric(g[f"ret_{h}_close"], errors="coerce")
        row[f"pool_mean_ret_{h}"] = float(s_all.mean()) if len(s_all) else np.nan
        row[f"pool_win_{h}"] = float((s_all > 0).mean()) if len(s_all) else np.nan
    return row


def _build_summary(df: pd.DataFrame, version: str) -> pd.DataFrame:
    groups = {
        "all": df.index == df.index,
        "F3": df["input_tier"] == "F3",
        "T2_S4": df["input_tier"] == "T2_S4",
    }
    rows = []
    for gname, mask in groups.items():
        g = df[mask].copy()
        row = _group_stats(g, gname)
        row["version"] = version
        rows.append(row)
    cols = ["version"] + [c for c in rows[0].keys() if c != "version"]
    return pd.DataFrame(rows)[cols]


def _build_compare(base_sum: pd.DataFrame, prod_sum: pd.DataFrame) -> pd.DataFrame:
    b = base_sum.set_index("group")
    p = prod_sum.set_index("group")
    groups = sorted(set(b.index.tolist()) | set(p.index.tolist()))
    rows = []
    for g in groups:
        row: dict[str, str | float] = {"group": g}
        for c in [x for x in b.columns if x != "version"]:
            bv = b.at[g, c] if g in b.index and c in b.columns else np.nan
            pv = p.at[g, c] if g in p.index and c in p.columns else np.nan
            row[f"baseline_{c}"] = bv
            row[f"prod_v1_{c}"] = pv
            if isinstance(bv, (int, float, np.number)) or isinstance(pv, (int, float, np.number)):
                try:
                    row[f"delta_{c}"] = float(pv) - float(bv)
                except Exception:
                    row[f"delta_{c}"] = np.nan
        rows.append(row)
    return pd.DataFrame(rows)


def _write_review(pool: pd.DataFrame, base_sum: pd.DataFrame, prod_sum: pd.DataFrame) -> None:
    def _grab(df: pd.DataFrame, g: str, c: str) -> float:
        x = df[df["group"] == g]
        if x.empty:
            return np.nan
        return float(x.iloc[0][c])

    b_all_tr = _grab(base_sum, "all", "trigger_rate")
    p_all_tr = _grab(prod_sum, "all", "trigger_rate")
    b_f3_tr = _grab(base_sum, "F3", "trigger_rate")
    p_f3_tr = _grab(prod_sum, "F3", "trigger_rate")
    b_t2_tr = _grab(base_sum, "T2_S4", "trigger_rate")
    p_t2_tr = _grab(prod_sum, "T2_S4", "trigger_rate")

    b_all_w2 = _grab(base_sum, "all", "win_t2")
    p_all_w2 = _grab(prod_sum, "all", "win_t2")
    b_f3_w2 = _grab(base_sum, "F3", "win_t2")
    p_f3_w2 = _grab(prod_sum, "F3", "win_t2")
    b_t2_w2 = _grab(base_sum, "T2_S4", "win_t2")
    p_t2_w2 = _grab(prod_sum, "T2_S4", "win_t2")

    lines = [
        "# True Breakout Buy Signal Prod V1 Review",
        "",
        "Production input is frozen and reused directly:",
        "- Tier-1: F3",
        "- Tier-2: T2_S4_pri0_breadth",
        "",
        "## What changed vs baseline",
        "- Baseline: current default unified buy signal logic (v1.1).",
        "- Prod_v1: tier-aware buy signal routing with minimal conservative gate for T2_S4.",
        "",
        "## Headline metrics",
        f"- input samples: {len(pool)} (F3={int((pool['input_tier']=='F3').sum())}, T2_S4={int((pool['input_tier']=='T2_S4').sum())})",
        f"- trigger_rate all: baseline={b_all_tr:.2%}, prod_v1={p_all_tr:.2%}",
        f"- trigger_rate F3: baseline={b_f3_tr:.2%}, prod_v1={p_f3_tr:.2%}",
        f"- trigger_rate T2_S4: baseline={b_t2_tr:.2%}, prod_v1={p_t2_tr:.2%}",
        f"- win_t2 all(triggered): baseline={b_all_w2:.2%}, prod_v1={p_all_w2:.2%}",
        f"- win_t2 F3(triggered): baseline={b_f3_w2:.2%}, prod_v1={p_f3_w2:.2%}",
        f"- win_t2 T2_S4(triggered): baseline={b_t2_w2:.2%}, prod_v1={p_t2_w2:.2%}",
        "",
        "## Boundaries kept",
        "- selector unchanged (v3.2/v3.1/priority_tag unchanged)",
        "- no sell logic, no full backtest, no parameter search",
        "",
        "## Run",
        "- python scripts/run_true_breakout_buy_signal_prod_v1.py",
    ]
    OUT_REVIEW.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    cfg = ProdV1Config()
    pool = _build_production_pool(cfg)

    baseline = _run_signals(pool, mode="baseline", cfg=cfg)
    prod = _run_signals(pool, mode="prod_v1", cfg=cfg)

    # Keep stable export column order.
    base_cols = list(pool.columns) + [
        "signal_triggered",
        "signal_type",
        "signal_time",
        "signal_price",
        "signal_reason",
        "non_trigger_reason",
    ]
    for d in [baseline, prod]:
        for c in base_cols:
            if c not in d.columns:
                d[c] = pd.NA
        d = d[base_cols]

    baseline = baseline[base_cols].copy()
    prod = prod[base_cols].copy()

    baseline.to_csv(OUT_BASELINE, index=False, encoding="utf-8-sig")
    prod.to_csv(OUT_PROD, index=False, encoding="utf-8-sig")

    base_sum = _build_summary(baseline, version="baseline")
    prod_sum = _build_summary(prod, version="prod_v1")
    base_sum.to_csv(OUT_BASELINE_SUM, index=False, encoding="utf-8-sig")
    prod_sum.to_csv(OUT_PROD_SUM, index=False, encoding="utf-8-sig")

    compare = _build_compare(base_sum, prod_sum)
    compare.to_csv(OUT_COMPARE, index=False, encoding="utf-8-sig")

    _write_review(pool, base_sum, prod_sum)

    summary_payload = {
        "pool": {
            "sample_n": int(len(pool)),
            "f3_n": int((pool["input_tier"] == "F3").sum()),
            "t2_s4_n": int((pool["input_tier"] == "T2_S4").sum()),
            "trade_days": int(pool["trade_date"].nunique()),
        },
        "baseline": base_sum.to_dict("records"),
        "prod_v1": prod_sum.to_dict("records"),
        "outputs": {
            "production_pool": str(OUT_POOL),
            "baseline_signal": str(OUT_BASELINE),
            "baseline_summary": str(OUT_BASELINE_SUM),
            "prod_signal": str(OUT_PROD),
            "prod_summary": str(OUT_PROD_SUM),
            "compare": str(OUT_COMPARE),
            "review": str(OUT_REVIEW),
        },
    }
    OUT_SUMMARY_JSON.write_text(json.dumps(summary_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def _fmt(v: float) -> str:
        return "nan" if pd.isna(v) else f"{v:.2%}"

    b_all = base_sum[base_sum["group"] == "all"].iloc[0]
    p_all = prod_sum[prod_sum["group"] == "all"].iloc[0]
    b_tag = int((baseline["signal_triggered"] == 1).sum())
    p_tag = int((prod["signal_triggered"] == 1).sum())

    print(f"POOL total={len(pool)} F3={int((pool['input_tier']=='F3').sum())} T2_S4={int((pool['input_tier']=='T2_S4').sum())}")
    print(
        f"BASELINE triggered={b_tag} rate={_fmt(float(b_all['trigger_rate']))} "
        f"T1 mean/win={_fmt(float(b_all['mean_ret_t1']))}/{_fmt(float(b_all['win_t1']))} "
        f"T2 mean/win={_fmt(float(b_all['mean_ret_t2']))}/{_fmt(float(b_all['win_t2']))} "
        f"T3 mean/win={_fmt(float(b_all['mean_ret_t3']))}/{_fmt(float(b_all['win_t3']))}"
    )
    print(
        f"PROD_V1 triggered={p_tag} rate={_fmt(float(p_all['trigger_rate']))} "
        f"T1 mean/win={_fmt(float(p_all['mean_ret_t1']))}/{_fmt(float(p_all['win_t1']))} "
        f"T2 mean/win={_fmt(float(p_all['mean_ret_t2']))}/{_fmt(float(p_all['win_t2']))} "
        f"T3 mean/win={_fmt(float(p_all['mean_ret_t3']))}/{_fmt(float(p_all['win_t3']))}"
    )
    print(str(OUT_POOL))
    print(str(OUT_BASELINE))
    print(str(OUT_BASELINE_SUM))
    print(str(OUT_PROD))
    print(str(OUT_PROD_SUM))
    print(str(OUT_COMPARE))
    print(str(OUT_REVIEW))


if __name__ == "__main__":
    main()

