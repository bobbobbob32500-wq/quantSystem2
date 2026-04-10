# -*- coding: utf-8 -*-
"""
持仓事件推送存储：
1. 事件去重（event_id 唯一）
2. 推送状态落库（pending/success/failed）
3. 失败重试队列
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from src.core.database import DatabaseManager
from src.core.logger import get_logger

logger = get_logger("position_event_store")


class PositionEventStore:
    """持仓事件存储仓库。"""

    def __init__(self, db: DatabaseManager):
        self.db = db
        self._ensure_table()

    def _ensure_table(self) -> None:
        create_sql = """
            CREATE TABLE IF NOT EXISTS position_push_event (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id TEXT NOT NULL UNIQUE,
                event_type TEXT NOT NULL,
                ts_code TEXT,
                name TEXT,
                severity TEXT,
                payload TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                retry_count INTEGER NOT NULL DEFAULT 0,
                max_retry INTEGER NOT NULL DEFAULT 3,
                next_retry_time TEXT,
                last_error TEXT,
                created_time TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_time TEXT DEFAULT CURRENT_TIMESTAMP,
                pushed_time TEXT
            )
        """
        idx_sql = [
            "CREATE INDEX IF NOT EXISTS idx_position_event_status ON position_push_event(status)",
            "CREATE INDEX IF NOT EXISTS idx_position_event_next_retry ON position_push_event(next_retry_time)",
            "CREATE INDEX IF NOT EXISTS idx_position_event_ts_code ON position_push_event(ts_code)",
        ]
        self.db.execute(create_sql)
        for sql in idx_sql:
            self.db.execute(sql)

    @staticmethod
    def _now_str() -> str:
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def enqueue_event(self, event: Dict[str, Any], max_retry: int = 3) -> bool:
        """
        入队事件；event_id 已存在时返回 False（去重）。
        """
        event_id = str(event.get("event_id", "")).strip()
        if not event_id:
            raise ValueError("event_id is required")

        exists = self.db.query_one(
            "SELECT event_id FROM position_push_event WHERE event_id = ?",
            (event_id,),
        )
        if exists:
            return False

        payload = json.dumps(event, ensure_ascii=False)
        now = self._now_str()
        self.db.execute(
            """
            INSERT INTO position_push_event (
                event_id, event_type, ts_code, name, severity, payload,
                status, retry_count, max_retry, next_retry_time, last_error,
                created_time, updated_time
            )
            VALUES (?, ?, ?, ?, ?, ?, 'pending', 0, ?, ?, NULL, ?, ?)
            """,
            (
                event_id,
                str(event.get("event_type", "position_alert")),
                str(event.get("ts_code", "")),
                str(event.get("name", "")),
                str(event.get("severity", "medium")),
                payload,
                int(max_retry),
                now,
                now,
                now,
            ),
        )
        return True

    def list_retryable_events(self, limit: int = 20) -> List[Dict[str, Any]]:
        now = self._now_str()
        rows = self.db.query(
            """
            SELECT event_id, payload, retry_count, max_retry, status
            FROM position_push_event
            WHERE status IN ('pending', 'failed')
              AND retry_count < max_retry
              AND (next_retry_time IS NULL OR next_retry_time <= ?)
            ORDER BY created_time ASC
            LIMIT ?
            """,
            (now, int(max(1, limit))),
        )

        events: List[Dict[str, Any]] = []
        for row in rows or []:
            try:
                payload = json.loads(str(row.get("payload", "{}")))
                payload["event_id"] = str(row.get("event_id", payload.get("event_id", "")))
                payload["_retry_count"] = int(row.get("retry_count", 0) or 0)
                payload["_max_retry"] = int(row.get("max_retry", 0) or 0)
                payload["_status"] = str(row.get("status", "pending"))
                events.append(payload)
            except Exception as e:
                logger.warning("invalid payload for event %s: %s", row.get("event_id"), e)
        return events

    def mark_success(self, event_id: str) -> None:
        now = self._now_str()
        self.db.execute(
            """
            UPDATE position_push_event
            SET status = 'success',
                pushed_time = ?,
                updated_time = ?,
                last_error = NULL
            WHERE event_id = ?
            """,
            (now, now, str(event_id)),
        )

    def mark_failed(self, event_id: str, error: str = "", retry_delay_seconds: int = 60) -> None:
        row = self.db.query_one(
            "SELECT retry_count FROM position_push_event WHERE event_id = ?",
            (str(event_id),),
        )
        if not row:
            return

        retry_count = int(row.get("retry_count", 0) or 0) + 1
        next_retry = datetime.now() + timedelta(seconds=max(0, int(retry_delay_seconds)))
        now = self._now_str()
        self.db.execute(
            """
            UPDATE position_push_event
            SET status = 'failed',
                retry_count = ?,
                next_retry_time = ?,
                updated_time = ?,
                last_error = ?
            WHERE event_id = ?
            """,
            (
                retry_count,
                next_retry.strftime("%Y-%m-%d %H:%M:%S"),
                now,
                str(error or "")[:500],
                str(event_id),
            ),
        )

    def get_status(self, event_id: str) -> Optional[Dict[str, Any]]:
        return self.db.query_one(
            """
            SELECT event_id, status, retry_count, max_retry, last_error, created_time, pushed_time
            FROM position_push_event
            WHERE event_id = ?
            """,
            (str(event_id),),
        )
