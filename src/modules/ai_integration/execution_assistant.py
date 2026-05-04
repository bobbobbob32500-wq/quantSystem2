# -*- coding: utf-8 -*-
"""
智能执行助手
交易计划生成、分批执行建议、最佳执行时机判断
"""

from datetime import datetime
from typing import Any, Dict, List, Optional
from enum import Enum

from src.core.logger import get_logger
from src.modules.ai_integration.llm_client import LLMClient

logger = get_logger("execution_assistant")


class ExecutionAction(Enum):
    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"
    REDUCE = "reduce"    # 减仓
    ADD = "add"          # 加仓


class TradePlan:
    """交易计划"""

    def __init__(
        self,
        action: ExecutionAction,
        symbol: str,
        name: str = "",
        total_position: float = 0.0,
        batches: Optional[List[Dict]] = None,
        stop_loss: float = 0.0,
        take_profit: Optional[List[float]] = None,
        reason: str = "",
        risk_note: str = "",
    ):
        self.id = f"tp_{datetime.now().strftime('%Y%m%d%H%M%S')}"
        self.action = action
        self.symbol = symbol
        self.name = name
        self.total_position = total_position
        self.batches = batches or []
        self.stop_loss = stop_loss
        self.take_profit = take_profit or []
        self.reason = reason
        self.risk_note = risk_note
        self.created_at = datetime.now().isoformat()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "action": self.action.value,
            "symbol": self.symbol,
            "name": self.name,
            "total_position": self.total_position,
            "batches": self.batches,
            "stop_loss": self.stop_loss,
            "take_profit": self.take_profit,
            "reason": self.reason,
            "risk_note": self.risk_note,
            "created_at": self.created_at,
        }


class ExecutionAssistant:
    """智能执行助手"""

    def __init__(self, llm_client: Optional[LLMClient] = None):
        self.llm = llm_client
        self._plans: List[TradePlan] = []

    def generate_trade_plan(
        self,
        signal: Dict[str, Any],
        stock_info: Dict[str, Any],
        current_position: Optional[Dict[str, Any]] = None,
        risk_config: Optional[Dict[str, Any]] = None,
    ) -> TradePlan:
        """根据信号生成交易计划"""
        signal_type = signal.get("signal_type", "")
        symbol = stock_info.get("symbol", signal.get("symbol", ""))
        name = stock_info.get("name", "")
        price = stock_info.get("price", 0)
        score = signal.get("score", 60)

        # 默认风控配置
        risk = risk_config or {
            "max_single_position": 0.3,
            "default_stop_loss_pct": -5.0,
            "default_take_profit_pct": 8.0,
            "batch_count": 3,
        }

        # 判断操作方向
        if "buy" in signal_type.lower() or "突破" in signal_type or "启动" in signal_type:
            action = ExecutionAction.BUY
        elif "sell" in signal_type.lower() or "止损" in signal_type:
            action = ExecutionAction.SELL
        else:
            action = ExecutionAction.HOLD

        # 计算仓位
        position_pct = min(score / 100 * risk["max_single_position"], risk["max_single_position"])

        # 分批执行计划
        batch_count = risk.get("batch_count", 3)
        batch_size = position_pct / batch_count
        batches = []
        for i in range(batch_count):
            batch = {
                "batch": i + 1,
                "position_pct": round(batch_size, 4),
                "condition": self._get_batch_condition(i, action),
                "status": "pending",
            }
            batches.append(batch)

        # 止损止盈
        stop_loss = price * (1 + risk["default_stop_loss_pct"] / 100) if price > 0 else 0
        tp1 = price * (1 + risk["default_take_profit_pct"] / 100) if price > 0 else 0
        tp2 = price * (1 + risk["default_take_profit_pct"] * 1.5 / 100) if price > 0 else 0

        plan = TradePlan(
            action=action,
            symbol=symbol,
            name=name,
            total_position=round(position_pct, 4),
            batches=batches,
            stop_loss=round(stop_loss, 2),
            take_profit=[round(tp1, 2), round(tp2, 2)],
            reason=f"基于{signal_type}信号，评分{score}分",
            risk_note=f"止损 {stop_loss:.2f}（{risk['default_stop_loss_pct']}%），分{batch_count}批执行",
        )

        self._plans.append(plan)
        return plan

    def _get_batch_condition(self, batch_index: int, action: ExecutionAction) -> str:
        """获取分批执行条件"""
        if action == ExecutionAction.BUY:
            conditions = [
                "开盘观察5分钟，若走势符合预期则建仓1/3",
                "回踩支撑位不破，加仓1/3",
                "突破确认放量，加仓1/3",
            ]
        elif action == ExecutionAction.SELL:
            conditions = [
                "立即卖出1/3仓位",
                "反弹无力时再卖1/3",
                "剩余1/3设止损价自动卖出",
            ]
        else:
            conditions = ["继续持有观察"]

        return conditions[min(batch_index, len(conditions) - 1)]

    def suggest_execution_timing(
        self,
        symbol: str,
        intraday_data: Dict[str, Any],
    ) -> Dict[str, Any]:
        """建议执行时机"""
        current_time = datetime.now()
        hour = current_time.hour
        minute = current_time.minute

        # 开盘30分钟内波动大
        if hour == 9 and minute >= 30 or (hour == 10 and minute < 0):
            return {
                "timing": "wait",
                "reason": "开盘30分钟内波动较大，建议等待走势明朗",
                "suggested_time": "10:00-10:30",
                "confidence": 0.7,
            }

        # 午盘前
        if hour == 11 and minute >= 0:
            return {
                "timing": "cautious",
                "reason": "临近午盘收盘，午后走势可能变化",
                "suggested_time": "13:30-14:00",
                "confidence": 0.6,
            }

        # 尾盘
        if hour == 14 and minute >= 30:
            return {
                "timing": "good",
                "reason": "尾盘走势相对确定，适合执行",
                "suggested_time": "14:30-14:50",
                "confidence": 0.8,
            }

        # 盘中正常时段
        return {
            "timing": "normal",
            "reason": "当前为盘中正常时段，可按计划执行",
            "suggested_time": f"{hour:02d}:{minute:02d}",
            "confidence": 0.5,
        }

    def ai_generate_plan(
        self,
        signal: Dict,
        stock_info: Dict,
        position: Optional[Dict] = None,
    ) -> Optional[str]:
        """AI生成交易计划"""
        if not self.llm or not self.llm.is_available:
            return None

        prompt = f"""你是量化交易执行助手，请根据以下信息生成详细的交易执行计划：

## 信号
- 类型: {signal.get('signal_type', '')}
- 评分: {signal.get('score', 0)}
- 原因: {signal.get('reason', '')}

## 股票
- 代码: {stock_info.get('symbol', '')}
- 名称: {stock_info.get('name', '')}
- 现价: {stock_info.get('price', 0)}

## 当前持仓
{self._format_position(position)}

请给出：
1. 操作方向和仓位建议
2. 分批执行计划（具体条件和仓位）
3. 止损位和止盈位
4. 最佳执行时机
5. 风险提示

用简洁专业的中文回答。"""

        try:
            return self.llm.chat(
                prompt=prompt,
                system="你是专业的交易执行师，擅长制定精确的交易计划和风控方案。",
            )
        except Exception:
            logger.exception("AI生成交易计划失败")
            return None

    def _format_position(self, position: Optional[Dict]) -> str:
        if not position:
            return "无持仓"
        return f"- 持仓: {position.get('position_pct', 0)*100:.1f}%\n- 成本: {position.get('cost', 0):.2f}\n- 浮盈: {position.get('pnl_pct', 0):.2f}%"

    def get_plans(self, limit: int = 10) -> List[Dict]:
        return [p.to_dict() for p in self._plans[-limit:]]

    def get_plan(self, plan_id: str) -> Optional[Dict]:
        for p in self._plans:
            if p.id == plan_id:
                return p.to_dict()
        return None
