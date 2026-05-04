# -*- coding: utf-8 -*-
"""Backtest configuration."""

from dataclasses import dataclass
from typing import Any, Dict


@dataclass
class BacktestConfig:
    """Core backtest config for daily/intraday engines."""

    # Capital and position
    initial_capital: float = 100000.0
    max_positions: int = 5
    position_size: float = 0.2

    # Trading cost
    buy_slippage: float = 0.001
    sell_slippage: float = 0.001
    buy_fee: float = 0.0003
    sell_fee: float = 0.0013

    # Signal threshold
    buy_signal_threshold: float = 30.0
    sell_signal_threshold: float = 40.0

    # Hold constraints
    max_hold_days: int = 10
    max_wait_buy_days: int = 5

    # Risk control
    stop_loss_pct: float = -0.05
    take_profit_pct: float = 0.10
    trailing_stop_pct: float = 0.03

    # A-share rules
    enable_t1_rule: bool = True
    enable_limit_rule: bool = True
    limit_up_pct: float = 0.10
    limit_down_pct: float = -0.10

    # Data settings
    use_cache: bool = True
    window_size: int = 50

    # Allocator settings
    # fixed: legacy fixed-size per position
    # score: score-proportional allocation
    # skfolio: optimization via skfolio MeanRisk
    allocator_mode: str = "fixed"
    position_budget: float = 1.0
    skfolio_max_weight: float = 0.3
    skfolio_risk_aversion: float = 0.5
    skfolio_min_history: int = 10
    skfolio_max_drawdown: float = 0.05
    skfolio_max_turnover: float = 0.2

    def to_dict(self) -> Dict[str, Any]:
        return {
            "initial_capital": self.initial_capital,
            "max_positions": self.max_positions,
            "position_size": self.position_size,
            "buy_slippage": self.buy_slippage,
            "sell_slippage": self.sell_slippage,
            "buy_fee": self.buy_fee,
            "sell_fee": self.sell_fee,
            "buy_signal_threshold": self.buy_signal_threshold,
            "sell_signal_threshold": self.sell_signal_threshold,
            "max_hold_days": self.max_hold_days,
            "max_wait_buy_days": self.max_wait_buy_days,
            "stop_loss_pct": self.stop_loss_pct,
            "take_profit_pct": self.take_profit_pct,
            "trailing_stop_pct": self.trailing_stop_pct,
            "enable_t1_rule": self.enable_t1_rule,
            "enable_limit_rule": self.enable_limit_rule,
            "limit_up_pct": self.limit_up_pct,
            "limit_down_pct": self.limit_down_pct,
            "use_cache": self.use_cache,
            "window_size": self.window_size,
            "allocator_mode": self.allocator_mode,
            "position_budget": self.position_budget,
            "skfolio_max_weight": self.skfolio_max_weight,
            "skfolio_risk_aversion": self.skfolio_risk_aversion,
            "skfolio_min_history": self.skfolio_min_history,
            "skfolio_max_drawdown": self.skfolio_max_drawdown,
            "skfolio_max_turnover": self.skfolio_max_turnover,
        }

    @classmethod
    def from_dict(cls, config_dict: Dict[str, Any]) -> "BacktestConfig":
        return cls(**config_dict)
