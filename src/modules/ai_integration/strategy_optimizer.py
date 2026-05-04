# -*- coding: utf-8 -*-
"""
策略参数智能优化
基于历史表现和市场环境，智能建议参数调整
"""

from datetime import datetime
from typing import Any, Dict, List, Optional

from src.core.logger import get_logger
from src.modules.ai_integration.llm_client import LLMClient

logger = get_logger("strategy_optimizer")


class StrategyOptimizer:
    """策略参数智能优化"""

    # 市场环境对应的参数倾向
    MARKET_REGIME_PARAMS = {
        "bull": {
            "name": "牛市",
            "suggestions": {"top_k": 20, "min_score": 55, "position_pct": 0.3},
            "reason": "牛市可适当放宽选股标准，增加候选数量，提高仓位",
        },
        "normal": {
            "name": "震荡市",
            "suggestions": {"top_k": 15, "min_score": 60, "position_pct": 0.2},
            "reason": "震荡市保持标准参数，控制仓位",
        },
        "bear": {
            "name": "熊市",
            "suggestions": {"top_k": 10, "min_score": 70, "position_pct": 0.1},
            "reason": "熊市提高选股门槛，减少候选，降低仓位",
        },
        "volatile": {
            "name": "高波动",
            "suggestions": {"top_k": 12, "min_score": 65, "position_pct": 0.15},
            "reason": "高波动环境提高评分门槛，降低仓位以控制风险",
        },
    }

    def __init__(self, llm_client: Optional[LLMClient] = None):
        self.llm = llm_client
        self._optimization_history: List[Dict] = []

    def analyze_strategy_performance(
        self,
        strategy_id: str,
        strategy_name: str,
        current_params: Dict[str, Any],
        performance: Dict[str, Any],
    ) -> Dict[str, Any]:
        """分析策略表现，给出优化建议"""
        win_rate = performance.get("win_rate", 0)
        avg_return = performance.get("avg_return_pct", 0)
        max_drawdown = performance.get("max_drawdown_pct", 0)
        total_trades = performance.get("total_trades", 0)
        recent_win_rate = performance.get("recent_win_rate", win_rate)

        suggestions: Dict[str, Any] = {}
        reasons: List[str] = []

        # 胜率偏低 -> 提高评分门槛
        if win_rate < 0.45 and total_trades >= 10:
            current_min_score = current_params.get("min_score", 60)
            suggested_min_score = min(current_min_score + 5, 80)
            suggestions["min_score"] = suggested_min_score
            reasons.append(f"胜率 {win_rate*100:.1f}% 偏低，建议提高评分门槛至 {suggested_min_score}")

        # 近期胜率下降 -> 收紧参数
        if recent_win_rate < win_rate - 0.1 and total_trades >= 20:
            current_top_k = current_params.get("top_k", 15)
            suggested_top_k = max(current_top_k - 3, 5)
            suggestions["top_k"] = suggested_top_k
            reasons.append(f"近期胜率 {recent_win_rate*100:.1f}% 明显下降，建议减少候选数量至 {suggested_top_k}")

        # 最大回撤过大 -> 降低仓位
        if max_drawdown < -10:
            suggestions["position_pct"] = 0.15
            reasons.append(f"最大回撤 {max_drawdown:.1f}% 过大，建议降低单只仓位至15%")

        # 平均收益高但胜率低 -> 可能是盈亏比好但需要优化入场
        if avg_return > 0 and win_rate < 0.5:
            reasons.append("盈亏比良好但胜率偏低，建议优化入场时机而非放宽选股")

        # 胜率高但收益低 -> 可能过于保守
        if win_rate > 0.7 and avg_return < 1:
            current_min_score = current_params.get("min_score", 60)
            suggested_min_score = max(current_min_score - 5, 40)
            suggestions["min_score"] = suggested_min_score
            reasons.append(f"胜率 {win_rate*100:.1f}% 高但收益 {avg_return:.2f}% 偏低，可适当放宽评分门槛至 {suggested_min_score}")

        result = {
            "strategy_id": strategy_id,
            "strategy_name": strategy_name,
            "current_params": current_params,
            "suggested_params": suggestions,
            "reasons": reasons,
            "performance_summary": {
                "win_rate": win_rate,
                "avg_return_pct": avg_return,
                "max_drawdown_pct": max_drawdown,
                "total_trades": total_trades,
            },
            "has_suggestions": len(suggestions) > 0,
            "analyzed_at": datetime.now().isoformat(),
        }

        self._optimization_history.append(result)
        return result

    def suggest_market_adaptive_params(
        self,
        market_regime: str,
        current_params: Dict[str, Any],
    ) -> Dict[str, Any]:
        """基于市场环境建议参数调整"""
        regime_config = self.MARKET_REGIME_PARAMS.get(market_regime, self.MARKET_REGIME_PARAMS["normal"])

        suggested = {}
        for key, value in regime_config["suggestions"].items():
            if key in current_params and current_params[key] != value:
                suggested[key] = value

        return {
            "market_regime": market_regime,
            "regime_name": regime_config["name"],
            "current_params": current_params,
            "suggested_params": regime_config["suggestions"],
            "changed_params": suggested,
            "reason": regime_config["reason"],
            "has_changes": len(suggested) > 0,
        }

    def ai_optimize_strategy(
        self,
        strategy_id: str,
        strategy_name: str,
        current_params: Dict,
        performance: Dict,
        market_context: str = "",
    ) -> Optional[str]:
        """AI深度优化策略"""
        if not self.llm or not self.llm.is_available:
            return None

        prompt = f"""你是量化策略优化专家，请分析以下策略并给出优化建议：

## 策略: {strategy_name} ({strategy_id})
## 当前参数
{self._format_params(current_params)}

## 历史表现
- 胜率: {performance.get('win_rate', 0)*100:.1f}%
- 平均收益: {performance.get('avg_return_pct', 0):.2f}%
- 最大回撤: {performance.get('max_drawdown_pct', 0):.1f}%
- 总交易次数: {performance.get('total_trades', 0)}

## 市场环境
{market_context or '当前市场环境正常'}

请给出：
1. 参数优化建议（具体数值）
2. 优化理由
3. 预期改善效果
4. 风险提示

用简洁专业的中文回答。"""

        try:
            return self.llm.chat(
                prompt=prompt,
                system="你是专业的量化策略优化师，擅长参数调优和策略改进。",
            )
        except Exception:
            logger.exception("AI策略优化失败")
            return None

    def compare_strategies(
        self,
        strategies: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """对比多个策略表现"""
        if not strategies:
            return {"strategies": [], "best": None, "ranking": []}

        # 按综合评分排序
        def score(s: Dict) -> float:
            wr = s.get("win_rate", 0)
            ar = s.get("avg_return_pct", 0)
            md = abs(s.get("max_drawdown_pct", 0))
            return wr * 0.4 + (ar / 10) * 0.3 + (1 - md / 20) * 0.3

        ranked = sorted(strategies, key=score, reverse=True)

        return {
            "ranking": [
                {
                    "strategy_id": s.get("strategy_id", ""),
                    "strategy_name": s.get("strategy_name", ""),
                    "win_rate": s.get("win_rate", 0),
                    "avg_return_pct": s.get("avg_return_pct", 0),
                    "max_drawdown_pct": s.get("max_drawdown_pct", 0),
                    "composite_score": round(score(s), 4),
                }
                for s in ranked
            ],
            "best": {
                "strategy_id": ranked[0].get("strategy_id", ""),
                "strategy_name": ranked[0].get("strategy_name", ""),
            } if ranked else None,
        }

    def get_optimization_history(self, limit: int = 10) -> List[Dict]:
        return self._optimization_history[-limit:]

    def _format_params(self, params: Dict) -> str:
        return "\n".join(f"- {k}: {v}" for k, v in params.items()) or "无参数"
