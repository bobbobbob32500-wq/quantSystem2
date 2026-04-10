# -*- coding: utf-8 -*-
"""Tests for strategy-level buy-template routing."""

from __future__ import annotations

from datetime import datetime, time, timedelta
from types import SimpleNamespace

import pandas as pd

from src.modules.enhanced_hybrid_system import EnhancedHybridSystem
from src.modules.optimized_buy_signals import SignalOutput


def _build_system_stub() -> EnhancedHybridSystem:
    system = EnhancedHybridSystem.__new__(EnhancedHybridSystem)
    system.legacy_gap_entry_enabled = True
    system.legacy_gap_entry_start_time = time(9, 35)
    system.legacy_gap_entry_end_time = time(10, 15)
    system.legacy_low_open_entry_end_time = time(10, 30)
    system.legacy_gap_mid_lower_pct = 1.0
    system.legacy_gap_mid_upper_pct = 4.0
    system.legacy_gap_flat_skip_lower_pct = -2.0
    system.legacy_gap_flat_skip_upper_pct = 1.0
    system.legacy_low_open_reclaim_pct = 0.3
    system.legacy_low_open_min_wait_time = time(9, 45)
    system.legacy_low_open_min_low_age_bars = 1
    system.legacy_low_open_rebound_from_low_pct = 0.5
    system.legacy_low_open_max_chase_from_low_pct = 2.0
    system.legacy_low_open_recent_trend_bars = 3
    system.legacy_open_support_tolerance_pct = 0.8
    system.legacy_vwap_support_tolerance_pct = 0.2
    system.legacy_route_exit_override_enabled = True
    system.legacy_route_exit_overrides = {
        "legacy_gap_mid_open": {
            "stop_loss_pct": -0.05,
            "tp1_pct": 0.06,
            "take_profit_pct": 0.10,
            "trailing_stop_pct": 0.03,
            "max_hold_hours": 96,
            "carry_peak_arm_on_t1": True,
            "profile_label": "mid_open_protect_v1",
        }
    }
    system.config = {"debounce_window": 2}
    system.overnight_selector = SimpleNamespace(strategy_profile="legacy")
    system.system_config = SimpleNamespace(get=lambda *_args, **_kwargs: "legacy")
    system.signal_detector = SimpleNamespace(
        mutual_exclusive_signal=lambda *_args, **_kwargs: SignalOutput(
            signal=True,
            signal_type="breakout",
            confidence=0.82,
            reason="分时确认买点",
            details={},
        ),
        time_filter=lambda *_args, **_kwargs: False,
        debounce=lambda history, window: len(history) >= window and all(history[-window:]),
    )
    system._get_intraday_data_for_signal = lambda *_args, **_kwargs: object()
    return system


def _minute_frame(rows) -> pd.DataFrame:
    base = datetime(2026, 3, 28, 9, 35)
    return pd.DataFrame(
        [
            {
                "trade_time": base + timedelta(minutes=5 * idx),
                "close": float(close),
                "high": float(high),
                "low": float(low),
                "volume": float(volume),
            }
            for idx, (close, high, low, volume) in enumerate(rows)
        ]
    )


def test_legacy_mid_gap_route_emits_immediate_signal():
    system = _build_system_stub()
    candidate = {"symbol": "600001", "name": "A", "strategy_profile": "legacy"}
    quote = {
        "symbol": "600001",
        "price": 10.28,
        "open": 10.20,
        "high": 10.30,
        "low": 10.20,
        "volume": 1000,
        "pre_close": 10.00,
    }
    minute_map = {
        "600001": _minute_frame(
            [
                (10.24, 10.26, 10.20, 120),
                (10.28, 10.30, 10.24, 160),
            ]
        )
    }

    signal = system._detect_legacy_gap_signal(
        candidate=candidate,
        quote=quote,
        now=datetime(2026, 3, 28, 9, 40),
        minute_map=minute_map,
    )

    assert signal is not None
    assert signal.signal is True
    assert signal.signal_type == "legacy_gap_mid_open"
    assert signal.details["buy_template_source"] == "legacy_gap_open_v1"
    assert signal.details["buy_route"] == "legacy_gap_mid_open"
    assert signal.details["debounce_window"] == 1


def test_legacy_flat_gap_route_blocks_signal():
    system = _build_system_stub()
    candidate = {"symbol": "600001", "name": "A", "strategy_profile": "legacy_opt"}
    quote = {
        "symbol": "600001",
        "price": 10.05,
        "open": 10.03,
        "high": 10.08,
        "low": 9.99,
        "volume": 800,
        "pre_close": 10.00,
    }

    signal = system._detect_legacy_gap_signal(
        candidate=candidate,
        quote=quote,
        now=datetime(2026, 3, 28, 9, 40),
        minute_map={},
    )

    assert signal is not None
    assert signal.signal is False
    assert signal.details["route_blocked"] is True
    assert signal.details["buy_route"] == "legacy_flat_gap_skip"


def test_legacy_low_open_waits_for_session_low_to_form():
    system = _build_system_stub()
    candidate = {"symbol": "600003", "name": "C", "strategy_profile": "legacy"}
    quote = {
        "symbol": "600003",
        "price": 9.45,
        "open": 9.70,
        "high": 9.72,
        "low": 9.40,
        "volume": 950,
        "pre_close": 10.00,
    }
    minute_map = {
        "600003": _minute_frame(
            [
                (9.45, 9.62, 9.40, 150),
            ]
        )
    }

    signal = system._detect_legacy_gap_signal(
        candidate=candidate,
        quote=quote,
        now=datetime(2026, 3, 28, 9, 35),
        minute_map=minute_map,
    )

    assert signal is not None
    assert signal.signal is False
    assert signal.details["buy_route"] == "legacy_low_open_repair"
    assert signal.details["route_blocked"] is True
    assert signal.details["filter_reason"] == "low_open_wait_window"


def test_legacy_low_open_can_enter_on_first_bar_reversal():
    system = _build_system_stub()
    candidate = {"symbol": "600006", "name": "F", "strategy_profile": "legacy"}
    quote = {
        "symbol": "600006",
        "price": 9.54,
        "open": 9.70,
        "high": 9.58,
        "low": 9.42,
        "volume": 980,
        "pre_close": 10.00,
    }
    minute_map = {
        "600006": _minute_frame(
            [
                (9.54, 9.58, 9.42, 160),
            ]
        )
    }

    signal = system._detect_legacy_gap_signal(
        candidate=candidate,
        quote=quote,
        now=datetime(2026, 3, 28, 9, 35),
        minute_map=minute_map,
    )

    assert signal is not None
    assert signal.signal is True
    assert signal.signal_type == "legacy_low_open_repair"
    assert signal.details["buy_route"] == "legacy_low_open_repair"
    assert signal.details["early_reversal_ready"] is True
    assert signal.details["near_day_low"] is True
    assert signal.details["close_in_upper_half"] is True


def test_legacy_low_open_requires_confirmed_rebound_near_day_low():
    system = _build_system_stub()
    candidate = {"symbol": "600003", "name": "C", "strategy_profile": "legacy_opt"}
    quote = {
        "symbol": "600003",
        "price": 9.52,
        "open": 9.70,
        "high": 9.72,
        "low": 9.40,
        "volume": 1200,
        "pre_close": 10.00,
    }
    minute_map = {
        "600003": _minute_frame(
            [
                (9.62, 9.65, 9.58, 100),
                (9.45, 9.50, 9.40, 150),
                (9.48, 9.52, 9.43, 100),
                (9.52, 9.55, 9.47, 90),
            ]
        )
    }

    signal = system._detect_legacy_gap_signal(
        candidate=candidate,
        quote=quote,
        now=datetime(2026, 3, 28, 9, 50),
        minute_map=minute_map,
    )

    assert signal is not None
    assert signal.signal is True
    assert signal.signal_type == "legacy_low_open_repair"
    assert signal.details["buy_route"] == "legacy_low_open_repair"
    assert signal.details["low_confirmed"] is True
    assert signal.details["reclaim_from_low"] is True
    assert signal.details["near_day_low"] is True
    assert signal.details["not_still_falling"] is True


def test_legacy_low_open_blocks_when_price_is_still_falling():
    system = _build_system_stub()
    candidate = {"symbol": "600004", "name": "D", "strategy_profile": "legacy"}
    quote = {
        "symbol": "600004",
        "price": 9.46,
        "open": 9.70,
        "high": 9.72,
        "low": 9.40,
        "volume": 1200,
        "pre_close": 10.00,
    }
    minute_map = {
        "600004": _minute_frame(
            [
                (9.60, 9.64, 9.55, 100),
                (9.52, 9.56, 9.48, 120),
                (9.49, 9.52, 9.44, 110),
                (9.46, 9.49, 9.40, 130),
            ]
        )
    }

    signal = system._detect_legacy_gap_signal(
        candidate=candidate,
        quote=quote,
        now=datetime(2026, 3, 28, 9, 50),
        minute_map=minute_map,
    )

    assert signal is not None
    assert signal.signal is False
    assert signal.details["buy_route"] == "legacy_low_open_repair"
    assert signal.details["route_blocked"] is True
    assert signal.details["not_still_falling"] is False
    assert signal.details["low_confirmed"] is False


def test_legacy_low_open_blocks_when_rebound_has_chased_too_far():
    system = _build_system_stub()
    candidate = {"symbol": "600005", "name": "E", "strategy_profile": "legacy"}
    quote = {
        "symbol": "600005",
        "price": 9.68,
        "open": 9.70,
        "high": 9.70,
        "low": 9.40,
        "volume": 1200,
        "pre_close": 10.00,
    }
    minute_map = {
        "600005": _minute_frame(
            [
                (9.62, 9.65, 9.58, 100),
                (9.45, 9.50, 9.40, 150),
                (9.56, 9.60, 9.52, 120),
                (9.68, 9.70, 9.62, 130),
            ]
        )
    }

    signal = system._detect_legacy_gap_signal(
        candidate=candidate,
        quote=quote,
        now=datetime(2026, 3, 28, 9, 50),
        minute_map=minute_map,
    )

    assert signal is not None
    assert signal.signal is False
    assert signal.details["buy_route"] == "legacy_low_open_repair"
    assert signal.details["route_blocked"] is True
    assert signal.details["low_confirmed"] is True
    assert signal.details["reclaim_from_low"] is True
    assert signal.details["near_day_low"] is False


def test_enhanced_profile_uses_confirmation_template():
    system = _build_system_stub()
    candidate = {"symbol": "600002", "name": "B", "strategy_profile": "enhanced"}
    quote = {
        "symbol": "600002",
        "price": 8.12,
        "open": 8.05,
        "high": 8.15,
        "low": 8.02,
        "volume": 600,
        "pre_close": 8.00,
    }

    signal = system._resolve_strategy_routed_signal(
        candidate=candidate,
        quote=quote,
        now=datetime(2026, 3, 28, 10, 5),
        minute_map={},
        market_env={"market_score": 65.0},
    )

    assert signal.signal is True
    assert signal.details["buy_template_source"] == "enhanced_confirmation_v1"
    assert signal.details["buy_route"] == "enhanced_confirmation"
    assert signal.details["buy_route_label"] == "增强分时确认"


def test_legacy_window_can_open_before_confirmation_window():
    system = _build_system_stub()
    system.candidate_pool = [{"symbol": "600001", "strategy_profile": "legacy"}]

    assert system._signal_monitor_window_open(
        now=datetime(2026, 3, 28, 9, 40),
        market_env={"market_score": 60.0},
    ) is True


def test_legacy_route_exit_override_reads_configured_profile():
    system = _build_system_stub()

    override = system._get_legacy_route_exit_override(
        strategy_profile="legacy",
        route_name="legacy_gap_mid_open",
    )

    assert override["dynamic_stop_loss_pct"] == -0.05
    assert override["dynamic_tp1_pct"] == 0.06
    assert override["dynamic_take_profit_pct"] == 0.10
    assert override["dynamic_trailing_stop_pct"] == 0.03
    assert override["max_hold_hours"] == 96.0
    assert override["carry_peak_arm_on_t1"] is True
