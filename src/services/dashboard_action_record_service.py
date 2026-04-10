from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict, List, Optional

from src.core.config import ConfigManager
from src.core.database import DatabaseManager
from src.core.logger import get_logger

logger = get_logger("dashboard_action_record_service")


class DashboardActionRecordService:
    """看板动作执行记录中心。"""

    def __init__(
        self,
        config: Optional[ConfigManager] = None,
        db: Optional[DatabaseManager] = None,
    ):
        self.config = config or ConfigManager()
        self.db = db or DatabaseManager(self.config)
        self._ensure_table()

    def _ensure_table(self) -> None:
        self.db.execute(
            """
            CREATE TABLE IF NOT EXISTS dashboard_action_record (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                action_key TEXT NOT NULL,
                status TEXT NOT NULL,
                message TEXT,
                payload_json TEXT,
                created_time TEXT NOT NULL
            )
            """
        )
        self.db.execute(
            "CREATE INDEX IF NOT EXISTS idx_dashboard_action_record_time ON dashboard_action_record(created_time)"
        )

    def record(self, action_key: str, status: str, message: str, payload: Optional[Dict[str, Any]] = None) -> None:
        self.db.execute(
            """
            INSERT INTO dashboard_action_record (action_key, status, message, payload_json, created_time)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                str(action_key or ""),
                str(status or "unknown"),
                str(message or ""),
                json.dumps(payload or {}, ensure_ascii=False),
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            ),
        )

    def get_recent(self, limit: int = 10) -> List[Dict[str, Any]]:
        rows = self.db.query(
            """
            SELECT action_key, status, message, payload_json, created_time
            FROM dashboard_action_record
            ORDER BY created_time DESC, id DESC
            LIMIT ?
            """,
            (int(limit),),
        )
        for row in rows:
            row["payload"] = self._safe_json_loads(row.pop("payload_json", None))
        return rows

    def get_latest_by_action(self, action_key: str) -> Optional[Dict[str, Any]]:
        row = self.db.query_one(
            """
            SELECT action_key, status, message, payload_json, created_time
            FROM dashboard_action_record
            WHERE action_key = ?
            ORDER BY created_time DESC, id DESC
            LIMIT 1
            """,
            (str(action_key or ""),),
        )
        if not row:
            return None
        row["payload"] = self._safe_json_loads(row.pop("payload_json", None))
        return row

    @staticmethod
    def _safe_json_loads(payload: Optional[str]) -> Dict[str, Any]:
        if not payload:
            return {}
        try:
            return json.loads(payload)
        except Exception:
            logger.warning("动作记录 payload 解析失败")
            return {}
