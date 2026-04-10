# -*- coding: utf-8 -*-
"""Persistence store for runtime incidents and health snapshots."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict, List, Optional

from src.core.config import ConfigManager
from src.core.database import DatabaseManager
from src.core.logger import get_logger

logger = get_logger("monitoring_store")


class MonitoringStore:
    """Database-backed storage for runtime monitoring data."""

    def __init__(self, db: Optional[DatabaseManager] = None):
        self.db = db or DatabaseManager(ConfigManager())
        self._ensure_tables()

    def _ensure_tables(self):
        self.db.execute(
            """
            CREATE TABLE IF NOT EXISTS runtime_incident (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                incident_time TEXT NOT NULL,
                title TEXT NOT NULL,
                message TEXT,
                severity TEXT NOT NULL,
                category TEXT,
                component TEXT,
                retryable INTEGER DEFAULT 0,
                error_code TEXT,
                exception_type TEXT,
                context_json TEXT,
                created_time TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        self.db.execute(
            """
            CREATE TABLE IF NOT EXISTS health_snapshot (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                snapshot_time TEXT NOT NULL,
                source TEXT NOT NULL,
                uptime_seconds REAL,
                success_total INTEGER DEFAULT 0,
                incident_total INTEGER DEFAULT 0,
                severity_json TEXT,
                component_status_json TEXT,
                latency_summary_json TEXT,
                snapshot_json TEXT,
                created_time TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        self.db.execute(
            "CREATE INDEX IF NOT EXISTS idx_runtime_incident_time ON runtime_incident(incident_time)"
        )
        self.db.execute(
            "CREATE INDEX IF NOT EXISTS idx_runtime_incident_component ON runtime_incident(component)"
        )
        self.db.execute(
            "CREATE INDEX IF NOT EXISTS idx_health_snapshot_time ON health_snapshot(snapshot_time)"
        )
        self.db.execute(
            "CREATE INDEX IF NOT EXISTS idx_health_snapshot_source ON health_snapshot(source)"
        )

    def save_incident(self, incident: Any):
        """Persist one incident record."""
        if hasattr(incident, "to_dict"):
            incident = incident.to_dict()

        self.db.execute(
            """
            INSERT INTO runtime_incident (
                incident_time, title, message, severity, category, component,
                retryable, error_code, exception_type, context_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                incident.get("timestamp", datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
                incident.get("title", "runtime incident"),
                incident.get("message", ""),
                incident.get("severity", "warning"),
                incident.get("category", "system"),
                incident.get("component", "unknown"),
                1 if incident.get("retryable") else 0,
                incident.get("error_code"),
                incident.get("exception_type"),
                json.dumps(incident.get("context") or {}, ensure_ascii=False),
            ),
        )

    def save_health_snapshot(self, snapshot: Dict[str, Any], source: str = "service"):
        """Persist one health snapshot."""
        success_total = sum((snapshot.get("success_counter") or {}).values())
        incident_total = sum((snapshot.get("incident_counter") or {}).values())

        self.db.execute(
            """
            INSERT INTO health_snapshot (
                snapshot_time, source, uptime_seconds, success_total, incident_total,
                severity_json, component_status_json, latency_summary_json, snapshot_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                source,
                snapshot.get("uptime_seconds", 0),
                success_total,
                incident_total,
                json.dumps(snapshot.get("severity_counter", {}), ensure_ascii=False),
                json.dumps(snapshot.get("component_status", {}), ensure_ascii=False),
                json.dumps(snapshot.get("latency_summary", {}), ensure_ascii=False),
                json.dumps(snapshot, ensure_ascii=False),
            ),
        )

    def get_recent_incidents(
        self,
        limit: int = 50,
        severity: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Read latest incidents, optionally filtered by severity."""
        sql = """
            SELECT incident_time, title, message, severity, category, component,
                   retryable, error_code, exception_type, context_json
            FROM runtime_incident
        """
        params: List[Any] = []
        if severity:
            sql += " WHERE severity = ?"
            params.append(severity)
        sql += " ORDER BY incident_time DESC LIMIT ?"
        params.append(limit)

        rows = self.db.query(sql, tuple(params))
        for row in rows:
            row["context"] = self._safe_json_loads(row.pop("context_json", None))
        return rows

    def get_latest_snapshot(self, source: str = "service") -> Optional[Dict[str, Any]]:
        """Read latest snapshot by source."""
        row = self.db.query_one(
            """
            SELECT snapshot_time, source, uptime_seconds, success_total, incident_total,
                   severity_json, component_status_json, latency_summary_json, snapshot_json
            FROM health_snapshot
            WHERE source = ?
            ORDER BY snapshot_time DESC
            LIMIT 1
            """,
            (source,),
        )
        if not row:
            return None

        row["severity_counter"] = self._safe_json_loads(row.pop("severity_json", None))
        row["component_status"] = self._safe_json_loads(row.pop("component_status_json", None))
        row["latency_summary"] = self._safe_json_loads(row.pop("latency_summary_json", None))
        row["snapshot"] = self._safe_json_loads(row.pop("snapshot_json", None))
        return row

    def get_recent_snapshots(self, source: str = "service", limit: int = 100) -> List[Dict[str, Any]]:
        """Read recent snapshots by source."""
        rows = self.db.query(
            """
            SELECT snapshot_time, source, uptime_seconds, success_total, incident_total,
                   severity_json, component_status_json, latency_summary_json
            FROM health_snapshot
            WHERE source = ?
            ORDER BY snapshot_time DESC
            LIMIT ?
            """,
            (source, limit),
        )
        for row in rows:
            row["severity_counter"] = self._safe_json_loads(row.pop("severity_json", None))
            row["component_status"] = self._safe_json_loads(row.pop("component_status_json", None))
            row["latency_summary"] = self._safe_json_loads(row.pop("latency_summary_json", None))
        return rows

    @staticmethod
    def _safe_json_loads(payload: Optional[str]) -> Dict[str, Any]:
        if not payload:
            return {}
        try:
            return json.loads(payload)
        except Exception:
            logger.warning("Failed to parse monitoring JSON payload")
            return {}
