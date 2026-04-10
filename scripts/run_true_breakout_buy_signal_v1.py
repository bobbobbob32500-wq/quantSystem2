from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd


ROOT = Path(r"D:\HuaweiAI\quantSystem2")
BASE = ROOT / "data/research/strong_start_full/v4_scan"
IN_MVP = BASE / "true_breakout_strategy_mvp.csv"

DB_DAILY = ROOT / "data/database/quant_system.db"
DB_INTRADAY = ROOT / "data/history_recommendation.db"

OUT_SIGNAL = BASE / "true_breakout_buy_signal_v1.csv"
OUT_SUMMARY = BASE / "true_breakout_buy_signal_v1_summary.csv"
OUT_README = BASE / "true_breakout_buy_signal_v1_readme.md"


@dataclass
class SignalConfig:
    breakout_lookback: int = 30
    breakout_vol_ratio_min: float = 1.30
    breakout_break_pct: float = 0.001
    breakout_max_chg_from_open: float = 0.095
    hold_bars_above_ref: int = 3

    pullback_support_buffer: float = 0.002
    pullback_reclaim_buffer: float = 0.001
    pullback_drawdown_min: float = 0.004
    pullback_drawdown_max: float = 0.035
    pullback_vol_ratio_min: float = 0.95
    pullback_max_chg_from_open: float = 0.08

    range_lookback: int = 20
    range_width_max: float = 0.012
    range_break_pct: float = 0.001
    range_vol_ratio_min: float = 1.15

    min_bars_required: int = 40


def _load_mvp() -> pd.DataFrame:
    d = pd.read_csv(IN_MVP)
    d["trade_date"] = d["trade_date"].astype(str)
    d["stock_code"] = d["stock_code"].astype(str)
    return d


def _load_next_trade_date() -> pd.DataFrame:
    conn = sqlite3.connect(DB_DAILY)
    try:
        daily = pd.read_sql_query("select ts_code, trade_date from stock_daily", conn)
    finally:
        conn.close()
    daily["trade_date"] = daily["trade_date"].astype(str)
    daily = daily.sort_values(["ts_code", "trade_date"]).reset_index(drop=True)
    daily["buy_date"] = daily.groupby("ts_code")["trade_date"].shift(-1)
    return daily[["ts_code", "trade_date", "buy_date"]]


def _load_intraday(symbol: str, signal_date: str) -> pd.DataFrame:
    if not signal_date or pd.isna(signal_date):
        return pd.DataFrame()
    day = f"{signal_date[:4]}-{signal_date[4:6]}-{signal_date[6:8]}"
    conn = sqlite3.connect(DB_INTRADAY)
    try:
        q = """
        select symbol, trade_time, trade_date, open, high, low, close, volume, amount
        from intraday_data
        where symbol=? and trade_date=?
        order by trade_time
        """
        df = pd.read_sql_query(q, conn, params=[symbol, day])
    finally:
        conn.close()
    if df.empty:
        return df
    for c in ["open", "high", "low", "close", "volume", "amount"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["trade_time"] = pd.to_datetime(df["trade_time"], errors="coerce")
    df = df.dropna(subset=["trade_time", "close"]).copy()
    return df.reset_index(drop=True)


def _prep_intraday(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    d = df.copy()
    d["avg_vol_20"] = d["volume"].rolling(20, min_periods=5).mean()
    d["vol_ratio_20"] = d["volume"] / d["avg_vol_20"].replace(0, np.nan)
    d["vwap"] = (d["close"] * d["volume"]).cumsum() / d["volume"].replace(0, np.nan).cumsum()
    d["session_high"] = d["high"].cummax()
    d["chg_from_open"] = d["close"] / d["open"].iloc[0] - 1.0
    d["drawdown_from_session_high"] = d["close"] / d["session_high"] - 1.0
    return d


def _detect_breakout(d: pd.DataFrame, cfg: SignalConfig) -> Optional[dict]:
    n = len(d)
    if n < cfg.min_bars_required:
        return None
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
        if vol_ratio < cfg.breakout_vol_ratio_min:
            continue
        if chg > cfg.breakout_max_chg_from_open:
            continue

        start = max(0, i - cfg.hold_bars_above_ref + 1)
        hold = d.iloc[start : i + 1]
        if len(hold) < cfg.hold_bars_above_ref:
            continue
        if (hold["close"] >= ref * 0.998).all():
            return {
                "signal_type": "breakout_confirm",
                "trigger_idx": i,
                "trigger_time": d.at[i, "trade_time"],
                "trigger_price": close_i,
                "reason": f"breakout_above_ref_with_volume(ref={ref:.3f},vol_ratio={vol_ratio:.2f})",
            }
    return None


def _detect_pullback(d: pd.DataFrame, cfg: SignalConfig) -> Optional[dict]:
    n = len(d)
    if n < cfg.min_bars_required:
        return None
    for i in range(20, n):
        close_i = float(d.at[i, "close"])
        low_i = float(d.at[i, "low"])
        vwap_i = float(d.at[i, "vwap"]) if pd.notna(d.at[i, "vwap"]) else close_i
        support = max(vwap_i, float(d.at[0, "open"]))
        drawdown = abs(float(d.at[i, "drawdown_from_session_high"])) if pd.notna(d.at[i, "drawdown_from_session_high"]) else 0.0
        vol_ratio = float(d.at[i, "vol_ratio_20"]) if pd.notna(d.at[i, "vol_ratio_20"]) else 0.0
        chg = float(d.at[i, "chg_from_open"]) if pd.notna(d.at[i, "chg_from_open"]) else 0.0

        if drawdown < cfg.pullback_drawdown_min or drawdown > cfg.pullback_drawdown_max:
            continue
        if low_i > support * (1 + cfg.pullback_support_buffer):
            continue
        if close_i < support * (1 + cfg.pullback_reclaim_buffer):
            continue
        if vol_ratio < cfg.pullback_vol_ratio_min:
            continue
        if chg > cfg.pullback_max_chg_from_open:
            continue
        if i >= 1 and close_i < float(d.at[i - 1, "close"]):
            continue
        return {
            "signal_type": "pullback_confirm",
            "trigger_idx": i,
            "trigger_time": d.at[i, "trade_time"],
            "trigger_price": close_i,
            "reason": f"pullback_reclaim_support(support={support:.3f},drawdown={drawdown:.3%})",
        }
    return None


def _detect_range_break(d: pd.DataFrame, cfg: SignalConfig) -> Optional[dict]:
    n = len(d)
    if n < cfg.min_bars_required:
        return None
    lb = cfg.range_lookback
    for i in range(lb, n):
        base = d.iloc[i - lb : i]
        hi = float(base["high"].max())
        lo = float(base["low"].min())
        width = (hi - lo) / lo if lo > 0 else np.nan
        close_i = float(d.at[i, "close"])
        vol_ratio = float(d.at[i, "vol_ratio_20"]) if pd.notna(d.at[i, "vol_ratio_20"]) else 0.0
        if pd.isna(width) or width > cfg.range_width_max:
            continue
        if close_i <= hi * (1 + cfg.range_break_pct):
            continue
        if vol_ratio < cfg.range_vol_ratio_min:
            continue
        return {
            "signal_type": "range_break_confirm",
            "trigger_idx": i,
            "trigger_time": d.at[i, "trade_time"],
            "trigger_price": close_i,
            "reason": f"range_break(width={width:.3%},vol_ratio={vol_ratio:.2f})",
        }
    return None


def detect_buy_signal(stock_row: pd.Series, intraday_df: pd.DataFrame, config: SignalConfig) -> dict:
    code = str(stock_row.get("stock_code", ""))
    date_t = str(stock_row.get("trade_date", ""))
    buy_date = str(stock_row.get("buy_date", ""))
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

    d = _prep_intraday(intraday_df)
    if d.empty or len(d) < config.min_bars_required:
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

    sig_pull = _detect_pullback(d, config)
    sig_break = _detect_breakout(d, config)
    sig_range = _detect_range_break(d, config)
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
            "non_trigger_reason": "no_v1_pattern_triggered",
        }

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


def build_summary(result: pd.DataFrame) -> pd.DataFrame:
    rows = []
    groups = [
        ("all", result),
        ("triggered", result[result["signal_triggered"] == 1]),
        ("priority_tag_1", result[result["priority_tag"] == 1]),
        ("priority_tag_1_triggered", result[(result["priority_tag"] == 1) & (result["signal_triggered"] == 1)]),
    ]
    for name, g in groups:
        if g.empty:
            continue
        rows.append(
            {
                "group": name,
                "sample_n": int(len(g)),
                "triggered_n": int((g["signal_triggered"] == 1).sum()),
                "trigger_rate": float((g["signal_triggered"] == 1).mean()),
                "mean_ret_t1": float(g["ret_t1_close"].mean()),
                "mean_ret_t2": float(g["ret_t2_close"].mean()),
                "mean_ret_t3": float(g["ret_t3_close"].mean()),
                "win_t1": float((g["ret_t1_close"] > 0).mean()),
                "win_t2": float((g["ret_t2_close"] > 0).mean()),
                "win_t3": float((g["ret_t3_close"] > 0).mean()),
            }
        )
    return pd.DataFrame(rows)


def write_readme() -> None:
    txt = [
        "# True Breakout Buy Signal V1",
        "",
        "Scope: pre-market selector output to intraday buy-signal detection.",
        "",
        "## Frozen inputs",
        "- Main system: v3.2_candidate",
        "- Enhancement tag: v3.1_relaxed",
        "- priority_tag unchanged",
        "",
        "## V1 signal types",
        "1. pullback_confirm",
        "2. breakout_confirm",
        "3. range_break_confirm",
        "",
        "Mutual exclusivity: same timestamp conflict uses priority pullback > breakout > range.",
        "",
        "## Outputs",
        "- true_breakout_buy_signal_v1.csv",
        "- true_breakout_buy_signal_v1_summary.csv",
        "",
        "## Boundaries",
        "- no selector changes",
        "- no sell logic",
        "- no full backtest",
    ]
    OUT_README.write_text("\n".join(txt), encoding="utf-8")


def main() -> None:
    cfg = SignalConfig()
    mvp = _load_mvp()
    nxt = _load_next_trade_date().rename(columns={"ts_code": "stock_code"})
    mvp = mvp.merge(nxt, on=["stock_code", "trade_date"], how="left")

    # only pre-market core candidates are scanned
    pre = mvp[mvp["is_core_candidate"] == 1].copy()
    pre["buy_date"] = pre["buy_date"].astype(str)

    out_rows = []
    for row in pre.itertuples(index=False):
        rr = pd.Series(row._asdict())
        intraday = _load_intraday(rr["stock_code"], rr.get("trade_date", ""))
        sig = detect_buy_signal(rr, intraday, cfg)
        merged = {**rr.to_dict(), **sig}
        out_rows.append(merged)

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

    summary = build_summary(result)
    summary.to_csv(OUT_SUMMARY, index=False, encoding="utf-8-sig")
    write_readme()

    core_row = summary[summary["group"] == "all"].iloc[0] if not summary[summary["group"] == "all"].empty else None
    tag_row = (
        summary[summary["group"] == "priority_tag_1_triggered"].iloc[0]
        if not summary[summary["group"] == "priority_tag_1_triggered"].empty
        else None
    )
    payload = {
        "total_samples": int(len(result)),
        "core_samples": int(len(result)),
        "priority_tag_1_samples": int((result["priority_tag"] == 1).sum()),
        "triggered_samples": int((result["signal_triggered"] == 1).sum()),
        "core_mean_win": {
            "t1_mean": float(core_row["mean_ret_t1"]) if core_row is not None else None,
            "t1_win": float(core_row["win_t1"]) if core_row is not None else None,
            "t2_mean": float(core_row["mean_ret_t2"]) if core_row is not None else None,
            "t2_win": float(core_row["win_t2"]) if core_row is not None else None,
            "t3_mean": float(core_row["mean_ret_t3"]) if core_row is not None else None,
            "t3_win": float(core_row["win_t3"]) if core_row is not None else None,
        },
        "tag_triggered_mean_win": {
            "t1_mean": float(tag_row["mean_ret_t1"]) if tag_row is not None else None,
            "t1_win": float(tag_row["win_t1"]) if tag_row is not None else None,
            "t2_mean": float(tag_row["mean_ret_t2"]) if tag_row is not None else None,
            "t2_win": float(tag_row["win_t2"]) if tag_row is not None else None,
            "t3_mean": float(tag_row["mean_ret_t3"]) if tag_row is not None else None,
            "t3_win": float(tag_row["win_t3"]) if tag_row is not None else None,
        },
        "output_paths": {
            "signal": str(OUT_SIGNAL),
            "summary": str(OUT_SUMMARY),
            "readme": str(OUT_README),
        },
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
