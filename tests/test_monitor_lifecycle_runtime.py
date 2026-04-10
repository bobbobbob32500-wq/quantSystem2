# -*- coding: utf-8 -*-
"""Regression tests for monitor lifecycle helpers."""

from __future__ import annotations

from datetime import datetime

from src.modules import enhanced_monitor_lifecycle as lifecycle
from src.modules.enhanced_hybrid_system import EnhancedHybridSystem


def _build_system_stub() -> EnhancedHybridSystem:
    system = EnhancedHybridSystem.__new__(EnhancedHybridSystem)
    system.candidate_pool = []
    system.is_monitoring = False
    system.monitor_thread = None
    system.optimization_auto_start = False
    system.enable_enhanced_optimization = False
    system.enhanced_optimizer = None
    system.optimization_bootstrap_enabled = False
    system.enable_auto_optimization = False
    system.auto_optimizer = None
    system._monitor_loop = lambda interval_seconds: None
    return system


def test_is_trade_time_matches_a_share_sessions():
    system = _build_system_stub()

    assert system._is_trade_time(datetime(2026, 3, 30, 9, 45, 0)) is True
    assert system._is_trade_time(datetime(2026, 3, 30, 11, 45, 0)) is False
    assert system._is_trade_time(datetime(2026, 3, 29, 10, 0, 0)) is False


def test_start_stop_monitoring_aliases_delegate():
    system = _build_system_stub()

    system.start_realtime_monitor = lambda interval_seconds=10: ("start", interval_seconds)
    system.stop_realtime_monitor = lambda: "stop"

    assert EnhancedHybridSystem.start_monitoring(system, interval_seconds=7) == ("start", 7)
    assert EnhancedHybridSystem.stop_monitoring(system) == "stop"


def test_start_realtime_monitor_short_circuits_on_empty_pool(capsys):
    system = _build_system_stub()

    lifecycle.start_realtime_monitor(system, interval_seconds=5)

    captured = capsys.readouterr()
    assert "候选池为空" in captured.out
    assert system.is_monitoring is False
    assert system.monitor_thread is None


def test_start_realtime_monitor_bootstraps_and_spawns(monkeypatch):
    system = _build_system_stub()
    system.candidate_pool = [{"symbol": "600001", "pool_type": "core"}]

    events = []

    monkeypatch.setattr(lifecycle, "_bootstrap_optimizers", lambda current: events.append(("bootstrap", current)))
    monkeypatch.setattr(lifecycle, "_print_start_banner", lambda current, interval: events.append(("banner", interval)))

    def _fake_spawn(current, interval):
        events.append(("spawn", interval))
        current.monitor_thread = object()

    def _fake_wait(current):
        events.append(("wait", current.is_monitoring))
        current.is_monitoring = False

    monkeypatch.setattr(lifecycle, "_spawn_monitor_thread", _fake_spawn)
    monkeypatch.setattr(lifecycle, "_wait_for_monitor_loop", _fake_wait)

    lifecycle.start_realtime_monitor(system, interval_seconds=9)

    assert events == [
        ("bootstrap", system),
        ("banner", 9),
        ("spawn", 9),
        ("wait", True),
    ]
    assert system.is_monitoring is False


def test_stop_realtime_monitor_joins_thread(capsys):
    system = _build_system_stub()
    system.is_monitoring = True

    class _ThreadStub:
        def __init__(self):
            self.join_timeout = None

        def join(self, timeout=None):
            self.join_timeout = timeout

    thread = _ThreadStub()
    system.monitor_thread = thread

    lifecycle.stop_realtime_monitor(system)

    captured = capsys.readouterr()
    assert "正在停止监控" in captured.out
    assert thread.join_timeout == 2
    assert system.is_monitoring is False
