# -*- coding: utf-8 -*-
"""
通用推送 Outbox（发件箱）：
- 任何推送失败都应落库入队，避免“失败即丢”
- 定时任务负责重试，支持幂等键防重复
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from src.core.database import DatabaseManager
from src.core.logger import get_logger

logger = get_logger("push_outbox")


class PushOutboxStore:
    def __init__(self, db: DatabaseManager):
        self.db = db
        self._ensure_table()

    def _ensure_table(self):
        self.db.execute(
            """
            CREATE TABLE IF NOT EXISTS push_outbox (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                idempotency_key TEXT UNIQUE NOT NULL,
                channel TEXT NOT NULL,
                msg_type TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                attempts INTEGER NOT NULL DEFAULT 0,
                max_attempts INTEGER NOT NULL DEFAULT 5,
                next_retry_time TEXT,
                last_error TEXT,
                created_time TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_time TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        self.db.execute(
            "CREATE INDEX IF NOT EXISTS idx_push_outbox_status_time ON push_outbox(status, next_retry_time)"
        )

    @staticmethod
    def build_idempotency_key(channel: str, msg_type: str, payload: Dict[str, Any]) -> str:
        raw = json.dumps({"c": channel, "t": msg_type, "p": payload}, ensure_ascii=False, sort_keys=True)
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()

    def enqueue(
        self,
        channel: str,
        msg_type: str,
        payload: Dict[str, Any],
        max_attempts: int = 5,
        retry_delay_seconds: int = 60,
        idempotency_key: Optional[str] = None,
        last_error: str = "",
    ) -> bool:
        key = idempotency_key or self.build_idempotency_key(channel, msg_type, payload)
        next_retry = (datetime.now() + timedelta(seconds=max(1, int(retry_delay_seconds)))).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
        try:
            self.db.execute(
                """
                INSERT OR IGNORE INTO push_outbox (
                    idempotency_key, channel, msg_type, payload_json, status,
                    attempts, max_attempts, next_retry_time, last_error, updated_time
                ) VALUES (?, ?, ?, ?, 'pending', 0, ?, ?, ?, ?)
                """,
                (
                    key,
                    str(channel),
                    str(msg_type),
                    json.dumps(payload, ensure_ascii=False),
                    int(max(1, max_attempts)),
                    next_retry,
                    str(last_error or ""),
                    datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                ),
            )
            return True
        except Exception as exc:
            logger.error("enqueue outbox failed: %s", exc)
            return False

    def list_retryable(self, limit: int = 50) -> List[Dict[str, Any]]:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        rows = self.db.query(
            """
            SELECT id, idempotency_key, channel, msg_type, payload_json, attempts, max_attempts, next_retry_time
            FROM push_outbox
            WHERE status IN ('pending', 'failed')
              AND (next_retry_time IS NULL OR next_retry_time <= ?)
              AND attempts < max_attempts
            ORDER BY next_retry_time ASC, id ASC
            LIMIT ?
            """,
            (now, int(limit)),
        )
        for row in rows:
            try:
                row["payload"] = json.loads(row.pop("payload_json") or "{}")
            except Exception:
                row["payload"] = {}
        return rows

    def mark_success(self, row_id: int):
        self.db.execute(
            """
            UPDATE push_outbox
            SET status='success', updated_time=?
            WHERE id=?
            """,
            (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), int(row_id)),
        )

    def mark_failed(self, row_id: int, error: str, retry_delay_seconds: int = 60):
        next_retry = (datetime.now() + timedelta(seconds=max(1, int(retry_delay_seconds)))).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
        self.db.execute(
            """
            UPDATE push_outbox
            SET status='failed',
                attempts=attempts+1,
                last_error=?,
                next_retry_time=?,
                updated_time=?
            WHERE id=?
            """,
            (
                str(error or "push failed"),
                next_retry,
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                int(row_id),
            ),
        )

