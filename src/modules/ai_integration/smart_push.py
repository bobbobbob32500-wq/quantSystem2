# -*- coding: utf-8 -*-
"""
智能推送策略
根据重要性和紧急程度分级推送，支持多渠道，智能免打扰
"""

from datetime import datetime, time
from typing import Any, Dict, List, Optional
from enum import Enum

from src.core.logger import get_logger

logger = get_logger("smart_push")


class PushChannel(Enum):
    APP = "app"               # App内推送
    WECHAT = "wechat"         # 企业微信
    DINGTALK = "dingtalk"     # 钉钉
    EMAIL = "email"           # 邮件


class PushPriority(Enum):
    URGENT = "urgent"         # 紧急：多渠道推送
    HIGH = "high"             # 高：App+微信
    NORMAL = "normal"         # 普通：仅App
    LOW = "low"               # 低：仅App内消息


class SmartPushStrategy:
    """智能推送策略"""

    # 默认免打扰时段
    DEFAULT_SILENT_START = time(22, 0)
    DEFAULT_SILENT_END = time(7, 30)

    def __init__(self, config: Optional[Dict] = None):
        self._config = config or {}
        self._silent_start = self._parse_time(self._config.get("silent_start", "22:00"))
        self._silent_end = self._parse_time(self._config.get("silent_end", "07:30"))
        self._enabled_channels = self._config.get("enabled_channels", ["app"])
        self._push_history: List[Dict] = []

    def _parse_time(self, time_str: str) -> time:
        try:
            parts = time_str.split(":")
            return time(int(parts[0]), int(parts[1]))
        except Exception:
            return self.DEFAULT_SILENT_START

    def should_push(self, alert_level: str, user_active: bool = True) -> Dict[str, Any]:
        """判断是否推送及推送渠道"""
        now = datetime.now().time()
        is_silent = self._is_silent_time(now)

        # 紧急级别始终推送
        if alert_level in ("critical", "urgent"):
            return {
                "should_push": True,
                "channels": self._get_channels_for_priority(PushPriority.URGENT),
                "reason": "紧急预警，始终推送",
                "silent_overridden": is_silent,
            }

        # 免打扰时段
        if is_silent and not user_active:
            return {
                "should_push": False,
                "channels": [],
                "reason": "免打扰时段，用户不活跃",
                "silent_overridden": False,
            }

        # 根据级别决定
        priority_map = {
            "high": PushPriority.HIGH,
            "medium": PushPriority.NORMAL,
            "low": PushPriority.LOW,
            "info": PushPriority.LOW,
        }
        priority = priority_map.get(alert_level, PushPriority.NORMAL)

        return {
            "should_push": True,
            "channels": self._get_channels_for_priority(priority),
            "reason": f"预警级别 {alert_level}，推送至 {priority.value} 渠道",
            "silent_overridden": False,
        }

    def _is_silent_time(self, now: time) -> bool:
        if self._silent_start <= self._silent_end:
            return self._silent_start <= now <= self._silent_end
        else:
            return now >= self._silent_start or now <= self._silent_end

    def _get_channels_for_priority(self, priority: PushPriority) -> List[str]:
        channel_map = {
            PushPriority.URGENT: ["app", "wechat", "dingtalk"],
            PushPriority.HIGH: ["app", "wechat"],
            PushPriority.NORMAL: ["app"],
            PushPriority.LOW: ["app"],
        }
        available = channel_map.get(priority, ["app"])
        return [ch for ch in available if ch in self._enabled_channels]

    def format_push_message(self, alert: Dict[str, Any]) -> Dict[str, str]:
        """格式化推送消息"""
        level = alert.get("level", "info")
        title = alert.get("title", "系统通知")
        message = alert.get("message", "")
        action = alert.get("action", "")
        symbol = alert.get("symbol", "")

        level_emoji = {
            "critical": "🚨",
            "high": "⚠️",
            "medium": "📋",
            "low": "💡",
            "info": "ℹ️",
        }.get(level, "ℹ️")

        app_title = f"{level_emoji} {title}"
        app_body = message
        if action:
            app_body += f"\n\n建议操作: {action}"

        wechat_title = f"量化系统预警 - {title}"
        wechat_body = f"{message}"
        if symbol:
            wechat_body = f"[{symbol}] {message}"
        if action:
            wechat_body += f"\n建议: {action}"

        return {
            "app_title": app_title,
            "app_body": app_body,
            "wechat_title": wechat_title,
            "wechat_body": wechat_body,
        }

    def record_push(self, alert: Dict, channels: List[str], success: bool):
        """记录推送历史"""
        self._push_history.append({
            "alert_id": alert.get("id", ""),
            "channels": channels,
            "success": success,
            "timestamp": datetime.now().isoformat(),
        })

    def get_push_stats(self) -> Dict[str, Any]:
        """获取推送统计"""
        total = len(self._push_history)
        successful = sum(1 for p in self._push_history if p.get("success"))
        return {
            "total_pushes": total,
            "successful": successful,
            "success_rate": round(successful / total, 4) if total > 0 else 0,
        }

    def update_silent_window(self, start: str, end: str):
        """更新免打扰时段"""
        self._silent_start = self._parse_time(start)
        self._silent_end = self._parse_time(end)

    def update_channels(self, channels: List[str]):
        """更新启用渠道"""
        self._enabled_channels = channels
