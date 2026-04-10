from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

import run_true_breakout_buy_signal_v1 as v1


ROOT = Path(r"D:\HuaweiAI\quantSystem2")
BASE = ROOT / "data/research/strong_start_full/v4_scan"

OUT_SIGNAL = BASE / "true_breakout_buy_signal_v1_1.csv"
OUT_SUMMARY = BASE / "true_breakout_buy_signal_v1_1_summary.csv"
OUT_SUMMARY_JSON = BASE / "true_breakout_buy_signal_v1_1_summary.json"
OUT_README = BASE / "true_breakout_buy_signal_v1_1_readme.md"


@dataclass
class SignalConfigV11(v1.SignalConfig):
    # Path A breakout adaptation (minimal relax)
    breakout_vol_ratio_min_path_a: float = 1.20
    hold_bars_above_ref_path_a: int = 2
    breakout_ref_hold_floor: float = 0.997

    # Path A range adaptation (fast rhythm)
    range_lookback_path_a: int = 12
    range_width_max_path_a: float = 0.015
    range_vol_ratio_min_path_a: float = 1.05


def _detect_breakout_pathaware(d: pd.DataFrame, cfg: SignalConfigV11, path_source: str) -> Optional[dict]:
    n = len(d)
    if n < cfg.min_bars_required:
        return None

    if path_source == "A":
        vol_ratio_min = cfg.breakout_vol_ratio_min_path_a
        hold_bars = cfg.hold_bars_above_ref_path_a
        hold_floor = cfg.breakout_ref_hold_floor
    else:
        vol_ratio_min = cfg.breakout_vol_ratio_min
        hold_bars = cfg.hold_bars_above_ref
        hold_floor = 0.998

    for i in range(cfg.breakout_lookback, n):
        window = d.iloc[max(0, i - cfg.breakout_lookback) : i]
        if window.empty:
            continue
        ref = float(window["high"].max())
        close_i = float(d.at[i, "close"])
        vol_ratio = float(d.at[i, "vol_ratio_20"]) if pd.notna(d.at[i, "vol_ratio_20"]) else 0.0
        chg = float(d.at[i, "chg_from_open"]) if pd.notna(d.at[i, "chg_from_open"]) else 0.0

        if close_i <= ref * (1 + cfg.breakout_break_pct):
            continue
        if vol_ratio < vol_ratio_min:
            continue
        if chg > cfg.breakout_max_chg_from_open:
            continue

        start = max(0, i - hold_bars + 1)
        hold = d.iloc[start : i + 1]
        if len(hold) < hold_bars:
            continue
        if (hold["close"] >= ref * hold_floor).all():
            return {
                "signal_type": "breakout_confirm",
                "trigger_idx": i,
                "trigger_time": d.at[i, "trade_time"],
                "trigger_price": close_i,
                "reason": (
                    f"breakout_v11(path={path_source},ref={ref:.3f},"
                    f"vol_ratio={vol_ratio:.2f},hold={hold_bars})"
                ),
            }
    return None


def _detect_range_break_pathaware(d: pd.DataFrame, cfg: SignalConfigV11, path_source: str) -> Optional[dict]:
    n = len(d)
    if n < cfg.min_bars_required:
        return None

    if path_source == "A":
        lb = cfg.range_lookback_path_a
        width_max = cfg.range_width_max_path_a
        vol_ratio_min = cfg.range_vol_ratio_min_path_a
    else:
        lb = cfg.range_lookback
        width_max = cfg.range_width_max
        vol_ratio_min = cfg.range_vol_ratio_min

    for i in range(lb, n):
        base = d.iloc[i - lb : i]
        hi = float(base["high"].max())
        lo = float(base["low"].min())
        width = (hi - lo) / lo if lo > 0 else np.nan
        close_i = float(d.at[i, "close"])
        vol_ratio = float(d.at[i, "vol_ratio_20"]) if pd.notna(d.at[i, "vol_ratio_20"]) else 0.0
        if pd.isna(width) or width > width_max:
            continue
        if close_i <= hi * (1 + cfg.range_break_pct):
            continue
        if vol_ratio < vol_ratio_min:
            continue
        return {
            "signal_type": "range_break_confirm",
            "trigger_idx": i,
            "trigger_time": d.at[i, "trade_time"],
            "trigger_price": close_i,
            "reason": f"range_break_v11(path={path_source},width={width:.3%},vol_ratio={vol_ratio:.2f})",
        }
    return None


def detect_buy_signal_v1_1(stock_row: pd.Series, intraday_df: pd.DataFrame, cfg: SignalConfigV11) -> dict:
    code = str(stock_row.get("stock_code", ""))
    date_t = str(stock_row.get("trade_date", ""))
    buy_date = str(stock_row.get("buy_date", ""))
    path_source = str(stock_row.get("path_source", ""))
    if intraday_df.empty:
        return {
            "trade_date": date_t,
            "buy_date": buy_date,
            "stock_code": code,
            "stock_name": stock_row.get("stock_name", ""),
            "signal_triggered": 0,
            "signal_type": "",
            "signal_time": "",
            "signal_price": np.nan,
            "signal_reason": "",
            "non_trigger_reason": "missing_intraday_data",
        }

    d = v1._prep_intraday(intraday_df)
    if d.empty or len(d) < cfg.min_bars_required:
        return {
            "trade_date": date_t,
            "buy_date": buy_date,
            "stock_code": code,
            "stock_name": stock_row.get("stock_name", ""),
            "signal_triggered": 0,
            "signal_type": "",
            "signal_time": "",
            "signal_price": np.nan,
            "signal_reason": "",
            "non_trigger_reason": "insufficient_intraday_bars",
        }

    sig_pull = v1._detect_pullback(d, cfg)
    sig_break = _detect_breakout_pathaware(d, cfg, path_source)
    sig_range = _detect_range_break_pathaware(d, cfg, path_source)

    cands = [x for x in [sig_pull, sig_break, sig_range] if x is not None]
    if not cands:
        return {
            "trade_date": date_t,
            "buy_date": buy_date,
            "stock_code": code,
            "stock_name": stock_row.get("stock_name", ""),
            "signal_triggered": 0,
            "signal_type": "",
            "signal_time": "",
            "signal_price": np.nan,
            "signal_reason": "",
            "non_trigger_reason": "no_v1_1_pattern_triggered",
        }

    # minimal path-aware routing
    if path_source == "A":
        priority = {"breakout_confirm": 1, "range_break_confirm": 2, "pullback_confirm": 3}
    else:
        priority = {"pullback_confirm": 1, "breakout_confirm": 2, "range_break_confirm": 3}
    cands = sorted(cands, key=lambda x: (x["trigger_idx"], priority.get(x["signal_type"], 99)))
    pick = cands[0]
    return {
        "trade_date": date_t,
        "buy_date": buy_date,
        "stock_code": code,
        "stock_name": stock_row.get("stock_name", ""),
        "signal_triggered": 1,
        "signal_type": pick["signal_type"],
        "signal_time": pd.Timestamp(pick["trigger_time"]).strftime("%Y-%m-%d %H:%M:%S"),
        "signal_price": float(pick["trigger_price"]),
        "signal_reason": pick["reason"],
        "non_trigger_reason": "",
    }


def _build_summary(result: pd.DataFrame) -> pd.DataFrame:
    groups = [
        ("all", result),
        ("triggered", result[result["signal_triggered"] == 1]),
        ("priority_tag_1", result[result["priority_tag"] == 1]),
        ("priority_tag_0", result[result["priority_tag"] == 0]),
        ("path_A", result[result["path_source"] == "A"]),
        ("path_B", result[result["path_source"] == "B"]),
        ("priority1_pathA", result[(result["priority_tag"] == 1) & (result["path_source"] == "A")]),
        ("priority1_pathB", result[(result["priority_tag"] == 1) & (result["path_source"] == "B")]),
    ]
    rows = []
    for gname, g in groups:
        if g.empty:
            continue
        row = {
            "group": gname,
            "sample_n": int(len(g)),
            "trigger_n": int((g["signal_triggered"] == 1).sum()),
            "trigger_rate": float((g["signal_triggered"] == 1).mean()),
            "pullback_confirm_n": int((g["signal_type"] == "pullback_confirm").sum()),
            "breakout_confirm_n": int((g["signal_type"] == "breakout_confirm").sum()),
            "range_break_confirm_n": int((g["signal_type"] == "range_break_confirm").sum()),
        }
        for h in ["t1", "t2", "t3"]:
            s = pd.to_numeric(g[f"ret_{h}_close"], errors="coerce")
            row[f"mean_ret_{h}"] = float(s.mean())
            row[f"win_{h}"] = float((s > 0).mean())
        rows.append(row)
    return pd.DataFrame(rows)


def _write_readme() -> None:
    txt = [
        "# True Breakout Buy Signal V1.1 (Minimal Iteration)",
        "",
        "V1.1 keeps selector frozen and only applies minimal buy-signal adaptations.",
        "",
        "## Minimal changes vs V1",
        "- Path-aware signal priority: Path A prefers breakout/range before pullback.",
        "- Path A breakout confirm lightly relaxed (volume threshold and hold bars).",
        "- Path A range break uses shorter/faster consolidation window.",
        "",
        "## Why",
        "- V1 audit showed Path A / priority_tag=1 under-triggered.",
        "- V1 was structurally pullback-heavy and Path B-biased.",
        "",
        "## Run",
        "- python scripts/run_true_breakout_buy_signal_v1_1.py",
        "",
        "## Outputs",
        "- true_breakout_buy_signal_v1_1.csv",
        "- true_breakout_buy_signal_v1_1_summary.csv",
        "- true_breakout_buy_signal_v1_1_summary.json",
        "",
        "## Boundaries",
        "- no selector changes",
        "- no sell logic",
        "- no full backtest",
    ]
    OUT_README.write_text("\n".join(txt), encoding="utf-8")


def main() -> None:
    cfg = SignalConfigV11()
    mvp = v1._load_mvp()
    nxt = v1._load_next_trade_date().rename(columns={"ts_code": "stock_code"})
    mvp = mvp.merge(nxt, on=["stock_code", "trade_date"], how="left")
    pre = mvp[mvp["is_core_candidate"] == 1].copy()
    pre["buy_date"] = pre["buy_date"].astype(str)

    out_rows = []
    for row in pre.itertuples(index=False):
        rr = pd.Series(row._asdict())
        intraday = v1._load_intraday(rr["stock_code"], rr.get("trade_date", ""))
        sig = detect_buy_signal_v1_1(rr, intraday, cfg)
        out_rows.append({**rr.to_dict(), **sig})

    result = pd.DataFrame(out_rows)
    keep_cols = [
        "trade_date",
        "buy_date",
        "stock_code",
        "stock_name",
        "path_source",
        "priority_tag",
        "rank_global_after_merge",
        "score_total",
        "ret_t1_close",
        "ret_t2_close",
        "ret_t3_close",
        "signal_triggered",
        "signal_type",
        "signal_time",
        "signal_price",
        "signal_reason",
        "non_trigger_reason",
        "selector_explain",
        "priority_reason",
    ]
    for c in keep_cols:
        if c not in result.columns:
            result[c] = pd.NA
    result = result[keep_cols].copy()

    result.to_csv(OUT_SIGNAL, index=False, encoding="utf-8-sig")
    summary = _build_summary(result)
    summary.to_csv(OUT_SUMMARY, index=False, encoding="utf-8-sig")
    _write_readme()

    payload = {
        "total_samples": int(len(result)),
        "triggered_samples": int((result["signal_triggered"] == 1).sum()),
        "priority_tag_1_samples": int((result["priority_tag"] == 1).sum()),
        "priority_tag_1_triggered": int(((result["priority_tag"] == 1) & (result["signal_triggered"] == 1)).sum()),
        "path_A_triggered": int(((result["path_source"] == "A") & (result["signal_triggered"] == 1)).sum()),
        "path_B_triggered": int(((result["path_source"] == "B") & (result["signal_triggered"] == 1)).sum()),
        "outputs": {"signal": str(OUT_SIGNAL), "summary": str(OUT_SUMMARY), "readme": str(OUT_README)},
    }
    OUT_SUMMARY_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

