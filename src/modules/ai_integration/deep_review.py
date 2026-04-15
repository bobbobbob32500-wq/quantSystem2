# -*- coding: utf-8 -*-
"""
深度复盘分析
错误操作识别、成功模式提炼、改进建议生成
"""

from datetime import datetime
from typing import Any, Dict, List, Optional

from src.core.logger import get_logger
from src.modules.ai_integration.llm_client import LLMClient

logger = get_logger("deep_review")


class DeepReviewAnalyzer:
    """深度复盘分析"""

    # 常见错误模式
    MISTAKE_PATTERNS = {
        "chase_high": {
            "name": "追高买入",
            "condition": lambda t: t.get("buy_pct_from_low", 0) > 5 and t.get("pnl_pct", 0) < -2,
            "lesson": "避免在日内涨幅过大时追入，应等待回踩确认",
        },
        "slow_stop_loss": {
            "name": "止损犹豫",
            "condition": lambda t: t.get("max_drawdown_pct", 0) < -8 and t.get("pnl_pct", 0) < -5,
            "lesson": "严格执行止损纪律，到达止损位立即执行",
        },
        "overtrade": {
            "name": "过度交易",
            "condition": lambda t: t.get("hold_minutes", 0) < 30 and t.get("pnl_pct", 0) < 0,
            "lesson": "减少短线频繁操作，给交易足够的发展时间",
        },
        "ignore_signal": {
            "name": "忽视信号",
            "condition": lambda t: t.get("signal_score", 0) > 70 and not t.get("acted_on_signal", False),
            "lesson": "高分信号应给予重视，至少进行小仓位试错",
        },
    }

    def __init__(self, llm_client: Optional[LLMClient] = None):
        self.llm = llm_client

    def analyze_mistakes(self, trades: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """分析错误操作"""
        mistakes: List[Dict[str, Any]] = []

        for trade in trades:
            for pattern_id, pattern in self.MISTAKE_PATTERNS.items():
                try:
                    if pattern["condition"](trade):
                        mistakes.append({
                            "type": pattern_id,
                            "name": pattern["name"],
                            "trade": {
                                "symbol": trade.get("symbol", ""),
                                "name": trade.get("name", ""),
                                "buy_time": trade.get("buy_time", ""),
                                "sell_time": trade.get("sell_time", ""),
                                "pnl_pct": trade.get("pnl_pct", 0),
                            },
                            "lesson": pattern["lesson"],
                            "severity": "high" if trade.get("pnl_pct", 0) < -5 else "medium",
                        })
                except Exception:
                    continue

        # 按严重程度排序
        mistakes.sort(key=lambda m: 0 if m["severity"] == "high" else 1)
        return mistakes

    def extract_success_patterns(self, profitable_trades: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """提炼成功模式"""
        if not profitable_trades:
            return []

        patterns: List[Dict[str, Any]] = []

        # 按信号类型分组
        by_signal: Dict[str, List] = {}
        for trade in profitable_trades:
            signal_type = trade.get("signal_type", "unknown")
            by_signal.setdefault(signal_type, []).append(trade)

        for signal_type, trades in by_signal.items():
            if len(trades) < 2:
                continue

            win_rate = len([t for t in trades if t.get("pnl_pct", 0) > 0]) / len(trades)
            avg_return = sum(t.get("pnl_pct", 0) for t in trades) / len(trades)
            avg_hold = sum(t.get("hold_minutes", 0) for t in trades) / len(trades)

            patterns.append({
                "pattern": f"{signal_type}信号",
                "count": len(trades),
                "win_rate": round(win_rate, 4),
                "avg_return_pct": round(avg_return, 2),
                "avg_hold_minutes": round(avg_hold, 0),
                "suggestion": self._get_pattern_suggestion(signal_type, win_rate, avg_return),
            })

        # 按胜率排序
        patterns.sort(key=lambda p: p["win_rate"], reverse=True)
        return patterns

    def _get_pattern_suggestion(self, signal_type: str, win_rate: float, avg_return: float) -> str:
        if win_rate > 0.7 and avg_return > 3:
            return f"{signal_type}信号表现优异，可适当增加仓位"
        elif win_rate > 0.5:
            return f"{signal_type}信号表现稳定，维持当前策略"
        else:
            return f"{signal_type}信号表现一般，需优化过滤条件"

    def generate_improvement_plan(
        self,
        mistakes: List[Dict],
        success_patterns: List[Dict],
        overall_stats: Dict[str, Any],
    ) -> Dict[str, Any]:
        """生成改进计划"""
        improvements: List[str] = []
        priorities: List[Dict] = []

        # 基于错误生成改进
        mistake_types = set(m["type"] for m in mistakes)
        if "chase_high" in mistake_types:
            improvements.append("设置买入涨幅上限，超过3%日涨幅不追入")
            priorities.append({"priority": 1, "action": "设置追高过滤规则"})
        if "slow_stop_loss" in mistake_types:
            improvements.append("设置自动止损提醒，到达止损位立即通知")
            priorities.append({"priority": 1, "action": "强化止损纪律"})
        if "overtrade" in mistake_types:
            improvements.append("限制日内交易次数，设置最小持仓时间")
            priorities.append({"priority": 2, "action": "控制交易频率"})

        # 基于成功模式生成改进
        for pattern in success_patterns[:3]:
            if pattern["win_rate"] > 0.6:
                improvements.append(f"增加{pattern['pattern']}的仓位权重")

        return {
            "improvements": improvements,
            "priorities": priorities,
            "overall_assessment": self._assess_overall(overall_stats),
            "generated_at": datetime.now().isoformat(),
        }

    def _assess_overall(self, stats: Dict) -> str:
        win_rate = stats.get("win_rate", 0)
        avg_return = stats.get("avg_return_pct", 0)
        if win_rate > 0.6 and avg_return > 2:
            return "整体表现良好，继续保持并小幅优化"
        elif win_rate > 0.5:
            return "整体表现中等，重点改进错误操作"
        else:
            return "整体表现需提升，建议全面复盘策略和纪律"

    def ai_deep_review(
        self,
        today_trades: List[Dict],
        signals: List[Dict],
        holdings: List[Dict],
    ) -> Optional[str]:
        """AI深度复盘"""
        if not self.llm or not self.llm.is_available:
            return None

        trades_summary = "\n".join(
            f"- {t.get('symbol', '')} {t.get('name', '')}: 买入{t.get('buy_price', '')} 卖出{t.get('sell_price', '')} 盈亏{t.get('pnl_pct', 0):.2f}%"
            for t in today_trades[:10]
        ) or "今日无交易"

        prompt = f"""你是量化交易复盘专家，请对今日操作进行深度复盘：

## 今日交易
{trades_summary}

## 今日信号
共 {len(signals)} 个信号

## 当前持仓
共 {len(holdings)} 只

请给出深度复盘：
1. 操作评价（每笔交易的对错分析）
2. 错误归类和教训
3. 成功经验提炼
4. 纪律检查
5. 明日改进计划

用简洁专业的中文回答。"""

        try:
            return self.llm.chat(
                prompt=prompt,
                system="你是专业的交易复盘师，擅长从操作中提炼经验和教训。",
            )
        except Exception:
            logger.exception("AI深度复盘失败")
            return None
