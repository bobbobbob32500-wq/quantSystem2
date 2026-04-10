# -*- coding: utf-8 -*-
"""真实分时回放与压力测试验证。"""

from datetime import datetime

from src.modules.live_replay_engine import LiveReplayEngine
from src.modules.optimized_buy_signals import OptimizedBuySignals


def test_signal_time_filter_uses_market_score():
    detector = OptimizedBuySignals()
    current_time = datetime(2026, 3, 27, 10, 0)

    allowed, position_ratio = detector.evaluate_time_filter(current_time, market_score=65.0)
    assert allowed is True
    assert 0 < position_ratio <= 1
    assert detector.time_filter(current_time, market_score=45.0) is False


def test_live_replay_session_uses_real_intraday_data():
    engine = LiveReplayEngine(warmup_bars=20, debounce_window=2)
    sessions = engine.list_available_sessions(limit=1, min_rows=120)

    assert sessions, "未找到可用的真实分时回放会话"
    report = engine.replay_session(
        symbol=sessions[0]["symbol"],
        trade_date=sessions[0]["trade_date"],
        min_rows=120,
    )

    assert report["bars_total"] >= 120
    assert report["bars_processed"] > 0
    assert report["avg_latency_ms"] >= 0
    assert report["error_count"] >= 0


def test_live_replay_stress_test_runs_with_real_data():
    engine = LiveReplayEngine(warmup_bars=20, debounce_window=2)
    summary = engine.stress_test(session_limit=3, loop_count=1, min_rows=120)

    assert summary["session_runs"] > 0
    assert summary["total_bars_processed"] > 0
    assert summary["bars_per_second"] > 0
    assert summary["peak_memory_mb"] >= 0
