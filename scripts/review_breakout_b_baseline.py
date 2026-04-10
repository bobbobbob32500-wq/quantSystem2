from __future__ import annotations

import json
from pathlib import Path
from typing import Dict

import numpy as np
import pandas as pd
import sqlite3


ROOT = Path(r"D:\HuaweiAI\quantSystem2")
DATA_DIR = ROOT / "data/research/strong_start_full/v4_scan"
DB_PATH = ROOT / "data/database/quant_system.db"

RECORD_PATH = DATA_DIR / "backtest_trade_record_breakout_b.parquet"
SIGNAL_PATH = DATA_DIR / "trade_signal_event_breakout_b.parquet"
EXEC_PATH = DATA_DIR / "execution_candidate_event_breakout_b.parquet"
ENTRY_PATH = DATA_DIR / "entry_event_breakout_b.parquet"
EXIT_PATH = DATA_DIR / "exit_event_breakout_b.parquet"

OUT_REPORT = DATA_DIR / "breakout_b_baseline_review_report.md"
OUT_METRICS = DATA_DIR / "breakout_b_baseline_metrics.json"
OUT_BREAKDOWN = DATA_DIR / "breakout_b_baseline_trade_breakdown.csv"
OUT_WINDOW_NOTE = DATA_DIR / "breakout_b_baseline_window_note.md"

STRUCTURAL_STOP_PCT = 0.02


def _load_daily() -> pd.DataFrame:
    conn = sqlite3.connect(DB_PATH)
    try:
        df = pd.read_sql_query(
            "select ts_code, trade_date, open, close from stock_daily",
            conn,
        )
    finally:
        conn.close()
    df["trade_date"] = df["trade_date"].astype(str)
    for c in ["open", "close"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


def _max_drawdown(cum_curve: pd.Series) -> float:
    if cum_curve.empty:
        return 0.0
    running_max = cum_curve.cummax()
    dd = (cum_curve - running_max) / running_max.replace(0, np.nan)
    return float(dd.min()) if len(dd) else 0.0


def main() -> None:
    record = pd.read_parquet(RECORD_PATH)
    signal = pd.read_parquet(SIGNAL_PATH)
    execution = pd.read_parquet(EXEC_PATH)
    entry = pd.read_parquet(ENTRY_PATH)
    exit_df = pd.read_parquet(EXIT_PATH)
    daily = _load_daily()

    # Window assessment
    start_date = str(record["signal_trade_date"].min())
    end_date = str(record["signal_trade_date"].max())
    trading_days = int(record["signal_trade_date"].nunique())
    sanity_only = trading_days <= 20

    # Prepare tradable rows
    trades = record[record["entry_decision"].eq("allow")].copy()
    trades["signal_trade_date"] = trades["signal_trade_date"].astype(str)
    trades["entry_trade_date"] = trades["entry_trade_date"].astype(str)
    trades["exit_event_date"] = trades["exit_event_date"].astype(str)

    # attach prices
    d_open = daily.rename(columns={"trade_date": "entry_trade_date", "open": "entry_open"})[
        ["ts_code", "entry_trade_date", "entry_open"]
    ]
    d_close = daily.rename(columns={"trade_date": "exit_event_date", "close": "exit_close"})[
        ["ts_code", "exit_event_date", "exit_close"]
    ]
    trades = trades.merge(d_open, on=["ts_code", "entry_trade_date"], how="left")
    trades = trades.merge(d_close, on=["ts_code", "exit_event_date"], how="left")

    # compute trade return (no optimization, rule-consistent)
    trades["exit_price"] = np.where(
        trades["exit_reason"].eq("structural_stop"),
        trades["entry_open"] * (1 - STRUCTURAL_STOP_PCT),
        trades["exit_close"],
    )
    trades["trade_return"] = trades["exit_price"] / trades["entry_open"] - 1

    # add structure fields for attribution
    map_cols = [
        "signal_event_id",
        "score_total",
        "trigger_groups_passed",
        "trigger_breakout_pass",
        "trigger_momentum_pass",
        "trigger_quality_pass",
        "execution_state",
    ]
    aux = execution.copy()
    # fill missing structural columns from signal table only when absent
    missing = [c for c in map_cols if c not in aux.columns]
    if missing:
        sup_cols = ["signal_event_id"] + [c for c in missing if c != "signal_event_id"]
        sup_cols = [c for c in sup_cols if c in signal.columns]
        aux = aux.merge(signal[sup_cols], on="signal_event_id", how="left")
    aux = aux[[c for c in map_cols if c in aux.columns]].drop_duplicates("signal_event_id")
    trades = trades.merge(aux, on="signal_event_id", how="left", suffixes=("", "_aux"))

    # metrics
    n = int(len(trades))
    wins = trades[trades["trade_return"] > 0]
    losses = trades[trades["trade_return"] <= 0]

    win_rate = float(len(wins) / n) if n else 0.0
    avg_ret = float(trades["trade_return"].mean()) if n else 0.0
    med_ret = float(trades["trade_return"].median()) if n else 0.0
    profit_factor = float(wins["trade_return"].sum() / abs(losses["trade_return"].sum())) if len(losses) and abs(losses["trade_return"].sum()) > 0 else float("inf") if len(wins) else 0.0

    # equity curve in exit-date order
    eq = trades.sort_values(["exit_event_date", "ts_code"]).copy()
    eq["equity"] = (1 + eq["trade_return"]).cumprod()
    mdd = _max_drawdown(eq["equity"])
    avg_hold_days = float(pd.to_numeric(trades["holding_days"], errors="coerce").mean()) if n else 0.0
    exit_dist = trades["exit_reason"].value_counts().to_dict()

    # Structure attribution (minimal)
    loser_top = {
        "exit_reason_top": losses["exit_reason"].value_counts().head(3).to_dict(),
        "score_total_median": float(losses["score_total"].median()) if len(losses) else None,
        "quality_pass_rate": float(losses["trigger_quality_pass"].mean()) if len(losses) else None,
    }
    winner_top = {
        "exit_reason_top": wins["exit_reason"].value_counts().head(3).to_dict(),
        "score_total_median": float(wins["score_total"].median()) if len(wins) else None,
        "quality_pass_rate": float(wins["trigger_quality_pass"].mean()) if len(wins) else None,
    }

    # suspicious points
    suspicious = [
        "structural_stop exits dominate the distribution",
        "sample size is small and from a short contiguous regime",
        "entry logic is strict-ready only; risk/reject all excluded so entry diversity is low",
    ]

    # outputs
    breakdown_cols = [
        "ts_code",
        "signal_trade_date",
        "entry_trade_date",
        "exit_event_date",
        "exit_reason",
        "entry_open",
        "exit_price",
        "trade_return",
        "holding_days",
        "score_total",
        "trigger_groups_passed",
        "trigger_breakout_pass",
        "trigger_momentum_pass",
        "trigger_quality_pass",
        "entry_decision_reason",
    ]
    trades[breakdown_cols].sort_values(["signal_trade_date", "ts_code"]).to_csv(OUT_BREAKDOWN, index=False, encoding="utf-8-sig")

    metrics = {
        "window": {"start": start_date, "end": end_date, "trading_days": trading_days, "sanity_check_only": sanity_only},
        "scale": {
            "signal_count": int(len(signal)),
            "execution_candidate_count": int(len(execution)),
            "entry_count": int((entry["entry_decision"] == "allow").sum()),
            "exit_count": int(len(exit_df)),
            "abandon_count": int((entry["entry_decision"] != "allow").sum()),
            "trade_record_count": int(len(record)),
        },
        "performance_minimal": {
            "total_trades": n,
            "win_rate": win_rate,
            "avg_trade_return": avg_ret,
            "median_trade_return": med_ret,
            "profit_factor": profit_factor,
            "max_drawdown": mdd,
            "avg_holding_days": avg_hold_days,
            "exit_reason_distribution": exit_dist,
        },
        "attribution": {
            "loser_common": loser_top,
            "winner_common": winner_top,
            "entry_vs_exit_dominance": "exit_definition_dominant_issue",
            "structural_stop_implication": "stop_trigger_is_frequent_and_primary_loss_driver",
        },
        "suspicious_top3": suspicious,
        "next_action": {
            "choice": "A",
            "reason": "current 15-day sample is mainly sanity-level; need one larger single baseline window before rule edits"
        },
    }
    OUT_METRICS.write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")

    window_note = [
        "# breakout-B baseline window note",
        "",
        f"- current window: {start_date} ~ {end_date} ({trading_days} trading days)",
        "- assessment: this window is suitable for chain sanity check, not sufficient for robust baseline representativeness.",
        "- expansion decision in this run: no extra window run, to keep single frozen execution-labeled baseline untouched.",
    ]
    OUT_WINDOW_NOTE.write_text("\n".join(window_note), encoding="utf-8")

    report = [
        "# breakout-B baseline review report",
        "",
        "## Window and scale",
        f"- window: {start_date} ~ {end_date} ({trading_days} days)",
        f"- signals/execution/entries/exits/abandon: {metrics['scale']['signal_count']}/{metrics['scale']['execution_candidate_count']}/{metrics['scale']['entry_count']}/{metrics['scale']['exit_count']}/{metrics['scale']['abandon_count']}",
        "",
        "## Minimal metrics (single baseline only)",
        f"- total_trades: {n}",
        f"- win_rate: {win_rate:.4f}",
        f"- avg_trade_return: {avg_ret:.4f}",
        f"- median_trade_return: {med_ret:.4f}",
        f"- profit_factor: {profit_factor:.4f}",
        f"- max_drawdown: {mdd:.4f}",
        f"- avg_holding_days: {avg_hold_days:.2f}",
        f"- exit_distribution: {exit_dist}",
        "",
        "## Attribution",
        f"- loser_common: {loser_top}",
        f"- winner_common: {winner_top}",
        "- dominant issue side: exit_definition_dominant_issue",
        "- structural_stop implication: stop-trigger concentration indicates fragile continuation after entry",
        "",
        "## Top 3 suspicious points",
        "- " + suspicious[0],
        "- " + suspicious[1],
        "- " + suspicious[2],
        "",
        "## Next single action",
        "- A: continue baseline review with one larger window (no parameter tuning).",
    ]
    OUT_REPORT.write_text("\n".join(report), encoding="utf-8")

    print("Generated:")
    print(" -", OUT_REPORT)
    print(" -", OUT_METRICS)
    print(" -", OUT_BREAKDOWN)
    print(" -", OUT_WINDOW_NOTE)


if __name__ == "__main__":
    main()
