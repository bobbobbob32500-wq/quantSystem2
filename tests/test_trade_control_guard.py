# -*- coding: utf-8 -*-
"""Unit tests for market gate, circuit breaker and position linkage."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pandas as pd

from src.modules.enhanced_hybrid_system import EnhancedHybridSystem


def _build_system_stub() -> EnhancedHybridSystem:
    system = EnhancedHybridSystem.__new__(EnhancedHybridSystem)
    system.runtime_monitor = None

    system.market_gate_enabled = True
    system.market_gate_refresh_seconds = 0
    system.market_gate_open_min_target_position = 0.30
    system.market_gate_force_defensive_regimes = {"WEAK_BEAR", "BEAR", "STRONG_BEAR"}
    system.market_gate_defensive_score_boost = 4.0
    system.market_gate_defensive_push_boost = 4.0
    system.market_gate_defensive_position_multiplier = 0.60
    system.market_gate_normal_max_signals_per_round = 4
    system.market_gate_defensive_max_signals_per_round = 2
    system._market_gate_cache = {"ts": None, "context": None}

    system.intraday_circuit_breaker_enabled = True
    system.circuit_soft_trigger_drop_pct = -1.2
    system.circuit_hard_trigger_drop_pct = -2.0
    system.circuit_soft_breadth_threshold = 0.35
    system.circuit_hard_breadth_threshold = 0.25
    system.circuit_hold_seconds = 0
    system.circuit_recover_drop_pct = -0.8
    system.circuit_recover_breadth_threshold = 0.45
    system.circuit_soft_score_boost = 3.0
    system.circuit_soft_push_boost = 2.0
    system.circuit_soft_position_multiplier = 0.5
    system.circuit_index_codes = ["000001.SH", "399001.SZ", "399006.SZ"]
    system._circuit_breaker_state = {"state": "normal", "since": None, "last_change": None, "reason": ""}

    system.position_linkage_enabled = True
    system.position_linkage_per_signal_cap = 0.10
    system.position_linkage_min_ratio = 0.02
    system.feedback_adaptive_cache_seconds = 300
    system._feedback_adaptive_cache = {"ts": 0.0, "profiles": {}}
    system.db = SimpleNamespace(query_one=lambda *_args, **_kwargs: None)

    system.push_enabled = False
    system.message_pusher = SimpleNamespace(enabled=False, push_markdown=lambda *_args, **_kwargs: True)
    system._last_trade_control_snapshot = None
    system._last_trade_control_alert_at = None
    system.trade_control_alert_cooldown_seconds = 0
    system.trade_control_status_print_interval_seconds = 0
    system._last_trade_control_status_print_at = None
    system.latest_trade_control_context = {}
    return system


def test_market_gate_switches_to_defensive_for_bear_regime():
    system = _build_system_stub()
    system.position_controller = SimpleNamespace(
        analyze_market=lambda end_date=None: {
            "market_regime": "BEAR",
            "risk_state": "HIGH",
            "target_position": 0.12,
        }
    )

    context = system._get_market_gate_context(now=datetime(2026, 3, 28, 10, 0, 0))

    assert context["tier"] == "defensive"
    assert context["target_position"] == 0.12
    assert context["threshold_boost"] == 4.0
    assert context["max_signals_per_round"] == 2


def test_compose_trade_control_hard_circuit_blocks_new_signals():
    system = _build_system_stub()
    system.position_controller = SimpleNamespace(
        analyze_market=lambda end_date=None: {
            "market_regime": "NEUTRAL",
            "risk_state": "MEDIUM",
            "target_position": 0.30,
        }
    )
    system._fetch_index_pct_change_map = lambda: {}

    quote_df = pd.DataFrame(
        [
            {"symbol": "600001", "price": 9.7, "pre_close": 10.0},
            {"symbol": "600002", "price": 7.8, "pre_close": 8.0},
            {"symbol": "600003", "price": 11.7, "pre_close": 12.0},
        ]
    )

    context = system._compose_trade_control_context(
        now=datetime(2026, 3, 28, 10, 1, 0),
        quote_df=quote_df,
    )

    assert context["circuit_state"] == "hard"
    assert context["allow_new_signals"] is False
    assert context["position_multiplier"] == 0.0
    assert context["max_signals_per_round"] == 0


def test_build_position_advice_applies_cap_and_block():
    system = _build_system_stub()
    candidate = {"pool_type": "reserve"}
    control = {"allow_new_signals": True, "target_position": 0.5, "position_multiplier": 1.0}

    advice = system._build_position_advice(candidate=candidate, total_score=90.0, trade_control=control)
    assert advice["suggest_position_ratio"] == 0.10
    assert advice["suggest_position_pct"] == 10.0

    blocked = system._build_position_advice(
        candidate=candidate,
        total_score=90.0,
        trade_control={"allow_new_signals": False},
    )
    assert blocked["suggest_position_ratio"] == 0.0
    assert blocked["suggest_position_pct"] == 0.0


def test_build_position_advice_boosts_best_secondary_launch_subtype():
    system = _build_system_stub()
    system.db = SimpleNamespace(
        query_one=lambda *_args, **_kwargs: {
            "run_id": "run_best",
            "meta_json": (
                '{"signal_meta":{"insights":{"best_signal_type":{"signal_type":"secondary_launch_breakout"}},'
                '"signal_type_stats":[{"signal_type":"secondary_launch_breakout","sample_count":6,"win_rate":0.67,"mean_net_return":0.025}]}}'
            ),
        }
    )
    candidate = {"pool_type": "core"}
    control = {"allow_new_signals": True, "target_position": 0.08, "position_multiplier": 1.0}

    advice = system._build_position_advice(
        candidate=candidate,
        total_score=88.0,
        trade_control=control,
        strategy_profile="secondary_launch",
        signal_subtype="secondary_launch_breakout",
    )

    assert advice["suggest_position_ratio"] > 0.08
    assert "feedback_best_subtype_boost" in advice["position_note"]


def test_build_sell_signals_from_closed_trades_maps_reason_and_fields():
    system = _build_system_stub()
    closed_trades = [
        SimpleNamespace(
            symbol="600519",
            name="贵州茅台",
            buy_price=1500.0,
            sell_price=1515.0,
            sell_reason="take_profit",
            pnl_pct=0.01,
            hold_duration=45,
            buy_score=86.0,
            details={},
        )
    ]
    control = {"gate_tier": "defensive", "circuit_state": "soft"}

    signals = system._build_sell_signals_from_closed_trades(
        closed_trades=closed_trades,
        trade_control=control,
    )

    assert len(signals) == 1
    signal = signals[0]
    assert signal["action"] == "SELL"
    assert signal["signal_type"] == "止盈卖点"
    assert signal["market_gate_tier"] == "defensive"
    assert signal["circuit_state"] == "soft"
    assert signal["suggest_position_pct"] == 0.0
