# -*- coding: utf-8 -*-
"""
二次启动菜单候选池同步测试
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from src.modules.secondary_launch_menu import SecondaryLaunchMenu


class FakeConfig:
    def get(self, key, default=None):
        return default


class FakeDB:
    def execute(self, *args, **kwargs):
        return None

    def query(self, sql, params=None):
        if "SELECT DISTINCT trade_date" in sql:
            return [{"trade_date": "20260331"}]
        return []

    def get_latest_trade_date(self, table_name):
        return "20260331"


def test_sync_to_candidate_pool_writes_monitor_cache(tmp_path):
    menu = SecondaryLaunchMenu(config=FakeConfig(), db=FakeDB())
    menu.root = Path(tmp_path)
    menu.cache_dir = menu.root / "data" / "cache"
    menu.cache_dir.mkdir(parents=True, exist_ok=True)

    selections = [
        {
            "ts_code": "600468.SH",
            "name": "百利电气",
            "industry": "电力设备",
            "signal_score": 88.6,
            "strategy_name": "secondary_launch_walkforward",
        },
        {
            "ts_code": "001258.SZ",
            "name": "立新能源",
            "industry": "公用事业",
            "signal_score": 86.2,
            "strategy_name": "secondary_launch_walkforward",
        },
    ]

    count = menu.sync_to_candidate_pool("20260331", selections)

    assert count == 2
    cache_file = menu.cache_dir / "candidate_pool.json"
    assert cache_file.exists()

    payload = json.loads(cache_file.read_text(encoding="utf-8"))
    assert payload["date"] == "20260331"
    assert len(payload["candidates"]) == 2
    assert payload["candidates"][0]["symbol"] == "600468"
    assert payload["candidates"][0]["strategy_profile"] == "secondary_launch"
    assert payload["candidates"][0]["pool_type"] == "core"


def test_format_recent_tracking_report_includes_intraday_review_section():
    menu = SecondaryLaunchMenu(config=FakeConfig(), db=FakeDB())
    report = {
        "generated_at": "2026-04-01 15:10:00",
        "latest_trade_date": "20260401",
        "lookback_trade_days": 40,
        "hold_days": 2,
        "signal_days": 2,
        "signal_count": 2,
        "completed_count": 1,
        "pending_count": 1,
        "completed_win_rate": 0.5,
        "completed_avg_return": 0.0123,
        "weekly_summary": [],
        "monthly_summary": [],
        "signal_gap_stats": {"gap_count": 0, "avg_gap_trade_days": 0, "max_gap_trade_days": 0, "gaps": []},
        "empty_streak_stats": {"max_empty_trade_days": 0, "latest_empty_trade_days": 0},
        "horizon_distribution": {
            "T+1": {"sample_count": 1, "win_rate": 1.0, "avg_return": 0.02, "min_return": 0.02, "max_return": 0.02},
            "T+2": {"sample_count": 1, "win_rate": 1.0, "avg_return": 0.03, "min_return": 0.03, "max_return": 0.03},
            "T+3": {"sample_count": 0, "win_rate": 0.0, "avg_return": 0.0, "min_return": 0.0, "max_return": 0.0},
        },
        "intraday_review_summary": {
            "reviewed_signal_count": 2,
            "buy_signal_count": 1,
            "buy_signal_ratio": 0.5,
            "not_pushed_count": 1,
            "top_not_pushed_reasons": [{"reason": "二次启动突破条件未满足", "count": 1}],
        },
        "details": [
            {
                "signal_date": "20260401",
                "ts_code": "600468.SH",
                "name": "百利电气",
                "rank": 1,
                "status": "跟踪中",
                "has_buy_signal": True,
                "signal_type": "secondary_launch_pullback",
                "trigger_time": "10:16:00",
                "push_reason": "回踩不破VWAP/开盘价后回拉",
                "not_pushed_reason": "",
                "confidence": 0.82,
                "observed_return": 0.01,
                "horizon_returns": {"T+1": 0.02, "T+2": 0.03, "T+3": None},
                "exit_date": "20260401",
            },
            {
                "signal_date": "20260401",
                "ts_code": "001258.SZ",
                "name": "立新能源",
                "rank": 2,
                "status": "跟踪中",
                "has_buy_signal": False,
                "signal_type": "",
                "trigger_time": "",
                "push_reason": "",
                "not_pushed_reason": "二次启动突破条件未满足",
                "confidence": 0.41,
                "observed_return": -0.01,
                "horizon_returns": {"T+1": None, "T+2": None, "T+3": None},
                "exit_date": "20260401",
            },
        ],
    }

    markdown = menu._format_recent_tracking_report(report)
    assert "盘中买点复盘统计" in markdown
    assert "未推送原因TOP" in markdown
    assert "是否买点" in markdown
    assert "回踩不破VWAP/开盘价后回拉" in markdown
    assert "二次启动突破条件未满足" in markdown


def test_recent_tracking_uses_optimized_final_signals_only(monkeypatch):
    menu = SecondaryLaunchMenu(config=FakeConfig(), db=FakeDB())

    class _FakeStrategy:
        params = type("P", (), {"picks_per_day": 2, "cooldown_days": 2})()

        @staticmethod
        def prepare_features(daily, basic):
            return pd.DataFrame(
                [
                    {"ts_code": "600468.SH", "trade_date": pd.Timestamp("2026-03-31"), "open": 10.0, "close": 10.2},
                    {"ts_code": "001258.SZ", "trade_date": pd.Timestamp("2026-03-31"), "open": 9.8, "close": 9.9},
                ]
            )

        @staticmethod
        def build_signal_frame(features):
            return pd.DataFrame(
                [
                    {
                        "signal_date": pd.Timestamp("2026-03-31"),
                        "ts_code": "600468.SH",
                        "name": "百利电气",
                        "industry": "电力设备",
                        "drawdown_from_peak": 0.05,
                        "days_since_last_limit_up": 4,
                    },
                    {
                        "signal_date": pd.Timestamp("2026-03-31"),
                        "ts_code": "001258.SZ",
                        "name": "立新能源",
                        "industry": "公用事业",
                        "drawdown_from_peak": 0.07,
                        "days_since_last_limit_up": 5,
                    },
                ]
            )

        @staticmethod
        def generate_signals_from_frame(signal_frame):
            return pd.DataFrame(
                [
                    {
                        "signal_date": pd.Timestamp("2026-03-31"),
                        "ts_code": "600468.SH",
                        "name": "百利电气",
                        "rank": 1,
                        "rs20": 0.91,
                        "signal_score": 88.6,
                    }
                ]
            )

    class _FakeBacktester:
        cost = type("C", (), {"slippage_rate": 0.001})()

        @staticmethod
        def load_data(start_date, end_date, warmup_days=90, forward_days=10):
            return {"daily": pd.DataFrame(), "basic": pd.DataFrame()}

        @staticmethod
        def _simulate_trades(features, signals, hold_days):
            return pd.DataFrame()

    monkeypatch.setattr(menu, "_build_strategy", lambda: (_FakeStrategy(), _FakeBacktester()))
    monkeypatch.setattr(menu, "_build_intraday_review_for_signal", lambda trade_date, row: {"has_buy_signal": False, "not_pushed_reason": "未触发", "confidence": 0.2})

    report = menu.generate_recent_signal_tracking_report(trade_days=1)

    detail_rows = [row for row in report["details"] if row.get("status") != "无信号"]
    assert len(detail_rows) == 1
    assert detail_rows[0]["ts_code"] == "600468.SH"
    assert all(row["ts_code"] != "001258.SZ" for row in detail_rows)
