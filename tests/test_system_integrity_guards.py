# -*- coding: utf-8 -*-
"""Regression guards for duplicate methods, realtime minute requirements and optimizer sensitivity."""

from __future__ import annotations

import ast
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pandas as pd

from src.modules.complete_strategy_system import CompleteStrategySystem
from src.modules.enhanced_hybrid_system import EnhancedHybridSystem


def _class_method_duplicates(path_str: str, class_name: str):
    path = Path(path_str)
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            names = {}
            duplicates = []
            for item in node.body:
                if isinstance(item, ast.FunctionDef):
                    names.setdefault(item.name, []).append(item.lineno)
            for name, lines in names.items():
                if len(lines) > 1:
                    duplicates.append((name, lines))
            return duplicates
    raise AssertionError(f"class not found: {class_name}")


def test_critical_classes_have_no_duplicate_method_definitions():
    assert _class_method_duplicates(
        "src/modules/enhanced_hybrid_system.py",
        "EnhancedHybridSystem",
    ) == []
    assert _class_method_duplicates(
        "src/modules/message_pusher.py",
        "MessagePusher",
    ) == []


def test_realtime_intraday_signal_builder_does_not_fallback_to_pseudo_data():
    system = EnhancedHybridSystem.__new__(EnhancedHybridSystem)
    system._build_intraday_from_minute = lambda minute_df: None
    system._build_intraday_data = lambda *args, **kwargs: "pseudo_intraday"

    intraday = system._get_intraday_data_for_signal(
        symbol="600001",
        current_price=10.0,
        current_volume=1000.0,
        high=10.2,
        low=9.8,
        minute_map={},
    )

    assert intraday is None


def test_confirmation_signal_is_blocked_when_realtime_minute_data_missing():
    system = EnhancedHybridSystem.__new__(EnhancedHybridSystem)
    system.config = {"debounce_window": 2}
    system.overnight_selector = SimpleNamespace(strategy_profile="legacy")
    system.system_config = SimpleNamespace(get=lambda *_args, **_kwargs: "legacy")
    system.signal_detector = SimpleNamespace(
        mutual_exclusive_signal=lambda *_args, **_kwargs: None,
    )
    system._get_intraday_data_for_signal = lambda **_kwargs: None

    signal = system._detect_confirmation_signal(
        candidate={"symbol": "600001", "strategy_profile": "legacy"},
        quote={"price": 10.1, "open": 10.0, "high": 10.2, "low": 9.9, "pre_close": 9.95, "volume": 1000},
        now=datetime(2026, 3, 29, 9, 45, 0),
        minute_map={},
        market_env={"market_score": 65.0},
        template_source="legacy_confirmation_fallback_v1",
        route_name="legacy_confirmation_fallback",
        route_label="原策略确认兜底",
    )

    assert signal.signal is False
    assert signal.details["route_blocked"] is True
    assert signal.reason == "缺少真实分钟数据，跳过执行信号"
    assert signal.details["data_source"] == "missing_realtime_minute"


def test_strategy_evaluation_changes_with_parameters():
    system = EnhancedHybridSystem.__new__(EnhancedHybridSystem)
    trades = [
        {
            "buy_time": "2026-03-20 09:35:00",
            "sell_time": "2026-03-20 14:30:00",
            "raw_pnl_pct": 0.02,
            "peak_pnl_pct": 0.12,
            "lowest_pnl_pct": -0.01,
            "signal_score": 85.0,
            "weight": 1.0,
        },
        {
            "buy_time": "2026-03-20 10:05:00",
            "sell_time": "2026-03-20 14:30:00",
            "raw_pnl_pct": -0.03,
            "peak_pnl_pct": 0.01,
            "lowest_pnl_pct": -0.08,
            "signal_score": 65.0,
            "weight": 1.0,
        },
    ]

    baseline = system._evaluate_strategy(
        trades,
        {"min_signal_score": 0.60, "stop_loss_pct": -0.05, "take_profit_pct": 0.10},
    )
    tuned = system._evaluate_strategy(
        trades,
        {"min_signal_score": 0.80, "stop_loss_pct": -0.03, "take_profit_pct": 0.05},
    )

    assert baseline["trade_count"] == 2
    assert tuned["trade_count"] == 1
    assert tuned["avg_pnl"] != baseline["avg_pnl"]


def test_complete_strategy_system_returns_composite_score_for_dataframe_input():
    system = CompleteStrategySystem()
    result = system.run_complete_pipeline(pd.DataFrame())
    assert result.composite_score == 0.0
    assert isinstance(result.summary, dict)
