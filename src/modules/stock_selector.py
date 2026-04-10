# -*- coding: utf-8 -*-
"""
每日选股模块
基于多因子策略（趋势+动量+量能+基本面+回调保护）进行选股
针对小资金、短中线风格优化
集成自动优化系统
"""

import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional

from src.core.logger import get_logger
from src.core.config import ConfigManager
from src.core.database import DatabaseManager
from src.core.exceptions import StockSelectionException
from src.modules.factor_cache import FactorValueStorage
from src.modules.feedback_guard import FeedbackPerformanceGuard

# 导入自动优化系统
try:
    from src.modules.fully_automatic_system import FullyAutomaticOptimizationSystem
    AUTO_OPTIMIZATION_AVAILABLE = True
except ImportError as e:
    get_logger("stock_selection").warning(f"自动优化系统导入失败: {e}")
    AUTO_OPTIMIZATION_AVAILABLE = False

logger = get_logger("stock_selection")

ENHANCED_WEIGHT_CONFIG_MAP = {
    "trend": "trend_factor_weight",
    "momentum": "momentum_factor_weight",
    "volume": "volume_factor_weight",
    "fundamental": "fundamental_factor_weight",
    "pullback": "pullback_factor_weight",
    "quality": "quality_factor_weight",
}

LEGACY_BASE_PROFILE = "legacy"
ENHANCED_PROFILE = "enhanced"
SUPPORTED_STRATEGY_PROFILES = {LEGACY_BASE_PROFILE, ENHANCED_PROFILE}


class StockSelector:
    """股票选择器 - 多因子选股模型（集成自动优化）"""
    
    def __init__(self, config: ConfigManager = None, db: DatabaseManager = None,
                 enable_auto_optimization: bool = False):
        """
        初始化股票选择器
        
        Args:
            config: 配置管理器
            db: 数据库管理器
            enable_auto_optimization: 是否启用自动优化
        """
        if config is None:
            config = ConfigManager()
        if db is None:
            db = DatabaseManager(config)
        
        self.config = config
        self.db = db
        
        # 因子值存储
        self.factor_storage = FactorValueStorage(db)
        
        # 策略档位：legacy / enhanced
        requested_profile = str(config.get("stock_selection.strategy_profile", LEGACY_BASE_PROFILE) or LEGACY_BASE_PROFILE)
        requested_profile = requested_profile.strip().lower()
        if requested_profile not in SUPPORTED_STRATEGY_PROFILES:
            requested_profile = LEGACY_BASE_PROFILE
        self.strategy_profile = requested_profile

        # enhanced 命名权重档位（用于看板/测试/回放；legacy 下也保留读取能力）
        self.enhanced_weight_profile = str(
            config.get("stock_selection.enhanced_weight_profile", "active") or "active"
        ).strip()
        self.enhanced_weight_profiles = config.get("stock_selection.enhanced_weight_profiles", {}) or {}
        if not isinstance(self.enhanced_weight_profiles, dict):
            self.enhanced_weight_profiles = {}

        # 兜底：确保关键命名档位存在，避免配置被裁剪时影响实盘一致性与回归测试
        self.enhanced_weight_profiles.setdefault(
            "active",
            {
                "trend": float(config.get("stock_selection.trend_factor_weight", 0.2613)),
                "momentum": float(config.get("stock_selection.momentum_factor_weight", 0.3324)),
                "pullback": float(config.get("stock_selection.pullback_factor_weight", 0.2164)),
                "quality": float(config.get("stock_selection.quality_factor_weight", 0.1122)),
                "fundamental": float(config.get("stock_selection.fundamental_factor_weight", 0.0651)),
                "volume": float(config.get("stock_selection.volume_factor_weight", 0.0125)),
            },
        )
        self.enhanced_weight_profiles.setdefault(
            "progressive_20",
            {
                "trend": 0.2486,
                "momentum": 0.3326,
                "pullback": 0.1861,
                "quality": 0.1389,
                "fundamental": 0.0795,
                "volume": 0.0143,
            },
        )
        self.enhanced_weight_profiles.setdefault(
            "quality_ab_0109",
            {
                "trend": 0.2572,
                "momentum": 0.3441,
                "pullback": 0.1926,
                "quality": 0.1090,
                "fundamental": 0.0823,
                "volume": 0.0148,
            },
        )

        # enhanced 基础权重字段（供后续动态调权/看板/回归测试使用）
        # 默认以“当前命名档位”为基准，缺失则回退到 active
        base_profile = (
            dict(self.enhanced_weight_profiles.get(self.enhanced_weight_profile) or {})
            or dict(self.enhanced_weight_profiles.get("active") or {})
        )
        base_profile = self._normalize_weights(base_profile)
        self.base_enhanced_weights = dict(base_profile)
        self.trend_weight = float(base_profile.get("trend", 0.0))
        self.momentum_weight = float(base_profile.get("momentum", 0.0))
        self.volume_weight = float(base_profile.get("volume", 0.0))
        self.fundamental_weight = float(base_profile.get("fundamental", 0.0))
        self.pullback_weight = float(base_profile.get("pullback", 0.0))
        self.quality_weight = float(base_profile.get("quality", 0.0))

        # legacy 因子权重配置
        # P1d: volume_weight 默认改为 0.10，启用量能因子
        self.legacy_trend_weight = float(
            config.get("stock_selection.legacy_trend_factor_weight",
                       config.get("stock_selection.trend_factor_weight", 0.45))
        )
        self.legacy_momentum_weight = float(
            config.get("stock_selection.legacy_momentum_factor_weight",
                       config.get("stock_selection.momentum_factor_weight", 0.50))
        )
        self.legacy_volume_weight = float(
            config.get("stock_selection.legacy_volume_factor_weight",
                       config.get("stock_selection.volume_factor_weight", 0.00))
        )
        self.legacy_fundamental_weight = float(
            config.get("stock_selection.legacy_fundamental_factor_weight",
                       config.get("stock_selection.fundamental_factor_weight", 0.00))
        )
        self.legacy_pullback_weight = float(
            config.get("stock_selection.legacy_pullback_factor_weight",
                       config.get("stock_selection.pullback_factor_weight", 0.05))
        )
        
        self.top_n = config.get("stock_selection.top_n", 20)
        self.min_score = config.get("stock_selection.min_score", 60.0)
        self.exclude_st = config.get("stock_selection.exclude_st", True)
        self.exclude_new = config.get("stock_selection.exclude_new", 60)
        self.prediction_period = int(config.get("stock_selection.prediction_period", 5))
        self.short_cycle_window = max(3, min(self.prediction_period, 5))
        self.min_avg_amount_20d = float(config.get("stock_selection.min_avg_amount_20d", 100000.0))
        self.max_recent_limit_up_count_20d = int(
            config.get("stock_selection.max_recent_limit_up_count_20d", 2)
        )
        self.max_recent_return_20d = float(config.get("stock_selection.max_recent_return_20d", 25.0))
        self.max_avg_amplitude_10d = float(config.get("stock_selection.max_avg_amplitude_10d", 6.5))
        self.max_latest_pct_chg = float(config.get("stock_selection.max_latest_pct_chg", 8.5))
        self.short_cycle_score_weight = float(
            config.get("stock_selection.short_cycle_score_weight", 0.16)
        )
        self.tradeability_penalty_weight = float(
            config.get("stock_selection.tradeability_penalty_weight", 0.18)
        )
        self.use_point_in_time_universe = bool(
            config.get("stock_selection.use_point_in_time_universe", True)
        )
        self.universe_max_stale_days = max(
            1, int(config.get("stock_selection.universe_max_stale_days", 10))
        )
        self.use_dynamic_tradeability_thresholds = bool(
            config.get("stock_selection.use_dynamic_tradeability_thresholds", True)
        )
        self.dynamic_liquidity_quantile = float(
            config.get("stock_selection.dynamic_liquidity_quantile", 0.35)
        )
        self.dynamic_limit_up_quantile = float(
            config.get("stock_selection.dynamic_limit_up_quantile", 0.80)
        )
        self.dynamic_recent_return_quantile = float(
            config.get("stock_selection.dynamic_recent_return_quantile", 0.85)
        )
        self.dynamic_amplitude_quantile = float(
            config.get("stock_selection.dynamic_amplitude_quantile", 0.80)
        )
        self.dynamic_latest_pct_chg_quantile = float(
            config.get("stock_selection.dynamic_latest_pct_chg_quantile", 0.90)
        )
        self.dynamic_threshold_min_ratio = float(
            config.get("stock_selection.dynamic_threshold_min_ratio", 0.70)
        )
        self.dynamic_threshold_max_ratio = float(
            config.get("stock_selection.dynamic_threshold_max_ratio", 1.40)
        )
        self.limit_up_threshold = float(config.get("stock_selection.limit_up_threshold", 9.7))
        self.strong_up_day_threshold = float(config.get("stock_selection.strong_up_day_threshold", 6.0))
        self.use_dynamic_industry_strength = bool(
            config.get("stock_selection.use_dynamic_industry_strength", True)
        )
        self.industry_lookback_days = max(
            3, int(config.get("stock_selection.industry_lookback_days", 5))
        )
        self.industry_min_stock_count = max(
            3, int(config.get("stock_selection.industry_min_stock_count", 8))
        )
        self.industry_cache_days = max(
            1, int(config.get("stock_selection.industry_cache_days", 1))
        )
        self.enhanced_market_guard_enabled = bool(
            config.get("stock_selection.enhanced_market_guard_enabled", False)
        )
        self.enhanced_market_guard_index_code = str(
            config.get("stock_selection.enhanced_market_guard_index_code", "000001.SH")
        )
        self.enhanced_market_guard_min_ret1 = float(
            config.get("stock_selection.enhanced_market_guard_min_ret1", 0.0)
        )
        self.enhanced_market_guard_min_ret3 = float(
            config.get("stock_selection.enhanced_market_guard_min_ret3", -0.005)
        )
        self.feedback_guard_enabled = bool(
            config.get("stock_selection.feedback_guard_enabled", True)
        )
        self.feedback_guard_min_score_boost_caution = float(
            config.get("stock_selection.feedback_guard_min_score_boost_caution", 2.0)
        )
        self.feedback_guard_min_score_boost_defensive = float(
            config.get("stock_selection.feedback_guard_min_score_boost_defensive", 4.0)
        )
        self.feedback_guard_top_n_multiplier_caution = float(
            config.get("stock_selection.feedback_guard_top_n_multiplier_caution", 0.90)
        )
        self.feedback_guard_top_n_multiplier_defensive = float(
            config.get("stock_selection.feedback_guard_top_n_multiplier_defensive", 0.70)
        )
        self.feedback_guard_min_avg_amount_multiplier_caution = float(
            config.get("stock_selection.feedback_guard_min_avg_amount_multiplier_caution", 1.10)
        )
        self.feedback_guard_min_avg_amount_multiplier_defensive = float(
            config.get("stock_selection.feedback_guard_min_avg_amount_multiplier_defensive", 1.25)
        )
        self.feedback_guard_max_return_multiplier_caution = float(
            config.get("stock_selection.feedback_guard_max_return_multiplier_caution", 0.92)
        )
        self.feedback_guard_max_return_multiplier_defensive = float(
            config.get("stock_selection.feedback_guard_max_return_multiplier_defensive", 0.82)
        )
        self.feedback_guard_max_amplitude_multiplier_caution = float(
            config.get("stock_selection.feedback_guard_max_amplitude_multiplier_caution", 0.92)
        )
        self.feedback_guard_max_amplitude_multiplier_defensive = float(
            config.get("stock_selection.feedback_guard_max_amplitude_multiplier_defensive", 0.82)
        )
        self.feedback_guard_max_latest_pct_multiplier_caution = float(
            config.get("stock_selection.feedback_guard_max_latest_pct_multiplier_caution", 0.95)
        )
        self.feedback_guard_max_latest_pct_multiplier_defensive = float(
            config.get("stock_selection.feedback_guard_max_latest_pct_multiplier_defensive", 0.85)
        )

        # 运行时行业热度缓存（按end_date维度）
        self._industry_strength_cache_date: Optional[str] = None
        self._industry_strength_map: Dict[str, Dict] = {}
        self._industry_strength_ranked: List[Dict] = []
        self._tradeability_threshold_cache_date: Optional[str] = None
        self._tradeability_threshold_cache: Dict[str, float] = {}
        
        # 行业分散配置
        self.max_per_industry = config.get("stock_selection.max_per_industry", 3)
        
        # 市场环境
        self.market_score = 50.0  # 默认中性市场
        
        # 是否保存因子值
        self.save_factor_values = config.get("stock_selection.save_factor_values", True)
        self.feedback_guard = FeedbackPerformanceGuard(config, db)
        
        # 自动优化系统（保留接口，legacy档不使用）
        self.enable_auto_optimization = False
        self.auto_optimizer = None
        self.optimized_weights = None

        logger.info(
            "股票选择器初始化完成（模式:%s, 自动优化:%s）",
            self.strategy_profile,
            self.enable_auto_optimization,
        )
    
    def _init_auto_optimization(self):
        """初始化自动优化系统"""
        try:
            self.auto_optimizer = FullyAutomaticOptimizationSystem(
                scheduled_interval_minutes=60,  # 选股每小时重优化一次
                consecutive_loss_threshold=5,
                drawdown_threshold=0.20
            )
            logger.info("选股自动优化系统初始化成功")
        except Exception as e:
            logger.error(f"选股自动优化系统初始化失败: {e}")
            self.enable_auto_optimization = False
            self.auto_optimizer = None
    
    def _normalize_weights(self, weights: Dict[str, float]) -> Dict[str, float]:
        """归一化权重，确保所有因子权重和为1。"""
        sanitized = {key: max(0.0, float(value)) for key, value in weights.items()}
        total_weight = sum(sanitized.values())

        if total_weight <= 0:
            factor_count = len(sanitized) or 1
            return {key: round(1.0 / factor_count, 4) for key in sanitized}

        return {
            key: round(value / total_weight, 4)
            for key, value in sanitized.items()
        }

    def _get_flat_enhanced_weights(self) -> Dict[str, float]:
        """兼容旧版平铺配置。"""
        return {
            factor_name: float(self.config.get(f"stock_selection.{config_key}", default_value))
            for factor_name, config_key, default_value in (
                ("trend", ENHANCED_WEIGHT_CONFIG_MAP["trend"], 0.35),
                ("momentum", ENHANCED_WEIGHT_CONFIG_MAP["momentum"], 0.30),
                ("volume", ENHANCED_WEIGHT_CONFIG_MAP["volume"], 0.05),
                ("fundamental", ENHANCED_WEIGHT_CONFIG_MAP["fundamental"], 0.05),
                ("pullback", ENHANCED_WEIGHT_CONFIG_MAP["pullback"], 0.15),
                ("quality", ENHANCED_WEIGHT_CONFIG_MAP["quality"], 0.10),
            )
        }

    def _coerce_enhanced_weight_profile(self, raw_profile: Dict) -> Dict[str, float]:
        """兼容 trend / trend_factor_weight 两种写法。"""
        if not isinstance(raw_profile, dict):
            return {}

        profile = {}
        for factor_name, config_key in ENHANCED_WEIGHT_CONFIG_MAP.items():
            value = raw_profile.get(factor_name, raw_profile.get(config_key))
            if value is None:
                continue
            profile[factor_name] = float(value)

        if len(profile) < len(ENHANCED_WEIGHT_CONFIG_MAP):
            flat_weights = self._get_flat_enhanced_weights()
            for factor_name, fallback in flat_weights.items():
                profile.setdefault(factor_name, float(fallback))

        return self._normalize_weights(profile)

    def _load_enhanced_weight_profiles(self) -> Dict[str, Dict[str, float]]:
        """加载命名权重档位，并保留对旧配置的兼容。"""
        profiles = {}
        raw_profiles = self.config.get("stock_selection.enhanced_weight_profiles", {}) or {}
        if isinstance(raw_profiles, dict):
            for profile_name, raw_profile in raw_profiles.items():
                normalized_name = str(profile_name).strip().lower()
                if not normalized_name:
                    continue
                normalized_profile = self._coerce_enhanced_weight_profile(raw_profile)
                if normalized_profile:
                    profiles[normalized_name] = normalized_profile

        profiles.setdefault("active", self._normalize_weights(self._get_flat_enhanced_weights()))
        return profiles

    def _resolve_enhanced_weight_profile(self) -> Tuple[str, Dict[str, float]]:
        """解析当前启用的增强权重档位。"""
        preferred = str(self.enhanced_weight_profile or "active").strip().lower()
        if preferred in self.enhanced_weight_profiles:
            return preferred, dict(self.enhanced_weight_profiles[preferred])
        if "active" in self.enhanced_weight_profiles:
            return "active", dict(self.enhanced_weight_profiles["active"])
        return "flat", self._normalize_weights(self._get_flat_enhanced_weights())

    def _apply_weights(self, weights: Dict[str, float]) -> Dict[str, float]:
        """应用并持久化当前权重到实例属性。"""
        normalized = self._normalize_weights(weights)
        self.trend_weight = normalized.get('trend', 0.0)
        self.momentum_weight = normalized.get('momentum', 0.0)
        self.volume_weight = normalized.get('volume', 0.0)
        self.fundamental_weight = normalized.get('fundamental', 0.0)
        self.pullback_weight = normalized.get('pullback', 0.0)
        self.quality_weight = normalized.get('quality', 0.0)
        return normalized

    def _get_default_weights(self) -> Dict:
        """获取默认权重"""
        return dict(getattr(self, "base_enhanced_weights", {
            'trend': self.trend_weight,
            'momentum': self.momentum_weight,
            'volume': self.volume_weight,
            'fundamental': self.fundamental_weight,
            'pullback': self.pullback_weight,
            'quality': self.quality_weight
        }))

    def get_enhanced_weight_profile_name(self) -> str:
        """返回当前增强权重档位名称。"""
        return str(self.enhanced_weight_profile or "active")

    def get_enhanced_weight_profiles(self) -> Dict[str, Dict[str, float]]:
        """返回全部命名权重档位。"""
        return {
            name: dict(weights)
            for name, weights in self.enhanced_weight_profiles.items()
        }

    def _get_legacy_weights(self) -> Dict[str, float]:
        """返回 legacy 因子权重，归一化确保总和为 1.0。"""
        raw = {
            "trend": float(self.legacy_trend_weight),
            "momentum": float(self.legacy_momentum_weight),
            "volume": float(self.legacy_volume_weight),
            "fundamental": float(self.legacy_fundamental_weight),
            "pullback": float(self.legacy_pullback_weight),
            "quality": 0.0,
        }
        return self._normalize_weights({k: v for k, v in raw.items() if k != "quality"})\
               | {"quality": 0.0}

    def _get_market_adaptive_weights(self) -> Dict[str, float]:
        """根据市场环境动态调整因子权重。"""
        adaptive = self._get_default_weights().copy()

        if self.market_score > 70:
            adaptive['trend'] *= 1.15
            adaptive['momentum'] *= 1.15
            adaptive['pullback'] *= 0.85
            adaptive['quality'] *= 0.95
        elif self.market_score < 40:
            adaptive['momentum'] *= 0.75
            adaptive['pullback'] *= 1.20
            adaptive['quality'] *= 1.20
            adaptive['fundamental'] *= 1.10
            adaptive['trend'] *= 0.95
        else:
            adaptive['pullback'] *= 1.05
            adaptive['quality'] *= 1.05

        return self._normalize_weights(adaptive)

    def _get_active_weights(self) -> Dict[str, float]:
        """返回当前生效权重：legacy 返回 5 因子；enhanced 返回命名档位。"""
        if self.strategy_profile == ENHANCED_PROFILE:
            name = self.get_enhanced_weight_profile_name()
            profile = self.get_enhanced_weight_profiles().get(name) or self.get_enhanced_weight_profiles().get("active")
            if profile:
                return self._normalize_weights(profile)
        return self._get_legacy_weights()

    def _use_legacy_profile(self) -> bool:
        """是否使用 legacy 档位。"""
        return self.strategy_profile == LEGACY_BASE_PROFILE

    def _evaluate_enhanced_market_guard(self, end_date: str) -> Dict[str, float]:
        """
        增强策略的市场状态防护检测。

        默认使用上证指数(000001.SH)的1日与3日收益判断市场是否允许开仓。
        """
        sql = """
            SELECT trade_date, close
            FROM stock_daily
            WHERE ts_code = ? AND trade_date <= ?
            ORDER BY trade_date DESC
            LIMIT 4
        """
        rows = self.db.query(sql, (self.enhanced_market_guard_index_code, end_date))
        if not rows or len(rows) < 4:
            return {
                "passed": True,
                "reason": "index_data_insufficient",
                "ret1": 0.0,
                "ret3": 0.0,
            }

        closes = [float(r.get("close", 0.0) or 0.0) for r in rows]
        if any(c <= 0 for c in closes):
            return {
                "passed": True,
                "reason": "index_price_invalid",
                "ret1": 0.0,
                "ret3": 0.0,
            }

        latest = closes[0]
        ret1 = latest / closes[1] - 1.0
        ret3 = latest / closes[3] - 1.0
        passed = ret1 >= self.enhanced_market_guard_min_ret1 and ret3 >= self.enhanced_market_guard_min_ret3
        return {
            "passed": bool(passed),
            "reason": "ok" if passed else "market_guard_blocked",
            "ret1": float(ret1),
            "ret3": float(ret3),
        }

    def optimize_factor_weights(self, historical_data: pd.DataFrame = None) -> Dict:
        """
        优化因子权重。

        优先使用市场自适应权重；如果提供了带目标收益列的历史数据，
        则按因子和未来收益的相关性进一步微调。
        """
        if self._use_legacy_profile():
            self.optimized_weights = self._get_legacy_weights()
            logger.info("%s档位启用5因子固定权重: %s", self.strategy_profile, self.optimized_weights)
            return self.optimized_weights

        adaptive_weights = self._get_market_adaptive_weights()
        factor_columns = {
            'trend': 'trend_score',
            'momentum': 'momentum_score',
            'volume': 'volume_score',
            'fundamental': 'fundamental_score',
            'pullback': 'pullback_score',
            'quality': 'quality_score'
        }
        target_candidates = ['forward_return', 'future_return', 'return', 'pnl_pct']

        try:
            if historical_data is None or historical_data.empty:
                self.optimized_weights = adaptive_weights
                return adaptive_weights

            target_col = next(
                (column for column in target_candidates if column in historical_data.columns),
                None
            )
            if not target_col:
                self.optimized_weights = adaptive_weights
                return adaptive_weights

            factor_strength = {}
            for factor_name, column_name in factor_columns.items():
                if column_name not in historical_data.columns:
                    continue

                sample = historical_data[[column_name, target_col]].dropna()
                if len(sample) < 20:
                    continue

                corr = sample[column_name].corr(sample[target_col])
                if pd.notna(corr):
                    factor_strength[factor_name] = abs(float(corr))

            if not factor_strength:
                self.optimized_weights = adaptive_weights
                return adaptive_weights

            correlation_weights = self._normalize_weights(factor_strength)
            blended_weights = {
                factor_name: adaptive_weights.get(factor_name, 0.0) * 0.6 +
                correlation_weights.get(factor_name, 0.0) * 0.4
                for factor_name in adaptive_weights
            }

            self.optimized_weights = self._normalize_weights(blended_weights)
            logger.info(f"因子权重优化完成: {self.optimized_weights}")
            return self.optimized_weights

        except Exception as e:
            logger.error(f"优化因子权重失败: {e}")
            self.optimized_weights = adaptive_weights
            return adaptive_weights
    
    def update_weights(self, weights: Dict):
        """
        更新因子权重
        
        Args:
            weights: 新权重
        """
        merged_weights = self._get_default_weights()
        merged_weights.update(weights)
        normalized = self._apply_weights(merged_weights)
        self.optimized_weights = normalized

        logger.info(f"因子权重已更新: {normalized}")

    @staticmethod
    def _normalize_date_value(value: object) -> Optional[str]:
        """将日期文本归一化为YYYYMMDD，无法识别时返回None。"""
        if value is None:
            return None
        raw = str(value).strip()
        if not raw or raw.lower() in {"none", "nan", "nat"}:
            return None
        digits = "".join(ch for ch in raw if ch.isdigit())
        if len(digits) < 8:
            return None
        return digits[:8]

    @staticmethod
    def _clamp_ratio(value: float, base: float, min_ratio: float, max_ratio: float) -> float:
        """按比例限制阈值漂移范围，避免参数在单日极端行情下失真。"""
        if base <= 0:
            return float(value)
        low = base * min(min_ratio, max_ratio)
        high = base * max(min_ratio, max_ratio)
        return float(min(max(value, low), high))

    @staticmethod
    def _clamp_quantile(value: float, fallback: float) -> float:
        """量化分位数参数安全钳制到[0.05, 0.95]。"""
        try:
            q = float(value)
        except Exception:
            q = fallback
        return float(min(max(q, 0.05), 0.95))

    def _get_static_tradeability_thresholds(self) -> Dict[str, float]:
        """返回配置中的静态交易性阈值。"""
        return {
            "min_avg_amount_20d": float(self.min_avg_amount_20d),
            "max_recent_limit_up_count_20d": int(self.max_recent_limit_up_count_20d),
            "max_recent_return_20d": float(self.max_recent_return_20d),
            "max_avg_amplitude_10d": float(self.max_avg_amplitude_10d),
            "max_latest_pct_chg": float(self.max_latest_pct_chg),
            "source": "static",
            "use_dynamic": False,
            "sample_size": 0,
            "end_date": None,
        }

    def _resolve_tradeability_thresholds(
        self,
        dynamic_thresholds: Optional[Dict],
    ) -> Dict[str, float]:
        """合并动态阈值与静态阈值，保证评估逻辑稳定。"""
        resolved = self._get_static_tradeability_thresholds()
        if not dynamic_thresholds:
            return resolved

        for key in (
            "min_avg_amount_20d",
            "max_recent_return_20d",
            "max_avg_amplitude_10d",
            "max_latest_pct_chg",
        ):
            if key in dynamic_thresholds and dynamic_thresholds[key] is not None:
                try:
                    resolved[key] = float(dynamic_thresholds[key])
                except Exception:
                    pass

        if (
            "max_recent_limit_up_count_20d" in dynamic_thresholds
            and dynamic_thresholds["max_recent_limit_up_count_20d"] is not None
        ):
            try:
                resolved["max_recent_limit_up_count_20d"] = max(
                    1, int(dynamic_thresholds["max_recent_limit_up_count_20d"])
                )
            except Exception:
                pass

        resolved["source"] = str(dynamic_thresholds.get("source", "dynamic"))
        resolved["use_dynamic"] = bool(dynamic_thresholds.get("use_dynamic", True))
        resolved["sample_size"] = int(dynamic_thresholds.get("sample_size", 0))
        resolved["end_date"] = dynamic_thresholds.get("end_date")
        return resolved

    def _apply_feedback_guard_to_thresholds(
        self,
        thresholds: Optional[Dict[str, Any]],
        guard_level: str,
    ) -> Dict[str, Any]:
        """按闭环闸门档位收紧交易性阈值。"""
        base = self._resolve_tradeability_thresholds(thresholds or {})
        level = str(guard_level or "normal").lower()
        if level not in {"caution", "defensive"}:
            return base

        if level == "defensive":
            amount_mult = self.feedback_guard_min_avg_amount_multiplier_defensive
            return_mult = self.feedback_guard_max_return_multiplier_defensive
            amp_mult = self.feedback_guard_max_amplitude_multiplier_defensive
            latest_mult = self.feedback_guard_max_latest_pct_multiplier_defensive
        else:
            amount_mult = self.feedback_guard_min_avg_amount_multiplier_caution
            return_mult = self.feedback_guard_max_return_multiplier_caution
            amp_mult = self.feedback_guard_max_amplitude_multiplier_caution
            latest_mult = self.feedback_guard_max_latest_pct_multiplier_caution

        adjusted = dict(base)
        adjusted["min_avg_amount_20d"] = float(
            max(1.0, float(base.get("min_avg_amount_20d", self.min_avg_amount_20d)) * max(1.0, amount_mult))
        )
        adjusted["max_recent_return_20d"] = float(
            max(5.0, float(base.get("max_recent_return_20d", self.max_recent_return_20d)) * min(1.0, return_mult))
        )
        adjusted["max_avg_amplitude_10d"] = float(
            max(2.5, float(base.get("max_avg_amplitude_10d", self.max_avg_amplitude_10d)) * min(1.0, amp_mult))
        )
        adjusted["max_latest_pct_chg"] = float(
            max(3.5, float(base.get("max_latest_pct_chg", self.max_latest_pct_chg)) * min(1.0, latest_mult))
        )
        adjusted["source"] = f"{base.get('source', 'dynamic')}+feedback_guard_{level}"
        adjusted["feedback_guard_level"] = level
        return adjusted

    def _get_feedback_guard_profile(self, end_date: str) -> Dict[str, Any]:
        """评估闭环防护档位，并生成选股侧执行参数。"""
        default_profile = {
            "enabled": False,
            "level": "normal",
            "active": False,
            "reason": "",
            "effective_min_score": float(self.min_score),
            "effective_top_n": int(self.top_n),
            "raw_state": {},
        }
        if not self.feedback_guard_enabled:
            return default_profile

        try:
            state = self.feedback_guard.evaluate(end_date=end_date)
            level = str(state.get("level", "normal")).lower()
            effective_min_score = float(self.min_score)
            effective_top_n = int(self.top_n)

            if level == "defensive":
                effective_min_score += self.feedback_guard_min_score_boost_defensive
                effective_top_n = max(3, int(round(self.top_n * self.feedback_guard_top_n_multiplier_defensive)))
            elif level == "caution":
                effective_min_score += self.feedback_guard_min_score_boost_caution
                effective_top_n = max(5, int(round(self.top_n * self.feedback_guard_top_n_multiplier_caution)))

            return {
                "enabled": True,
                "level": level,
                "active": level in {"caution", "defensive"},
                "reason": str(state.get("reason", "")),
                "effective_min_score": float(effective_min_score),
                "effective_top_n": int(max(1, effective_top_n)),
                "raw_state": state,
            }
        except Exception as e:
            logger.warning("闭环防护评估失败，回退normal: %s", e)
            return default_profile

    def _build_point_in_time_stock_list(self, end_date: str) -> pd.DataFrame:
        """
        构建时点股票池（降低生存者偏差）。

        说明：仅保留在end_date之前仍有交易记录、且最近交易不陈旧的主板股票。
        """
        end_dt = datetime.strptime(end_date, "%Y%m%d")
        stale_cutoff = (end_dt - timedelta(days=self.universe_max_stale_days)).strftime("%Y%m%d")
        sql = """
            SELECT
                d.ts_code,
                b.symbol,
                b.name,
                b.industry,
                b.list_date,
                MAX(d.trade_date) AS latest_trade_date,
                MIN(d.trade_date) AS first_trade_date,
                COUNT(1) AS trade_days
            FROM stock_daily d
            JOIN stock_basic b ON d.ts_code = b.ts_code
            WHERE d.trade_date <= ?
              AND (
                    d.ts_code LIKE '600%.SH' OR d.ts_code LIKE '601%.SH'
                 OR d.ts_code LIKE '603%.SH' OR d.ts_code LIKE '605%.SH'
                 OR d.ts_code LIKE '000%.SZ' OR d.ts_code LIKE '001%.SZ'
                 OR d.ts_code LIKE '002%.SZ' OR d.ts_code LIKE '003%.SZ'
              )
            GROUP BY d.ts_code, b.symbol, b.name, b.industry, b.list_date
            HAVING MAX(d.trade_date) >= ?
        """
        rows = self.db.query(sql, (end_date, stale_cutoff))
        if not rows:
            return pd.DataFrame()

        df = pd.DataFrame(rows)
        if "list_date" in df.columns:
            normalized = df["list_date"].apply(self._normalize_date_value)
            df = df[normalized.isna() | (normalized <= end_date)]
        return df.reset_index(drop=True)

    def get_stock_list(self, end_date: str = None, point_in_time: bool = True) -> pd.DataFrame:
        """
        获取股票基础列表。

        Args:
            end_date: 结束日期（YYYYMMDD）
            point_in_time: 是否按时点构建股票池

        Returns:
            股票列表DataFrame
        """
        resolved_end_date = self._resolve_end_date(end_date)
        use_point_in_time = bool(point_in_time and self.use_point_in_time_universe)
        if use_point_in_time:
            df = self._build_point_in_time_stock_list(resolved_end_date)
            if not df.empty:
                return df
            logger.warning("时点股票池为空，回退到stock_basic全量股票池")

        sql = "SELECT ts_code, symbol, name, industry, list_date FROM stock_basic"
        results = self.db.query(sql)

        if not results:
            logger.warning("股票基础信息表为空")
            return pd.DataFrame()

        return pd.DataFrame(results)
    
    def filter_basic(self, stock_list: pd.DataFrame, end_date: str = None) -> pd.DataFrame:
        """
        基本面初筛
        
        Args:
            stock_list: 股票列表
        
        Returns:
            筛选后的股票列表
        """
        if stock_list.empty:
            return stock_list
        end_date = self._resolve_end_date(end_date)
        original_count = len(stock_list)
        
        # 排除ST股票
        if self.exclude_st:
            stock_list = stock_list[~stock_list['name'].str.contains('ST|st|退', na=False)]
        
        # 排除新股
        if self.exclude_new > 0:
            end_dt = datetime.strptime(end_date, "%Y%m%d")
            min_list_date = (end_dt - timedelta(days=self.exclude_new)).strftime("%Y%m%d")
            normalized_list_date = stock_list["list_date"].apply(self._normalize_date_value)
            stock_list = stock_list[
                normalized_list_date.isna() | (normalized_list_date < min_list_date)
            ]
        
        # 只保留沪深主板股票
        # 沪市主板: 600xxx, 601xxx, 603xxx, 605xxx (SH)
        # 深市主板: 000xxx, 001xxx, 002xxx, 003xxx (SZ)
        # 排除:
        #   - 创业板: 300xxx, 301xxx (SZ)
        #   - 科创板: 688xxx (SH)
        #   - 北交所: 8xxxxx, 4xxxxx
        
        def is_main_board(ts_code: str) -> bool:
            """判断是否为主板股票"""
            if '.' not in ts_code:
                return False
            
            code, market = ts_code.split('.')
            
            # 沪市主板: 600, 601, 603, 605 开头
            if market == 'SH':
                if code.startswith(('600', '601', '603', '605')):
                    return True
                return False
            
            # 深市主板: 000, 001, 002, 003 开头
            if market == 'SZ':
                if code.startswith(('000', '001', '002', '003')):
                    return True
                return False
            
            return False
        
        stock_list = stock_list[stock_list['ts_code'].apply(is_main_board)]
        
        filtered_count = len(stock_list)
        logger.info(
            "基本面初筛(%s): %d -> %d只股票（仅沪深主板）",
            end_date,
            original_count,
            filtered_count,
        )
        
        return stock_list
    
    def get_stock_daily_data(self, ts_code: str, days: int = 120, end_date: str = None) -> pd.DataFrame:
        """
        获取个股日线数据
        
        Args:
            ts_code: 股票代码
            days: 获取天数
            end_date: 结束日期（YYYYMMDD格式），默认为当天
        
        Returns:
            日线数据DataFrame
        """
        if end_date is None:
            end_date = datetime.now().strftime("%Y%m%d")
        
        # 计算开始日期
        end_dt = datetime.strptime(end_date, "%Y%m%d")
        start_date = (end_dt - timedelta(days=days * 2)).strftime("%Y%m%d")
        
        sql = """
            SELECT trade_date, open, close, high, low, vol, amount, pct_chg
            FROM stock_daily
            WHERE ts_code = ? AND trade_date >= ? AND trade_date <= ?
            ORDER BY trade_date DESC
        """
        
        results = self.db.query(sql, (ts_code, start_date, end_date))
        
        if not results:
            return pd.DataFrame()
        
        df = pd.DataFrame(results)
        # 处理日期格式
        try:
            if len(str(df['trade_date'].iloc[0])) == 8:
                df['trade_date'] = pd.to_datetime(df['trade_date'], format='%Y%m%d')
            else:
                df['trade_date'] = pd.to_datetime(df['trade_date'])
        except:
            df['trade_date'] = pd.to_datetime(df['trade_date'])
        df = df.sort_values('trade_date').reset_index(drop=True)
        
        if len(df) > days:
            df = df.tail(days)
        
        return df
    
    def calculate_ma(self, prices: pd.Series, window: int) -> pd.Series:
        """计算移动平均线"""
        return prices.rolling(window=window).mean()

    @staticmethod
    def _clamp_score(score: float, low: float = 0.0, high: float = 100.0) -> float:
        """限制评分范围，避免极端值放大排序偏差。"""
        return float(min(max(score, low), high))

    @staticmethod
    def _window_return(close: pd.Series, periods: int) -> float:
        """计算指定窗口收益率。"""
        periods = max(int(periods), 1)
        if len(close) <= periods:
            return 0.0

        base_price = float(close.iloc[-periods - 1])
        latest_price = float(close.iloc[-1])
        if base_price <= 0:
            return 0.0

        return (latest_price / base_price - 1) * 100

    def _resolve_end_date(self, end_date: str = None) -> str:
        """将日期标准化为YYYYMMDD字符串。"""
        if end_date:
            return str(end_date)
        return datetime.now().strftime("%Y%m%d")

    def _resolve_selection_end_date(self, end_date: str = None) -> str:
        """
        解析盘前选股使用的交易日锚点。

        规则：
        1. 默认使用 stock_daily 最新交易日（避免盘前使用“今天”造成未来信息偏差）。
        2. 若显式传入 end_date 且晚于最新交易日，则回退到最新交易日并告警。
        3. 若数据库无交易日，则回退到 _resolve_end_date。
        """
        requested = self._normalize_date_value(end_date) if end_date else None
        latest_trade_date = self.db.get_latest_trade_date("stock_daily")
        latest = self._normalize_date_value(latest_trade_date) if latest_trade_date else None

        if not latest:
            return self._resolve_end_date(end_date)

        if not requested:
            return latest

        if requested > latest:
            logger.warning(
                "选股end_date=%s晚于最新交易日%s，已回退到%s",
                requested,
                latest,
                latest,
            )
            return latest

        return requested

    @staticmethod
    def _is_main_board_symbol(ts_code: str) -> bool:
        """判断是否属于沪深主板股票。"""
        if not ts_code or "." not in ts_code:
            return False
        code, market = ts_code.split(".")
        if market == "SH":
            return code.startswith(("600", "601", "603", "605"))
        if market == "SZ":
            return code.startswith(("000", "001", "002", "003"))
        return False

    def _industry_heat_level(self, heat_score: float) -> str:
        """将行业热度分映射为等级标签。"""
        if heat_score >= 80:
            return "hot"
        if heat_score >= 65:
            return "warm"
        if heat_score >= 50:
            return "neutral"
        if heat_score >= 35:
            return "cool"
        return "cold"

    def _prepare_dynamic_industry_strength(self, end_date: str = None) -> Dict[str, Dict]:
        """
        预计算盘前行业强弱（基于本地历史库，截止到end_date）。

        说明：盘前没有当天完整行情，因此使用历史截至日做行业热度预估。
        """
        if not self.use_dynamic_industry_strength:
            return {}

        end_date = self._resolve_end_date(end_date)
        if self._industry_strength_cache_date and self._industry_strength_map:
            if self._industry_strength_cache_date == end_date:
                return self._industry_strength_map

            if self.industry_cache_days > 1:
                cache_dt = datetime.strptime(self._industry_strength_cache_date, "%Y%m%d")
                end_dt = datetime.strptime(end_date, "%Y%m%d")
                if abs((end_dt - cache_dt).days) < self.industry_cache_days:
                    return self._industry_strength_map

        end_dt = datetime.strptime(end_date, "%Y%m%d")
        start_date = (end_dt - timedelta(days=max(self.industry_lookback_days * 12, 60))).strftime("%Y%m%d")

        sql = """
            SELECT d.ts_code, d.trade_date, d.close, d.amount, d.pct_chg, b.industry
            FROM stock_daily d
            JOIN stock_basic b ON d.ts_code = b.ts_code
            WHERE d.trade_date >= ? AND d.trade_date <= ?
              AND b.industry IS NOT NULL AND b.industry != ''
              AND (
                    d.ts_code LIKE '600%.SH' OR d.ts_code LIKE '601%.SH'
                 OR d.ts_code LIKE '603%.SH' OR d.ts_code LIKE '605%.SH'
                 OR d.ts_code LIKE '000%.SZ' OR d.ts_code LIKE '001%.SZ'
                 OR d.ts_code LIKE '002%.SZ' OR d.ts_code LIKE '003%.SZ'
              )
            ORDER BY d.ts_code ASC, d.trade_date ASC
        """
        rows = self.db.query(sql, (start_date, end_date))
        if not rows:
            self._industry_strength_cache_date = end_date
            self._industry_strength_map = {}
            self._industry_strength_ranked = []
            logger.warning("动态行业热度计算无数据，回退到中性行业评分")
            return {}

        df = pd.DataFrame(rows)
        if df.empty:
            self._industry_strength_cache_date = end_date
            self._industry_strength_map = {}
            self._industry_strength_ranked = []
            return {}

        df["close"] = pd.to_numeric(df["close"], errors="coerce")
        df["amount"] = pd.to_numeric(df["amount"], errors="coerce").fillna(0.0)
        df["pct_chg"] = pd.to_numeric(df["pct_chg"], errors="coerce").fillna(0.0)
        df = df.dropna(subset=["close"])

        lookback = max(self.industry_lookback_days, 5)
        stock_metrics = []
        for ts_code, g in df.groupby("ts_code"):
            if not self._is_main_board_symbol(ts_code):
                continue
            g = g.sort_values("trade_date")
            if len(g) < max(lookback + 2, 12):
                continue

            close = g["close"].replace(0, np.nan).ffill().bfill()
            amount = g["amount"].fillna(0.0)
            pct = g["pct_chg"].fillna(0.0)
            industry = str(g["industry"].iloc[-1]).strip()
            if not industry:
                continue

            ret_1 = float(pct.iloc[-1])
            ret_3 = self._window_return(close, min(3, len(close) - 1))
            ret_5 = self._window_return(close, min(5, len(close) - 1))
            ret_lb = self._window_return(close, min(lookback, len(close) - 1))

            recent_amount = float(amount.tail(lookback).mean())
            prev_amount = float(
                amount.iloc[-lookback * 2:-lookback].mean()
                if len(amount) >= lookback * 2
                else amount.head(lookback).mean()
            )
            amount_ratio = recent_amount / prev_amount if prev_amount > 0 else 1.0

            limit_up_days = int((pct.tail(lookback) >= self.limit_up_threshold).sum())
            stock_metrics.append(
                {
                    "ts_code": ts_code,
                    "industry": industry,
                    "ret_1": ret_1,
                    "ret_3": ret_3,
                    "ret_5": ret_5,
                    "ret_lb": ret_lb,
                    "amount_ratio": amount_ratio,
                    "up_today": 1.0 if ret_1 > 0 else 0.0,
                    "up_lb": 1.0 if ret_lb > 0 else 0.0,
                    "active_limit_up": 1.0 if limit_up_days > 0 else 0.0,
                }
            )

        stock_df = pd.DataFrame(stock_metrics)
        if stock_df.empty:
            self._industry_strength_cache_date = end_date
            self._industry_strength_map = {}
            self._industry_strength_ranked = []
            logger.warning("动态行业热度计算样本不足，回退到中性行业评分")
            return {}

        industry_df = (
            stock_df.groupby("industry")
            .agg(
                stock_count=("ts_code", "count"),
                avg_ret_1=("ret_1", "mean"),
                avg_ret_3=("ret_3", "mean"),
                avg_ret_5=("ret_5", "mean"),
                avg_ret_lb=("ret_lb", "mean"),
                breadth_today=("up_today", "mean"),
                breadth_lb=("up_lb", "mean"),
                avg_amount_ratio=("amount_ratio", "mean"),
                limit_up_ratio=("active_limit_up", "mean"),
            )
            .reset_index()
        )
        if industry_df.empty:
            self._industry_strength_cache_date = end_date
            self._industry_strength_map = {}
            self._industry_strength_ranked = []
            return {}

        industry_df["momentum_rank"] = (
            industry_df["avg_ret_3"].rank(pct=True) * 0.4
            + industry_df["avg_ret_5"].rank(pct=True) * 0.4
            + industry_df["avg_ret_lb"].rank(pct=True) * 0.2
        )
        industry_df["breadth_rank"] = (
            industry_df["breadth_today"].rank(pct=True) * 0.65
            + industry_df["breadth_lb"].rank(pct=True) * 0.35
        )
        industry_df["liquidity_rank"] = industry_df["avg_amount_ratio"].rank(pct=True)
        industry_df["leadership_rank"] = industry_df["limit_up_ratio"].rank(pct=True)

        industry_df["raw_heat_score"] = (
            industry_df["momentum_rank"] * 45
            + industry_df["breadth_rank"] * 30
            + industry_df["liquidity_rank"] * 15
            + industry_df["leadership_rank"] * 10
        )

        # 对样本过小行业降权，降低偶然性噪声。
        small_group = industry_df["stock_count"] < self.industry_min_stock_count
        if small_group.any():
            penalty = (self.industry_min_stock_count - industry_df.loc[small_group, "stock_count"]).clip(lower=0)
            industry_df.loc[small_group, "raw_heat_score"] -= penalty * 1.2

        industry_df["heat_score"] = industry_df["raw_heat_score"].clip(lower=0, upper=100).round(2)
        industry_df = industry_df.sort_values("heat_score", ascending=False).reset_index(drop=True)
        industry_df["rank"] = np.arange(1, len(industry_df) + 1)
        industry_df["heat_level"] = industry_df["heat_score"].apply(self._industry_heat_level)

        strength_map = {}
        ranked_rows = []
        for row in industry_df.to_dict("records"):
            info = {
                "industry": row["industry"],
                "heat_score": float(row["heat_score"]),
                "heat_level": row["heat_level"],
                "rank": int(row["rank"]),
                "stock_count": int(row["stock_count"]),
                "avg_ret_1": round(float(row["avg_ret_1"]), 2),
                "avg_ret_3": round(float(row["avg_ret_3"]), 2),
                "avg_ret_5": round(float(row["avg_ret_5"]), 2),
                "avg_ret_lb": round(float(row["avg_ret_lb"]), 2),
                "breadth_today": round(float(row["breadth_today"]), 3),
                "breadth_lb": round(float(row["breadth_lb"]), 3),
                "avg_amount_ratio": round(float(row["avg_amount_ratio"]), 3),
                "limit_up_ratio": round(float(row["limit_up_ratio"]), 3),
            }
            strength_map[row["industry"]] = info
            ranked_rows.append(info)

        self._industry_strength_cache_date = end_date
        self._industry_strength_map = strength_map
        self._industry_strength_ranked = ranked_rows
        return strength_map

    def get_dynamic_industry_strength(self, end_date: str = None, top_n: int = 10) -> List[Dict]:
        """获取动态行业强弱快照，供报告/调试使用。"""
        if not self.use_dynamic_industry_strength:
            return []
        self._prepare_dynamic_industry_strength(end_date=end_date)
        return self._industry_strength_ranked[: max(1, int(top_n))]

    def _compute_dynamic_tradeability_thresholds(self, end_date: str = None) -> Dict[str, float]:
        """根据真实历史分布生成盘前动态交易性阈值。"""
        resolved_end_date = self._resolve_end_date(end_date)
        if (
            self._tradeability_threshold_cache_date == resolved_end_date
            and self._tradeability_threshold_cache
        ):
            return self._tradeability_threshold_cache

        static_thresholds = self._get_static_tradeability_thresholds()
        static_thresholds["end_date"] = resolved_end_date

        if not self.use_dynamic_tradeability_thresholds:
            static_thresholds["source"] = "static_disabled"
            self._tradeability_threshold_cache_date = resolved_end_date
            self._tradeability_threshold_cache = static_thresholds
            return static_thresholds

        end_dt = datetime.strptime(resolved_end_date, "%Y%m%d")
        start_date = (end_dt - timedelta(days=160)).strftime("%Y%m%d")
        sql = """
            SELECT ts_code, trade_date, close, high, low, amount, pct_chg
            FROM stock_daily
            WHERE trade_date >= ? AND trade_date <= ?
              AND (
                    ts_code LIKE '600%.SH' OR ts_code LIKE '601%.SH'
                 OR ts_code LIKE '603%.SH' OR ts_code LIKE '605%.SH'
                 OR ts_code LIKE '000%.SZ' OR ts_code LIKE '001%.SZ'
                 OR ts_code LIKE '002%.SZ' OR ts_code LIKE '003%.SZ'
              )
            ORDER BY ts_code ASC, trade_date ASC
        """
        rows = self.db.query(sql, (start_date, resolved_end_date))
        if not rows:
            static_thresholds["source"] = "static_fallback_no_data"
            self._tradeability_threshold_cache_date = resolved_end_date
            self._tradeability_threshold_cache = static_thresholds
            return static_thresholds

        raw = pd.DataFrame(rows)
        if raw.empty:
            static_thresholds["source"] = "static_fallback_no_data"
            self._tradeability_threshold_cache_date = resolved_end_date
            self._tradeability_threshold_cache = static_thresholds
            return static_thresholds

        raw["close"] = pd.to_numeric(raw["close"], errors="coerce")
        raw["high"] = pd.to_numeric(raw["high"], errors="coerce")
        raw["low"] = pd.to_numeric(raw["low"], errors="coerce")
        raw["amount"] = pd.to_numeric(raw["amount"], errors="coerce").fillna(0.0)
        raw["pct_chg"] = pd.to_numeric(raw["pct_chg"], errors="coerce").fillna(0.0)
        raw = raw.dropna(subset=["close"])
        if raw.empty:
            static_thresholds["source"] = "static_fallback_no_data"
            self._tradeability_threshold_cache_date = resolved_end_date
            self._tradeability_threshold_cache = static_thresholds
            return static_thresholds

        metrics = []
        for _, g in raw.groupby("ts_code"):
            if len(g) < 25:
                continue
            close = g["close"].replace(0, np.nan).ffill().bfill()
            if close.empty:
                continue
            high = g["high"].fillna(close)
            low = g["low"].fillna(close)
            amount = g["amount"].fillna(0.0)
            pct = g["pct_chg"].fillna(0.0)

            avg_amount_20 = float(amount.tail(20).mean())
            return_20 = self._window_return(close, min(20, max(len(close) - 1, 1)))
            limit_up_days_20 = int((pct.tail(20) >= self.limit_up_threshold).sum())
            latest_pct_chg = float(pct.iloc[-1])
            prev_close = close.shift(1).replace(0, np.nan)
            amplitude = (((high - low) / prev_close) * 100).replace([np.inf, -np.inf], np.nan)
            avg_amplitude_10 = (
                float(amplitude.tail(10).dropna().mean())
                if amplitude.tail(10).notna().any()
                else 0.0
            )
            metrics.append(
                {
                    "avg_amount_20": avg_amount_20,
                    "return_20": return_20,
                    "limit_up_days_20": limit_up_days_20,
                    "avg_amplitude_10": avg_amplitude_10,
                    "latest_pct_chg": latest_pct_chg,
                }
            )

        metrics_df = pd.DataFrame(metrics)
        if metrics_df.empty or len(metrics_df) < 80:
            static_thresholds["source"] = "static_fallback_sample_small"
            static_thresholds["sample_size"] = int(len(metrics_df))
            self._tradeability_threshold_cache_date = resolved_end_date
            self._tradeability_threshold_cache = static_thresholds
            return static_thresholds

        def q(series_name: str, quantile_value: float, default: float) -> float:
            series = pd.to_numeric(metrics_df[series_name], errors="coerce").dropna()
            if series.empty:
                return float(default)
            q_value = self._clamp_quantile(quantile_value, 0.5)
            return float(series.quantile(q_value))

        min_ratio = max(0.3, float(self.dynamic_threshold_min_ratio))
        max_ratio = max(min_ratio, float(self.dynamic_threshold_max_ratio))

        liquidity_candidate = q("avg_amount_20", self.dynamic_liquidity_quantile, self.min_avg_amount_20d)
        min_avg_amount_20d = self._clamp_ratio(
            liquidity_candidate,
            self.min_avg_amount_20d,
            min_ratio,
            max_ratio,
        )

        return_candidate = q("return_20", self.dynamic_recent_return_quantile, self.max_recent_return_20d)
        max_recent_return_20d = self._clamp_ratio(
            return_candidate,
            self.max_recent_return_20d,
            min_ratio,
            max_ratio,
        )
        max_recent_return_20d = max(8.0, max_recent_return_20d)

        amplitude_candidate = q("avg_amplitude_10", self.dynamic_amplitude_quantile, self.max_avg_amplitude_10d)
        max_avg_amplitude_10d = self._clamp_ratio(
            amplitude_candidate,
            self.max_avg_amplitude_10d,
            min_ratio,
            max_ratio,
        )
        max_avg_amplitude_10d = max(3.0, max_avg_amplitude_10d)

        latest_pct_candidate = q(
            "latest_pct_chg",
            self.dynamic_latest_pct_chg_quantile,
            self.max_latest_pct_chg,
        )
        max_latest_pct_chg = self._clamp_ratio(
            latest_pct_candidate,
            self.max_latest_pct_chg,
            min_ratio,
            max_ratio,
        )
        max_latest_pct_chg = max(4.0, max_latest_pct_chg)

        limit_up_candidate = q(
            "limit_up_days_20",
            self.dynamic_limit_up_quantile,
            self.max_recent_limit_up_count_20d,
        )
        lower_limit = max(1, self.max_recent_limit_up_count_20d - 1)
        upper_limit = self.max_recent_limit_up_count_20d + 2
        max_recent_limit_up_count_20d = int(round(limit_up_candidate))
        max_recent_limit_up_count_20d = int(
            min(max(max_recent_limit_up_count_20d, lower_limit), upper_limit)
        )

        dynamic_thresholds = {
            "min_avg_amount_20d": float(round(min_avg_amount_20d, 2)),
            "max_recent_limit_up_count_20d": int(max_recent_limit_up_count_20d),
            "max_recent_return_20d": float(round(max_recent_return_20d, 2)),
            "max_avg_amplitude_10d": float(round(max_avg_amplitude_10d, 2)),
            "max_latest_pct_chg": float(round(max_latest_pct_chg, 2)),
            "source": "dynamic",
            "use_dynamic": True,
            "sample_size": int(len(metrics_df)),
            "end_date": resolved_end_date,
        }
        self._tradeability_threshold_cache_date = resolved_end_date
        self._tradeability_threshold_cache = dynamic_thresholds
        return dynamic_thresholds

    def get_tradeability_thresholds(self, end_date: str = None) -> Dict[str, float]:
        """对外暴露当前选股所用的交易性门槛。"""
        return self._compute_dynamic_tradeability_thresholds(end_date=end_date)

    def assess_tradeability(
        self,
        df: pd.DataFrame,
        dynamic_thresholds: Optional[Dict] = None,
    ) -> Dict:
        """
        评估主板短线票的可交易性。

        盘前先过滤流动性不足、近期过热、振幅过大的标的，再进入因子评分。
        """
        thresholds = self._resolve_tradeability_thresholds(dynamic_thresholds)
        if df.empty or len(df) < 20:
            return {
                "is_tradeable": False,
                "filters": {
                    "liquidity_pass": False,
                    "limit_up_pass": False,
                    "recent_return_pass": False,
                    "amplitude_pass": False,
                },
                "blocked_reasons": ["历史数据不足"],
                "tradeability_score": 0.0,
                "risk_penalty": 10.0,
                "risk_tags": ["历史数据不足"],
                "applied_thresholds": thresholds,
            }

        close = pd.to_numeric(df["close"], errors="coerce").replace(0, np.nan).ffill().bfill()
        high = pd.to_numeric(df["high"], errors="coerce").fillna(close)
        low = pd.to_numeric(df["low"], errors="coerce").fillna(close)
        amount = pd.to_numeric(df["amount"], errors="coerce").fillna(0.0)
        pct_chg = pd.to_numeric(df["pct_chg"], errors="coerce").fillna(0.0)

        latest_close = float(close.iloc[-1]) if not close.empty else 0.0
        prev_close = close.shift(1).replace(0, np.nan)
        amplitude = (((high - low) / prev_close) * 100).replace([np.inf, -np.inf], np.nan)

        avg_amount_20 = float(amount.tail(20).mean())
        median_amount_20 = float(amount.tail(20).median())
        recent_amount_5 = float(amount.tail(5).mean()) if len(amount) >= 5 else float(amount.mean())
        amount_cv_20 = float(amount.tail(20).std() / avg_amount_20) if avg_amount_20 > 0 else 9.99
        amount_ratio_5_20 = recent_amount_5 / avg_amount_20 if avg_amount_20 > 0 else 0.0

        return_5 = self._window_return(close, self.short_cycle_window)
        return_10 = self._window_return(close, min(10, max(len(close) - 1, 1)))
        return_20 = self._window_return(close, min(20, max(len(close) - 1, 1)))

        latest_pct_chg = float(pct_chg.iloc[-1])
        limit_up_days_20 = int((pct_chg.tail(20) >= self.limit_up_threshold).sum())
        strong_up_days_10 = int((pct_chg.tail(10) >= self.strong_up_day_threshold).sum())
        down_shock_days_10 = int((pct_chg.tail(10) <= -6.0).sum())
        avg_amplitude_10 = float(amplitude.tail(10).dropna().mean()) if amplitude.tail(10).notna().any() else 0.0

        high_20 = float(high.tail(20).max()) if not high.tail(20).empty else 0.0
        pullback_from_high = ((high_20 - latest_close) / high_20 * 100) if high_20 > 0 else 0.0
        close_to_20d_high = (latest_close / high_20) if high_20 > 0 else 0.0
        one_word_limit_up_days_20 = int(
            (
                (pct_chg.tail(20) >= self.limit_up_threshold)
                & ((high.tail(20) - low.tail(20)).abs() <= (close.tail(20).abs() * 0.0015))
            ).sum()
        )

        min_avg_amount_20d = float(thresholds["min_avg_amount_20d"])
        max_recent_limit_up_count_20d = int(thresholds["max_recent_limit_up_count_20d"])
        max_recent_return_20d = float(thresholds["max_recent_return_20d"])
        max_avg_amplitude_10d = float(thresholds["max_avg_amplitude_10d"])
        max_latest_pct_chg = float(thresholds["max_latest_pct_chg"])

        filters = {
            "liquidity_pass": avg_amount_20 >= min_avg_amount_20d,
            "limit_up_pass": limit_up_days_20 <= max_recent_limit_up_count_20d,
            "recent_return_pass": return_20 <= max_recent_return_20d,
            "amplitude_pass": avg_amplitude_10 <= max_avg_amplitude_10d,
        }

        liquidity_ratio = avg_amount_20 / max(min_avg_amount_20d, 1.0)
        if liquidity_ratio >= 3.5:
            liquidity_score = 34
        elif liquidity_ratio >= 2.5:
            liquidity_score = 30
        elif liquidity_ratio >= 1.8:
            liquidity_score = 26
        elif liquidity_ratio >= 1.2:
            liquidity_score = 22
        elif liquidity_ratio >= 1.0:
            liquidity_score = 18
        else:
            liquidity_score = 8

        if amount_ratio_5_20 >= 1.15:
            liquidity_score += 4
        elif amount_ratio_5_20 >= 0.90:
            liquidity_score += 2
        elif amount_ratio_5_20 < 0.65:
            liquidity_score -= 6
        elif amount_ratio_5_20 < 0.80:
            liquidity_score -= 3

        if amount_cv_20 > 1.4:
            liquidity_score -= 7
        elif amount_cv_20 > 1.1:
            liquidity_score -= 5
        elif amount_cv_20 > 0.85:
            liquidity_score -= 3
        elif amount_cv_20 < 0.35:
            liquidity_score += 2

        if 2.0 <= return_20 <= 15.0:
            heat_score = 14
        elif 0.0 <= return_20 < 2.0 or 15.0 < return_20 <= 22.0:
            heat_score = 11
        elif -6.0 <= return_20 < 0.0:
            heat_score = 9
        elif 22.0 < return_20 <= 30.0:
            heat_score = 6
        else:
            heat_score = 3

        if limit_up_days_20 == 0:
            heat_score += 8
        elif limit_up_days_20 == 1:
            heat_score += 6
        elif limit_up_days_20 == 2:
            heat_score += 4
        elif limit_up_days_20 <= max_recent_limit_up_count_20d:
            heat_score += 2

        chase_score = 8.0
        if latest_pct_chg >= max_latest_pct_chg:
            chase_score -= 5.0
        elif latest_pct_chg >= 6.5:
            chase_score -= 3.0
        elif latest_pct_chg <= -4.0:
            chase_score -= 2.0

        if close_to_20d_high >= 0.995 and return_5 >= 7.0:
            chase_score -= 3.0
        elif close_to_20d_high >= 0.99 and return_5 >= 5.0:
            chase_score -= 2.0

        if strong_up_days_10 >= 3:
            chase_score -= 3.0
        elif strong_up_days_10 >= 2:
            chase_score -= 1.5

        heat_score += max(chase_score, 0.0)

        if avg_amplitude_10 <= 4.0:
            stability_score = 16
        elif avg_amplitude_10 <= 5.0:
            stability_score = 13
        elif avg_amplitude_10 <= max_avg_amplitude_10d:
            stability_score = 10
        elif avg_amplitude_10 <= (max_avg_amplitude_10d + 1.2):
            stability_score = 6
        else:
            stability_score = 3

        if 2.0 <= pullback_from_high <= 12.0:
            stability_score += 10
        elif 0.5 <= pullback_from_high < 2.0 or 12.0 < pullback_from_high <= 18.0:
            stability_score += 8
        elif 18.0 < pullback_from_high <= 25.0:
            stability_score += 6
        else:
            stability_score += 4

        if down_shock_days_10 == 0:
            stability_score += 4
        elif down_shock_days_10 == 1:
            stability_score += 3
        elif down_shock_days_10 == 2:
            stability_score += 1

        if one_word_limit_up_days_20 >= 1:
            stability_score -= min(6.0, one_word_limit_up_days_20 * 2.0)

        liquidity_score = self._clamp_score(liquidity_score, 0.0, 40.0)
        heat_score = self._clamp_score(heat_score, 0.0, 30.0)
        stability_score = self._clamp_score(stability_score, 0.0, 30.0)

        tradeability_score = self._clamp_score(liquidity_score + heat_score + stability_score)
        risk_penalty = max(0.0, (68.0 - tradeability_score) * self.tradeability_penalty_weight)

        if latest_pct_chg >= max_latest_pct_chg + 0.8:
            risk_penalty += min(3.5, 1.2 + (latest_pct_chg - max_latest_pct_chg) * 0.55)
        if strong_up_days_10 >= 2:
            risk_penalty += min(3.0, (strong_up_days_10 - 1) * 0.7)
        if amount_ratio_5_20 < 0.65:
            risk_penalty += min(2.0, (0.65 - amount_ratio_5_20) * 8.0)
        if down_shock_days_10 >= 2:
            risk_penalty += min(2.5, (down_shock_days_10 - 1) * 0.8)
        if one_word_limit_up_days_20 >= 1:
            risk_penalty += min(2.0, one_word_limit_up_days_20 * 0.6)

        blocked_reasons = []
        if not filters["liquidity_pass"]:
            blocked_reasons.append("近20日成交额不足")
        if not filters["limit_up_pass"]:
            blocked_reasons.append("近20日涨停次数过多")
        if not filters["recent_return_pass"]:
            blocked_reasons.append("近20日涨幅过热")
        if not filters["amplitude_pass"]:
            blocked_reasons.append("近10日振幅过大")

        risk_tags = []
        if filters["liquidity_pass"] and amount_ratio_5_20 >= 0.80:
            risk_tags.append("成交活跃")
        elif filters["liquidity_pass"]:
            risk_tags.append("成交活跃但近期缩量")
        else:
            risk_tags.append("流动性偏弱")

        if limit_up_days_20 > 0:
            risk_tags.append("近期涨停活跃")
        if latest_pct_chg >= max_latest_pct_chg or close_to_20d_high >= 0.99:
            risk_tags.append("追高风险")
        if avg_amplitude_10 > max(5.5, max_avg_amplitude_10d * 0.9):
            risk_tags.append("波动偏大")
        if amount_ratio_5_20 < 0.75:
            risk_tags.append("近期成交降温")
        if down_shock_days_10 >= 2:
            risk_tags.append("下跌波动偏大")
        if one_word_limit_up_days_20 >= 1:
            risk_tags.append("一字板博弈风险")
        if len(risk_tags) == 1 and risk_tags[0] == "成交活跃":
            risk_tags.append("换手结构健康")

        return {
            "is_tradeable": all(filters.values()),
            "filters": filters,
            "blocked_reasons": blocked_reasons,
            "risk_tags": risk_tags,
            "tradeability_score": round(tradeability_score, 1),
            "risk_penalty": round(risk_penalty, 2),
            "avg_amount_20": round(avg_amount_20, 2),
            "median_amount_20": round(median_amount_20, 2),
            "recent_amount_5": round(recent_amount_5, 2),
            "liquidity_ratio_20d": round(liquidity_ratio, 3),
            "amount_ratio_5_20": round(amount_ratio_5_20, 3),
            "amount_cv_20": round(amount_cv_20, 3),
            "return_5": round(return_5, 2),
            "return_10": round(return_10, 2),
            "return_20": round(return_20, 2),
            "latest_pct_chg": round(latest_pct_chg, 2),
            "limit_up_days_20": limit_up_days_20,
            "strong_up_days_10": strong_up_days_10,
            "down_shock_days_10": down_shock_days_10,
            "one_word_limit_up_days_20": one_word_limit_up_days_20,
            "avg_amplitude_10": round(avg_amplitude_10, 2),
            "pullback_from_high": round(pullback_from_high, 2),
            "close_to_20d_high": round(close_to_20d_high, 4),
            "component_scores": {
                "liquidity": round(liquidity_score, 1),
                "heat": round(heat_score, 1),
                "stability": round(stability_score, 1),
            },
            "applied_thresholds": thresholds,
        }

    def calculate_short_cycle_factor(self, df: pd.DataFrame, tradeability_profile: Dict = None) -> Tuple[float, Dict]:
        """计算3-5天持有窗口适配分，避免盘前选股偏向中线形态。"""
        if df.empty or len(df) < 20:
            return 0.0, {}

        if tradeability_profile is None:
            tradeability_profile = self.assess_tradeability(df)

        close = pd.to_numeric(df["close"], errors="coerce").replace(0, np.nan).ffill().bfill()
        pct_chg = pd.to_numeric(df["pct_chg"], errors="coerce").fillna(0.0)
        latest_close = float(close.iloc[-1])
        ma5_series = self.calculate_ma(close, 5)
        ma10_series = self.calculate_ma(close, 10)
        ma5 = float(ma5_series.iloc[-1])
        ma10 = float(ma10_series.iloc[-1])

        return_3 = self._window_return(close, min(3, max(len(close) - 1, 1)))
        return_window = tradeability_profile.get("return_5", self._window_return(close, self.short_cycle_window))
        return_10 = tradeability_profile.get("return_10", self._window_return(close, min(10, max(len(close) - 1, 1))))
        pullback_from_high = float(tradeability_profile.get("pullback_from_high", 0.0))
        latest_pct_chg = float(tradeability_profile.get("latest_pct_chg", 0.0))
        close_to_20d_high = float(tradeability_profile.get("close_to_20d_high", 0.0))
        strong_up_days_10 = int(tradeability_profile.get("strong_up_days_10", 0))
        down_shock_days_10 = int(tradeability_profile.get("down_shock_days_10", 0))
        amount_ratio_5_20 = float(tradeability_profile.get("amount_ratio_5_20", 1.0))
        amount_cv_20 = float(tradeability_profile.get("amount_cv_20", 1.0))
        applied_thresholds = tradeability_profile.get("applied_thresholds", {}) or {}
        latest_pct_chg_cap = float(
            applied_thresholds.get("max_latest_pct_chg", self.max_latest_pct_chg)
        )

        ma5_slope_3 = 0.0
        ma10_slope_3 = 0.0
        if len(ma5_series) >= 4 and pd.notna(ma5_series.iloc[-4]) and ma5_series.iloc[-4] != 0:
            ma5_slope_3 = (float(ma5_series.iloc[-1]) / float(ma5_series.iloc[-4]) - 1.0) * 100.0
        if len(ma10_series) >= 4 and pd.notna(ma10_series.iloc[-4]) and ma10_series.iloc[-4] != 0:
            ma10_slope_3 = (float(ma10_series.iloc[-1]) / float(ma10_series.iloc[-4]) - 1.0) * 100.0

        if 1.5 <= return_window <= 7.5:
            impulse_score = 22
        elif -1.0 <= return_window < 1.5 or 7.5 < return_window <= 10.5:
            impulse_score = 17
        elif -4.0 <= return_window < -1.0:
            impulse_score = 12
        elif 10.5 < return_window <= 14.0:
            impulse_score = 8
        else:
            impulse_score = 5

        if 0.5 <= return_3 <= 4.5:
            impulse_score += 13
        elif -2.0 <= return_3 < 0.5 or 4.5 < return_3 <= 6.5:
            impulse_score += 9
        elif 6.5 < return_3 <= 8.0:
            impulse_score += 5
        else:
            impulse_score += 3
        impulse_score = self._clamp_score(impulse_score, 0.0, 35.0)

        if latest_close > ma5 > ma10:
            structure_score = 16
        elif latest_close > ma5 and ma5 >= ma10 * 0.995:
            structure_score = 14
        elif latest_close > ma10:
            structure_score = 11
        else:
            structure_score = 7

        if 2.0 <= pullback_from_high <= 12.0:
            structure_score += 12
        elif 1.0 <= pullback_from_high < 2.0 or 12.0 < pullback_from_high <= 16.0:
            structure_score += 10
        elif 16.0 < pullback_from_high <= 22.0:
            structure_score += 8
        elif pullback_from_high < 1.0:
            structure_score += 6
        else:
            structure_score += 5

        if ma5_slope_3 > 0 and ma10_slope_3 >= -0.2:
            structure_score += 7
        elif ma5_slope_3 > -0.2:
            structure_score += 5
        elif ma5_slope_3 > -0.8:
            structure_score += 3
        else:
            structure_score += 1
        structure_score = self._clamp_score(structure_score, 0.0, 35.0)

        if -1.8 <= latest_pct_chg <= 3.8:
            timing_score = 12
        elif -3.5 <= latest_pct_chg < -1.8 or 3.8 < latest_pct_chg <= 5.8:
            timing_score = 9
        elif latest_pct_chg > latest_pct_chg_cap:
            timing_score = 4
        else:
            timing_score = 6

        if 0.94 <= close_to_20d_high <= 0.985:
            timing_score += 4
        elif 0.985 < close_to_20d_high <= 0.995:
            timing_score += 2
        elif close_to_20d_high < 0.92 and latest_pct_chg < 0:
            timing_score -= 2
        timing_score = self._clamp_score(timing_score, 0.0, 20.0)

        if amount_ratio_5_20 >= 1.20:
            flow_score = 8
        elif amount_ratio_5_20 >= 0.95:
            flow_score = 7
        elif amount_ratio_5_20 >= 0.75:
            flow_score = 5
        elif amount_ratio_5_20 >= 0.60:
            flow_score = 3
        else:
            flow_score = 1

        if amount_cv_20 <= 0.9:
            flow_score += 2
        elif amount_cv_20 > 1.3:
            flow_score -= 2
        flow_score = self._clamp_score(flow_score, 0.0, 10.0)

        overheat_penalty = 0.0
        if close_to_20d_high >= 0.995 and return_window >= 8.0:
            overheat_penalty += 5.0
        elif close_to_20d_high >= 0.99 and return_window >= 6.0:
            overheat_penalty += 3.0
        if strong_up_days_10 >= 3:
            overheat_penalty += 4.0
        elif strong_up_days_10 >= 2:
            overheat_penalty += 3.0
        if return_10 >= 16.0:
            overheat_penalty += 3.0
        if latest_pct_chg >= latest_pct_chg_cap + 1.0:
            overheat_penalty += 2.0
        if int((pct_chg.tail(5).abs() >= 7.0).sum()) >= 2:
            overheat_penalty += 2.0
        if down_shock_days_10 >= 2:
            overheat_penalty += 2.0

        total_score = self._clamp_score(
            impulse_score + structure_score + timing_score + flow_score - overheat_penalty
        )
        detail = {
            "holding_window_days": self.short_cycle_window,
            "swing_score": round(impulse_score, 1),
            "structure_score": round(structure_score, 1),
            "timing_score": round(timing_score, 1),
            "flow_score": round(flow_score, 1),
            "overheat_penalty": round(overheat_penalty, 1),
            "return_3": round(return_3, 2),
            "return_window": round(return_window, 2),
            "return_10": round(return_10, 2),
            "pullback_from_high": round(pullback_from_high, 2),
            "latest_pct_chg": round(latest_pct_chg, 2),
            "latest_pct_chg_cap": round(latest_pct_chg_cap, 2),
            "amount_ratio_5_20": round(amount_ratio_5_20, 3),
            "ma5_slope_3": round(ma5_slope_3, 3),
            "ma10_slope_3": round(ma10_slope_3, 3),
        }
        return round(total_score, 1), detail

    def calculate_trend_factor(self, df: pd.DataFrame) -> Tuple[float, Dict]:
        """
        计算趋势因子得分（P1c: 新增 MACD 状态确认）

        评分维度：
          - MA 多头排列 (0-40分)
          - 趋势强度：20日价格位置 (0-30分)
          - 均线发散度 (0-20分)
          - MACD 状态确认 (-8 ~ +8分)
        """
        if df.empty or len(df) < 20:
            return 0.0, {}

        close = pd.to_numeric(df['close'], errors='coerce').ffill().bfill()
        ma5  = self.calculate_ma(close, 5)
        ma10 = self.calculate_ma(close, 10)
        ma20 = self.calculate_ma(close, 20)
        ma60 = self.calculate_ma(close, 60) if len(df) >= 60 else ma20

        latest_close  = float(close.iloc[-1])
        latest_ma5    = float(ma5.iloc[-1])
        latest_ma10   = float(ma10.iloc[-1])
        latest_ma20   = float(ma20.iloc[-1])
        latest_ma60   = float(ma60.iloc[-1])

        # --- 1. MA 多头排列得分 (0-40分) ---
        if latest_close > latest_ma5 > latest_ma10 > latest_ma20:
            ma_score = 40
        elif latest_close > latest_ma5 > latest_ma10:
            ma_score = 32
        elif latest_close > latest_ma5:
            ma_score = 22
        elif latest_close < latest_ma5 < latest_ma10 < latest_ma20:
            ma_score = 5   # 空头排列
        else:
            ma_score = 14

        # MA60 加分（中长线趋势确认）
        if latest_close > latest_ma60 and latest_ma20 > latest_ma60:
            ma_score = min(ma_score + 5, 40)

        # --- 2. 趋势强度：20日价格位置 (0-30分) ---
        high_20 = float(df['high'].tail(20).max())
        low_20  = float(df['low'].tail(20).min())
        if high_20 > low_20:
            position = (latest_close - low_20) / (high_20 - low_20)
            strength_score = self._clamp_score(position * 30, 0.0, 30.0)
        else:
            strength_score = 15.0

        # --- 3. 均线发散度 (0-20分) ---
        if latest_ma20 > 0:
            ma_diff_pct = abs(latest_ma5 - latest_ma20) / latest_ma20 * 100
            if ma_diff_pct > 5:
                divergence_score = 20
            elif ma_diff_pct > 3:
                divergence_score = 17
            elif ma_diff_pct > 1:
                divergence_score = 13
            else:
                divergence_score = 9   # 均线粘合，趋势不明
        else:
            divergence_score = 12

        # --- 4. P1c: MACD 状态确认 (-8 ~ +8分) ---
        macd_score = 0
        if len(close) >= 35:
            ema12 = close.ewm(span=12, adjust=False).mean()
            ema26 = close.ewm(span=26, adjust=False).mean()
            dif   = ema12 - ema26
            dea   = dif.ewm(span=9, adjust=False).mean()
            hist  = dif - dea  # MACD 柱

            dif_now  = float(dif.iloc[-1])
            dif_prev = float(dif.iloc[-2])
            dea_now  = float(dea.iloc[-1])
            hist_now = float(hist.iloc[-1])
            hist_prev= float(hist.iloc[-2])

            # 金叉（DIF 上穿 DEA）
            if dif_prev <= dea_now and dif_now > dea_now:
                macd_score = +8
            # DIF > DEA 且 MACD 柱扩张（多头趋势延续）
            elif dif_now > dea_now and hist_now > hist_prev > 0:
                macd_score = +5
            # DIF > DEA 但柱收缩（上涨动能减弱）
            elif dif_now > dea_now and hist_now < hist_prev:
                macd_score = +2
            # DIF > 0 但 < DEA（弱势，仍在零轴上方）
            elif dif_now > 0:
                macd_score = 0
            # 死叉（DIF 下穿 DEA）——明确减分
            elif dif_prev >= dea_now and dif_now < dea_now:
                macd_score = -8
            # DIF < DEA < 0（空头趋势）
            else:
                macd_score = -5
        else:
            macd_score = 0  # 数据不足时中性

        total_score = self._clamp_score(
            ma_score + strength_score + divergence_score + macd_score
        )
        detail = {
            "ma_score": round(ma_score, 1),
            "strength_score": round(strength_score, 1),
            "divergence_score": round(divergence_score, 1),
            "macd_score": round(macd_score, 1),
            "ma5": round(latest_ma5, 3),
            "ma10": round(latest_ma10, 3),
            "ma20": round(latest_ma20, 3),
        }
        return round(total_score, 1), detail
    
    def calculate_momentum_factor(self, df: pd.DataFrame) -> Tuple[float, Dict]:
        """
        计算动量因子得分
        
        Args:
            df: 日线数据
        
        Returns:
            (得分, 详细信息)
        """
        if df.empty or len(df) < 20:
            return 0.0, {}
        
        detail = {}
        close = df['close']
        pct_chg = df['pct_chg']
        
        return_5 = self._window_return(close, self.short_cycle_window)
        return_20 = self._window_return(close, min(20, max(len(close) - 1, 1)))

        # A股主板短线更偏好“中等强度而非极端加速”
        if 3 <= return_20 <= 18:
            return_score = 35
        elif 0 <= return_20 < 3 or 18 < return_20 <= 25:
            return_score = 28
        elif -5 <= return_20 < 0:
            return_score = 20
        elif 25 < return_20 <= 35:
            return_score = 16
        else:
            return_score = 10

        if return_5 > 9:
            return_score -= 5
        elif 1 <= return_5 <= 6:
            return_score += 2
        return_score = self._clamp_score(return_score, 0.0, 35.0)
        
        # RSI得分 (0-35分) - 优化版：避免追高
        if len(df) >= 14:
            delta = close.diff()
            gain = delta.where(delta > 0, 0).rolling(window=14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
            rs = gain / loss
            rsi = 100 - (100 / (1 + rs))
            latest_rsi = rsi.iloc[-1]
            
            # 优化：RSI最佳区间50-65，避免过热（>70）和过冷（<40）
            if 50 <= latest_rsi <= 65:
                rsi_score = 35  # 最佳区间：健康上涨
            elif 45 <= latest_rsi < 50 or 65 < latest_rsi <= 70:
                rsi_score = 30  # 次优区间
            elif 40 <= latest_rsi < 45:
                rsi_score = 25  # 偏弱
            elif latest_rsi > 70:
                rsi_score = 20  # 过热：降分，避免追高
            else:
                rsi_score = 15  # 过冷
        else:
            rsi_score = 20
        
        # 连续上涨天数得分 (0-30分)
        up_days = 0
        for i in range(len(pct_chg) - 1, max(len(pct_chg) - 10, 0), -1):
            if pct_chg.iloc[i] > 0:
                up_days += 1
            else:
                break
        
        if 2 <= up_days <= 3:
            up_days_score = 30
        elif up_days == 4:
            up_days_score = 24
        elif up_days == 1:
            up_days_score = 20
        elif up_days >= 5:
            up_days_score = 15
        else:
            up_days_score = 16
        
        total_score = return_score + rsi_score + up_days_score
        
        detail = {
            "return_score": round(return_score, 1),
            "rsi_score": round(rsi_score, 1),
            "up_days_score": round(up_days_score, 1),
            "up_days": up_days,
            "return_5": round(return_5, 2),
            "return_20": round(return_20, 2),
        }
        
        return round(total_score, 1), detail

    def calculate_momentum_factor_legacy(self, df: pd.DataFrame) -> Tuple[float, Dict]:
        """原始动量因子（用于legacy档位回退）。"""
        if df.empty or len(df) < 20:
            return 0.0, {}

        close = df['close']
        pct_chg = df['pct_chg']

        if len(df) >= 20:
            return_20 = (close.iloc[-1] / close.iloc[-20] - 1) * 100
            if return_20 > 20:
                return_score = 35
            elif return_20 > 10:
                return_score = 30
            elif return_20 > 5:
                return_score = 25
            elif return_20 > 0:
                return_score = 20
            elif return_20 > -5:
                return_score = 15
            else:
                return_score = 10
        else:
            return_score = 15

        if len(df) >= 14:
            delta = close.diff()
            gain = delta.where(delta > 0, 0).rolling(window=14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
            rs = gain / loss
            rsi = 100 - (100 / (1 + rs))
            latest_rsi = rsi.iloc[-1]
            if 50 <= latest_rsi <= 65:
                rsi_score = 35
            elif 45 <= latest_rsi < 50 or 65 < latest_rsi <= 70:
                rsi_score = 30
            elif 40 <= latest_rsi < 45:
                rsi_score = 25
            elif latest_rsi > 70:
                rsi_score = 20
            else:
                rsi_score = 15
        else:
            rsi_score = 20

        up_days = 0
        for i in range(len(pct_chg) - 1, max(len(pct_chg) - 10, 0), -1):
            if pct_chg.iloc[i] > 0:
                up_days += 1
            else:
                break

        if up_days >= 5:
            up_days_score = 30
        elif up_days >= 3:
            up_days_score = 25
        elif up_days >= 2:
            up_days_score = 20
        else:
            up_days_score = 15

        total_score = return_score + rsi_score + up_days_score
        detail = {
            "return_score": round(return_score, 1),
            "rsi_score": round(rsi_score, 1),
            "up_days_score": round(up_days_score, 1),
            "up_days": up_days,
            "mode": "legacy",
        }
        return round(total_score, 1), detail

    def calculate_volume_factor(self, df: pd.DataFrame) -> Tuple[float, Dict]:
        """
        计算量能因子得分
        
        Args:
            df: 日线数据
        
        Returns:
            (得分, 详细信息)
        """
        if df.empty or len(df) < 20:
            return 0.0, {}
        
        detail = {}
        vol = df['vol']
        amount = pd.to_numeric(df['amount'], errors='coerce').fillna(0.0)
        close = df['close']
        
        # 量能放大得分 (0-35分)
        vol_ma5 = self.calculate_ma(vol, 5)
        vol_ma20 = self.calculate_ma(vol, 20)
        
        latest_vol = vol.iloc[-1]
        latest_vol_ma5 = vol_ma5.iloc[-1]
        latest_vol_ma20 = vol_ma20.iloc[-1]
        
        amount_ma20 = self.calculate_ma(amount, 20)
        latest_amount = amount.iloc[-1]
        latest_amount_ma20 = amount_ma20.iloc[-1]

        if latest_vol_ma20 > 0:
            vol_ratio = latest_vol / latest_vol_ma20
            if 1.1 <= vol_ratio <= 1.8:
                vol_expand_score = 35
            elif 0.9 <= vol_ratio < 1.1 or 1.8 < vol_ratio <= 2.5:
                vol_expand_score = 28
            elif 0.7 <= vol_ratio < 0.9:
                vol_expand_score = 20
            else:
                vol_expand_score = 14
        else:
            vol_expand_score = 20
        
        # 量价配合得分 (0-35分)
        if len(df) >= 5:
            price_change = close.iloc[-1] / close.iloc[-5] - 1
            amount_change = amount.iloc[-1] / amount.iloc[-5] - 1 if amount.iloc[-5] > 0 else 0

            if price_change > 0 and 0 < amount_change <= 1.5:
                vp_score = 35  # 温和放量上涨
            elif price_change > 0 and -0.2 <= amount_change <= 0:
                vp_score = 26  # 价升量稳
            elif price_change > 0 and amount_change > 1.5:
                vp_score = 20  # 爆量后容易过热
            elif price_change < 0 and amount_change > 0:
                vp_score = 18
            else:
                vp_score = 15
        else:
            vp_score = 20
        
        # 量能趋势得分 (0-30分)
        if len(df) >= 10:
            recent_vol_ma5 = vol_ma5.iloc[-10:]
            vol_slope = (recent_vol_ma5.iloc[-1] - recent_vol_ma5.iloc[0]) / recent_vol_ma5.iloc[0] * 100 if recent_vol_ma5.iloc[0] > 0 else 0
            if vol_slope > 20:
                vol_trend_score = 30
            elif vol_slope > 10:
                vol_trend_score = 25
            elif vol_slope > 0:
                vol_trend_score = 20
            else:
                vol_trend_score = 15
        else:
            vol_trend_score = 20
        
        liquidity_floor_score = 0
        avg_amount_20 = float(amount.tail(20).mean())
        if avg_amount_20 >= self.min_avg_amount_20d * 2:
            liquidity_floor_score = 6
        elif avg_amount_20 >= self.min_avg_amount_20d:
            liquidity_floor_score = 3

        total_score = self._clamp_score(vol_expand_score + vp_score + vol_trend_score + liquidity_floor_score)
        
        detail = {
            "vol_expand_score": round(vol_expand_score, 1),
            "vp_score": round(vp_score, 1),
            "vol_trend_score": round(vol_trend_score, 1),
            "liquidity_floor_score": round(liquidity_floor_score, 1),
            "vol_ratio": round(vol_ratio, 2) if latest_vol_ma20 > 0 else 1,
            "amount_ratio": round(latest_amount / latest_amount_ma20, 2) if latest_amount_ma20 > 0 else 1,
            "avg_amount_20": round(avg_amount_20, 2),
        }
        
        return round(total_score, 1), detail

    def calculate_volume_factor_legacy(self, df: pd.DataFrame) -> Tuple[float, Dict]:
        """原始量能因子（用于legacy档位回退）。"""
        if df.empty or len(df) < 20:
            return 0.0, {}

        vol = df['vol']
        close = df['close']
        vol_ma5 = self.calculate_ma(vol, 5)
        vol_ma20 = self.calculate_ma(vol, 20)

        latest_vol = vol.iloc[-1]
        latest_vol_ma20 = vol_ma20.iloc[-1]

        if latest_vol_ma20 > 0:
            vol_ratio = latest_vol / latest_vol_ma20
            if vol_ratio > 2:
                vol_expand_score = 35
            elif vol_ratio > 1.5:
                vol_expand_score = 30
            elif vol_ratio > 1.2:
                vol_expand_score = 25
            elif vol_ratio > 1:
                vol_expand_score = 20
            else:
                vol_expand_score = 15
        else:
            vol_expand_score = 20

        if len(df) >= 5:
            price_change = close.iloc[-1] / close.iloc[-5] - 1
            vol_change = vol.iloc[-1] / vol.iloc[-5] - 1 if vol.iloc[-5] > 0 else 0
            if price_change > 0 and vol_change > 0:
                vp_score = 35
            elif price_change > 0 and vol_change < 0:
                vp_score = 20
            elif price_change < 0 and vol_change > 0:
                vp_score = 25
            else:
                vp_score = 15
        else:
            vp_score = 20

        if len(df) >= 10:
            recent_vol_ma5 = vol_ma5.iloc[-10:]
            vol_slope = (
                (recent_vol_ma5.iloc[-1] - recent_vol_ma5.iloc[0]) / recent_vol_ma5.iloc[0] * 100
                if recent_vol_ma5.iloc[0] > 0
                else 0
            )
            if vol_slope > 20:
                vol_trend_score = 30
            elif vol_slope > 10:
                vol_trend_score = 25
            elif vol_slope > 0:
                vol_trend_score = 20
            else:
                vol_trend_score = 15
        else:
            vol_trend_score = 20

        total_score = vol_expand_score + vp_score + vol_trend_score
        detail = {
            "vol_expand_score": round(vol_expand_score, 1),
            "vp_score": round(vp_score, 1),
            "vol_trend_score": round(vol_trend_score, 1),
            "vol_ratio": round(vol_ratio, 2) if latest_vol_ma20 > 0 else 1,
            "mode": "legacy",
        }
        return round(total_score, 1), detail
    
    def calculate_fundamental_factor(
        self,
        ts_code: str,
        end_date: str = None,
        name: str = None,
        industry: str = None,
        list_date: str = None,
    ) -> Tuple[float, Dict]:
        """
        计算基本面因子得分。

        行业分优先使用动态行业热度（盘前基于历史库截至end_date计算），
        若动态数据不可用则回退到中性评分。
        """
        detail = {}
        end_date = self._resolve_end_date(end_date)

        if name is None or industry is None or list_date is None:
            sql = """
                SELECT name, industry, list_date
                FROM stock_basic
                WHERE ts_code = ?
            """
            result = self.db.query_one(sql, (ts_code,))
            if not result:
                return 50.0, {"note": "无基础数据"}
            name = result.get("name", "")
            industry = result.get("industry", "")
            list_date = result.get("list_date", "")

        industry_map = self._prepare_dynamic_industry_strength(end_date=end_date)
        industry_info = industry_map.get(industry) if industry_map else None

        if industry_info:
            heat_score = float(industry_info.get("heat_score", 50.0))
            if heat_score >= 80:
                industry_score = 35
            elif heat_score >= 65:
                industry_score = 31
            elif heat_score >= 50:
                industry_score = 26
            elif heat_score >= 35:
                industry_score = 21
            else:
                industry_score = 16
        else:
            heat_score = 50.0
            industry_score = 24

        if "ST" in str(name) or "st" in str(name) or "退" in str(name):
            name_score = 0
        elif "*ST" in str(name):
            name_score = 0
        else:
            name_score = 30

        days_listed = 0
        if list_date:
            try:
                list_date_str = str(list_date)
                if len(list_date_str) == 8:
                    list_dt = datetime.strptime(list_date_str, "%Y%m%d")
                else:
                    list_dt = datetime.strptime(list_date_str[:10], "%Y-%m-%d")
                days_listed = (datetime.strptime(end_date, "%Y%m%d") - list_dt).days

                if days_listed > 365 * 3:
                    list_score = 35
                elif days_listed > 365 * 2:
                    list_score = 30
                elif days_listed > 365:
                    list_score = 25
                else:
                    list_score = 15
            except Exception:
                list_score = 25
        else:
            list_score = 25

        total_score = industry_score + name_score + list_score

        detail = {
            "industry_score": round(industry_score, 1),
            "name_score": round(name_score, 1),
            "list_score": round(list_score, 1),
            "industry": industry,
            "days_listed": days_listed if list_date else 0,
            "industry_dynamic": {
                "enabled": bool(self.use_dynamic_industry_strength),
                "end_date": end_date,
                "industry_heat_score": round(float(heat_score), 2),
                "industry_heat_level": (
                    industry_info.get("heat_level", "neutral")
                    if industry_info
                    else "neutral"
                ),
                "industry_rank": (
                    int(industry_info.get("rank"))
                    if industry_info and industry_info.get("rank") is not None
                    else None
                ),
                "industry_stock_count": (
                    int(industry_info.get("stock_count"))
                    if industry_info and industry_info.get("stock_count") is not None
                    else None
                ),
                "avg_ret_3": (
                    float(industry_info.get("avg_ret_3", 0.0))
                    if industry_info
                    else 0.0
                ),
                "avg_ret_5": (
                    float(industry_info.get("avg_ret_5", 0.0))
                    if industry_info
                    else 0.0
                ),
                "breadth_today": (
                    float(industry_info.get("breadth_today", 0.0))
                    if industry_info
                    else 0.0
                ),
            },
        }

        return round(total_score, 1), detail

    def calculate_fundamental_factor_legacy(
        self,
        ts_code: str,
        end_date: str = None,
        name: str = None,
        industry: str = None,
        list_date: str = None,
    ) -> Tuple[float, Dict]:
        """基本面因子 - 使用动态行业热度替代硬编码行业白名单（P1b 优化）。"""
        end_date = self._resolve_end_date(end_date)

        if name is None or industry is None or list_date is None:
            sql = "SELECT name, industry, list_date FROM stock_basic WHERE ts_code = ?"
            result = self.db.query_one(sql, (ts_code,))
            if not result:
                return 50.0, {"note": "无基础数据"}
            name = result.get("name", "")
            industry = result.get("industry", "")
            list_date = result.get("list_date", "")

        # P1b: 动态行业热度评分（替代硬编码白名单）
        industry_map = self._prepare_dynamic_industry_strength(end_date=end_date)
        industry_info = industry_map.get(industry) if industry_map else None
        if industry_info:
            heat_score = float(industry_info.get("heat_score", 50.0))
            if heat_score >= 80:
                industry_score = 35
            elif heat_score >= 65:
                industry_score = 31
            elif heat_score >= 50:
                industry_score = 26
            elif heat_score >= 35:
                industry_score = 21
            else:
                industry_score = 16
        else:
            heat_score = 50.0
            industry_score = 24  # 动态数据不可用时使用中性分

        # ST / 退市标记
        if any(tag in str(name) for tag in ("ST", "st", "退", "*ST")):
            name_score = 0
        else:
            name_score = 30

        # 上市年限评分
        days_listed = 0
        if list_date:
            try:
                ld_str = str(list_date)
                list_dt = (
                    datetime.strptime(ld_str, "%Y%m%d")
                    if len(ld_str) == 8
                    else datetime.strptime(ld_str[:10], "%Y-%m-%d")
                )
                days_listed = (datetime.strptime(end_date, "%Y%m%d") - list_dt).days
                if days_listed > 365 * 3:
                    list_score = 35
                elif days_listed > 365 * 2:
                    list_score = 30
                elif days_listed > 365:
                    list_score = 25
                else:
                    list_score = 15
            except Exception:
                list_score = 25
        else:
            list_score = 25

        total_score = industry_score + name_score + list_score
        detail = {
            "industry_score": round(industry_score, 1),
            "name_score": round(name_score, 1),
            "list_score": round(list_score, 1),
            "industry": industry,
            "days_listed": days_listed,
            "industry_heat_score": round(heat_score, 2),
            "industry_heat_level": (
                industry_info.get("heat_level", "neutral") if industry_info else "neutral"
            ),
            "mode": "legacy_dynamic",
        }
        return round(total_score, 1), detail

    def calculate_quality_factor(self, df: pd.DataFrame) -> Tuple[float, Dict]:
        """
        计算质量/稳定性因子得分。

        用于补足趋势和动量之外的稳定性维度，降低高波动、回撤过深标的的权重。
        """
        if df.empty or len(df) < 20:
            return 50.0, {}

        close = df['close']
        vol = df['vol']
        returns = close.pct_change().dropna().tail(20)

        daily_volatility = float(returns.std() * 100) if not returns.empty else 0.0
        positive_ratio = float((returns > 0).mean()) if not returns.empty else 0.5

        rolling_high = close.cummax()
        drawdown = ((rolling_high - close) / rolling_high.replace(0, np.nan)).fillna(0)
        max_drawdown = float(drawdown.tail(60).max() * 100)

        recent_volume = vol.tail(20)
        volume_cv = float(recent_volume.std() / recent_volume.mean()) if recent_volume.mean() else 1.0

        if 1.0 <= daily_volatility <= 3.0:
            risk_score = 40
        elif 3.0 < daily_volatility <= 4.5:
            risk_score = 30
        elif daily_volatility < 1.0:
            risk_score = 25
        else:
            risk_score = 15

        if max_drawdown <= 8:
            drawdown_score = 35
        elif max_drawdown <= 12:
            drawdown_score = 30
        elif max_drawdown <= 18:
            drawdown_score = 20
        else:
            drawdown_score = 10

        if volume_cv <= 0.4:
            liquidity_score = 25
        elif volume_cv <= 0.7:
            liquidity_score = 20
        elif volume_cv <= 1.0:
            liquidity_score = 15
        else:
            liquidity_score = 10

        total_score = risk_score + drawdown_score + liquidity_score
        detail = {
            "risk_score": round(risk_score, 1),
            "drawdown_score": round(drawdown_score, 1),
            "liquidity_score": round(liquidity_score, 1),
            "daily_volatility": round(daily_volatility, 2),
            "max_drawdown": round(max_drawdown, 2),
            "volume_cv": round(volume_cv, 2),
            "positive_ratio": round(positive_ratio, 2)
        }

        return round(total_score, 1), detail
    
    def calculate_pullback_factor(self, df: pd.DataFrame) -> Tuple[float, Dict]:
        """
        计算回调保护因子得分 - 避免追高
        
        Args:
            df: 日线数据
        
        Returns:
            (得分, 详细信息)
        """
        if df.empty or len(df) < 20:
            return 50.0, {}
        
        detail = {}
        close = df['close']
        
        latest_close = close.iloc[-1]
        
        # 计算距离20日高点的回撤
        high_20 = df['high'].tail(20).max()
        low_20 = df['low'].tail(20).min()
        
        if high_20 > 0:
            pullback_from_high = (high_20 - latest_close) / high_20 * 100
        else:
            pullback_from_high = 0
        
        # 回撤位置评分 (0-40分) - 买在回调位置加分
        if 5 <= pullback_from_high <= 15:  # 回调5-15%，最佳买点
            pullback_score = 40
        elif 3 <= pullback_from_high < 5:  # 小幅回调
            pullback_score = 35
        elif 15 < pullback_from_high <= 25:  # 较大回调
            pullback_score = 30
        elif pullback_from_high < 3:  # 接近新高，追高风险
            pullback_score = 15
        else:  # 回撤过大，可能趋势破坏
            pullback_score = 20
        
        # 支撑位评分 (0-30分) - 距离支撑位距离
        ma20 = self.calculate_ma(close, 20).iloc[-1]
        if ma20 > 0:
            dist_to_ma20 = (latest_close - ma20) / ma20 * 100
            if 0 <= dist_to_ma20 <= 5:  # 接近MA20支撑
                support_score = 30
            elif -5 <= dist_to_ma20 < 0:  # 略破MA20但不多
                support_score = 25
            elif 5 < dist_to_ma20 <= 10:
                support_score = 20
            else:
                support_score = 15
        else:
            support_score = 20
        
        # 波动率评分 (0-30分) - 适度波动更好
        if len(df) >= 20:
            returns = close.pct_change().tail(20)
            volatility = returns.std() * 100
            if 2 <= volatility <= 4:  # 适度波动
                vol_score = 30
            elif 1 <= volatility < 2:  # 波动太小
                vol_score = 25
            elif 4 < volatility <= 6:  # 波动稍大
                vol_score = 20
            else:  # 波动过大或过小
                vol_score = 15
        else:
            vol_score = 20
        
        total_score = pullback_score + support_score + vol_score
        
        detail = {
            "pullback_score": round(pullback_score, 1),
            "support_score": round(support_score, 1),
            "vol_score": round(vol_score, 1),
            "pullback_pct": round(pullback_from_high, 2),
            "dist_to_ma20": round(dist_to_ma20, 2) if ma20 > 0 else 0
        }
        
        return round(total_score, 1), detail
    
    def adjust_by_market(self, base_score: float) -> float:
        """
        根据市场环境调整得分
        
        Args:
            base_score: 基础得分
        
        Returns:
            调整后的得分
        """
        # 强势市场（>70分）：放宽标准，更多机会
        if self.market_score > 70:
            return base_score * 1.1
        # 弱势市场（<40分）：收紧标准，更谨慎
        elif self.market_score < 40:
            return base_score * 0.9
        # 震荡市场：保持原样
        else:
            return base_score
    
    def diversify_by_industry(self, results: List[Dict]) -> List[Dict]:
        """
        行业分散 - 避免单一行业集中
        
        Args:
            results: 选股结果列表
        
        Returns:
            分散后的结果列表
        """
        industry_count = {}
        diversified = []
        
        for stock in results:
            industry = stock.get('industry', '未知')
            count = industry_count.get(industry, 0)
            
            if count < self.max_per_industry:
                diversified.append(stock)
                industry_count[industry] = count + 1
        
        return diversified

    def _build_legacy_tradeability_profile(
        self,
        dynamic_tradeability_thresholds: Optional[Dict] = None,
    ) -> Dict:
        """legacy模式下返回兼容字段的中性交易性信息。"""
        thresholds = self._resolve_tradeability_thresholds(dynamic_tradeability_thresholds)
        return {
            "is_tradeable": True,
            "filters": {
                "liquidity_pass": True,
                "limit_up_pass": True,
                "recent_return_pass": True,
                "amplitude_pass": True,
            },
            "blocked_reasons": [],
            "risk_tags": ["legacy_profile"],
            "tradeability_score": 100.0,
            "risk_penalty": 0.0,
            "applied_thresholds": thresholds,
        }

    def _filter_basic_legacy(self, stock_list: pd.DataFrame) -> pd.DataFrame:
        """
        legacy严格兼容：按原策略做基础过滤。

        与新版filter_basic的区别：
        1. 新股过滤以当前自然日为锚点；
        2. list_date按原始文本直接比较，不做额外归一化。
        """
        if stock_list.empty:
            return stock_list

        original_count = len(stock_list)

        if self.exclude_st:
            stock_list = stock_list[~stock_list['name'].str.contains('ST|st|退', na=False)]

        if self.exclude_new > 0:
            today = datetime.now()
            min_list_date = (today - timedelta(days=self.exclude_new)).strftime("%Y%m%d")
            stock_list = stock_list[
                (stock_list['list_date'].isna()) |
                (stock_list['list_date'] < min_list_date)
            ]

        def is_main_board(ts_code: str) -> bool:
            if '.' not in ts_code:
                return False

            code, market = ts_code.split('.')
            if market == 'SH':
                return code.startswith(('600', '601', '603', '605'))
            if market == 'SZ':
                return code.startswith(('000', '001', '002', '003'))
            return False

        stock_list = stock_list[stock_list['ts_code'].apply(is_main_board)]
        logger.info(f"基本面初筛: {original_count} -> {len(stock_list)}只股票（仅沪深主板）")
        return stock_list

    def _calculate_stock_score_legacy_exact(
        self,
        ts_code: str,
        name: str,
        industry: str,
        end_date: str = None,
    ) -> Optional[Dict]:
        """
        legacy严格兼容：使用原始5因子评分链路。

        关键特性：
        1. 不做交易性硬过滤；
        2. 不做短周期附加惩奖；
        3. 不做总分裁剪（保持原策略行为）。
        """
        df = self.get_stock_daily_data(ts_code, days=120, end_date=end_date)
        if df.empty or len(df) < 20:
            return None

        trend_score, trend_detail = self.calculate_trend_factor(df)
        momentum_score, momentum_detail = self.calculate_momentum_factor_legacy(df)
        volume_score, volume_detail = self.calculate_volume_factor_legacy(df)
        fundamental_score, fundamental_detail = self.calculate_fundamental_factor_legacy(
            ts_code=ts_code,
            end_date=end_date,
            name=name,
            industry=industry,
        )
        pullback_score, pullback_detail = self.calculate_pullback_factor(df)

        active_weights = self._get_legacy_weights()
        total_score = (
            trend_score * active_weights['trend'] +
            momentum_score * active_weights['momentum'] +
            volume_score * active_weights['volume'] +
            fundamental_score * active_weights['fundamental'] +
            pullback_score * active_weights['pullback']
        )
        total_score = self.adjust_by_market(total_score)

        if self.save_factor_values and end_date:
            factor_data = pd.DataFrame([
                {'ts_code': ts_code, 'trade_date': end_date, 'factor_name': 'trend_score', 'factor_value': trend_score},
                {'ts_code': ts_code, 'trade_date': end_date, 'factor_name': 'momentum_score', 'factor_value': momentum_score},
                {'ts_code': ts_code, 'trade_date': end_date, 'factor_name': 'volume_score', 'factor_value': volume_score},
                {'ts_code': ts_code, 'trade_date': end_date, 'factor_name': 'pullback_score', 'factor_value': pullback_score},
            ])
            self.factor_storage.save_factor_values(factor_data)

        if total_score >= 85:
            level = "强烈推荐"
        elif total_score >= 75:
            level = "推荐"
        elif total_score >= 65:
            level = "观望"
        else:
            level = "不推荐"

        tradeability_detail = self._build_legacy_tradeability_profile(None)

        return {
            "ts_code": ts_code,
            "name": name,
            "industry": industry,
            "strategy_profile": self.strategy_profile,
            "total_score": round(total_score, 1),
            "trend_score": trend_score,
            "momentum_score": momentum_score,
            "volume_score": volume_score,
            "fundamental_score": fundamental_score,
            "pullback_score": pullback_score,
            "quality_score": 0.0,
            "short_cycle_score": 50.0,
            "tradeability_score": 100.0,
            "tradeability_penalty": 0.0,
            "holding_window_days": self.short_cycle_window,
            "tradeability_tags": tradeability_detail.get("risk_tags", []),
            "tradeability_thresholds": tradeability_detail.get("applied_thresholds", {}),
            "level": level,
            "factor_weights": active_weights,
            "score_breakdown": {
                "trend": round(trend_score * active_weights['trend'], 2),
                "momentum": round(momentum_score * active_weights['momentum'], 2),
                "volume": round(volume_score * active_weights['volume'], 2),
                "fundamental": round(fundamental_score * active_weights['fundamental'], 2),
                "pullback": round(pullback_score * active_weights['pullback'], 2),
                "quality": 0.0,
                "short_cycle_adjustment": 0.0,
                "tradeability_penalty": 0.0,
            },
            "trend_detail": trend_detail,
            "momentum_detail": momentum_detail,
            "volume_detail": volume_detail,
            "fundamental_detail": fundamental_detail,
            "pullback_detail": pullback_detail,
            "quality_detail": {"mode": "legacy_disabled"},
            "tradeability_detail": tradeability_detail,
            "short_cycle_detail": {"mode": "legacy_disabled"},
        }
    
    def calculate_stock_score(
        self,
        ts_code: str,
        name: str,
        industry: str,
        end_date: str = None,
        list_date: str = None,
        dynamic_tradeability_thresholds: Optional[Dict] = None,
    ) -> Optional[Dict]:
        """
        计算单只股票的综合得分（6因子模型）
        
        Args:
            ts_code: 股票代码
            name: 股票名称
            industry: 所属行业
            end_date: 结束日期（YYYYMMDD格式），默认为当天
        
        Returns:
            评分结果字典
        """
        if self._use_legacy_profile():
            return self._calculate_stock_score_legacy_exact(
                ts_code=ts_code,
                name=name,
                industry=industry,
                end_date=end_date,
            )

        # 获取日线数据
        df = self.get_stock_daily_data(ts_code, days=120, end_date=end_date)
        
        if df.empty or len(df) < 20:
            return None
        active_weights = self._get_active_weights()

        tradeability_detail = self.assess_tradeability(
            df,
            dynamic_thresholds=dynamic_tradeability_thresholds,
        )
        if not tradeability_detail.get("is_tradeable", False):
            logger.debug(
                "%s 盘前过滤未通过: %s",
                ts_code,
                ",".join(tradeability_detail.get("blocked_reasons", [])) or "未知原因"
            )
            return None

        # enhanced档位：完整6因子 + 交易性过滤 + 短周期修正
        trend_score, trend_detail = self.calculate_trend_factor(df)
        momentum_score, momentum_detail = self.calculate_momentum_factor(df)
        volume_score, volume_detail = self.calculate_volume_factor(df)
        fundamental_score, fundamental_detail = self.calculate_fundamental_factor(
            ts_code=ts_code,
            end_date=end_date,
            name=name,
            industry=industry,
            list_date=list_date,
        )
        pullback_score, pullback_detail = self.calculate_pullback_factor(df)
        quality_score, quality_detail = self.calculate_quality_factor(df)
        short_cycle_score, short_cycle_detail = self.calculate_short_cycle_factor(
            df, tradeability_profile=tradeability_detail
        )

        total_score = (
            trend_score * active_weights['trend'] +
            momentum_score * active_weights['momentum'] +
            volume_score * active_weights['volume'] +
            fundamental_score * active_weights['fundamental'] +
            pullback_score * active_weights['pullback'] +
            quality_score * active_weights['quality']
        )
        total_score = self.adjust_by_market(total_score)
        short_cycle_adjustment = (short_cycle_score - 50.0) * self.short_cycle_score_weight
        total_score = total_score + short_cycle_adjustment - tradeability_detail["risk_penalty"]
        total_score = self._clamp_score(total_score)
        
        # 保存因子值到数据库（用于IC分析）
        if self.save_factor_values and end_date:
            trade_date = end_date
            factor_data = pd.DataFrame([
                {'ts_code': ts_code, 'trade_date': trade_date, 'factor_name': 'trend_score', 'factor_value': trend_score},
                {'ts_code': ts_code, 'trade_date': trade_date, 'factor_name': 'momentum_score', 'factor_value': momentum_score},
                {'ts_code': ts_code, 'trade_date': trade_date, 'factor_name': 'volume_score', 'factor_value': volume_score},
                {'ts_code': ts_code, 'trade_date': trade_date, 'factor_name': 'fundamental_score', 'factor_value': fundamental_score},
                {'ts_code': ts_code, 'trade_date': trade_date, 'factor_name': 'pullback_score', 'factor_value': pullback_score},
                {'ts_code': ts_code, 'trade_date': trade_date, 'factor_name': 'quality_score', 'factor_value': quality_score},
                {'ts_code': ts_code, 'trade_date': trade_date, 'factor_name': 'short_cycle_score', 'factor_value': short_cycle_score},
                {'ts_code': ts_code, 'trade_date': trade_date, 'factor_name': 'tradeability_score', 'factor_value': tradeability_detail['tradeability_score']},
            ])
            self.factor_storage.save_factor_values(factor_data)
        
        # 判定推荐等级
        if total_score >= 85:
            level = "强烈推荐"
        elif total_score >= 75:
            level = "推荐"
        elif total_score >= 65:
            level = "观望"
        else:
            level = "不推荐"
        
        return {
            "ts_code": ts_code,
            "name": name,
            "industry": industry,
            "strategy_profile": "enhanced",
            "enhanced_weight_profile": self.get_enhanced_weight_profile_name(),
            "total_score": round(total_score, 1),
            "trend_score": trend_score,
            "momentum_score": momentum_score,
            "volume_score": volume_score,
            "fundamental_score": fundamental_score,
            "pullback_score": pullback_score,
            "quality_score": quality_score,
            "short_cycle_score": short_cycle_score,
            "tradeability_score": tradeability_detail["tradeability_score"],
            "tradeability_penalty": tradeability_detail["risk_penalty"],
            "holding_window_days": self.short_cycle_window,
            "tradeability_tags": tradeability_detail.get("risk_tags", []),
            "tradeability_thresholds": tradeability_detail.get("applied_thresholds", {}),
            "level": level,
            "factor_weights": active_weights,
            "score_breakdown": {
                "trend": round(trend_score * active_weights['trend'], 2),
                "momentum": round(momentum_score * active_weights['momentum'], 2),
                "volume": round(volume_score * active_weights['volume'], 2),
                "fundamental": round(fundamental_score * active_weights['fundamental'], 2),
                "pullback": round(pullback_score * active_weights['pullback'], 2),
                "quality": round(quality_score * active_weights['quality'], 2),
                "short_cycle_adjustment": round(short_cycle_adjustment, 2),
                "tradeability_penalty": round(tradeability_detail["risk_penalty"], 2),
            },
            "trend_detail": trend_detail,
            "momentum_detail": momentum_detail,
            "volume_detail": volume_detail,
            "fundamental_detail": fundamental_detail,
            "pullback_detail": pullback_detail,
            "quality_detail": quality_detail,
            "tradeability_detail": tradeability_detail,
            "short_cycle_detail": short_cycle_detail,
        }
    
    @staticmethod
    def _zscore_normalize_scores(results: List[Dict]) -> List[Dict]:
        """
        P5: Z-score 标准化候选股评分，扩大 top_n 内部区分度。
        将原始 total_score 保留，同时生成 score_normalized 字段（映射至 [50, 100]）。
        """
        if len(results) < 3:
            for r in results:
                r["score_normalized"] = r["total_score"]
            return results
        scores = np.array([r["total_score"] for r in results], dtype=float)
        mean_s = float(np.mean(scores))
        std_s  = float(np.std(scores))
        if std_s < 1e-6:
            for r in results:
                r["score_normalized"] = round(float(r["total_score"]), 2)
            return results
        for r in results:
            z = (float(r["total_score"]) - mean_s) / std_s
            r["score_normalized"] = round(float(np.clip(50.0 + z * 10.0, 0.0, 100.0)), 2)
        return results

    def run_selection(self, market_score: float = None, end_date: str = None) -> List[Dict]:
        """
        执行 legacy 选股（原始5因子模型，含 P1~P5 全量优化）

        Args:
            market_score: 市场评分（可选，用于 adjust_by_market）
            end_date: 结束日期（YYYYMMDD），默认为当天

        Returns:
            经评分标准化、行业分散后的 TOP N 股票列表
        """
        if end_date is None:
            end_date = datetime.now().strftime("%Y%m%d")

        logger.info("=" * 50)
        logger.info("开始执行选股（Legacy 5因子模型）...")
        logger.info("选股日期: %s", end_date)
        logger.info("=" * 50)

        if market_score is not None:
            self.market_score = market_score
            logger.info("市场评分: %s分", market_score)

        # 预计算动态行业热度（P1b 基本面因子使用）
        if self.use_dynamic_industry_strength:
            industry_snapshot = self.get_dynamic_industry_strength(end_date=end_date, top_n=5)
            if industry_snapshot:
                top_desc = ", ".join(
                    f"{item['industry']}({item['heat_score']:.1f})"
                    for item in industry_snapshot
                )
                logger.info("盘前动态行业热度TOP5: %s", top_desc)

        # 获取股票列表
        stock_list = self.get_stock_list(end_date=end_date, point_in_time=False)
        if stock_list.empty:
            logger.error("股票列表为空，请先更新数据")
            raise StockSelectionException("股票列表为空")

        # 基本面初筛
        stock_list = self._filter_basic_legacy(stock_list)

        # FeedbackGuard 防护（legacy 档也启用）
        feedback_guard_profile = self._get_feedback_guard_profile(end_date=end_date)
        effective_min_score = float(feedback_guard_profile.get("effective_min_score", self.min_score))
        effective_top_n    = int(feedback_guard_profile.get("effective_top_n", self.top_n))
        if feedback_guard_profile.get("active"):
            logger.warning(
                "闭环防护生效: level=%s reason=%s min_score %.1f -> %.1f top_n %d -> %d",
                feedback_guard_profile.get("level", "normal"),
                feedback_guard_profile.get("reason", ""),
                float(self.min_score), effective_min_score,
                int(self.top_n), effective_top_n,
            )

        active_weights = self._get_active_weights()
        total_count = len(stock_list)
        logger.info(
            "开始计算 %d 只股票的得分... 因子权重: 趋势%.0f%% 动量%.0f%% 量能%.0f%% 基本面%.0f%% 回调%.0f%%",
            total_count,
            active_weights['trend'] * 100,
            active_weights['momentum'] * 100,
            active_weights['volume'] * 100,
            active_weights['fundamental'] * 100,
            active_weights['pullback'] * 100,
        )

        results = []
        processed_count = 0
        for _, row in stock_list.iterrows():
            ts_code  = row['ts_code']
            name     = row.get('name', '')
            industry = row.get('industry', '')
            list_date = row.get('list_date', '')
            try:
                result = self._calculate_stock_score_legacy_exact(
                    ts_code=ts_code,
                    name=name,
                    industry=industry,
                    end_date=end_date,
                )
                if result and result['total_score'] >= effective_min_score:
                    result["feedback_guard_level"] = str(feedback_guard_profile.get("level", "normal"))
                    result["feedback_guard_active"] = bool(feedback_guard_profile.get("active", False))
                    results.append(result)
                processed_count += 1
                if processed_count % 500 == 0:
                    logger.info("已处理 %d/%d 只股票", processed_count, total_count)
            except Exception as e:
                logger.debug("计算 %s 得分失败: %s", ts_code, e)
                continue

        # P5: Z-score 标准化，扩大候选池内区分度
        results = self._zscore_normalize_scores(results)

        # 按标准化分排序
        results.sort(key=lambda x: x.get('score_normalized', x['total_score']), reverse=True)

        # 行业分散
        diversified_results = self.diversify_by_industry(results)

        # 取 TOP N
        top_results = diversified_results[:effective_top_n]

        industry_dist: Dict[str, int] = {}
        for stock in top_results:
            ind = stock.get('industry', '未知')
            industry_dist[ind] = industry_dist.get(ind, 0) + 1

        logger.info("=" * 50)
        logger.info("选股完成，共筛选出 %d 只符合条件的股票", len(results))
        logger.info("行业分散后: %d 只（每行业最多 %d 只）", len(diversified_results), self.max_per_industry)
        logger.info("行业分布: %s", industry_dist)
        logger.info("TOP %d 股票:", len(top_results))
        for i, stock in enumerate(top_results, 1):
            logger.info(
                "  %d. %s %s - 原始%.1f分 标准%.1f分 (%s) [%s]",
                i, stock['ts_code'], stock['name'],
                stock['total_score'], stock.get('score_normalized', stock['total_score']),
                stock['level'], stock.get('industry', '未知'),
            )
        logger.info("=" * 50)

        return top_results

    def generate_report(self, results: List[Dict]) -> str:
        """
        生成选股报告
        
        Args:
            results: 选股结果
        
        Returns:
            报告文本
        """
        active_weights = self._get_active_weights()
        report_lines = [
            "=" * 70,
            "每日选股报告（Legacy 5因子模型）",
            f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"市场环境: {self.market_score}分",
            f"策略档位: {self.strategy_profile}",
            "=" * 70,
            "",
            "因子权重配置:",
            f"  趋势因子:   {active_weights['trend']*100:.0f}%",
            f"  动量因子:   {active_weights['momentum']*100:.0f}%",
            f"  量能因子:   {active_weights['volume']*100:.0f}%",
            f"  基本面因子: {active_weights['fundamental']*100:.0f}%",
            f"  回调保护:   {active_weights['pullback']*100:.0f}%",
            "",
        ]
        
        if not results:
            report_lines.append("未筛选出符合条件的股票")
            return "\n".join(report_lines)
        
        # 行业分布统计
        industry_dist = {}
        for stock in results:
            ind = stock.get('industry', '未知')
            industry_dist[ind] = industry_dist.get(ind, 0) + 1
        
        report_lines.append(f"共筛选出 {len(results)} 只股票（每行业最多{self.max_per_industry}只）")
        report_lines.append(f"行业分布: {dict(sorted(industry_dist.items(), key=lambda x: -x[1]))}")
        report_lines.append("")
        
        for i, stock in enumerate(results, 1):
            fd = stock.get('fundamental_detail', {})
            pd_detail = stock.get('pullback_detail', {})
            qd_detail = stock.get('quality_detail', {})
            industry_dynamic = fd.get("industry_dynamic", {}) or {}
            raw_heat_score = industry_dynamic.get("industry_heat_score")
            if raw_heat_score is None:
                industry_heat_display = "-"
            else:
                try:
                    industry_heat_display = f"{float(raw_heat_score):.1f}"
                except Exception:
                    industry_heat_display = "-"
            industry_heat_level = industry_dynamic.get("industry_heat_level", "neutral")

            if is_legacy:
                report_lines.extend([
                    f"【{i}】{stock['ts_code']} {stock['name']} [{stock.get('industry', '未知')}]",
                    f"    综合得分: {stock['total_score']}分 (标准化:{stock.get('score_normalized', stock['total_score'])}分) ({stock['level']})",
                    f"    ├─ 趋势因子: {stock['trend_score']}分 (权重{active_weights['trend']*100:.0f}%)",
                    f"    ├─ 动量因子: {stock['momentum_score']}分 (权重{active_weights['momentum']*100:.0f}%)",
                    f"    ├─ 量能因子: {stock['volume_score']}分 (权重{active_weights['volume']*100:.0f}%)",
                    f"    ├─ 基本面因子: {stock['fundamental_score']}分 (权重{active_weights['fundamental']*100:.0f}%)",
                    f"    │   └─ 行业:{fd.get('industry', '未知')} 上市:{fd.get('days_listed', 0)}天",
                    f"    │      行业热度:{industry_heat_display}({industry_heat_level})",
                    f"    └─ 回调保护: {stock['pullback_score']}分 (权重{active_weights['pullback']*100:.0f}%)",
                    f"        └─ 回撤:{pd_detail.get('pullback_pct', 0):.1f}% 距MA20:{pd_detail.get('dist_to_ma20', 0):.1f}%",
                    ""
                ])
            else:
                report_lines.extend([
                    f"【{i}】{stock['ts_code']} {stock['name']} [{stock.get('industry', '未知')}]",
                    f"    综合得分: {stock['total_score']}分 ({stock['level']})",
                    f"    ├─ 趋势因子: {stock['trend_score']}分",
                    f"    ├─ 动量因子: {stock['momentum_score']}分",
                    f"    ├─ 量能因子: {stock['volume_score']}分",
                    f"    ├─ 基本面因子: {stock['fundamental_score']}分",
                    f"    ├─ 回调保护: {stock['pullback_score']}分",
                    f"    └─ 质量稳定: {stock['quality_score']}分",
                    ""
                ])
        
        report_lines.append("=" * 70)
        return "\n".join(report_lines)

