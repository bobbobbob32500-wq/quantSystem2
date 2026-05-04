from __future__ import annotations

import pytest


@pytest.fixture()
def mobile_api_client(monkeypatch):
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient
    from src.api import app as app_module

    payload = {
        "checked_at": "2026-04-10T10:00:00",
        "overall_status": "pass",
        "overall_status_label": "PASS",
        "summary": "Startup self-check passed.",
        "stats": {"pass_count": 3, "warn_count": 0, "fail_count": 0},
        "items": [],
    }

    class StubStartupSelfCheckService:
        def run_check(self):
            return payload

    stub_service = StubStartupSelfCheckService()
    monkeypatch.setattr(app_module, "startup_self_check_service", stub_service)
    monkeypatch.setattr(app_module.data_service, "startup_self_check_service", stub_service)
    monkeypatch.setattr(
        app_module.data_service,
        "build_terminal_home_snapshot",
        lambda: {
            "meta": {"generated_at": "2026-04-10T10:00:00"},
            "startup_self_check": payload,
        },
    )

    with TestClient(app_module.app) as client:
        yield client


def test_startup_self_check_endpoint(mobile_api_client):
    response = mobile_api_client.get("/api/system/startup_self_check")
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["data"]["overall_status"] == "pass"
    assert body["data"]["stats"]["fail_count"] == 0


def test_overview_contains_startup_self_check_section(mobile_api_client):
    response = mobile_api_client.get("/api/dashboard/overview")
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["data"]["startup_self_check"]["overall_status_label"] == "PASS"
