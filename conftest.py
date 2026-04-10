"""Pytest tiering configuration for smoke/slow/nightly suites."""

from __future__ import annotations

from pathlib import Path

import pytest


SLOW_FILES = {
    "test_batch_downloader.py",
    "test_daily_report_markdown.py",
    "test_factor_analysis.py",
    "test_history_recommendation_db.py",
    "test_history_records.py",
    "test_intraday_download.py",
    "test_position_controller_integration.py",
    "test_signal_feedback_evaluator.py",
}

NIGHTLY_FILES = {
    "test_backtest.py",
    "test_backtest_integration.py",
    "test_backtest_menu.py",
    "test_backtest_system.py",
    "test_improved_backtest.py",
    "test_live_replay_engine.py",
    "test_single_factor_ab.py",
    "test_stock_selector_pre_market.py",
    "test_strategy_backtest.py",
    "test_trade_visualizer.py",
}


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--run-slow",
        action="store_true",
        default=False,
        help="Run slow regression tests in addition to smoke tests.",
    )
    parser.addoption(
        "--run-nightly",
        action="store_true",
        default=False,
        help="Run nightly/full regression tests (includes slow tests).",
    )


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    run_slow = config.getoption("--run-slow")
    run_nightly = config.getoption("--run-nightly")
    skip_slow = pytest.mark.skip(reason="slow suite skipped; use --run-slow or --run-nightly")
    skip_nightly = pytest.mark.skip(reason="nightly suite skipped; use --run-nightly")

    for item in items:
        filename = Path(str(item.fspath)).name

        if filename in NIGHTLY_FILES:
            item.add_marker(pytest.mark.nightly)
            item.add_marker(pytest.mark.slow)
        elif filename in SLOW_FILES:
            item.add_marker(pytest.mark.slow)
        else:
            item.add_marker(pytest.mark.smoke)

        if item.get_closest_marker("nightly") and not run_nightly:
            item.add_marker(skip_nightly)
            continue

        if item.get_closest_marker("slow") and not (run_slow or run_nightly):
            item.add_marker(skip_slow)

