# -*- coding: utf-8 -*-
"""
信号引擎核心模块

提供统一的买点信号检测、验证和评分管道，
支持多维度验证和可配置的信号过滤。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, time
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from src.core.logger import get_logger

logger = get_logger("signal_engine")


@dataclass
class EntryContext:
    """买点上下文"""
    symbol: str
    current_price: float
    minute_data: Optional[pd.DataFrame] = None
    daily_data: Optional[pd.DataFrame] = None
    market_context: Dict[str, Any] = field(default_factory=dict)
    candidate_info: Dict[str, Any] = field(default_factory=dict)


@dataclass
class EntrySignal:
    """买点信号"""
    symbol: str
    signal_type: str = ""
    trigger_price: float = 0.0
    stop_loss: float = 0.0
    take_profit: float = 0.0
    confidence: float = 0.0
    risk_level: str = "medium"
    factors: Dict[str, float] = field(default_factory=dict)
    reason: str = ""
    timestamp: Optional[datetime] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "symbol": self.symbol,
            "signal_type": self.signal_type,
            "trigger_price": self.trigger_price,
            "stop_loss": self.stop_loss,
            "take_profit": self.take_profit,
            "confidence": self.confidence,
            "risk_level": self.risk_level,
            "factors": self.factors,
            "reason": self.reason,
            "timestamp": self.timestamp.strftime("%Y-%m-%d %H:%M:%S") if self.timestamp else "",
        }


@dataclass
class ValidationResult:
    """验证结果"""
    validator_name: str
    passed: bool
    score: float = 0.0
    details: Dict[str, Any] = field(default_factory=dict)


class BaseValidator(ABC):
    """验证器基类"""

    @abstractmethod
    def validate(self, context: EntryContext) -> ValidationResult:
        pass

    @property
    @abstractmethod
    def name(self) -> str:
        pass

    @property
    def weight(self) -> float:
        return 1.0


class TrendValidator(BaseValidator):
    """趋势验证器"""

    @property
    def name(self) -> str:
        return "trend"

    @property
    def weight(self) -> float:
        return 0.30

    def validate(self, context: EntryContext) -> ValidationResult:
        data = context.minute_data
        if data is None or len(data) < 20:
            return ValidationResult(self.name, False, 0.0, {"reason": "data_insufficient"})

        close = data["close"].values if isinstance(data, pd.DataFrame) else data
        ma5 = np.mean(close[-5:])
        ma10 = np.mean(close[-10:])
        ma20 = np.mean(close[-20:])
        current = close[-1]

        trend_aligned = (current > ma5) and (ma5 > ma10) and (ma10 > ma20)
        price_above_ma5 = current > ma5

        score = 0.0
        if trend_aligned:
            score = 1.0
        elif price_above_ma5:
            score = 0.5

        return ValidationResult(
            self.name,
            passed=price_above_ma5,
            score=score,
            details={
                "trend_aligned": trend_aligned,
                "price_above_ma5": price_above_ma5,
                "ma5": round(float(ma5), 3),
                "ma10": round(float(ma10), 3),
                "ma20": round(float(ma20), 3),
            },
        )


class VolumeValidator(BaseValidator):
    """量能验证器"""

    @property
    def name(self) -> str:
        return "volume"

    @property
    def weight(self) -> float:
        return 0.25

    def validate(self, context: EntryContext) -> ValidationResult:
        data = context.minute_data
        if data is None or len(data) < 10:
            return ValidationResult(self.name, True, 0.5, {"reason": "data_insufficient_skipped"})

        volume = data["volume"].values if isinstance(data, pd.DataFrame) else np.array(data)
        recent_vol = np.mean(volume[-3:])
        prev_vol = np.mean(volume[-10:-3])

        if prev_vol <= 0:
            return ValidationResult(self.name, True, 0.5, {"reason": "zero_volume_skipped"})

        vol_ratio = recent_vol / prev_vol
        is_shrinking = vol_ratio < 0.85
        is_normal = vol_ratio < 2.0

        score = 0.0
        if is_shrinking:
            score = 1.0
        elif is_normal:
            score = 0.6

        return ValidationResult(
            self.name,
            passed=is_normal,
            score=score,
            details={
                "vol_ratio": round(float(vol_ratio), 3),
                "is_shrinking": is_shrinking,
                "is_normal": is_normal,
            },
        )


class SupportValidator(BaseValidator):
    """支撑位验证器"""

    @property
    def name(self) -> str:
        return "support"

    @property
    def weight(self) -> float:
        return 0.25

    def validate(self, context: EntryContext) -> ValidationResult:
        data = context.minute_data
        if data is None or len(data) < 5:
            return ValidationResult(self.name, True, 0.5, {"reason": "data_insufficient_skipped"})

        low = data["low"].values if isinstance(data, pd.DataFrame) else np.array(data)
        recent_lows = low[-5:]
        rising_lows = all(recent_lows[i] >= recent_lows[i - 1] * 0.998 for i in range(1, len(recent_lows)))

        score = 1.0 if rising_lows else 0.3

        return ValidationResult(
            self.name,
            passed=rising_lows,
            score=score,
            details={
                "rising_lows": rising_lows,
                "recent_lows": [round(float(x), 3) for x in recent_lows],
            },
        )


class TimeFilterValidator(BaseValidator):
    """时间过滤验证器"""

    AVOID_PERIODS = [
        (time(9, 30), time(9, 45)),
        (time(11, 30), time(13, 0)),
    ]

    @property
    def name(self) -> str:
        return "time_filter"

    @property
    def weight(self) -> float:
        return 0.20

    def validate(self, context: EntryContext) -> ValidationResult:
        now = datetime.now().time()

        in_avoid_period = any(start <= now <= end for start, end in self.AVOID_PERIODS)
        in_trade_hours = time(9, 30) <= now <= time(15, 0)

        passed = in_trade_hours and not in_avoid_period
        score = 0.0 if in_avoid_period else (1.0 if in_trade_hours else 0.3)

        return ValidationResult(
            self.name,
            passed=passed,
            score=score,
            details={
                "in_trade_hours": in_trade_hours,
                "in_avoid_period": in_avoid_period,
                "current_time": now.strftime("%H:%M"),
            },
        )


class SignalEngine:
    """信号引擎 - 统一管理买点检测与验证"""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        self.validators: List[BaseValidator] = [
            TrendValidator(),
            VolumeValidator(),
            SupportValidator(),
            TimeFilterValidator(),
        ]
        self.min_confidence = self.config.get("min_confidence", 0.6)

    def add_validator(self, validator: BaseValidator):
        self.validators.append(validator)

    def detect_signal(self, context: EntryContext) -> Optional[EntrySignal]:
        """检测买点信号"""
        validation_results = []
        for validator in self.validators:
            result = validator.validate(context)
            validation_results.append(result)
            if not result.passed:
                logger.debug(
                    "Signal validation failed: %s for %s",
                    validator.name,
                    context.symbol,
                )
                return None

        confidence = self._calculate_confidence(validation_results)
        if confidence < self.min_confidence:
            return None

        risk_level = self._assess_risk(confidence, validation_results)

        return EntrySignal(
            symbol=context.symbol,
            signal_type=self._determine_signal_type(context, validation_results),
            trigger_price=context.current_price,
            stop_loss=self._calculate_stop_loss(context),
            take_profit=self._calculate_take_profit(context),
            confidence=confidence,
            risk_level=risk_level,
            factors=self._extract_factors(validation_results),
            reason=self._build_reason(validation_results),
            timestamp=datetime.now(),
        )

    def _calculate_confidence(self, results: List[ValidationResult]) -> float:
        """计算综合置信度"""
        total_weight = sum(v.weight for v in self.validators)
        weighted_score = sum(
            r.score * self.validators[i].weight
            for i, r in enumerate(results)
        )
        return weighted_score / total_weight if total_weight > 0 else 0.0

    def _assess_risk(self, confidence: float, results: List[ValidationResult]) -> str:
        """评估风险等级"""
        if confidence >= 0.8:
            return "low"
        elif confidence >= 0.6:
            return "medium"
        else:
            return "high"

    def _determine_signal_type(self, context: EntryContext, results: List[ValidationResult]) -> str:
        """判断信号类型"""
        data = context.minute_data
        if data is None or len(data) < 20:
            return "unknown"

        close = data["close"].values if isinstance(data, pd.DataFrame) else np.array(data)
        ma20 = np.mean(close[-20:])
        current = close[-1]

        if current > ma20 * 1.02:
            return "breakout"
        elif abs(current - ma20) / ma20 < 0.01:
            return "pullback"
        else:
            return "consolidation"

    def _calculate_stop_loss(self, context: EntryContext) -> float:
        """计算止损价"""
        data = context.minute_data
        if data is None or len(data) < 5:
            return context.current_price * 0.95

        low = data["low"].values if isinstance(data, pd.DataFrame) else np.array(data)
        recent_low = np.min(low[-5:])
        return min(recent_low * 0.99, context.current_price * 0.95)

    def _calculate_take_profit(self, context: EntryContext) -> float:
        """计算止盈价"""
        return context.current_price * 1.03

    def _extract_factors(self, results: List[ValidationResult]) -> Dict[str, float]:
        """提取因子值"""
        factors = {}
        for result in results:
            factors[f"{result.validator_name}_score"] = round(result.score, 3)
            for key, value in result.details.items():
                if isinstance(value, (int, float, bool)):
                    factors[f"{result.validator_name}_{key}"] = value
        return factors

    def _build_reason(self, results: List[ValidationResult]) -> str:
        """构建信号原因描述"""
        parts = []
        for result in results:
            if result.score >= 0.8:
                parts.append(f"{result.validator_name}:strong")
            elif result.score >= 0.5:
                parts.append(f"{result.validator_name}:moderate")
            else:
                parts.append(f"{result.validator_name}:weak")
        return " | ".join(parts)
