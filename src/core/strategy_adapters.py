# -*- coding: utf-8 -*-
"""
策略适配器模块

将现有策略类桥接到统一的策略引擎框架，
无需修改原策略代码即可实现标准化管理。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import pandas as pd

from src.core.logger import get_logger
from src.core.strategy_engine import BaseStrategy, SelectionContext, SelectionResult

logger = get_logger("strategy_adapters")


class FinalStrategyAdapter(BaseStrategy):
    """强势回调二次启动策略适配器"""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self._strategy = None

    def _get_strategy(self):
        if self._strategy is None:
            from src.modules.final_strategy import FinalStrategy
            self._strategy = FinalStrategy(config=self.config)
        return self._strategy

    def select(self, context: SelectionContext, data: pd.DataFrame) -> List[SelectionResult]:
        strategy = self._get_strategy()
        if data is None or data.empty:
            return []

        try:
            featured = strategy.prepare_features(data)
            filtered = strategy.apply_base_filter(featured)
            strength = strategy.apply_strength_filter(filtered)
            pullback = strategy.apply_pullback_filter(strength)
            volume = strategy.apply_volume_filter(pullback)
            trend = strategy.apply_trend_filter(volume)
            scored = strategy.apply_scoring(trend)

            if scored.empty:
                return []

            results = []
            for _, row in scored.head(self.config.get("max_candidates", 15)).iterrows():
                results.append(SelectionResult(
                    symbol=str(row.get("ts_code", "")),
                    name=str(row.get("name", "")),
                    score=float(row.get("total_score", 0)),
                    factors={
                        "strength_score": float(row.get("strength_score", 0)),
                        "pullback_score": float(row.get("pullback_score", 0)),
                        "trend_score": float(row.get("trend_score", 0)),
                        "volume_score": float(row.get("volume_score", 0)),
                    },
                    confidence=float(row.get("total_score", 0)) / 100.0,
                    strategy_name=self.name,
                    strategy_version=self.version,
                ))
            return results
        except Exception as exc:
            logger.error("FinalStrategyAdapter select failed: %s", exc)
            return []

    def get_required_fields(self) -> List[str]:
        return ["ts_code", "trade_date", "open", "high", "low", "close", "vol", "amount"]


class BreakoutStrategyAdapter(BaseStrategy):
    """突破策略适配器"""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self._strategy = None

    def _get_strategy(self):
        if self._strategy is None:
            from src.modules.breakout_strategy import BreakoutStrategy
            self._strategy = BreakoutStrategy(config=self.config)
        return self._strategy

    def select(self, context: SelectionContext, data: pd.DataFrame) -> List[SelectionResult]:
        strategy = self._get_strategy()
        if data is None or data.empty:
            return []

        try:
            candidates = strategy.run_selection(data, context.trade_date)
            results = []
            for candidate in candidates:
                results.append(SelectionResult(
                    symbol=str(candidate.get("symbol", candidate.get("ts_code", ""))),
                    name=str(candidate.get("name", "")),
                    score=float(candidate.get("score", candidate.get("total_score", 0))),
                    factors=candidate.get("factors", {}),
                    confidence=float(candidate.get("score", 0)) / 100.0,
                    strategy_name=self.name,
                    strategy_version=self.version,
                    metadata=candidate,
                ))
            return results
        except Exception as exc:
            logger.error("BreakoutStrategyAdapter select failed: %s", exc)
            return []

    def get_required_fields(self) -> List[str]:
        return ["ts_code", "trade_date", "open", "high", "low", "close", "vol", "amount"]


class StrongStartStrategyAdapter(BaseStrategy):
    """强势启动策略适配器"""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self._strategy = None

    def _get_strategy(self):
        if self._strategy is None:
            from src.modules.strong_start_strategy import StrongStartStrategy
            self._strategy = StrongStartStrategy(config=self.config)
        return self._strategy

    def select(self, context: SelectionContext, data: pd.DataFrame) -> List[SelectionResult]:
        strategy = self._get_strategy()
        if data is None or data.empty:
            return []

        try:
            candidates = strategy.run_selection(data, context.trade_date)
            results = []
            for candidate in candidates:
                results.append(SelectionResult(
                    symbol=str(candidate.get("symbol", candidate.get("ts_code", ""))),
                    name=str(candidate.get("name", "")),
                    score=float(candidate.get("score", candidate.get("total_score", 0))),
                    factors=candidate.get("factors", {}),
                    confidence=float(candidate.get("score", 0)) / 100.0,
                    strategy_name=self.name,
                    strategy_version=self.version,
                    metadata=candidate,
                ))
            return results
        except Exception as exc:
            logger.error("StrongStartStrategyAdapter select failed: %s", exc)
            return []

    def get_required_fields(self) -> List[str]:
        return ["ts_code", "trade_date", "open", "high", "low", "close", "vol", "amount"]


def register_default_strategies(engine_config: Optional[Dict[str, Any]] = None) -> Dict[str, BaseStrategy]:
    """注册所有默认策略"""
    from src.core.strategy_engine import StrategyRegistry

    strategies = {}
    adapters = {
        "final": FinalStrategyAdapter,
        "breakout": BreakoutStrategyAdapter,
        "strong_start": StrongStartStrategyAdapter,
    }

    for name, adapter_class in adapters.items():
        config = (engine_config or {}).get(name, {})
        config["name"] = name
        StrategyRegistry.register(name)(adapter_class)
        instance = StrategyRegistry.create(name, config)
        if instance:
            strategies[name] = instance

    return strategies
