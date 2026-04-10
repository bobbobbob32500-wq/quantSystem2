"""Shared signal utility helpers for EnhancedHybridSystem."""

from __future__ import annotations

from datetime import time
from typing import Any, Dict, Optional

import pandas as pd

from src.modules.optimized_buy_signals import SignalOutput


def is_time_in_window(current: time, start: time, end: time) -> bool:
    if start <= end:
        return start <= current <= end
    return current >= start or current <= end


def calc_open_pct(open_price: float, pre_close: float) -> float:
    if open_price <= 0 or pre_close <= 0:
        return 0.0
    return (open_price / pre_close - 1.0) * 100.0


def calc_intraday_vwap(minute_df: Optional[pd.DataFrame], fallback_price: float) -> float:
    if minute_df is None or minute_df.empty:
        return float(fallback_price)
    if "close" not in minute_df.columns:
        return float(fallback_price)

    prices = minute_df["close"].fillna(fallback_price).astype(float)
    volumes = (
        minute_df["volume"].fillna(0).astype(float)
        if "volume" in minute_df.columns
        else pd.Series([0.0] * len(prices))
    )
    total_volume = float(volumes.sum())
    if total_volume > 0:
        return float((prices * volumes).sum() / total_volume)
    return float(prices.iloc[-1]) if not prices.empty else float(fallback_price)


def wrap_signal_metadata(
    system,
    signal: SignalOutput,
    strategy_profile: str,
    template_source: str,
    route_name: str,
    route_label: str,
    debounce_window: Optional[int] = None,
    route_blocked: bool = False,
) -> SignalOutput:
    details = signal.details if isinstance(signal.details, dict) else {}
    details["strategy_profile"] = system._normalize_strategy_profile(strategy_profile)
    details["buy_template_source"] = str(template_source or "").strip()
    details["buy_route"] = str(route_name or "").strip()
    details["buy_route_label"] = str(route_label or "").strip()
    details["route_blocked"] = bool(route_blocked)
    if debounce_window is not None:
        details["debounce_window"] = max(1, int(debounce_window))
    signal.details = details
    return signal


def build_false_signal(
    system,
    strategy_profile: str,
    template_source: str,
    route_name: str,
    route_label: str,
    reason: str = "",
    debounce_window: Optional[int] = None,
    route_blocked: bool = False,
    extra_details: Optional[Dict[str, Any]] = None,
) -> SignalOutput:
    signal = SignalOutput(
        signal=False,
        signal_type="",
        confidence=0.0,
        reason=reason,
        details=dict(extra_details or {}),
    )
    return system._wrap_signal_metadata(
        signal=signal,
        strategy_profile=strategy_profile,
        template_source=template_source,
        route_name=route_name,
        route_label=route_label,
        debounce_window=debounce_window,
        route_blocked=route_blocked,
    )


def resolve_signal_debounce_window(system, signal: SignalOutput) -> int:
    details = signal.details if isinstance(signal.details, dict) else {}
    configured = int(system.config.get("debounce_window", 2))
    return max(1, int(system._to_float(details.get("debounce_window", configured), configured)))
