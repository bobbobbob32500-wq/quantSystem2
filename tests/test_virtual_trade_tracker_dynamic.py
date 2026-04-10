# -*- coding: utf-8 -*-
"""Tests for dynamic virtual-trade exit logic."""

from __future__ import annotations

from datetime import datetime, timedelta

from src.modules.virtual_trade_tracker import VirtualTradeTracker


def _latest_open_trade(tracker: VirtualTradeTracker, symbol: str):
    trade = tracker.get_latest_open_trade(symbol)
    assert trade is not None
    return trade


def test_partial_take_then_trailing_stop_close():
    tracker = VirtualTradeTracker(
        stop_loss_pct=-0.05,
        take_profit_pct=0.10,
        max_hold_hours=None,
        fallback_max_hold_hours=None,
        enable_dynamic_exit=True,
        trailing_stop_pct=0.03,
    )
    ok = tracker.on_buy_signal(
        {
            "symbol": "000001.SZ",
            "name": "TEST_A",
            "price": 10.0,
            "signal_type": "breakout",
            "total_score": 86.0,
            "market_gate_tier": "normal",
            "circuit_state": "normal",
        }
    )
    assert ok is True

    # First move up, trigger partial take event but keep holding.
    closed = tracker.check_and_close({"000001.SZ": 10.7})
    assert closed == []
    assert _latest_open_trade(tracker, "000001.SZ").partial_take_done is True

    # Then retrace enough from peak, trigger trailing stop close.
    closed = tracker.check_and_close({"000001.SZ": 10.3})
    assert len(closed) == 1
    assert closed[0].sell_reason == "trailing_stop"


def test_fallback_time_exit_when_hold_too_long():
    tracker = VirtualTradeTracker(
        stop_loss_pct=-0.05,
        take_profit_pct=0.10,
        max_hold_hours=None,
        fallback_max_hold_hours=1,
        enable_dynamic_exit=False,
    )
    ok = tracker.on_buy_signal(
        {
            "symbol": "000002.SZ",
            "name": "TEST_B",
            "price": 10.0,
            "signal_type": "pullback",
            "total_score": 70.0,
            "max_hold_hours": 1,
        }
    )
    assert ok is True

    trade = _latest_open_trade(tracker, "000002.SZ")
    trade.buy_time = trade.buy_time - timedelta(hours=2)

    closed = tracker.check_and_close({"000002.SZ": 10.02})
    assert len(closed) == 1
    assert closed[0].sell_reason == "time_exit"


def test_defensive_gate_generates_defensive_profile():
    tracker = VirtualTradeTracker()
    ok = tracker.on_buy_signal(
        {
            "symbol": "000003.SZ",
            "name": "TEST_C",
            "price": 8.0,
            "signal_type": "breakout",
            "total_score": 90.0,
            "market_gate_tier": "defensive",
            "circuit_state": "normal",
        }
    )
    assert ok is True

    trade = _latest_open_trade(tracker, "000003.SZ")
    assert trade.risk_profile == "defensive"
    assert float(trade.stop_loss_pct) > -0.05
    assert float(trade.take_profit_stage1_pct) <= 0.06


def test_buy_signal_uses_explicit_timestamp():
    tracker = VirtualTradeTracker()
    signal_time = datetime(2026, 3, 20, 9, 45, 0)
    ok = tracker.on_buy_signal(
        {
            "symbol": "000004.SZ",
            "name": "TEST_D",
            "price": 12.3,
            "signal_type": "legacy_gap_mid_open",
            "total_score": 84.0,
            "timestamp": signal_time.isoformat(sep=" "),
        }
    )
    assert ok is True

    trade = _latest_open_trade(tracker, "000004.SZ")
    assert trade.buy_time == signal_time


def test_blocked_symbols_skip_close_but_keep_peak_tracking():
    tracker = VirtualTradeTracker(
        stop_loss_pct=-0.05,
        take_profit_pct=0.10,
        max_hold_hours=None,
        fallback_max_hold_hours=None,
        enable_dynamic_exit=True,
        trailing_stop_pct=0.03,
    )
    ok = tracker.on_buy_signal(
        {
            "symbol": "000005.SZ",
            "name": "TEST_E",
            "price": 10.0,
            "signal_type": "legacy_gap_mid_open",
            "total_score": 88.0,
            "timestamp": "2026-03-20 09:35:00",
        }
    )
    assert ok is True

    closed = tracker.check_and_close(
        {"000005.SZ": 10.8},
        now=datetime(2026, 3, 20, 10, 0, 0),
        blocked_symbols=["000005.SZ"],
    )
    assert closed == []

    trade = _latest_open_trade(tracker, "000005.SZ")
    assert trade.partial_take_done is False
    assert round(float(trade.highest_pnl_pct), 4) == 0.08


def test_peak_arm_on_t1_can_trigger_next_day_trailing_exit():
    tracker = VirtualTradeTracker(
        stop_loss_pct=-0.05,
        take_profit_pct=0.10,
        max_hold_hours=None,
        fallback_max_hold_hours=None,
        enable_dynamic_exit=True,
        trailing_stop_pct=0.03,
    )
    ok = tracker.on_buy_signal(
        {
            "symbol": "000006.SZ",
            "name": "TEST_F",
            "price": 10.0,
            "signal_type": "legacy_gap_mid_open",
            "total_score": 86.0,
            "dynamic_tp1_pct": 0.05,
            "dynamic_take_profit_pct": 0.10,
            "dynamic_trailing_stop_pct": 0.03,
            "carry_peak_arm_on_t1": True,
            "timestamp": "2026-03-20 09:35:00",
        }
    )
    assert ok is True

    closed = tracker.check_and_close(
        {"000006.SZ": 10.8},
        now=datetime(2026, 3, 20, 14, 30, 0),
        blocked_symbols=["000006.SZ"],
    )
    assert closed == []

    closed = tracker.check_and_close(
        {"000006.SZ": 10.3},
        now=datetime(2026, 3, 21, 9, 35, 0),
    )
    assert len(closed) == 1
    assert closed[0].sell_reason == "trailing_stop"
    assert closed[0].details["partial_take"]["trigger"] == "peak_arm_t1"


def test_same_symbol_multiple_buy_signals_create_independent_samples():
    tracker = VirtualTradeTracker()

    first_ok = tracker.on_buy_signal(
        {
            "symbol": "000007.SZ",
            "name": "TEST_G",
            "price": 10.0,
            "signal_type": "legacy_gap_mid_open",
            "total_score": 82.0,
            "timestamp": "2026-03-20 09:35:00",
        }
    )
    second_ok = tracker.on_buy_signal(
        {
            "symbol": "000007.SZ",
            "name": "TEST_G",
            "price": 10.2,
            "signal_type": "legacy_confirmation_fallback",
            "total_score": 79.0,
            "timestamp": "2026-03-20 10:05:00",
        }
    )

    assert first_ok is True
    assert second_ok is True
    assert len(tracker.open_trades) == 2

    open_infos = tracker.get_open_trades_info()
    assert len(open_infos) == 2
    assert len({item["trade_id"] for item in open_infos}) == 2
    assert all(item["symbol"] == "000007.SZ" for item in open_infos)


def test_min_hold_trading_days_blocks_same_day_exit_until_t1():
    tracker = VirtualTradeTracker(
        stop_loss_pct=-0.05,
        take_profit_pct=0.10,
        max_hold_hours=None,
        fallback_max_hold_hours=None,
        enable_dynamic_exit=False,
    )
    ok = tracker.on_buy_signal(
        {
            "symbol": "000008.SZ",
            "name": "TEST_H",
            "price": 10.0,
            "signal_type": "secondary_launch_pullback",
            "total_score": 88.0,
            "timestamp": "2026-03-20 10:00:00",
            "dynamic_stop_loss_pct": -0.015,
            "min_hold_trading_days": 1,
        }
    )
    assert ok is True

    closed_same_day = tracker.check_and_close(
        {"000008.SZ": 9.7},
        now=datetime(2026, 3, 20, 14, 30, 0),
    )
    assert closed_same_day == []
    assert _latest_open_trade(tracker, "000008.SZ").details["min_hold_satisfied"] is False

    closed_t1 = tracker.check_and_close(
        {"000008.SZ": 9.7},
        now=datetime(2026, 3, 21, 9, 35, 0),
    )
    assert len(closed_t1) == 1
    assert closed_t1[0].sell_reason == "stop_loss"
