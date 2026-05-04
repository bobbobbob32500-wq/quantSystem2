# -*- coding: utf-8 -*-
"""
交易风格学习
自动学习用户交易习惯，建立用户画像，提供个性化建议
"""

from datetime import datetime
from typing import Any, Dict, List, Optional
from collections import Counter

from src.core.logger import get_logger
from src.modules.ai_integration.llm_client import LLMClient

logger = get_logger("style_learner")


class TradingStyle:
    """交易风格画像"""

    def __init__(self):
        self.avg_hold_days: float = 0.0
        self.stop_loss_preference: float = -5.0
        self.take_profit_preference: float = 8.0
        self.position_style: str = "moderate"  # conservative, moderate, aggressive
        self.win_rate: float = 0.0
        self.avg_profit_pct: float = 0.0
        self.avg_loss_pct: float = 0.0
        self.profit_loss_ratio: float = 0.0
        self.trade_frequency: str = "normal"  # low, normal, high
        self.favorite_sectors: List[str] = []
        self.weaknesses: List[str] = []
        self.strengths: List[str] = []
        self.risk_tolerance: float = 0.5
        self.updated_at: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "avg_hold_days": self.avg_hold_days,
            "stop_loss_preference": self.stop_loss_preference,
            "take_profit_preference": self.take_profit_preference,
            "position_style": self.position_style,
            "win_rate": self.win_rate,
            "avg_profit_pct": self.avg_profit_pct,
            "avg_loss_pct": self.avg_loss_pct,
            "profit_loss_ratio": self.profit_loss_ratio,
            "trade_frequency": self.trade_frequency,
            "favorite_sectors": self.favorite_sectors,
            "weaknesses": self.weaknesses,
            "strengths": self.strengths,
            "risk_tolerance": self.risk_tolerance,
            "updated_at": self.updated_at,
        }


class TradingStyleLearner:
    """交易风格学习器"""

    def __init__(self, llm_client: Optional[LLMClient] = None):
        self.llm = llm_client
        self._style = TradingStyle()
        self._decision_records: List[Dict] = []

    def analyze_user_pattern(self, trade_history: List[Dict[str, Any]]) -> TradingStyle:
        """分析用户交易模式"""
        if not trade_history:
            return self._style

        style = TradingStyle()

        # 持仓周期
        hold_days_list = [t.get("hold_days", 0) for t in trade_history if t.get("hold_days") is not None]
        if hold_days_list:
            style.avg_hold_days = sum(hold_days_list) / len(hold_days_list)

        # 胜率
        profitable = [t for t in trade_history if t.get("pnl_pct", 0) > 0]
        losing = [t for t in trade_history if t.get("pnl_pct", 0) <= 0]
        style.win_rate = len(profitable) / len(trade_history) if trade_history else 0

        # 平均盈亏
        if profitable:
            style.avg_profit_pct = sum(t.get("pnl_pct", 0) for t in profitable) / len(profitable)
        if losing:
            style.avg_loss_pct = sum(t.get("pnl_pct", 0) for t in losing) / len(losing)

        # 盈亏比
        if style.avg_loss_pct != 0:
            style.profit_loss_ratio = abs(style.avg_profit_pct / style.avg_loss_pct)

        # 止损止盈偏好
        stop_losses = [t.get("pnl_pct", 0) for t in losing if t.get("pnl_pct", 0) < -2]
        if stop_losses:
            style.stop_loss_preference = sum(stop_losses) / len(stop_losses)
        take_profits = [t.get("pnl_pct", 0) for t in profitable if t.get("pnl_pct", 0) > 2]
        if take_profits:
            style.take_profit_preference = sum(take_profits) / len(take_profits)

        # 仓位风格
        max_positions = [t.get("position_pct", 0) for t in trade_history]
        if max_positions:
            avg_pos = sum(max_positions) / len(max_positions)
            if avg_pos > 0.25:
                style.position_style = "aggressive"
            elif avg_pos > 0.15:
                style.position_style = "moderate"
            else:
                style.position_style = "conservative"

        # 交易频率
        if len(trade_history) > 20:
            style.trade_frequency = "high"
        elif len(trade_history) > 8:
            style.trade_frequency = "normal"
        else:
            style.trade_frequency = "low"

        # 偏好板块
        sectors = [t.get("sector", "") for t in trade_history if t.get("sector")]
        if sectors:
            counter = Counter(sectors)
            style.favorite_sectors = [s for s, _ in counter.most_common(5)]

        # 识别弱点和优势
        style.weaknesses = self._identify_weaknesses(trade_history, style)
        style.strengths = self._identify_strengths(trade_history, style)

        # 风险承受度
        style.risk_tolerance = self._calculate_risk_tolerance(style)

        style.updated_at = datetime.now().isoformat()
        self._style = style
        return style

    def _identify_weaknesses(self, trades: List[Dict], style: TradingStyle) -> List[str]:
        weaknesses = []
        if style.win_rate < 0.45:
            weaknesses.append("胜率偏低，需提高选股标准")
        if style.profit_loss_ratio < 1.0:
            weaknesses.append("盈亏比不足1:1，需优化止盈止损")
        big_losses = [t for t in trades if t.get("pnl_pct", 0) < -5]
        if len(big_losses) > len(trades) * 0.15:
            weaknesses.append("大亏交易占比过高，止损不坚决")
        chase_high = [t for t in trades if t.get("buy_pct_from_low", 0) > 5 and t.get("pnl_pct", 0) < 0]
        if len(chase_high) > 2:
            weaknesses.append("存在追高习惯，需等待回踩确认")
        return weaknesses

    def _identify_strengths(self, trades: List[Dict], style: TradingStyle) -> List[str]:
        strengths = []
        if style.win_rate > 0.6:
            strengths.append("选股胜率较高")
        if style.profit_loss_ratio > 2.0:
            strengths.append("盈亏比优秀，让利润奔跑")
        if style.position_style == "conservative":
            strengths.append("仓位控制稳健")
        quick_stops = [t for t in trades if -3 < t.get("pnl_pct", 0) < -2]
        if len(quick_stops) > 0 and style.avg_loss_pct > -4:
            strengths.append("止损执行及时")
        return strengths

    def _calculate_risk_tolerance(self, style: TradingStyle) -> float:
        score = 0.5
        if style.position_style == "aggressive":
            score += 0.2
        elif style.position_style == "conservative":
            score -= 0.2
        if style.profit_loss_ratio > 1.5:
            score += 0.1
        if style.win_rate > 0.6:
            score += 0.1
        return max(0.0, min(1.0, score))

    def track_decision(self, ai_suggestion: str, user_action: str, outcome: Optional[Dict] = None):
        """追踪决策"""
        self._decision_records.append({
            "ai_suggestion": ai_suggestion,
            "user_action": user_action,
            "adopted": ai_suggestion.lower() in user_action.lower(),
            "outcome": outcome,
            "timestamp": datetime.now().isoformat(),
        })

    def analyze_adoption_rate(self) -> Dict[str, Any]:
        """分析AI建议采纳率"""
        if not self._decision_records:
            return {"total": 0, "adopted": 0, "adoption_rate": 0}

        total = len(self._decision_records)
        adopted = sum(1 for r in self._decision_records if r.get("adopted"))
        adopted_with_outcome = [r for r in self._decision_records if r.get("adopted") and r.get("outcome")]
        rejected_with_outcome = [r for r in self._decision_records if not r.get("adopted") and r.get("outcome")]

        avg_pnl_adopted = 0.0
        avg_pnl_rejected = 0.0
        if adopted_with_outcome:
            avg_pnl_adopted = sum(r["outcome"].get("pnl_pct", 0) for r in adopted_with_outcome) / len(adopted_with_outcome)
        if rejected_with_outcome:
            avg_pnl_rejected = sum(r["outcome"].get("pnl_pct", 0) for r in rejected_with_outcome) / len(rejected_with_outcome)

        return {
            "total": total,
            "adopted": adopted,
            "adoption_rate": round(adopted / total, 4),
            "avg_pnl_when_adopted": round(avg_pnl_adopted, 2),
            "avg_pnl_when_rejected": round(avg_pnl_rejected, 2),
        }

    def generate_personalized_advice(self, context: Dict[str, Any]) -> str:
        """生成个性化建议"""
        style = self._style
        advice_parts = []

        if style.weaknesses:
            advice_parts.append(f"需改进: {'; '.join(style.weaknesses[:3])}")

        if style.win_rate < 0.5:
            advice_parts.append("建议提高选股评分门槛，减少低质量交易")
        if style.profit_loss_ratio < 1.5:
            advice_parts.append("建议优化止盈策略，让盈利交易充分发展")

        if context.get("market_regime") == "bear" and style.position_style == "aggressive":
            advice_parts.append("当前市场偏弱，建议降低仓位至保守水平")

        return "\n".join(advice_parts) if advice_parts else "当前交易风格良好，继续保持"

    def ai_analyze_style(self, trade_history: List[Dict]) -> Optional[str]:
        """AI分析交易风格"""
        if not self.llm or not self.llm.is_available:
            return None

        style = self._style
        prompt = f"""你是量化交易心理分析师，请分析以下交易者的风格和特点：

## 交易风格画像
- 平均持仓: {style.avg_hold_days:.1f}天
- 胜率: {style.win_rate*100:.1f}%
- 盈亏比: {style.profit_loss_ratio:.2f}
- 仓位风格: {style.position_style}
- 交易频率: {style.trade_frequency}
- 偏好板块: {', '.join(style.favorite_sectors) or '无'}
- 弱点: {', '.join(style.weaknesses) or '无'}
- 优势: {', '.join(style.strengths) or '无'}

请给出：
1. 交易者类型判断
2. 核心优势和需要改进的地方
3. 个性化建议
4. 适合的策略类型

用简洁专业的中文回答。"""

        try:
            return self.llm.chat(
                prompt=prompt,
                system="你是专业的交易心理分析师，擅长分析交易者行为模式。",
            )
        except Exception:
            logger.exception("AI分析交易风格失败")
            return None

    def get_style(self) -> Dict[str, Any]:
        return self._style.to_dict()
