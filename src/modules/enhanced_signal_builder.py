"""
信号构建 - 从 EnhancedHybridSystem 拆分出的信号构建模块。
原方法: _build_buy_signal, _build_false_signal, _wrap_signal_metadata,
        _get_dynamic_signal_thresholds, _calculate_total_signal_score
"""

from datetime import datetime
from typing import Any, Dict, List, Optional


class SignalBuilder:
    """信号构建器，负责买入信号的构建、包装、评分。"""

    def __init__(self, hybrid_system):
        """
        Parameters
        ----------
        hybrid_system : EnhancedHybridSystem
            持有 config、logger 等成员的主系统实例。
        """
        self._hs = hybrid_system

    # ── 以下方法从 EnhancedHybridSystem 原样移入 ──

    def _wrap_signal_metadata(
        self,
        symbol: str,
        price: float,
        signal_type: str,
        source: str,
    ) -> Dict[str, Any]:
        """包装信号元数据。"""
        return {
            "symbol": symbol,
            "price": price,
            "signal_type": signal_type,
            "source": source,
            "created_at": datetime.now().isoformat(),
        }

    def _build_false_signal(
        self,
        symbol: str,
        reason: str,
    ) -> Dict[str, Any]:
        """构建一个假信号（用于占位/测试）。"""
        return {
            "symbol": symbol,
            "is_false": True,
            "reason": reason,
            "created_at": datetime.now().isoformat(),
        }

    def _get_dynamic_signal_thresholds(
        self,
        market_score: float,
    ) -> Dict[str, float]:
        """根据市场评分动态获取信号阈值。"""
        if market_score >= 70:
            return {"min_score": 60, "max_signals": 10}
        elif market_score >= 50:
            return {"min_score": 70, "max_signals": 8}
        elif market_score >= 30:
            return {"min_score": 80, "max_signals": 5}
        else:
            return {"min_score": 85, "max_signals": 3}

    def _calculate_total_signal_score(
        self,
        base_score: float,
        market_score: float,
        adjustments: Optional[Dict[str, float]] = None,
    ) -> float:
        """计算最终信号总分。"""
        score = base_score
        if adjustments:
            for factor, weight in adjustments.items():
                score += weight
        # 加入市场环境加权
        market_factor = (market_score - 50) / 100
        score += market_factor * 10
        return max(0.0, min(100.0, score))

    def _build_buy_signal(
        self,
        symbol: str,
        name: str,
        price: float,
        score: float,
        reason: str,
        strategy_profile: str = "default",
        extra: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """构建标准买入信号。"""
        signal = {
            "symbol": symbol,
            "name": name,
            "price": price,
            "score": round(score, 2),
            "reason": reason,
            "strategy_profile": strategy_profile,
            "signal_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        if extra:
            signal.update(extra)
        return signal
