# -*- coding: utf-8 -*-
from __future__ import annotations

import importlib
from typing import Any, Dict

import pytest

pytest.importorskip("fastapi")


@pytest.fixture(scope="module")
def api_and_module():
    from fastapi.testclient import TestClient

    app_module = importlib.import_module("src.api.app")
    if not getattr(app_module, "_ai_available", False):
        pytest.skip("AI module is not available in current runtime")
    return TestClient(app_module.app), app_module


@pytest.mark.smoke
def test_golden_risk_check_contract(api_and_module, monkeypatch):
    client, app_module = api_and_module

    def fake_risk_check_now(*, holdings: list[Dict[str, Any]], market_data: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "risk_level": "MEDIUM",
            "alerts": [{"level": "MEDIUM", "message": "position concentration rising"}],
            "actions": ["reduce single-name exposure"],
            "meta": {"holding_count": len(holdings), "regime": market_data.get("regime", "UNKNOWN")},
        }

    monkeypatch.setattr(app_module.butler_service, "do_risk_check_now", fake_risk_check_now)

    payload = {
        "holdings": [{"code": "000001.SZ", "name": "平安银行", "position": 0.32}],
        "market_data": {"regime": "NORMAL"},
    }
    resp = client.post("/api/butler/risk-check", json=payload)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body.get("success") is True
    result = body.get("result") or {}
    assert result.get("risk_level") in {"LOW", "MEDIUM", "HIGH", "CRITICAL"}
    assert isinstance(result.get("alerts"), list)
    assert isinstance(result.get("actions"), list)
    assert isinstance(result.get("meta"), dict)


@pytest.mark.smoke
def test_golden_signal_analysis_contract(api_and_module, monkeypatch):
    client, app_module = api_and_module

    def fake_on_signal_triggered(
        signal: Dict[str, Any],
        stock_info: Dict[str, Any],
        position: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        return {
            "action": "BUY",
            "confidence": 0.83,
            "reason": f"{stock_info.get('code', '')} breakout confirmed",
            "execution_advice": "scale in with 2 tranches",
            "risk_note": "place stop-loss at -3%",
            "input_echo": {"signal_type": signal.get("type"), "has_position": bool(position)},
        }

    monkeypatch.setattr(app_module.butler_service, "on_signal_triggered", fake_on_signal_triggered)

    payload = {
        "signal": {"type": "BREAKOUT", "time": "10:30:00"},
        "stock_info": {"code": "000001.SZ", "name": "平安银行", "price": 12.51},
        "position": None,
    }
    resp = client.post("/api/butler/signal-analysis", json=payload)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body.get("success") is True
    result = body.get("result") or {}
    assert result.get("action") in {"BUY", "HOLD", "SELL"}
    confidence = float(result.get("confidence", -1))
    assert 0.0 <= confidence <= 1.0
    assert isinstance(result.get("reason"), str) and result["reason"]
    assert isinstance(result.get("execution_advice"), str) and result["execution_advice"]

