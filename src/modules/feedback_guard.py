# -*- coding: utf-8 -*-
"""
闭环表现防护模块

目标：
1. 基于 signal_feedback_detail 评估最近 20/60 日闭环表现；
2. 输出 normal / caution / defensive 档位；
3. 为盘前与盘中模块提供统一的风控闸门输入。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from src.core.config import ConfigManager
from src.core.database import DatabaseManager
from src.core.logger import get_logger

logger = get_logger("feedback_guard")


class FeedbackPerformanceGuard:
    """闭环表现防护评估器。"""

    SOURCE_PRE_MARKET = "pre_market_recommendation"
    SOURCE_INTRADAY = "intraday_signal"

    def __init__(self, config: ConfigManager = None, db: DatabaseManager = None):
        if config is None:
            config = ConfigManager()
        if db is None:
            db = DatabaseManager(config)

        self.config = config
        self.db = db

        self.enabled = bool(config.get("feedback.guard_enabled", True))
        raw_windows = config.get("feedback.guard_windows", [20, 60])
        self.windows = self._parse_windows(raw_windows)
        self.min_samples = int(config.get("feedback.guard_min_samples", 20))
        self.pre_market_horizon = int(config.get("feedback.guard_pre_market_horizon", 2))
        self.sell_horizon = int(config.get("feedback.guard_sell_horizon", 3))
        self.require_sell_confirmation = bool(
            config.get("feedback.guard_require_sell_confirmation", False)
        )
        self.negative_threshold = float(config.get("feedback.guard_negative_threshold", 0.0))

        self._cache: Dict[str, Dict[str, Any]] = {}

    @staticmethod
    def _parse_windows(raw: Any) -> List[int]:
        values: List[int] = []
        if isinstance(raw, (list, tuple)):
            for x in raw:
                try:
                    values.append(int(x))
                except Exception:
                    continue
        elif raw is not None:
            for token in str(raw).split(","):
                token = token.strip()
                if not token:
                    continue
                try:
                    values.append(int(token))
                except Exception:
                    continue
        if not values:
            values = [20, 60]
        return sorted(set([max(1, int(v)) for v in values]))

    @staticmethod
    def _norm_date(value: Any) -> Optional[str]:
        if value is None:
            return None
        s = str(value).strip()
        if not s:
            return None
        digits = "".join(ch for ch in s if ch.isdigit())
        if len(digits) < 8:
            return None
        return digits[:8]

    def _resolve_end_date(self, end_date: Optional[str] = None) -> str:
        norm = self._norm_date(end_date)
        if norm:
            return norm
        latest = self._norm_date(self.db.get_latest_trade_date("stock_daily"))
        if latest:
            return latest
        return datetime.now().strftime("%Y%m%d")

    def _resolve_window_start(self, end_date: str, window_days: int) -> str:
        try:
            rows = self.db.query(
                """
                SELECT trade_date
                FROM stock_daily
                WHERE trade_date <= ?
                GROUP BY trade_date
                ORDER BY trade_date DESC
                LIMIT ?
                """,
                (end_date, int(window_days)),
            )
        except Exception as exc:
            logger.warning("feedback guard window start fallback: %s", exc)
            return end_date
        if not rows:
            return end_date
        trade_dates = [self._norm_date(r.get("trade_date")) for r in rows]
        trade_dates = [d for d in trade_dates if d]
        if not trade_dates:
            return end_date
        return min(trade_dates)

    def _query_window_stat(
        self,
        source_type: str,
        direction: str,
        horizon: int,
        start_date: str,
        end_date: str,
    ) -> Dict[str, Any]:
        try:
            row = self.db.query_one(
                """
                SELECT
                    COUNT(*) AS sample_count,
                    AVG(net_return) AS mean_net_return,
                    AVG(CASE WHEN net_return > 0 THEN 1.0 ELSE 0.0 END) AS win_rate
                FROM signal_feedback_detail
                WHERE source_type = ?
                  AND direction = ?
                  AND horizon = ?
                  AND signal_date >= ?
                  AND signal_date <= ?
                """,
                (str(source_type), str(direction), int(horizon), str(start_date), str(end_date)),
            ) or {}
        except Exception as exc:
            logger.warning(
                "feedback guard stat query fallback: source=%s direction=%s horizon=%s err=%s",
                source_type,
                direction,
                horizon,
                exc,
            )
            return {
                "sample_count": 0,
                "mean_net_return": 0.0,
                "win_rate": 0.0,
            }

        return {
            "sample_count": int(row.get("sample_count", 0) or 0),
            "mean_net_return": float(row.get("mean_net_return", 0.0) or 0.0),
            "win_rate": float(row.get("win_rate", 0.0) or 0.0),
        }

    def _is_negative(self, item: Dict[str, Any]) -> bool:
        return (
            int(item.get("sample_count", 0) or 0) >= int(self.min_samples)
            and float(item.get("mean_net_return", 0.0) or 0.0) < self.negative_threshold
        )

    def evaluate(self, end_date: Optional[str] = None) -> Dict[str, Any]:
        if not self.enabled:
            return {
                "enabled": False,
                "level": "normal",
                "active": False,
                "reason": "guard_disabled",
                "end_date": self._resolve_end_date(end_date),
                "windows": {},
            }

        resolved_end = self._resolve_end_date(end_date)
        cached = self._cache.get(resolved_end)
        if cached:
            return dict(cached)

        windows_payload: Dict[str, Any] = {}
        for window in self.windows:
            start = self._resolve_window_start(resolved_end, window)
            pre = self._query_window_stat(
                source_type=self.SOURCE_PRE_MARKET,
                direction="buy",
                horizon=self.pre_market_horizon,
                start_date=start,
                end_date=resolved_end,
            )
            sell = self._query_window_stat(
                source_type=self.SOURCE_INTRADAY,
                direction="sell",
                horizon=self.sell_horizon,
                start_date=start,
                end_date=resolved_end,
            )
            windows_payload[str(window)] = {
                "window_days": int(window),
                "start_date": start,
                "end_date": resolved_end,
                "pre_market": pre,
                "sell_signal": sell,
            }

        short_window = self.windows[0]
        long_window = self.windows[-1]
        short_data = windows_payload.get(str(short_window), {})
        long_data = windows_payload.get(str(long_window), {})
        short_pre = short_data.get("pre_market", {})
        long_pre = long_data.get("pre_market", {})
        short_sell = short_data.get("sell_signal", {})
        long_sell = long_data.get("sell_signal", {})

        short_pre_neg = self._is_negative(short_pre)
        long_pre_neg = self._is_negative(long_pre)
        short_sell_neg = self._is_negative(short_sell)
        long_sell_neg = self._is_negative(long_sell)

        level = "normal"
        reason = "feedback_positive_or_insufficient"

        if short_pre_neg and long_pre_neg:
            sell_ok = True
            if self.require_sell_confirmation:
                sell_ok = short_sell_neg and long_sell_neg
            if sell_ok:
                level = "defensive"
                reason = "pre_market_negative_20_60d"
        if level == "normal" and short_pre_neg:
            if not self.require_sell_confirmation or short_sell_neg:
                level = "caution"
                reason = "pre_market_negative_20d"

        result = {
            "enabled": True,
            "level": level,
            "active": level in {"caution", "defensive"},
            "reason": reason,
            "end_date": resolved_end,
            "windows": windows_payload,
            "min_samples": int(self.min_samples),
            "pre_market_horizon": int(self.pre_market_horizon),
            "sell_horizon": int(self.sell_horizon),
        }
        self._cache[resolved_end] = dict(result)
        return result
