# -*- coding: utf-8 -*-
"""
增强系统与优化器之间的桥接层。
将虚拟交易、回测样本和参数评估逻辑从主系统类中拆出。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List

import numpy as np

from src.core.logger import get_logger

logger = get_logger("enhanced_optimization_bridge")


def handle_virtual_trade_closed(system, trade) -> None:
    """虚拟交易平仓后，把结果桥接到自动优化链路。"""
    logger.info("虚拟交易平仓: %s, 盈亏=%+.2f%%", trade.symbol, float(trade.pnl_pct or 0.0) * 100.0)

    if system.enable_auto_optimization and system.auto_optimizer:
        system.auto_optimizer.on_trade_result({
            "pnl": trade.pnl_pct,
            "symbol": trade.symbol,
        })

    if not (system.enable_enhanced_optimization and system.enhanced_optimizer):
        return

    factors = {}
    if hasattr(trade, "details") and trade.details:
        factors = {
            "overnight_score": trade.details.get("overnight_score", 0) / 100,
            "intraday_score": trade.details.get("intraday_score", 0) / 100,
            "pool_type": 1.0 if trade.details.get("pool_type") == "core" else 0.5,
        }

    market_env = system._get_market_environment()
    hold_hours = 0.0
    if getattr(trade, "sell_time", None) and getattr(trade, "buy_time", None):
        hold_hours = max(
            0.0,
            (trade.sell_time - trade.buy_time).total_seconds() / 3600.0,
        )

    enhanced_trade = {
        "trade_id": getattr(trade, "trade_id", ""),
        "signal_instance_id": getattr(trade, "signal_instance_id", ""),
        "symbol": trade.symbol,
        "name": trade.name,
        "buy_time": trade.buy_time,
        "buy_price": trade.buy_price,
        "sell_time": trade.sell_time,
        "sell_price": trade.sell_price,
        "pnl": trade.pnl,
        "pnl_pct": trade.pnl_pct,
        "peak_pnl_pct": system._to_float(getattr(trade, "highest_pnl_pct", 0.0)),
        "lowest_pnl_pct": system._to_float(getattr(trade, "lowest_pnl_pct", 0.0)),
        "sell_reason": str(getattr(trade, "sell_reason", "") or ""),
        "hold_hours": hold_hours,
        "signal_type": (
            str((getattr(trade, "details", {}) or {}).get("signal_subtype", "") or "")
            or trade.buy_signal
        ),
        "signal_score": trade.buy_score,
        "factors": factors,
        "market_env": market_env,
    }
    system.enhanced_optimizer.on_virtual_trade_closed(enhanced_trade)


def evaluate_strategy(system, trades, params) -> Dict[str, Any]:
    """对样本交易集做参数敏感评估。"""
    if not trades:
        return {"win_rate": 0, "avg_pnl": 0, "trade_count": 0, "effective_weight": 0.0}

    min_signal_score = float(params.get("min_signal_score", 0.0) or 0.0)
    stop_loss_pct = float(params.get("stop_loss_pct", -0.05) or -0.05)
    take_profit_pct = float(params.get("take_profit_pct", 0.10) or 0.10)
    trailing_stop_pct = system._parse_optional_float(params.get("trailing_stop_pct", None))
    max_hold_hours = system._parse_optional_float(params.get("max_hold_hours", None))

    selected_trades: List[Dict[str, Any]] = []
    weighted_contributions: List[float] = []
    weights: List[float] = []
    simulated_pnls: List[float] = []

    for trade in trades:
        raw_score = system._to_float(trade.get("signal_score", 0.0), 0.0)
        normalized_score = raw_score / 100.0 if raw_score > 1.0 else raw_score
        if normalized_score < min_signal_score:
            continue

        raw_pnl_pct = system._parse_optional_float(trade.get("raw_pnl_pct", trade.get("pnl_pct", 0.0)))
        if raw_pnl_pct is None:
            raw_pnl_pct = 0.0
        peak_pnl_pct = system._parse_optional_float(trade.get("peak_pnl_pct", None))
        lowest_pnl_pct = system._parse_optional_float(trade.get("lowest_pnl_pct", None))
        hold_hours = system._parse_optional_float(trade.get("hold_hours", None))
        if hold_hours is None:
            buy_time = system._parse_datetime_value(trade.get("buy_time", None))
            sell_time = system._parse_datetime_value(trade.get("sell_time", None))
            if buy_time and sell_time:
                hold_hours = max(0.0, (sell_time - buy_time).total_seconds() / 3600.0)

        simulated_pnl_pct = float(raw_pnl_pct)
        if lowest_pnl_pct is not None and lowest_pnl_pct <= stop_loss_pct and simulated_pnl_pct <= 0:
            simulated_pnl_pct = max(simulated_pnl_pct, stop_loss_pct)
        if peak_pnl_pct is not None and peak_pnl_pct >= take_profit_pct:
            simulated_pnl_pct = max(simulated_pnl_pct, take_profit_pct)
        if (
            trailing_stop_pct is not None
            and peak_pnl_pct is not None
            and peak_pnl_pct > 0
            and simulated_pnl_pct < peak_pnl_pct - trailing_stop_pct
        ):
            simulated_pnl_pct = max(simulated_pnl_pct, peak_pnl_pct - trailing_stop_pct)
        if (
            max_hold_hours is not None
            and hold_hours is not None
            and hold_hours > max_hold_hours
            and peak_pnl_pct is not None
            and peak_pnl_pct > 0
        ):
            simulated_pnl_pct = max(simulated_pnl_pct, min(peak_pnl_pct * 0.7, peak_pnl_pct))

        weight = max(0.0, system._to_float(trade.get("weight", 1.0), 1.0))
        selected_trades.append(trade)
        weights.append(weight)
        simulated_pnls.append(simulated_pnl_pct)
        weighted_contributions.append(simulated_pnl_pct * weight)

    if not selected_trades:
        return {"win_rate": 0, "avg_pnl": 0, "trade_count": 0, "effective_weight": 0.0}

    weights_array = np.array(weights, dtype=float)
    pnls_array = np.array(simulated_pnls, dtype=float)
    contribution_array = np.array(weighted_contributions, dtype=float)
    total_weight = float(weights_array.sum()) if len(weights_array) else 0.0
    if total_weight <= 0:
        weights_array = np.ones(len(selected_trades), dtype=float)
        total_weight = float(weights_array.sum())

    win_mask = pnls_array > 0
    win_rate = float(np.average(win_mask.astype(float), weights=weights_array))
    avg_pnl = float(np.average(pnls_array, weights=weights_array))
    pnl_std = float(np.sqrt(np.average((pnls_array - avg_pnl) ** 2, weights=weights_array)))

    order_pairs = []
    for idx, trade in enumerate(selected_trades):
        buy_time = system._parse_datetime_value(trade.get("buy_time", None))
        order_pairs.append((buy_time or datetime.max, contribution_array[idx]))
    order_pairs.sort(key=lambda item: item[0])
    cumulative_pnl = np.cumsum([item[1] for item in order_pairs]) if order_pairs else np.array([])
    if len(cumulative_pnl) > 0:
        peak_curve = np.maximum.accumulate(cumulative_pnl)
        max_drawdown = float(np.max(peak_curve - cumulative_pnl))
    else:
        max_drawdown = 0.0

    return {
        "win_rate": win_rate,
        "avg_pnl": avg_pnl,
        "total_trades": len(selected_trades),
        "trade_count": len(selected_trades),
        "effective_weight": total_weight,
        "win_count": int(win_mask.sum()),
        "pnl_std": pnl_std,
        "max_drawdown": max_drawdown,
    }


def collect_virtual_closed_trade_samples(system, limit: int = 500) -> List[Dict[str, Any]]:
    """从虚拟交易器中收集已平仓样本，供增强优化器启动或重训。"""
    samples: List[Dict[str, Any]] = []
    tracker = getattr(system, "virtual_tracker", None)
    if tracker is None:
        return samples
    closed = list(getattr(tracker, "closed_trades", []) or [])
    if not closed:
        return samples

    for trade in reversed(closed):
        pnl_pct = system._to_float(getattr(trade, "pnl_pct", 0.0))
        buy_price = system._to_float(getattr(trade, "buy_price", 0.0))
        sell_price = system._to_float(getattr(trade, "sell_price", 0.0))
        buy_time = getattr(trade, "buy_time", None)
        sell_time = getattr(trade, "sell_time", None)
        if buy_price <= 0 or sell_price <= 0:
            continue
        if buy_time is None:
            continue

        details = getattr(trade, "details", {}) or {}
        factors = {
            "overnight_score": system._to_float(details.get("overnight_score", 0.0)) / 100.0,
            "intraday_score": system._to_float(details.get("intraday_score", 0.0)) / 100.0,
            "pool_type": 1.0 if str(details.get("pool_type", "")) == "core" else 0.5,
        }
        samples.append(
            {
                "trade_id": str(getattr(trade, "trade_id", "")),
                "signal_instance_id": str(getattr(trade, "signal_instance_id", "")),
                "symbol": str(getattr(trade, "symbol", "")),
                "name": str(getattr(trade, "name", "")),
                "buy_time": buy_time,
                "buy_price": buy_price,
                "sell_time": sell_time or buy_time,
                "sell_price": sell_price,
                "pnl": system._to_float(getattr(trade, "pnl", 0.0)),
                "pnl_pct": pnl_pct,
                "peak_pnl_pct": system._to_float(getattr(trade, "highest_pnl_pct", 0.0)),
                "lowest_pnl_pct": system._to_float(getattr(trade, "lowest_pnl_pct", 0.0)),
                "sell_reason": str(getattr(trade, "sell_reason", "") or ""),
                "hold_hours": (
                    max(0.0, (sell_time - buy_time).total_seconds() / 3600.0)
                    if sell_time is not None
                    else 0.0
                ),
                "signal_type": str(getattr(trade, "buy_signal", "") or "virtual_trade"),
                "signal_subtype": str(details.get("signal_subtype", "") or ""),
                "signal_score": system._to_float(getattr(trade, "buy_score", 0.0)),
                "factors": factors,
                "market_env": {
                    "trend": str(getattr(trade, "entry_market_gate_tier", "unknown")),
                    "risk_profile": str(getattr(trade, "risk_profile", "balanced")),
                },
                "data_source": "virtual_closed_trade",
            }
        )
        if len(samples) >= max(1, int(limit)):
            break
    return samples
