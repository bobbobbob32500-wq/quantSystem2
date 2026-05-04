"""
完善的融合选股系统
基于事件驱动的买点信号，而非简单评分
集成完全自动优化系统
集成虚拟交易跟踪
集成增强自动优化器（混合数据源）
"""

import pandas as pd
import numpy as np
from typing import Any, List, Dict, Optional, Tuple
from datetime import datetime, time, timedelta
import logging
import json
import os

from src.core.config import ConfigManager
from src.core.database import DatabaseManager
from src.modules.stock_selector import StockSelector
from src.modules.realtime_quote_fetcher import RealtimeQuoteFetcher
from src.modules.realtime_minute_fetcher import RealtimeMinuteFetcher
from src.modules.optimized_buy_signals import OptimizedBuySignals, IntradayData, SignalOutput
from src.modules.message_pusher import MessagePusher
from src.modules.position_controller import PositionController
from src.modules.feedback_guard import FeedbackPerformanceGuard
from src.modules.enhanced_monitor_runtime import (
    detect_confirmation_signal as runtime_detect_confirmation_signal,
    detect_signals as runtime_detect_signals,
    get_intraday_data_for_signal as runtime_get_intraday_data_for_signal,
    monitor_candidates as runtime_monitor_candidates,
    resolve_strategy_routed_signal as runtime_resolve_strategy_routed_signal,
    run_intraday_buy_router_healthcheck as runtime_run_intraday_buy_router_healthcheck,
    show_buy_signals as runtime_show_buy_signals,
)
from src.modules.enhanced_optimization_bridge import (
    collect_virtual_closed_trade_samples as bridge_collect_virtual_closed_trade_samples,
    evaluate_strategy as bridge_evaluate_strategy,
    handle_virtual_trade_closed as bridge_handle_virtual_trade_closed,
)
from src.modules.enhanced_trade_control import (
    build_position_advice as runtime_build_position_advice,
    compose_trade_control_context as runtime_compose_trade_control_context,
    compute_intraday_market_snapshot as runtime_compute_intraday_market_snapshot,
    evaluate_circuit_breaker as runtime_evaluate_circuit_breaker,
    fetch_index_pct_change_map as runtime_fetch_index_pct_change_map,
    get_feedback_guard_context as runtime_get_feedback_guard_context,
    get_market_gate_context as runtime_get_market_gate_context,
    maybe_emit_trade_control_alert as runtime_maybe_emit_trade_control_alert,
    record_monitor_incident as runtime_record_monitor_incident,
    report_trade_control_status as runtime_report_trade_control_status,
)
from src.modules.enhanced_industry_runtime import (
    build_candidate_minute_industry_context as runtime_build_candidate_minute_industry_context,
    build_intraday_industry_context as runtime_build_intraday_industry_context,
    fetch_realtime_industry_context_from_source as runtime_fetch_realtime_industry_context_from_source,
    industry_level_by_score as runtime_industry_level_by_score,
    match_industry_context as runtime_match_industry_context,
    resolve_candidate_industry_confirm as runtime_resolve_candidate_industry_confirm,
)
from src.modules.enhanced_sell_runtime import (
    build_sell_signals_from_closed_trades as runtime_build_sell_signals_from_closed_trades,
    map_sell_reason as runtime_map_sell_reason,
    show_virtual_trades_closed as runtime_show_virtual_trades_closed,
)
from src.modules.enhanced_signal_scoring import (
    calculate_total_signal_score as runtime_calculate_total_signal_score,
    get_dynamic_signal_thresholds as runtime_get_dynamic_signal_thresholds,
)
from src.modules.enhanced_signal_building import (
    build_buy_signal as runtime_build_buy_signal,
)
from src.modules.enhanced_realtime_context import (
    build_intraday_from_minute as runtime_build_intraday_from_minute,
    fetch_realtime_context as runtime_fetch_realtime_context,
    resolve_quote_row as runtime_resolve_quote_row,
)
from src.modules.enhanced_legacy_entry_runtime import (
    detect_legacy_gap_signal as runtime_detect_legacy_gap_signal,
    signal_monitor_window_open as runtime_signal_monitor_window_open,
)
from src.modules.enhanced_signal_utils import (
    build_false_signal as runtime_build_false_signal,
    calc_intraday_vwap as runtime_calc_intraday_vwap,
    calc_open_pct as runtime_calc_open_pct,
    is_time_in_window as runtime_is_time_in_window,
    resolve_signal_debounce_window as runtime_resolve_signal_debounce_window,
    wrap_signal_metadata as runtime_wrap_signal_metadata,
)
from src.modules.enhanced_monitor_orchestration import (
    monitor_loop as runtime_monitor_loop,
    push_buy_signals as runtime_push_buy_signals,
    show_monitor_info as runtime_show_monitor_info,
    show_non_trade_time as runtime_show_non_trade_time,
    update_latest_quotes as runtime_update_latest_quotes,
)
from src.modules.enhanced_monitor_lifecycle import (
    is_trade_time as runtime_is_trade_time,
    start_realtime_monitor as runtime_start_realtime_monitor,
    stop_realtime_monitor as runtime_stop_realtime_monitor,
)

# 导入自动优化系统
try:
    from src.modules.fully_automatic_system import FullyAutomaticOptimizationSystem
    AUTO_OPTIMIZATION_AVAILABLE = True
except ImportError as e:
    logging.warning(f"自动优化系统导入失败: {e}")
    AUTO_OPTIMIZATION_AVAILABLE = False

# 导入虚拟交易跟踪器
try:
    from src.modules.virtual_trade_tracker import VirtualTradeTracker
    VIRTUAL_TRADE_AVAILABLE = True
except ImportError as e:
    logging.warning(f"虚拟交易跟踪器导入失败: {e}")
    VIRTUAL_TRADE_AVAILABLE = False

# 导入增强自动优化器
try:
    from src.modules.enhanced_auto_optimizer import EnhancedAutoOptimizer
    from src.modules.complete_auto_optimizer import ParameterOptimizer, EffectValidator
    ENHANCED_OPTIMIZATION_AVAILABLE = True
except ImportError as e:
    logging.warning(f"增强优化器导入失败: {e}")
    ENHANCED_OPTIMIZATION_AVAILABLE = False

# 导入涨停过滤器
try:
    from src.modules.limit_filter import LimitFilter
    LIMIT_FILTER_AVAILABLE = True
except ImportError as e:
    logging.warning(f"涨停过滤器导入失败: {e}")
    LIMIT_FILTER_AVAILABLE = False

logger = logging.getLogger(__name__)



# 拆分出的子模块
from src.modules.enhanced_candidate_manager import CandidateManager
from src.modules.enhanced_market_context import MarketContext
from src.modules.enhanced_signal_builder import SignalBuilder

class EnhancedHybridSystem:
    """完善的融合选股系统（集成自动优化 + 虚拟交易跟踪）"""
    
    def __init__(self, enable_auto_optimization: bool = True,
                 enable_virtual_trade: bool = True,
                 runtime_monitor=None):
        self.overnight_selector = StockSelector()
        self.quote_fetcher = RealtimeQuoteFetcher()
        self.signal_detector = OptimizedBuySignals()
        self.system_config = ConfigManager()
        self.db = DatabaseManager(self.system_config)
        self.runtime_monitor = runtime_monitor
        self.position_controller = PositionController(self.system_config)
        self.minute_fetcher = RealtimeMinuteFetcher(
            cache_ttl_seconds=self.system_config.get("data_source.minute_cache_ttl_seconds", 8),
            request_pause_seconds=self.system_config.get("data_source.minute_request_pause_seconds", 0.05),
            max_workers=self.system_config.get("data_source.minute_fetch_workers", 3),
            min_valid_rows=self.system_config.get("data_source.minute_min_bars", 20),
            enable_akshare_minute=self.system_config.get("data_source.enable_akshare_minute_fetch", True),
            runtime_guard_py314_with_mini_racer=self.system_config.get(
                "data_source.disable_akshare_minute_on_py314", True
            ),
        )
        # 实盘级：分钟批量拉取整体超时预算，超时则返回部分结果并让下游降级
        self.minute_batch_timeout_seconds = float(
            self.system_config.get("data_source.minute_batch_timeout_seconds", 2.8)
        )
        self.minute_signal_min_bars = int(
            self.system_config.get("data_source.minute_min_bars", 20)
        )
        self.minute_max_symbols_per_round = int(
            self.system_config.get("data_source.minute_max_symbols_per_round", 12)
        )
        self.allow_quote_fallback_when_minute_missing = bool(
            self.system_config.get("monitor.allow_quote_fallback_when_minute_missing", True)
        )
        # symbol -> minute / quote_fallback / unavailable
        self._last_intraday_source: Dict[str, str] = {}
        self.enable_intraday_industry_confirmation = bool(
            self.system_config.get("monitor.intraday_industry_confirm_enabled", True)
        )
        self.intraday_industry_min_symbols = int(
            self.system_config.get("monitor.intraday_industry_min_symbols", 2)
        )
        self.intraday_industry_lookback_bars = int(
            self.system_config.get("monitor.intraday_industry_lookback_bars", 15)
        )
        self.intraday_industry_strong_threshold = float(
            self.system_config.get("monitor.intraday_industry_strong_threshold", 65.0)
        )
        self.intraday_industry_weak_threshold = float(
            self.system_config.get("monitor.intraday_industry_weak_threshold", 40.0)
        )
        self.intraday_industry_cache_seconds = int(
            self.system_config.get("monitor.intraday_industry_cache_seconds", 30)
        )
        self.market_gate_enabled = bool(
            self.system_config.get("monitor.market_gate_enabled", True)
        )
        self.market_gate_refresh_seconds = int(
            self.system_config.get("monitor.market_gate_refresh_seconds", 120)
        )
        self.market_gate_open_min_target_position = float(
            self.system_config.get("monitor.market_gate_open_min_target_position", 0.30)
        )
        self.market_gate_force_defensive_regimes = {
            str(item).upper()
            for item in self.system_config.get(
                "monitor.market_gate_force_defensive_regimes",
                ["WEAK_BEAR", "BEAR", "STRONG_BEAR"],
            )
        }
        self.market_gate_defensive_score_boost = float(
            self.system_config.get("monitor.market_gate_defensive_score_boost", 4.0)
        )
        self.market_gate_defensive_push_boost = float(
            self.system_config.get("monitor.market_gate_defensive_push_boost", 4.0)
        )
        self.market_gate_defensive_position_multiplier = float(
            self.system_config.get("monitor.market_gate_defensive_position_multiplier", 0.60)
        )
        self.market_gate_normal_max_signals_per_round = int(
            self.system_config.get("monitor.market_gate_normal_max_signals_per_round", 4)
        )
        self.market_gate_defensive_max_signals_per_round = int(
            self.system_config.get("monitor.market_gate_defensive_max_signals_per_round", 2)
        )

        self.intraday_circuit_breaker_enabled = bool(
            self.system_config.get("monitor.intraday_circuit_breaker_enabled", True)
        )
        self.circuit_index_codes = list(
            self.system_config.get(
                "monitor.circuit_index_codes",
                ["000001.SH", "399001.SZ", "399006.SZ"],
            )
        )
        self.circuit_soft_trigger_drop_pct = float(
            self.system_config.get("monitor.circuit_soft_trigger_drop_pct", -1.2)
        )
        self.circuit_hard_trigger_drop_pct = float(
            self.system_config.get("monitor.circuit_hard_trigger_drop_pct", -2.0)
        )
        self.circuit_soft_breadth_threshold = float(
            self.system_config.get("monitor.circuit_soft_breadth_threshold", 0.35)
        )
        self.circuit_hard_breadth_threshold = float(
            self.system_config.get("monitor.circuit_hard_breadth_threshold", 0.25)
        )
        self.circuit_hold_seconds = int(
            self.system_config.get("monitor.circuit_hold_minutes", 20)
        ) * 60
        self.circuit_recover_drop_pct = float(
            self.system_config.get("monitor.circuit_recover_drop_pct", -0.8)
        )
        self.circuit_recover_breadth_threshold = float(
            self.system_config.get("monitor.circuit_recover_breadth_threshold", 0.45)
        )
        self.circuit_soft_score_boost = float(
            self.system_config.get("monitor.circuit_soft_score_boost", 3.0)
        )
        self.circuit_soft_push_boost = float(
            self.system_config.get("monitor.circuit_soft_push_boost", 2.0)
        )
        self.circuit_soft_position_multiplier = float(
            self.system_config.get("monitor.circuit_soft_position_multiplier", 0.5)
        )

        self.position_linkage_enabled = bool(
            self.system_config.get("monitor.position_linkage_enabled", True)
        )
        self.position_linkage_per_signal_cap = float(
            self.system_config.get("monitor.position_linkage_per_signal_cap", 0.12)
        )
        self.position_linkage_min_ratio = float(
            self.system_config.get("monitor.position_linkage_min_ratio", 0.02)
        )
        self.feedback_adaptive_cache_seconds = float(
            self.system_config.get("monitor.feedback_adaptive_cache_seconds", 300)
        )
        self._feedback_adaptive_cache = {"ts": 0.0, "profiles": {}}
        self.trade_control_alert_cooldown_seconds = int(
            self.system_config.get("monitor.trade_control_alert_cooldown_seconds", 300)
        )
        self.trade_control_status_print_interval_seconds = int(
            self.system_config.get("monitor.trade_control_status_print_interval_seconds", 60)
        )
        self.feedback_guard_enabled = bool(
            self.system_config.get("monitor.feedback_guard_enabled", True)
        )
        self.feedback_guard_position_multiplier_caution = float(
            self.system_config.get("monitor.feedback_guard_position_multiplier_caution", 0.85)
        )
        self.feedback_guard_position_multiplier_defensive = float(
            self.system_config.get("monitor.feedback_guard_position_multiplier_defensive", 0.65)
        )
        self.feedback_guard_threshold_boost_caution = float(
            self.system_config.get("monitor.feedback_guard_threshold_boost_caution", 1.5)
        )
        self.feedback_guard_threshold_boost_defensive = float(
            self.system_config.get("monitor.feedback_guard_threshold_boost_defensive", 3.0)
        )
        self.feedback_guard_push_boost_caution = float(
            self.system_config.get("monitor.feedback_guard_push_boost_caution", 1.0)
        )
        self.feedback_guard_push_boost_defensive = float(
            self.system_config.get("monitor.feedback_guard_push_boost_defensive", 2.0)
        )
        self.feedback_guard_max_signals_caution = int(
            self.system_config.get("monitor.feedback_guard_max_signals_caution", 3)
        )
        self.feedback_guard_max_signals_defensive = int(
            self.system_config.get("monitor.feedback_guard_max_signals_defensive", 2)
        )
        self.feedback_guard_refresh_seconds = int(
            self.system_config.get("monitor.feedback_guard_refresh_seconds", 300)
        )
        self.feedback_guard = FeedbackPerformanceGuard(self.system_config, self.db)
        self.legacy_gap_entry_enabled = bool(
            self.system_config.get("monitor.legacy_gap_entry_enabled", True)
        )
        self.legacy_gap_entry_start_time = self._parse_time_value(
            self.system_config.get("monitor.legacy_gap_entry_start_time", "09:35"),
            default=time(9, 35),
        )
        self.legacy_gap_entry_end_time = self._parse_time_value(
            self.system_config.get("monitor.legacy_gap_entry_end_time", "10:15"),
            default=time(10, 15),
        )
        self.legacy_low_open_entry_end_time = self._parse_time_value(
            self.system_config.get("monitor.legacy_low_open_entry_end_time", "10:30"),
            default=time(10, 30),
        )
        self.legacy_gap_mid_lower_pct = float(
            self.system_config.get("monitor.legacy_gap_mid_lower_pct", 1.0)
        )
        self.legacy_gap_mid_upper_pct = float(
            self.system_config.get("monitor.legacy_gap_mid_upper_pct", 4.0)
        )
        self.legacy_gap_flat_skip_lower_pct = float(
            self.system_config.get("monitor.legacy_gap_flat_skip_lower_pct", -2.0)
        )
        self.legacy_gap_flat_skip_upper_pct = float(
            self.system_config.get("monitor.legacy_gap_flat_skip_upper_pct", 1.0)
        )
        self.legacy_low_open_reclaim_pct = float(
            self.system_config.get("monitor.legacy_low_open_reclaim_pct", 0.3)
        )
        self.legacy_low_open_min_wait_time = self._parse_time_value(
            self.system_config.get("monitor.legacy_low_open_min_wait_time", "09:45"),
            default=time(9, 45),
        )
        self.legacy_low_open_min_low_age_bars = int(
            self.system_config.get("monitor.legacy_low_open_min_low_age_bars", 2)
        )
        self.legacy_low_open_rebound_from_low_pct = float(
            self.system_config.get("monitor.legacy_low_open_rebound_from_low_pct", 0.5)
        )
        self.legacy_low_open_max_chase_from_low_pct = float(
            self.system_config.get("monitor.legacy_low_open_max_chase_from_low_pct", 2.0)
        )
        self.legacy_low_open_recent_trend_bars = int(
            self.system_config.get("monitor.legacy_low_open_recent_trend_bars", 3)
        )
        self.legacy_open_support_tolerance_pct = float(
            self.system_config.get("monitor.legacy_open_support_tolerance_pct", 0.8)
        )
        self.legacy_vwap_support_tolerance_pct = float(
            self.system_config.get("monitor.legacy_vwap_support_tolerance_pct", 0.2)
        )
        self.legacy_route_exit_override_enabled = bool(
            self.system_config.get("monitor.legacy_route_exit_override_enabled", True)
        )
        legacy_route_exit_overrides = self.system_config.get(
            "monitor.legacy_route_exit_overrides",
            {},
        )
        self.legacy_route_exit_overrides = (
            legacy_route_exit_overrides
            if isinstance(legacy_route_exit_overrides, dict)
            else {}
        )

        # 候选池
        self.candidate_pool = []
        self.candidate_date = None
        self.latest_industry_context = {
            "enabled": self.enable_intraday_industry_confirmation,
            "industry_map": {},
            "top_industries": [],
            "bottom_industries": [],
        }
        self._industry_realtime_cache = {
            "ts": None,
            "context": None,
        }
        self._market_gate_cache = {"ts": None, "context": None}
        self._feedback_guard_cache = {"ts": None, "state": None}
        self._circuit_breaker_state = {
            "state": "normal",
            "since": None,
            "last_change": None,
            "reason": "",
        }
        self._last_trade_control_snapshot = None
        self._last_trade_control_alert_at = None
        self._last_trade_control_status_print_at = None
        self.latest_trade_control_context = {}
        self._trade_day_cache = {}
        self._last_non_trade_day_log_key = None
        
        # 信号历史（用于防抖）
        self.signal_history = {}
        
        default_debounce_window = max(
            1,
            int(self.system_config.get("monitor.debounce_window", 2)),
        )
        # 配置
        self.config = {
            # 候选池配置
            'core_pool_size': 10,      # 核心池大小
            'reserve_pool_size': 5,    # 备选池大小
            
            # 信号配置
            'min_signal_score': 0.6,   # 最低信号评分
            'debounce_window': default_debounce_window,      # 防抖窗口
            'debounce_window_breakout': max(
                1,
                int(self.system_config.get("monitor.debounce_window_breakout", 1)),
            ),
            'debounce_window_wide_breakout': max(
                1,
                int(self.system_config.get("monitor.debounce_window_wide_breakout", 1)),
            ),
            'debounce_window_secondary_launch': max(
                1,
                int(self.system_config.get("monitor.debounce_window_secondary_launch", default_debounce_window)),
            ),
            
            # 时间配置
            'monitor_start': time(9, 45),
            'monitor_end': time(14, 30),
            
            # 风控配置
            'stop_loss_pct': -0.05,    # 止损
            'take_profit_pct': 0.10,   # 止盈
            'max_hold_days': 10,       # 最大持仓
        }
        
        # 缓存目录
        self.cache_dir = 'data/cache'
        os.makedirs(self.cache_dir, exist_ok=True)
        
        # 实时监控状态
        self.is_monitoring = False
        self.monitor_thread = None
        self.latest_quotes = {}  # 最新行情数据
        
        # 消息推送
        self.message_pusher = MessagePusher()
        self.push_enabled = True  # 是否推送买点信号
        
        # 推送控制（避免频繁推送）
        self.pushed_signals = {}  # 已推送的信号 {symbol: {signal_type, push_time}}
        self.push_cooldown = 300  # 推送冷却时间（秒），同一股票同一信号5分钟内不重复推送
        self.min_signal_score_for_push = 75  # 最低推送评分，低于此分数不推送

        # 优化结果落参控制
        self.optimization_runtime_enabled = bool(
            self.system_config.get("monitor.optimization_runtime_enabled", True)
        )
        self.optimization_profile_refresh_seconds = int(
            self.system_config.get("monitor.optimization_profile_refresh_seconds", 60)
        )
        self.optimization_deploy_min_score_delta = float(
            self.system_config.get("monitor.optimization_deploy_min_score_delta", 0.001)
        )
        self.optimization_deploy_min_trade_count = int(
            self.system_config.get("monitor.optimization_deploy_min_trade_count", 30)
        )
        self.optimization_max_profile_age_hours = float(
            self.system_config.get("monitor.optimization_max_profile_age_hours", 168.0)
        )
        self.optimization_apply_to_thresholds = bool(
            self.system_config.get("monitor.optimization_apply_to_thresholds", True)
        )
        self.optimization_apply_to_exit_params = bool(
            self.system_config.get("monitor.optimization_apply_to_exit_params", True)
        )
        self.optimization_min_total_score_floor = float(
            self.system_config.get("monitor.optimization_min_total_score_floor", 68.0)
        )
        self.optimization_max_total_score_floor = float(
            self.system_config.get("monitor.optimization_max_total_score_floor", 88.0)
        )
        self.optimization_intraday_margin = float(
            self.system_config.get("monitor.optimization_intraday_margin", 14.0)
        )
        self.optimization_push_floor_offset = float(
            self.system_config.get("monitor.optimization_push_floor_offset", 4.0)
        )
        self.optimization_tp1_ratio = float(
            self.system_config.get("monitor.optimization_tp1_ratio", 0.65)
        )
        self.optimization_trailing_stop_default = float(
            self.system_config.get("monitor.optimization_trailing_stop_default", 0.035)
        )
        self.optimization_max_hold_hours = self._parse_optional_float(
            self.system_config.get("monitor.optimization_max_hold_hours", None)
        )
        self.optimization_auto_start = bool(
            self.system_config.get("monitor.optimization_auto_start", True)
        )
        self.optimization_bootstrap_enabled = bool(
            self.system_config.get("monitor.optimization_bootstrap_enabled", True)
        )
        self.optimization_bootstrap_lookback_days = int(
            self.system_config.get("monitor.optimization_bootstrap_lookback_days", 180)
        )
        self.optimization_bootstrap_max_samples = int(
            self.system_config.get("monitor.optimization_bootstrap_max_samples", 2000)
        )
        self._optimization_runtime_cache = {"ts": None, "profile": None}
        self._optimization_bootstrap_done = False
        
        # ========== 新增：自动优化系统 ==========
        self.enable_auto_optimization = enable_auto_optimization and AUTO_OPTIMIZATION_AVAILABLE
        self.auto_optimizer = None
        self.trade_results = []  # 交易结果记录
        
        if self.enable_auto_optimization:
            self._init_auto_optimization()
        
        # ========== 新增：虚拟交易跟踪器 ==========
        self.enable_virtual_trade = enable_virtual_trade and VIRTUAL_TRADE_AVAILABLE
        self.virtual_tracker = None
        
        if self.enable_virtual_trade:
            self._init_virtual_trade_tracker()
        
        # ========== 新增：增强自动优化器 ==========
        self.enable_enhanced_optimization = ENHANCED_OPTIMIZATION_AVAILABLE
        self.enhanced_optimizer = None
        
        if self.enable_enhanced_optimization:
            self._init_enhanced_optimizer()
            if self.optimization_bootstrap_enabled:
                self._bootstrap_enhanced_optimizer_real_samples()
        
        # ========== 新增：涨停过滤器 ==========
        self.enable_limit_filter = LIMIT_FILTER_AVAILABLE
        self.limit_filter = None
        
        if self.enable_limit_filter:
            self.limit_filter = LimitFilter(
                limit_up_threshold=0.095,   # 9.5%视为涨停
                limit_down_threshold=-0.095,
                enable_filter=True
            )
        
                # 暴露给子模块的属性
        self.logger = logger
        self.config = self.system_config
        
        logger.info(f"系统初始化完成（自动优化:{self.enable_auto_optimization}, "
                   f"虚拟交易:{self.enable_virtual_trade}, "
                   f"增强优化:{self.enable_enhanced_optimization}, "
                   f"涨停过滤:{self.enable_limit_filter}）")
        

        # 初始化拆分出的子模块
        self.candidate_manager = CandidateManager(self)
        self.market_context = MarketContext(self)
        self.signal_builder = SignalBuilder(self)
    def _init_auto_optimization(self):
        """初始化自动优化系统"""
        try:
            self.auto_optimizer = FullyAutomaticOptimizationSystem(
                scheduled_interval_minutes=30,  # 每30分钟重优化
                consecutive_loss_threshold=3,   # 连续亏损3次触发
                drawdown_threshold=0.15         # 回撤15%触发
            )
            
            # 设置回调
            self.auto_optimizer.on_signal = self._on_auto_optimization_signal
            self.auto_optimizer.on_position_change = self._on_auto_optimization_position_change
            
            logger.info("自动优化系统初始化成功")
        except Exception as e:
            logger.error(f"自动优化系统初始化失败: {e}")
            self.enable_auto_optimization = False
            self.auto_optimizer = None
    
    def _init_virtual_trade_tracker(self):
        """初始化虚拟交易跟踪器"""
        try:
            partial_take_profit_pct = self.system_config.get(
                "monitor.virtual_partial_take_profit_pct",
                None,
            )
            if str(partial_take_profit_pct).strip().lower() in {"", "none", "null"}:
                partial_take_profit_pct = None
            elif partial_take_profit_pct is not None:
                partial_take_profit_pct = float(partial_take_profit_pct)
            max_hold_hours = self.system_config.get("monitor.virtual_max_hold_hours", None)
            if str(max_hold_hours).strip().lower() in {"", "none", "null"}:
                max_hold_hours = None
            elif max_hold_hours is not None:
                max_hold_hours = float(max_hold_hours)

            fallback_max_hold_hours = self.system_config.get(
                "monitor.virtual_fallback_max_hold_hours",
                96,
            )
            if str(fallback_max_hold_hours).strip().lower() in {"", "none", "null"}:
                fallback_max_hold_hours = None
            elif fallback_max_hold_hours is not None:
                fallback_max_hold_hours = float(fallback_max_hold_hours)

            self.virtual_tracker = VirtualTradeTracker(
                stop_loss_pct=float(
                    self.system_config.get("monitor.virtual_stop_loss_pct", -0.05)
                ),
                take_profit_pct=float(
                    self.system_config.get("monitor.virtual_take_profit_pct", 0.10)
                ),
                max_hold_hours=max_hold_hours,
                enable_auto_feedback=True,
                enable_dynamic_exit=bool(
                    self.system_config.get("monitor.virtual_dynamic_exit_enabled", True)
                ),
                fallback_max_hold_hours=fallback_max_hold_hours,
                partial_take_ratio=float(
                    self.system_config.get("monitor.virtual_partial_take_ratio", 0.5)
                ),
                partial_take_profit_pct=partial_take_profit_pct,
                trailing_stop_pct=float(
                    self.system_config.get("monitor.virtual_trailing_stop_pct", 0.035)
                ),
            )

            # 加载历史真实虚拟交易样本，避免冷启动
            try:
                self.virtual_tracker.load_state()
            except Exception as load_exc:
                logger.warning("加载虚拟交易历史失败，继续空状态启动: %s", load_exc)
            
            # 设置回调：虚拟交易平仓时自动反馈给优化系统
            self.virtual_tracker.on_trade_closed = self._on_virtual_trade_closed
            
            logger.info("虚拟交易跟踪器初始化成功")
        except Exception as e:
            logger.error(f"虚拟交易跟踪器初始化失败: {e}")
            self.enable_virtual_trade = False
            self.virtual_tracker = None
    
    def _on_virtual_trade_closed(self, trade):
        """虚拟交易平仓回调（增强版）"""
        return bridge_handle_virtual_trade_closed(self, trade)
    
    def _init_enhanced_optimizer(self):
        """初始化增强自动优化器"""
        try:
            # 定义参数空间（可配置）
            param_space = self.system_config.get(
                "monitor.optimization_param_space",
                {
                    'min_signal_score': [0.6, 0.7, 0.8],
                    'stop_loss_pct': [-0.03, -0.05, -0.07],
                    'take_profit_pct': [0.08, 0.10, 0.12],
                },
            )
            if not isinstance(param_space, dict):
                param_space = {
                    'min_signal_score': [0.6, 0.7, 0.8],
                    'stop_loss_pct': [-0.03, -0.05, -0.07],
                    'take_profit_pct': [0.08, 0.10, 0.12],
                }
            
            # 创建参数优化器
            param_optimizer = ParameterOptimizer(param_space)
            
            # 创建效果验证器
            effect_validator = EffectValidator(
                min_win_rate_improvement=float(
                    self.system_config.get("monitor.optimization_min_win_rate_improvement", 0.01)
                ),
                min_pnl_improvement=float(
                    self.system_config.get("monitor.optimization_min_pnl_improvement", 0.01)
                )
            )
            
            # 创建增强优化器
            self.enhanced_optimizer = EnhancedAutoOptimizer(
                param_optimizer=param_optimizer,
                effect_validator=effect_validator,
                evaluate_func=self._evaluate_strategy,
                optimize_interval=int(
                    self.system_config.get("monitor.optimization_interval", 50)
                ),
                min_trades_for_optimization=int(
                    self.system_config.get("monitor.optimization_min_trades", 20)
                ),
                use_backtest_data=True,
                backtest_weight=float(
                    self.system_config.get("monitor.optimization_backtest_weight", 0.3)
                ),
                min_robustness_score=float(
                    self.system_config.get("monitor.optimization_min_robustness_score", 0.55)
                ),
                min_deploy_score_delta=self.optimization_deploy_min_score_delta,
                min_deploy_trade_count=self.optimization_deploy_min_trade_count,
            )
            
            logger.info("增强自动优化器初始化成功")
            
        except Exception as e:
            logger.error(f"增强优化器初始化失败: {e}")
            self.enable_enhanced_optimization = False
            self.enhanced_optimizer = None
    
    def _evaluate_strategy(self, trades, params):
        """策略评价函数"""
        return bridge_evaluate_strategy(self, trades, params)

    @staticmethod
    def _parse_optional_float(value: Any) -> Optional[float]:
        if value is None:
            return None
        text = str(value).strip().lower()
        if text in {"", "none", "null"}:
            return None
        try:
            return float(value)
        except Exception:
            return None

    @staticmethod
    def _parse_datetime_value(value: Any) -> Optional[datetime]:
        if value is None:
            return None
        text = str(value).strip()
        if not text:
            return None
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y%m%d%H%M%S", "%Y-%m-%d", "%Y%m%d"):
            try:
                return datetime.strptime(text, fmt)
            except Exception:
                continue
        try:
            return datetime.fromisoformat(text)
        except Exception:
            return None

    @staticmethod
    def _parse_time_value(value: Any, default: time) -> time:
        if isinstance(value, time):
            return value
        text = str(value or "").strip()
        if not text:
            return default
        for fmt in ("%H:%M:%S", "%H:%M"):
            try:
                return datetime.strptime(text, fmt).time()
            except Exception:
                continue
        return default

    @staticmethod
    def _normalize_strategy_profile(profile: Any) -> str:
        text = str(profile or "").strip().lower()
        # 与候选池 strategy_profile、resolve_strategy_routed_signal 分支一致；未列出的回退 legacy
        known = {
            "legacy",
            "legacy_opt",
            "alpha158",
            "enhanced",
            "institutional_core",
            "daily_multi_strategy",
            "secondary_launch",
            "breakout",
            "wide_breakout",
            "strong_start",
        }
        if text in known:
            return text
        return "legacy"

    def _resolve_candidate_strategy_profile(self, candidate: Optional[Dict[str, Any]]) -> str:
        if isinstance(candidate, dict):
            profile = candidate.get("strategy_profile")
            if profile:
                return self._normalize_strategy_profile(profile)

        selector = getattr(self, "overnight_selector", None)
        selector_profile = getattr(selector, "strategy_profile", None)
        if selector_profile:
            return self._normalize_strategy_profile(selector_profile)

        config_obj = getattr(self, "system_config", None)
        if config_obj is not None and hasattr(config_obj, "get"):
            return self._normalize_strategy_profile(
                config_obj.get("stock_selection.strategy_profile", "legacy")
            )
        return "legacy"

    def _resolve_route_debounce_window(self, strategy_profile: str) -> int:
        profile = self._normalize_strategy_profile(strategy_profile)
        default_window = max(1, int(self.config.get("debounce_window", 2)))
        key_map = {
            "breakout": "debounce_window_breakout",
            "wide_breakout": "debounce_window_wide_breakout",
            "secondary_launch": "debounce_window_secondary_launch",
        }
        profile_key = key_map.get(profile)
        if not profile_key:
            return default_window
        return max(1, int(self._to_float(self.config.get(profile_key, default_window), default_window)))

    @staticmethod
    def _strategy_profile_label(profile: str) -> str:
        mapping = {
            "legacy": "原策略",
            "legacy_opt": "原策略优化版",
            "alpha158": "Alpha158 因子策略",
            "enhanced": "增强策略",
            "institutional_core": "机构核心策略",
            "daily_multi_strategy": "多策略协同",
            "secondary_launch": "二次启动策略",
            "breakout": "突破策略",
            "wide_breakout": "宽进突破策略",
            "strong_start": "强势股刚启动",
        }
        return mapping.get(str(profile or "").lower(), "原策略")

    def _default_buy_template_source(self, strategy_profile: str) -> str:
        profile = self._normalize_strategy_profile(strategy_profile)
        if profile == "alpha158":
            return "alpha158_confirmation_v1"
        if profile == "daily_multi_strategy":
            return "daily_multi_confirmation_v1"
        if profile == "institutional_core":
            return "institutional_core_confirmation_v1"
        if profile == "enhanced":
            return "enhanced_confirmation_v1"
        if profile == "secondary_launch":
            return "secondary_launch_confirmation_v1"
        return "legacy_gap_open_v1"

    def _default_buy_route_label(self, strategy_profile: str) -> str:
        profile = self._normalize_strategy_profile(strategy_profile)
        if profile == "alpha158":
            return "Alpha158 分时确认"
        if profile == "daily_multi_strategy":
            return "多策略协同确认"
        if profile == "institutional_core":
            return "机构核心确认"
        if profile == "enhanced":
            return "分时确认"
        if profile == "secondary_launch":
            return "二次启动分时确认"
        return "开盘形态路由"

    def _get_legacy_route_exit_override(
        self,
        strategy_profile: str,
        route_name: str,
    ) -> Dict[str, Any]:
        profile = self._normalize_strategy_profile(strategy_profile)
        if profile not in {"legacy", "legacy_opt"}:
            return {}
        if not bool(getattr(self, "legacy_route_exit_override_enabled", True)):
            return {}

        overrides = getattr(self, "legacy_route_exit_overrides", {})
        if not isinstance(overrides, dict):
            return {}

        route_key = str(route_name or "").strip()
        route_override = overrides.get(route_key, {})
        if not isinstance(route_override, dict):
            return {}

        result: Dict[str, Any] = {}
        stop_loss_pct = self._parse_optional_float(route_override.get("stop_loss_pct", None))
        tp1_pct = self._parse_optional_float(route_override.get("tp1_pct", None))
        take_profit_pct = self._parse_optional_float(route_override.get("take_profit_pct", None))
        trailing_stop_pct = self._parse_optional_float(route_override.get("trailing_stop_pct", None))
        max_hold_hours = self._parse_optional_float(route_override.get("max_hold_hours", None))

        if stop_loss_pct is not None:
            result["dynamic_stop_loss_pct"] = float(stop_loss_pct)
        if tp1_pct is not None:
            result["dynamic_tp1_pct"] = float(tp1_pct)
        if take_profit_pct is not None:
            result["dynamic_take_profit_pct"] = float(take_profit_pct)
        if trailing_stop_pct is not None:
            result["dynamic_trailing_stop_pct"] = float(trailing_stop_pct)
        if max_hold_hours is not None:
            result["max_hold_hours"] = float(max_hold_hours)
        if "carry_peak_arm_on_t1" in route_override:
            result["carry_peak_arm_on_t1"] = bool(route_override.get("carry_peak_arm_on_t1"))
        if "profile_label" in route_override:
            result["legacy_exit_profile_label"] = str(route_override.get("profile_label") or "").strip()
        return result

    @staticmethod
    def _is_time_in_window(current: time, start: time, end: time) -> bool:
        return runtime_is_time_in_window(current=current, start=start, end=end)

    @staticmethod
    def _calc_open_pct(open_price: float, pre_close: float) -> float:
        return runtime_calc_open_pct(open_price=open_price, pre_close=pre_close)

    @staticmethod
    def _calc_intraday_vwap(minute_df: Optional[pd.DataFrame], fallback_price: float) -> float:
        return runtime_calc_intraday_vwap(
            minute_df=minute_df,
            fallback_price=fallback_price,
        )



    def _collect_virtual_closed_trade_samples(self, limit: int = 500) -> List[Dict[str, Any]]:
        return bridge_collect_virtual_closed_trade_samples(self, limit=limit)

    def _collect_feedback_backtest_samples(
        self,
        lookback_days: int = 180,
        limit: int = 2000,
    ) -> List[Dict[str, Any]]:
        samples: List[Dict[str, Any]] = []
        latest_trade_date = str(self.db.get_latest_trade_date("stock_daily") or "")
        latest_dt = self._parse_datetime_value(latest_trade_date) or datetime.now()
        start_dt = latest_dt - timedelta(days=max(30, int(lookback_days)))
        start_date = start_dt.strftime("%Y%m%d")
        end_date = latest_dt.strftime("%Y%m%d")

        try:
            rows = self.db.query(
                """
                SELECT source_type, direction, horizon, ts_code, name, signal_type,
                       signal_date, entry_date, exit_date, entry_price, exit_price,
                       net_return, recommendation_score, extra_json
                FROM signal_feedback_detail
                WHERE direction = 'buy'
                  AND signal_date >= ?
                  AND signal_date <= ?
                ORDER BY signal_date DESC, id DESC
                LIMIT ?
                """,
                (start_date, end_date, int(max(100, limit * 2))),
            )
        except Exception as exc:
            logger.info("feedback detail samples unavailable: %s", exc)
            return samples

        for row in rows:
            entry_price = self._to_float(row.get("entry_price", 0.0))
            exit_price = self._to_float(row.get("exit_price", 0.0))
            net_return = self._to_float(row.get("net_return", 0.0))
            if entry_price <= 0 or exit_price <= 0:
                continue
            if abs(net_return) > 0.8:
                continue

            signal_date = str(row.get("signal_date", "") or "")
            entry_date = str(row.get("entry_date", signal_date) or signal_date)
            exit_date = str(row.get("exit_date", signal_date) or signal_date)
            buy_time = self._parse_datetime_value(entry_date) or self._parse_datetime_value(signal_date)
            sell_time = self._parse_datetime_value(exit_date) or buy_time
            if buy_time is None or sell_time is None:
                continue

            source_type = str(row.get("source_type", "") or "")
            horizon = int(self._to_float(row.get("horizon", 0), 0))
            recommendation_score = self._to_float(row.get("recommendation_score", 50.0), 50.0)
            factors = {
                "recommendation_score": max(0.0, min(1.0, recommendation_score / 100.0)),
                "horizon_norm": max(0.0, min(1.0, horizon / 5.0)),
                "source_pre_market": 1.0 if source_type == "pre_market_recommendation" else 0.0,
            }
            samples.append(
                {
                    "symbol": str(row.get("ts_code", "") or ""),
                    "name": str(row.get("name", "") or ""),
                    "buy_time": buy_time,
                    "buy_price": entry_price,
                    "sell_time": sell_time,
                    "sell_price": exit_price,
                    "pnl": net_return,
                    "pnl_pct": net_return,
                    "signal_type": str(row.get("signal_type", "") or f"{source_type}_h{horizon}"),
                    "signal_score": recommendation_score,
                    "factors": factors,
                    "market_env": {},
                    "data_source": "feedback_detail",
                }
            )
            if len(samples) >= max(1, int(limit)):
                break
        return samples

    def _load_real_training_samples(self) -> List[Dict[str, Any]]:
        max_samples = max(100, int(self.optimization_bootstrap_max_samples))
        samples: List[Dict[str, Any]] = []
        samples.extend(
            self._collect_virtual_closed_trade_samples(limit=min(600, max_samples))
        )
        remain = max_samples - len(samples)
        if remain > 0:
            samples.extend(
                self._collect_feedback_backtest_samples(
                    lookback_days=self.optimization_bootstrap_lookback_days,
                    limit=remain,
                )
            )

        dedup: Dict[Tuple[str, str, str], Dict[str, Any]] = {}
        for item in samples:
            symbol = str(item.get("symbol", "") or "")
            buy_time = self._parse_datetime_value(item.get("buy_time")) or datetime.now()
            signal_type = str(item.get("signal_type", "") or "")
            key = (symbol, buy_time.strftime("%Y%m%d"), signal_type)
            if key not in dedup:
                dedup[key] = item

        merged = list(dedup.values())
        merged.sort(
            key=lambda x: self._parse_datetime_value(x.get("buy_time")) or datetime.min,
            reverse=True,
        )
        return merged[:max_samples]

    def _bootstrap_enhanced_optimizer_real_samples(self, force: bool = False) -> Dict[str, Any]:
        if not self.enable_enhanced_optimization or not self.enhanced_optimizer:
            return {"status": "disabled", "samples": 0}
        if self._optimization_bootstrap_done and not force:
            return {"status": "already_done", "samples": len(self.enhanced_optimizer.backtest_trades)}

        samples = self._load_real_training_samples()
        if not samples:
            logger.warning("未找到可用于增强优化器的真实训练样本")
            return {"status": "empty", "samples": 0}

        self.enhanced_optimizer.add_backtest_data(samples)
        self._optimization_bootstrap_done = True
        self._optimization_runtime_cache = {"ts": None, "profile": None}

        optimization_result = self.enhanced_optimizer.run_optimization_once()
        logger.info(
            "增强优化样本已加载: %d 条, 首次优化=%s",
            len(samples),
            "done" if optimization_result else "skipped",
        )
        return {
            "status": "ok",
            "samples": len(samples),
            "optimization_result": optimization_result,
        }

    def _build_optimization_runtime_profile(self, now: Optional[datetime] = None) -> Dict[str, Any]:
        timestamp = now or datetime.now()
        default_profile = {
            "enabled": bool(self.optimization_runtime_enabled),
            "active": False,
            "reason": "disabled",
            "params": {},
            "factor_weights": {},
            "min_total_score_floor": float(self.optimization_min_total_score_floor),
            "min_intraday_score_floor": max(
                45.0,
                float(self.optimization_min_total_score_floor) - float(self.optimization_intraday_margin),
            ),
            "push_threshold_floor": max(
                70.0,
                float(self.optimization_min_total_score_floor) + float(self.optimization_push_floor_offset),
            ),
            "exit_params": {},
            "timestamp": timestamp.strftime("%Y-%m-%d %H:%M:%S"),
            "score_delta": 0.0,
            "robustness_score": 0.0,
            "trade_count": 0,
        }
        if not self.optimization_runtime_enabled:
            return default_profile
        if not self.enable_enhanced_optimization or not self.enhanced_optimizer:
            default_profile["reason"] = "enhanced_optimizer_disabled"
            return default_profile

        deployed = {}
        try:
            deployed = self.enhanced_optimizer.get_deployed_profile() or {}
        except Exception as exc:
            default_profile["reason"] = f"summary_error:{exc}"
            return default_profile

        params = deployed.get("params", {}) if isinstance(deployed.get("params"), dict) else {}
        if not params:
            default_profile["reason"] = "no_deployed_params"
            return default_profile

        deploy_ts = self._parse_datetime_value(deployed.get("timestamp"))
        if deploy_ts and self.optimization_max_profile_age_hours > 0:
            age_hours = (timestamp - deploy_ts).total_seconds() / 3600.0
            if age_hours > self.optimization_max_profile_age_hours:
                default_profile["reason"] = "deployed_profile_stale"
                return default_profile

        min_signal_score = self._to_float(params.get("min_signal_score", 0.0), 0.0)
        if min_signal_score <= 0:
            default_profile["reason"] = "invalid_min_signal_score"
            return default_profile

        total_floor = max(
            self.optimization_min_total_score_floor,
            min(self.optimization_max_total_score_floor, min_signal_score * 100.0),
        )
        intraday_floor = max(45.0, total_floor - self.optimization_intraday_margin)
        push_floor = max(70.0, total_floor + self.optimization_push_floor_offset)

        stop_loss_pct = self._to_float(params.get("stop_loss_pct", -0.05), -0.05)
        take_profit_pct = self._to_float(params.get("take_profit_pct", 0.10), 0.10)
        tp1_pct = max(0.03, take_profit_pct * self.optimization_tp1_ratio)
        trailing_stop_pct = max(0.015, self.optimization_trailing_stop_default)

        profile = dict(default_profile)
        profile.update(
            {
                "active": True,
                "reason": "deployed_profile_active",
                "params": dict(params),
                "factor_weights": deployed.get("factor_weights", {}) if isinstance(deployed.get("factor_weights"), dict) else {},
                "min_total_score_floor": float(total_floor),
                "min_intraday_score_floor": float(intraday_floor),
                "push_threshold_floor": float(push_floor),
                "exit_params": {
                    "stop_loss_pct": float(max(-0.08, min(-0.02, stop_loss_pct))),
                    "take_profit_pct": float(max(0.05, min(0.20, take_profit_pct))),
                    "tp1_pct": float(max(0.03, min(0.16, tp1_pct))),
                    "trailing_stop_pct": float(max(0.015, min(0.06, trailing_stop_pct))),
                    "max_hold_hours": self.optimization_max_hold_hours,
                },
                "score_delta": self._to_float(deployed.get("score_delta", 0.0)),
                "robustness_score": self._to_float(deployed.get("robustness_score", 0.0)),
                "trade_count": int(self._to_float(deployed.get("trade_count", 0), 0)),
            }
        )
        return profile

    def _get_optimization_runtime_profile(self, now: Optional[datetime] = None) -> Dict[str, Any]:
        timestamp = now or datetime.now()
        if not hasattr(self, "_optimization_runtime_cache"):
            total_floor = float(getattr(self, "optimization_min_total_score_floor", 68.0))
            intraday_margin = float(getattr(self, "optimization_intraday_margin", 14.0))
            push_offset = float(getattr(self, "optimization_push_floor_offset", 4.0))
            return {
                "enabled": bool(getattr(self, "optimization_runtime_enabled", False)),
                "active": False,
                "reason": "runtime_profile_uninitialized",
                "params": {},
                "factor_weights": {},
                "min_total_score_floor": total_floor,
                "min_intraday_score_floor": max(45.0, total_floor - intraday_margin),
                "push_threshold_floor": max(70.0, total_floor + push_offset),
                "exit_params": {},
                "timestamp": timestamp.strftime("%Y-%m-%d %H:%M:%S"),
                "score_delta": 0.0,
                "robustness_score": 0.0,
                "trade_count": 0,
            }
        cache = self._optimization_runtime_cache
        cached_ts = cache.get("ts")
        cached_profile = cache.get("profile")
        if (
            cached_ts is not None
            and cached_profile is not None
            and (timestamp - cached_ts).total_seconds() <= max(0, self.optimization_profile_refresh_seconds)
        ):
            return dict(cached_profile)

        profile = self._build_optimization_runtime_profile(now=timestamp)
        cache["ts"] = timestamp
        cache["profile"] = dict(profile)
        return profile

    def _normalize_symbol_6(code: Any) -> str:
        text = str(code or "").strip().upper()
        if not text:
            return ""
        if "." in text:
            text = text.split(".", 1)[0]
        if text.startswith("SH") or text.startswith("SZ"):
            text = text[2:]
        digits = "".join(ch for ch in text if ch.isdigit())
        if len(digits) >= 6:
            return digits[-6:]
        return ""

    def _record_monitor_incident(
        self,
        title: str,
        message: str,
        severity: str = "warning",
        component: str = "monitor.trade_control",
        context: Optional[Dict[str, Any]] = None,
    ):
        return runtime_record_monitor_incident(
            system=self,
            title=title,
            message=message,
            severity=severity,
            component=component,
            context=context,
        )

    def _get_market_gate_context(self, now: Optional[datetime] = None) -> Dict[str, Any]:
        return runtime_get_market_gate_context(system=self, now=now)

    def _get_feedback_guard_context(self, now: Optional[datetime] = None) -> Dict[str, Any]:
        return runtime_get_feedback_guard_context(system=self, now=now)





    def _maybe_emit_trade_control_alert(self, context: Dict[str, Any], circuit_changed: bool = False):
        return runtime_maybe_emit_trade_control_alert(
            system=self,
            context=context,
            circuit_changed=circuit_changed,
        )





    
    def add_backtest_data(self, backtest_trades: List[Dict]):
        """
        添加回测数据
        
        Args:
            backtest_trades: 回测交易列表
        """
        if not self.enable_enhanced_optimization or not self.enhanced_optimizer:
            logger.warning("增强优化器未启用，无法添加回测数据")
            return
        
        self.enhanced_optimizer.add_backtest_data(backtest_trades)
        logger.info(f"回测数据已添加: {len(backtest_trades)}笔")
    
    def get_optimization_summary(self) -> Dict:
        """获取优化总结"""
        if not self.enable_enhanced_optimization or not self.enhanced_optimizer:
            return {'status': 'disabled'}
        
        return self.enhanced_optimizer.get_optimization_summary()
    
    def get_factor_report(self) -> str:
        """获取因子分析报告"""
        if not self.enable_enhanced_optimization or not self.enhanced_optimizer:
            return "增强优化器未启用"
        
        return self.enhanced_optimizer.get_factor_report()
    
    def _get_recent_data_for_optimization(self):
        """获取最近数据用于优化"""
        try:
            samples = self._load_real_training_samples()
            if not samples:
                logger.warning("优化训练样本为空（真实样本入口）")
                return []

            feature_rows: List[Dict[str, Any]] = []
            symbol_to_dates: Dict[str, List[str]] = {}

            for item in samples:
                buy_time = self._parse_datetime_value(item.get("buy_time"))
                if buy_time is None:
                    continue

                symbol_raw = str(item.get("symbol", "") or "")
                symbol6 = self._normalize_symbol_6(symbol_raw)
                if not symbol6:
                    continue

                entry_date = buy_time.strftime("%Y-%m-%d")
                entry_trade_date = buy_time.strftime("%Y%m%d")
                pnl = self._to_float(item.get("pnl_pct", item.get("pnl", 0.0)), 0.0)
                signal_type = str(item.get("signal_type", "") or "real_sample")

                feature_rows.append(
                    {
                        "symbol": symbol6,
                        "entry_date": entry_date,
                        "entry_trade_date": entry_trade_date,
                        "signal_type": signal_type,
                        "pnl": pnl,
                        "rsi": 55.0,
                        "pullback": 8.0,
                        "volume_ratio": 1.5,
                    }
                )
                symbol_to_dates.setdefault(symbol6, []).append(entry_trade_date)

            if not feature_rows:
                return []

            min_trade_date = min(
                min(dates) for dates in symbol_to_dates.values() if dates
            )
            max_trade_date = max(
                max(dates) for dates in symbol_to_dates.values() if dates
            )
            min_dt = self._parse_datetime_value(min_trade_date) or datetime.now()
            start_dt = (min_dt - timedelta(days=40)).strftime("%Y%m%d")
            end_dt = max_trade_date

            ts_codes: List[str] = []
            seen_codes = set()
            for symbol6 in symbol_to_dates:
                code = f"{symbol6}.SH" if symbol6.startswith(("5", "6", "9")) else f"{symbol6}.SZ"
                if code not in seen_codes:
                    seen_codes.add(code)
                    ts_codes.append(code)

            price_map: Dict[str, pd.DataFrame] = {}
            chunk_size = 400
            for idx in range(0, len(ts_codes), chunk_size):
                chunk = ts_codes[idx : idx + chunk_size]
                placeholders = ",".join(["?"] * len(chunk))
                sql = f"""
                    SELECT ts_code, trade_date, close, high, low, vol
                    FROM stock_daily
                    WHERE ts_code IN ({placeholders})
                      AND trade_date >= ?
                      AND trade_date <= ?
                    ORDER BY ts_code, trade_date
                """
                rows = self.db.query(sql, tuple(chunk) + (start_dt, end_dt))
                if not rows:
                    continue
                df = pd.DataFrame(rows)
                if df.empty:
                    continue
                for ts_code, group in df.groupby("ts_code"):
                    g = group.sort_values("trade_date").reset_index(drop=True)
                    price_map[str(ts_code)] = g

            for row in feature_rows:
                ts_code = (
                    f"{row['symbol']}.SH"
                    if row["symbol"].startswith(("5", "6", "9"))
                    else f"{row['symbol']}.SZ"
                )
                hist = price_map.get(ts_code)
                if hist is None or hist.empty:
                    continue

                anchor = str(row.get("entry_trade_date", ""))
                hist_anchor = hist[hist["trade_date"] <= anchor]
                if hist_anchor.empty:
                    continue

                closes = pd.to_numeric(hist_anchor["close"], errors="coerce").dropna()
                highs = pd.to_numeric(hist_anchor["high"], errors="coerce").dropna()
                vols = pd.to_numeric(hist_anchor["vol"], errors="coerce").dropna()

                if len(closes) >= 15:
                    diffs = closes.diff().dropna().tail(14)
                    gains = diffs.clip(lower=0.0)
                    losses = (-diffs.clip(upper=0.0)).abs()
                    avg_gain = float(gains.mean()) if not gains.empty else 0.0
                    avg_loss = float(losses.mean()) if not losses.empty else 0.0
                    rs = avg_gain / (avg_loss + 1e-9)
                    row["rsi"] = max(1.0, min(99.0, 100.0 - 100.0 / (1.0 + rs)))

                if len(highs) >= 3 and len(closes) >= 1:
                    max_high_10 = float(highs.tail(10).max())
                    last_close = float(closes.iloc[-1])
                    if max_high_10 > 0:
                        row["pullback"] = max(
                            0.0,
                            min(40.0, (max_high_10 - last_close) / max_high_10 * 100.0),
                        )

                if len(vols) >= 6:
                    curr_vol = float(vols.iloc[-1])
                    base_vol = float(vols.iloc[-6:-1].mean())
                    if base_vol > 0:
                        row["volume_ratio"] = max(
                            0.2,
                            min(5.0, curr_vol / (base_vol + 1e-9)),
                        )

            return [
                {
                    "entry_date": item["entry_date"],
                    "signal_type": item["signal_type"],
                    "pnl": self._to_float(item["pnl"], 0.0),
                    "rsi": self._to_float(item.get("rsi", 55.0), 55.0),
                    "pullback": self._to_float(item.get("pullback", 8.0), 8.0),
                    "volume_ratio": self._to_float(item.get("volume_ratio", 1.5), 1.5),
                }
                for item in feature_rows
            ]
        except Exception as e:
            logger.error(f"获取数据失败: {e}")
            return []
    
    def _on_auto_optimization_signal(self, signal):
        """自动优化信号回调"""
        logger.info(f"自动优化信号: {signal}")
    
    def _on_auto_optimization_position_change(self, action, symbol, position):
        """自动优化持仓变化回调"""
        logger.info(f"持仓变化: {action} {symbol}")
    
    def start_auto_optimization(self):
        """启动自动优化"""
        if not self.enable_auto_optimization or not self.auto_optimizer:
            logger.warning("自动优化未启用")
            return False
        
        try:
            self.auto_optimizer.start(
                data_getter=self._get_recent_data_for_optimization,
                initial_strategy=self._default_strategy_for_optimization
            )
            logger.info("自动优化已启动")
            return True
        except Exception as e:
            logger.error(f"启动自动优化失败: {e}")
            return False
    
    def stop_auto_optimization(self):
        """停止自动优化"""
        if self.auto_optimizer:
            self.auto_optimizer.stop()
            logger.info("自动优化已停止")
    
    def on_trade_result(self, symbol: str, pnl: float, details: Dict = None):
        """
        交易结果反馈（用于在线学习）
        
        Args:
            symbol: 股票代码
            pnl: 盈亏
            details: 详细信息
        """
        # 记录交易结果
        trade_result = {
            'symbol': symbol,
            'pnl': pnl,
            'time': datetime.now(),
            'details': details or {}
        }
        self.trade_results.append(trade_result)
        
        # 反馈给自动优化系统
        if self.enable_auto_optimization and self.auto_optimizer:
            self.auto_optimizer.on_trade_result({'pnl': pnl, 'symbol': symbol})
            
            # 更新回撤
            drawdown = self._calculate_drawdown()
            self.auto_optimizer.on_drawdown_update(drawdown)
    
    def _calculate_drawdown(self) -> float:
        """计算当前回撤"""
        if not self.trade_results:
            return 0.0
        
        # 简化：计算累计盈亏
        total_pnl = sum(t['pnl'] for t in self.trade_results)
        
        # 假设初始资金100000
        initial_capital = 100000
        current_capital = initial_capital + total_pnl
        
        # 计算回撤
        if current_capital < initial_capital:
            return (initial_capital - current_capital) / initial_capital
        
        return 0.0
    
    
    
    
    def _build_intraday_data(self, price: float, volume: float, 
                            high: float, low: float) -> IntradayData:
        """
        构建分时数据（简化版）
        
        实际应用中应该获取真实的分时数据
        """
        # 模拟分时序列
        n = 30  # 30分钟数据
        
        # 价格序列（模拟波动）
        prices = np.array([price] * n)
        prices += np.random.randn(n) * price * 0.005  # 添加小波动
        
        # 成交量序列
        volumes = np.array([volume / n] * n)
        
        # 最高最低价
        highs = prices + np.random.rand(n) * (high - price)
        lows = prices - np.random.rand(n) * (price - low)
        
        return IntradayData(
            price=prices,
            volume=volumes,
            high=highs,
            low=lows,
            timestamp=np.arange(n)
        )
    
    

    # ── 委托方法（委托给拆分出的子模块） ──

    def load_candidate_pool(self) -> bool:
        return self.candidate_manager.load_candidate_pool()

    def _save_candidate_pool(self):
        self.candidate_manager._save_candidate_pool()

    def run_overnight_selection(self):
        return self.candidate_manager.run_overnight_selection()

    def print_buy_signals(self, signals):
        self.candidate_manager.print_buy_signals(signals)

    def _get_market_environment(self):
        return self.market_context._get_market_environment()

    def _report_trade_control_status(self, context, now=None):
        self.market_context._report_trade_control_status(context, now)

    def _build_buy_signal(self, symbol, name, price, score, reason, strategy_profile="default", extra=None):
        return self.signal_builder._build_buy_signal(symbol, name, price, score, reason, strategy_profile, extra)

    def _build_false_signal(self, symbol, reason):
        return self.signal_builder._build_false_signal(symbol, reason)

    def _wrap_signal_metadata(self, symbol, price, signal_type, source):
        return self.signal_builder._wrap_signal_metadata(symbol, price, signal_type, source)

    def _get_dynamic_signal_thresholds(self, market_score):
        return self.signal_builder._get_dynamic_signal_thresholds(market_score)

    def _calculate_total_signal_score(self, base_score, market_score, adjustments=None):
        return self.signal_builder._calculate_total_signal_score(base_score, market_score, adjustments)

    def start_realtime_monitor(self, interval_seconds: int = 10):
        """启动实时监控。"""
        return runtime_start_realtime_monitor(system=self, interval_seconds=interval_seconds)
    
    def stop_realtime_monitor(self):
        """停止实时监控。"""
        return runtime_stop_realtime_monitor(system=self)

    def start_monitoring(self, interval_seconds: int = 10):
        """Backward-compatible alias for legacy entrypoints."""
        return self.start_realtime_monitor(interval_seconds=interval_seconds)

    def stop_monitoring(self):
        """Backward-compatible alias for legacy entrypoints."""
        return self.stop_realtime_monitor()
    
    def _is_trade_time(self, now: datetime) -> bool:
        """判断是否为交易时间。"""
        return runtime_is_trade_time(now=now, system=self)
    
    def _show_non_trade_time(self, now: datetime):
        """显示非交易时间"""
        return runtime_show_non_trade_time(system=self, now=now)
    
    def _update_latest_quotes(self, df: pd.DataFrame):
        """更新最新行情数据"""
        return runtime_update_latest_quotes(system=self, df=df)
    
    def _show_monitor_info(self, df: pd.DataFrame, now: datetime):
        """显示监控信息"""
        return runtime_show_monitor_info(system=self, df=df, now=now)
    
    @staticmethod
    def _to_float(value, default: float = 0.0) -> float:
        try:
            return float(value)
        except Exception:
            return float(default)

    def _fetch_realtime_context(
        self,
        symbols: List[str],
    ) -> Tuple[pd.DataFrame, Dict[str, pd.DataFrame]]:
        return runtime_fetch_realtime_context(system=self, symbols=symbols)

    def _resolve_quote_row(
        self,
        symbol: str,
        stock_data: pd.DataFrame,
        minute_map: Optional[Dict[str, pd.DataFrame]] = None,
        candidate_name: str = "",
    ) -> Optional[Dict[str, float]]:
        return runtime_resolve_quote_row(
            system=self,
            symbol=symbol,
            stock_data=stock_data,
            minute_map=minute_map,
            candidate_name=candidate_name,
        )

    def _has_legacy_open_route_candidates(self) -> bool:
        if not bool(getattr(self, "legacy_gap_entry_enabled", True)):
            return False
        for candidate in getattr(self, "candidate_pool", []) or []:
            if self._resolve_candidate_strategy_profile(candidate) in {"legacy", "legacy_opt"}:
                return True
        return False

    def _signal_monitor_window_open(self, now: datetime, market_env: Optional[Dict[str, Any]] = None) -> bool:
        return runtime_signal_monitor_window_open(
            system=self,
            now=now,
            market_env=market_env,
        )

    def _detect_confirmation_signal(
        self,
        candidate: Dict[str, Any],
        quote: Dict[str, float],
        now: datetime,
        minute_map: Optional[Dict[str, pd.DataFrame]],
        market_env: Dict[str, Any],
        template_source: str,
        route_name: str,
        route_label: str,
        breakout_intraday_param_key: str = "breakout",
        debounce_window: Optional[int] = None,
        time_filter_profile: str = "default",
    ) -> SignalOutput:
        return runtime_detect_confirmation_signal(
            system=self,
            candidate=candidate,
            quote=quote,
            now=now,
            minute_map=minute_map,
            market_env=market_env,
            template_source=template_source,
            route_name=route_name,
            route_label=route_label,
            breakout_intraday_param_key=breakout_intraday_param_key,
            debounce_window=debounce_window,
            time_filter_profile=time_filter_profile,
        )

    def _detect_legacy_gap_signal(
        self,
        candidate: Dict[str, Any],
        quote: Dict[str, float],
        now: datetime,
        minute_map: Optional[Dict[str, pd.DataFrame]],
    ) -> Optional[SignalOutput]:
        return runtime_detect_legacy_gap_signal(
            system=self,
            candidate=candidate,
            quote=quote,
            now=now,
            minute_map=minute_map,
        )

    def _resolve_strategy_routed_signal(
        self,
        candidate: Dict[str, Any],
        quote: Dict[str, float],
        now: datetime,
        minute_map: Optional[Dict[str, pd.DataFrame]],
        market_env: Dict[str, Any],
    ) -> SignalOutput:
        return runtime_resolve_strategy_routed_signal(
            system=self,
            candidate=candidate,
            quote=quote,
            now=now,
            minute_map=minute_map,
            market_env=market_env,
        )

    def _resolve_signal_debounce_window(self, signal: SignalOutput) -> int:
        return runtime_resolve_signal_debounce_window(system=self, signal=signal)

    @staticmethod
    def _normalize_industry_key(industry_name: str) -> str:
        text = str(industry_name or "").strip().lower()
        if not text:
            return ""
        for token in (" ", "-", "_", "/", "\\", "·", "　"):
            text = text.replace(token, "")
        return text

    def _industry_level_by_score(self, score: float) -> str:
        return runtime_industry_level_by_score(system=self, score=score)

    def _build_candidate_minute_industry_context(
        self,
        minute_map: Optional[Dict[str, pd.DataFrame]],
    ) -> Dict:
        return runtime_build_candidate_minute_industry_context(
            system=self,
            minute_map=minute_map,
        )

    def _fetch_realtime_industry_context_from_source(self) -> Optional[Dict]:
        return runtime_fetch_realtime_industry_context_from_source(system=self)

    def _match_industry_context(self, industry_name: str, industry_map: Dict[str, Dict]) -> Optional[Dict]:
        return runtime_match_industry_context(
            system=self,
            industry_name=industry_name,
            industry_map=industry_map,
        )

    def _build_intraday_industry_context(
        self,
        minute_map: Optional[Dict[str, pd.DataFrame]],
        now: Optional[datetime] = None,
    ) -> Dict:
        return runtime_build_intraday_industry_context(
            system=self,
            minute_map=minute_map,
            now=now,
        )

    def _resolve_candidate_industry_confirm(
        self,
        candidate: Dict,
        industry_context: Optional[Dict],
    ) -> Dict:
        return runtime_resolve_candidate_industry_confirm(
            system=self,
            candidate=candidate,
            industry_context=industry_context,
        )

    def _build_intraday_from_minute(self, minute_df: pd.DataFrame) -> Optional[IntradayData]:
        return runtime_build_intraday_from_minute(system=self, minute_df=minute_df)

    def _get_intraday_data_for_signal(
        self,
        symbol: str,
        current_price: float,
        current_volume: float,
        high: float,
        low: float,
        minute_map: Optional[Dict[str, pd.DataFrame]] = None,
    ) -> Optional[IntradayData]:
        return runtime_get_intraday_data_for_signal(
            system=self,
            symbol=symbol,
            current_price=current_price,
            current_volume=current_volume,
            high=high,
            low=low,
            minute_map=minute_map,
            allow_quote_fallback=self.allow_quote_fallback_when_minute_missing,
        )

    def monitor_candidates(self) -> List[Dict]:
        """Use realtime minute bars only; missing minute data downgrades to observe/skip."""
        return runtime_monitor_candidates(self)

    def run_intraday_buy_router_healthcheck(self) -> List[Dict[str, Any]]:
        """盘中买点路由冒烟：各 strategy_profile 调用一次 resolve 不抛异常即视为链路可用。"""
        return runtime_run_intraday_buy_router_healthcheck(self)

    def _default_strategy_for_optimization(self, bar):
        """Default strategy hook for auto optimization with realtime minute input only."""
        try:
            now = datetime.now()
            symbol = str(bar.get("symbol", "")).strip()
            price = self._to_float(bar.get("price"))
            volume = self._to_float(bar.get("volume"))
            high = self._to_float(bar.get("high"), default=price)
            low = self._to_float(bar.get("low"), default=price)

            minute_map: Dict[str, pd.DataFrame] = {}
            if symbol:
                minute_df = self.minute_fetcher.get_minute_bars(symbol)
                if minute_df is not None and not minute_df.empty:
                    minute_map[symbol] = minute_df

            intraday_data = self._get_intraday_data_for_signal(
                symbol=symbol,
                current_price=price,
                current_volume=volume,
                high=high,
                low=low,
                minute_map=minute_map,
            )
            if intraday_data is None:
                return None
            signal = self.signal_detector.mutual_exclusive_signal(
                intraday_data,
                now,
                market_score=self._get_market_environment().get("market_score", 50.0),
            )

            if signal.signal:
                return {
                    "action": "buy",
                    "reason": signal.reason,
                    "confidence": signal.confidence,
                }
        except Exception as e:
            logger.error("Strategy execution failed: %s", e)

        return None

    def _monitor_loop(self, interval_seconds: int):
        """Background monitor loop with realtime minute source."""
        return runtime_monitor_loop(system=self, interval_seconds=interval_seconds)

    def _detect_signals(
        self,
        df: pd.DataFrame,
        now: datetime,
        minute_map: Optional[Dict[str, pd.DataFrame]] = None,
        industry_context: Optional[Dict] = None,
        trade_control: Optional[Dict[str, Any]] = None,
    ) -> List[Dict]:
        """Signal detection with minute source fallback."""
        return runtime_detect_signals(
            system=self,
            df=df,
            now=now,
            minute_map=minute_map,
            industry_context=industry_context,
            trade_control=trade_control,
        )

    def _show_buy_signals(self, signals: List[Dict], now: datetime):
        """显示买点信号。"""
        return runtime_show_buy_signals(signals, now)

    def _push_buy_signals(self, signals: List[Dict], now: datetime):
        return runtime_push_buy_signals(system=self, signals=signals, now=now)

    @staticmethod
    def _map_sell_reason(reason: str) -> str:
        return runtime_map_sell_reason(reason)

    def _build_sell_signals_from_closed_trades(
        self,
        closed_trades: List,
        trade_control: Optional[Dict[str, Any]] = None,
    ) -> List[Dict]:
        return runtime_build_sell_signals_from_closed_trades(
            system=self,
            closed_trades=closed_trades,
            trade_control=trade_control,
        )
    
    def _show_virtual_trades_closed(self, closed_trades: List, now: datetime):
        return runtime_show_virtual_trades_closed(
            system=self,
            closed_trades=closed_trades,
            now=now,
        )


# 使用示例
if __name__ == '__main__':
    # 创建系统
    system = EnhancedHybridSystem()
    
    # 步骤1：盘后选股（T日收盘后）
    print("步骤1：盘后选股")
    print("="*80)
    candidates = system.run_overnight_selection()
    
    if candidates:
        print(f"\n候选池：")
        for i, c in enumerate(candidates, 1):
            pool_str = "核心池" if c['pool_type'] == 'core' else "备选池"
            print(f"{i}. {c['symbol']} - {c['name']} [{pool_str}] 评分:{c['score']:.1f}")
    
    # 步骤2：盘中监控（T+1日交易时间）
    print("\n步骤2：盘中监控")
    print("="*80)
    signals = system.monitor_candidates()
    system.print_buy_signals(signals)
