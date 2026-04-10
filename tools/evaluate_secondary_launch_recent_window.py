# -*- coding: utf-8 -*-
"""
评估二次启动策略最近 N 个交易日表现，并对比新旧参数。
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path
import sys

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.core.config import ConfigManager
from src.core.database import DatabaseManager
from src.modules.mainboard_secondary_launch_backtester import (
    CostConfig,
    MainboardSecondaryLaunchBacktester,
)
from src.modules.mainboard_secondary_launch_strategy import (
    MainboardSecondaryLaunchStrategy,
    StrategyParams,
)


def build_common_params(config: ConfigManager) -> dict:
    return {
        "min_list_days": int(config.get("stock_selection.secondary_launch.min_list_days", 60)),
        "limit_up_threshold": float(config.get("stock_selection.secondary_launch.limit_up_threshold", 9.7)),
        "limit_down_threshold": float(config.get("stock_selection.secondary_launch.limit_down_threshold", -9.7)),
        "limit_up_count_10_min": int(config.get("stock_selection.secondary_launch.limit_up_count_10_min", 1)),
        "limit_up_count_10_max": int(config.get("stock_selection.secondary_launch.limit_up_count_10_max", 3)),
        "min_amt_ma20": float(config.get("stock_selection.secondary_launch.min_amt_ma20", 1e5)),
        "max_amt_ma20": float(config.get("stock_selection.secondary_launch.max_amt_ma20", 5e6)),
        "min_price": float(config.get("stock_selection.secondary_launch.min_price", 3.0)),
        "limit_up_amt_ratio_min": float(config.get("stock_selection.secondary_launch.limit_up_amt_ratio_min", 0.6)),
        "limit_up_amt_ratio_max": float(config.get("stock_selection.secondary_launch.limit_up_amt_ratio_max", 3.5)),
        "rs_lookback": int(config.get("stock_selection.secondary_launch.rs_lookback", 20)),
        "max_candidates": int(config.get("stock_selection.secondary_launch.max_candidates", 12)),
        "picks_per_day": int(config.get("stock_selection.secondary_launch.picks_per_day", 2)),
        "min_score": float(config.get("stock_selection.secondary_launch.min_score", 62.0)),
        "cooldown_days": int(config.get("stock_selection.secondary_launch.cooldown_days", 2)),
        "vol_shrink_ratio": float(config.get("stock_selection.secondary_launch.vol_shrink_ratio", 0.8)),
        "close_ma5_dev_max": float(config.get("stock_selection.secondary_launch.close_ma5_dev_max", 0.04)),
    }


def build_cost(config: ConfigManager) -> CostConfig:
    return CostConfig(
        buy_fee_rate=float(config.get("feedback.buy_fee_rate", 0.0003)),
        sell_fee_rate=float(config.get("feedback.sell_fee_rate", 0.0003)),
        stamp_tax_rate=float(config.get("feedback.stamp_tax_rate", 0.0005)),
        transfer_fee_rate=float(config.get("stock_selection.secondary_launch.transfer_fee_rate", 0.00001)),
        slippage_rate=float(config.get("feedback.buy_slippage", 0.001)),
    )


def resolve_window(db: DatabaseManager, end_date: str, trade_days: int) -> tuple[str, str]:
    date_df = pd.DataFrame(
        db.query(
            "SELECT DISTINCT trade_date FROM stock_daily WHERE trade_date <= ? ORDER BY trade_date",
            (end_date,),
        )
    )
    if date_df.empty or len(date_df) < trade_days:
        raise RuntimeError(f"交易日数据不足，无法回看最近 {trade_days} 个交易日")
    dates = date_df["trade_date"].astype(str).tolist()
    return dates[-trade_days], dates[-1]


def summarize_case(
    db: DatabaseManager,
    cost: CostConfig,
    start_date: str,
    end_date: str,
    hold_days: int,
    label: str,
    params: StrategyParams,
) -> dict:
    strategy = MainboardSecondaryLaunchStrategy(params)
    backtester = MainboardSecondaryLaunchBacktester(db, strategy, cost)
    result = backtester.run_backtest(start_date, end_date, hold_days=hold_days)
    metrics = result["metrics"]
    signals = result["signals"]
    trades = result["trades"]
    latest_signal_days = {}
    if not signals.empty:
        day_counts = signals.groupby("signal_date").size().sort_index().tail(8)
        latest_signal_days = {str(k.date()): int(v) for k, v in day_counts.items()}
    latest_picks = []
    if not signals.empty:
        latest_picks = signals[["signal_date", "ts_code", "name", "rank", "signal_score"]].tail(10).to_dict(orient="records")
    return {
        "case": label,
        "signal_days": int(metrics.get("total_signal_days", 0)),
        "trades": int(metrics.get("total_trades", 0)),
        "win_rate": float(metrics.get("win_rate", 0.0)),
        "day_win_rate": float(metrics.get("day_win_rate", 0.0)),
        "avg_return": float(metrics.get("avg_return", 0.0)),
        "total_return": float(metrics.get("total_return", 0.0)),
        "annual_return": float(metrics.get("annual_return", 0.0)),
        "profit_factor": float(metrics.get("profit_factor", 0.0)),
        "max_drawdown": float(metrics.get("max_drawdown", 0.0)),
        "regime_bull_avg": float(metrics.get("regime_bull_avg", 0.0)),
        "regime_sideways_avg": float(metrics.get("regime_sideways_avg", 0.0)),
        "regime_bear_avg": float(metrics.get("regime_bear_avg", 0.0)),
        "latest_signal_days": latest_signal_days,
        "latest_picks": latest_picks,
        "param_snapshot": asdict(params),
        "trade_sample": trades[["signal_date", "ts_code", "entry_date", "exit_date", "net_ret"]].tail(10).to_dict(orient="records")
        if not trades.empty
        else [],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="评估二次启动策略最近 N 个交易日表现")
    parser.add_argument("--trade-days", type=int, default=40, help="回看最近多少个交易日")
    parser.add_argument("--end-date", type=str, default="20260331", help="评估截止日期，格式 YYYYMMDD")
    args = parser.parse_args()

    config = ConfigManager()
    db = DatabaseManager(config)
    common = build_common_params(config)
    cost = build_cost(config)
    start_date, end_date = resolve_window(db, args.end_date, args.trade_days)
    hold_days = int(config.get("stock_selection.secondary_launch.hold_days", 2))

    old_params = StrategyParams(
        **{
            **common,
            "last_limit_up_days_min": 2,
            "last_limit_up_days_max": 10,
            "drawdown_min": 0.01,
            "drawdown_max": 0.12,
            "close_ma10_min_ratio": 0.97,
            "weak_market_ret5_threshold": -0.03,
            "weak_market_min_score_boost": 5.0,
            "weak_market_max_picks": 1,
            "second_pick_min_score": 66.0,
            "second_pick_score_gap": 4.0,
        }
    )
    new_params = StrategyParams(
        **{
            **common,
            "last_limit_up_days_min": 2,
            "last_limit_up_days_max": 7,
            "drawdown_min": 0.02,
            "drawdown_max": 0.08,
            "close_ma10_min_ratio": 0.99,
            "weak_market_ret5_threshold": -0.02,
            "weak_market_min_score_boost": 6.0,
            "weak_market_max_picks": 1,
            "second_pick_min_score": 68.0,
            "second_pick_score_gap": 4.0,
        }
    )

    output = {
        "window_trade_days": int(args.trade_days),
        "start_date": start_date,
        "end_date": end_date,
        "hold_days": hold_days,
        "old": summarize_case(db, cost, start_date, end_date, hold_days, "旧参数", old_params),
        "new": summarize_case(db, cost, start_date, end_date, hold_days, "新参数", new_params),
    }
    print(json.dumps(output, ensure_ascii=False, default=str, indent=2))


if __name__ == "__main__":
    main()
