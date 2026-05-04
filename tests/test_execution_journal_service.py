from __future__ import annotations

from src.services.execution_journal_service import ExecutionJournalService


def test_execution_journal_append_and_trim(tmp_path):
    journal_path = tmp_path / "execution_journal.json"
    service = ExecutionJournalService(journal_path=journal_path, max_entries=100)

    for idx in range(0, 130):
        service.append_event(
            action="virtual_trade_create",
            status="success",
            symbol=f"{idx:06d}",
            trade_id=f"trade_{idx}",
        )

    payload = service.get_journal(limit=200)
    assert len(payload["entries"]) == 100
    assert payload["summary"]["total_events"] == 100
    assert payload["entries"][0]["trade_id"] == "trade_129"
    assert payload["entries"][-1]["trade_id"] == "trade_30"


def test_execution_journal_snapshot_summary(tmp_path):
    journal_path = tmp_path / "execution_journal.json"
    service = ExecutionJournalService(journal_path=journal_path, max_entries=200)
    service.append_event(action="virtual_trade_create", status="success", symbol="600519")
    service.append_event(action="virtual_trade_update", status="failed", symbol="600519", message="not found")
    service.append_event(action="virtual_trade_delete", status="success", symbol="600519")

    snapshot = service.build_snapshot(recent_limit=10)
    assert snapshot["total_events"] == 3
    assert snapshot["success_count"] == 2
    assert snapshot["failed_count"] == 1
    assert snapshot["latest_event_time"] is not None
    assert len(snapshot["recent_events"]) == 3
    assert snapshot["recent_failed"][0]["action"] == "virtual_trade_update"
