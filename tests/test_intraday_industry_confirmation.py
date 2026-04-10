# -*- coding: utf-8 -*-
"""Unit tests for intraday industry confirmation in EnhancedHybridSystem."""

from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace

import pandas as pd

from src.modules.enhanced_hybrid_system import EnhancedHybridSystem


def _build_system_stub() -> EnhancedHybridSystem:
    system = EnhancedHybridSystem.__new__(EnhancedHybridSystem)
    system.enable_intraday_industry_confirmation = True
    system.intraday_industry_min_symbols = 1
    system.intraday_industry_lookback_bars = 5
    system.intraday_industry_strong_threshold = 65.0
    system.intraday_industry_weak_threshold = 40.0
    system.intraday_industry_cache_seconds = 0
    system._industry_realtime_cache = {"ts": None, "context": None}
    system.latest_industry_context = {}
    system.candidate_pool = [
        {"symbol": "600001", "industry": "化学制药", "score": 82.0, "pool_type": "core", "name": "A"},
        {"symbol": "600002", "industry": "电力", "score": 76.0, "pool_type": "reserve", "name": "B"},
    ]
    system.min_signal_score_for_push = 75
    system.feedback_adaptive_cache_seconds = 300
    system._feedback_adaptive_cache = {"ts": 0.0, "profiles": {}}
    system.db = SimpleNamespace(query_one=lambda *_args, **_kwargs: None)
    return system


def _minute_frame(prices, volumes) -> pd.DataFrame:
    base = datetime(2026, 3, 27, 10, 0, 0)
    rows = []
    for i, (price, volume) in enumerate(zip(prices, volumes)):
        rows.append(
            {
                "trade_time": base + timedelta(minutes=i),
                "close": float(price),
                "volume": float(volume),
            }
        )
    return pd.DataFrame(rows)


def test_intraday_industry_context_fallback_builds_scores():
    system = _build_system_stub()
    system._fetch_realtime_industry_context_from_source = lambda: None

    minute_map = {
        "600001": _minute_frame([10, 10.1, 10.2, 10.3, 10.5, 10.6], [100, 120, 130, 140, 160, 170]),
        "600002": _minute_frame([8.0, 7.95, 7.9, 7.85, 7.88, 7.86], [90, 95, 100, 110, 100, 90]),
    }

    context = system._build_intraday_industry_context(
        minute_map=minute_map,
        now=datetime(2026, 3, 27, 10, 30, 0),
    )

    assert context["enabled"] is True
    assert context["source"] == "candidate_minute_fallback"
    assert "化学制药" in context["industry_map"]
    assert "电力" in context["industry_map"]
    assert context["industry_map"]["化学制药"]["score"] > context["industry_map"]["电力"]["score"]


def test_intraday_industry_context_accepts_string_numeric_config():
    system = _build_system_stub()
    system._fetch_realtime_industry_context_from_source = lambda: None
    system.intraday_industry_min_symbols = "1"
    system.intraday_industry_lookback_bars = "5"

    minute_map = {
        "600001": _minute_frame([10, 10.1, 10.2, 10.3, 10.5, 10.6], [100, 120, 130, 140, 160, 170]),
        "600002": _minute_frame([8.0, 7.95, 7.9, 7.85, 7.88, 7.86], [90, 95, 100, 110, 100, 90]),
    }

    context = system._build_intraday_industry_context(
        minute_map=minute_map,
        now=datetime(2026, 3, 27, 10, 30, 0),
    )

    assert context["enabled"] is True
    assert context["source"] == "candidate_minute_fallback"
    assert len(context["industry_map"]) >= 1
    assert all("score" in item for item in context["industry_map"].values())


def test_intraday_industry_context_no_longer_calls_primary_source():
    system = _build_system_stub()
    system._fetch_realtime_industry_context_from_source = lambda: (_ for _ in ()).throw(
        AssertionError("primary source should not be called")
    )

    minute_map = {
        "600001": _minute_frame([10, 10.1, 10.2, 10.3, 10.5, 10.6], [100, 120, 130, 140, 160, 170]),
    }
    context = system._build_intraday_industry_context(
        minute_map=minute_map,
        now=datetime(2026, 3, 27, 10, 30, 0),
    )

    assert context["enabled"] is True
    assert context["source"] == "candidate_minute_fallback"
    assert context["source_available"] is False


def test_thresholds_and_total_score_adjust_by_industry_confirmation():
    system = _build_system_stub()

    candidate = {"score": 80.0, "pool_type": "core"}
    market_env = {"market_score": 70.0, "volatility": "normal", "trend": "sideways"}
    signal = SimpleNamespace(confidence=0.75)

    strong_threshold = system._get_dynamic_signal_thresholds(
        candidate,
        market_env,
        industry_confirm={"level": "strong"},
    )
    weak_threshold = system._get_dynamic_signal_thresholds(
        candidate,
        market_env,
        industry_confirm={"level": "weak"},
    )

    assert strong_threshold["min_total_score"] < weak_threshold["min_total_score"]
    assert strong_threshold["push_threshold"] < weak_threshold["push_threshold"]

    base_total = system._calculate_total_signal_score(candidate, signal, market_env, industry_score_adjustment=0.0)
    strong_total = system._calculate_total_signal_score(candidate, signal, market_env, industry_score_adjustment=3.0)
    weak_total = system._calculate_total_signal_score(candidate, signal, market_env, industry_score_adjustment=-4.0)

    assert strong_total > base_total > weak_total


def test_secondary_launch_best_subtype_gets_lower_threshold():
    system = _build_system_stub()
    system.db = SimpleNamespace(
        query_one=lambda *_args, **_kwargs: {
            "run_id": "run_best",
            "meta_json": (
                '{"signal_meta":{"insights":{"best_signal_type":{"signal_type":"secondary_launch_breakout"}},'
                '"signal_type_stats":[{"signal_type":"secondary_launch_breakout","sample_count":6,"win_rate":0.71,"mean_net_return":0.021}]}}'
            ),
        }
    )
    candidate = {"score": 80.0, "pool_type": "core"}
    market_env = {"market_score": 70.0, "volatility": "normal", "trend": "sideways"}

    boosted = system._get_dynamic_signal_thresholds(
        candidate,
        market_env,
        industry_confirm={"level": "neutral"},
        strategy_profile="secondary_launch",
        signal_subtype="secondary_launch_breakout",
    )
    neutral = system._get_dynamic_signal_thresholds(
        candidate,
        market_env,
        industry_confirm={"level": "neutral"},
        strategy_profile="secondary_launch",
        signal_subtype="secondary_launch_pullback",
    )

    assert boosted["min_total_score"] < neutral["min_total_score"]
    assert boosted["push_threshold"] < neutral["push_threshold"]


def test_secondary_launch_old_feedback_meta_does_not_break_thresholds():
    system = _build_system_stub()
    system.db = SimpleNamespace(
        query_one=lambda *_args, **_kwargs: {
            "run_id": "run_old",
            "meta_json": '{"signal_meta":{"signal_count":51,"detail_count":102,"horizons":[1,2,3]}}',
        }
    )
    candidate = {"score": 80.0, "pool_type": "core"}
    market_env = {"market_score": 70.0, "volatility": "normal", "trend": "sideways"}

    thresholds = system._get_dynamic_signal_thresholds(
        candidate,
        market_env,
        industry_confirm={"level": "neutral"},
        strategy_profile="secondary_launch",
        signal_subtype="secondary_launch_breakout",
    )

    assert thresholds["min_total_score"] >= 65.0
    assert thresholds["push_threshold"] >= 70.0
