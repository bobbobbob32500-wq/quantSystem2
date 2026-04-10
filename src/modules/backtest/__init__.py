# -*- coding: utf-8 -*-
"""
回测系统

基于事件驱动的回测引擎，支持：
- 分时数据驱动
- 多信号触发
- A股特有规则（T+1、涨跌停）
- 多股票并行
- 完整绩效评估
"""

from .engine import BacktestEngine
from .data_handler import DataHandler
from .signal_engine import SignalEngine
from .execution_engine import ExecutionEngine
from .portfolio import Portfolio
from .position import Position
from .metrics import compute_metrics
from .config import BacktestConfig as CoreBacktestConfig
from .history_recommendation_db import HistoryRecommendationDB
from .event_backtest_engine import (
    EventDrivenBacktest,
    BacktestConfig as EventBacktestConfig,
    Trade,
    Position as EventPosition,
)
from .improved_backtest_engine import (
    ImprovedBacktestEngine,
    BacktestConfig as ImprovedBacktestConfig,
    Trade as ImprovedTrade,
    Position as ImprovedPosition,
    StockState,
    StockStateInfo,
    Signal
)
from .strategy_backtest_engine import (
    StrategyBacktestEngine,
    BacktestConfig as StrategyBacktestConfig,
    Trade as StrategyTrade,
    Position as StrategyPosition,
    StockState as StrategyStockState,
    StockStateInfo as StrategyStockStateInfo,
    Signal as StrategySignal
)
from .data_validator import (
    StockCodeValidator,
    DataValidator,
    ValidationStatus,
    StockValidationResult,
    DataValidationReport
)
from .backtest_data_manager import BacktestDataManager, DataCache
from .performance_analyzer import PerformanceAnalyzer, PerformanceMetrics
from .visualizer import BacktestVisualizer
from .trade_visualizer import TradeVisualizer, TradePoint, generate_multi_stock_report
from .batch_intraday_downloader import BatchIntradayDownloader

__all__ = [
    'BacktestEngine',
    'DataHandler',
    'SignalEngine',
    'ExecutionEngine',
    'Portfolio',
    'Position',
    'compute_metrics',
    'CoreBacktestConfig',
    'HistoryRecommendationDB',
    'EventDrivenBacktest',
    'BacktestConfig',
    'EventBacktestConfig',
    'Trade',
    'EventPosition',
    'ImprovedBacktestEngine',
    'ImprovedBacktestConfig',
    'ImprovedTrade',
    'ImprovedPosition',
    'StockState',
    'StockStateInfo',
    'Signal',
    'StrategyBacktestEngine',
    'StrategyBacktestConfig',
    'StrategyTrade',
    'StrategyPosition',
    'StrategyStockState',
    'StrategyStockStateInfo',
    'StrategySignal',
    'StockCodeValidator',
    'DataValidator',
    'DataCache',
    'ValidationStatus',
    'StockValidationResult',
    'DataValidationReport',
    'BacktestDataManager',
    'PerformanceAnalyzer',
    'PerformanceMetrics',
    'BacktestVisualizer',
    'TradeVisualizer',
    'TradePoint',
    'generate_multi_stock_report',
    'BatchIntradayDownloader',
]

# Keep the package-level BacktestConfig aligned with the core event-loop backtest
# pipeline used by BacktestEngine/ExecutionEngine and the main test suite.
BacktestConfig = CoreBacktestConfig
