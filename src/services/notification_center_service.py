# -*- coding: utf-8 -*-
"""Notification center service backed by push_outbox for mobile app consumption."""
from __future__ import annotations

import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from threading import Lock
from typing import Any, Dict, List, Optional

from src.core.config import ConfigManager
from src.core.database import DatabaseManager
from src.core.logger import get_logger
from src.modules.push_outbox_store import PushOutboxStore

logger = get_logger("notification_center_service")


class NotificationCenterService:
    """Aggregate push outbox messages and maintain read/ack state."""

    SUPPORTED_STATUSES = {"pending", "failed", "success", "dead_letter"}

    def __init__(
        self,
        db: Optional[DatabaseManager] = None,
        config: Optional[ConfigManager] = None,
        ack_state_path: str | Path | None = None,
        max_scan_items: int = 5000,
    ):
        self.config = config or ConfigManager()
        self.db = db or DatabaseManager(self.config)
        # Ensure push_outbox table exists before reads.
        self.outbox_store = PushOutboxStore(self.db)
        self.max_scan_items = max(200, int(max_scan_items or 5000))

        default_path = Path(__file__).resolve().parents[2] / "data" / "cache" / "notification_center_ack.json"
        self.ack_state_path = Path(ack_state_path or default_path)
        self._lock = Lock()

    def list_notifications(
        self,
        limit: int = 50,
        status: Optional[str] = None,
        unread_only: bool = False,
    ) -> Dict[str, Any]:
        safe_limit = max(1, min(int(limit or 50), 200))
        rows = self._fetch_rows(limit=self.max_scan_items, status=status)

        with self._lock:
            ack_map = self._load_ack_map()

        items = [self._build_item(row=row, ack_map=ack_map) for row in rows]
        if unread_only:
            items = [item for item in items if not bool(item.get("acked"))]

        status_counter: Counter[str] = Counter(str(item.get("status") or "unknown") for item in items)
        unread_count = sum(1 for item in items if not bool(item.get("acked")))

        return {
            "updated_at": datetime.now().isoformat(),
            "total": len(items),
            "unread_count": unread_count,
            "items": items[:safe_limit],
            "status_distribution": [
                {"name": key, "value": value}
                for key, value in status_counter.most_common(8)
            ],
        }

    def build_summary(self, recent_limit: int = 20) -> Dict[str, Any]:
        safe_recent_limit = max(1, min(int(recent_limit or 20), 100))
        rows = self._fetch_rows(limit=self.max_scan_items, status=None)

        with self._lock:
            ack_map = self._load_ack_map()

        items = [self._build_item(row=row, ack_map=ack_map) for row in rows]
        unread_count = sum(1 for item in items if not bool(item.get("acked")))

        by_status: Counter[str] = Counter()
        by_severity: Counter[str] = Counter()
        retryable_count = 0
        dead_letter_count = 0
        latest_notification_time: Optional[str] = None

        for row, item in zip(rows, items):
            status = str(item.get("status") or "unknown")
            severity = str(item.get("severity") or "info")
            by_status[status] += 1
            by_severity[severity] += 1

            attempts = int(row.get("attempts") or 0)
            max_attempts = int(row.get("max_attempts") or 0)
            if status in {"pending", "failed"} and attempts < max_attempts:
                retryable_count += 1
            if status == "dead_letter":
                dead_letter_count += 1

            updated_time = str(item.get("updated_time") or "").strip()
            created_time = str(item.get("created_time") or "").strip()
            candidate_time = updated_time or created_time
            if candidate_time and (latest_notification_time is None or candidate_time > latest_notification_time):
                latest_notification_time = candidate_time

        return {
            "updated_at": datetime.now().isoformat(),
            "total": len(items),
            "unread_count": unread_count,
            "retryable_count": retryable_count,
            "dead_letter_count": dead_letter_count,
            "latest_notification_time": latest_notification_time,
            "by_status": [{"name": key, "value": value} for key, value in by_status.most_common(8)],
            "by_severity": [{"name": key, "value": value} for key, value in by_severity.most_common(8)],
            "recent_items": items[:safe_recent_limit],
        }

    def ack_notification(self, notification_id: str) -> Dict[str, Any]:
        normalized = str(notification_id or "").strip()
        if not normalized:
            raise ValueError("notification_id is required")

        if not self._notification_exists(normalized):
            raise KeyError(f"notification not found: {normalized}")

        now = datetime.now().isoformat()
        with self._lock:
            payload = self._load_ack_payload()
            ack_map = payload.get("acks") if isinstance(payload.get("acks"), dict) else {}
            ack_map[normalized] = now
            payload["acks"] = ack_map
            self._persist_ack_payload(payload)

        return {
            "notification_id": normalized,
            "acked": True,
            "acked_at": now,
        }

    def ack_all(self, status: Optional[str] = None) -> Dict[str, Any]:
        rows = self._fetch_rows(limit=self.max_scan_items, status=status)
        ids = [self._notification_id_for_row(row) for row in rows]
        now = datetime.now().isoformat()

        with self._lock:
            payload = self._load_ack_payload()
            ack_map = payload.get("acks") if isinstance(payload.get("acks"), dict) else {}
            for notification_id in ids:
                ack_map[notification_id] = now
            payload["acks"] = ack_map
            self._persist_ack_payload(payload)

        return {
            "acked_count": len(ids),
            "acked_at": now,
            "status_filter": self._normalize_status(status),
        }

    def _fetch_rows(self, limit: int, status: Optional[str]) -> List[Dict[str, Any]]:
        safe_limit = max(1, int(limit or self.max_scan_items))
        normalized_status = self._normalize_status(status)
        sql = """
            SELECT
                id,
                channel,
                msg_type,
                status,
                attempts,
                max_attempts,
                next_retry_time,
                last_error,
                created_time,
                updated_time,
                payload_json
            FROM push_outbox
        """
        params: List[Any] = []
        if normalized_status:
            sql += " WHERE status = ?"
            params.append(normalized_status)
        sql += " ORDER BY updated_time DESC, id DESC LIMIT ?"
        params.append(safe_limit)

        try:
            return self.db.query(sql, tuple(params))
        except Exception:
            logger.exception("Failed to fetch notification rows")
            return []

    def _notification_exists(self, notification_id: str) -> bool:
        raw_id = notification_id.split(":", 1)[1] if ":" in notification_id else ""
        if not raw_id.isdigit():
            return False
        row = self.db.query_one("SELECT id FROM push_outbox WHERE id = ?", (int(raw_id),))
        return row is not None

    def _build_item(self, row: Dict[str, Any], ack_map: Dict[str, str]) -> Dict[str, Any]:
        notification_id = self._notification_id_for_row(row)
        payload = self._safe_json_loads(row.get("payload_json"))
        status = str(row.get("status") or "unknown").strip().lower()
        content = str(payload.get("content") or payload.get("message") or "").strip()
        last_error = str(row.get("last_error") or "").strip() or None

        if not content and last_error:
            content = f"Push failed: {last_error}"

        if len(content) > 220:
            content = f"{content[:217]}..."

        severity = self._severity_of(status)
        title = self._title_of(status=status, channel=row.get("channel"), msg_type=row.get("msg_type"))
        acked_at = ack_map.get(notification_id)

        return {
            "notification_id": notification_id,
            "source": "push_outbox",
            "status": status,
            "severity": severity,
            "title": title,
            "message": content or "(empty message payload)",
            "channel": str(row.get("channel") or ""),
            "msg_type": str(row.get("msg_type") or ""),
            "attempts": int(row.get("attempts") or 0),
            "max_attempts": int(row.get("max_attempts") or 0),
            "next_retry_time": row.get("next_retry_time"),
            "last_error": last_error,
            "created_time": row.get("created_time"),
            "updated_time": row.get("updated_time"),
            "acked": bool(acked_at),
            "acked_at": acked_at,
        }

    @staticmethod
    def _title_of(status: str, channel: Any, msg_type: Any) -> str:
        channel_label = str(channel or "unknown")
        type_label = str(msg_type or "unknown")
        status_label = {
            "pending": "Pending",
            "failed": "Failed",
            "success": "Delivered",
            "dead_letter": "Dead Letter",
        }.get(status, status or "Unknown")
        return f"{status_label} [{channel_label}/{type_label}]"

    @staticmethod
    def _severity_of(status: str) -> str:
        if status == "dead_letter":
            return "critical"
        if status == "failed":
            return "warning"
        if status == "pending":
            return "info"
        if status == "success":
            return "success"
        return "info"

    @staticmethod
    def _notification_id_for_row(row: Dict[str, Any]) -> str:
        return f"outbox:{int(row.get('id') or 0)}"

    def _normalize_status(self, status: Optional[str]) -> Optional[str]:
        value = str(status or "").strip().lower()
        if not value or value == "all":
            return None
        if value not in self.SUPPORTED_STATUSES:
            raise ValueError(f"unsupported status filter: {status}")
        return value

    def _load_ack_payload(self) -> Dict[str, Any]:
        if not self.ack_state_path.exists():
            return {"version": 1, "updated_at": None, "acks": {}}
        try:
            payload = json.loads(self.ack_state_path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                return {"version": 1, "updated_at": None, "acks": {}}
            payload.setdefault("version", 1)
            payload.setdefault("updated_at", None)
            if not isinstance(payload.get("acks"), dict):
                payload["acks"] = {}
            return payload
        except Exception:
            logger.exception("Failed to load notification ack payload")
            return {"version": 1, "updated_at": None, "acks": {}}

    def _load_ack_map(self) -> Dict[str, str]:
        payload = self._load_ack_payload()
        return payload.get("acks") if isinstance(payload.get("acks"), dict) else {}

    def _persist_ack_payload(self, payload: Dict[str, Any]) -> None:
        payload["updated_at"] = datetime.now().isoformat()
        self.ack_state_path.parent.mkdir(parents=True, exist_ok=True)
        self.ack_state_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    @staticmethod
    def _safe_json_loads(raw: Any) -> Dict[str, Any]:
        if isinstance(raw, dict):
            return raw
        if not raw:
            return {}
        try:
            payload = json.loads(str(raw))
            return payload if isinstance(payload, dict) else {}
        except Exception:
            return {}
