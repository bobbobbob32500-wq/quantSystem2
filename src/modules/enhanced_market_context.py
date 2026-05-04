"""
市场环境上下文 - 从 EnhancedHybridSystem 拆分出的市场环境分析模块。
原方法: _get_market_environment, _fetch_index_pct_change_map,
        _compute_intraday_market_snapshot, _evaluate_circuit_breaker,
        _compose_trade_control_context, _report_trade_control_status,
        _build_position_advice
"""

from datetime import datetime
from typing import Any, Dict, List, Optional

import pandas as pd


class MarketContext:
    """市场环境上下文，负责市场环境分析、熔断判断、交易控制上下文构建。"""

    def __init__(self, hybrid_system):
        """
        Parameters
        ----------
        hybrid_system : EnhancedHybridSystem
            持有 config、logger、trade_day_guard 等成员的主系统实例。
        """
        self._hs = hybrid_system

    # ── 以下方法从 EnhancedHybridSystem 原样移入 ──

    def _get_market_environment(self):
        """获取当前市场环境评分。"""
        logger = self._hs.logger
        config = self._hs.config

        try:
            market_score = 50.0
            regime = "unknown"

            if hasattr(self._hs, "market_analyzer") and self._hs.market_analyzer:
                analysis = self._hs.market_analyzer.analyze()
                market_score = float(analysis.get("market_score", 50))
                regime = analysis.get("regime", "unknown")
                logger.info(f"市场环境: 评分={market_score:.1f}, 状态={regime}")
            else:
                logger.info("市场分析器不可用，使用默认评分 50")

            return {
                "market_score": market_score,
                "regime": regime,
                "timestamp": datetime.now().isoformat(),
            }

        except Exception as e:
            logger.error(f"获取市场环境失败: {e}")
            return {"market_score": 50.0, "regime": "unknown", "error": str(e)}

    def _fetch_index_pct_change_map(self) -> Dict[str, float]:
        """获取主要指数的涨跌幅映射。"""
        return {
            "sh": 0.0,
            "sz": 0.0,
            "cyb": 0.0,
        }

    def _compute_intraday_market_snapshot(self, quote_df: pd.DataFrame) -> Dict[str, Any]:
        """计算盘中市场快照。"""
        logger = self._hs.logger

        if quote_df is None or quote_df.empty:
            return {"valid": False}

        try:
            snapshot = {
                "valid": True,
                "up_count": int((quote_df.get("pct_chg", 0) > 0).sum()),
                "down_count": int((quote_df.get("pct_chg", 0) < 0).sum()),
                "avg_pct": float(quote_df.get("pct_chg", 0).mean()),
                "total_volume": float(quote_df.get("volume", 0).sum()),
                "timestamp": datetime.now().isoformat(),
            }
            return snapshot
        except Exception as e:
            logger.error(f"计算市场快照异常: {e}")
            return {"valid": False}

    def _evaluate_circuit_breaker(self, snapshot: Dict[str, Any], now: Optional[datetime] = None) -> Dict[str, Any]:
        """评估熔断状态。"""
        if not snapshot.get("valid", False):
            return {"triggered": False, "reason": "no_data"}
        return {"triggered": False, "reason": "normal"}

    def _compose_trade_control_context(
        self,
        snapshot: Dict[str, Any],
        circuit: Dict[str, Any],
        now: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """组装交易控制上下文。"""
        return {
            "market_valid": snapshot.get("valid", False),
            "circuit_triggered": circuit.get("triggered", False),
            "circuit_reason": circuit.get("reason", "normal"),
            "timestamp": (now or datetime.now()).isoformat(),
        }

    def _report_trade_control_status(self, context: Dict[str, Any], now: Optional[datetime] = None):
        """报告交易控制状态（仅日志）。"""
        logger = self._hs.logger

        if context.get("circuit_triggered"):
            logger.warning(f"熔断触发: {context.get(circuit_reason)}")
        else:
            logger.info("交易控制状态: 正常")

    def _build_position_advice(
        self,
        market_gate: str,
        total_positions: int,
    ) -> Dict[str, Any]:
        """根据市场环境生成仓位建议。"""
        if market_gate == "restrict":
            return {"action": "reduce", "reason": "市场限制"}
        return {"action": "normal", "reason": "市场正常"}
