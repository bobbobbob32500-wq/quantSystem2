from __future__ import annotations

from pathlib import Path

import pytest

from src.services.execution_journal_service import ExecutionJournalService


@pytest.fixture()
def mobile_api_trade_client(tmp_path: Path, monkeypatch):
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient
    from src.api import app as app_module

    virtual_trades_path = tmp_path / "virtual_trades.json"
    execution_journal_path = tmp_path / "execution_journal.json"
    service = ExecutionJournalService(execution_journal_path, max_entries=200)

    monkeypatch.setattr(app_module, "virtual_trades_path", virtual_trades_path)
    monkeypatch.setattr(app_module, "execution_journal_path", execution_journal_path)
    monkeypatch.setattr(app_module, "execution_journal_service", service)
    monkeypatch.setattr(app_module.data_service, "virtual_trades_path", virtual_trades_path)
    monkeypatch.setattr(app_module.data_service, "execution_journal_service", service)

    with TestClient(app_module.app) as client:
        yield client


def test_close_virtual_trade_updates_snapshot_and_journal(mobile_api_trade_client):
    client = mobile_api_trade_client

    create_resp = client.post(
        "/api/virtual_trades",
        json={
            "symbol": "600519",
            "name": "KweichowMoutai",
            "buy_price": 1500.0,
            "quantity": 100,
        },
    )
    assert create_resp.status_code == 200
    trade_id = create_resp.json()["data"]["trade_id"]

    close_resp = client.post(
        f"/api/virtual_trades/{trade_id}/close",
        json={
            "sell_price": 1560.0,
            "quantity": 100,
            "reason": "manual_close",
            "note": "close from mobile app",
        },
    )
    assert close_resp.status_code == 200
    close_data = close_resp.json()["data"]
    assert close_data["trade_id"] == trade_id
    assert close_data["sell_reason"] == "manual_close"

    trades_resp = client.get("/api/virtual_trades")
    assert trades_resp.status_code == 200
    trades_data = trades_resp.json()["data"]
    assert trades_data["open_count"] == 0
    assert trades_data["closed_count"] == 1
    assert len(trades_data["recent_closed"]) == 1
    assert trades_data["recent_closed"][0]["trade_id"] == trade_id
    assert trades_data["stats"]["total_closed"] == 1
    assert trades_data["stats"]["win_rate_pct"] > 0

    journal_resp = client.get("/api/execution_journal?limit=10&action=virtual_trade_close")
    assert journal_resp.status_code == 200
    journal_data = journal_resp.json()["data"]
    assert journal_data["summary"]["filtered_count"] == 1
    assert journal_data["entries"][0]["trade_id"] == trade_id
    assert journal_data["entries"][0]["status"] == "success"


def test_close_virtual_trade_not_found_records_failed_journal(mobile_api_trade_client):
    client = mobile_api_trade_client

    response = client.post(
        "/api/virtual_trades/not_exist/close",
        json={"sell_price": 12.3, "quantity": 10},
    )
    assert response.status_code == 404

    journal_resp = client.get("/api/execution_journal?limit=10&action=virtual_trade_close")
    assert journal_resp.status_code == 200
    journal_data = journal_resp.json()["data"]
    assert journal_data["summary"]["filtered_count"] == 1
    assert journal_data["entries"][0]["status"] == "failed"


def test_close_virtual_trade_validation_error_records_failed_journal(mobile_api_trade_client):
    client = mobile_api_trade_client

    create_resp = client.post(
        "/api/virtual_trades",
        json={
            "symbol": "000001",
            "name": "PingAnBank",
            "buy_price": 10.5,
            "quantity": 500,
        },
    )
    assert create_resp.status_code == 200
    trade_id = create_resp.json()["data"]["trade_id"]

    response = client.post(
        f"/api/virtual_trades/{trade_id}/close",
        json={"sell_price": 0, "quantity": 500},
    )
    assert response.status_code == 400
    assert "sell_price" in response.json()["detail"]

    journal_resp = client.get("/api/execution_journal?limit=10&action=virtual_trade_close")
    assert journal_resp.status_code == 200
    journal_data = journal_resp.json()["data"]
    assert journal_data["summary"]["filtered_count"] == 1
    assert journal_data["entries"][0]["status"] == "failed"
