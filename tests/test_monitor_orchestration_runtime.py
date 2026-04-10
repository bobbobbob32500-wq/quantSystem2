# -*- coding: utf-8 -*-
"""Regression tests for monitor orchestration helpers."""

from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace

import pandas as pd

from src.modules.enhanced_hybrid_system import EnhancedHybridSystem


def _build_system_stub() -> EnhancedHybridSystem:
    system = EnhancedHybridSystem.__new__(EnhancedHybridSystem)
    system.min_signal_score_for_push = 75
    system.push_cooldown = 300
    system.pushed_signals = {}
    system.latest_quotes = {}
    captured = {"signals": None, "filtered_count": None, "side": None}

    def _push_trade_signals(signals, now, filtered_count=0, side="buy"):
        captured["signals"] = signals
        captured["filtered_count"] = filtered_count
        captured["side"] = side
        return True

    system.message_pusher = SimpleNamespace(push_trade_signals=_push_trade_signals)
    system._captured_push = captured
    return system


def test_push_buy_signals_filters_by_score_and_cooldown():
    system = _build_system_stub()
    now = datetime(2026, 3, 29, 10, 0, 0)
    system.pushed_signals["600002"] = {
        "signal_type": "A",
        "push_time": now - timedelta(seconds=120),
        "total_score": 88.0,
    }

    signals = [
        {"symbol": "600001", "signal_type": "A", "total_score": 80.0, "push_threshold": 75.0},
        {"symbol": "600002", "signal_type": "A", "total_score": 90.0, "push_threshold": 75.0},
        {"symbol": "600003", "signal_type": "A", "total_score": 70.0, "push_threshold": 75.0},
    ]

    system._push_buy_signals(signals, now)

    pushed = system._captured_push["signals"]
    assert pushed is not None
    assert len(pushed) == 1
    assert pushed[0]["symbol"] == "600001"
    assert system._captured_push["filtered_count"] == 2
    assert system._captured_push["side"] == "buy"


def test_push_buy_signals_secondary_launch_uses_strict_cooldown():
    system = _build_system_stub()
    now = datetime(2026, 3, 29, 10, 0, 0)
    system.pushed_signals["600002"] = {
        "signal_type": "secondary_launch_pullback",
        "push_time": now - timedelta(seconds=120),
        "total_score": 88.0,
    }

    signals = [
        {
            "symbol": "600002",
            "signal_type": "secondary_launch_breakout",
            "total_score": 90.0,
            "push_threshold": 75.0,
            "strategy_profile": "secondary_launch",
        },
        {
            "symbol": "600001",
            "signal_type": "secondary_launch_pullback",
            "total_score": 82.0,
            "push_threshold": 75.0,
            "strategy_profile": "secondary_launch",
        },
    ]

    system._push_buy_signals(signals, now)

    pushed = system._captured_push["signals"]
    assert pushed is not None
    assert len(pushed) == 1
    assert pushed[0]["symbol"] == "600001"


def test_update_latest_quotes_refreshes_cache_fields():
    system = _build_system_stub()
    df = pd.DataFrame(
        [
            {
                "symbol": "600001",
                "price": 10.5,
                "open": 10.1,
                "high": 10.6,
                "low": 10.0,
                "volume": 1200,
                "amount": 12000,
            }
        ]
    )

    system._update_latest_quotes(df)

    assert "600001" in system.latest_quotes
    latest = system.latest_quotes["600001"]
    assert latest["price"] == 10.5
    assert latest["open"] == 10.1
    assert latest["high"] == 10.6
    assert latest["low"] == 10.0
    assert latest["volume"] == 1200.0
    assert latest["amount"] == 12000.0
