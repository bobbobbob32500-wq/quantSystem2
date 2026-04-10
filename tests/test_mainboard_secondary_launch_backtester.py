# -*- coding: utf-8 -*-
"""
二次启动策略回测器测试
"""

from __future__ import annotations

import pandas as pd

from src.modules.mainboard_secondary_launch_backtester import (
    CostConfig,
    MainboardSecondaryLaunchBacktester,
)


class FakeDB:
    def __init__(self):
        self.calls = []

    def query(self, sql, params=None):
        self.calls.append((sql, params))
        if "FROM stock_daily" in sql:
            return []
        if "FROM stock_basic" in sql:
            return []
        return []


class FakeStrategy:
    def prepare_features(self, daily_df, basic_df):
        return daily_df.copy()

    def generate_signals(self, feature_df):
        return pd.DataFrame(
            [
                {
                    "signal_date": pd.Timestamp("2026-03-02"),
                    "ts_code": "000001.SZ",
                    "name": "测试A",
                    "rank": 1,
                    "rs20": 0.12,
                },
                {
                    "signal_date": pd.Timestamp("2026-03-05"),
                    "ts_code": "000001.SZ",
                    "name": "测试A",
                    "rank": 1,
                    "rs20": 0.15,
                },
            ]
        )


class StubBacktester(MainboardSecondaryLaunchBacktester):
    def load_data(self, start_date, end_date, warmup_days=60, forward_days=10):
        daily = pd.DataFrame(
            [
                {"ts_code": "000001.SZ", "trade_date": "20260302", "open": 10.0, "close": 10.1, "high": 10.2, "low": 9.9, "vol": 1000, "amount": 100000, "pct_chg": 1.0},
                {"ts_code": "000001.SZ", "trade_date": "20260303", "open": 10.1, "close": 10.3, "high": 10.4, "low": 10.0, "vol": 1000, "amount": 100000, "pct_chg": 2.0},
                {"ts_code": "000001.SZ", "trade_date": "20260304", "open": 10.3, "close": 10.4, "high": 10.5, "low": 10.2, "vol": 1000, "amount": 100000, "pct_chg": 1.0},
                {"ts_code": "000001.SZ", "trade_date": "20260305", "open": 10.4, "close": 10.6, "high": 10.7, "low": 10.3, "vol": 1000, "amount": 100000, "pct_chg": 2.0},
                {"ts_code": "000001.SZ", "trade_date": "20260306", "open": 10.6, "close": 10.8, "high": 10.9, "low": 10.5, "vol": 1000, "amount": 100000, "pct_chg": 2.0},
                {"ts_code": "000001.SH", "trade_date": "20260302", "open": 3000, "close": 3000, "high": 3010, "low": 2990, "vol": 1000, "amount": 100000, "pct_chg": 0.0},
                {"ts_code": "000001.SH", "trade_date": "20260303", "open": 3000, "close": 3020, "high": 3030, "low": 2990, "vol": 1000, "amount": 100000, "pct_chg": 0.7},
                {"ts_code": "000001.SH", "trade_date": "20260304", "open": 3020, "close": 3010, "high": 3030, "low": 3000, "vol": 1000, "amount": 100000, "pct_chg": -0.3},
                {"ts_code": "000001.SH", "trade_date": "20260305", "open": 3010, "close": 3030, "high": 3040, "low": 3000, "vol": 1000, "amount": 100000, "pct_chg": 0.7},
                {"ts_code": "000001.SH", "trade_date": "20260306", "open": 3030, "close": 3040, "high": 3050, "low": 3020, "vol": 1000, "amount": 100000, "pct_chg": 0.3},
            ]
        )
        basic = pd.DataFrame(
            [
                {"ts_code": "000001.SZ", "name": "测试A", "industry": "测试", "list_date": "20200101"},
                {"ts_code": "000001.SH", "name": "上证指数", "industry": "指数", "list_date": "19900101"},
            ]
        )
        return {"daily": daily, "basic": basic}


def test_load_data_extends_query_window():
    db = FakeDB()
    backtester = MainboardSecondaryLaunchBacktester(db=db, strategy=FakeStrategy(), cost=CostConfig())
    backtester.load_data("20260301", "20260327", warmup_days=60, forward_days=10)

    _, params = db.calls[0]
    assert params == ("20251231", "20260406")


def test_run_backtest_filters_signals_to_requested_window():
    backtester = StubBacktester(db=FakeDB(), strategy=FakeStrategy(), cost=CostConfig(slippage_rate=0.0))
    result = backtester.run_backtest("20260304", "20260305", hold_days=1)

    signals = result["signals"]
    trades = result["trades"]

    assert len(signals) == 1
    assert signals.iloc[0]["signal_date"] == pd.Timestamp("2026-03-05")
    assert len(trades) == 1
    assert trades.iloc[0]["signal_date"] == pd.Timestamp("2026-03-05")
