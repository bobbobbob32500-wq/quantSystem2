# -*- coding: utf-8 -*-
"""Tests for realtime minute fetcher normalization and cache behavior."""

import pandas as pd

import src.modules.realtime_minute_fetcher as minute_module
from src.modules.realtime_minute_fetcher import RealtimeMinuteFetcher


def _sample_hist_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "时间": ["2026-03-27 09:30:00", "2026-03-27 09:31:00", "2026-03-27 09:32:00"],
            "开盘": [10.0, 10.0, 10.2],
            "收盘": [10.0, 10.2, 10.1],
            "最高": [10.05, 10.25, 10.22],
            "最低": [9.98, 9.99, 10.06],
            "成交量": [1000, 2000, 1500],
            "成交额": [10000, 20400, 15150],
        }
    )


def test_normalize_hist_minute_df_and_quote_build():
    fetcher = RealtimeMinuteFetcher(cache_ttl_seconds=0, min_valid_rows=1)
    normalized = fetcher._normalize_hist_minute_df(_sample_hist_frame(), symbol="600000")

    assert list(normalized.columns) == fetcher.STANDARD_COLUMNS
    assert len(normalized) == 3
    assert normalized.iloc[-1]["trade_date"] == "2026-03-27"
    assert float(normalized.iloc[-1]["close"]) == 10.1

    quote = fetcher.build_quote_from_minute("600000", normalized, name="浦发银行")
    assert quote["symbol"] == "600000"
    assert quote["name"] == "浦发银行"
    assert quote["price"] == 10.1
    assert quote["open"] == 10.0
    assert quote["high"] == 10.25
    assert quote["low"] == 9.98
    assert quote["volume"] == 4500.0


def test_get_minute_bars_uses_cache(monkeypatch):
    fetcher = RealtimeMinuteFetcher(cache_ttl_seconds=60, min_valid_rows=1)
    sample = fetcher._normalize_hist_minute_df(_sample_hist_frame(), symbol="600000")
    calls = {"hist": 0}

    monkeypatch.setattr(minute_module, "AKSHARE_AVAILABLE", True)

    def fake_hist(symbol: str, trade_date=None):
        calls["hist"] += 1
        return sample.copy()

    monkeypatch.setattr(fetcher, "_fetch_from_hist_min_em", fake_hist)
    monkeypatch.setattr(fetcher, "_fetch_from_sina_minute", lambda *args, **kwargs: fetcher._empty_frame())

    first = fetcher.get_minute_bars("600000", trade_date="2026-03-27", force_refresh=False)
    second = fetcher.get_minute_bars("600000", trade_date="2026-03-27", force_refresh=False)

    assert not first.empty
    assert not second.empty
    assert calls["hist"] == 1
