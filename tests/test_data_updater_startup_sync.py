# -*- coding: utf-8 -*-
from __future__ import annotations

from datetime import datetime

from src.modules.data_updater import DataUpdater


class FakeConfig:
    def __init__(self, values=None):
        self.values = values or {}

    def get(self, key, default=None):
        return self.values.get(key, default)


class FakeDB:
    def __init__(self, latest="20260402", mainboard_stock_count=5, daily_counts=None):
        self.latest = latest
        self.mainboard_stock_count = mainboard_stock_count
        self.daily_counts = dict(daily_counts or {})

    def get_latest_trade_date(self, table_name="stock_daily"):
        return self.latest

    def query_one(self, sql, params=None):
        if "FROM stock_basic" in sql:
            return {"cnt": self.mainboard_stock_count}
        if "FROM stock_daily" in sql and "COUNT(DISTINCT ts_code)" in sql:
            trade_date = (params or [""])[0]
            return {"cnt": int(self.daily_counts.get(trade_date, 0))}
        raise AssertionError(f"Unexpected query: {sql}")


class FakeCalendarSource:
    def __init__(self, trade_dates):
        self.trade_dates = list(trade_dates)

    def get_trade_calendar(self, start_date: str, end_date: str):
        return [d for d in self.trade_dates if start_date <= d <= end_date]


def test_resolve_startup_target_trade_date_uses_previous_open_day_before_ready_time():
    updater = DataUpdater(config=FakeConfig(), db=FakeDB())
    updater.primary_source = FakeCalendarSource(["20260403", "20260406", "20260407"])
    updater.secondary_source = FakeCalendarSource([])

    target = updater._resolve_startup_target_trade_date(datetime(2026, 4, 7, 11, 0, 0))

    assert target == "20260406"


def test_ensure_latest_market_data_backfills_missing_trade_dates():
    config = FakeConfig(
        {
            "data_source.startup_refresh_stock_basic": True,
            "data_source.startup_update_ready_time": "17:30",
            "data_source.startup_trade_calendar_lookback_days": 14,
            "data_source.startup_min_mainboard_coverage_ratio": 0.7,
            "market_analysis.indices": ["000001.SH", "399001.SZ"],
        }
    )
    db = FakeDB(latest="20260402", mainboard_stock_count=5, daily_counts={"20260402": 5})
    updater = DataUpdater(config=config, db=db)
    updater.primary_source = FakeCalendarSource(["20260402", "20260403", "20260407"])
    updater.secondary_source = FakeCalendarSource([])

    calls = {"stock_basic": 0, "range": None, "index": []}

    def fake_update_stock_basic():
        calls["stock_basic"] += 1
        return 3210

    def fake_update_daily_data_range(start_date: str, end_date: str):
        calls["range"] = (start_date, end_date)
        db.latest = "20260407"
        db.daily_counts["20260407"] = 5
        return 6543

    def fake_update_index_data(index_code: str, days: int = 30):
        calls["index"].append((index_code, days))
        return 30

    updater.update_stock_basic = fake_update_stock_basic
    updater.update_daily_data_range = fake_update_daily_data_range
    updater.update_index_data = fake_update_index_data

    result = updater.ensure_latest_market_data(datetime(2026, 4, 7, 18, 0, 0))

    assert result["status"] == "success"
    assert result["target_trade_date"] == "20260407"
    assert result["missing_trade_dates"] == ["20260403", "20260407"]
    assert result["latest_trade_date_after"] == "20260407"
    assert result["daily_data_count"] == 6543
    assert result["stock_basic_count"] == 3210
    assert calls["stock_basic"] == 1
    assert calls["range"] == ("2026-04-03", "2026-04-07")
    assert calls["index"] == [("000001.SH", 30), ("399001.SZ", 30)]
