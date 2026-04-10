# -*- coding: utf-8 -*-
"""Regression tests for scheduled reoptimizer integration contract."""

from __future__ import annotations

from types import SimpleNamespace

import pandas as pd

from src.modules.scheduled_reoptimizer import ScheduledReoptimizer


def test_force_reoptimize_accepts_result_with_composite_score_and_summary():
    optimizer = ScheduledReoptimizer(interval_minutes=30, lookback_days=30, min_improvement=0.1)
    optimizer.strategy_system = SimpleNamespace(
        run_complete_pipeline=lambda data: SimpleNamespace(
            strategy_func=lambda bar: {"action": "buy", "bar": bar},
            composite_score=1.23,
            summary={"status": "ok", "composite_score": 1.23},
        )
    )

    result = optimizer.force_reoptimize(pd.DataFrame([{"entry_date": "2026-03-20"}]))

    assert result is not None
    assert result["score"] == 1.23
    assert result["summary"]["status"] == "ok"
    assert optimizer.current_score == 1.23
    assert callable(optimizer.current_strategy)
