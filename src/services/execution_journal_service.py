# -*- coding: utf-8 -*-
"""Execution journal service for API-visible operation traces."""
from __future__ import annotations

import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from threading import Lock
from typing import Any, Dict, List, Optional

from src.core.logger import get_logger

logger = get_logger("execution_journal_service")


class ExecutionJournalService:
    """Persist and summarize execution journal entries in a JSON file."""

    def __init__(self, journal_path: str | Path, max_entries: int = 2000):
        self.journal_path = Path(journal_path)
        self.max_entries = max(100, int(max_entries or 2000))
        self._lock = Lock()
        self._seq = 0
        self._ensure_payload_file()

    def append_event(
        self,
        action: str,
        status: str,
        message: Optional[str] = None,
        symbol: Optional[str] = None,
        trade_id: Optional[str] = None,
        source: str = "mobile_api",
        channel: str = "android_app",
        details: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        with self._lock:
            payload = self._load_payload()
            now = datetime.now()
            self._seq = (self._seq + 1) % 1_000_000
            event = {
                "event_id": f"ej_{now.strftime('%Y%m%d%H%M%S%f')}_{self._seq:06d}",
                "event_time": now.isoformat(),
                "action": str(action or "").strip() or "unknown",
                "status": str(status or "").strip().lower() or "unknown",
                "message": str(message or "").strip() or None,
                "symbol": str(symbol or "").strip() or None,
                "trade_id": str(trade_id or "").strip() or None,
                "source": str(source or "").strip() or "mobile_api",
                "channel": str(channel or "").strip() or "android_app",
                "details": details if isinstance(details, dict) else {},
            }
            entries = list(payload.get("entries") or [])
            entries.insert(0, event)
            payload["entries"] = entries[: self.max_entries]
            self._persist_payload(payload)
            return event

    def get_journal(
        self,
        limit: int = 50,
        action: Optional[str] = None,
        status: Optional[str] = None,
        symbol: Optional[str] = None,
    ) -> Dict[str, Any]:
        with self._lock:
            payload = self._load_payload()
            all_entries = list(payload.get("entries") or [])

        normalized_action = str(action or "").strip().lower()
        normalized_status = str(status or "").strip().lower()
        normalized_symbol = str(symbol or "").strip().upper()

        def _match(entry: Dict[str, Any]) -> bool:
            if normalized_action and str(entry.get("action") or "").strip().lower() != normalized_action:
                return False
            if normalized_status and str(entry.get("status") or "").strip().lower() != normalized_status:
                return False
            if normalized_symbol and str(entry.get("symbol") or "").strip().upper() != normalized_symbol:
                return False
            return True

        filtered = [entry for entry in all_entries if _match(entry)]
        safe_limit = max(1, min(int(limit or 50), 500))
        summary = self._build_summary(all_entries)
        summary["filtered_count"] = len(filtered)
        return {
            "updated_at": payload.get("updated_at"),
            "entries": filtered[:safe_limit],
            "summary": summary,
        }

    def build_snapshot(self, recent_limit: int = 20) -> Dict[str, Any]:
        with self._lock:
            payload = self._load_payload()
            entries = list(payload.get("entries") or [])

        summary = self._build_summary(entries)
        safe_limit = max(1, min(int(recent_limit or 20), 200))
        return {
            "updated_at": payload.get("updated_at"),
            **summary,
            "recent_events": entries[:safe_limit],
            "recent_failed": [entry for entry in entries if entry.get("status") == "failed"][:5],
        }

    def _load_payload(self) -> Dict[str, Any]:
        if not self.journal_path.exists():
            return {"version": 1, "updated_at": None, "entries": []}
        try:
            payload = json.loads(self.journal_path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                return {"version": 1, "updated_at": None, "entries": []}
            if not isinstance(payload.get("entries"), list):
                payload["entries"] = []
            payload.setdefault("version", 1)
            payload.setdefault("updated_at", None)
            return payload
        except Exception:
            logger.exception("Failed to load execution journal payload")
            return {"version": 1, "updated_at": None, "entries": []}

    def _ensure_payload_file(self) -> None:
        if self.journal_path.exists():
            return
        try:
            self.journal_path.parent.mkdir(parents=True, exist_ok=True)
            self.journal_path.write_text(
                json.dumps({"version": 1, "updated_at": None, "entries": []}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception:
            logger.exception("Failed to initialize execution journal payload")

    def _persist_payload(self, payload: Dict[str, Any]) -> None:
        payload["updated_at"] = datetime.now().isoformat()
        self.journal_path.parent.mkdir(parents=True, exist_ok=True)
        self.journal_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    @staticmethod
    def _build_summary(entries: List[Dict[str, Any]]) -> Dict[str, Any]:
        status_counter: Counter[str] = Counter()
        action_counter: Counter[str] = Counter()
        latest_event_time: Optional[str] = None

        for entry in entries:
            status = str(entry.get("status") or "").strip().lower() or "unknown"
            action = str(entry.get("action") or "").strip() or "unknown"
            status_counter[status] += 1
            action_counter[action] += 1
            event_time = str(entry.get("event_time") or "").strip()
            if event_time and (latest_event_time is None or event_time > latest_event_time):
                latest_event_time = event_time

        return {
            "total_events": len(entries),
            "success_count": int(status_counter.get("success", 0)),
            "failed_count": int(status_counter.get("failed", 0)),
            "latest_event_time": latest_event_time,
            "status_distribution": [
                {"name": name, "value": value}
                for name, value in status_counter.most_common(6)
            ],
            "action_distribution": [
                {"name": name, "value": value}
                for name, value in action_counter.most_common(10)
            ],
        }
