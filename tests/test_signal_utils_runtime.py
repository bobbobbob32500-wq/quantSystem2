# -*- coding: utf-8 -*-
"""Regression tests for signal utility runtime helpers."""

from __future__ import annotations

from datetime import time

import pandas as pd

from src.modules.enhanced_hybrid_system import EnhancedHybridSystem
from src.modules.optimized_buy_signals import SignalOutput


def _build_system_stub() -> EnhancedHybridSystem:
    system = EnhancedHybridSystem.__new__(EnhancedHybridSystem)
    system.config = {"debounce_window": 2}
    return system


def test_wrap_signal_metadata_populates_route_fields():
    system = _build_system_stub()
    signal = SignalOutput(
        signal=True,
        signal_type="breakout",
        confidence=0.8,
        reason="test",
        details={},
    )

    wrapped = system._wrap_signal_metadata(
        signal=signal,
        strategy_profile="legacy_opt",
        template_source="legacy_gap_open_v1",
        route_name="legacy_gap_mid_open",
        route_label="中强开盘直入",
        debounce_window=1,
        route_blocked=True,
    )

    assert wrapped.details["strategy_profile"] == "legacy_opt"
    assert wrapped.details["buy_template_source"] == "legacy_gap_open_v1"
    assert wrapped.details["buy_route"] == "legacy_gap_mid_open"
    assert wrapped.details["buy_route_label"] == "中强开盘直入"
    assert wrapped.details["route_blocked"] is True
    assert wrapped.details["debounce_window"] == 1


def test_build_false_signal_keeps_reason_and_extra_details():
    system = _build_system_stub()

    signal = system._build_false_signal(
        strategy_profile="legacy",
        template_source="legacy_gap_open_v1",
        route_name="legacy_flat_gap_skip",
        route_label="平弱开盘跳过",
        reason="平弱开盘过滤",
        debounce_window=1,
        route_blocked=True,
        extra_details={"filter_reason": "flat_gap_skip"},
    )

    assert signal.signal is False
    assert signal.reason == "平弱开盘过滤"
    assert signal.details["filter_reason"] == "flat_gap_skip"
    assert signal.details["buy_route"] == "legacy_flat_gap_skip"
    assert signal.details["route_blocked"] is True


def test_calc_open_pct_and_vwap_and_time_window_helpers_remain_stable():
    minute_df = pd.DataFrame(
        [
            {"close": 10.0, "volume": 100},
            {"close": 10.2, "volume": 200},
        ]
    )

    assert EnhancedHybridSystem._calc_open_pct(10.0, 9.5) > 0
    assert EnhancedHybridSystem._calc_open_pct(0.0, 9.5) == 0.0
    assert round(EnhancedHybridSystem._calc_intraday_vwap(minute_df, 9.9), 4) == 10.1333
    assert EnhancedHybridSystem._is_time_in_window(time(9, 40), time(9, 35), time(10, 30)) is True


def test_resolve_signal_debounce_window_uses_details_override():
    system = _build_system_stub()
    signal = SignalOutput(
        signal=True,
        signal_type="breakout",
        confidence=0.8,
        reason="test",
        details={"debounce_window": 4},
    )

    assert system._resolve_signal_debounce_window(signal) == 4
