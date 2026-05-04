# -*- coding: utf-8 -*-
"""
多维度预警系统
技术面预警、资金面预警、情绪面预警、综合预警
"""

from datetime import datetime
from typing import Any, Dict, List, Optional
from enum import Enum

from src.core.logger import get_logger
from src.modules.ai_integration.llm_client import LLMClient

logger = get_logger("alert_system")


class AlertLevel(Enum):
    CRITICAL = "critical"   # 紧急：需立即处理
    HIGH = "high"           # 高：需尽快处理
    MEDIUM = "medium"       # 中：需关注
    LOW = "low"             # 低：仅供参考
    INFO = "info"           # 信息：无需操作


class AlertType(Enum):
    TECHNICAL = "technical"         # 技术面
    CAPITAL_FLOW = "capital_flow"   # 资金面
    SENTIMENT = "sentiment"         # 情绪面
    RISK = "risk"                   # 风控
    OPPORTUNITY = "opportunity"     # 机会
    SYSTEM = "system"               # 系统


class Alert:
    """预警项"""

    def __init__(
        self,
        alert_type: AlertType,
        level: AlertLevel,
        title: str,
        message: str,
        symbol: str = "",
        action: str = "",
        details: Optional[Dict[str, Any]] = None,
    ):
        self.id = f"{alert_type.value}_{datetime.now().strftime('%Y%m%d%H%M%S%f')}"
        self.alert_type = alert_type
        self.level = level
        self.title = title
        self.message = message
        self.symbol = symbol
        self.action = action
        self.details = details or {}
        self.created_at = datetime.now().isoformat()
        self.acked = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "type": self.alert_type.value,
            "level": self.level.value,
            "title": self.title,
            "message": self.message,
            "symbol": self.symbol,
            "action": self.action,
            "details": self.details,
            "created_at": self.created_at,
            "acked": self.acked,
        }


class MultiDimensionalAlertSystem:
    """多维度预警系统"""

    def __init__(self, llm_client: Optional[LLMClient] = None):
        self.llm = llm_client
        self._active_alerts: List[Alert] = []
        self._alert_history: List[Alert] = []

    # ==================== 技术面预警 ====================

    def check_technical_alerts(
        self,
        symbol: str,
        price_data: Dict[str, Any],
        indicators: Optional[Dict[str, Any]] = None,
    ) -> List[Alert]:
        """技术面预警检查"""
        alerts: List[Alert] = []
        close = price_data.get("close", 0)
        high = price_data.get("high", 0)
        low = price_data.get("low", 0)
        volume = price_data.get("volume", 0)
        avg_volume = price_data.get("avg_volume_20", volume)

        # 突破阻力位
        resistance = price_data.get("resistance")
        if resistance and close > resistance:
            alerts.append(Alert(
                alert_type=AlertType.TECHNICAL,
                level=AlertLevel.HIGH,
                title=f"{symbol} 突破阻力位",
                message=f"收盘价 {close:.2f} 突破阻力位 {resistance:.2f}，关注回踩确认",
                symbol=symbol,
                action="观察回踩力度，若缩量回踩不破可考虑介入",
                details={"price": close, "resistance": resistance, "break_pct": (close - resistance) / resistance * 100},
            ))

        # 跌破支撑位
        support = price_data.get("support")
        if support and close < support:
            alerts.append(Alert(
                alert_type=AlertType.TECHNICAL,
                level=AlertLevel.HIGH,
                title=f"{symbol} 跌破支撑位",
                message=f"收盘价 {close:.2f} 跌破支撑位 {support:.2f}，注意风险",
                symbol=symbol,
                action="评估是否止损，观察是否有效跌破",
                details={"price": close, "support": support, "break_pct": (support - close) / support * 100},
            ))

        # 放量异动
        if avg_volume > 0 and volume > avg_volume * 2:
            ratio = volume / avg_volume
            level = AlertLevel.HIGH if ratio > 3 else AlertLevel.MEDIUM
            alerts.append(Alert(
                alert_type=AlertType.TECHNICAL,
                level=level,
                title=f"{symbol} 放量异动",
                message=f"成交量 {volume:.0f} 为20日均量 {avg_volume:.0f} 的 {ratio:.1f} 倍",
                symbol=symbol,
                action="结合价格方向判断：放量上涨关注，放量下跌警惕",
                details={"volume": volume, "avg_volume": avg_volume, "ratio": ratio},
            ))

        # 急涨急跌
        pct_change = price_data.get("pct_change", 0)
        if abs(pct_change) > 5:
            level = AlertLevel.CRITICAL if abs(pct_change) > 8 else AlertLevel.HIGH
            direction = "急涨" if pct_change > 0 else "急跌"
            alerts.append(Alert(
                alert_type=AlertType.TECHNICAL,
                level=level,
                title=f"{symbol} {direction}",
                message=f"日内涨跌幅 {pct_change:.2f}%，波动剧烈",
                symbol=symbol,
                action="急涨：警惕追高；急跌：评估是否抄底或止损",
                details={"pct_change": pct_change},
            ))

        # 指标背离
        if indicators:
            self._check_divergence(symbol, price_data, indicators, alerts)

        self._active_alerts.extend(alerts)
        return alerts

    def _check_divergence(
        self,
        symbol: str,
        price_data: Dict,
        indicators: Dict,
        alerts: List[Alert],
    ):
        """检查指标背离"""
        macd_divergence = indicators.get("macd_divergence")
        if macd_divergence:
            alerts.append(Alert(
                alert_type=AlertType.TECHNICAL,
                level=AlertLevel.MEDIUM,
                title=f"{symbol} MACD背离",
                message=f"检测到{macd_divergence}背离，趋势可能反转",
                symbol=symbol,
                action="结合其他指标确认，考虑减仓或反向操作",
            ))

        rsi = indicators.get("rsi_14")
        if rsi is not None:
            if rsi > 80:
                alerts.append(Alert(
                    alert_type=AlertType.TECHNICAL,
                    level=AlertLevel.MEDIUM,
                    title=f"{symbol} RSI超买",
                    message=f"RSI(14) = {rsi:.1f}，进入超买区域",
                    symbol=symbol,
                    action="注意回调风险，可考虑分批止盈",
                ))
            elif rsi < 20:
                alerts.append(Alert(
                    alert_type=AlertType.TECHNICAL,
                    level=AlertLevel.MEDIUM,
                    title=f"{symbol} RSI超卖",
                    message=f"RSI(14) = {rsi:.1f}，进入超卖区域",
                    symbol=symbol,
                    action="可能存在反弹机会，但需确认趋势",
                ))

    # ==================== 资金面预警 ====================

    def check_capital_flow_alerts(
        self,
        symbol: str,
        capital_data: Dict[str, Any],
    ) -> List[Alert]:
        """资金面预警检查"""
        alerts: List[Alert] = []

        # 主力资金异动
        main_net = capital_data.get("main_net_inflow", 0)
        main_pct = capital_data.get("main_net_pct", 0)
        if abs(main_pct) > 3:
            direction = "大幅流入" if main_pct > 0 else "大幅流出"
            level = AlertLevel.HIGH if abs(main_pct) > 5 else AlertLevel.MEDIUM
            alerts.append(Alert(
                alert_type=AlertType.CAPITAL_FLOW,
                level=level,
                title=f"{symbol} 主力资金{direction}",
                message=f"主力净流入 {main_net/10000:.0f}万，占比 {main_pct:.2f}%",
                symbol=symbol,
                action="流入：关注是否持续；流出：警惕主力出货",
                details={"main_net": main_net, "main_pct": main_pct},
            ))

        # 北向资金
        north_net = capital_data.get("north_net_inflow")
        if north_net is not None and abs(north_net) > 1e8:
            direction = "大幅买入" if north_net > 0 else "大幅卖出"
            alerts.append(Alert(
                alert_type=AlertType.CAPITAL_FLOW,
                level=AlertLevel.MEDIUM,
                title=f"{symbol} 北向资金{direction}",
                message=f"北向净买入 {north_net/1e8:.2f}亿",
                symbol=symbol,
                action="北向资金动向可作为参考，关注持续性",
                details={"north_net": north_net},
            ))

        self._active_alerts.extend(alerts)
        return alerts

    # ==================== 情绪面预警 ====================

    def check_sentiment_alerts(
        self,
        market_data: Dict[str, Any],
    ) -> List[Alert]:
        """情绪面预警检查"""
        alerts: List[Alert] = []

        # 市场情绪极端
        fear_greed_index = market_data.get("fear_greed_index")
        if fear_greed_index is not None:
            if fear_greed_index < 20:
                alerts.append(Alert(
                    alert_type=AlertType.SENTIMENT,
                    level=AlertLevel.HIGH,
                    title="市场极度恐惧",
                    message=f"恐惧贪婪指数 {fear_greed_index}，市场极度恐惧",
                    action="逆向思维：极度恐惧时可能存在反弹机会",
                    details={"fear_greed_index": fear_greed_index},
                ))
            elif fear_greed_index > 80:
                alerts.append(Alert(
                    alert_type=AlertType.SENTIMENT,
                    level=AlertLevel.HIGH,
                    title="市场极度贪婪",
                    message=f"恐惧贪婪指数 {fear_greed_index}，市场极度贪婪",
                    action="警惕回调风险，考虑降低仓位",
                    details={"fear_greed_index": fear_greed_index},
                ))

        # 涨停/跌停数量异常
        limit_up = market_data.get("limit_up_count", 0)
        limit_down = market_data.get("limit_down_count", 0)
        if limit_down > 50:
            alerts.append(Alert(
                alert_type=AlertType.SENTIMENT,
                level=AlertLevel.CRITICAL,
                title="跌停潮预警",
                message=f"当前跌停 {limit_down} 家，市场恐慌加剧",
                action="系统性风险，建议降低仓位或空仓观望",
                details={"limit_down": limit_down},
            ))

        self._active_alerts.extend(alerts)
        return alerts

    # ==================== 综合预警 ====================

    def check_comprehensive_alerts(
        self,
        holdings: List[Dict[str, Any]],
        market_data: Dict[str, Any],
    ) -> List[Alert]:
        """综合风控预警"""
        alerts: List[Alert] = []

        # 持仓集中度
        if len(holdings) > 0:
            total_position = sum(h.get("position_pct", 0) for h in holdings)
            max_single = max(h.get("position_pct", 0) for h in holdings)
            if max_single > 0.3:
                symbol = next((h.get("symbol", "") for h in holdings if h.get("position_pct", 0) == max_single), "")
                alerts.append(Alert(
                    alert_type=AlertType.RISK,
                    level=AlertLevel.HIGH,
                    title="持仓集中度过高",
                    message=f"单只持仓 {symbol} 占比 {max_single*100:.1f}%，超过30%阈值",
                    symbol=symbol,
                    action="考虑分散持仓，降低单一标的风险",
                    details={"max_position_pct": max_single},
                ))

            # 整体浮亏
            total_pnl = sum(h.get("pnl_pct", 0) * h.get("position_pct", 0) for h in holdings)
            if total_pnl < -3:
                alerts.append(Alert(
                    alert_type=AlertType.RISK,
                    level=AlertLevel.CRITICAL if total_pnl < -5 else AlertLevel.HIGH,
                    title="整体浮亏预警",
                    message=f"持仓组合浮亏 {total_pnl:.2f}%",
                    action="评估是否需要减仓止损，检查市场环境是否恶化",
                    details={"total_pnl_pct": total_pnl},
                ))

        self._active_alerts.extend(alerts)
        return alerts

    # ==================== AI增强预警 ====================

    def ai_analyze_alerts(self, alerts: List[Alert], context: str = "") -> Optional[str]:
        """AI增强分析预警"""
        if not self.llm or not self.llm.is_available:
            return None

        alert_summary = "\n".join(
            f"- [{a.level.value}][{a.alert_type.value}] {a.title}: {a.message}"
            for a in alerts
        )

        prompt = f"""你是量化交易系统的AI管家，请对以下预警进行综合分析和优先级排序：

## 当前预警
{alert_summary}

## 上下文
{context or '无额外上下文'}

请给出：
1. 预警优先级排序（最紧急的排前面）
2. 综合判断和建议
3. 需要立即执行的操作

用简洁专业的中文回答。"""

        try:
            return self.llm.chat(
                prompt=prompt,
                system="你是专业的风控分析师，擅长综合评估风险和机会。",
            )
        except Exception:
            logger.exception("AI预警分析失败")
            return None

    # ==================== 预警管理 ====================

    def get_active_alerts(self, level: Optional[AlertLevel] = None, alert_type: Optional[AlertType] = None) -> List[Dict]:
        """获取活跃预警"""
        result = self._active_alerts
        if level:
            result = [a for a in result if a.level == level]
        if alert_type:
            result = [a for a in result if a.alert_type == alert_type]
        return [a.to_dict() for a in result]

    def ack_alert(self, alert_id: str) -> bool:
        """确认预警"""
        for alert in self._active_alerts:
            if alert.id == alert_id:
                alert.acked = True
                self._alert_history.append(alert)
                self._active_alerts.remove(alert)
                return True
        return False

    def clear_all(self):
        """清空所有预警"""
        self._alert_history.extend(self._active_alerts)
        self._active_alerts.clear()

    def get_alert_summary(self) -> Dict[str, Any]:
        """获取预警摘要"""
        level_counts = {}
        type_counts = {}
        for a in self._active_alerts:
            level_counts[a.level.value] = level_counts.get(a.level.value, 0) + 1
            type_counts[a.alert_type.value] = type_counts.get(a.alert_type.value, 0) + 1
        return {
            "total_active": len(self._active_alerts),
            "total_history": len(self._alert_history),
            "by_level": level_counts,
            "by_type": type_counts,
            "has_critical": any(a.level == AlertLevel.CRITICAL for a in self._active_alerts),
        }
