# -*- coding: utf-8 -*-
from __future__ import annotations

import pytest


def test_schedule_startup_market_data_sync_runs_once(monkeypatch):
    pytest.importorskip("fastapi")
    from src.api import app as app_module

    calls = []

    class StubRunner:
        def run_startup_market_data_sync(self):
            calls.append("run")
            return {"task_id": "startup-sync-1"}

    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.setattr(
        app_module.config,
        "get",
        lambda key, default=None: True if key == "data_source.startup_auto_update_enabled" else default,
    )
    monkeypatch.setattr(app_module.action_service, "task_runner", StubRunner())
    monkeypatch.setattr(app_module, "startup_market_sync_scheduled", False)

    first = app_module._schedule_startup_market_data_sync()
    second = app_module._schedule_startup_market_data_sync()

    assert first == {"task_id": "startup-sync-1"}
    assert second is None
    assert calls == ["run"]
