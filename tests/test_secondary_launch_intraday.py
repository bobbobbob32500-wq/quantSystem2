# -*- coding: utf-8 -*-
"""
二次启动盘中买点测试
"""

from __future__ import annotations

from datetime import datetime

import pandas as pd

from src.modules.secondary_launch_intraday import detect_secondary_launch_signal


def test_detect_secondary_launch_breakout_signal():
    minute_df = pd.DataFrame(
        {
            "timestamp": pd.date_range("2026-04-01 10:00:00", periods=16, freq="min"),
            "open": [10.00, 10.02, 10.03, 10.04, 10.03, 10.05, 10.04, 10.05, 10.06, 10.05, 10.04, 10.05, 10.06, 10.08, 10.11, 10.15],
            "high": [10.03, 10.04, 10.05, 10.05, 10.05, 10.06, 10.06, 10.06, 10.07, 10.06, 10.06, 10.07, 10.08, 10.10, 10.13, 10.18],
            "low": [9.99, 10.00, 10.01, 10.02, 10.02, 10.03, 10.03, 10.04, 10.04, 10.03, 10.03, 10.04, 10.06, 10.10, 10.12, 10.14],
            "close": [10.02, 10.03, 10.04, 10.03, 10.05, 10.04, 10.05, 10.06, 10.05, 10.04, 10.05, 10.06, 10.09, 10.12, 10.15, 10.17],
            "volume": [100, 110, 120, 95, 105, 100, 98, 102, 101, 99, 100, 103, 120, 160, 190, 260],
        }
    )

    signal = detect_secondary_launch_signal(
        candidate={"symbol": "600468", "name": "百利电气"},
        quote={"price": 10.17, "open": 10.00, "high": 10.18, "low": 9.99, "volume": 260},
        now=datetime(2026, 4, 1, 10, 15, 0),
        minute_df=minute_df,
    )

    assert signal.signal is True
    assert signal.signal_type == "secondary_launch_breakout"
    assert signal.details["buy_route"] == "secondary_launch_breakout"


def test_detect_secondary_launch_pullback_signal():
    minute_df = pd.DataFrame(
        {
            "timestamp": pd.date_range("2026-04-01 10:00:00", periods=10, freq="min"),
            "open": [10.00, 10.05, 10.08, 10.12, 10.18, 10.16, 10.13, 10.12, 10.14, 10.17],
            "high": [10.05, 10.08, 10.12, 10.18, 10.20, 10.17, 10.14, 10.15, 10.18, 10.19],
            "low": [9.99, 10.04, 10.07, 10.11, 10.15, 10.12, 10.11, 10.11, 10.13, 10.15],
            "close": [10.04, 10.07, 10.11, 10.17, 10.16, 10.13, 10.12, 10.14, 10.17, 10.18],
            "volume": [150, 180, 220, 260, 180, 120, 90, 95, 130, 150],
        }
    )

    signal = detect_secondary_launch_signal(
        candidate={"symbol": "001258", "name": "立新能源"},
        quote={"price": 10.18, "open": 10.00, "high": 10.19, "low": 9.99, "volume": 150},
        now=datetime(2026, 4, 1, 10, 9, 0),
        minute_df=minute_df,
    )

    assert signal.signal is True
    assert signal.signal_type == "secondary_launch_pullback"
    assert signal.details["buy_route_label"] == "二次启动回踩确认"


def test_detect_secondary_launch_signal_blocked_by_weak_industry():
    minute_df = pd.DataFrame(
        {
            "timestamp": pd.date_range("2026-04-01 10:00:00", periods=16, freq="min"),
            "open": [10.00, 10.02, 10.03, 10.04, 10.03, 10.05, 10.04, 10.05, 10.06, 10.05, 10.04, 10.05, 10.06, 10.08, 10.11, 10.15],
            "high": [10.03, 10.04, 10.05, 10.05, 10.05, 10.06, 10.06, 10.06, 10.07, 10.06, 10.06, 10.07, 10.08, 10.10, 10.13, 10.18],
            "low": [9.99, 10.00, 10.01, 10.02, 10.02, 10.03, 10.03, 10.04, 10.04, 10.03, 10.03, 10.04, 10.05, 10.07, 10.09, 10.12],
            "close": [10.02, 10.03, 10.04, 10.03, 10.05, 10.04, 10.05, 10.06, 10.05, 10.04, 10.05, 10.06, 10.08, 10.11, 10.14, 10.17],
            "volume": [100, 110, 120, 95, 105, 100, 98, 102, 101, 99, 100, 103, 120, 160, 190, 260],
        }
    )

    signal = detect_secondary_launch_signal(
        candidate={"symbol": "600468", "name": "百利电气"},
        quote={"price": 10.17, "open": 10.00, "high": 10.18, "low": 9.99, "volume": 260},
        now=datetime(2026, 4, 1, 10, 15, 0),
        minute_df=minute_df,
        industry_confirm={"score": 38.0, "level": "weak", "industry": "电力设备"},
    )

    assert signal.signal is False
    assert signal.details["route_blocked"] is True


def test_detect_secondary_launch_breakout_vetoed_by_near_high_supply():
    minute_df = pd.DataFrame(
        {
            "timestamp": pd.date_range("2026-04-01 10:00:00", periods=16, freq="min"),
            "open": [10.00, 10.02, 10.03, 10.04, 10.03, 10.05, 10.04, 10.05, 10.06, 10.05, 10.04, 10.05, 10.06, 10.08, 10.11, 10.15],
            "high": [10.03, 10.04, 10.05, 10.05, 10.05, 10.06, 10.06, 10.06, 10.07, 10.06, 10.06, 10.07, 10.08, 10.10, 10.13, 10.20],
            "low": [9.99, 10.00, 10.01, 10.02, 10.02, 10.03, 10.03, 10.04, 10.04, 10.03, 10.03, 10.04, 10.06, 10.10, 10.12, 10.14],
            "close": [10.02, 10.03, 10.04, 10.03, 10.05, 10.04, 10.05, 10.06, 10.05, 10.04, 10.05, 10.06, 10.09, 10.12, 10.15, 10.17],
            "volume": [100, 110, 120, 95, 105, 100, 98, 102, 101, 99, 100, 103, 120, 160, 190, 190],
        }
    )

    signal = detect_secondary_launch_signal(
        candidate={"symbol": "600468", "name": "百利电气"},
        quote={"price": 10.17, "open": 10.00, "high": 10.20, "low": 9.99, "volume": 190},
        now=datetime(2026, 4, 1, 10, 15, 0),
        minute_df=minute_df,
    )

    assert signal.signal is False
    assert signal.reason == "前高抛压过近且量能不足，突破信号否决"
    assert signal.details["near_high_supply_veto"] is True


def test_detect_secondary_launch_breakout_requires_higher_afternoon_threshold():
    minute_df = pd.DataFrame(
        {
            "timestamp": pd.date_range("2026-04-01 13:20:00", periods=16, freq="min"),
            "open": [10.00, 10.02, 10.03, 10.04, 10.03, 10.05, 10.04, 10.05, 10.06, 10.05, 10.04, 10.05, 10.06, 10.08, 10.11, 10.15],
            "high": [10.03, 10.04, 10.05, 10.05, 10.05, 10.06, 10.06, 10.06, 10.07, 10.06, 10.06, 10.07, 10.08, 10.10, 10.13, 10.18],
            "low": [9.99, 10.00, 10.01, 10.02, 10.02, 10.03, 10.03, 10.04, 10.04, 10.03, 10.03, 10.04, 10.06, 10.10, 10.12, 10.14],
            "close": [10.02, 10.03, 10.04, 10.03, 10.05, 10.04, 10.05, 10.06, 10.05, 10.04, 10.05, 10.06, 10.09, 10.12, 10.15, 10.17],
            "volume": [100, 110, 120, 95, 105, 100, 98, 102, 101, 99, 100, 103, 120, 160, 190, 205],
        }
    )

    signal = detect_secondary_launch_signal(
        candidate={"symbol": "600468", "name": "百利电气"},
        quote={"price": 10.17, "open": 10.00, "high": 10.18, "low": 9.99, "volume": 205},
        now=datetime(2026, 4, 1, 13, 35, 0),
        minute_df=minute_df,
    )

    assert signal.signal is False
    assert signal.reason == "午后首次突破阈值更高，当前量能不足"
    assert signal.details["afternoon_breakout_tightened"] is True
    assert signal.details["required_volume_ratio"] == 1.6


def test_detect_secondary_launch_breakout_requires_higher_threshold_in_weak_market():
    minute_df = pd.DataFrame(
        {
            "timestamp": pd.date_range("2026-04-01 10:00:00", periods=16, freq="min"),
            "open": [10.00, 10.02, 10.03, 10.04, 10.03, 10.05, 10.04, 10.05, 10.06, 10.05, 10.04, 10.05, 10.06, 10.08, 10.11, 10.15],
            "high": [10.03, 10.04, 10.05, 10.05, 10.05, 10.06, 10.06, 10.06, 10.07, 10.06, 10.06, 10.07, 10.08, 10.10, 10.13, 10.18],
            "low": [9.99, 10.00, 10.01, 10.02, 10.02, 10.03, 10.03, 10.04, 10.04, 10.03, 10.03, 10.04, 10.06, 10.10, 10.12, 10.14],
            "close": [10.02, 10.03, 10.04, 10.03, 10.05, 10.04, 10.05, 10.06, 10.05, 10.04, 10.05, 10.06, 10.09, 10.12, 10.15, 10.17],
            "volume": [100, 110, 120, 95, 105, 100, 98, 102, 101, 99, 100, 103, 120, 160, 190, 210],
        }
    )

    signal = detect_secondary_launch_signal(
        candidate={"symbol": "600468", "name": "百利电气"},
        quote={"price": 10.17, "open": 10.00, "high": 10.18, "low": 9.99, "volume": 210},
        now=datetime(2026, 4, 1, 10, 15, 0),
        minute_df=minute_df,
        market_confirm={"market_score": 40.0, "trend": "down"},
    )

    assert signal.signal is False
    assert signal.reason == "市场共振偏弱，突破量能未达提高阈值"
    assert signal.details["market_gate_tightened"] is True
    assert signal.details["required_volume_ratio"] == 1.6
