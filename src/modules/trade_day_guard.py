# -*- coding: utf-8 -*-
"""
A-share trade-day guard.

目标：
1) 盘中交易前先判断“今天是否为真实交易日”（不仅是周一到周五）。
2) 默认严格模式：若无法确认交易日，宁可不交易，避免节假日误触发。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional, Tuple

from src.core.config import ConfigManager
from src.core.database import DatabaseManager
from src.core.logger import get_logger
from src.modules.data_updater import DataUpdater

logger = get_logger("trade_day_guard")


def _to_bool(value: Any, default: bool = True) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return bool(default)
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on", "y"}:
        return True
    if text in {"0", "false", "no", "off", "n"}:
        return False
    return bool(default)


def is_cn_a_share_trade_day(
    now: datetime,
    db: Optional[DatabaseManager],
    config: Optional[ConfigManager],
    cache: Optional[Dict[str, Any]] = None,
) -> Tuple[bool, str]:
    """
    返回 (是否交易日, 判定来源)。

    判定顺序：
      1. 周末直接否决
      2. 当天缓存命中直接返回
      3. 数据库 stock_daily 同日存在 -> 交易日
      4. 交易日历接口校验（Tushare trade_cal）
      5. 严格模式：无法确认则否决；非严格模式回退“工作日”
    """
    if now.weekday() >= 5:
        if isinstance(cache, dict):
            cache.update(
                {
                    "date": now.strftime("%Y%m%d"),
                    "is_open": False,
                    "source": "weekend",
                    "checked_at": now.strftime("%Y-%m-%d %H:%M:%S"),
                }
            )
        return False, "weekend"

    day = now.strftime("%Y%m%d")
    if isinstance(cache, dict) and cache.get("date") == day and "is_open" in cache:
        return bool(cache.get("is_open", False)), str(cache.get("source", "cache"))

    strict_mode = True
    if config is not None and hasattr(config, "get"):
        strict_mode = _to_bool(config.get("monitor.require_trade_calendar_open", True), default=True)

    is_open = False
    source = "unknown"

    try:
        if db is not None and hasattr(db, "get_trade_dates"):
            same_day = db.get_trade_dates(day, day)
            if day in set(str(x) for x in (same_day or [])):
                is_open = True
                source = "db_stock_daily"
    except Exception as exc:
        logger.warning("trade-day db check failed: %s", exc)

    if not is_open:
        try:
            if db is not None and config is not None:
                updater = DataUpdater(config=config, db=db)
                calendar_days = updater._resolve_trade_calendar(day, day)
                if day in set(str(x) for x in (calendar_days or [])):
                    is_open = True
                    source = "calendar_api"
                else:
                    source = "calendar_api_closed"
            else:
                source = "calendar_unavailable"
        except Exception as exc:
            source = "calendar_error"
            logger.warning("trade-day calendar check failed: %s", exc)

    if not is_open and not strict_mode:
        is_open = now.weekday() < 5
        source = "weekday_fallback"

    if isinstance(cache, dict):
        cache.update(
            {
                "date": day,
                "is_open": bool(is_open),
                "source": source,
                "checked_at": now.strftime("%Y-%m-%d %H:%M:%S"),
            }
        )
    return bool(is_open), source

