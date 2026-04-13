# -*- coding: utf-8 -*-
"""
Strong-start strategy baseline backtest (daily approximation).

Process:
1) T day selection -> candidate list.
2) Enter on T+1 when breakout trigger is touched.
3) Hold up to N days with structure stop-loss.
4) Export trade details and markdown summary.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.core.config import ConfigManager
from src.core.database import DatabaseManager
from src.modules.strong_start_strategy import StrongStartParams, StrongStartStrategy


def _fmt_pct(value: float) -> str:
    if value is None or pd.isna(value):
        return "N/A"
    return f"{float(value):.2%}"


def _write_json(path: str, payload: dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def _resolve_backtest_window(
    all_dates: List[str],
    start_date: Optional[str],
    end_date: Optional[str],
    years: int,
    min_window_days: int = 30,
) -> Tuple[List[str], str, str]:
    if not all_dates:
        return [], "", ""

    start = start_date or ""
    end = end_date or all_dates[-1]

    if not start:
        end_dt = datetime.strptime(end, "%Y%m%d")
        approx_start = (end_dt - pd.Timedelta(days=365 * max(years, 1))).strftime("%Y%m%d")
        start = approx_start

    selected = [d for d in all_dates if start <= d <= end]
    min_need = max(int(min_window_days), 1)
    if len(selected) < min_need:
        return [], start, end
    return selected, start, end


def _build_price_map(features: pd.DataFrame) -> Dict[str, pd.DataFrame]:
    px = features[["ts_code", "trade_date", "open", "high", "low", "close"]].copy()
    px = px.dropna(subset=["ts_code", "trade_date", "open", "high", "low", "close"])
    px = px.sort_values(["ts_code", "trade_date"]).reset_index(drop=True)
    px["trade_date"] = px["trade_date"].dt.strftime("%Y%m%d")
    out: Dict[str, pd.DataFrame] = {}
    for ts_code, sub in px.groupby("ts_code"):
        out[str(ts_code)] = sub.reset_index(drop=True)
    return out


def _evaluate_trade(
    bars: pd.DataFrame,
    entry_idx: int,
    entry_price: float,
    stop_loss: float,
    hold_days: int,
    intrabar_policy: str = "midpoint",
) -> Optional[dict]:
    risk = entry_price - stop_loss
    if risk <= 0:
        return None

    max_idx = min(entry_idx + hold_days - 1, len(bars) - 1)
    exit_price = float(bars.loc[max_idx, "close"])
    exit_idx = max_idx
    exit_reason = "time_exit"

    target_1r = entry_price + risk
    target_2r = entry_price + 2.0 * risk
    target_3r = entry_price + 3.0 * risk
    hit_1r = False
    hit_2r = False
    hit_3r = False
    ambiguous_intrabar = False

    for i in range(entry_idx, max_idx + 1):
        o = float(bars.loc[i, "open"])
        h = float(bars.loc[i, "high"])
        l = float(bars.loc[i, "low"])

        if o <= stop_loss:
            exit_price = o
            exit_idx = i
            exit_reason = "gap_stop"
            break
        hit_stop = l <= stop_loss
        hit_1r_now = h >= target_1r
        hit_2r_now = h >= target_2r
        hit_3r_now = h >= target_3r

        if hit_stop and hit_1r_now:
            ambiguous_intrabar = True
            if intrabar_policy == "target_first":
                exit_price = target_1r
                exit_idx = i
                exit_reason = "target1_intrabar"
            elif intrabar_policy == "stop_first":
                exit_price = stop_loss
                exit_idx = i
                exit_reason = "stop_loss_intrabar"
            else:
                # Neutral daily approximation when intrabar path is unknown.
                exit_price = (stop_loss + target_1r) / 2.0
                exit_idx = i
                exit_reason = "intrabar_mid"
            hit_1r = True
            if hit_2r_now:
                hit_2r = True
            if hit_3r_now:
                hit_3r = True
            break

        if hit_stop:
            exit_price = stop_loss
            exit_idx = i
            exit_reason = "stop_loss"
            break

        if hit_1r_now:
            hit_1r = True
        if hit_2r_now:
            hit_2r = True
        if hit_3r_now:
            hit_3r = True

    pnl_pct = exit_price / entry_price - 1.0
    r_multiple = (exit_price - entry_price) / risk
    return {
        "exit_idx": exit_idx,
        "exit_price": exit_price,
        "exit_reason": exit_reason,
        "pnl_pct": pnl_pct,
        "r_multiple": r_multiple,
        "risk_pct": risk / entry_price,
        "hit_1r": int(hit_1r),
        "hit_2r": int(hit_2r),
        "hit_3r": int(hit_3r),
        "ambiguous_intrabar": int(ambiguous_intrabar),
    }


def _summarize(trades: pd.DataFrame) -> Dict[str, float]:
    out = {
        "n_trades": 0,
        "win_rate": np.nan,
        "avg_ret": np.nan,
        "median_ret": np.nan,
        "avg_r": np.nan,
        "payoff": np.nan,
        "profit_factor": np.nan,
        "hit_1r_rate": np.nan,
        "hit_2r_rate": np.nan,
        "hit_3r_rate": np.nan,
        "port_total_ret": np.nan,
        "port_mdd": np.nan,
        "port_sharpe": np.nan,
        "ambiguous_intrabar_rate": np.nan,
    }
    if trades.empty:
        return out

    pnl = trades["pnl_pct"].dropna()
    if pnl.empty:
        return out

    out["n_trades"] = int(len(pnl))
    out["win_rate"] = float((pnl > 0).mean())
    out["avg_ret"] = float(pnl.mean())
    out["median_ret"] = float(pnl.median())
    out["avg_r"] = float(trades["r_multiple"].dropna().mean())
    wins = pnl[pnl > 0]
    losses = pnl[pnl < 0]
    out["payoff"] = float(wins.mean() / abs(losses.mean())) if not wins.empty and not losses.empty else np.nan
    out["profit_factor"] = float(wins.sum() / abs(losses.sum())) if not wins.empty and not losses.empty else np.nan
    out["hit_1r_rate"] = float(trades["hit_1r"].mean())
    out["hit_2r_rate"] = float(trades["hit_2r"].mean())
    out["hit_3r_rate"] = float(trades["hit_3r"].mean())
    if "ambiguous_intrabar" in trades.columns:
        out["ambiguous_intrabar_rate"] = float(trades["ambiguous_intrabar"].mean())

    daily = trades.groupby("entry_date")["pnl_pct"].mean().dropna().sort_index()
    if not daily.empty:
        equity = (1.0 + daily).cumprod()
        out["port_total_ret"] = float(equity.iloc[-1] - 1.0)
        out["port_mdd"] = float((equity / equity.cummax() - 1.0).min())
        out["port_sharpe"] = (
            float(daily.mean() / daily.std() * np.sqrt(252))
            if daily.std() and float(daily.std()) > 1e-12
            else 0.0
        )
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="Run strong-start baseline backtest.")
    parser.add_argument("--start-date", type=str, default="", help="YYYYMMDD")
    parser.add_argument("--end-date", type=str, default="", help="YYYYMMDD")
    parser.add_argument("--years", type=int, default=3, help="lookback years when start-date not provided")
    parser.add_argument("--hold-days", type=int, default=5, help="max holding days")
    parser.add_argument("--top-k", type=int, default=15, help="daily top K candidates")
    parser.add_argument("--min-score", type=float, default=60.0, help="minimum signal score")
    parser.add_argument("--checkpoint-every-days", type=int, default=10, help="write progress every N signal days")
    parser.add_argument("--progress-file", type=str, default="", help="optional path for progress json")
    parser.add_argument(
        "--intrabar-policy",
        type=str,
        default="midpoint",
        choices=["midpoint", "stop_first", "target_first"],
        help="daily intrabar ambiguity handling policy",
    )
    parser.add_argument(
        "--preset",
        type=str,
        default="tradeable_v1",
        choices=[
            "default",
            "tradeable_v1",
            "tradeable_v2",
            "tradeable_v3_research",
            "tradeable_v4_parameter_reverse_loose",
        ],
        help="parameter preset",
    )
    parser.add_argument(
        "--min-window-days",
        type=int,
        default=30,
        help="区间内最少交易日数（样本外仅两自然月时可能不足 30，可改为 20）",
    )
    args = parser.parse_args()

    config = ConfigManager()
    db = DatabaseManager(config)

    if args.preset == "tradeable_v1":
        strategy_params = StrongStartParams.tradeable_v1()
    elif args.preset == "tradeable_v2":
        strategy_params = StrongStartParams.tradeable_v2()
    elif args.preset == "tradeable_v3_research":
        strategy_params = StrongStartParams.tradeable_v3_research()
    elif args.preset == "tradeable_v4_parameter_reverse_loose":
        strategy_params = StrongStartParams.tradeable_v4_parameter_reverse_loose()
    else:
        strategy_params = StrongStartParams()
    strategy_params.top_k = max(int(args.top_k), 1)
    strategy_params.min_signal_score = float(args.min_score)
    strategy_params.chip_factor_strict_mode = True
    strategy = StrongStartStrategy(db=db, params=strategy_params)

    daily_dates = db.query("SELECT DISTINCT trade_date FROM stock_daily ORDER BY trade_date ASC")
    all_dates = [str(r["trade_date"]) for r in daily_dates]
    test_dates, start_date, end_date = _resolve_backtest_window(
        all_dates=all_dates,
        start_date=args.start_date,
        end_date=args.end_date,
        years=int(args.years),
        min_window_days=int(args.min_window_days),
    )
    if not test_dates:
        print("No enough trade dates in requested window.")
        return

    print("=" * 70)
    print("Strong-start baseline backtest")
    print("=" * 70)
    print(f"Window: {start_date} -> {end_date}, days={len(test_dates)}")

    raw_daily, raw_basic, raw_chip, raw_chip_dist = strategy._load_data(end_date)
    features = strategy._compute_features(raw_daily, raw_basic, raw_chip, raw_chip_dist)
    if features.empty:
        print("No features generated, abort.")
        return

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    out_dir = os.path.join(root, "data", "reports")
    os.makedirs(out_dir, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    progress_latest = args.progress_file or os.path.join(out_dir, "strong_start_backtest_progress_latest.json")
    progress_stamp = os.path.join(out_dir, f"strong_start_backtest_progress_{stamp}.json")
    checkpoint_every = max(int(args.checkpoint_every_days), 1)
    total_signal_days = max(len(test_dates) - 1, 1)
    start_ts = time.time()

    _write_json(
        progress_latest,
        {
            "status": "running",
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "window": {"start_date": start_date, "end_date": end_date, "days": len(test_dates)},
            "preset": args.preset,
            "intrabar_policy": args.intrabar_policy,
            "progress": {"processed_signal_days": 0, "total_signal_days": total_signal_days, "progress_pct": 0.0},
            "trades_count": 0,
            "last_signal_date": "",
            "checkpoint_every_days": checkpoint_every,
        },
    )

    price_map = _build_price_map(features)
    date_pos = {d: i for i, d in enumerate(all_dates)}
    trades: List[dict] = []

    for i, td in enumerate(test_dates[:-1]):
        if (i + 1) % 20 == 0:
            print(f"Progress {i+1}/{len(test_dates)-1}")

        cands = strategy.select_candidates_from_features(features, td)
        next_idx = date_pos.get(td, -1) + 1
        if cands and next_idx > 0 and next_idx < len(all_dates):
            entry_date = all_dates[next_idx]
            for item in cands:
                ts_code = str(item.ts_code)
                bars = price_map.get(ts_code)
                if bars is None or bars.empty:
                    continue
                hit = bars.index[bars["trade_date"] == entry_date]
                if len(hit) == 0:
                    continue
                eidx = int(hit[0])
                bar = bars.loc[eidx]
                trigger = float(item.trigger_price)
                day_open = float(bar["open"])
                day_high = float(bar["high"])

                if day_high < trigger:
                    continue
                entry_price = max(day_open, trigger)
                eval_result = _evaluate_trade(
                    bars=bars,
                    entry_idx=eidx,
                    entry_price=entry_price,
                    stop_loss=float(item.stop_loss),
                    hold_days=max(int(args.hold_days), 1),
                    intrabar_policy=str(args.intrabar_policy),
                )
                if not eval_result:
                    continue

                exit_idx = int(eval_result["exit_idx"])
                trade = {
                    "signal_date": td,
                    "entry_date": entry_date,
                    "exit_date": str(bars.loc[exit_idx, "trade_date"]),
                    "hold_bars": int(exit_idx - eidx + 1),
                    "ts_code": ts_code,
                    "name": item.name,
                    "setup_type": item.setup_type,
                    "signal_score": float(item.signal_score),
                    "single_peak_dense_score": float(item.single_peak_dense_score),
                    "trigger_price": float(item.trigger_price),
                    "stop_loss": float(item.stop_loss),
                    "entry_price": float(entry_price),
                    "exit_price": float(eval_result["exit_price"]),
                    "exit_reason": str(eval_result["exit_reason"]),
                    "pnl_pct": float(eval_result["pnl_pct"]),
                    "r_multiple": float(eval_result["r_multiple"]),
                    "risk_pct": float(eval_result["risk_pct"]),
                    "hit_1r": int(eval_result["hit_1r"]),
                    "hit_2r": int(eval_result["hit_2r"]),
                    "hit_3r": int(eval_result["hit_3r"]),
                    "ambiguous_intrabar": int(eval_result["ambiguous_intrabar"]),
                    "volume_ratio": float(item.volume_ratio),
                    "platform_range": float(item.platform_range),
                    "chip_concentration": float(item.chip_concentration),
                    "chip_low_position": float(item.chip_low_position),
                }
                trades.append(trade)

        processed_days = i + 1
        if processed_days % checkpoint_every == 0 or processed_days == total_signal_days:
            elapsed = max(time.time() - start_ts, 1e-9)
            speed = processed_days / elapsed
            remain_days = max(total_signal_days - processed_days, 0)
            eta_sec = remain_days / max(speed, 1e-9)
            _write_json(
                progress_latest,
                {
                    "status": "running",
                    "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "window": {"start_date": start_date, "end_date": end_date, "days": len(test_dates)},
                    "preset": args.preset,
                    "intrabar_policy": args.intrabar_policy,
                    "progress": {
                        "processed_signal_days": processed_days,
                        "total_signal_days": total_signal_days,
                        "progress_pct": round(processed_days / total_signal_days * 100.0, 2),
                    },
                    "runtime": {
                        "elapsed_sec": round(elapsed, 2),
                        "eta_sec": round(eta_sec, 2),
                        "signal_days_per_sec": round(speed, 4),
                    },
                    "trades_count": len(trades),
                    "last_signal_date": td,
                    "checkpoint_every_days": checkpoint_every,
                },
            )

    trades_df = pd.DataFrame(trades)
    summary = _summarize(trades_df)

    trades_latest = os.path.join(out_dir, "strong_start_backtest_trades_latest.csv")
    trades_stamp = os.path.join(out_dir, f"strong_start_backtest_trades_{stamp}.csv")
    summary_latest = os.path.join(out_dir, "strong_start_backtest_summary_latest.md")
    summary_stamp = os.path.join(out_dir, f"strong_start_backtest_summary_{stamp}.md")

    if not trades_df.empty:
        trades_df = trades_df.sort_values(["entry_date", "ts_code"]).reset_index(drop=True)
        trades_df.to_csv(trades_latest, index=False, encoding="utf-8-sig")
        trades_df.to_csv(trades_stamp, index=False, encoding="utf-8-sig")

    lines = []
    lines.append("# Strong-start baseline backtest\n\n")
    lines.append(f"- generated_at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
    lines.append(f"- window: {start_date} -> {end_date}\n")
    lines.append(f"- hold_days: {int(args.hold_days)}\n")
    lines.append(f"- preset: {args.preset}\n")
    lines.append(f"- top_k: {int(args.top_k)}\n")
    lines.append(f"- min_signal_score: {float(args.min_score):.2f}\n")
    lines.append(f"- intrabar_policy: {args.intrabar_policy}\n")
    lines.append(f"- trades: {int(summary['n_trades'])}\n\n")

    lines.append("## Metrics\n\n")
    lines.append("| metric | value |\n| --- | --- |\n")
    lines.append(f"| win_rate | {_fmt_pct(summary['win_rate'])} |\n")
    lines.append(f"| avg_ret | {_fmt_pct(summary['avg_ret'])} |\n")
    lines.append(f"| median_ret | {_fmt_pct(summary['median_ret'])} |\n")
    lines.append(f"| avg_r | {summary['avg_r']:.3f} |\n" if not pd.isna(summary["avg_r"]) else "| avg_r | N/A |\n")
    lines.append(f"| payoff | {summary['payoff']:.3f} |\n" if not pd.isna(summary["payoff"]) else "| payoff | N/A |\n")
    lines.append(
        f"| profit_factor | {summary['profit_factor']:.3f} |\n"
        if not pd.isna(summary["profit_factor"])
        else "| profit_factor | N/A |\n"
    )
    lines.append(f"| hit_1r_rate | {_fmt_pct(summary['hit_1r_rate'])} |\n")
    lines.append(f"| hit_2r_rate | {_fmt_pct(summary['hit_2r_rate'])} |\n")
    lines.append(f"| hit_3r_rate | {_fmt_pct(summary['hit_3r_rate'])} |\n")
    lines.append(f"| ambiguous_intrabar_rate | {_fmt_pct(summary['ambiguous_intrabar_rate'])} |\n")
    lines.append(f"| port_total_ret | {_fmt_pct(summary['port_total_ret'])} |\n")
    lines.append(f"| port_mdd | {_fmt_pct(summary['port_mdd'])} |\n")
    lines.append(
        f"| port_sharpe | {summary['port_sharpe']:.3f} |\n"
        if not pd.isna(summary["port_sharpe"])
        else "| port_sharpe | N/A |\n"
    )

    payload = "".join(lines)
    with open(summary_latest, "w", encoding="utf-8") as f:
        f.write(payload)
    with open(summary_stamp, "w", encoding="utf-8") as f:
        f.write(payload)

    elapsed_total = max(time.time() - start_ts, 0.0)
    progress_done = {
        "status": "completed",
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "window": {"start_date": start_date, "end_date": end_date, "days": len(test_dates)},
        "preset": args.preset,
        "intrabar_policy": args.intrabar_policy,
        "progress": {
            "processed_signal_days": total_signal_days,
            "total_signal_days": total_signal_days,
            "progress_pct": 100.0,
        },
        "runtime": {
            "elapsed_sec": round(elapsed_total, 2),
            "signal_days_per_sec": round(total_signal_days / max(elapsed_total, 1e-9), 4),
        },
        "trades_count": int(summary["n_trades"]),
        "summary": {
            "win_rate": None if pd.isna(summary["win_rate"]) else float(summary["win_rate"]),
            "avg_ret": None if pd.isna(summary["avg_ret"]) else float(summary["avg_ret"]),
            "profit_factor": None if pd.isna(summary["profit_factor"]) else float(summary["profit_factor"]),
            "port_total_ret": None if pd.isna(summary["port_total_ret"]) else float(summary["port_total_ret"]),
            "port_mdd": None if pd.isna(summary["port_mdd"]) else float(summary["port_mdd"]),
            "port_sharpe": None if pd.isna(summary["port_sharpe"]) else float(summary["port_sharpe"]),
            "ambiguous_intrabar_rate": (
                None if pd.isna(summary["ambiguous_intrabar_rate"]) else float(summary["ambiguous_intrabar_rate"])
            ),
        },
        "files": {
            "summary_latest": summary_latest,
            "summary_stamp": summary_stamp,
            "trades_latest": trades_latest,
            "trades_stamp": trades_stamp,
        },
    }
    _write_json(progress_latest, progress_done)
    _write_json(progress_stamp, progress_done)

    print(f"Trades CSV: {trades_latest}")
    print(f"Summary: {summary_latest}")
    print(f"Progress: {progress_latest}")
    print("-" * 70)
    print(f"Trades={int(summary['n_trades'])}  WinRate={_fmt_pct(summary['win_rate'])}  AvgRet={_fmt_pct(summary['avg_ret'])}")
    print(
        f"Payoff={'N/A' if pd.isna(summary['payoff']) else f'{summary['payoff']:.3f}'}  "
        f"PF={'N/A' if pd.isna(summary['profit_factor']) else f'{summary['profit_factor']:.3f}'}"
    )
    print(
        f"1R={_fmt_pct(summary['hit_1r_rate'])}  2R={_fmt_pct(summary['hit_2r_rate'])}  3R={_fmt_pct(summary['hit_3r_rate'])}  "
        f"Ambi={_fmt_pct(summary['ambiguous_intrabar_rate'])}"
    )
    print(
        f"PortRet={_fmt_pct(summary['port_total_ret'])}  MDD={_fmt_pct(summary['port_mdd'])}  "
        f"Sharpe={'N/A' if pd.isna(summary['port_sharpe']) else f'{summary['port_sharpe']:.3f}'}"
    )


if __name__ == "__main__":
    main()
