# -*- coding: utf-8 -*-
"""
实时盯盘助手
关键价位提醒、异常波动监控、盘口监控
"""

from datetime import datetime
from typing import Any, Dict, List, Optional
from enum import Enum

from src.core.logger import get_logger
from src.modules.ai_integration.llm_client import LLMClient

logger = get_logger("realtime_watcher")


class WatchType(Enum):
    PRICE_ABOVE = "price_above"       # 价格上穿
    PRICE_BELOW = "price_below"       # 价格下穿
    VOLUME_SPIKE = "volume_spike"     # 放量异动
    PCT_CHANGE = "pct_change"         # 涨跌幅
    SUPPORT_BREAK = "support_break"   # 支撑跌破
    RESISTANCE_BREAK = "resistance_break"  # 阻力突破


class PriceAlert:
    """价位提醒"""

    def __init__(self, symbol: str, watch_type: WatchType, target_value: float, label: str = ""):
        self.id = f"pa_{symbol}_{watch_type.value}_{datetime.now().strftime('%Y%m%d%H%M%S')}"
        self.symbol = symbol
        self.watch_type = watch_type
        self.target_value = target_value
        self.label = label or f"{symbol} {watch_type.value} {target_value}"
        self.created_at = datetime.now().isoformat()
        self.triggered = False
        self.triggered_at: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "symbol": self.symbol,
            "watch_type": self.watch_type.value,
            "target_value": self.target_value,
            "label": self.label,
            "created_at": self.created_at,
            "triggered": self.triggered,
            "triggered_at": self.triggered_at,
        }


class RealTimeWatcher:
    """实时盯盘助手"""

    def __init__(self, llm_client: Optional[LLMClient] = None):
        self.llm = llm_client
        self._price_alerts: List[PriceAlert] = []
        self._watchlist: List[str] = []
        self._abnormal_events: List[Dict] = []

    # ==================== 价位提醒 ====================

    def set_price_alert(
        self,
        symbol: str,
        watch_type: WatchType,
        target_value: float,
        label: str = "",
    ) -> PriceAlert:
        """设置价位提醒"""
        alert = PriceAlert(symbol, watch_type, target_value, label)
        self._price_alerts.append(alert)
        logger.info("设置价位提醒: %s %s %.2f", symbol, watch_type.value, target_value)
        return alert

    def set_stop_loss_alert(self, symbol: str, stop_price: float) -> PriceAlert:
        """设置止损提醒"""
        return self.set_price_alert(symbol, WatchType.PRICE_BELOW, stop_price, f"{symbol} 止损 {stop_price:.2f}")

    def set_take_profit_alert(self, symbol: str, target_price: float) -> PriceAlert:
        """设置止盈提醒"""
        return self.set_price_alert(symbol, WatchType.PRICE_ABOVE, target_price, f"{symbol} 止盈 {target_price:.2f}")

    def set_support_alert(self, symbol: str, support_price: float) -> PriceAlert:
        """设置支撑位提醒"""
        return self.set_price_alert(symbol, WatchType.SUPPORT_BREAK, support_price, f"{symbol} 支撑 {support_price:.2f}")

    def set_resistance_alert(self, symbol: str, resistance_price: float) -> PriceAlert:
        """设置阻力位提醒"""
        return self.set_price_alert(symbol, WatchType.RESISTANCE_BREAK, resistance_price, f"{symbol} 阻力 {resistance_price:.2f}")

    def remove_price_alert(self, alert_id: str) -> bool:
        """移除价位提醒"""
        before = len(self._price_alerts)
        self._price_alerts = [a for a in self._price_alerts if a.id != alert_id]
        return len(self._price_alerts) < before

    # ==================== 异常波动监控 ====================

    def check_price_alerts(self, symbol: str, current_price: float) -> List[Dict]:
        """检查价位提醒是否触发"""
        triggered: List[Dict] = []
        for alert in self._price_alerts:
            if alert.symbol != symbol or alert.triggered:
                continue
            is_triggered = False
            if alert.watch_type == WatchType.PRICE_ABOVE and current_price > alert.target_value:
                is_triggered = True
            elif alert.watch_type == WatchType.PRICE_BELOW and current_price < alert.target_value:
                is_triggered = True
            elif alert.watch_type == WatchType.RESISTANCE_BREAK and current_price > alert.target_value:
                is_triggered = True
            elif alert.watch_type == WatchType.SUPPORT_BREAK and current_price < alert.target_value:
                is_triggered = True

            if is_triggered:
                alert.triggered = True
                alert.triggered_at = datetime.now().isoformat()
                triggered.append({
                    "alert": alert.to_dict(),
                    "current_price": current_price,
                    "message": f"{alert.label} 已触发！当前价 {current_price:.2f}",
                })
        return triggered

    def monitor_abnormal_movement(
        self,
        symbol: str,
        realtime_data: Dict[str, Any],
    ) -> List[Dict]:
        """监控异常波动"""
        events: List[Dict] = []
        close = realtime_data.get("close", 0)
        pre_close = realtime_data.get("pre_close", close)
        volume = realtime_data.get("volume", 0)
        avg_volume_5 = realtime_data.get("avg_volume_5", volume)

        # 急涨急跌
        if pre_close > 0:
            pct = (close - pre_close) / pre_close * 100
            if abs(pct) > 3:
                direction = "急涨" if pct > 0 else "急跌"
                events.append({
                    "type": "abnormal_move",
                    "symbol": symbol,
                    "direction": direction,
                    "pct_change": round(pct, 2),
                    "message": f"{symbol} {direction} {pct:.2f}%",
                    "action": "急涨警惕追高；急跌评估止损" if pct < 0 else "急涨关注持续性；急跌警惕抄底",
                    "timestamp": datetime.now().isoformat(),
                })

        # 放量异动
        if avg_volume_5 > 0 and volume > avg_volume_5 * 2:
            ratio = volume / avg_volume_5
            events.append({
                "type": "volume_spike",
                "symbol": symbol,
                "volume_ratio": round(ratio, 2),
                "message": f"{symbol} 放量 {ratio:.1f}倍",
                "action": "结合价格方向判断",
                "timestamp": datetime.now().isoformat(),
            })

        self._abnormal_events.extend(events)
        return events

    # ==================== 盘口监控 ====================

    def watch_order_book(
        self,
        symbol: str,
        order_book: Dict[str, Any],
    ) -> Optional[Dict]:
        """盘口监控"""
        bid_volume = sum(order_book.get("bid_volumes", []))
        ask_volume = sum(order_book.get("ask_volumes", []))

        if ask_volume == 0:
            return None

        ratio = bid_volume / ask_volume

        # 买卖盘力量严重失衡
        if ratio > 3 or ratio < 0.33:
            direction = "买盘远大于卖盘" if ratio > 3 else "卖盘远大于买盘"
            return {
                "type": "order_imbalance",
                "symbol": symbol,
                "bid_ask_ratio": round(ratio, 2),
                "message": f"{symbol} {direction}（比率 {ratio:.2f}）",
                "action": "买盘强：关注突破机会；卖盘强：警惕下跌风险",
                "timestamp": datetime.now().isoformat(),
            }

        # 大单压盘/托盘
        max_bid = max(order_book.get("bid_volumes", [0]))
        max_ask = max(order_book.get("ask_volumes", [0]))
        avg_bid = bid_volume / max(len(order_book.get("bid_volumes", [1])), 1)
        avg_ask = ask_volume / max(len(order_book.get("ask_volumes", [1])), 1)

        if max_bid > avg_bid * 5:
            return {
                "type": "big_bid",
                "symbol": symbol,
                "message": f"{symbol} 买一出现大单托盘",
                "action": "大单托盘可能是支撑，也可能是诱多",
                "timestamp": datetime.now().isoformat(),
            }
        if max_ask > avg_ask * 5:
            return {
                "type": "big_ask",
                "symbol": symbol,
                "message": f"{symbol} 卖一出现大单压盘",
                "action": "大单压盘可能是阻力，也可能是洗盘",
                "timestamp": datetime.now().isoformat(),
            }

        return None

    # ==================== AI盯盘分析 ====================

    def ai_watch_analysis(self, symbol: str, market_data: Dict) -> Optional[str]:
        """AI盯盘分析"""
        if not self.llm or not self.llm.is_available:
            return None

        prompt = f"""你是量化交易盯盘助手，请分析以下实时数据：

## 股票: {symbol}
## 实时数据
{self._format_market_data(market_data)}

请给出：
1. 当前走势判断
2. 关键价位提醒
3. 操作建议
4. 风险提示

用简洁专业的中文回答。"""

        try:
            return self.llm.chat(
                prompt=prompt,
                system="你是专业的A股盯盘分析师，擅长实时走势判断和操作建议。",
            )
        except Exception:
            logger.exception("AI盯盘分析失败")
            return None

    def _format_market_data(self, data: Dict) -> str:
        parts = []
        for key, value in data.items():
            parts.append(f"- {key}: {value}")
        return "\n".join(parts) if parts else "暂无数据"

    # ==================== 管理接口 ====================

    def get_all_alerts(self) -> List[Dict]:
        return [a.to_dict() for a in self._price_alerts]

    def get_active_alerts(self) -> List[Dict]:
        return [a.to_dict() for a in self._price_alerts if not a.triggered]

    def get_triggered_alerts(self) -> List[Dict]:
        return [a.to_dict() for a in self._price_alerts if a.triggered]

    def get_recent_events(self, limit: int = 20) -> List[Dict]:
        return self._abnormal_events[-limit:]

    def get_summary(self) -> Dict[str, Any]:
        return {
            "total_alerts": len(self._price_alerts),
            "active_alerts": len([a for a in self._price_alerts if not a.triggered]),
            "triggered_alerts": len([a for a in self._price_alerts if a.triggered]),
            "recent_events": len(self._abnormal_events),
        }
