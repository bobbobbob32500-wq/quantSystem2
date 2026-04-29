# -*- coding: utf-8 -*-
"""Signal engine for backtest."""

from __future__ import annotations

from collections import deque
from typing import Dict, Optional, Tuple

import numpy as np
import pandas as pd

from .config import BacktestConfig
from src.core.logger import get_logger

logger = get_logger("signal_engine")


class SignalEngine:
    """Generate buy/sell signals from rolling bars."""

    def __init__(self, config: BacktestConfig):
        self.config = config
        self.data_windows: Dict[str, deque] = {}
        self.signal_history: Dict[str, list] = {}

    def update_data(self, bars: list) -> None:
        for bar in bars:
            symbol = bar["symbol"]
            if symbol not in self.data_windows:
                self.data_windows[symbol] = deque(maxlen=self.config.window_size)
            self.data_windows[symbol].append(bar)

    def generate_signal(self, symbol: str, position_exists: bool = False) -> Optional[Dict]:
        if symbol not in self.data_windows:
            return None

        window = list(self.data_windows[symbol])
        if len(window) < 10:
            return None

        if not position_exists:
            buy_signal, buy_type, buy_score = self._detect_buy_signal(window)
        else:
            buy_signal, buy_type, buy_score = False, "", 0.0

        if position_exists:
            sell_signal, sell_type, sell_score = self._detect_sell_signal(window)
        else:
            sell_signal, sell_type, sell_score = False, "", 0.0

        return {
            "buy": buy_signal,
            "buy_type": buy_type,
            "buy_score": buy_score,
            "sell": sell_signal,
            "sell_type": sell_type,
            "sell_score": sell_score,
            "recent_returns": self._extract_recent_returns(window),
        }

    def _detect_buy_signal(self, window: list) -> Tuple[bool, str, float]:
        if len(window) < 10:
            return False, "", 0.0

        current = window[-1]
        prices = np.asarray([x["close"] for x in window], dtype=float)
        volumes = np.asarray([x["volume"] for x in window], dtype=float)

        if len(window) >= 5:
            prev_high = max(x["high"] for x in window[-5:-1])
            breakout_pct = (current["close"] - prev_high) / prev_high if prev_high > 0 else 0.0
            avg_vol = np.mean(volumes[-5:-1]) if len(volumes) >= 5 else 0.0
            vol_ratio = current["volume"] / avg_vol if avg_vol > 0 else 1.0

            if breakout_pct > 0.03 and vol_ratio > 1.5:
                score = 80 + min(breakout_pct * 50, 15)
                return True, "strong_breakout", float(score)
            if breakout_pct > 0.02 and vol_ratio > 1.3:
                score = 70 + min(breakout_pct * 50, 10)
                return True, "mid_breakout", float(score)

        if len(window) >= 5:
            ma5 = float(np.mean(prices[-5:]))
            price_diff = abs(current["close"] - ma5) / ma5 if ma5 > 0 else 0.0
            if price_diff < 0.015:
                recent_low = min(x["low"] for x in window[-3:])
                if current["close"] > recent_low * 1.005:
                    avg_vol = np.mean(volumes[-5:-1]) if len(volumes) >= 5 else 0.0
                    vol_ratio = current["volume"] / avg_vol if avg_vol > 0 else 1.0
                    if vol_ratio > 1.0:
                        score = 45 + min(vol_ratio * 5, 10)
                        return True, "ma_pullback", float(score)

        if len(window) >= 2:
            prev_close = float(window[-2]["close"])
            rise_pct = (current["close"] - prev_close) / prev_close if prev_close > 0 else 0.0
            avg_vol = np.mean(volumes[-5:-1]) if len(volumes) >= 5 else float(volumes[-1])
            vol_ratio = current["volume"] / avg_vol if avg_vol > 0 else 1.0
            if rise_pct > 0.02 and vol_ratio > 1.3:
                score = 55 + min(rise_pct * 50, 15)
                return True, "price_volume_sync", float(score)

        return False, "", 0.0

    def _detect_sell_signal(self, window: list) -> Tuple[bool, str, float]:
        if len(window) < 2:
            return False, "", 0.0

        current = window[-1]
        prices = np.asarray([x["close"] for x in window], dtype=float)

        if len(window) >= 3:
            prev_price = float(window[-3]["close"])
            drop_pct = (current["close"] - prev_price) / prev_price if prev_price > 0 else 0.0
            if drop_pct < -0.05:
                return True, "fast_drop", 60.0

        if len(window) >= 10:
            ma5 = float(np.mean(prices[-5:]))
            ma10 = float(np.mean(prices[-10:]))
            if current["close"] < ma5 * 0.95 and ma5 < ma10:
                return True, "trend_weak", 65.0

        return False, "", 0.0

    def get_signal_history(self, symbol: str) -> list:
        return self.signal_history.get(symbol, [])

    def clear_signal_history(self, symbol: str) -> None:
        if symbol in self.signal_history:
            self.signal_history[symbol] = []

    @staticmethod
    def _extract_recent_returns(window: list, lookback: int = 20) -> list:
        closes = np.asarray([float(x.get("close", 0.0) or 0.0) for x in window], dtype=float)
        closes = closes[closes > 0]
        if closes.size < 3:
            return []
        rets = pd.Series(closes).pct_change().dropna()
        if rets.empty:
            return []
        return rets.tail(lookback).astype(float).tolist()

