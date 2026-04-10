"""Legacy open-route entry helpers for EnhancedHybridSystem."""

from __future__ import annotations

from datetime import datetime, time
from typing import Any, Dict, Optional

import pandas as pd

from src.modules.optimized_buy_signals import SignalOutput


def signal_monitor_window_open(
    system,
    now: datetime,
    market_env: Optional[Dict[str, Any]] = None,
) -> bool:
    market_score = float((market_env or {}).get("market_score", 50.0))
    detector = getattr(system, "signal_detector", None)
    if detector is not None and detector.time_filter(now, market_score=market_score):
        return True

    if not system._has_legacy_open_route_candidates():
        return False

    current_time = now.time()
    start_time = getattr(system, "legacy_gap_entry_start_time", time(9, 35))
    end_time = getattr(system, "legacy_low_open_entry_end_time", time(10, 30))
    return market_score > 50.0 and system._is_time_in_window(current_time, start_time, end_time)


def _ordered_minute_frame(
    system,
    symbol: str,
    minute_map: Optional[Dict[str, pd.DataFrame]],
) -> Optional[pd.DataFrame]:
    normalized_symbol = str(symbol or "").zfill(6)
    candidates = [normalized_symbol]
    normalizer = getattr(system, "_normalize_symbol_6", None)
    if callable(normalizer):
        normalized = normalizer(symbol)
        if normalized and normalized not in candidates:
            candidates.append(str(normalized))

    for key in candidates:
        minute_df = (minute_map or {}).get(key)
        if minute_df is not None and not minute_df.empty:
            return minute_df.sort_values("trade_time").reset_index(drop=True)
    return None


def _build_base_context(
    system,
    candidate: Dict[str, Any],
    quote: Dict[str, float],
    minute_map: Optional[Dict[str, pd.DataFrame]],
):
    strategy_profile = system._resolve_candidate_strategy_profile(candidate)
    if strategy_profile not in {"legacy", "legacy_opt"}:
        return None

    symbol = str(candidate.get("symbol", "")).zfill(6)
    current_price = system._to_float(quote.get("price"))
    open_price = system._to_float(quote.get("open"), default=current_price)
    pre_close = system._to_float(quote.get("pre_close"), default=open_price)
    current_price = system._to_float(quote.get("price"), default=open_price)
    high_price = system._to_float(quote.get("high"), default=current_price)
    low_price = system._to_float(quote.get("low"), default=current_price)
    open_pct = system._calc_open_pct(open_price, pre_close)

    ordered = _ordered_minute_frame(system, symbol=symbol, minute_map=minute_map)
    if ordered is not None:
        if "high" in ordered.columns:
            high_price = max(
                high_price,
                system._to_float(ordered["high"].max(), default=high_price),
            )
        if "low" in ordered.columns:
            low_price = min(
                low_price,
                system._to_float(ordered["low"].min(), default=low_price),
            )

    vwap = system._calc_intraday_vwap(ordered, fallback_price=current_price)
    details = {
        "open_pct": open_pct,
        "open_price": open_price,
        "pre_close": pre_close,
        "session_vwap": vwap,
        "session_high": high_price,
        "session_low": low_price,
    }
    return {
        "strategy_profile": strategy_profile,
        "template_source": "legacy_gap_open_v1",
        "symbol": symbol,
        "ordered": ordered,
        "open_price": open_price,
        "pre_close": pre_close,
        "current_price": current_price,
        "high_price": high_price,
        "low_price": low_price,
        "open_pct": open_pct,
        "vwap": vwap,
        "details": details,
    }


def _handle_flat_gap(system, context: Dict[str, Any], flat_lower: float, flat_upper: float):
    open_pct = float(context["open_pct"])
    if not (flat_lower < open_pct < flat_upper):
        return None

    details = dict(context["details"])
    details["filter_reason"] = "flat_gap_skip"
    return system._build_false_signal(
        strategy_profile=context["strategy_profile"],
        template_source=context["template_source"],
        route_name="legacy_flat_gap_skip",
        route_label="平弱开盘跳过",
        reason="平弱开盘过滤",
        debounce_window=1,
        route_blocked=True,
        extra_details=details,
    )


def _handle_mid_gap(
    system,
    context: Dict[str, Any],
    current_time: time,
    mid_lower: float,
    mid_upper: float,
    start_time: time,
    mid_end: time,
    support_tol: float,
    vwap_tol: float,
):
    open_pct = float(context["open_pct"])
    if not (mid_lower <= open_pct < mid_upper):
        return None
    if not system._is_time_in_window(current_time, start_time, mid_end):
        return None

    current_price = float(context["current_price"])
    open_price = float(context["open_price"])
    low_price = float(context["low_price"])
    vwap = float(context["vwap"])
    details = dict(context["details"])

    above_open = current_price >= open_price
    vwap_supported = current_price >= vwap * (1.0 - vwap_tol)
    open_supported = low_price >= open_price * (1.0 - support_tol)
    confidence = 0.55
    if above_open:
        confidence += 0.15
    if vwap_supported:
        confidence += 0.15
    if open_supported:
        confidence += 0.15
    details.update(
        {
            "above_open": above_open,
            "vwap_supported": vwap_supported,
            "open_supported": open_supported,
        }
    )
    if above_open and vwap_supported and open_supported:
        signal = SignalOutput(
            signal=True,
            signal_type="legacy_gap_mid_open",
            confidence=min(confidence, 0.95),
            reason="原策略开盘强势买点",
            details=details,
        )
        return system._wrap_signal_metadata(
            signal=signal,
            strategy_profile=context["strategy_profile"],
            template_source=context["template_source"],
            route_name="legacy_gap_mid_open",
            route_label="中强开盘直入",
            debounce_window=1,
        )
    return system._build_false_signal(
        strategy_profile=context["strategy_profile"],
        template_source=context["template_source"],
        route_name="legacy_gap_mid_open",
        route_label="中强开盘直入",
        reason="原策略开盘强势买点待确认",
        debounce_window=1,
        route_blocked=True,
        extra_details=details,
    )


def _handle_low_open(
    system,
    context: Dict[str, Any],
    current_time: time,
    flat_lower: float,
    start_time: time,
    low_end: time,
    reclaim_pct: float,
    vwap_tol: float,
):
    open_pct = float(context["open_pct"])
    if open_pct > flat_lower:
        return None
    if not system._is_time_in_window(current_time, start_time, low_end):
        return None

    details = dict(context["details"])
    ordered = context["ordered"]
    open_price = float(context["open_price"])
    current_price = float(context["current_price"])
    vwap = float(context["vwap"])
    strategy_profile = context["strategy_profile"]
    template_source = context["template_source"]
    low_wait_time = getattr(system, "legacy_low_open_min_wait_time", time(9, 45))

    min_low_age_bars = max(1, int(getattr(system, "legacy_low_open_min_low_age_bars", 1)))
    rebound_from_low_pct = float(
        getattr(system, "legacy_low_open_rebound_from_low_pct", 0.5)
    ) / 100.0
    max_chase_from_low_pct = float(
        getattr(system, "legacy_low_open_max_chase_from_low_pct", 2.0)
    ) / 100.0
    trend_bars = max(3, int(getattr(system, "legacy_low_open_recent_trend_bars", 3)))

    if ordered is None or ordered.empty:
        details["filter_reason"] = "low_open_need_more_bars"
        return system._build_false_signal(
            strategy_profile=strategy_profile,
            template_source=template_source,
            route_name="legacy_low_open_repair",
            route_label="低开探底后修复确认",
            reason="低开修复等待更多分时结构",
            debounce_window=1,
            route_blocked=True,
            extra_details=details,
        )

    ordered_low = pd.to_numeric(ordered["low"], errors="coerce").ffill().bfill()
    ordered_high = pd.to_numeric(ordered["high"], errors="coerce").ffill().bfill()
    ordered_close = pd.to_numeric(ordered["close"], errors="coerce").ffill().bfill()
    bar_count = len(ordered)
    low_pos = int(ordered_low.to_numpy().argmin())
    session_low_value = float(ordered_low.iloc[low_pos])
    low_age_bars = max(0, bar_count - 1 - low_pos)
    recent_window = min(trend_bars, bar_count)
    recent_closes = ordered_close.tail(recent_window).to_numpy()
    recent_lows = ordered_low.tail(recent_window).to_numpy()
    current_bar_high = float(ordered_high.iloc[-1])
    current_bar_low = float(ordered_low.iloc[-1])
    current_bar_range = max(current_bar_high - current_bar_low, max(open_price, 1.0) * 0.001)

    reclaim_open = current_price >= open_price * (1.0 + reclaim_pct)
    vwap_supported = current_price >= vwap * (1.0 - vwap_tol)
    reclaim_from_low = current_price >= session_low_value * (1.0 + rebound_from_low_pct)
    near_day_low = current_price <= session_low_value * (1.0 + max_chase_from_low_pct)
    low_confirmed = low_age_bars >= min_low_age_bars
    if recent_window >= 3:
        recent_close_up = bool(recent_closes[-1] >= recent_closes[-2] >= recent_closes[0])
        recent_higher_low = bool(recent_lows[-1] >= recent_lows[-2])
    elif recent_window == 2:
        recent_close_up = bool(recent_closes[-1] >= recent_closes[-2])
        recent_higher_low = bool(recent_lows[-1] >= recent_lows[-2])
    else:
        recent_close_up = False
        recent_higher_low = False
    not_still_falling = recent_close_up and recent_higher_low
    close_in_upper_half = current_price >= current_bar_low + current_bar_range * 0.50
    early_structure_ok = bool(
        (bar_count == 1 and close_in_upper_half)
        or (
            bar_count == 2
            and low_age_bars >= 1
            and recent_close_up
            and close_in_upper_half
        )
    )
    early_reversal_ready = bool(
        current_time < low_wait_time
        and bar_count <= 2
        and reclaim_from_low
        and near_day_low
        and early_structure_ok
    )
    standard_reversal_ready = bool(
        current_time >= low_wait_time
        and low_confirmed
        and reclaim_from_low
        and near_day_low
        and vwap_supported
        and not_still_falling
    )

    confidence = 0.35
    if low_confirmed:
        confidence += 0.15
    if reclaim_from_low:
        confidence += 0.15
    if near_day_low:
        confidence += 0.10
    if vwap_supported:
        confidence += 0.15
    if not_still_falling:
        confidence += 0.10
    if early_reversal_ready:
        confidence += 0.10

    details.update(
        {
            "reclaim_open": reclaim_open,
            "above_vwap": vwap_supported,
            "vwap_supported": vwap_supported,
            "session_low_value": session_low_value,
            "low_age_bars": low_age_bars,
            "low_confirmed": low_confirmed,
            "reclaim_from_low": reclaim_from_low,
            "near_day_low": near_day_low,
            "recent_close_up": recent_close_up,
            "recent_higher_low": recent_higher_low,
            "not_still_falling": not_still_falling,
            "close_in_upper_half": close_in_upper_half,
            "early_structure_ok": early_structure_ok,
            "early_reversal_ready": early_reversal_ready,
            "standard_reversal_ready": standard_reversal_ready,
            "bar_count": bar_count,
        }
    )
    if early_reversal_ready or standard_reversal_ready:
        signal = SignalOutput(
            signal=True,
            signal_type="legacy_low_open_repair",
            confidence=min(confidence, 0.92),
            reason="原策略低开探底后修复买点",
            details=details,
        )
        return system._wrap_signal_metadata(
            signal=signal,
            strategy_profile=strategy_profile,
            template_source=template_source,
            route_name="legacy_low_open_repair",
            route_label="低开探底后修复确认",
            debounce_window=1,
        )
    if current_time < low_wait_time:
        details["filter_reason"] = "low_open_wait_window"
        return system._build_false_signal(
            strategy_profile=strategy_profile,
            template_source=template_source,
            route_name="legacy_low_open_repair",
            route_label="低开探底后修复确认",
            reason="低开先观察，等待首轮止跌回拉",
            debounce_window=1,
            route_blocked=True,
            extra_details=details,
        )
    return system._build_false_signal(
        strategy_profile=strategy_profile,
        template_source=template_source,
        route_name="legacy_low_open_repair",
        route_label="低开探底后修复确认",
        reason="低开修复未确认，继续等待止跌转强",
        debounce_window=1,
        route_blocked=True,
        extra_details=details,
    )


def detect_legacy_gap_signal(
    system,
    candidate: Dict[str, Any],
    quote: Dict[str, float],
    now: datetime,
    minute_map: Optional[Dict[str, pd.DataFrame]],
) -> Optional[SignalOutput]:
    context = _build_base_context(
        system=system,
        candidate=candidate,
        quote=quote,
        minute_map=minute_map,
    )
    if context is None:
        return None

    current_time = now.time()
    flat_lower = float(getattr(system, "legacy_gap_flat_skip_lower_pct", -2.0))
    flat_upper = float(getattr(system, "legacy_gap_flat_skip_upper_pct", 1.0))
    mid_lower = float(getattr(system, "legacy_gap_mid_lower_pct", 1.0))
    mid_upper = float(getattr(system, "legacy_gap_mid_upper_pct", 4.0))
    start_time = getattr(system, "legacy_gap_entry_start_time", time(9, 35))
    mid_end = getattr(system, "legacy_gap_entry_end_time", time(10, 15))
    low_end = getattr(system, "legacy_low_open_entry_end_time", time(10, 30))
    support_tol = float(getattr(system, "legacy_open_support_tolerance_pct", 0.8)) / 100.0
    vwap_tol = float(getattr(system, "legacy_vwap_support_tolerance_pct", 0.2)) / 100.0
    reclaim_pct = float(getattr(system, "legacy_low_open_reclaim_pct", 0.3)) / 100.0

    flat_signal = _handle_flat_gap(system, context, flat_lower=flat_lower, flat_upper=flat_upper)
    if flat_signal is not None:
        return flat_signal

    mid_signal = _handle_mid_gap(
        system,
        context,
        current_time=current_time,
        mid_lower=mid_lower,
        mid_upper=mid_upper,
        start_time=start_time,
        mid_end=mid_end,
        support_tol=support_tol,
        vwap_tol=vwap_tol,
    )
    if mid_signal is not None:
        return mid_signal

    return _handle_low_open(
        system,
        context,
        current_time=current_time,
        flat_lower=flat_lower,
        start_time=start_time,
        low_end=low_end,
        reclaim_pct=reclaim_pct,
        vwap_tol=vwap_tol,
    )
