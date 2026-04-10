"""Realtime quote/minute normalization helpers for EnhancedHybridSystem."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from src.modules.optimized_buy_signals import IntradayData

logger = logging.getLogger(__name__)


def _safe_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)


def _safe_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _normalize_symbol(system, symbol: Any) -> str:
    normalizer = getattr(system, "_normalize_symbol_6", None)
    if callable(normalizer):
        normalized = normalizer(symbol)
        if normalized:
            return str(normalized)
    text = str(symbol or "").strip()
    digits = "".join(ch for ch in text if ch.isdigit())
    if len(digits) >= 6:
        return digits[-6:]
    return text.zfill(6) if text.isdigit() else text


def _normalize_quote_frame(system, quote_df: pd.DataFrame) -> pd.DataFrame:
    if quote_df is None or quote_df.empty:
        return pd.DataFrame()

    normalized = quote_df.copy()
    if "symbol" in normalized.columns:
        normalized["symbol"] = normalized["symbol"].map(lambda value: _normalize_symbol(system, value))
    return normalized


def _normalize_minute_map(
    system,
    minute_map: Optional[Dict[str, pd.DataFrame]],
) -> Dict[str, pd.DataFrame]:
    normalized: Dict[str, pd.DataFrame] = {}
    for symbol, frame in (minute_map or {}).items():
        key = _normalize_symbol(system, symbol)
        if not key:
            continue
        normalized[key] = frame
    return normalized


def _standardize_quote(
    system,
    symbol: str,
    raw_quote: Dict[str, Any],
    default_name: str = "",
) -> Optional[Dict[str, float]]:
    if not raw_quote:
        return None

    normalized_symbol = _normalize_symbol(system, raw_quote.get("symbol", symbol) or symbol)
    price = system._to_float(raw_quote.get("price"))
    open_price = system._to_float(raw_quote.get("open"), default=price)
    high = system._to_float(raw_quote.get("high"), default=price)
    low = system._to_float(raw_quote.get("low"), default=price)
    volume = system._to_float(raw_quote.get("volume"))
    amount = system._to_float(raw_quote.get("amount"))
    pre_close = system._to_float(raw_quote.get("pre_close"), default=open_price)

    return {
        "symbol": normalized_symbol or _normalize_symbol(system, symbol),
        "name": str(raw_quote.get("name") or default_name or ""),
        "price": price,
        "open": open_price,
        "high": high,
        "low": low,
        "volume": volume,
        "amount": amount,
        "pre_close": pre_close,
    }


def fetch_realtime_context(
    system,
    symbols: List[str],
) -> Tuple[pd.DataFrame, Dict[str, pd.DataFrame]]:
    normalized_symbols = [_normalize_symbol(system, symbol) for symbol in symbols]
    normalized_symbols = [symbol for symbol in normalized_symbols if symbol]

    quote_df = system.quote_fetcher.get_realtime_quotes_sina(normalized_symbols)
    quote_df = _normalize_quote_frame(system, quote_df)

    minute_symbols = normalized_symbols
    max_symbols = _safe_int(getattr(system, "minute_max_symbols_per_round", 0), 0)
    if max_symbols > 0 and len(normalized_symbols) > max_symbols:
        minute_symbols = normalized_symbols[:max_symbols]
        logger.info(
            "Minute fetch symbols capped: %s/%s",
            len(minute_symbols),
            len(normalized_symbols),
        )

    raw_timeout = getattr(system, "minute_batch_timeout_seconds", None)
    overall_timeout = _safe_float(raw_timeout, 0.0) if raw_timeout is not None else None
    if overall_timeout is not None and overall_timeout <= 0:
        overall_timeout = None
    # 兼容测试替身/不同实现：若不支持 overall_timeout_seconds，则回退到旧签名调用
    try:
        minute_map = system.minute_fetcher.get_batch_minute_bars(
            minute_symbols,
            overall_timeout_seconds=overall_timeout,
        )
    except TypeError:
        minute_map = system.minute_fetcher.get_batch_minute_bars(minute_symbols)
    minute_map = _normalize_minute_map(system, minute_map)

    if quote_df.empty and minute_map:
        names = {
            _normalize_symbol(system, candidate.get("symbol")): candidate.get("name", "")
            for candidate in getattr(system, "candidate_pool", []) or []
        }
        quote_df = _normalize_quote_frame(
            system,
            system.minute_fetcher.build_quote_frame(minute_map, names=names),
        )

    return quote_df, minute_map


def resolve_quote_row(
    system,
    symbol: str,
    stock_data: pd.DataFrame,
    minute_map: Optional[Dict[str, pd.DataFrame]] = None,
    candidate_name: str = "",
) -> Optional[Dict[str, float]]:
    normalized_symbol = _normalize_symbol(system, symbol)
    if stock_data is not None and not stock_data.empty:
        row = stock_data.iloc[0].to_dict()
        return _standardize_quote(
            system=system,
            symbol=normalized_symbol,
            raw_quote=row,
            default_name=candidate_name,
        )

    normalized_minute_map = _normalize_minute_map(system, minute_map)
    minute_df = normalized_minute_map.get(normalized_symbol)
    if minute_df is None or minute_df.empty:
        return None

    quote = system.minute_fetcher.build_quote_from_minute(
        symbol=normalized_symbol,
        minute_frame=minute_df,
        name=candidate_name,
    )
    return _standardize_quote(
        system=system,
        symbol=normalized_symbol,
        raw_quote=quote,
        default_name=candidate_name,
    )


def build_intraday_from_minute(
    system,
    minute_df: pd.DataFrame,
) -> Optional[IntradayData]:
    if minute_df is None or minute_df.empty:
        return None

    ordered = minute_df.sort_values("trade_time").reset_index(drop=True)
    min_bars = max(1, _safe_int(getattr(system, "minute_signal_min_bars", 20), 20))
    if len(ordered) < min_bars:
        return None

    close = pd.to_numeric(ordered.get("close"), errors="coerce").ffill().bfill()
    if close.empty:
        return None

    volume = pd.to_numeric(ordered.get("volume"), errors="coerce").fillna(0.0)
    high_source = ordered["high"] if "high" in ordered.columns else close
    low_source = ordered["low"] if "low" in ordered.columns else close
    high = pd.to_numeric(high_source, errors="coerce").fillna(close).astype(float)
    low = pd.to_numeric(low_source, errors="coerce").fillna(close).astype(float)

    return IntradayData(
        price=close.astype(float).to_numpy(),
        volume=volume.astype(float).to_numpy(),
        high=high.to_numpy(),
        low=low.to_numpy(),
        timestamp=ordered["trade_time"].to_numpy(),
    )
