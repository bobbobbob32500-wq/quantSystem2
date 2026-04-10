# -*- coding: utf-8 -*-
"""Analyze alternative exit profiles for legacy signal-replay trades."""

from __future__ import annotations

import argparse
import itertools
import json
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Tuple

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Analyze legacy exit profiles on replayed trades.")
    parser.add_argument(
        "--trades-file",
        default="reports/legacy_signal_replay_trades_20260329_013739.csv",
    )
    parser.add_argument(
        "--db-path",
        default="data/history_recommendation.db",
    )
    parser.add_argument(
        "--lookahead-days",
        type=int,
        default=7,
        help="Maximum calendar days of minute bars to evaluate after entry.",
    )
    return parser.parse_args()


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return float(default)


def _load_trades(path: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    df["buy_time"] = pd.to_datetime(df["buy_time"])
    df["sell_time"] = pd.to_datetime(df["sell_time"], errors="coerce")
    for col in ["buy_price", "sell_price", "pnl_pct", "peak_pnl_pct", "hold_hours"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def _load_intraday(db_path: str, symbols: List[str], start_dt: datetime, end_dt: datetime) -> pd.DataFrame:
    conn = sqlite3.connect(db_path)
    try:
        placeholders = ",".join(["?"] * len(symbols))
        df = pd.read_sql_query(
            f"""
            SELECT symbol, trade_time, trade_date, close
            FROM intraday_data
            WHERE symbol IN ({placeholders})
              AND trade_time >= ?
              AND trade_time <= ?
            ORDER BY trade_time ASC
            """,
            conn,
            params=[*symbols, start_dt.strftime("%Y-%m-%d %H:%M:%S"), end_dt.strftime("%Y-%m-%d %H:%M:%S")],
        )
    finally:
        conn.close()
    if not df.empty:
        df["trade_time"] = pd.to_datetime(df["trade_time"])
        df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.date
        df["close"] = pd.to_numeric(df["close"], errors="coerce")
        df = df.dropna(subset=["trade_time", "close"])
    return df


def _prepare_paths(
    trades: pd.DataFrame,
    intraday: pd.DataFrame,
    lookahead_days: int,
) -> Dict[int, pd.DataFrame]:
    by_symbol: Dict[str, pd.DataFrame] = {
        symbol: frame.sort_values("trade_time").reset_index(drop=True)
        for symbol, frame in intraday.groupby("symbol", sort=False)
    }
    paths: Dict[int, pd.DataFrame] = {}
    for idx, row in trades.iterrows():
        symbol = str(row["symbol"])
        frame = by_symbol.get(symbol)
        if frame is None or frame.empty:
            continue
        buy_time = pd.Timestamp(row["buy_time"]).to_pydatetime()
        end_time = buy_time + timedelta(days=max(1, lookahead_days))
        sliced = frame[(frame["trade_time"] >= buy_time) & (frame["trade_time"] <= end_time)].copy()
        if sliced.empty:
            continue
        paths[int(idx)] = sliced.reset_index(drop=True)
    return paths


def _simulate_trade(
    path: pd.DataFrame,
    buy_time: datetime,
    buy_price: float,
    stop_loss_pct: float,
    tp1_pct: float,
    tp2_pct: float,
    trailing_pct: float,
    max_hold_hours: float,
    carry_peak_arm: bool,
) -> Dict[str, Any]:
    highest_pnl = 0.0
    partial_take_done = False
    armed_from_peak = False
    buy_date = buy_time.date()

    for _, row in path.iterrows():
        trade_time = pd.Timestamp(row["trade_time"]).to_pydatetime()
        current_price = _safe_float(row["close"])
        pnl_pct = (current_price - buy_price) / buy_price if buy_price > 0 else 0.0
        highest_pnl = max(highest_pnl, pnl_pct)

        blocked = trade_time.date() == buy_date
        if carry_peak_arm and blocked and highest_pnl >= tp1_pct:
            armed_from_peak = True
        if blocked:
            continue

        if not partial_take_done and (pnl_pct >= tp1_pct or (carry_peak_arm and armed_from_peak)):
            partial_take_done = True

        reason = ""
        if pnl_pct <= stop_loss_pct:
            reason = "stop_loss"
        elif pnl_pct >= tp2_pct:
            reason = "take_profit"
        elif partial_take_done and (highest_pnl - pnl_pct) >= trailing_pct:
            reason = "trailing_stop"
        else:
            hold_hours = (trade_time - buy_time).total_seconds() / 3600.0
            if hold_hours >= max_hold_hours:
                reason = "time_exit"

        if not reason and partial_take_done and pnl_pct <= -0.001:
            reason = "break_even_stop"

        if reason:
            return {
                "sell_time": trade_time,
                "sell_price": current_price,
                "sell_reason": reason,
                "pnl_pct": pnl_pct,
                "peak_pnl_pct": highest_pnl,
                "hold_hours": (trade_time - buy_time).total_seconds() / 3600.0,
            }

    last = path.iloc[-1]
    last_time = pd.Timestamp(last["trade_time"]).to_pydatetime()
    last_price = _safe_float(last["close"])
    final_pnl = (last_price - buy_price) / buy_price if buy_price > 0 else 0.0
    return {
        "sell_time": last_time,
        "sell_price": last_price,
        "sell_reason": "forced_end",
        "pnl_pct": final_pnl,
        "peak_pnl_pct": highest_pnl,
        "hold_hours": (last_time - buy_time).total_seconds() / 3600.0,
    }


def _summarize(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    df = pd.DataFrame(results)
    if df.empty:
        return {
            "trade_count": 0,
            "win_rate": 0.0,
            "avg_pnl_pct": 0.0,
            "avg_peak_pnl_pct": 0.0,
            "avg_giveback_pct": 0.0,
            "profit_loss_ratio": 0.0,
        }
    pnl = pd.to_numeric(df["pnl_pct"], errors="coerce")
    peak = pd.to_numeric(df["peak_pnl_pct"], errors="coerce")
    giveback = peak - pnl
    wins = pnl[pnl > 0]
    losses = pnl[pnl < 0]
    avg_loss = abs(float(losses.mean())) if not losses.empty else 0.0
    return {
        "trade_count": int(len(df)),
        "win_rate": float((pnl > 0).mean()),
        "avg_pnl_pct": float(pnl.mean()),
        "avg_peak_pnl_pct": float(peak.mean()),
        "avg_giveback_pct": float(giveback.mean()),
        "profit_loss_ratio": float(wins.mean() / avg_loss) if avg_loss > 0 and not wins.empty else 0.0,
    }


def main() -> None:
    args = parse_args()
    trades = _load_trades(args.trades_file)
    symbols = sorted(trades["symbol"].astype(str).unique().tolist())
    intraday = _load_intraday(
        db_path=args.db_path,
        symbols=symbols,
        start_dt=trades["buy_time"].min().to_pydatetime(),
        end_dt=(trades["buy_time"].max() + pd.Timedelta(days=args.lookahead_days)).to_pydatetime(),
    )
    paths = _prepare_paths(trades, intraday, lookahead_days=args.lookahead_days)

    baseline_rows = []
    for _, row in trades.iterrows():
        baseline_rows.append(
            {
                "buy_route_label": row["buy_route_label"],
                "pnl_pct": _safe_float(row["pnl_pct"]),
                "peak_pnl_pct": _safe_float(row["peak_pnl_pct"]),
            }
        )

    candidate_profiles = []
    for stop_loss, tp1, trailing, max_hold, carry_peak_arm in itertools.product(
        [-0.045, -0.05, -0.055],
        [0.05, 0.06, 0.07],
        [0.025, 0.03],
        [48.0, 72.0, 96.0],
        [False, True],
    ):
        tp2 = tp1 + 0.04
        candidate_profiles.append(
            {
                "stop_loss_pct": stop_loss,
                "tp1_pct": tp1,
                "tp2_pct": tp2,
                "trailing_pct": trailing,
                "max_hold_hours": max_hold,
                "carry_peak_arm": carry_peak_arm,
            }
        )

    route_reports: Dict[str, Any] = {}
    route_names = sorted(trades["buy_route_label"].dropna().astype(str).unique().tolist())
    for route in route_names:
        route_trades = trades[trades["buy_route_label"] == route].copy()
        baseline = _summarize(
            [row for row in baseline_rows if row["buy_route_label"] == route]
        )

        ranked: List[Dict[str, Any]] = []
        for profile in candidate_profiles:
            results: List[Dict[str, Any]] = []
            for idx, row in route_trades.iterrows():
                path = paths.get(int(idx))
                if path is None or path.empty:
                    continue
                sim = _simulate_trade(
                    path=path,
                    buy_time=pd.Timestamp(row["buy_time"]).to_pydatetime(),
                    buy_price=_safe_float(row["buy_price"]),
                    stop_loss_pct=profile["stop_loss_pct"],
                    tp1_pct=profile["tp1_pct"],
                    tp2_pct=profile["tp2_pct"],
                    trailing_pct=profile["trailing_pct"],
                    max_hold_hours=profile["max_hold_hours"],
                    carry_peak_arm=profile["carry_peak_arm"],
                )
                results.append(sim)

            stats = _summarize(results)
            objective = (
                stats["avg_pnl_pct"] * 100.0
                + stats["win_rate"] * 6.0
                - stats["avg_giveback_pct"] * 30.0
            )
            ranked.append(
                {
                    **profile,
                    **stats,
                    "objective": objective,
                }
            )

        ranked.sort(
            key=lambda item: (
                -item["objective"],
                -item["avg_pnl_pct"],
                -item["win_rate"],
                item["avg_giveback_pct"],
            )
        )
        route_reports[route] = {
            "baseline": baseline,
            "top_profiles": ranked[:10],
            "recommended_profile": ranked[0] if ranked else None,
        }

    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    reports_dir = ROOT / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    json_path = reports_dir / f"legacy_exit_profile_analysis_{run_id}.json"
    md_path = reports_dir / f"legacy_exit_profile_analysis_{run_id}.md"

    payload = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "trades_file": str(Path(args.trades_file).resolve()),
        "route_reports": route_reports,
    }
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        "# 原策略卖点参数扫描",
        "",
        f"- 生成时间: {payload['generated_at']}",
        f"- 交易样本: {len(trades)}",
        "",
    ]
    for route, report in route_reports.items():
        base = report["baseline"]
        rec = report["recommended_profile"] or {}
        lines.extend(
            [
                f"## {route}",
                "",
                "- 基线: 胜率 {win:.2f}% | 平均收益 {ret:+.2f}% | 平均回吐 {gb:+.2f}%".format(
                    win=base["win_rate"] * 100.0,
                    ret=base["avg_pnl_pct"] * 100.0,
                    gb=base["avg_giveback_pct"] * 100.0,
                ),
                "- 推荐: stop {sl:+.1f}% | tp1 {tp1:.1f}% | tp2 {tp2:.1f}% | trailing {tr:.1f}% | hold {hold:.0f}h | carry_peak_arm={arm}".format(
                    sl=rec.get("stop_loss_pct", 0.0) * 100.0,
                    tp1=rec.get("tp1_pct", 0.0) * 100.0,
                    tp2=rec.get("tp2_pct", 0.0) * 100.0,
                    tr=rec.get("trailing_pct", 0.0) * 100.0,
                    hold=rec.get("max_hold_hours", 0.0),
                    arm=rec.get("carry_peak_arm", False),
                ),
                "- 推荐效果: 胜率 {win:.2f}% | 平均收益 {ret:+.2f}% | 平均回吐 {gb:+.2f}%".format(
                    win=rec.get("win_rate", 0.0) * 100.0,
                    ret=rec.get("avg_pnl_pct", 0.0) * 100.0,
                    gb=rec.get("avg_giveback_pct", 0.0) * 100.0,
                ),
                "",
            ]
        )
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(json.dumps({"json": str(json_path), "markdown": str(md_path)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
