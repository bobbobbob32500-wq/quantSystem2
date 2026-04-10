# -*- coding: utf-8 -*-
"""
二次启动策略筛选测试
"""

from __future__ import annotations

import pandas as pd

from src.modules.mainboard_secondary_launch_strategy import (
    MainboardSecondaryLaunchStrategy,
    StrategyParams,
)


def test_select_candidates_keeps_relaxed_secondary_launch_setup():
    params = StrategyParams(
        rs_lookback=2,
        min_score=40.0,
        limit_up_count_10_min=1,
        limit_up_count_10_max=3,
        last_limit_up_days_min=2,
        last_limit_up_days_max=10,
        drawdown_min=0.01,
        drawdown_max=0.12,
        vol_shrink_ratio=0.8,
        close_ma5_dev_max=0.04,
        max_candidates=10,
        picks_per_day=3,
    )
    strategy = MainboardSecondaryLaunchStrategy(params)

    feature_df = pd.DataFrame(
        [
            {
                "ts_code": "600001.SH",
                "trade_date": pd.Timestamp("2026-03-10"),
                "name": "测试标的",
                "is_mainboard": True,
                "is_risk_name": False,
                "list_days": 800,
                "vol": 700.0,
                "close": 10.2,
                "amt_ma20": 300000.0,
                "limit_down_count_20": 0.0,
                "limit_up_count_10": 2.0,
                "days_since_last_limit_up": 6.0,
                "drawdown_from_peak": 0.05,
                "vol_ma5": 1000.0,
                "vol_ma20": 900.0,
                "ma5": 10.1,
                "ma10": 9.9,
                "is_limit_up": False,
                "rs20": 0.12,
                "limit_up_amt_ratio": 1.8,
                "next_ret_after_limit_up": 0.03,
            }
        ]
    )

    selected = strategy.generate_daily_candidates(feature_df, pd.Timestamp("2026-03-11"))

    assert len(selected) == 1
    assert selected.iloc[0]["ts_code"] == "600001.SH"
    assert float(selected.iloc[0]["signal_score"]) >= params.min_score


def test_generate_signals_from_frame_orders_by_signal_score():
    params = StrategyParams(rs_lookback=2, min_score=35.0, picks_per_day=1, max_candidates=5)
    strategy = MainboardSecondaryLaunchStrategy(params)

    signal_frame = pd.DataFrame(
        [
            {
                "signal_date": pd.Timestamp("2026-03-11"),
                "ts_code": "600001.SH",
                "name": "高分",
                "is_mainboard": True,
                "is_risk_name": False,
                "list_days": 800,
                "vol": 650.0,
                "close": 10.3,
                "amt_ma20": 300000.0,
                "limit_down_count_20": 0.0,
                "limit_up_count_10": 2.0,
                "days_since_last_limit_up": 5.0,
                "drawdown_from_peak": 0.04,
                "vol_ma5": 1000.0,
                "vol_ma20": 850.0,
                "ma5": 10.2,
                "ma10": 9.8,
                "is_limit_up": False,
                "rs20": 0.16,
                "limit_up_amt_ratio": 1.6,
                "next_ret_after_limit_up": 0.04,
            },
            {
                "signal_date": pd.Timestamp("2026-03-11"),
                "ts_code": "600002.SH",
                "name": "低分",
                "is_mainboard": True,
                "is_risk_name": False,
                "list_days": 800,
                "vol": 920.0,
                "close": 10.0,
                "amt_ma20": 300000.0,
                "limit_down_count_20": 0.0,
                "limit_up_count_10": 1.0,
                "days_since_last_limit_up": 12.0,
                "drawdown_from_peak": 0.14,
                "vol_ma5": 1000.0,
                "vol_ma20": 980.0,
                "ma5": 10.1,
                "ma10": 9.95,
                "is_limit_up": False,
                "rs20": 0.08,
                "limit_up_amt_ratio": 0.5,
                "next_ret_after_limit_up": -0.03,
            },
        ]
    )

    signals = strategy.generate_signals_from_frame(signal_frame)

    assert len(signals) == 1
    assert signals.iloc[0]["ts_code"] == "600001.SH"
    assert "signal_score" in signals.columns


def test_generate_signals_respects_cooldown_between_days():
    params = StrategyParams(
        rs_lookback=2,
        min_score=35.0,
        picks_per_day=2,
        max_candidates=5,
        cooldown_days=2,
        second_pick_min_score=35.0,
        second_pick_score_gap=20.0,
    )
    strategy = MainboardSecondaryLaunchStrategy(params)

    base_row = {
        "is_mainboard": True,
        "is_risk_name": False,
        "list_days": 800,
        "vol": 650.0,
        "close": 10.3,
        "amt_ma20": 300000.0,
        "limit_down_count_20": 0.0,
        "limit_up_count_10": 2.0,
        "days_since_last_limit_up": 5.0,
        "drawdown_from_peak": 0.04,
        "vol_ma5": 1000.0,
        "vol_ma20": 850.0,
        "ma5": 10.2,
        "ma10": 9.8,
        "is_limit_up": False,
        "limit_up_amt_ratio": 1.6,
        "next_ret_after_limit_up": 0.04,
        "ret5": 0.02,
    }
    signal_frame = pd.DataFrame(
        [
            {"signal_date": pd.Timestamp("2026-03-11"), "ts_code": "600001.SH", "name": "重复股", "rs20": 0.16, **base_row},
            {"signal_date": pd.Timestamp("2026-03-11"), "ts_code": "600002.SH", "name": "补位股", "rs20": 0.12, **base_row},
            {"signal_date": pd.Timestamp("2026-03-12"), "ts_code": "600001.SH", "name": "重复股", "rs20": 0.17, **base_row},
            {"signal_date": pd.Timestamp("2026-03-12"), "ts_code": "600003.SH", "name": "新候选", "rs20": 0.11, **base_row},
        ]
    )

    signals = strategy.generate_signals_from_frame(signal_frame)

    assert list(signals[signals["signal_date"] == pd.Timestamp("2026-03-11")]["ts_code"]) == ["600001.SH", "600002.SH"]
    assert list(signals[signals["signal_date"] == pd.Timestamp("2026-03-12")]["ts_code"]) == ["600003.SH"]


def test_generate_signals_weak_market_limits_daily_picks():
    params = StrategyParams(
        rs_lookback=2,
        min_score=35.0,
        picks_per_day=2,
        max_candidates=5,
        weak_market_ret5_threshold=-0.01,
        weak_market_max_picks=1,
        weak_market_min_score_boost=0.0,
    )
    strategy = MainboardSecondaryLaunchStrategy(params)

    signal_frame = pd.DataFrame(
        [
            {
                "signal_date": pd.Timestamp("2026-03-11"),
                "ts_code": "600001.SH",
                "name": "候选A",
                "is_mainboard": True,
                "is_risk_name": False,
                "list_days": 800,
                "vol": 650.0,
                "close": 10.3,
                "amt_ma20": 300000.0,
                "limit_down_count_20": 0.0,
                "limit_up_count_10": 2.0,
                "days_since_last_limit_up": 5.0,
                "drawdown_from_peak": 0.04,
                "vol_ma5": 1000.0,
                "vol_ma20": 850.0,
                "ma5": 10.2,
                "ma10": 9.8,
                "is_limit_up": False,
                "rs20": 0.16,
                "limit_up_amt_ratio": 1.6,
                "next_ret_after_limit_up": 0.04,
                "ret5": 0.01,
            },
            {
                "signal_date": pd.Timestamp("2026-03-11"),
                "ts_code": "600002.SH",
                "name": "候选B",
                "is_mainboard": True,
                "is_risk_name": False,
                "list_days": 800,
                "vol": 660.0,
                "close": 10.2,
                "amt_ma20": 300000.0,
                "limit_down_count_20": 0.0,
                "limit_up_count_10": 2.0,
                "days_since_last_limit_up": 5.0,
                "drawdown_from_peak": 0.04,
                "vol_ma5": 1000.0,
                "vol_ma20": 850.0,
                "ma5": 10.1,
                "ma10": 9.8,
                "is_limit_up": False,
                "rs20": 0.14,
                "limit_up_amt_ratio": 1.5,
                "next_ret_after_limit_up": 0.03,
                "ret5": 0.01,
            },
            {
                "signal_date": pd.Timestamp("2026-03-11"),
                "ts_code": "000001.SH",
                "name": "上证指数",
                "is_mainboard": True,
                "is_risk_name": False,
                "list_days": 10000,
                "vol": 1000.0,
                "close": 3000.0,
                "amt_ma20": 1000000.0,
                "limit_down_count_20": 0.0,
                "limit_up_count_10": 2.0,
                "days_since_last_limit_up": 5.0,
                "drawdown_from_peak": 0.02,
                "vol_ma5": 1000.0,
                "vol_ma20": 1000.0,
                "ma5": 3010.0,
                "ma10": 3020.0,
                "is_limit_up": False,
                "rs20": -0.02,
                "limit_up_amt_ratio": 1.0,
                "next_ret_after_limit_up": 0.0,
                "ret5": -0.02,
            },
        ]
    )

    signals = strategy.generate_signals_from_frame(signal_frame)

    assert len(signals) == 1


def test_refine_daily_picks_drops_weak_second_pick():
    params = StrategyParams(
        rs_lookback=2,
        min_score=35.0,
        picks_per_day=2,
        max_candidates=5,
        second_pick_min_score=66.0,
        second_pick_score_gap=4.0,
    )
    strategy = MainboardSecondaryLaunchStrategy(params)

    signal_frame = pd.DataFrame(
        [
            {
                "signal_date": pd.Timestamp("2026-03-11"),
                "ts_code": "600001.SH",
                "name": "第一名",
                "is_mainboard": True,
                "is_risk_name": False,
                "list_days": 800,
                "vol": 650.0,
                "close": 10.4,
                "amt_ma20": 300000.0,
                "limit_down_count_20": 0.0,
                "limit_up_count_10": 2.0,
                "days_since_last_limit_up": 5.0,
                "drawdown_from_peak": 0.04,
                "vol_ma5": 1000.0,
                "vol_ma20": 850.0,
                "ma5": 10.2,
                "ma10": 9.8,
                "is_limit_up": False,
                "rs20": 0.20,
                "limit_up_amt_ratio": 1.8,
                "next_ret_after_limit_up": 0.06,
                "ret5": 0.02,
            },
            {
                "signal_date": pd.Timestamp("2026-03-11"),
                "ts_code": "600002.SH",
                "name": "边缘第二名",
                "is_mainboard": True,
                "is_risk_name": False,
                "list_days": 800,
                "vol": 900.0,
                "close": 10.0,
                "amt_ma20": 300000.0,
                "limit_down_count_20": 0.0,
                "limit_up_count_10": 1.0,
                "days_since_last_limit_up": 10.0,
                "drawdown_from_peak": 0.10,
                "vol_ma5": 1000.0,
                "vol_ma20": 950.0,
                "ma5": 10.0,
                "ma10": 9.9,
                "is_limit_up": False,
                "rs20": 0.08,
                "limit_up_amt_ratio": 0.8,
                "next_ret_after_limit_up": -0.02,
                "ret5": 0.02,
            },
        ]
    )

    signals = strategy.generate_signals_from_frame(signal_frame)

    assert len(signals) == 1
    assert signals.iloc[0]["ts_code"] == "600001.SH"
