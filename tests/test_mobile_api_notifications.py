from __future__ import annotations

from pathlib import Path

import pytest

from src.core.database import DatabaseManager
from src.modules.push_outbox_store import PushOutboxStore
from src.services.notification_center_service import NotificationCenterService


class _StubConfig:
    def get(self, key: str, default=None):
        return default


@pytest.fixture()
def mobile_api_client_with_notifications(tmp_path: Path, monkeypatch):
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient
    from src.api import app as app_module

    db_path = tmp_path / "api_notification_test.db"
    db = DatabaseManager(config=_StubConfig(), db_path=str(db_path))
    notification_service = NotificationCenterService(
        db=db,
        config=_StubConfig(),
        ack_state_path=tmp_path / "notification_center_ack.json",
        max_scan_items=500,
    )

    monkeypatch.setattr(app_module, "notification_center_service", notification_service)

    with TestClient(app_module.app) as client:
        yield client, db


def test_notification_list_and_summary_endpoints(mobile_api_client_with_notifications):
    client, db = mobile_api_client_with_notifications
    outbox = PushOutboxStore(db)

    outbox.enqueue(channel="wechat", msg_type="markdown", payload={"content": "pending msg"})
    outbox.enqueue(channel="wechat", msg_type="markdown", payload={"content": "failed msg"})
    rows = db.query("SELECT id FROM push_outbox ORDER BY id ASC")
    outbox.mark_failed(int(rows[-1]["id"]), error="network fail")

    list_resp = client.get("/api/notifications?limit=20")
    assert list_resp.status_code == 200
    body = list_resp.json()
    assert body["success"] is True
    assert body["data"]["total"] == 2
    assert len(body["data"]["items"]) == 2

    summary_resp = client.get("/api/notifications/summary?limit=5")
    assert summary_resp.status_code == 200
    summary_body = summary_resp.json()
    assert summary_body["success"] is True
    assert summary_body["data"]["total"] == 2
    assert summary_body["data"]["retryable_count"] >= 1


def test_notification_ack_endpoints(mobile_api_client_with_notifications):
    client, db = mobile_api_client_with_notifications
    outbox = PushOutboxStore(db)

    outbox.enqueue(channel="wechat", msg_type="markdown", payload={"content": "first"})
    outbox.enqueue(channel="wechat", msg_type="markdown", payload={"content": "second"})
    rows = db.query("SELECT id FROM push_outbox ORDER BY id ASC")
    first_id = int(rows[0]["id"])

    ack_resp = client.post(f"/api/notifications/outbox:{first_id}/ack")
    assert ack_resp.status_code == 200
    ack_body = ack_resp.json()
    assert ack_body["success"] is True
    assert ack_body["data"]["acked"] is True

    unread_resp = client.get("/api/notifications?unread_only=true")
    assert unread_resp.status_code == 200
    unread_body = unread_resp.json()
    assert unread_body["success"] is True
    assert unread_body["data"]["total"] == 1

    ack_all_resp = client.post("/api/notifications/ack_all", json={})
    assert ack_all_resp.status_code == 200
    ack_all_body = ack_all_resp.json()
    assert ack_all_body["success"] is True
    assert ack_all_body["data"]["acked_count"] == 2

    unread_after = client.get("/api/notifications?unread_only=true")
    assert unread_after.status_code == 200
    assert unread_after.json()["data"]["total"] == 0
