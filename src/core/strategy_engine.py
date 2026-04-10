# -*- coding: utf-8 -*-
"""
策略引擎核心抽象层

提供统一的策略基类、注册机制和执行框架，
使各选股策略可独立开发、测试和部署。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from src.core.logger import get_logger

logger = get_logger("strategy_engine")


@dataclass
class SelectionContext:
    """选股上下文"""
    trade_date: str
    market_state: str = "NEUTRAL"
    market_score: float = 50.0
    candidate_pool: List[str] = field(default_factory=list)
    constraints: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SelectionResult:
    """选股结果"""
    symbol: str
    name: str = ""
    score: float = 0.0
    rank: int = 0
    factors: Dict[str, float] = field(default_factory=dict)
    confidence: float = 0.0
    strategy_name: str = ""
    strategy_version: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "symbol": self.symbol,
            "name": self.name,
            "score": self.score,
            "rank": self.rank,
            "factors": self.factors,
            "confidence": self.confidence,
            "strategy_name": self.strategy_name,
            "strategy_version": self.strategy_version,
            "metadata": self.metadata,
        }


class BaseStrategy(ABC):
    """策略基类 - 所有选股策略必须继承此类"""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        self.name: str = self.config.get("name", self.__class__.__name__)
        self.version: str = self.config.get("version", "1.0.0")
        self.frozen_at: Optional[str] = self.config.get("frozen_at")
        self._validate_config()

    def _validate_config(self):
        """验证配置参数有效性"""
        pass

    @abstractmethod
    def select(self, context: SelectionContext, data: pd.DataFrame) -> List[SelectionResult]:
        """执行选股"""
        pass

    @abstractmethod
    def get_required_fields(self) -> List[str]:
        """获取所需数据字段"""
        pass

    def validate_result(self, result: SelectionResult) -> bool:
        """验证选股结果"""
        if not result.symbol:
            return False
        if result.score < self.config.get("min_score", 0):
            return False
        return True

    def get_info(self) -> Dict[str, Any]:
        """获取策略信息"""
        return {
            "name": self.name,
            "version": self.version,
            "frozen_at": self.frozen_at,
            "required_fields": self.get_required_fields(),
            "config_keys": list(self.config.keys()),
        }


class StrategyRegistry:
    """策略注册表 - 管理所有已注册策略"""

    _strategies: Dict[str, BaseStrategy] = {}
    _factories: Dict[str, type] = {}

    @classmethod
    def register(cls, name: str, strategy_class: Optional[type] = None):
        """注册策略类（可用作装饰器或直接调用）"""
        def decorator(klass: type) -> type:
            cls._factories[name] = klass
            logger.info("Strategy registered: %s -> %s", name, klass.__name__)
            return klass

        if strategy_class is not None:
            return decorator(strategy_class)
        return decorator

    @classmethod
    def create(cls, name: str, config: Optional[Dict[str, Any]] = None) -> Optional[BaseStrategy]:
        """创建策略实例"""
        factory = cls._factories.get(name)
        if factory is None:
            logger.error("Strategy not found: %s", name)
            return None
        try:
            instance = factory(config=config)
            cls._strategies[name] = instance
            return instance
        except Exception as exc:
            logger.error("Create strategy failed: %s -> %s", name, exc)
            return None

    @classmethod
    def get(cls, name: str) -> Optional[BaseStrategy]:
        """获取已创建的策略实例"""
        return cls._strategies.get(name)

    @classmethod
    def list_available(cls) -> List[str]:
        """列出所有可用策略名称"""
        return list(cls._factories.keys())

    @classmethod
    def list_active(cls) -> Dict[str, Dict[str, Any]]:
        """列出所有活跃策略信息"""
        return {name: strategy.get_info() for name, strategy in cls._strategies.items()}


class StrategyEngine:
    """策略引擎 - 统一调度选股执行"""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        self.registry = StrategyRegistry()
        self._results_cache: Dict[str, List[SelectionResult]] = {}

    def register_strategy(self, name: str, strategy_class: type, config: Optional[Dict[str, Any]] = None) -> bool:
        """注册并创建策略实例"""
        self.registry.register(name)(strategy_class)
        instance = self.registry.create(name, config)
        return instance is not None

    def run_selection(
        self,
        context: SelectionContext,
        strategy_names: Optional[List[str]] = None,
        data: Optional[pd.DataFrame] = None,
    ) -> List[SelectionResult]:
        """执行选股"""
        names = strategy_names or self.registry.list_available()
        all_results: List[SelectionResult] = []

        for name in names:
            strategy = self.registry.get(name)
            if strategy is None:
                strategy = self.registry.create(name)
            if strategy is None:
                continue

            try:
                results = strategy.select(context, data)
                for r in results:
                    r.strategy_name = name
                    r.strategy_version = strategy.version
                    if strategy.validate_result(r):
                        all_results.append(r)
            except Exception as exc:
                logger.error("Strategy %s execution failed: %s", name, exc)

        merged = self._merge_results(all_results)
        for idx, r in enumerate(merged):
            r.rank = idx + 1

        cache_key = f"{context.trade_date}:{','.join(names or [])}"
        self._results_cache[cache_key] = merged

        return merged

    def _merge_results(self, results: List[SelectionResult]) -> List[SelectionResult]:
        """去重合并选股结果"""
        seen: Dict[str, SelectionResult] = {}
        for r in results:
            if r.symbol in seen:
                existing = seen[r.symbol]
                if r.score > existing.score:
                    seen[r.symbol] = r
            else:
                seen[r.symbol] = r
        sorted_results = sorted(seen.values(), key=lambda x: x.score, reverse=True)
        max_candidates = self.config.get("max_candidates", 15)
        return sorted_results[:max_candidates]
