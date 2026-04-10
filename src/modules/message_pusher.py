# -*- coding: utf-8 -*-
"""
消息推送模块
支持企业微信机器人消息推送
"""

import json
import random
import requests
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

from src.core.logger import get_logger
from src.core.config import ConfigManager
from src.core.database import DatabaseManager
from src.core.exceptions import PushException
from src.modules.push_outbox_store import PushOutboxStore
from src.modules.message_templates import (
    build_daily_report_markdown,
    build_feedback_digest_markdown,
    build_position_events_markdown,
    build_pre_market_selection_markdown,
    build_trade_signals_markdown,
)

logger = get_logger("push")


class WeChatWorkPusher:
    """企业微信机器人推送器"""
    
    def __init__(
        self,
        webhook_url: str = None,
        timeout: int = 10,
        min_interval_seconds: float = 0.7,
        rate_limit_retry_attempts: int = 2,
        rate_limit_backoff_seconds: float = 1.2,
        retry_jitter_seconds: float = 0.2,
    ):
        """
        初始化企业微信推送器
        
        Args:
            webhook_url: 企业微信机器人webhook地址
            timeout: HTTP 请求超时秒数（默认 10s），可通过配置调整避免阻塞监控主线程
        """
        self.webhook_url = webhook_url
        self.timeout = timeout
        self.min_interval_seconds = max(0.0, float(min_interval_seconds))
        self.rate_limit_retry_attempts = max(0, int(rate_limit_retry_attempts))
        self.rate_limit_backoff_seconds = max(0.1, float(rate_limit_backoff_seconds))
        self.retry_jitter_seconds = max(0.0, float(retry_jitter_seconds))
        self._next_send_ts = 0.0

    def _wait_for_send_window(self):
        if self.min_interval_seconds <= 0:
            return
        now_ts = time.monotonic()
        if now_ts < self._next_send_ts:
            time.sleep(self._next_send_ts - now_ts)
            now_ts = time.monotonic()
        self._next_send_ts = now_ts + self.min_interval_seconds

    @staticmethod
    def _is_rate_limited_response(errcode: Any, errmsg: str) -> bool:
        text = str(errmsg or "")
        if int(errcode or 0) in {45009}:
            return True
        keywords = ("并发", "每分钟最多", "每小时最多", "rate limit", "too many requests")
        return any(k in text for k in keywords)
    
    def _send_request(self, data: Dict) -> bool:
        """
        发送请求到企业微信
        
        Args:
            data: 请求数据
        
        Returns:
            是否成功
        """
        if not self.webhook_url:
            logger.warning("企业微信webhook未配置")
            return False
        
        headers = {"Content-Type": "application/json; charset=utf-8"}
        payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
        max_attempts = self.rate_limit_retry_attempts + 1
        last_error = ""

        for attempt in range(max_attempts):
            try:
                self._wait_for_send_window()
                response = requests.post(
                    self.webhook_url,
                    data=payload,
                    headers=headers,
                    timeout=self.timeout,
                )

                result = response.json()
                errcode = int(result.get("errcode", -1))
                errmsg = str(result.get("errmsg", "") or "")
                if errcode == 0:
                    logger.info("企业微信消息发送成功")
                    return True

                last_error = f"{errcode}:{errmsg}"
                if self._is_rate_limited_response(errcode, errmsg) and attempt < max_attempts - 1:
                    sleep_s = self.rate_limit_backoff_seconds * (2 ** attempt)
                    sleep_s += random.uniform(0.0, self.retry_jitter_seconds)
                    logger.warning(
                        "企业微信触发限流/并发限制，%.2fs 后重试 (%d/%d): %s",
                        sleep_s,
                        attempt + 1,
                        max_attempts,
                        errmsg,
                    )
                    time.sleep(sleep_s)
                    continue

                logger.error("企业微信消息发送失败: %s", last_error)
                return False
            except Exception as e:
                last_error = str(e)
                if attempt < max_attempts - 1:
                    sleep_s = self.rate_limit_backoff_seconds * (2 ** attempt)
                    sleep_s += random.uniform(0.0, self.retry_jitter_seconds)
                    logger.warning(
                        "企业微信发送异常，%.2fs 后重试 (%d/%d): %s",
                        sleep_s,
                        attempt + 1,
                        max_attempts,
                        e,
                    )
                    time.sleep(sleep_s)
                    continue
                logger.error("企业微信消息发送异常: %s", e)
                return False

        logger.error("企业微信消息发送失败(重试后): %s", last_error)
        return False
    
    def send_text(self, content: str, mentioned_list: List[str] = None) -> bool:
        """
        发送文本消息
        
        Args:
            content: 文本内容
            mentioned_list: @人员列表
        
        Returns:
            是否成功
        """
        data = {
            "msgtype": "text",
            "text": {
                "content": content
            }
        }
        
        if mentioned_list:
            data["text"]["mentioned_list"] = mentioned_list
        
        return self._send_request(data)
    
    def send_markdown(self, content: str) -> bool:
        """
        发送Markdown消息
        
        Args:
            content: Markdown内容
        
        Returns:
            是否成功
        """
        data = {
            "msgtype": "markdown",
            "markdown": {
                "content": content
            }
        }
        
        return self._send_request(data)
    
    def send_card(self, title: str, description: str, url: str = None, 
                  btntxt: str = "详情") -> bool:
        """
        发送卡片消息
        
        Args:
            title: 标题
            description: 描述
            url: 跳转链接
            btntxt: 按钮文本
        
        Returns:
            是否成功
        """
        data = {
            "msgtype": "template_card",
            "template_card": {
                "card_type": "text_notice",
                "source": {
                    "desc": "量化交易系统"
                },
                "main_title": {
                    "title": title
                },
                "sub_title_text": description
            }
        }
        
        if url:
            data["template_card"]["card_action"] = {
                "type": 1,
                "url": url
            }
        
        return self._send_request(data)


class MessagePusher:
    """消息推送管理器"""
    
    def __init__(self, config: ConfigManager = None, db: DatabaseManager = None):
        """
        初始化消息推送管理器
        
        Args:
            config: 配置管理器
        """
        if config is None:
            config = ConfigManager()
        
        self.config = config
        self.db = db or DatabaseManager(config)
        self.enabled = config.get("push.enabled", False)
        self.position_push_enabled = config.get("push.position_push_enabled", True)
        push_timeout = int(config.get("push.request_timeout_seconds", 8))
        webhook_min_interval_seconds = float(config.get("push.webhook_min_interval_seconds", 0.7))
        webhook_rate_limit_retry_attempts = int(
            config.get("push.webhook_rate_limit_retry_attempts", 2)
        )
        webhook_rate_limit_backoff_seconds = float(
            config.get("push.webhook_rate_limit_backoff_seconds", 1.2)
        )
        webhook_retry_jitter_seconds = float(
            config.get("push.webhook_retry_jitter_seconds", 0.2)
        )
        self.outbox_enabled = bool(config.get("push.outbox_enabled", True))
        self.outbox_retry_delay_seconds = int(config.get("push.outbox_retry_delay_seconds", 60))
        self.outbox_max_attempts = int(config.get("push.outbox_max_attempts", 5))
        self.outbox_store = PushOutboxStore(self.db) if self.outbox_enabled else None
        
        # 初始化企业微信推送器
        wechat_webhook = config.get("push.wechat_webhook", "")
        self.wechat_pusher = (
            WeChatWorkPusher(
                wechat_webhook,
                timeout=push_timeout,
                min_interval_seconds=webhook_min_interval_seconds,
                rate_limit_retry_attempts=webhook_rate_limit_retry_attempts,
                rate_limit_backoff_seconds=webhook_rate_limit_backoff_seconds,
                retry_jitter_seconds=webhook_retry_jitter_seconds,
            )
            if wechat_webhook
            else None
        )
        position_webhook = config.get("push.position_wechat_webhook", "")
        self.position_wechat_pusher = (
            WeChatWorkPusher(
                position_webhook,
                timeout=push_timeout,
                min_interval_seconds=webhook_min_interval_seconds,
                rate_limit_retry_attempts=webhook_rate_limit_retry_attempts,
                rate_limit_backoff_seconds=webhook_rate_limit_backoff_seconds,
                retry_jitter_seconds=webhook_retry_jitter_seconds,
            )
            if position_webhook
            else None
        )
        
        if self.enabled and not wechat_webhook:
            logger.error("推送已启用但 wechat_webhook 未配置，推送将静默失败！请设置 WECHAT_WEBHOOK 环境变量")
            logger.error("push is enabled but wechat webhook is missing")
        
        logger.info(f"消息推送管理器初始化完成，启用状态: {self.enabled}")

    def _enqueue_outbox(self, channel: str, msg_type: str, payload: Dict[str, Any], error: str = "") -> bool:
        if not self.outbox_store:
            return False
        return self.outbox_store.enqueue(
            channel=channel,
            msg_type=msg_type,
            payload=payload,
            max_attempts=self.outbox_max_attempts,
            retry_delay_seconds=self.outbox_retry_delay_seconds,
            last_error=error,
        )
    
    def push_text(self, content: str, channel: str = "wechat") -> bool:
        """
        推送文本消息
        
        Args:
            content: 文本内容
            channel: 推送渠道
        
        Returns:
            是否成功
        """
        if not self.enabled:
            logger.info("消息推送已禁用")
            return False

        if channel == "wechat":
            if not self.wechat_pusher:
                logger.error("wechat channel unavailable: webhook not configured")
                return False
            return self.wechat_pusher.send_text(content)

        if channel == "position":
            if not self.position_push_enabled:
                logger.info("持仓推送通道已禁用")
                return False
            if self.position_wechat_pusher:
                return self.position_wechat_pusher.send_text(content)
            if self.wechat_pusher:
                logger.warning("持仓webhook未配置，降级到主webhook")
                return self.wechat_pusher.send_text(content)
            logger.error("position channel unavailable: both position/main webhook are missing")
            return False

        logger.warning("不支持的文本推送渠道: %s", channel)
        return False
    
    def push_markdown(self, content: str, channel: str = "wechat", enqueue_on_fail: bool = True) -> bool:
        """
        推送Markdown消息
        
        Args:
            content: Markdown内容
            channel: 推送渠道
        
        Returns:
            是否成功
        """
        if not self.enabled:
            logger.info("消息推送已禁用")
            return False

        if channel == "wechat":
            if not self.wechat_pusher:
                logger.error("wechat channel unavailable: webhook not configured")
                if enqueue_on_fail:
                    self._enqueue_outbox(
                        channel="wechat",
                        msg_type="markdown",
                        payload={"content": content},
                        error="wechat_webhook_missing",
                    )
                return False
            ok = self.wechat_pusher.send_markdown(content)
            if not ok and enqueue_on_fail:
                self._enqueue_outbox(
                    channel="wechat",
                    msg_type="markdown",
                    payload={"content": content},
                    error="wechat_markdown_failed",
                )
            return ok

        if channel == "position":
            if not self.position_push_enabled:
                logger.info("持仓推送通道已禁用")
                return False
            if self.position_wechat_pusher:
                ok = self.position_wechat_pusher.send_markdown(content)
                if not ok and enqueue_on_fail:
                    self._enqueue_outbox(
                        channel="position",
                        msg_type="markdown",
                        payload={"content": content},
                        error="position_markdown_failed",
                    )
                return ok
            if self.wechat_pusher:
                logger.warning("持仓webhook未配置，降级到主webhook")
                ok = self.wechat_pusher.send_markdown(content)
                if not ok and enqueue_on_fail:
                    self._enqueue_outbox(
                        channel="wechat",
                        msg_type="markdown",
                        payload={"content": content},
                        error="wechat_markdown_failed",
                    )
                return ok

            logger.error("position channel unavailable: both position/main webhook are missing")
            if enqueue_on_fail:
                self._enqueue_outbox(
                    channel="position",
                    msg_type="markdown",
                    payload={"content": content},
                    error="position_webhook_missing",
                )
            return False

        logger.warning("不支持的 Markdown 推送渠道: %s", channel)
        if enqueue_on_fail:
            self._enqueue_outbox(
                channel=channel,
                msg_type="markdown",
                payload={"content": content},
                error=f"unsupported_channel:{channel}",
            )
        return False
    
    def push_risk_signal(self, signal: Dict) -> bool:
        """
        推送风控信号
        
        Args:
            signal: 风控信号信息
        
        Returns:
            是否成功
        """
        severity_emoji = {
            "高": "🔴",
            "中": "🟡",
            "低": "🟢"
        }
        
        emoji = severity_emoji.get(signal.get("severity", "中"), "🟡")
        
        content = f"""## {emoji} 风控信号提醒

**股票**: {signal.get('ts_code', '')} {signal.get('name', '')}
**信号类型**: {signal.get('signal_type', '')}
**风险等级**: {signal.get('severity', '')}风险
**触发时间**: {signal.get('trigger_time', '')}

**触发原因**:
{signal.get('reason', '')}

**操作建议**:
> {signal.get('suggestion', '')}

**当前价格**: {signal.get('current_price', 0)}元
**当前盈亏**: {signal.get('profit', 0)}%
"""
        
        return self.push_markdown(content)
    
    def push_daily_report(self, report_data: Dict) -> bool:
        """
        推送每日日报
        
        Args:
            report_data: 日报数据
        
        Returns:
            是否成功
        """
        return self.push_markdown(build_daily_report_markdown(report_data))

    def push_pre_market_selection(self, report_data: Dict) -> bool:
        """
        推送盘前选股计划（计划型模板）。

        与盘中买卖点推送解耦，专注盘前“候选+条件+执行约束”。
        """
        return self.push_markdown(build_pre_market_selection_markdown(report_data))

    def push_trade_signals(
        self,
        signals: List[Dict],
        now: Optional[datetime] = None,
        filtered_count: int = 0,
        side: str = "buy",
    ) -> bool:
        """推送盘中买卖点信号（手机阅读优化版）。"""
        if not (signals or []):
            return False
        return self.push_markdown(
            build_trade_signals_markdown(
                signals=signals,
                now=now,
                filtered_count=filtered_count,
                side=side,
            )
        )

    def push_position_events(
        self,
        events: List[Dict],
        now: Optional[datetime] = None,
    ) -> bool:
        """推送持仓管理事件（手机阅读优化版）。"""
        if not (events or []):
            return False
        return self.push_markdown(
            build_position_events_markdown(events=events, now=now),
            channel="position",
        )

    def push_feedback_digest(
        self,
        feedback_data: Dict,
        now: Optional[datetime] = None,
    ) -> bool:
        """
        推送盘后闭环反馈摘要（独立模板）。
        """
        return self.push_markdown(build_feedback_digest_markdown(feedback_data, now=now))

    def push_trade_plan(self, plan_data: Dict) -> bool:
        """
        推送交易计划
        
        Args:
            plan_data: 交易计划数据
        
        Returns:
            是否成功
        """
        content = f"""## 📋 尾盘交易计划

**生成时间**: {plan_data.get('generate_time', '')}
**市场评分**: {plan_data.get('market_score', 0)}分

---

### 市场状态

{plan_data.get('market_status', '')}

### 操作建议

{plan_data.get('suggestion', '')}

---

### 持仓操作

{plan_data.get('hold_suggestion', '暂无持仓')}

---

*请在收盘前完成相关操作*
"""
        
        return self.push_markdown(content)
    
    def push_data_update_result(self, result: Dict) -> bool:
        """
        推送数据更新结果
        
        Args:
            result: 更新结果
        
        Returns:
            是否成功
        """
        status = "✅ 成功" if result.get("status") == "success" else "❌ 失败"
        
        content = f"""## 📥 数据更新通知

**更新时间**: {result.get('end_time', '')}
**状态**: {status}

---

**股票基础信息**: {result.get('stock_basic_count', 0)}条
**日线数据**: {result.get('daily_data_count', 0)}条
**指数数据**: {result.get('index_data_count', 0)}条

---

{result.get('message', '')}
"""
        
        return self.push_markdown(content)

    def push_system_alert(self, alert: Any) -> bool:
        """
        推送系统级运行告警。

        Args:
            alert: 告警对象或字典

        Returns:
            是否成功
        """
        if hasattr(alert, "to_dict"):
            alert = alert.to_dict()

        severity = str(alert.get("severity", "warning")).lower()
        severity_badge = {
            "info": "INFO",
            "warning": "WARNING",
            "error": "ERROR",
            "critical": "CRITICAL",
        }.get(severity, "WARNING")

        context = alert.get("context") or {}
        context_lines = ""
        if context:
            context_lines = "\n".join(
                f"- **{key}**: {value}" for key, value in sorted(context.items())
            )

        content = f"""## 系统运行告警

**级别**: {severity_badge}
**组件**: {alert.get('component', 'unknown')}
**分类**: {alert.get('category', 'system')}
**时间**: {alert.get('timestamp', datetime.now().strftime('%Y-%m-%d %H:%M:%S'))}
**错误码**: {alert.get('error_code', 'N/A')}
**可重试**: {'是' if alert.get('retryable') else '否'}

### 标题
{alert.get('title', '系统告警')}

### 详情
{alert.get('message', '')}
"""

        if context_lines:
            content += f"\n### 上下文\n{context_lines}\n"

        return self.push_markdown(content)

    def push_custom_message(self, title: str, content: str) -> bool:
        """
        推送自定义消息
        
        Args:
            title: 标题
            content: 内容
        
        Returns:
            是否成功
        """
        full_content = f"""## {title}

{content}

---
*发送时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*
"""
        
        return self.push_markdown(full_content)
