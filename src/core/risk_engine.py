# -*- coding: utf-8 -*-
"""
风控引擎模块

将风控规则从监控和交易模块中解耦，
提供可配置、可扩展的风险控制框架。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from src.core.logger import get_logger

logger = get_logger("risk_engine")


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class CircuitState(str, Enum):
    NORMAL = "normal"
    SOFT = "soft"
    HARD = "hard"


@dataclass
class RiskAssessment:
    """风险评估结果"""
    risk_level: RiskLevel = RiskLevel.LOW
    circuit_state: CircuitState = CircuitState.NORMAL
    position_multiplier: float = 1.0
    max_signals: int = 4
    score_boost: float = 0.0
    push_boost: float = 1.0
    reasons: List[str] = field(default_factory=list)
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "risk_level": self.risk_level.value,
            "circuit_state": self.circuit_state.value,
            "position_multiplier": self.position_multiplier,
            "max_signals": self.max_signals,
            "score_boost": self.score_boost,
            "push_boost": self.push_boost,
            "reasons": self.reasons,
            "details": self.details,
        }


class BaseRiskRule(ABC):
    """风控规则基类"""

    @abstractmethod
    def evaluate(self, context: Dict[str, Any]) -> RiskAssessment:
        pass

    @property
    @abstractmethod
    def name(self) -> str:
        pass

    @property
    def priority(self) -> int:
        return 100


class MarketCircuitBreaker(BaseRiskRule):
    """市场熔断规则"""

    @property
    def name(self) -> str:
        return "market_circuit_breaker"

    @property
    def priority(self) -> int:
        return 10

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        self.soft_trigger_drop = self.config.get("circuit_soft_trigger_drop_pct", -1.2)
        self.hard_trigger_drop = self.config.get("circuit_hard_trigger_drop_pct", -2.0)
        self.soft_breadth = self.config.get("circuit_soft_breadth_threshold", 0.35)
        self.hard_breadth = self.config.get("circuit_hard_breadth_threshold", 0.25)

    def evaluate(self, context: Dict[str, Any]) -> RiskAssessment:
        market_drop = context.get("market_drop_pct", 0.0)
        breadth = context.get("breadth_ratio", 1.0)

        if market_drop <= self.hard_trigger_drop or breadth <= self.hard_breadth:
            return RiskAssessment(
                risk_level=RiskLevel.CRITICAL,
                circuit_state=CircuitState.HARD,
                position_multiplier=0.0,
                max_signals=0,
                score_boost=self.config.get("circuit_soft_score_boost", 3.0) * 2,
                push_boost=self.config.get("circuit_soft_push_boost", 2.0) * 2,
                reasons=["hard_circuit_triggered"],
                details={"market_drop": market_drop, "breadth": breadth},
            )

        if market_drop <= self.soft_trigger_drop or breadth <= self.soft_breadth:
            return RiskAssessment(
                risk_level=RiskLevel.HIGH,
                circuit_state=CircuitState.SOFT,
                position_multiplier=self.config.get("circuit_soft_position_multiplier", 0.5),
                max_signals=2,
                score_boost=self.config.get("circuit_soft_score_boost", 3.0),
                push_boost=self.config.get("circuit_soft_push_boost", 2.0),
                reasons=["soft_circuit_triggered"],
                details={"market_drop": market_drop, "breadth": breadth},
            )

        return RiskAssessment(
            circuit_state=CircuitState.NORMAL,
            reasons=["normal"],
        )


class MarketGateRule(BaseRiskRule):
    """市场闸门规则"""

    @property
    def name(self) -> str:
        return "market_gate"

    @property
    def priority(self) -> int:
        return 20

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        self.force_defensive_regimes = self.config.get(
            "market_gate_force_defensive_regimes",
            ["WEAK_BEAR", "BEAR", "STRONG_BEAR"],
        )
        self.defensive_position_multiplier = self.config.get(
            "market_gate_defensive_position_multiplier", 0.6
        )
        self.defensive_max_signals = self.config.get(
            "market_gate_defensive_max_signals_per_round", 2
        )
        self.normal_max_signals = self.config.get(
            "market_gate_normal_max_signals_per_round", 4
        )

    def evaluate(self, context: Dict[str, Any]) -> RiskAssessment:
        market_regime = context.get("market_regime", "NEUTRAL")

        if market_regime in self.force_defensive_regimes:
            return RiskAssessment(
                risk_level=RiskLevel.HIGH,
                position_multiplier=self.defensive_position_multiplier,
                max_signals=self.defensive_max_signals,
                score_boost=self.config.get("market_gate_defensive_score_boost", 4.0),
                push_boost=self.config.get("market_gate_defensive_push_boost", 4.0),
                reasons=["defensive_regime"],
                details={"market_regime": market_regime},
            )

        return RiskAssessment(
            max_signals=self.normal_max_signals,
            reasons=["normal_regime"],
            details={"market_regime": market_regime},
        )


class FeedbackGuardRule(BaseRiskRule):
    """反馈守卫规则"""

    @property
    def name(self) -> str:
        return "feedback_guard"

    @property
    def priority(self) -> int:
        return 30

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}

    def evaluate(self, context: Dict[str, Any]) -> RiskAssessment:
        guard_level = context.get("feedback_guard_level", "normal")

        if guard_level == "defensive":
            return RiskAssessment(
                risk_level=RiskLevel.HIGH,
                position_multiplier=self.config.get(
                    "feedback_guard_position_multiplier_defensive", 0.65
                ),
                max_signals=self.config.get("feedback_guard_max_signals_defensive", 2),
                score_boost=self.config.get(
                    "feedback_guard_threshold_boost_defensive", 3.0
                ),
                push_boost=self.config.get(
                    "feedback_guard_push_boost_defensive", 2.0
                ),
                reasons=["feedback_defensive"],
            )

        if guard_level == "caution":
            return RiskAssessment(
                risk_level=RiskLevel.MEDIUM,
                position_multiplier=self.config.get(
                    "feedback_guard_position_multiplier_caution", 0.85
                ),
                max_signals=self.config.get("feedback_guard_max_signals_caution", 3),
                score_boost=self.config.get(
                    "feedback_guard_threshold_boost_caution", 1.5
                ),
                push_boost=self.config.get(
                    "feedback_guard_push_boost_caution", 1.0
                ),
                reasons=["feedback_caution"],
            )

        return RiskAssessment(reasons=["feedback_normal"])


class PositionLimitRule(BaseRiskRule):
    """持仓限制规则"""

    @property
    def name(self) -> str:
        return "position_limit"

    @property
    def priority(self) -> int:
        return 40

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        self.max_positions = self.config.get("max_positions", 5)
        self.single_position_pct = self.config.get("single_position_pct", 0.1)
        self.per_signal_cap = self.config.get("position_linkage_per_signal_cap", 0.12)

    def evaluate(self, context: Dict[str, Any]) -> RiskAssessment:
        current_positions = context.get("current_positions", 0)
        total_position_pct = context.get("total_position_pct", 0.0)

        if current_positions >= self.max_positions:
            return RiskAssessment(
                risk_level=RiskLevel.HIGH,
                position_multiplier=0.0,
                max_signals=0,
                reasons=["max_positions_reached"],
                details={"current": current_positions, "max": self.max_positions},
            )

        if total_position_pct >= 0.8:
            return RiskAssessment(
                risk_level=RiskLevel.MEDIUM,
                position_multiplier=0.3,
                max_signals=1,
                reasons=["high_total_position"],
                details={"total_pct": total_position_pct},
            )

        return RiskAssessment(reasons=["position_ok"])


class RiskEngine:
    """风控引擎 - 统一管理风控规则"""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        self.rules: List[BaseRiskRule] = []
        self._register_default_rules()

    def _register_default_rules(self):
        self.rules = [
            MarketCircuitBreaker(self.config),
            MarketGateRule(self.config),
            FeedbackGuardRule(self.config),
            PositionLimitRule(self.config),
        ]
        self.rules.sort(key=lambda r: r.priority)

    def add_rule(self, rule: BaseRiskRule):
        self.rules.append(rule)
        self.rules.sort(key=lambda r: r.priority)

    def assess(self, context: Dict[str, Any]) -> RiskAssessment:
        """执行风险评估 - 取最严格的结果"""
        final = RiskAssessment(reasons=["no_rules_evaluated"])

        for rule in self.rules:
            try:
                assessment = rule.evaluate(context)
                final = self._merge_assessment(final, assessment, rule.name)
            except Exception as exc:
                logger.error("Risk rule %s evaluation failed: %s", rule.name, exc)

        return final

    def _merge_assessment(
        self, current: RiskAssessment, new: RiskAssessment, rule_name: str
    ) -> RiskAssessment:
        """合并风险评估 - 取更严格的结果"""
        risk_order = {
            RiskLevel.LOW: 0,
            RiskLevel.MEDIUM: 1,
            RiskLevel.HIGH: 2,
            RiskLevel.CRITICAL: 3,
        }
        circuit_order = {
            CircuitState.NORMAL: 0,
            CircuitState.SOFT: 1,
            CircuitState.HARD: 2,
        }

        merged = RiskAssessment(
            risk_level=max(current.risk_level, new.risk_level, key=lambda x: risk_order[x]),
            circuit_state=max(current.circuit_state, new.circuit_state, key=lambda x: circuit_order[x]),
            position_multiplier=min(current.position_multiplier, new.position_multiplier),
            max_signals=min(current.max_signals, new.max_signals),
            score_boost=max(current.score_boost, new.score_boost),
            push_boost=max(current.push_boost, new.push_boost),
            reasons=current.reasons + [f"{rule_name}:{new.reasons[0]}"] if new.reasons else current.reasons,
            details={**current.details, rule_name: new.details},
        )

        return merged

    def check_signal_allowed(
        self, context: Dict[str, Any], signal_count: int
    ) -> Tuple[bool, RiskAssessment]:
        """检查是否允许发出信号"""
        assessment = self.assess(context)
        allowed = signal_count < assessment.max_signals
        return allowed, assessment
