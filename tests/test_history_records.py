# -*- coding: utf-8 -*-
"""Regression tests for history record organization helpers."""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.core.logger import get_logger
from src.modules.backtest.history_records_organizer import HistoryRecordsOrganizer

logger = get_logger("test_history_records")


def _build_mock_records() -> list[dict]:
    return [
        {
            "symbol": "000001",
            "name": "平安银行",
            "selection_date": "2023-01-15",
            "selection_reason": "回踩均线买入",
            "selection_score": 85,
            "strategy_type": "Pullback",
            "buy_date": "2023-01-15",
            "buy_price": 10.50,
            "buy_signal": "回踩均线买入",
            "sell_date": "2023-01-20",
            "sell_price": 11.20,
            "sell_signal": "止盈",
            "profit_pct": 6.67,
            "hold_days": 5,
        },
        {
            "symbol": "000002",
            "name": "万科A",
            "selection_date": "2023-01-18",
            "selection_reason": "突破买入",
            "selection_score": 78,
            "strategy_type": "Momentum",
            "buy_date": "2023-01-18",
            "buy_price": 15.30,
            "buy_signal": "突破买入",
            "sell_date": "2023-01-25",
            "sell_price": 16.50,
            "sell_signal": "移动止盈",
            "profit_pct": 7.84,
            "hold_days": 7,
        },
        {
            "symbol": "600000",
            "name": "浦发银行",
            "selection_date": "2023-01-20",
            "selection_reason": "量价齐升",
            "selection_score": 72,
            "strategy_type": "Momentum",
            "buy_date": "2023-01-20",
            "buy_price": 8.50,
            "buy_signal": "量价齐升",
            "sell_date": "2023-01-22",
            "sell_price": 8.10,
            "sell_signal": "止损",
            "profit_pct": -4.71,
            "hold_days": 2,
        },
    ]


@pytest.fixture
def records() -> list[dict]:
    return _build_mock_records()


def test_with_mock_data(records: list[dict]):
    """使用模拟数据测试缓存保存/加载链路。"""
    organizer = HistoryRecordsOrganizer()

    filepath = organizer.save_to_cache(records, "test_observation_records.json")
    loaded_records = organizer.load_from_cache("test_observation_records.json")

    assert os.path.exists(filepath)
    assert len(loaded_records) == len(records)
    assert loaded_records[0]["symbol"] == records[0]["symbol"]

    organizer.print_statistics(loaded_records)


def test_database_extraction():
    """测试数据库提取；没有数据库或没有记录时按正常跳过处理。"""
    organizer = HistoryRecordsOrganizer()

    if not os.path.exists(organizer.db_path):
        pytest.skip(f"database not found: {organizer.db_path}")

    observation_records = organizer.extract_from_database()
    if not observation_records:
        pytest.skip("no history records extracted from database")

    enriched_records = organizer.supplement_sell_info(observation_records)
    filepath = organizer.save_to_cache(enriched_records)

    assert os.path.exists(filepath)
    assert isinstance(enriched_records, list)

    organizer.print_statistics(enriched_records)


def test_data_analysis(records: list[dict]):
    """测试基础分组统计逻辑。"""
    strategy_groups: dict[str, list[dict]] = {}
    for record in records:
        strategy = record.get("strategy_type", "unknown")
        strategy_groups.setdefault(strategy, []).append(record)

    assert "Pullback" in strategy_groups
    assert "Momentum" in strategy_groups
    assert len(strategy_groups["Momentum"]) == 2

    profits = [r.get("profit_pct", 0) for r in strategy_groups["Momentum"] if r.get("profit_pct") is not None]
    avg_profit = sum(profits) / len(profits)
    win_rate = sum(1 for value in profits if value > 0) / len(profits)

    assert round(avg_profit, 2) == 1.56
    assert win_rate == 0.5
