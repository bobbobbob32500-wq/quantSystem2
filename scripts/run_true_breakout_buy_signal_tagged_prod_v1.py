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

IN_TAGGED_POOL = BASE / "true_breakout_stage2_mainline_with_quality_tag.csv"

OUT_BASELINE = BASE / "true_breakout_buy_signal_tagged_baseline.csv"
OUT_PROD = BASE / "true_breakout_buy_signal_tagged_prod_v1.csv"
OUT_COMPARE = BASE / "true_breakout_buy_signal_tagged_compare.csv"
OUT_REVIEW = BASE / "true_breakout_buy_signal_tagged_prod_v1_review.md"
OUT_SUMMARY = BASE / "true_breakout_buy_signal_tagged_prod_v1_summary.json"


@dataclass
class Tag0ConservativeGate:
    rank_max: float = 12.0
    breakout_vol_ratio_min: float = 1.25
    breakout_max_chg_from_open: float = 0.075
    pullback_drawdown_min: float = 0.006
    pullback_drawdown_max: float = 0.030
    pullback_close_vs_vwap_min: float = 0.998
    allow_range_break: bool = False


def _prep_signal_candidates(row: pd.Series, intraday_df: pd.DataFrame) -> tuple[pd.DataFrame, list[dict]]:
    cfg_v11 = v11.SignalConfigV11()
    d = v1._prep_intraday(intraday_df)
    if d.empty or len(d) < cfg_v11.min_bars_required:
        return d, []
    path_source = str(row.get("path_source", ""))
    sig_pull = v1._detect_pullback(d, cfg_v11)
    sig_break = v11._detect_breakout_pathaware(d, cfg_v11, path_source)
    sig_range = v11._detect_range_break_pathaware(d, cfg_v11, path_source)
    cands = [x for x in [sig_pull, sig_break, sig_range] if x is not None]
    return d, cands


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


def _pick_by_priority(cands: list[dict], path_source: str) -> Optional[dict]:
    # Keep v1.1 path-aware priority
    if path_source == "A":
        priority = {"breakout_confirm": 1, "range_break_confirm": 2, "pullback_confirm": 3}
    else:
        priority = {"pullback_confirm": 1, "breakout_confirm": 2, "range_break_confirm": 3}
    ranked = sorted(cands, key=lambda x: (x["trigger_idx"], priority.get(x["signal_type"], 99)))
    return ranked[0] if ranked else None


def _apply_tag0_gate(row: pd.Series, d: pd.DataFrame, cand: dict, gate: Tag0ConservativeGate) -> tuple[bool, str]:
    idx = int(cand["trigger_idx"])
    sig = str(cand["signal_type"])

    rank_global = pd.to_numeric(row.get("rank_global_after_merge", np.nan), errors="coerce")
    if pd.notna(rank_global) and float(rank_global) > gate.rank_max:
        return False, f"tag0_gate_rank_gt_{gate.rank_max:.0f}"

    close_i = pd.to_numeric(d.at[idx, "close"], errors="coerce") if idx < len(d) else np.nan
    vwap_i = pd.to_numeric(d.at[idx, "vwap"], errors="coerce") if idx < len(d) else np.nan
    vol_ratio = pd.to_numeric(d.at[idx, "vol_ratio_20"], errors="coerce") if idx < len(d) else np.nan
    chg = pd.to_numeric(d.at[idx, "chg_from_open"], errors="coerce") if idx < len(d) else np.nan
    drawdown = (
        abs(float(pd.to_numeric(d.at[idx, "drawdown_from_session_high"], errors="coerce")))
        if idx < len(d) and pd.notna(d.at[idx, "drawdown_from_session_high"])
        else np.nan
    )

    if sig == "range_break_confirm" and not gate.allow_range_break:
        return False, "tag0_gate_disable_range_break"

    if sig == "breakout_confirm":
        if pd.isna(vol_ratio) or float(vol_ratio) < gate.breakout_vol_ratio_min:
            return False, f"tag0_gate_breakout_vol_lt_{gate.breakout_vol_ratio_min:.2f}"
        if pd.isna(chg) or float(chg) > gate.breakout_max_chg_from_open:
            return False, f"tag0_gate_breakout_chg_gt_{gate.breakout_max_chg_from_open:.3f}"
        if pd.notna(vwap_i) and pd.notna(close_i) and float(close_i) < float(vwap_i):
            return False, "tag0_gate_breakout_below_vwap"

    if sig == "pullback_confirm":
        if pd.isna(drawdown) or drawdown < gate.pullback_drawdown_min:
            return False, f"tag0_gate_pullback_dd_lt_{gate.pullback_drawdown_min:.3f}"
        if pd.isna(drawdown) or drawdown > gate.pullback_drawdown_max:
            return False, f"tag0_gate_pullback_dd_gt_{gate.pullback_drawdown_max:.3f}"
        if pd.notna(vwap_i) and pd.notna(close_i) and float(close_i) < float(vwap_i) * gate.pullback_close_vs_vwap_min:
            return False, f"tag0_gate_pullback_below_vwapx{gate.pullback_close_vs_vwap_min:.3f}"

    return True, "tag0_gate_pass"


def _detect_baseline(row: pd.Series, intraday_df: pd.DataFrame) -> dict:
    cfg_v11 = v11.SignalConfigV11()
    return v11.detect_buy_signal_v1_1(row, intraday_df, cfg_v11)


def _detect_prod(row: pd.Series, intraday_df: pd.DataFrame, gate: Tag0ConservativeGate) -> dict:
    if intraday_df.empty:
        return _non_trigger_row(row, "missing_intraday_data")

    d, cands = _prep_signal_candidates(row, intraday_df)
    if d.empty:
        return _non_trigger_row(row, "insufficient_intraday_bars")
    if not cands:
        return _non_trigger_row(row, "no_tagged_pattern_triggered")

    path_source = str(row.get("path_source", ""))
    pick = _pick_by_priority(cands, path_source)
    if pick is None:
        return _non_trigger_row(row, "no_priority_pick")

    # Tag-layer routing:
    # - quality_tag=1: keep baseline behavior
    # - quality_tag=0: apply conservative gate
    quality_tag = int(pd.to_numeric(row.get("quality_tag", 0), errors="coerce") or 0)
    if quality_tag == 0:
        ok, gate_reason = _apply_tag0_gate(row, d, pick, gate)
        if not ok:
            return _non_trigger_row(row, gate_reason)
        reason = f"tagged_prod_v1::quality_tag0::{pick['reason']}::{gate_reason}"
    else:
        reason = f"tagged_prod_v1::quality_tag1::{pick['reason']}"

    return {
        "trade_date": str(row.get("trade_date", "")),
        "stock_code": str(row.get("stock_code", "")),
        "stock_name": row.get("stock_name", ""),
        "signal_triggered": 1,
        "signal_type": pick["signal_type"],
        "signal_time": pd.Timestamp(pick["trigger_time"]).strftime("%Y-%m-%d %H:%M:%S"),
        "signal_price": float(pick["trigger_price"]),
        "signal_reason": reason,
        "non_trigger_reason": "",
    }


def _run(df: pd.DataFrame, mode: str, gate: Tag0ConservativeGate) -> pd.DataFrame:
    rows = []
    for r in df.itertuples(index=False):
        row = pd.Series(r._asdict())
        intraday = v1._load_intraday(str(row.get("stock_code", "")), str(row.get("trade_date", "")))
        if mode == "baseline":
            sig = _detect_baseline(row, intraday)
        else:
            sig = _detect_prod(row, intraday, gate)
        rows.append({**row.to_dict(), **sig})
    return pd.DataFrame(rows)


def _group_stats(g: pd.DataFrame, group: str, version: str) -> dict:
    trig = g[g["signal_triggered"] == 1].copy()
    row: dict[str, float | int | str] = {
        "version": version,
        "group": group,
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
    return row


def _build_compare(base: pd.DataFrame, prod: pd.DataFrame) -> pd.DataFrame:
    b = base.set_index("group")
    p = prod.set_index("group")
    groups = sorted(set(b.index) | set(p.index))
    rows = []
    cols = [c for c in b.columns if c != "version"]
    for g in groups:
        row: dict[str, float | str] = {"group": g}
        for c in cols:
            bv = b.at[g, c] if g in b.index else np.nan
            pv = p.at[g, c] if g in p.index else np.nan
            row[f"baseline_{c}"] = bv
            row[f"tagged_prod_{c}"] = pv
            try:
                row[f"delta_{c}"] = float(pv) - float(bv)
            except Exception:
                row[f"delta_{c}"] = np.nan
        rows.append(row)
    return pd.DataFrame(rows)


def main() -> None:
    if not IN_TAGGED_POOL.exists():
        raise FileNotFoundError(f"Missing input: {IN_TAGGED_POOL}")

    pool = pd.read_csv(IN_TAGGED_POOL)
    pool["trade_date"] = pool["trade_date"].astype(str)
    pool["stock_code"] = pool["stock_code"].astype(str)
    pool["quality_tag"] = pd.to_numeric(pool.get("quality_tag", 0), errors="coerce").fillna(0).astype(int)

    gate = Tag0ConservativeGate()

    baseline = _run(pool, mode="baseline", gate=gate)
    prod = _run(pool, mode="prod", gate=gate)

    keep_cols = list(pool.columns) + [
        "signal_triggered",
        "signal_type",
        "signal_time",
        "signal_price",
        "signal_reason",
        "non_trigger_reason",
    ]
    for d in (baseline, prod):
        for c in keep_cols:
            if c not in d.columns:
                d[c] = pd.NA
    baseline = baseline[keep_cols].copy()
    prod = prod[keep_cols].copy()

    baseline.to_csv(OUT_BASELINE, index=False, encoding="utf-8-sig")
    prod.to_csv(OUT_PROD, index=False, encoding="utf-8-sig")

    groups = {
        "all": pool.index == pool.index,
        "quality_tag_1": pool["quality_tag"] == 1,
        "quality_tag_0": pool["quality_tag"] == 0,
    }
    base_rows = []
    prod_rows = []
    for gname, mask in groups.items():
        base_rows.append(_group_stats(baseline[mask].copy(), gname, "baseline"))
        prod_rows.append(_group_stats(prod[mask].copy(), gname, "tagged_prod_v1"))
    base_sum = pd.DataFrame(base_rows)
    prod_sum = pd.DataFrame(prod_rows)
    compare = _build_compare(base_sum, prod_sum)
    compare.to_csv(OUT_COMPARE, index=False, encoding="utf-8-sig")

    def _grab(df: pd.DataFrame, g: str, c: str) -> float:
        x = df[df["group"] == g]
        if x.empty:
            return np.nan
        return float(x.iloc[0][c])

    lines = [
        "# Tagged Buy Signal Prod V1 Review",
        "",
        "## Routing",
        "- `quality_tag=1`: keep baseline v1.1 detection behavior.",
        "- `quality_tag=0`: apply conservative gate (rank/overheat/confirmation safety).",
        "",
        "## Full-year quick check",
        f"- all win_t2: baseline={_grab(base_sum,'all','win_t2'):.2%}, tagged_prod={_grab(prod_sum,'all','win_t2'):.2%}",
        f"- quality_tag=1 win_t2: baseline={_grab(base_sum,'quality_tag_1','win_t2'):.2%}, tagged_prod={_grab(prod_sum,'quality_tag_1','win_t2'):.2%}",
        f"- quality_tag=0 win_t2: baseline={_grab(base_sum,'quality_tag_0','win_t2'):.2%}, tagged_prod={_grab(prod_sum,'quality_tag_0','win_t2'):.2%}",
        "",
        "## Trigger rate",
        f"- all: baseline={_grab(base_sum,'all','trigger_rate'):.2%}, tagged_prod={_grab(prod_sum,'all','trigger_rate'):.2%}",
        f"- quality_tag=1: baseline={_grab(base_sum,'quality_tag_1','trigger_rate'):.2%}, tagged_prod={_grab(prod_sum,'quality_tag_1','trigger_rate'):.2%}",
        f"- quality_tag=0: baseline={_grab(base_sum,'quality_tag_0','trigger_rate'):.2%}, tagged_prod={_grab(prod_sum,'quality_tag_0','trigger_rate'):.2%}",
    ]
    OUT_REVIEW.write_text("\n".join(lines), encoding="utf-8")

    payload = {
        "input_pool": str(IN_TAGGED_POOL),
        "routing": {
            "quality_tag_1": "baseline_v1_1",
            "quality_tag_0": "conservative_gate",
        },
        "gate": {
            "rank_max": gate.rank_max,
            "breakout_vol_ratio_min": gate.breakout_vol_ratio_min,
            "breakout_max_chg_from_open": gate.breakout_max_chg_from_open,
            "pullback_drawdown_min": gate.pullback_drawdown_min,
            "pullback_drawdown_max": gate.pullback_drawdown_max,
            "pullback_close_vs_vwap_min": gate.pullback_close_vs_vwap_min,
            "allow_range_break": gate.allow_range_break,
        },
        "baseline_summary": base_sum.to_dict("records"),
        "tagged_prod_summary": prod_sum.to_dict("records"),
        "outputs": {
            "baseline": str(OUT_BASELINE),
            "prod": str(OUT_PROD),
            "compare": str(OUT_COMPARE),
            "review": str(OUT_REVIEW),
        },
    }
    OUT_SUMMARY.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print(str(OUT_BASELINE))
    print(str(OUT_PROD))
    print(str(OUT_COMPARE))
    print(str(OUT_REVIEW))
    print(str(OUT_SUMMARY))


if __name__ == "__main__":
    main()

