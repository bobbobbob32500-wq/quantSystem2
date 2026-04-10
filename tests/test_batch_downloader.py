# -*- coding: utf-8 -*-
"""Regression tests for batch intraday downloader compatibility helpers."""

from __future__ import annotations

import pandas as pd

from src.modules.backtest.batch_intraday_downloader import BatchIntradayDownloader


class _DBStub:
    def __init__(self):
        self.saved = {}

    def get_recommendations(self):
        return []

    def get_intraday_data(self, symbol):
        return self.saved.get(symbol, pd.DataFrame())

    def add_intraday_data(self, symbol, df):
        self.saved[symbol] = df.copy()
        return True


def _build_downloader() -> BatchIntradayDownloader:
    downloader = BatchIntradayDownloader.__new__(BatchIntradayDownloader)
    downloader.db = _DBStub()
    downloader.config = None
    downloader.bs = None
    return downloader


def test_get_unique_recommendations_normalizes_legacy_fields(monkeypatch):
    downloader = _build_downloader()
    monkeypatch.setattr(
        downloader,
        "get_historical_recommendations",
        lambda: [
            {"symbol": "600396.SH", "name": "华电辽能", "recommend_date": "2026-03-19"},
            {"symbol": "002980.SZ", "name": "华盛昌", "recommend_date": "2026-03-18"},
        ],
    )

    recommendations = downloader.get_unique_recommendations()

    assert len(recommendations) == 2
    assert recommendations[0]["first_recommend_date"] == "2026-03-19"
    assert recommendations[1]["symbol"] == "002980.SZ"


def test_get_next_n_trading_days_trims_result(monkeypatch):
    downloader = _build_downloader()
    monkeypatch.setattr(
        downloader,
        "get_trading_days",
        lambda start_date, end_date: [
            "2026-03-19",
            "2026-03-20",
            "2026-03-23",
            "2026-03-24",
        ],
    )

    trading_days = downloader.get_next_n_trading_days("2026-03-19", n=3)

    assert trading_days == ["2026-03-19", "2026-03-20", "2026-03-23"]


def test_batch_download_uses_default_recommendations(monkeypatch):
    downloader = _build_downloader()
    monkeypatch.setattr(
        downloader,
        "get_historical_recommendations",
        lambda: [{"symbol": "600396.SH", "name": "华电辽能", "recommend_date": "2026-03-19"}],
    )
    monkeypatch.setattr(
        downloader,
        "download_intraday_data",
        lambda symbol, start_date, end_date: pd.DataFrame(
            [
                {
                    "symbol": symbol,
                    "trade_time": pd.Timestamp("2026-03-19 09:35:00"),
                    "trade_date": "2026-03-19",
                    "open": 1.0,
                    "high": 1.1,
                    "low": 0.9,
                    "close": 1.05,
                    "volume": 1000,
                    "amount": 10000,
                }
            ]
        ),
    )

    stats = downloader.batch_download(recommendations=None, trading_days_count=1, skip_existing=True, show_progress=False)

    assert stats == {"600396.SH": 1}
    assert "600396.SH" in downloader.db.saved


def test_download_for_single_stock_filters_to_requested_days(monkeypatch):
    downloader = _build_downloader()
    monkeypatch.setattr(
        downloader,
        "get_next_n_trading_days",
        lambda start_date, n=5: ["2026-03-19", "2026-03-20"],
    )
    monkeypatch.setattr(
        downloader,
        "download_intraday_data",
        lambda symbol, start_date, end_date: pd.DataFrame(
            [
                {
                    "symbol": symbol,
                    "trade_time": pd.Timestamp("2026-03-19 09:35:00"),
                    "trade_date": "2026-03-19",
                    "open": 1.0,
                    "high": 1.1,
                    "low": 0.9,
                    "close": 1.05,
                    "volume": 1000,
                    "amount": 10000,
                },
                {
                    "symbol": symbol,
                    "trade_time": pd.Timestamp("2026-03-21 09:35:00"),
                    "trade_date": "2026-03-21",
                    "open": 1.0,
                    "high": 1.1,
                    "low": 0.9,
                    "close": 1.05,
                    "volume": 1000,
                    "amount": 10000,
                },
            ]
        ),
    )

    count = downloader.download_for_single_stock("600396.SH", "2026-03-19", trading_days_count=2)

    assert count == 1
    assert downloader.db.saved["600396.SH"]["trade_date"].tolist() == ["2026-03-19"]
