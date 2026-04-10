# -*- coding: utf-8 -*-
"""Regression tests for buy-signal building runtime helpers."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

from src.modules.enhanced_hybrid_system import EnhancedHybridSystem


def test_build_buy_signal_keeps_runtime_exit_params_and_legacy_route_override():
    system = EnhancedHybridSystem.__new__(EnhancedHybridSystem)
    system.min_signal_score_for_push = 75
    system.optimization_apply_to_thresholds = True
    system.optimization_apply_to_exit_params = True
    system.optimization_runtime_enabled = True
    system.enable_auto_optimization = True
    system.position_linkage_enabled = True
    system.position_linkage_per_signal_cap = 0.10
    system.position_linkage_min_ratio = 0.02
    system.feedback_adaptive_cache_seconds = 300
    system._feedback_adaptive_cache = {"ts": 0.0, "profiles": {}}
    system.db = SimpleNamespace(query_one=lambda *_args, **_kwargs: None)
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
    system._get_optimization_runtime_profile = lambda now=None: {
        "active": True,
        "reason": "test_profile",
        "score_delta": 1.5,
        "trade_count": 12,
        "min_total_score_floor": 70.0,
        "min_intraday_score_floor": 55.0,
        "push_threshold_floor": 76.0,
        "exit_params": {
            "stop_loss_pct": -0.02,
            "take_profit_pct": 0.08,
            "tp1_pct": 0.04,
            "trailing_stop_pct": 0.025,
            "max_hold_hours": 48,
        },
    }
    system._resolve_candidate_industry_confirm = lambda candidate, industry_context: {
        "industry": candidate.get("industry", ""),
        "score": 72.0,
        "level": "strong",
        "score_adjustment": 3.0,
        "source": "test",
    }
    system._build_position_advice = lambda candidate, total_score, trade_control, strategy_profile="", signal_subtype="": {
        "suggest_position_ratio": 0.085,
        "suggest_position_pct": 8.5,
        "position_note": "test_position_note",
    }

    candidate = {
        "symbol": "600001",
        "name": "测试股",
        "score": 82.0,
        "pool_type": "core",
        "industry": "电力",
        "strategy_profile": "legacy_opt",
    }
    signal = SimpleNamespace(
        confidence=0.82,
        reason="原策略开盘强势买点",
        details={
            "buy_template_source": "legacy_gap_open_v1",
            "buy_route": "legacy_gap_mid_open",
            "buy_route_label": "中强开盘直入",
        },
    )

    buy_signal = system._build_buy_signal(
        candidate=candidate,
        current_price=10.26,
        signal=signal,
        now=datetime(2026, 3, 29, 9, 40, 0),
        market_env={"market_score": 72.0, "volatility": "normal", "trend": "sideways"},
        industry_context=None,
        trade_control={"gate_tier": "normal", "circuit_state": "normal"},
    )

    assert buy_signal is not None
    assert buy_signal["strategy_profile"] == "legacy_opt"
    assert buy_signal["strategy_label"] == "原策略优化版"
    assert buy_signal["runtime_optimization_active"] is True
    assert buy_signal["runtime_optimization_reason"] == "test_profile"
    assert buy_signal["runtime_optimization_trade_count"] == 12
    assert buy_signal["suggest_position_pct"] == 8.5
    assert buy_signal["buy_route"] == "legacy_gap_mid_open"
    assert buy_signal["buy_route_label"] == "中强开盘直入"
    assert buy_signal["dynamic_stop_loss_pct"] == -0.05
    assert buy_signal["dynamic_tp1_pct"] == 0.06
    assert buy_signal["dynamic_take_profit_pct"] == 0.10
    assert buy_signal["dynamic_trailing_stop_pct"] == 0.03
    assert buy_signal["max_hold_hours"] == 96.0
    assert buy_signal["carry_peak_arm_on_t1"] is True
    assert buy_signal["signal_details"]["legacy_exit_override_applied"] is True


def test_build_buy_signal_applies_secondary_launch_replay_exit_profile():
    system = EnhancedHybridSystem.__new__(EnhancedHybridSystem)
    system.min_signal_score_for_push = 75
    system.optimization_apply_to_thresholds = True
    system.optimization_apply_to_exit_params = True
    system.optimization_runtime_enabled = True
    system.enable_auto_optimization = True
    system.position_linkage_enabled = True
    system.position_linkage_per_signal_cap = 0.10
    system.position_linkage_min_ratio = 0.02
    system.feedback_adaptive_cache_seconds = 300
    system._feedback_adaptive_cache = {"ts": 0.0, "profiles": {}}
    system.db = SimpleNamespace(query_one=lambda *_args, **_kwargs: None)
    system.legacy_route_exit_override_enabled = False
    system.legacy_route_exit_overrides = {}
    system._get_optimization_runtime_profile = lambda now=None: {
        "active": True,
        "reason": "test_profile",
        "score_delta": 1.0,
        "trade_count": 8,
        "min_total_score_floor": 70.0,
        "min_intraday_score_floor": 55.0,
        "push_threshold_floor": 76.0,
        "exit_params": {
            "stop_loss_pct": -0.03,
            "take_profit_pct": 0.10,
            "tp1_pct": 0.05,
            "trailing_stop_pct": 0.02,
            "max_hold_hours": 8,
        },
    }
    system._resolve_candidate_industry_confirm = lambda candidate, industry_context: {
        "industry": candidate.get("industry", ""),
        "score": 60.0,
        "level": "neutral",
        "score_adjustment": 0.0,
        "source": "test",
    }
    system._build_position_advice = lambda candidate, total_score, trade_control, strategy_profile="", signal_subtype="": {
        "suggest_position_ratio": 0.06,
        "suggest_position_pct": 6.0,
        "position_note": "test_position_note",
    }

    candidate = {
        "symbol": "600468",
        "name": "百利电气",
        "score": 90.0,
        "pool_type": "core",
        "industry": "电气设备",
        "strategy_profile": "secondary_launch",
    }
    signal = SimpleNamespace(
        confidence=0.78,
        reason="二次启动回踩确认",
        details={
            "buy_template_source": "secondary_launch_pullback_v1",
            "buy_route": "secondary_launch_pullback",
            "signal_subtype": "secondary_launch_pullback",
            "buy_route_label": "二次启动回踩确认",
        },
    )

    buy_signal = system._build_buy_signal(
        candidate=candidate,
        current_price=8.52,
        signal=signal,
        now=datetime(2026, 4, 1, 10, 20, 0),
        market_env={"market_score": 72.0, "volatility": "normal", "trend": "sideways"},
        industry_context=None,
        trade_control={"gate_tier": "normal", "circuit_state": "normal"},
    )

    assert buy_signal is not None
    assert buy_signal["strategy_profile"] == "secondary_launch"
    assert buy_signal["dynamic_stop_loss_pct"] == -0.015
    assert buy_signal["dynamic_take_profit_pct"] == 0.08
    assert buy_signal["dynamic_tp1_pct"] == 0.04
    assert buy_signal["disable_dynamic_trailing_stop"] is True
    assert buy_signal["min_hold_trading_days"] == 1
    assert buy_signal["next_day_observation_window_minutes"] == 240
    assert buy_signal["secondary_launch_exit_profile"] == "replay_best_t1_v2"
    assert buy_signal["signal_details"]["replay_exit_profile_applied"] is True
