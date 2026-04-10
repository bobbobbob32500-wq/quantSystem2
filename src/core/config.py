# -*- coding: utf-8 -*-
"""
配置管理模块
统一管理系统所有配置参数
支持从环境变量加载敏感信息
"""

import os
import yaml
from typing import Any, Dict
from src.core.logger import get_logger
from src.core.exceptions import ConfigException
from src.core.env_manager import EnvManager

logger = get_logger("config")


class ConfigManager:
    """配置管理器"""
    
    def __init__(self, config_file: str = None):
        """
        初始化配置管理器
        
        Args:
            config_file: 配置文件路径，默认为 src/config/config.yaml
        """
        if config_file is None:
            config_file = os.path.join(
                os.path.dirname(os.path.dirname(__file__)),
                "config",
                "config.yaml"
            )
        
        self.config_file = config_file
        self._config = {}
        self._load_config()
    
    def _load_config(self):
        """加载配置文件"""
        if not os.path.exists(self.config_file):
            logger.warning(f"配置文件不存在: {self.config_file}，使用默认配置")
            self._config = self._get_default_config()
            self._save_config()
            return
        
        try:
            with open(self.config_file, "r", encoding="utf-8") as f:
                self._config = yaml.safe_load(f) or {}
            
            self._load_sensitive_from_env()
            
            logger.info(f"配置文件加载成功: {self.config_file}")
        except Exception as e:
            logger.error(f"配置文件加载失败: {e}")
            raise ConfigException(f"配置文件加载失败: {e}")
    
    SENSITIVE_KEY_PATTERNS = (
        'token', 'webhook', 'secret', 'password', 'api_key', 'private_key',
    )

    def _load_sensitive_from_env(self):
        """从环境变量加载敏感配置（优先级高于配置文件）"""
        env_mappings = {
            'TUSHARE_TOKEN': 'data_source.tushare_token',
            'WECHAT_WEBHOOK': 'push.wechat_webhook',
            'POSITION_WECHAT_WEBHOOK': 'push.position_wechat_webhook',
            'DINGTALK_WEBHOOK': 'push.dingtalk_webhook',
            'LOG_LEVEL': 'system.log_level',
            'DATABASE_PATH': 'database.path',
        }

        for env_key, config_key in env_mappings.items():
            env_value = EnvManager.get(env_key)
            if env_value:
                keys = config_key.split('.')
                config = self._config
                for k in keys[:-1]:
                    if k not in config:
                        config[k] = {}
                    config = config[k]
                config[keys[-1]] = env_value
                logger.debug(f"从环境变量加载配置: {config_key}")

        self._clear_sensitive_in_config()

    def _clear_sensitive_in_config(self):
        """清除配置文件中残留的明文敏感值，防止意外泄露"""
        sensitive_keys = [
            ('data_source', 'tushare_token'),
            ('push', 'wechat_webhook'),
            ('push', 'position_wechat_webhook'),
            ('push', 'dingtalk_webhook'),
        ]
        for path in sensitive_keys:
            section = self._config
            for k in path[:-1]:
                if isinstance(section, dict) and k in section:
                    section = section[k]
                else:
                    break
            else:
                if isinstance(section, dict):
                    val = section.get(path[-1], '')
                    if val and self._is_sensitive_value(path[-1], val):
                        section[path[-1]] = ''

    def _is_sensitive_value(self, key: str, value: str) -> bool:
        """判断配置项是否为敏感值"""
        key_lower = key.lower()
        return any(p in key_lower for p in self.SENSITIVE_KEY_PATTERNS)
    
    def _get_default_config(self) -> Dict:
        """获取默认配置"""
        return {
            # 系统基础配置
            "system": {
                "name": "A股量化交易辅助系统",
                "version": "1.0.0",
                "log_level": "INFO"
            },
            
            # 数据源配置
            "data_source": {
                "primary": "tushare",
                "secondary": "adata",
                "tushare_token": "",
                "retry_times": 3,
                "retry_delay": 5,
                "realtime_minute_provider": "akshare",
                "minute_cache_ttl_seconds": 8,
                "minute_request_pause_seconds": 0.05,
                "minute_fetch_workers": 3,
                "minute_min_bars": 20,
                "minute_max_symbols_per_round": 12,
                "enable_akshare_minute_fetch": True,
                "disable_akshare_minute_on_py314": True,
                "startup_auto_update_enabled": True,
                "startup_refresh_stock_basic": True,
                "startup_sync_chip_data_enabled": True,
                "full_update_sync_chip_data_enabled": False,
                "startup_update_ready_time": "17:30",
                "startup_trade_calendar_lookback_days": 14,
                "startup_min_mainboard_coverage_ratio": 0.70,
                "fail_fast_on_quota_limit": True,
                # 实盘级：分钟批量拉取整体超时（秒），超时则返回部分结果并降级
                "minute_batch_timeout_seconds": 2.8,
            },
            
            # 数据库配置
            "database": {
                "type": "sqlite",
                "path": "data/database/quant_system.db",
                "backup_path": "data/database/backup/",
                "backup_days": 30
            },
            
            # 市场分析配置
            "market_analysis": {
                "trend_weight": 0.4,
                "width_weight": 0.35,
                "volume_weight": 0.25,
                "volume_coefficient": 1.0,
                "weak_threshold": 45.0,
                "indices": ["000001.SH", "399001.SZ", "399006.SZ"]
            },
            
            # 选股配置
            "stock_selection": {
                "strategy_profile": "legacy",
                "enhanced_weight_profile": "active",
                "enhanced_weight_profiles": {
                    "active": {
                        "trend": 0.2613,
                        "momentum": 0.3324,
                        "volume": 0.0125,
                        "fundamental": 0.0651,
                        "pullback": 0.2164,
                        "quality": 0.1122,
                    },
                },
                "trend_factor_weight": 0.2613,
                "momentum_factor_weight": 0.3324,
                "volume_factor_weight": 0.0125,
                "fundamental_factor_weight": 0.0651,
                "pullback_factor_weight": 0.2164,
                "quality_factor_weight": 0.1122,
                "legacy_trend_factor_weight": 0.35,
                "legacy_momentum_factor_weight": 0.30,
                "legacy_volume_factor_weight": 0.05,
                "legacy_fundamental_factor_weight": 0.05,
                "legacy_pullback_factor_weight": 0.15,
                "legacy_opt_trend_factor_weight": 0.35,
                "legacy_opt_momentum_factor_weight": 0.30,
                "legacy_opt_volume_factor_weight": 0.05,
                "legacy_opt_fundamental_factor_weight": 0.05,
                "legacy_opt_pullback_factor_weight": 0.15,
                "top_n": 10,
                "min_score": 60.0,
                "exclude_st": True,
                "exclude_new": 60,
                "prediction_period": 5,
                "min_avg_amount_20d": 100000.0,
                "max_recent_limit_up_count_20d": 2,
                "max_recent_return_20d": 25.0,
                "max_avg_amplitude_10d": 6.5,
                "max_latest_pct_chg": 8.5,
                "short_cycle_score_weight": 0.16,
                "tradeability_penalty_weight": 0.18,
                "use_point_in_time_universe": True,
                "universe_max_stale_days": 10,
                "use_dynamic_tradeability_thresholds": True,
                "dynamic_liquidity_quantile": 0.35,
                "dynamic_limit_up_quantile": 0.80,
                "dynamic_recent_return_quantile": 0.85,
                "dynamic_amplitude_quantile": 0.80,
                "dynamic_latest_pct_chg_quantile": 0.90,
                "dynamic_threshold_min_ratio": 0.70,
                "dynamic_threshold_max_ratio": 1.40,
                "limit_up_threshold": 9.7,
                "strong_up_day_threshold": 6.0,
                "use_dynamic_industry_strength": True,
                "industry_lookback_days": 5,
                "industry_min_stock_count": 8,
                "industry_cache_days": 1,
                "enhanced_market_guard_enabled": False,
                "enhanced_market_guard_index_code": "000001.SH",
                "enhanced_market_guard_min_ret1": 0.0,
                "enhanced_market_guard_min_ret3": -0.005,
                "feedback_guard_enabled": True,
                "feedback_guard_min_score_boost_caution": 2.0,
                "feedback_guard_min_score_boost_defensive": 4.0,
                "feedback_guard_top_n_multiplier_caution": 0.90,
                "feedback_guard_top_n_multiplier_defensive": 0.70,
                "feedback_guard_min_avg_amount_multiplier_caution": 1.10,
                "feedback_guard_min_avg_amount_multiplier_defensive": 1.25,
                "feedback_guard_max_return_multiplier_caution": 0.92,
                "feedback_guard_max_return_multiplier_defensive": 0.82,
                "feedback_guard_max_amplitude_multiplier_caution": 0.92,
                "feedback_guard_max_amplitude_multiplier_defensive": 0.82,
                "feedback_guard_max_latest_pct_multiplier_caution": 0.95,
                "feedback_guard_max_latest_pct_multiplier_defensive": 0.85,
                "secondary_launch": {
                    "enabled": True,
                    "min_list_days": 60,
                    "limit_up_threshold": 9.7,
                    "limit_down_threshold": -9.7,
                    "limit_up_count_10_min": 1,
                    "limit_up_count_10_max": 1,
                    "last_limit_up_days_min": 2,
                    "last_limit_up_days_max": 4,
                    "drawdown_min": 0.03,
                    "drawdown_max": 0.06,
                    "vol_shrink_ratio": 0.70,
                    "close_ma5_dev_max": 0.035,
                    "min_amt_ma20": 1e5,
                    "max_amt_ma20": 5e6,
                    "min_price": 3.0,
                    "limit_up_amt_ratio_min": 0.0,
                    "limit_up_amt_ratio_max": 999.0,
                    "rs_lookback": 20,
                    "max_candidates": 20,
                    "picks_per_day": 2,
                    "hold_days": 3,
                    "transfer_fee_rate": 0.00001,
                    "backtest_in_sample_start": "20251201",
                    "backtest_in_sample_end": "20260327",
                    "backtest_oos_start": "20260301",
                    "backtest_oos_end": "20260327",
                    "use_auction_filter": False,
                },
            },
            
            # 风控配置
            "risk_control": {
                "volume_high_ratio": 0.92,
                "volume_high_days": 120,
                "market_bad_threshold": 48.0,
                "profit_low_threshold": 5.0,
                "profit_high_threshold": 15.0,
                "market_weak_threshold": 45.0
            },
            
            # 监控配置
            "monitor": {
                "enabled": True,
                "interval_minutes": 5,
                "trade_start_time": "09:30",
                "trade_end_time": "15:00",
                "service_status_interval_minutes": 5,
                "heartbeat_timeout_seconds": 600,
                "alert_cooldown_seconds": 900,
                "health_snapshot_interval_seconds": 60,
                "intraday_industry_confirm_enabled": True,
                "allow_quote_fallback_when_minute_missing": True,
                "intraday_industry_min_symbols": 2,
                "intraday_industry_lookback_bars": 15,
                "intraday_industry_strong_threshold": 65.0,
                "intraday_industry_weak_threshold": 40.0,
                "intraday_industry_cache_seconds": 30,
                "legacy_gap_entry_enabled": True,
                "legacy_gap_entry_start_time": "09:35",
                "legacy_gap_entry_end_time": "10:15",
                "legacy_low_open_entry_end_time": "10:30",
                "legacy_gap_mid_lower_pct": 1.0,
                "legacy_gap_mid_upper_pct": 4.0,
                "legacy_gap_flat_skip_lower_pct": -2.0,
                "legacy_gap_flat_skip_upper_pct": 1.0,
                "legacy_low_open_reclaim_pct": 0.3,
                "legacy_low_open_min_wait_time": "09:45",
                "legacy_low_open_min_low_age_bars": 1,
                "legacy_low_open_rebound_from_low_pct": 0.5,
                "legacy_low_open_max_chase_from_low_pct": 2.0,
                "legacy_low_open_recent_trend_bars": 3,
                "legacy_open_support_tolerance_pct": 0.8,
                "legacy_vwap_support_tolerance_pct": 0.2,
                "legacy_route_exit_override_enabled": True,
                "legacy_route_exit_overrides": {
                    "legacy_gap_mid_open": {
                        "profile_label": "mid_open_protect_v1",
                        "stop_loss_pct": -0.05,
                        "tp1_pct": 0.06,
                        "take_profit_pct": 0.10,
                        "trailing_stop_pct": 0.03,
                        "max_hold_hours": 96,
                        "carry_peak_arm_on_t1": True,
                    },
                    "legacy_confirmation_fallback": {
                        "profile_label": "confirmation_protect_v1",
                        "stop_loss_pct": -0.045,
                        "tp1_pct": 0.06,
                        "take_profit_pct": 0.10,
                        "trailing_stop_pct": 0.03,
                        "max_hold_hours": 96,
                        "carry_peak_arm_on_t1": False,
                    },
                },
                "market_gate_enabled": True,
                "market_gate_refresh_seconds": 120,
                "market_gate_open_min_target_position": 0.30,
                "market_gate_force_defensive_regimes": ["WEAK_BEAR", "BEAR", "STRONG_BEAR"],
                "market_gate_defensive_score_boost": 4.0,
                "market_gate_defensive_push_boost": 4.0,
                "market_gate_defensive_position_multiplier": 0.60,
                "market_gate_normal_max_signals_per_round": 4,
                "market_gate_defensive_max_signals_per_round": 2,
                "intraday_circuit_breaker_enabled": True,
                "circuit_index_codes": ["000001.SH", "399001.SZ", "399006.SZ"],
                "circuit_soft_trigger_drop_pct": -1.2,
                "circuit_hard_trigger_drop_pct": -2.0,
                "circuit_soft_breadth_threshold": 0.35,
                "circuit_hard_breadth_threshold": 0.25,
                "circuit_hold_minutes": 20,
                "circuit_recover_drop_pct": -0.8,
                "circuit_recover_breadth_threshold": 0.45,
                "circuit_soft_score_boost": 3.0,
                "circuit_soft_push_boost": 2.0,
                "circuit_soft_position_multiplier": 0.5,
                "position_linkage_enabled": True,
                "position_linkage_per_signal_cap": 0.12,
                "position_linkage_min_ratio": 0.02,
                "trade_control_alert_cooldown_seconds": 300,
                "trade_control_status_print_interval_seconds": 60,
                "feedback_guard_enabled": True,
                "feedback_guard_position_multiplier_caution": 0.85,
                "feedback_guard_position_multiplier_defensive": 0.65,
                "feedback_guard_threshold_boost_caution": 1.5,
                "feedback_guard_threshold_boost_defensive": 3.0,
                "feedback_guard_push_boost_caution": 1.0,
                "feedback_guard_push_boost_defensive": 2.0,
                "feedback_guard_max_signals_caution": 3,
                "feedback_guard_max_signals_defensive": 2,
                "feedback_guard_refresh_seconds": 300,
                "optimization_runtime_enabled": True,
                "optimization_profile_refresh_seconds": 60,
                "feedback_adaptive_cache_seconds": 300,
                "optimization_deploy_min_score_delta": 0.001,
                "optimization_deploy_min_trade_count": 30,
                "optimization_max_profile_age_hours": 168.0,
                "optimization_apply_to_thresholds": True,
                "optimization_apply_to_exit_params": True,
                "optimization_min_total_score_floor": 68.0,
                "optimization_max_total_score_floor": 88.0,
                "optimization_intraday_margin": 14.0,
                "optimization_push_floor_offset": 4.0,
                "optimization_tp1_ratio": 0.65,
                "optimization_trailing_stop_default": 0.035,
                "optimization_max_hold_hours": None,
                "optimization_auto_start": True,
                "optimization_bootstrap_enabled": True,
                "optimization_bootstrap_lookback_days": 180,
                "optimization_bootstrap_max_samples": 2000,
                "optimization_param_space": {
                    "min_signal_score": [0.6, 0.7, 0.8],
                    "stop_loss_pct": [-0.03, -0.05, -0.07],
                    "take_profit_pct": [0.08, 0.10, 0.12],
                },
                "optimization_min_win_rate_improvement": 0.01,
                "optimization_min_pnl_improvement": 0.01,
                "optimization_interval": 50,
                "optimization_min_trades": 20,
                "optimization_backtest_weight": 0.3,
                "optimization_min_robustness_score": 0.55,
            },
            
            # 消息推送配置
            "push": {
                "enabled": False,
                "dingtalk_webhook": "",
                "wechat_webhook": "",
                "position_push_enabled": True,
                "position_wechat_webhook": "",
                "position_event_cooldown_minutes": 30,
                "position_retry_max_attempts": 3,
                "position_retry_delay_seconds": 60,
                "position_retry_batch_size": 20,
                # 通用推送 outbox：失败不丢，落库重试
                "outbox_enabled": True,
                "outbox_retry_batch_size": 30,
                "outbox_retry_delay_seconds": 60,
                "outbox_max_attempts": 5,
                "request_timeout_seconds": 8,
                "webhook_min_interval_seconds": 0.7,
                "webhook_rate_limit_retry_attempts": 2,
                "webhook_rate_limit_backoff_seconds": 1.2,
                "webhook_retry_jitter_seconds": 0.2,
                "retry_batch_pause_seconds": 0.35,
            },
            
            # 定时任务配置
            "scheduler": {
                "daily_report_time": "08:30",
                "trade_plan_time": "14:50",
                "data_update_time": "17:30",
                "post_market_time": "18:00",
                "feedback_digest_time": "18:10",
            },

            # 信号收益闭环评估配置
            "feedback": {
                "history_recommendation_db": "data/history_recommendation.db",
                "report_dir": "reports",
                "persist_to_db": True,
                "default_lookback_days": 90,
                "snapshot_enabled": True,
                "snapshot_lookback_days": 90,
                "snapshot_top_n_per_day": 10,
                "snapshot_recommendation_horizons": [2, 3, 4, 5],
                "snapshot_signal_horizons": [1, 2, 3],
                "snapshot_min_samples_for_best": 10,
                "snapshot_use_latest_run": True,
                "snapshot_latest_run_max_age_hours": 24,
                "digest_push_enabled": True,
                "digest_min_samples_for_best": 10,
                "top_n_per_day": 10,
                "recommendation_horizons": [2, 3, 4, 5],
                "signal_horizons": [1, 2, 3],
                "buy_slippage": 0.001,
                "sell_slippage": 0.001,
                "buy_fee_rate": 0.0003,
                "sell_fee_rate": 0.0003,
                "stamp_tax_rate": 0.001,
                "guard_enabled": True,
                "guard_windows": [20, 60],
                "guard_min_samples": 20,
                "guard_pre_market_horizon": 2,
                "guard_sell_horizon": 3,
                "guard_negative_threshold": 0.0,
                "guard_require_sell_confirmation": False,
            }
        }
    
    def _save_config(self):
        """保存配置到文件"""
        os.makedirs(os.path.dirname(self.config_file), exist_ok=True)
        try:
            with open(self.config_file, "w", encoding="utf-8") as f:
                yaml.dump(self._config, f, allow_unicode=True, default_flow_style=False)
            logger.info(f"配置文件保存成功: {self.config_file}")
        except Exception as e:
            logger.error(f"配置文件保存失败: {e}")
            raise ConfigException(f"配置文件保存失败: {e}")
    
    def get(self, key: str, default: Any = None) -> Any:
        """
        获取配置值（支持多级key，用.分隔）
        
        Args:
            key: 配置键，如 "data_source.primary"
            default: 默认值
        
        Returns:
            配置值
        """
        keys = key.split(".")
        value = self._config
        
        for k in keys:
            if isinstance(value, dict) and k in value:
                value = value[k]
            else:
                return default
        
        return value
    
    def set(self, key: str, value: Any, save: bool = True):
        """
        设置配置值
        
        Args:
            key: 配置键
            value: 配置值
            save: 是否立即保存到文件
        """
        keys = key.split(".")
        config = self._config
        
        for k in keys[:-1]:
            if k not in config:
                config[k] = {}
            config = config[k]
        
        config[keys[-1]] = value
        logger.info(f"配置已更新: {key} = {value}")
        
        if save:
            self._save_config()
    
    def get_all(self) -> Dict:
        """获取所有配置"""
        return self._config.copy()
    
    def reload(self):
        """重新加载配置"""
        self._load_config()
        logger.info("配置已重新加载")
