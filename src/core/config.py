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
            
            # 先清除 YAML 中明文敏感项，再由环境变量覆盖（避免把 env 里的 token 一并清空）
            self._clear_sensitive_in_config()
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
                "alpha158_lgb_model_enabled": True,
                "alpha158_lgb_model_path": "models/alpha158_lgb_model.txt",
                "alpha158_lgb_config_path": "models/alpha158_lgb_config.json",
                "alpha158_secondary_lgb_overlay_enabled": False,
                "alpha158_secondary_lgb_model_path": "models/alpha158_t5_lgb_model.txt",
                "alpha158_secondary_lgb_config_path": "models/alpha158_t5_lgb_config.json",
                "alpha158_secondary_lgb_weight": 0.15,
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
                "institutional_core": {
                    "lookback_days": 120,
                    "min_history_days": 80,
                    "min_amount": 150000.0,
                    "score_threshold": 58.0,
                    "min_quality_score": 42.0,
                    "risk_penalty_weight": 28.0,
                    "min_close_to_ma60": 0.96,
                    "min_ret60": -0.03,
                    "max_top_distance": 0.18,
                },
                "multi_strategy_daily": {
                    "enabled": True,
                    "lookback_days": 140,
                    "max_per_sleeve": 4,
                    "top_n": 5,
                    "min_combined_score": 58.0,
                    "allow_breakout_in_sideways": False,
                    "alpha_base_keep_ratio": 0.8,
                    "max_satellite_replacements": 1,
                    "breakout_overlay_bonus": 6.0,
                    "secondary_overlay_bonus": 4.0,
                    "wide_breakout_overlay_bonus": 5.0,
                    "enable_secondary_overlay": True,
                    "enable_wide_breakout_overlay": True,
                    "enable_satellite_fill": True,
                    "breakout_replace_threshold": 88.0,
                    "secondary_replace_threshold": 90.0,
                    "wide_breakout_replace_threshold": 92.0,
                    "alpha_edge_threshold": 62.0,
                    "regime_sleeve_weights": {
                        "trend": {
                            "alpha158": 0.58,
                            "breakout": 0.32,
                            "secondary_launch": 0.10,
                        },
                        "sideways": {
                            "alpha158": 0.70,
                            "breakout": 0.00,
                            "secondary_launch": 0.30,
                        },
                        "weak": {
                            "alpha158": 0.85,
                            "breakout": 0.00,
                            "secondary_launch": 0.15,
                        },
                    },
                },
                "portfolio_gate": {
                    "enabled": True,
                    "apply_profiles": ["institutional_core"],
                    "shortlist_multiplier": 4,
                    "lookback_days": 40,
                    "min_history": 25,
                    "max_per_industry": 2,
                    "max_pair_corr": 0.82,
                    "max_avg_corr": 0.58,
                    "max_hot_industry_slots": 1,
                    "max_risk_flags": 2,
                    "correlation_penalty_weight": 10.0,
                    "crowding_penalty_weight": 8.0,
                    "industry_penalty_weight": 5.0,
                    "allow_fallback_fill": False,
                    "trend_max_positions": 4,
                    "sideways_max_positions": 3,
                    "weak_max_positions": 2,
                    "trend_min_gate_score": 68.0,
                    "sideways_min_gate_score": 72.0,
                    "weak_min_gate_score": 76.0,
                },
                "loss_avoidance": {
                    "enabled": True,
                    "apply_profiles": ["institutional_core", "alpha158", "daily_multi_strategy"],
                    "trend_block_score": 2.3,
                    "sideways_block_score": 1.3,
                    "weak_block_score": 0.95,
                },
                "abstain_guard": {
                    "enabled": True,
                    "apply_profiles": ["alpha158", "daily_multi_strategy"],
                    "trend_top1_min_score": 58.0,
                    "sideways_top1_min_score": 61.0,
                    "weak_top1_min_score": 65.0,
                    "trend_top3_avg_min_score": 56.0,
                    "sideways_top3_avg_min_score": 59.0,
                    "weak_top3_avg_min_score": 63.0,
                    "max_avg_loss_avoidance_score": 0.90,
                    "sideways_min_candidates": 2,
                    "weak_min_candidates": 2,
                    "sideways_single_candidate_min_score": 76.0,
                    "weak_single_candidate_min_score": 76.0,
                    "weak_force_abstain_if_market_below_ma20": False,
                    "route_aware_positioning_enabled": True,
                    "dynamic_route_min_count": 1,
                    "sideways_keep_n_with_dynamic": 3,
                    "sideways_keep_n_without_dynamic": 2,
                    "weak_keep_n_with_dynamic": 1,
                    "weak_keep_n_without_dynamic": 1,
                },
                "position_sizing": {
                    "enabled": True,
                    "mode": "risk_budget_equal_weight",
                    "apply_profiles": ["alpha158"],
                    "trend_gross_exposure": 1.00,
                    "sideways_gross_exposure": 0.70,
                    "weak_gross_exposure": 0.35,
                    "market_below_ma20_multiplier": 0.75,
                    "score_power": 1.35,
                    "top_rank_boost": 0.18,
                    "loss_penalty_weight": 0.28,
                    "risk_flag_penalty": 0.12,
                    "sideways_risk_penalty_multiplier": 1.10,
                    "weak_risk_penalty_multiplier": 1.25,
                    "dynamic_hold_route_boost": 0.0,
                    "quality_route_boost": 0.0,
                    "pullback_route_boost": 0.0,
                    "short_hold_penalty": 0.0,
                    "single_name_cap": 0.25,
                    "min_name_weight": 0.08,
                },
                "alpha158_extension_enabled": False,
                "alpha158_extension_trend_quality_bonus": 0.18,
                "alpha158_extension_compression_bonus": 0.14,
                "alpha158_extension_leadership_bonus": 0.16,
                "alpha158_extension_overheat_penalty": 0.20,
                "alpha158_extension_trend_multiplier": 1.00,
                "alpha158_extension_sideways_multiplier": 0.75,
                "alpha158_extension_weak_multiplier": 0.45,
                "alpha158_prototype_router_enabled": True,
                "alpha158_prototype_trend_continuation_bonus": 0.0,
                "alpha158_prototype_trend_pullback_bonus": 0.0,
                "alpha158_prototype_trend_quality_bonus": 0.0,
                "alpha158_prototype_trend_risk_penalty": 0.0,
                "alpha158_prototype_sideways_continuation_bonus": 0.0,
                "alpha158_prototype_sideways_pullback_bonus": 0.0,
                "alpha158_prototype_sideways_quality_bonus": 0.0,
                "alpha158_prototype_sideways_risk_penalty": 0.0,
                "alpha158_prototype_weak_continuation_bonus": 0.0,
                "alpha158_prototype_weak_pullback_bonus": 0.0,
                "alpha158_prototype_weak_quality_bonus": 0.0,
                "alpha158_prototype_weak_risk_penalty": 0.0,
                "alpha158_hold_router_name": "regime_router_v3_selective",
                "alpha158_hold_router": {
                    "trend": {
                        "continuation": 5,
                        "pullback": 4,
                        "quality": 5,
                        "risk": 2,
                        "default": 4,
                    },
                    "sideways": {
                        "continuation": 5,
                        "pullback": 4,
                        "quality": 4,
                        "risk": 2,
                        "default": 3,
                    },
                    "weak": {
                        "continuation": 2,
                        "pullback": 2,
                        "quality": 4,
                        "risk": 2,
                        "default": 2,
                    },
                },
                "alpha158_hold_router_apply": {
                    "trend": {
                        "continuation": False,
                        "pullback": True,
                        "quality": False,
                        "risk": False,
                        "default": False,
                    },
                    "sideways": {
                        "continuation": False,
                        "pullback": False,
                        "quality": True,
                        "risk": False,
                        "default": False,
                    },
                    "weak": {
                        "continuation": False,
                        "pullback": False,
                        "quality": True,
                        "risk": False,
                        "default": False,
                    },
                },
                "exit_guard": {
                    "enabled": True,
                    "stop_loss_pct": -0.045,
                    "trail_arm_pct": 0.05,
                    "trail_drawdown_pct": 0.03,
                    "weak_time_stop_days": 2,
                    "activation_loss_avoidance_threshold": 1.00,
                    "activation_loss_avoidance_threshold_by_regime": {
                        "trend": None,
                        "sideways": 0.80,
                        "weak": 1.00,
                    },
                    "regimes": {
                        "trend": {
                            "stop_loss_pct": -0.060,
                            "trail_arm_pct": 0.08,
                            "trail_drawdown_pct": 0.040,
                            "weak_time_stop_days": 3,
                        },
                        "sideways": {
                            "stop_loss_pct": -0.045,
                            "trail_arm_pct": 0.055,
                            "trail_drawdown_pct": 0.030,
                            "weak_time_stop_days": 2,
                        },
                        "weak": {
                            "stop_loss_pct": -0.035,
                            "trail_arm_pct": 0.04,
                            "trail_drawdown_pct": 0.025,
                            "weak_time_stop_days": 2,
                        },
                    },
                },
                "light_entry_filter": {
                    "enabled": False,
                    "apply_regimes": ["weak"],
                    "preserve_top1_on_empty": True,
                    "regimes": {
                        "trend": {
                            "max_gap_pct": 0.070,
                            "max_day_pct_chg": 0.095,
                            "max_upper_shadow": 0.45,
                            "max_path_risk_score": 0.85,
                            "min_entry_quality_score": 0.32,
                            "max_recent_limit_up_count20": 3,
                            "max_vol_ratio5": 2.40,
                        },
                        "sideways": {
                            "max_gap_pct": 0.052,
                            "max_day_pct_chg": 0.078,
                            "max_upper_shadow": 0.35,
                            "max_path_risk_score": 0.74,
                            "min_entry_quality_score": 0.40,
                            "max_recent_limit_up_count20": 2,
                            "max_vol_ratio5": 2.00,
                        },
                        "weak": {
                            "max_gap_pct": 0.038,
                            "max_day_pct_chg": 0.058,
                            "max_upper_shadow": 0.30,
                            "max_path_risk_score": 0.64,
                            "min_entry_quality_score": 0.48,
                            "max_recent_limit_up_count20": 1,
                            "max_vol_ratio5": 1.70,
                        },
                    },
                },
                "fallback_enabled": False,
                "trend_near_threshold_fallback_enabled": True,
                "fallback_margin": 0.03,
                "fallback_max_count_mode": "top_n",
                "alpha158_regime_trend_breadth_min_up_ratio": 0.52,
                "alpha158_regime_trend_breadth_min_median_ret": 0.0,
                "alpha158_regime_trend_breadth_min_new_high_ratio": 0.08,
                "alpha158_regime_weak_breadth_max_up_ratio": 0.42,
                "alpha158_regime_weak_breadth_max_median_ret": -0.003,
                "alpha158_regime_weak_breadth_max_new_high_ratio": 0.05,
                "alpha158_regime_weak_extra_score_threshold_delta": 0.03,
                "alpha158_regime_weak_extra_top_n_multiplier": 0.85,
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
            
            # Qlib Alpha158 / LightGBM（与 Optuna 优化 JSON 对接，供训练与回测脚本统一读取）
            "qlib": {
                "use_optuna_alpha_lgb_params": True,
                "optuna_alpha_comparison_json": "output/qlib_optuna_alpha_comparison.json",
                "provider_uri": "~/.qlib/qlib_data/cn_data",
                "lgb_num_threads": None,
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
