# -*- coding: utf-8 -*-
"""Trade execution engine."""

from __future__ import annotations

from typing import Dict, List

from .config import BacktestConfig
from .portfolio import Portfolio
from .position_allocator import allocate_buy_weights
from src.core.logger import get_logger

logger = get_logger("execution_engine")


class ExecutionEngine:
    """Apply generated signals to portfolio operations."""

    def __init__(self, config: BacktestConfig):
        self.config = config
        self.today_buys: Dict[str, str] = {}

    def execute(self, bars: list, signals: Dict[str, Dict], portfolio: Portfolio, current_date: str) -> None:
        self._clean_today_buys(current_date)

        # 1) Execute sells first
        for bar in bars:
            symbol = bar["symbol"]
            signal = signals.get(symbol)
            if not signal:
                continue
            if self.config.enable_limit_rule and self._is_limit_down(bar):
                continue
            if signal.get("sell") and float(signal.get("sell_score", 0.0)) >= self.config.sell_signal_threshold:
                self._execute_sell(bar, signal, portfolio, current_date)

        # 2) Collect buy candidates and allocate weights
        buy_candidates: List[Dict] = []
        for bar in bars:
            symbol = bar["symbol"]
            signal = signals.get(symbol)
            if not signal:
                continue
            if not portfolio.can_open_position() or portfolio.has_position(symbol):
                continue
            if self.config.enable_limit_rule and self._is_limit_up(bar):
                continue
            if signal.get("buy") and float(signal.get("buy_score", 0.0)) >= self.config.buy_signal_threshold:
                buy_candidates.append(
                    {
                        "symbol": symbol,
                        "score": float(signal.get("buy_score", 0.0)),
                        "recent_returns": signal.get("recent_returns") or [],
                    }
                )

        if not buy_candidates:
            return

        target_weights = allocate_buy_weights(buy_candidates, self.config)
        bar_map = {bar["symbol"]: bar for bar in bars}
        signal_map = {sym: signals[sym] for sym in signals}

        for item in sorted(buy_candidates, key=lambda x: x["score"], reverse=True):
            symbol = item["symbol"]
            if not portfolio.can_open_position() or portfolio.has_position(symbol):
                continue
            bar = bar_map.get(symbol)
            signal = signal_map.get(symbol)
            if not bar or not signal:
                continue
            weight = target_weights.get(symbol)
            self._execute_buy(bar, signal, portfolio, current_date, target_weight=weight)

    def _execute_buy(
        self,
        bar: Dict,
        signal: Dict,
        portfolio: Portfolio,
        current_date: str,
        target_weight: float | None = None,
    ) -> bool:
        symbol = bar["symbol"]
        if not portfolio.can_open_position() or portfolio.has_position(symbol):
            return False

        price = float(bar["open"])
        quantity = portfolio.calculate_position_size(price, target_weight=target_weight)
        if quantity < 100:
            return False

        success = portfolio.open_position(
            symbol=symbol,
            price=price,
            quantity=quantity,
            entry_time=bar["timestamp"],
            entry_date=current_date,
            buy_signal_type=str(signal.get("buy_type", "")),
            buy_signal_score=float(signal.get("buy_score", 0.0)),
        )
        if success:
            self.today_buys[symbol] = current_date
            logger.info(
                "BUY %s price=%.2f qty=%s score=%.0f weight=%.3f mode=%s",
                symbol,
                price,
                quantity,
                float(signal.get("buy_score", 0.0)),
                float(target_weight) if target_weight is not None else float(self.config.position_size),
                self.config.allocator_mode,
            )
        return success

    def _execute_sell(self, bar: Dict, signal: Dict, portfolio: Portfolio, current_date: str) -> bool:
        symbol = bar["symbol"]
        if not portfolio.has_position(symbol):
            return False

        if self.config.enable_t1_rule and symbol in self.today_buys and self.today_buys[symbol] == current_date:
            return False

        price = float(bar["open"])
        success = portfolio.close_position(
            symbol=symbol,
            price=price,
            exit_time=bar["timestamp"],
            exit_date=current_date,
            sell_signal_type=str(signal.get("sell_type", "")),
            sell_signal_score=float(signal.get("sell_score", 0.0)),
        )
        if success:
            logger.info("SELL %s price=%.2f score=%.0f", symbol, price, float(signal.get("sell_score", 0.0)))
        return success

    def check_risk_control(self, bars: list, portfolio: Portfolio, current_date: str) -> None:
        for bar in bars:
            symbol = bar["symbol"]
            if not portfolio.has_position(symbol):
                continue

            position = portfolio.get_position(symbol)
            if position is None or position.entry_price <= 0:
                continue

            current_price = float(bar["close"])
            profit_pct = (current_price - position.entry_price) / position.entry_price

            if profit_pct <= self.config.stop_loss_pct:
                self._execute_risk_sell(bar, portfolio, current_date, "stop_loss", 100.0)
                continue
            if profit_pct >= self.config.take_profit_pct:
                self._execute_risk_sell(bar, portfolio, current_date, "take_profit", 85.0)
                continue
            if position.highest_price > position.entry_price * 1.03:
                drawdown = (position.highest_price - current_price) / position.highest_price
                if drawdown >= self.config.trailing_stop_pct:
                    self._execute_risk_sell(bar, portfolio, current_date, "trailing_stop", 90.0)
                    continue
            hold_days = (bar["timestamp"] - position.entry_time).days
            if hold_days >= self.config.max_hold_days and profit_pct < 0:
                self._execute_risk_sell(bar, portfolio, current_date, "time_stop", 50.0)

    def _execute_risk_sell(
        self, bar: Dict, portfolio: Portfolio, current_date: str, reason: str, score: float
    ) -> bool:
        symbol = bar["symbol"]
        if self.config.enable_t1_rule and symbol in self.today_buys and self.today_buys[symbol] == current_date:
            return False
        price = float(bar["close"])
        success = portfolio.close_position(
            symbol=symbol,
            price=price,
            exit_time=bar["timestamp"],
            exit_date=current_date,
            sell_signal_type=reason,
            sell_signal_score=score,
        )
        if success:
            logger.warning("RISK_SELL %s price=%.2f reason=%s", symbol, price, reason)
        return success

    def _is_limit_up(self, bar: Dict) -> bool:
        pct_change = float(bar.get("pct_change", 0.0) or 0.0)
        return pct_change >= self.config.limit_up_pct - 0.001

    def _is_limit_down(self, bar: Dict) -> bool:
        pct_change = float(bar.get("pct_change", 0.0) or 0.0)
        return pct_change <= self.config.limit_down_pct + 0.001

    def _clean_today_buys(self, current_date: str) -> None:
        expired = [symbol for symbol, dt in self.today_buys.items() if dt != current_date]
        for symbol in expired:
            del self.today_buys[symbol]

