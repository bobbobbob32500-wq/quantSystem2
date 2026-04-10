# -*- coding: utf-8 -*-
"""Tests for runtime monitoring persistence store."""

import sqlite3
from pathlib import Path

from src.core.runtime_monitor import AlertSeverity, IncidentCategory, SystemIncident
from src.modules.monitoring_store import MonitoringStore


class SQLiteTestDB:
    """Minimal DB adapter compatible with MonitoringStore expectations."""

    def __init__(self, db_path: Path):
        self.conn = sqlite3.connect(str(db_path))
        self.conn.row_factory = sqlite3.Row

    def execute(self, sql: str, params: tuple = None):
        cursor = self.conn.cursor()
        cursor.execute(sql, params or ())
        self.conn.commit()
        return cursor.rowcount

    def query(self, sql: str, params: tuple = None):
        cursor = self.conn.cursor()
        cursor.execute(sql, params or ())
        return [dict(row) for row in cursor.fetchall()]

    def query_one(self, sql: str, params: tuple = None):
        rows = self.query(sql, params)
        return rows[0] if rows else None


def test_monitoring_store_save_and_query(tmp_path):
    db = SQLiteTestDB(tmp_path / "monitoring_store_test.db")
    store = MonitoringStore(db=db)

    incident = SystemIncident(
        title="Data source warning",
        message="minute source timeout",
        severity=AlertSeverity.WARNING,
        category=IncidentCategory.DATA_SOURCE,
        component="monitor.minute_source",
        timestamp="2026-03-27 10:01:00",
        retryable=True,
        error_code="TIMEOUT",
        exception_type="TimeoutError",
        context={"symbol": "600519"},
    )
    store.save_incident(incident)

    snapshot = {
        "uptime_seconds": 3600.0,
        "success_counter": {"service.main_loop": 120},
        "incident_counter": {"monitor.minute_source": 1},
        "severity_counter": {"warning": 1},
        "component_status": {"service.main_loop": {"health": "healthy", "lag_seconds": 1.2}},
        "latency_summary": {"service.main_loop": {"avg_ms": 12.3, "p95_ms": 30.1}},
    }
    store.save_health_snapshot(snapshot, source="service")

    incidents = store.get_recent_incidents(limit=5)
    assert len(incidents) == 1
    assert incidents[0]["component"] == "monitor.minute_source"
    assert incidents[0]["context"]["symbol"] == "600519"

    latest = store.get_latest_snapshot(source="service")
    assert latest is not None
    assert int(latest["success_total"]) == 120
    assert int(latest["incident_total"]) == 1
    assert latest["severity_counter"]["warning"] == 1
