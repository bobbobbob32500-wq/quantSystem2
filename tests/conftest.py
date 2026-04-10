# -*- coding: utf-8 -*-
"""
pytest 配置和共享 fixtures
"""

import pytest
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import sys
import os

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.core.config import ConfigManager
from src.core.database import DatabaseManager
from src.core.logger import get_logger

logger = get_logger("pytest")


# ============================================================================
# 配置和初始化
# ============================================================================

@pytest.fixture(scope="session")
def config():
    """配置管理器（会话级别）"""
    return ConfigManager()


@pytest.fixture(scope="session")
def db(config):
    """数据库管理器（会话级别，使用测试数据库）"""
    db_manager = DatabaseManager(config)
    # 可选：使用内存数据库进行测试
    # db_manager.db_path = ":memory:"
    return db_manager


# ============================================================================
# 样本数据 Fixtures
# ============================================================================

@pytest.fixture
def sample_stock_data():
    """样本股票数据"""
    dates = pd.date_range('2024-01-01', periods=100, freq='D')
    return pd.DataFrame({
        'ts_code': '000001.SZ',
        'trade_date': dates,
        'open': 10.0 + (dates.day % 10) * 0.1,
        'high': 10.5 + (dates.day % 10) * 0.1,
        'low': 9.5 + (dates.day % 10) * 0.1,
        'close': 10.2 + (dates.day % 10) * 0.1,
        'vol': 1000000 + (dates.day % 100) * 10000,
        'amount': 10000000 + (dates.day % 100) * 100000,
    })


@pytest.fixture
def sample_market_data():
    """样本市场数据"""
    dates = pd.date_range('2024-01-01', periods=100, freq='D')
    return pd.DataFrame({
        'trade_date': dates,
        'up_count': 1000 + (dates.day % 100),
        'down_count': 800 + (dates.day % 100),
        'limit_up_count': 10 + (dates.day % 5),
        'limit_down_count': 5 + (dates.day % 3),
    })


@pytest.fixture
def sample_factor_data():
    """样本因子数据"""
    dates = pd.date_range('2024-01-01', periods=100, freq='D')
    stocks = ['000001.SZ', '000002.SZ', '000858.SZ']
    
    data = []
    for stock in stocks:
        for date in dates:
            data.append({
                'symbol': stock,
                'date': date,
                'trend_score': np.random.uniform(0, 100),
                'momentum_score': np.random.uniform(0, 100),
                'volume_score': np.random.uniform(0, 100),
                'pullback_score': np.random.uniform(0, 100),
            })
    
    return pd.DataFrame(data)


# ============================================================================
# 辅助函数
# ============================================================================

@pytest.fixture
def temp_dir(tmp_path):
    """临时目录"""
    return tmp_path


@pytest.fixture
def cleanup_cache():
    """清理缓存"""
    from src.core.code_standards import _cache_manager
    _cache_manager.clear()
    yield
    _cache_manager.clear()


# ============================================================================
# 测试配置
# ============================================================================

def pytest_configure(config):
    """pytest 配置钩子"""
    config.addinivalue_line(
        "markers", "slow: 标记为慢速测试"
    )
    config.addinivalue_line(
        "markers", "integration: 标记为集成测试"
    )
    config.addinivalue_line(
        "markers", "unit: 标记为单元测试"
    )


# ============================================================================
# 测试收集钩子
# ============================================================================

def pytest_collection_modifyitems(config, items):
    """修改测试项"""
    for item in items:
        # 自动标记测试
        if "integration" in item.nodeid:
            item.add_marker(pytest.mark.integration)
        elif "unit" in item.nodeid:
            item.add_marker(pytest.mark.unit)
