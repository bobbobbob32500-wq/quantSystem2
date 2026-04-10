# -*- coding: utf-8 -*-
"""Regression tests for realtime context normalization helpers."""

from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace

import pandas as pd

from src.modules.enhanced_hybrid_system import EnhancedHybridSystem


def _minute_frame(symbol: str, base_price: float = 10.0) -> pd.DataFrame:
    base = datetime(2026, 3, 29, 9, 35)
    return pd.DataFrame(
        [
            {
                "trade_time": base + timedelta(minutes=i),
                "open": base_price + 0.01 * i,
                "close": base_price + 0.02 * i,
                "high": base_price + 0.03 * i,
                "low": base_price - 0.01 + 0.01 * i,
                "volume": 100 + i * 10,
                "amount": (base_price + 0.02 * i) * (100 + i * 10),
                "symbol": symbol,
            }
            for i in range(3)
        ]
    )


def _build_system_stub() -> EnhancedHybridSystem:
    system = EnhancedHybridSystem.__new__(EnhancedHybridSystem)
    system.minute_max_symbols_per_round = 2
    system.minute_signal_min_bars = 2
    system.candidate_pool = [
        {"symbol": "600001", "name": "A"},
        {"symbol": "000001", "name": "B"},
        {"symbol": "000002", "name": "C"},
    ]
    system.quote_fetcher = SimpleNamespace(get_realtime_quotes_sina=lambda symbols: pd.DataFrame())
    system.minute_fetcher = SimpleNamespace(
        get_batch_minute_bars=lambda symbols: {},
        build_quote_frame=lambda minute_map, names=None: pd.DataFrame(),
        build_quote_from_minute=lambda symbol, minute_frame, name="": {},
    )
    return system


def test_fetch_realtime_context_caps_minute_symbols_and_falls_back_to_minute_quotes():
    system = _build_system_stub()
    captured = {"symbols": []}

    def _batch(symbols):
        captured["symbols"] = list(symbols)
        return {
            "600001.SH": _minute_frame("600001"),
            "000001.SZ": _minute_frame("000001", base_price=8.0),
        }

    system.minute_fetcher = SimpleNamespace(
        get_batch_minute_bars=_batch,
        build_quote_frame=lambda minute_map, names=None: pd.DataFrame(
            [
                {"symbol": "600001", "name": names.get("600001", ""), "price": 10.2, "open": 10.0, "high": 10.3, "low": 9.9, "volume": 330, "amount": 3300, "pre_close": 10.0},
                {"symbol": "000001", "name": names.get("000001", ""), "price": 8.2, "open": 8.0, "high": 8.3, "low": 7.9, "volume": 330, "amount": 2600, "pre_close": 8.0},
            ]
        ),
        build_quote_from_minute=lambda symbol, minute_frame, name="": {},
    )

    quote_df, minute_map = system._fetch_realtime_context(["600001", "000001", "000002"])

    assert captured["symbols"] == ["600001", "000001"]
    assert set(minute_map.keys()) == {"600001", "000001"}
    assert not quote_df.empty
    assert set(quote_df["symbol"].tolist()) == {"600001", "000001"}


def test_resolve_quote_row_prefers_realtime_quote_when_present():
    system = _build_system_stub()
    stock_data = pd.DataFrame(
        [
            {
                "symbol": "600001",
                "name": "实时A",
                "price": 10.5,
                "open": 10.1,
                "high": 10.6,
                "low": 10.0,
                "volume": 1200,
                "amount": 12000,
                "pre_close": 10.0,
            }
        ]
    )

    quote = system._resolve_quote_row(
        symbol="600001",
        stock_data=stock_data,
        minute_map={"600001": _minute_frame("600001")},
        candidate_name="候选A",
    )

    assert quote is not None
    assert quote["name"] == "实时A"
    assert quote["price"] == 10.5
    assert quote["symbol"] == "600001"


def test_resolve_quote_row_can_fallback_to_minute_map_with_normalized_symbol_key():
    system = _build_system_stub()
    system.minute_fetcher = SimpleNamespace(
        get_batch_minute_bars=lambda symbols: {},
        build_quote_frame=lambda minute_map, names=None: pd.DataFrame(),
        build_quote_from_minute=lambda symbol, minute_frame, name="": {
            "symbol": symbol,
            "name": name,
            "price": 9.9,
            "open": 9.7,
            "high": 10.0,
            "low": 9.6,
            "volume": 500,
            "amount": 4950,
            "pre_close": 9.7,
        },
    )

    quote = system._resolve_quote_row(
        symbol="600001",
        stock_data=pd.DataFrame(),
        minute_map={"600001.SH": _minute_frame("600001")},
        candidate_name="候选A",
    )

    assert quote is not None
    assert quote["symbol"] == "600001"
    assert quote["name"] == "候选A"
    assert quote["price"] == 9.9


def test_build_intraday_from_minute_uses_close_as_high_low_fallback():
    system = _build_system_stub()
    minute_df = pd.DataFrame(
        [
            {
                "trade_time": datetime(2026, 3, 29, 9, 35) + timedelta(minutes=i),
                "close": 10.0 + 0.1 * i,
                "volume": 100 + i,
            }
            for i in range(2)
        ]
    )

    intraday = system._build_intraday_from_minute(minute_df)

    assert intraday is not None
    assert intraday.price.tolist() == [10.0, 10.1]
    assert intraday.high.tolist() == [10.0, 10.1]
    assert intraday.low.tolist() == [10.0, 10.1]


def test_realtime_context_accepts_string_numeric_runtime_config():
    system = _build_system_stub()
    system.minute_max_symbols_per_round = "2"
    system.minute_signal_min_bars = "2"
    system.minute_batch_timeout_seconds = "2.8"
    captured = {"symbols": None, "timeout": None}

    def _batch(symbols, overall_timeout_seconds=None):
        captured["symbols"] = list(symbols)
        captured["timeout"] = overall_timeout_seconds
        return {"600001.SH": _minute_frame("600001")}

    system.minute_fetcher = SimpleNamespace(
        get_batch_minute_bars=_batch,
        build_quote_frame=lambda minute_map, names=None: pd.DataFrame(),
        build_quote_from_minute=lambda symbol, minute_frame, name="": {},
    )
    system.quote_fetcher = SimpleNamespace(get_realtime_quotes_sina=lambda symbols: pd.DataFrame())

    quote_df, minute_map = system._fetch_realtime_context(["600001", "000001", "000002"])
    intraday = system._build_intraday_from_minute(_minute_frame("600001"))

    assert quote_df.empty
    assert set(minute_map.keys()) == {"600001"}
    assert captured["symbols"] == ["600001", "000001"]
    assert abs(float(captured["timeout"]) - 2.8) < 1e-9
    assert intraday is not None
