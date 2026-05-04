"""Buy-signal building helpers for EnhancedHybridSystem."""

from __future__ import annotations

from datetime import datetime
from typing import Dict, Optional


def _get_secondary_launch_exit_profile(signal_subtype: str) -> Dict:
    """根据分钟级回放结果，为二次启动盘中信号提供默认退出参数。"""
    subtype = str(signal_subtype or "").strip()
    # 当前历史回放最优规则:
    # SL -1.5% | TP 8.0% | TR none | HOLD 240m
    # 但A股现货为T+1，不能把240分钟直接映射成当日真实卖出时间，
    # 因此这里只把它作为“次日优先观察窗口”，真实执行层至少持有1个交易日。
    if subtype in {"secondary_launch_pullback", "secondary_launch_breakout"}:
        return {
            "dynamic_stop_loss_pct": -0.015,
            "dynamic_take_profit_pct": 0.08,
            "dynamic_tp1_pct": 0.04,
            "disable_dynamic_trailing_stop": True,
            "min_hold_trading_days": 1,
            "next_day_observation_window_minutes": 240,
            "secondary_launch_exit_profile": "replay_best_t1_v2",
        }
    return {}


def build_buy_signal(
    system,
    candidate: Dict,
    current_price: float,
    signal,
    now: datetime,
    market_env: Dict,
    industry_context: Optional[Dict] = None,
    trade_control: Optional[Dict] = None,
) -> Optional[Dict]:
    """Build a unified buy signal after applying dynamic threshold filters."""
    intraday_score = float(signal.confidence) * 100
    signal_details = signal.details if isinstance(getattr(signal, "details", None), dict) else {}
    strategy_profile = system._resolve_candidate_strategy_profile(candidate)
    buy_template_source = str(
        signal_details.get(
            "buy_template_source",
            system._default_buy_template_source(strategy_profile),
        )
    )
    buy_route = str(signal_details.get("buy_route", "") or "")
    signal_subtype = str(
        signal_details.get(
            "signal_subtype",
            buy_route or str(getattr(signal, "signal_type", "") or signal.reason or ""),
        )
    )
    buy_route_label = str(
        signal_details.get(
            "buy_route_label",
            buy_route or system._default_buy_route_label(strategy_profile),
        )
    )
    industry_confirm = system._resolve_candidate_industry_confirm(candidate, industry_context)
    thresholds = system._get_dynamic_signal_thresholds(
        candidate,
        market_env,
        industry_confirm=industry_confirm,
        trade_control=trade_control,
        strategy_profile=strategy_profile,
        signal_subtype=signal_subtype,
    )
    total_score = system._calculate_total_signal_score(
        candidate,
        signal,
        market_env,
        industry_score_adjustment=industry_confirm.get("score_adjustment", 0.0),
    )
    optimization_profile = system._get_optimization_runtime_profile(now=now)

    if total_score < thresholds["min_total_score"]:
        return None

    if intraday_score < thresholds["min_intraday_score"]:
        return None

    if strategy_profile == "secondary_launch":
        industry_score = float(industry_confirm.get("score", 50.0) or 50.0)
        industry_level = str(industry_confirm.get("level", "neutral") or "neutral")
        if industry_score < 45.0 or industry_level in {"weak", "poor"}:
            return None

    position_advice = system._build_position_advice(
        candidate=candidate,
        total_score=total_score,
        trade_control=trade_control,
        strategy_profile=strategy_profile,
        signal_subtype=signal_subtype,
    )

    execution_tier = str(signal_details.get("execution_tier", "") or "").strip().lower()
    execution_note = str(signal_details.get("execution_note", "") or "").strip()

    buy_signal = {
        "symbol": candidate["symbol"],
        "name": candidate["name"],
        "price": current_price,
        "pool_type": candidate["pool_type"],
        "industry": candidate.get("industry", ""),
        "strategy_profile": strategy_profile,
        "strategy_label": system._strategy_profile_label(strategy_profile),
        "overnight_score": candidate["score"],
        "intraday_score": intraday_score,
        "total_score": total_score,
        "signal_type": signal.reason,
        "signal_subtype": signal_subtype,
        "signal_details": signal_details,
        "execution_tier": execution_tier,
        "execution_note": execution_note,
        "buy_template_source": buy_template_source,
        "buy_route": buy_route,
        "buy_route_label": buy_route_label,
        "timestamp": now.strftime("%Y-%m-%d %H:%M:%S"),
        "market_env": market_env,
        "industry_confirm": industry_confirm,
        "push_threshold": thresholds["push_threshold"],
        "suggest_position_ratio": position_advice.get("suggest_position_ratio", 0.0),
        "suggest_position_pct": position_advice.get("suggest_position_pct", 0.0),
        "position_note": position_advice.get("position_note", ""),
        "market_gate_tier": (trade_control or {}).get("gate_tier", "normal"),
        "feedback_guard_level": (trade_control or {}).get("feedback_guard_level", "normal"),
        "circuit_state": (trade_control or {}).get("circuit_state", "normal"),
        "auto_optimized": system.enable_auto_optimization,
        "runtime_optimization_active": bool(
            system.optimization_runtime_enabled
            and optimization_profile.get("active", False)
        ),
        "runtime_optimization_reason": optimization_profile.get("reason", ""),
        "runtime_optimization_score_delta": system._to_float(
            optimization_profile.get("score_delta", 0.0),
            0.0,
        ),
        "runtime_optimization_trade_count": int(
            system._to_float(optimization_profile.get("trade_count", 0), 0)
        ),
        "feedback_adaptive_active": bool(thresholds.get("feedback_adaptive_active", False)),
        "feedback_adaptive_best_subtype": bool(
            thresholds.get("feedback_adaptive_best_subtype", False)
        ),
    }

    suggested_hold_days = system._parse_optional_float(candidate.get("suggested_hold_days"))
    holding_route = str(candidate.get("holding_route", "") or "").strip()
    if suggested_hold_days is not None and suggested_hold_days > 0:
        buy_signal["suggested_hold_days"] = float(suggested_hold_days)
    if holding_route:
        buy_signal["holding_route"] = holding_route
        signal_details = dict(buy_signal.get("signal_details", {}) or {})
        signal_details["holding_route"] = holding_route
        buy_signal["signal_details"] = signal_details

    if (
        strategy_profile == "alpha158"
        and suggested_hold_days is not None
        and suggested_hold_days > 0
        and "max_hold_hours" not in buy_signal
    ):
        buy_signal["max_hold_hours"] = float(suggested_hold_days) * 24.0

    if strategy_profile == "secondary_launch":
        replay_exit_profile = _get_secondary_launch_exit_profile(signal_subtype)
        if replay_exit_profile:
            for key, value in replay_exit_profile.items():
                if value is not None:
                    buy_signal[key] = value
            signal_details = dict(buy_signal.get("signal_details", {}) or {})
            signal_details["replay_exit_profile_applied"] = True
            signal_details["replay_exit_profile"] = {
                key: value for key, value in replay_exit_profile.items()
            }
            buy_signal["signal_details"] = signal_details

    if system.optimization_apply_to_exit_params and optimization_profile.get("active", False):
        exit_params = optimization_profile.get("exit_params", {})
        if isinstance(exit_params, dict):
            if "dynamic_stop_loss_pct" not in buy_signal:
                buy_signal["dynamic_stop_loss_pct"] = system._to_float(
                    exit_params.get("stop_loss_pct", -0.05),
                    -0.05,
                )
            if "dynamic_take_profit_pct" not in buy_signal:
                buy_signal["dynamic_take_profit_pct"] = system._to_float(
                    exit_params.get("take_profit_pct", 0.10),
                    0.10,
                )
            if "dynamic_tp1_pct" not in buy_signal:
                buy_signal["dynamic_tp1_pct"] = system._to_float(
                    exit_params.get("tp1_pct", 0.06),
                    0.06,
                )
            if "dynamic_trailing_stop_pct" not in buy_signal:
                trailing_value = system._parse_optional_float(
                    exit_params.get("trailing_stop_pct", 0.035)
                )
                if trailing_value is not None:
                    buy_signal["dynamic_trailing_stop_pct"] = float(trailing_value)
            if "max_hold_hours" not in buy_signal:
                max_hold_hours = system._parse_optional_float(exit_params.get("max_hold_hours", None))
                if max_hold_hours is not None:
                    buy_signal["max_hold_hours"] = float(max_hold_hours)

    route_override = system._get_legacy_route_exit_override(
        strategy_profile=strategy_profile,
        route_name=buy_route,
    )
    if route_override:
        buy_signal.update(route_override)
        signal_details = dict(buy_signal.get("signal_details", {}) or {})
        signal_details["legacy_exit_override_applied"] = True
        signal_details["legacy_exit_override"] = {
            key: value for key, value in route_override.items()
        }
        buy_signal["signal_details"] = signal_details

    return buy_signal
