# -*- coding: utf-8 -*-
"""
历史推荐股票数据库测试，使用项目真实推荐记录与真实分时数据作为样本。
"""

import sys
import os
from pathlib import Path

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.modules.backtest.history_recommendation_db import HistoryRecommendationDB
from tests.real_data_helpers import get_intraday_sample, get_real_recommendations


@pytest.fixture
def history_test_db(tmp_path):
    """创建隔离的测试数据库。"""
    db_path = tmp_path / "history_recommendation_test.db"
    return HistoryRecommendationDB(str(db_path))


def test_database_creation(history_test_db):
    """测试数据库创建。"""
    assert Path(history_test_db.db_path).exists()


def test_add_recommendations(history_test_db):
    """测试添加真实推荐记录样本。"""
    recommendations = get_real_recommendations(limit=2)
    assert recommendations, "真实推荐记录为空"

    for rec in recommendations:
        assert history_test_db.add_recommendation(rec) is True

    saved = history_test_db.get_recommendations()
    assert len(saved) >= len(recommendations)


def test_add_intraday_data(history_test_db):
    """测试添加真实分时数据样本。"""
    symbol, intraday_df = get_intraday_sample(min_rows=180)
    sample_df = intraday_df.head(180).copy()

    assert history_test_db.add_intraday_data(symbol, sample_df) is True

    stored = history_test_db.get_intraday_data(symbol)
    assert not stored.empty
    assert len(stored) == len(sample_df)


def test_query_data(history_test_db):
    """测试查询数据。"""
    recommendations = get_real_recommendations(limit=1)
    symbol, intraday_df = get_intraday_sample(min_rows=120)
    sample_df = intraday_df.head(120).copy()

    assert history_test_db.add_recommendation(recommendations[0]) is True
    assert history_test_db.add_intraday_data(symbol, sample_df) is True

    queried_recommendations = history_test_db.get_recommendations()
    queried_intraday = history_test_db.get_intraday_data(symbol)

    assert queried_recommendations
    assert not queried_intraday.empty
    assert queried_intraday["trade_time"].is_monotonic_increasing


def test_statistics(history_test_db):
    """测试统计信息。"""
    recommendations = get_real_recommendations(limit=2)
    symbol, intraday_df = get_intraday_sample(min_rows=100)

    for rec in recommendations:
        assert history_test_db.add_recommendation(rec) is True
    assert history_test_db.add_intraday_data(symbol, intraday_df.head(100).copy()) is True

    stats = history_test_db.get_statistics()
    assert stats.get("total_recommendations", 0) >= 2
    assert stats.get("total_intraday_records", 0) >= 100
