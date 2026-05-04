from __future__ import annotations

import pytest

from src.services.execution_journal_service import ExecutionJournalService


@pytest.fixture()
def mobile_api_client(tmp_path, monkeypatch):
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
    monkeypatch.setattr(app_module.data_service, "execution_journal_service", service)

    with TestClient(app_module.app) as client:
        yield client


def test_create_virtual_trade_records_execution_journal(mobile_api_client):
    response = mobile_api_client.post(
        "/api/virtual_trades",
        json={
            "symbol": "600519",
            "name": "KweichowMoutai",
            "buy_price": 1500.0,
            "quantity": 100,
        },
    )
    assert response.status_code == 200
    trade_id = response.json()["data"]["trade_id"]

    journal_response = mobile_api_client.get("/api/execution_journal?limit=10")
    assert journal_response.status_code == 200
    payload = journal_response.json()["data"]
    assert payload["summary"]["total_events"] == 1
    assert payload["entries"][0]["action"] == "virtual_trade_create"
    assert payload["entries"][0]["status"] == "success"
    assert payload["entries"][0]["trade_id"] == trade_id


def test_update_missing_trade_records_failed_journal(mobile_api_client):
    response = mobile_api_client.put(
        "/api/virtual_trades/missing_trade_id",
        json={
            "symbol": "600519",
            "name": "KweichowMoutai",
            "buy_price": 1500.0,
            "quantity": 100,
        },
    )
    assert response.status_code == 404

    journal_response = mobile_api_client.get("/api/execution_journal?limit=10")
    assert journal_response.status_code == 200
    payload = journal_response.json()["data"]
    assert payload["summary"]["failed_count"] == 1
    assert payload["entries"][0]["action"] == "virtual_trade_update"
    assert payload["entries"][0]["status"] == "failed"


def test_execution_journal_summary_endpoint(mobile_api_client):
    mobile_api_client.post(
        "/api/virtual_trades",
        json={
            "symbol": "000001",
            "name": "PingAnBank",
            "buy_price": 10.2,
            "quantity": 500,
        },
    )
    summary_response = mobile_api_client.get("/api/execution_journal/summary?limit=5")
    assert summary_response.status_code == 200
    payload = summary_response.json()["data"]
    assert payload["total_events"] >= 1
    assert payload["success_count"] >= 1
    assert isinstance(payload["recent_events"], list)
