# -*- coding: utf-8 -*-
"""Portfolio management for backtest."""

from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Optional

from .config import BacktestConfig
from .position import Position


class Portfolio:
    """Portfolio state and position lifecycle."""

    def __init__(self, config: BacktestConfig):
        self.config = config
        self.initial_capital = config.initial_capital
        self.cash = config.initial_capital
        self.total_value = config.initial_capital
        self.positions: Dict[str, Position] = {}
        self.equity_curve: List[Dict] = []
        self.trade_history: List[Dict] = []
        self.daily_records: List[Dict] = []

    def get_position(self, symbol: str) -> Optional[Position]:
        return self.positions.get(symbol)

    def has_position(self, symbol: str) -> bool:
        return symbol in self.positions

    def get_position_count(self) -> int:
        return len(self.positions)

    def can_open_position(self) -> bool:
        return self.get_position_count() < self.config.max_positions

    def calculate_position_size(self, price: float, target_weight: Optional[float] = None) -> int:
        """Calculate lot-based quantity from target weight."""
        if price <= 0:
            return 0
        if target_weight is None:
            target_weight = self.config.position_size
        weight = max(0.0, min(1.0, float(target_weight)))
        target_amount = self.total_value * weight
        if target_amount > self.cash:
            target_amount = self.cash * 0.95
        quantity = int(target_amount / price / 100) * 100
        return max(0, quantity)

    def open_position(
        self,
        symbol: str,
        price: float,
        quantity: int,
        entry_time: datetime,
        entry_date: str,
        buy_signal_type: str = "",
        buy_signal_score: float = 0.0,
    ) -> bool:
        if not self.can_open_position():
            return False
        if self.has_position(symbol):
            return False
        if quantity <= 0 or price <= 0:
            return False

        actual_price = price * (1 + self.config.buy_slippage)
        cost = actual_price * quantity
        fee = cost * self.config.buy_fee
        total_cost = cost + fee
        if total_cost > self.cash:
            return False

        self.cash -= total_cost
        position = Position(
            symbol=symbol,
            entry_price=actual_price,
            quantity=quantity,
            entry_time=entry_time,
            entry_date=entry_date,
            buy_signal_type=buy_signal_type,
            buy_signal_score=buy_signal_score,
        )
        self.positions[symbol] = position
        self.trade_history.append(
            {
                "time": entry_time,
                "date": entry_date,
                "action": "buy",
                "symbol": symbol,
                "price": actual_price,
                "quantity": quantity,
                "amount": cost,
                "fee": fee,
                "total_cost": total_cost,
                "signal_type": buy_signal_type,
                "signal_score": buy_signal_score,
            }
        )
        return True

    def close_position(
        self,
        symbol: str,
        price: float,
        exit_time: datetime,
        exit_date: str,
        sell_signal_type: str = "",
        sell_signal_score: float = 0.0,
    ) -> bool:
        if not self.has_position(symbol):
            return False
        if price <= 0:
            return False

        position = self.positions[symbol]
        actual_price = price * (1 - self.config.sell_slippage)
        revenue = actual_price * position.quantity
        fee = revenue * self.config.sell_fee
        actual_revenue = revenue - fee
        self.cash += actual_revenue

        cost = position.entry_price * position.quantity
        profit = actual_revenue - cost
        profit_pct = profit / cost if cost > 0 else 0.0

        self.trade_history.append(
            {
                "time": exit_time,
                "date": exit_date,
                "action": "sell",
                "symbol": symbol,
                "price": actual_price,
                "quantity": position.quantity,
                "amount": actual_revenue,
                "fee": fee,
                "profit": profit,
                "profit_pct": profit_pct,
                "signal_type": sell_signal_type,
                "signal_score": sell_signal_score,
                "hold_days": (exit_time - position.entry_time).days,
            }
        )
        del self.positions[symbol]
        return True

    def update_positions(self, price_dict: Dict[str, float]) -> None:
        for symbol, price in price_dict.items():
            if self.has_position(symbol):
                self.positions[symbol].update_price(price)

    def update_total_value(self) -> None:
        positions_value = sum(pos.get_value() for pos in self.positions.values())
        self.total_value = self.cash + positions_value

    def record_equity(self, time: datetime, date: str) -> None:
        self.update_total_value()
        self.equity_curve.append(
            {
                "time": time,
                "date": date,
                "cash": self.cash,
                "positions_value": self.total_value - self.cash,
                "total_value": self.total_value,
                "position_count": self.get_position_count(),
            }
        )

    def get_results(self) -> Dict:
        return {
            "initial_capital": self.initial_capital,
            "final_capital": self.total_value,
            "total_return": (self.total_value - self.initial_capital) / self.initial_capital,
            "equity_curve": self.equity_curve,
            "trade_history": self.trade_history,
            "daily_records": self.daily_records,
        }

