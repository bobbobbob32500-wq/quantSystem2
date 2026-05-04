# -*- coding: utf-8 -*-
"""
通用推送 Outbox（发件箱）：
- 任何推送失败都应落库入队，避免"失败即丢"
- 定时任务负责重试，支持幂等键防重复
- 指数退避重试策略，避免频繁重试浪费资源
- 推送统计与死信队列，支持运维监控
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from src.core.database import DatabaseManager
from src.core.logger import get_logger

logger = get_logger("push_outbox")

EXPONENTIAL_BACKOFF_DELAYS = [60, 180, 600, 1800, 3600]


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
        self._ensure_stats_table()

    def _ensure_stats_table(self):
        self.db.execute(
            """
            CREATE TABLE IF NOT EXISTS push_stats (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                channel TEXT NOT NULL,
                msg_type TEXT NOT NULL,
                status TEXT NOT NULL,
                latency_ms INTEGER,
                error_code TEXT,
                created_time TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        self.db.execute(
            "CREATE INDEX IF NOT EXISTS idx_push_stats_channel_time ON push_stats(channel, created_time)"
        )

    @staticmethod
    def build_idempotency_key(channel: str, msg_type: str, payload: Dict[str, Any]) -> str:
        raw = json.dumps({"c": channel, "t": msg_type, "p": payload}, ensure_ascii=False, sort_keys=True)
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()

    @staticmethod
    def _compute_backoff_delay(attempts: int, base_delay: int = 60) -> int:
        """根据重试次数计算指数退避延迟"""
        if attempts <= 0:
            return base_delay
        idx = min(attempts - 1, len(EXPONENTIAL_BACKOFF_DELAYS) - 1)
        return EXPONENTIAL_BACKOFF_DELAYS[idx]

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
        next_retry = (datetime.now() + timedelta(seconds=max(0, int(retry_delay_seconds)))).strftime(
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

    def mark_success(self, row_id: int, latency_ms: Optional[int] = None):
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.db.execute(
            """
            UPDATE push_outbox
            SET status='success', updated_time=?
            WHERE id=?
            """,
            (now_str, int(row_id)),
        )
        row = self.db.query("SELECT channel, msg_type FROM push_outbox WHERE id=?", (int(row_id),))
        if row:
            self._record_stat(row[0]["channel"], row[0]["msg_type"], "success", latency_ms=latency_ms)

    def mark_failed(
        self,
        row_id: int,
        error: str,
        base_retry_delay: int = 60,
        retry_delay_seconds: Optional[int] = None,
    ):
        row = self.db.query("SELECT attempts, channel, msg_type FROM push_outbox WHERE id=?", (int(row_id),))
        if not row:
            return
        current_attempts = int(row[0].get("attempts", 0))
        delay_base = (
            int(retry_delay_seconds)
            if retry_delay_seconds is not None
            else int(base_retry_delay)
        )
        backoff_delay = self._compute_backoff_delay(current_attempts + 1, delay_base)
        next_retry = (datetime.now() + timedelta(seconds=backoff_delay)).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
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
                now_str,
                int(row_id),
            ),
        )
        self._record_stat(row[0]["channel"], row[0]["msg_type"], "failed", error_code=str(error)[:200])

    def move_to_dead_letter(self, row_id: int, reason: str = "max_attempts_exceeded"):
        """将超过最大重试次数的消息移入死信状态"""
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.db.execute(
            """
            UPDATE push_outbox
            SET status='dead_letter',
                last_error=?,
                updated_time=?
            WHERE id=? AND attempts >= max_attempts
            """,
            (reason, now_str, int(row_id)),
        )
        row = self.db.query("SELECT channel, msg_type FROM push_outbox WHERE id=?", (int(row_id),))
        if row:
            self._record_stat(row[0]["channel"], row[0]["msg_type"], "dead_letter", error_code=reason)
            logger.warning("Message moved to dead_letter: id=%s channel=%s reason=%s", row_id, row[0]["channel"], reason)

    def list_dead_letters(self, limit: int = 50) -> List[Dict[str, Any]]:
        """查询死信队列"""
        rows = self.db.query(
            """
            SELECT id, channel, msg_type, payload_json, attempts, max_attempts, last_error, created_time, updated_time
            FROM push_outbox
            WHERE status='dead_letter'
            ORDER BY updated_time DESC
            LIMIT ?
            """,
            (int(limit),),
        )
        for row in rows:
            try:
                row["payload"] = json.loads(row.pop("payload_json") or "{}")
            except Exception:
                row["payload"] = {}
        return rows

    def replay_dead_letter(self, row_id: int, max_attempts: int = 3) -> bool:
        """重放死信消息"""
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        next_retry = now_str
        try:
            self.db.execute(
                """
                UPDATE push_outbox
                SET status='pending',
                    attempts=0,
                    max_attempts=?,
                    next_retry_time=?,
                    updated_time=?
                WHERE id=? AND status='dead_letter'
                """,
                (int(max(1, max_attempts)), next_retry, now_str, int(row_id)),
            )
            logger.info("Dead letter replayed: id=%s", row_id)
            return True
        except Exception as exc:
            logger.error("Replay dead letter failed: %s", exc)
            return False

    def _record_stat(
        self,
        channel: str,
        msg_type: str,
        status: str,
        latency_ms: Optional[int] = None,
        error_code: Optional[str] = None,
    ):
        """记录推送统计"""
        try:
            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self.db.execute(
                """
                INSERT INTO push_stats (channel, msg_type, status, latency_ms, error_code, created_time)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (channel, msg_type, status, latency_ms, error_code, now_str),
            )
        except Exception as exc:
            logger.debug("record push stat failed: %s", exc)

    def get_stats(self, hours: int = 24) -> Dict[str, Any]:
        """获取推送统计摘要"""
        since = (datetime.now() - timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M:%S")
        try:
            rows = self.db.query(
                """
                SELECT channel, status, COUNT(*) as cnt,
                       AVG(latency_ms) as avg_latency_ms,
                       MAX(latency_ms) as max_latency_ms
                FROM push_stats
                WHERE created_time >= ?
                GROUP BY channel, status
                ORDER BY channel, status
                """,
                (since,),
            )
            total_success = 0
            total_failed = 0
            channel_stats = {}
            for row in rows:
                ch = row["channel"]
                if ch not in channel_stats:
                    channel_stats[ch] = {"success": 0, "failed": 0, "dead_letter": 0, "avg_latency_ms": 0}
                channel_stats[ch][row["status"]] = int(row["cnt"])
                if row["status"] == "success" and row["avg_latency_ms"]:
                    channel_stats[ch]["avg_latency_ms"] = round(float(row["avg_latency_ms"]), 1)
                if row["status"] == "success":
                    total_success += int(row["cnt"])
                elif row["status"] in ("failed", "dead_letter"):
                    total_failed += int(row["cnt"])

            total = total_success + total_failed
            return {
                "window_hours": hours,
                "total_success": total_success,
                "total_failed": total_failed,
                "success_rate": round(total_success / total * 100, 2) if total > 0 else 0.0,
                "channels": channel_stats,
            }
        except Exception as exc:
            logger.error("get push stats failed: %s", exc)
            return {"window_hours": hours, "total_success": 0, "total_failed": 0, "success_rate": 0.0, "channels": {}}

    def purge_old_records(self, days: int = 30) -> Tuple[int, int]:
        """清理过期记录"""
        cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
        try:
            self.db.execute(
                "DELETE FROM push_outbox WHERE status='success' AND updated_time < ?",
                (cutoff,),
            )
            purged_outbox = self.db.query("SELECT changes() as cnt")[0]["cnt"] if self.db.query("SELECT changes() as cnt") else 0
            self.db.execute(
                "DELETE FROM push_stats WHERE created_time < ?",
                (cutoff,),
            )
            purged_stats = self.db.query("SELECT changes() as cnt")[0]["cnt"] if self.db.query("SELECT changes() as cnt") else 0
            logger.info("Purged old records: outbox=%s, stats=%s", purged_outbox, purged_stats)
            return int(purged_outbox), int(purged_stats)
        except Exception as exc:
            logger.error("purge old records failed: %s", exc)
            return 0, 0
