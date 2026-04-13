# -*- coding: utf-8 -*-
"""
业务模块
"""

from src.modules.data_updater import DataUpdater
from src.modules.position_controller import PositionController
from src.modules.stock_selector import StockSelector
from src.modules.hold_analyzer import HoldAnalyzer
from src.modules.risk_controller import RiskController, risk_signal_trigger
from src.modules.message_pusher import MessagePusher, WeChatWorkPusher
from src.modules.task_scheduler import TaskScheduler, QuantTaskManager
from src.modules.daily_report import DailyReportGenerator
from src.modules.trade_plan import TradePlanGenerator
from src.modules.post_market import PostMarketWorker
from src.modules.trade_evaluator import TradeEvaluator
from src.modules.signal_feedback_evaluator import SignalFeedbackEvaluator
from src.modules.market_analyzer import MarketAnalyzer
from src.modules.mainboard_secondary_launch_strategy import (
    MainboardSecondaryLaunchStrategy,
    StrategyParams,
)
from src.modules.mainboard_secondary_launch_backtester import (
    MainboardSecondaryLaunchBacktester,
    CostConfig,
)
from src.modules.secondary_launch_menu import SecondaryLaunchMenu

try:
    from src.modules.backtest_menu import BacktestMenu
except ImportError:
    BacktestMenu = None

__all__ = [
    "DataUpdater",
    "MarketAnalyzer",
    "StockSelector",
    "HoldAnalyzer",
    "RiskController",
    "risk_signal_trigger",
    "MessagePusher",
    "WeChatWorkPusher",
    "TaskScheduler",
    "QuantTaskManager",
    "DailyReportGenerator",
    "TradePlanGenerator",
    "PostMarketWorker",
    "TradeEvaluator",
    "SignalFeedbackEvaluator",
    "BacktestMenu",
    "MainboardSecondaryLaunchStrategy",
    "StrategyParams",
    "MainboardSecondaryLaunchBacktester",
    "CostConfig",
    "SecondaryLaunchMenu",
]

try:
    from src.modules.breakout_strategy import (
        BreakoutStrategy,
        BreakoutParams,
        get_breakout_params_for_backtest,
        build_breakout_strategy_from_config,
        build_wide_breakout_strategy_from_config,
        resolve_breakout_preset_from_config,
    )
    from src.modules.breakout_selector_menu import breakout_selector_menu, wide_breakout_selector_menu

    __all__.extend(
        [
            "BreakoutStrategy",
            "BreakoutParams",
            "get_breakout_params_for_backtest",
            "build_breakout_strategy_from_config",
            "build_wide_breakout_strategy_from_config",
            "resolve_breakout_preset_from_config",
            "breakout_selector_menu",
            "wide_breakout_selector_menu",
        ]
    )
except ImportError:
    BreakoutStrategy = None  # type: ignore[misc, assignment]
    BreakoutParams = None  # type: ignore[misc, assignment]
    breakout_selector_menu = None  # type: ignore[misc, assignment]

try:
    from src.modules.strong_start_strategy import StrongStartStrategy, StrongStartParams

    __all__.extend(["StrongStartStrategy", "StrongStartParams"])
except ImportError:
    StrongStartStrategy = None  # type: ignore[misc, assignment]
    StrongStartParams = None  # type: ignore[misc, assignment]
