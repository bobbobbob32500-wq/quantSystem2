# -*- coding: utf-8 -*-
"""Regression tests for optimized intraday buy-signal detector."""

from __future__ import annotations

from datetime import datetime, timedelta

import numpy as np

from src.modules.optimized_buy_signals import IntradayData, OptimizedBuySignals


def test_pullback_requires_more_than_one_ma_window():
    detector = OptimizedBuySignals()
    start = datetime(2026, 3, 20, 9, 35)
    timestamps = np.array([start + timedelta(minutes=5 * i) for i in range(20)])
    prices = np.linspace(10.0, 10.8, 20)
    data = IntradayData(
        price=prices,
        volume=np.full(20, 1000.0),
        high=prices + 0.05,
        low=prices - 0.05,
        timestamp=timestamps,
    )

    output = detector.signal_pullback(data)
    assert output.signal is False
    assert output.reason == "数据不足"
