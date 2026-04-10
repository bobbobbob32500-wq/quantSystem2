"""Signal-scoring helpers for EnhancedHybridSystem."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Dict, Optional


def _safe_float(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return float(default)


def _safe_int(value, default: int = 0) -> int:
    try:
        return int(float(value))
    except Exception:
        return int(default)


def get_feedback_adaptive_profile(
    system,
    strategy_profile: str,
    signal_subtype: str = "",
) -> Dict[str, float | str | bool]:
    """从最近闭环结果中提取对子类型的轻量自适应参数。"""
    profile = str(strategy_profile or "").strip().lower()
    subtype = str(signal_subtype or "").strip()
    neutral = {
        "active": False,
        "is_best_subtype": False,
        "threshold_delta": 0.0,
        "push_delta": 0.0,
        "position_multiplier": 1.0,
        "position_note": "",
        "source_run_id": "",
    }
    if profile != "secondary_launch" or not subtype:
        return neutral

    cache = getattr(system, "_feedback_adaptive_cache", None)
    cache_ttl = _safe_float(getattr(system, "feedback_adaptive_cache_seconds", 300.0), 300.0)
    now_ts = datetime.now().timestamp()
    if isinstance(cache, dict):
        cached_ts = _safe_float(cache.get("ts", 0.0), 0.0)
        if now_ts - cached_ts <= cache_ttl:
            cached_profiles = cache.get("profiles", {})
            if isinstance(cached_profiles, dict):
                result = cached_profiles.get(subtype)
                if isinstance(result, dict):
                    return {**neutral, **result}

    db = getattr(system, "db", None)
    run_row = None
    try:
        if db is not None and hasattr(db, "query_one"):
            run_row = db.query_one(
                """
                SELECT run_id, meta_json
                FROM signal_feedback_run
                ORDER BY created_time DESC
                LIMIT 1
                """
            )
    except Exception:
        run_row = None

    profiles: Dict[str, Dict] = {}
    if run_row and run_row.get("meta_json"):
        try:
            meta = json.loads(str(run_row.get("meta_json", "") or "{}"))
        except Exception:
            meta = {}
        signal_meta = meta.get("signal_meta") or {}
        insights = signal_meta.get("insights") or {}
        best_signal_raw = ""
        if isinstance(insights, dict):
            best_signal_raw = insights.get("best_signal_type", "")
        if isinstance(best_signal_raw, dict):
            best_signal_type = str(best_signal_raw.get("signal_type", "") or "")
        else:
            best_signal_type = str(best_signal_raw or "")
        ranked_rows = signal_meta.get("signal_type_stats") or []
        if isinstance(ranked_rows, dict):
            ranked_rows = [ranked_rows]
        elif not isinstance(ranked_rows, list):
            ranked_rows = []
        for row in ranked_rows:
            if not isinstance(row, dict):
                continue
            row_subtype = str(row.get("signal_type", "") or "")
            if not row_subtype:
                continue
            mean_ret = _safe_float(row.get("mean_net_return", 0.0), 0.0)
            win_rate = _safe_float(row.get("win_rate", 0.0), 0.0)
            sample_count = _safe_int(row.get("sample_count", 0), 0)
            is_best = bool(best_signal_type and row_subtype == best_signal_type)

            threshold_delta = 0.0
            push_delta = 0.0
            position_multiplier = 1.0
            note = ""
            if sample_count >= 3:
                if is_best and win_rate >= 0.55 and mean_ret > 0:
                    threshold_delta = -2.0
                    push_delta = -1.5
                    position_multiplier = 1.15
                    note = "feedback_best_subtype_boost"
                elif not is_best and mean_ret <= 0:
                    threshold_delta = 1.5
                    push_delta = 1.0
                    position_multiplier = 0.9
                    note = "feedback_non_best_subtype_trim"

            profiles[row_subtype] = {
                "active": sample_count >= 3,
                "is_best_subtype": is_best,
                "threshold_delta": threshold_delta,
                "push_delta": push_delta,
                "position_multiplier": position_multiplier,
                "position_note": note,
                "source_run_id": str(run_row.get("run_id", "") or ""),
            }

    try:
        system._feedback_adaptive_cache = {"ts": now_ts, "profiles": profiles}
    except Exception:
        pass
    result = profiles.get(subtype)
    return {**neutral, **(result or {})}


def get_dynamic_signal_thresholds(
    system,
    candidate: Dict,
    market_env: Dict,
    industry_confirm: Optional[Dict] = None,
    trade_control: Optional[Dict] = None,
    strategy_profile: str = "",
    signal_subtype: str = "",
) -> Dict[str, float]:
    """Adjust signal thresholds using market, industry and runtime optimization context."""
    pool_type = candidate.get("pool_type", "reserve")
    market_score = _safe_float(market_env.get("market_score", 50.0), 50.0)
    volatility = market_env.get("volatility", "normal")

    total_threshold = 74.0 if pool_type == "core" else 79.0
    intraday_threshold = 58.0 if pool_type == "core" else 63.0
    push_threshold = (
        system.min_signal_score_for_push
        if pool_type == "core"
        else system.min_signal_score_for_push + 4
    )

    if market_score >= 78:
        total_threshold -= 3
        intraday_threshold -= 4
        push_threshold -= 2
    elif market_score <= 60:
        total_threshold += 4
        intraday_threshold += 5
        push_threshold += 4

    if volatility == "high":
        intraday_threshold += 3
        push_threshold += 2
    elif volatility == "low":
        total_threshold -= 1

    industry_level = (industry_confirm or {}).get("level", "neutral")
    if industry_level == "strong":
        total_threshold -= 2
        intraday_threshold -= 2
        push_threshold -= 1
    elif industry_level == "weak":
        total_threshold += 3
        intraday_threshold += 3
        push_threshold += 2

    if trade_control:
        threshold_boost = _safe_float(trade_control.get("threshold_boost", 0.0), 0.0)
        push_boost = _safe_float(trade_control.get("push_boost", 0.0), 0.0)
        total_threshold += threshold_boost
        intraday_threshold += threshold_boost * 0.8
        push_threshold += push_boost

    optimization_profile = system._get_optimization_runtime_profile()
    optimization_active = bool(
        bool(getattr(system, "optimization_apply_to_thresholds", True))
        and optimization_profile.get("active", False)
    )
    if optimization_active:
        total_threshold = max(
            total_threshold,
            _safe_float(optimization_profile.get("min_total_score_floor", total_threshold), total_threshold),
        )
        intraday_threshold = max(
            intraday_threshold,
            _safe_float(
                optimization_profile.get("min_intraday_score_floor", intraday_threshold),
                intraday_threshold,
            ),
        )
        push_threshold = max(
            push_threshold,
            _safe_float(optimization_profile.get("push_threshold_floor", push_threshold), push_threshold),
        )

    adaptive_profile = get_feedback_adaptive_profile(
        system=system,
        strategy_profile=strategy_profile,
        signal_subtype=signal_subtype,
    )
    total_threshold += _safe_float(adaptive_profile.get("threshold_delta", 0.0), 0.0)
    push_threshold += _safe_float(adaptive_profile.get("push_delta", 0.0), 0.0)

    return {
        "min_total_score": max(65.0, total_threshold),
        "min_intraday_score": max(45.0, intraday_threshold),
        "push_threshold": max(70.0, push_threshold),
        "optimization_active": optimization_active,
        "feedback_adaptive_active": bool(adaptive_profile.get("active", False)),
        "feedback_adaptive_best_subtype": bool(adaptive_profile.get("is_best_subtype", False)),
    }


def calculate_total_signal_score(
    system,
    candidate: Dict,
    signal,
    market_env: Dict,
    industry_score_adjustment: float = 0.0,
) -> float:
    """Blend overnight score with intraday signal confidence."""
    overnight_weight = 0.7
    intraday_weight = 0.3

    if market_env.get("trend") == "up":
        overnight_weight = 0.6
        intraday_weight = 0.4
    elif market_env.get("trend") == "down":
        overnight_weight = 0.75
        intraday_weight = 0.25

    if candidate.get("pool_type") == "reserve":
        overnight_weight -= 0.05
        intraday_weight += 0.05

    intraday_score = float(signal.confidence) * 100
    total = candidate["score"] * overnight_weight + intraday_score * intraday_weight
    return max(0.0, min(100.0, total + float(industry_score_adjustment)))
