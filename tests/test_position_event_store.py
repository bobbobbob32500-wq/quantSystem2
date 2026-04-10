# -*- coding: utf-8 -*-
"""Unit tests for position event dedupe/retry store."""

from __future__ import annotations

import sqlite3

from src.modules.position_event_store import PositionEventStore


class _DBStub:
    def __init__(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row

    def execute(self, sql: str, params: tuple = None) -> int:
        cur = self.conn.cursor()
        cur.execute(sql, params or ())
        self.conn.commit()
        return cur.rowcount

    def query(self, sql: str, params: tuple = None):
        cur = self.conn.cursor()
        cur.execute(sql, params or ())
        return [dict(row) for row in cur.fetchall()]

    def query_one(self, sql: str, params: tuple = None):
        rows = self.query(sql, params)
        return rows[0] if rows else None


def test_enqueue_dedupe_and_retry_flow():
    db = _DBStub()
    store = PositionEventStore(db=db)  # type: ignore[arg-type]
    event = {
        "event_id": "evt-abc",
        "event_type": "position_risk_signal",
        "ts_code": "600000.SH",
        "name": "浦发银行",
        "severity": "high",
        "signal_type": "价格止损",
        "reason": "跌破止损",
        "suggestion": "减仓",
    }

    assert store.enqueue_event(event, max_retry=3) is True
    assert store.enqueue_event(event, max_retry=3) is False  # dedupe

    retryable = store.list_retryable_events(limit=10)
    assert len(retryable) == 1
    assert retryable[0]["event_id"] == "evt-abc"

    store.mark_failed("evt-abc", error="push failed", retry_delay_seconds=0)
    retryable_after_fail = store.list_retryable_events(limit=10)
    assert len(retryable_after_fail) == 1
    assert int(retryable_after_fail[0]["_retry_count"]) == 1

    store.mark_success("evt-abc")
    assert store.list_retryable_events(limit=10) == []

    status = store.get_status("evt-abc")
    assert status is not None
    assert status["status"] == "success"
