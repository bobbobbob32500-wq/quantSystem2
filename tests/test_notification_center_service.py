from __future__ import annotations

from pathlib import Path

from src.core.database import DatabaseManager
from src.modules.push_outbox_store import PushOutboxStore
from src.services.notification_center_service import NotificationCenterService


class _StubConfig:
    def get(self, key: str, default=None):
        return default


def _build_service(tmp_path: Path) -> tuple[NotificationCenterService, DatabaseManager, PushOutboxStore]:
    db_path = tmp_path / "notification_center_test.db"
    db = DatabaseManager(config=_StubConfig(), db_path=str(db_path))
    outbox = PushOutboxStore(db)
    service = NotificationCenterService(
        db=db,
        config=_StubConfig(),
        ack_state_path=tmp_path / "notification_center_ack.json",
        max_scan_items=500,
    )
    return service, db, outbox


def test_notification_center_list_and_summary(tmp_path: Path) -> None:
    service, db, outbox = _build_service(tmp_path)

    outbox.enqueue(channel="wechat", msg_type="markdown", payload={"content": "pending msg"})
    outbox.enqueue(channel="wechat", msg_type="markdown", payload={"content": "failed msg"})
    outbox.enqueue(channel="wechat", msg_type="markdown", payload={"content": "success msg"})

    rows = db.query("SELECT id FROM push_outbox ORDER BY id ASC")
    pending_id, failed_id, success_id = [int(row["id"]) for row in rows]

    outbox.mark_failed(failed_id, error="network timeout")
    outbox.mark_success(success_id)

    payload = service.list_notifications(limit=10)
    assert payload["total"] == 3
    assert len(payload["items"]) == 3

    by_id = {item["notification_id"]: item for item in payload["items"]}
    assert by_id[f"outbox:{pending_id}"]["status"] == "pending"
    assert by_id[f"outbox:{failed_id}"]["status"] == "failed"
    assert by_id[f"outbox:{success_id}"]["status"] == "success"

    summary = service.build_summary(recent_limit=5)
    assert summary["total"] == 3
    assert summary["retryable_count"] >= 1
    assert isinstance(summary["recent_items"], list)


def test_notification_center_ack_and_ack_all(tmp_path: Path) -> None:
    service, db, outbox = _build_service(tmp_path)

    outbox.enqueue(channel="wechat", msg_type="markdown", payload={"content": "first"})
    outbox.enqueue(channel="wechat", msg_type="markdown", payload={"content": "second"})

    rows = db.query("SELECT id FROM push_outbox ORDER BY id ASC")
    first_id, second_id = [int(row["id"]) for row in rows]

    outbox.mark_failed(second_id, error="first fail")

    acked = service.ack_notification(f"outbox:{first_id}")
    assert acked["notification_id"] == f"outbox:{first_id}"
    assert acked["acked"] is True

    payload = service.list_notifications(limit=10)
    by_id = {item["notification_id"]: item for item in payload["items"]}
    assert by_id[f"outbox:{first_id}"]["acked"] is True
    assert by_id[f"outbox:{second_id}"]["acked"] is False

    ack_all = service.ack_all(status="failed")
    assert ack_all["acked_count"] == 1

    unread_only = service.list_notifications(limit=10, unread_only=True)
    assert unread_only["total"] == 0
