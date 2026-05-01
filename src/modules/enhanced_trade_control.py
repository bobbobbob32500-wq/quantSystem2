"""Trade-control runtime helpers for EnhancedHybridSystem."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional

import logging

import numpy as np
import pandas as pd
from src.modules.enhanced_signal_scoring import get_feedback_adaptive_profile

try:
    from src.core.runtime_monitor import AlertSeverity, IncidentCategory

    RUNTIME_MONITOR_AVAILABLE = True
except Exception:
    AlertSeverity = None
    IncidentCategory = None
    RUNTIME_MONITOR_AVAILABLE = False

try:
    import akshare as ak

    AKSHARE_AVAILABLE = True
except Exception:
    ak = None
    AKSHARE_AVAILABLE = False

logger = logging.getLogger(__name__)


def record_monitor_incident(
    system,
    title: str,
    message: str,
    severity: str = "warning",
    component: str = "monitor.trade_control",
    context: Optional[Dict[str, Any]] = None,
):
    if not getattr(system, "runtime_monitor", None):
        return

    if not RUNTIME_MONITOR_AVAILABLE or not IncidentCategory or not AlertSeverity:
        return

    try:
        level = str(severity or "warning").lower()
        severity_map = {
            "info": AlertSeverity.INFO,
            "warning": AlertSeverity.WARNING,
            "error": AlertSeverity.ERROR,
            "critical": AlertSeverity.CRITICAL,
        }
        system.runtime_monitor.record_incident(
            exception=RuntimeError(message),
            title=title,
            component=component,
            category=IncidentCategory.MONITOR,
            severity=severity_map.get(level, AlertSeverity.WARNING),
            context=context or {},
        )
    except Exception as exc:
        logger.debug("record monitor incident failed: %s", exc)


def get_market_gate_context(system, now: Optional[datetime] = None) -> Dict[str, Any]:
    timestamp = now or datetime.now()
    normal_context = {
        "enabled": system.market_gate_enabled,
        "tier": "normal",
        "regime": "NEUTRAL",
        "risk_state": "MEDIUM",
        "target_position": 0.30,
        "position_multiplier": 1.0,
        "threshold_boost": 0.0,
        "push_boost": 0.0,
        "max_signals_per_round": max(1, int(system.market_gate_normal_max_signals_per_round)),
        "allow_new_signals": True,
        "source": "fallback",
    }

    if not system.market_gate_enabled:
        return normal_context

    cached_ts = system._market_gate_cache.get("ts")
    cached_context = system._market_gate_cache.get("context")
    if (
        cached_ts is not None
        and cached_context is not None
        and (timestamp - cached_ts).total_seconds() <= max(0, system.market_gate_refresh_seconds)
    ):
        return dict(cached_context)

    try:
        result = system.position_controller.analyze_market(end_date=timestamp.strftime("%Y%m%d"))
        regime = str(result.get("market_regime", "NEUTRAL")).upper()
        risk_state = str(result.get("risk_state", "MEDIUM")).upper()
        target_position = float(result.get("target_position", 0.30))
        defensive = (
            regime in system.market_gate_force_defensive_regimes
            or target_position < system.market_gate_open_min_target_position
        )
        context = {
            "enabled": True,
            "tier": "defensive" if defensive else "normal",
            "regime": regime,
            "risk_state": risk_state,
            "target_position": max(0.0, min(1.0, target_position)),
            "position_multiplier": (
                system.market_gate_defensive_position_multiplier if defensive else 1.0
            ),
            "threshold_boost": system.market_gate_defensive_score_boost if defensive else 0.0,
            "push_boost": system.market_gate_defensive_push_boost if defensive else 0.0,
            "max_signals_per_round": max(
                0,
                int(
                    system.market_gate_defensive_max_signals_per_round
                    if defensive
                    else system.market_gate_normal_max_signals_per_round
                ),
            ),
            "allow_new_signals": True,
            "source": "position_controller",
        }
        system._market_gate_cache["ts"] = timestamp
        system._market_gate_cache["context"] = dict(context)
        return context
    except Exception as exc:
        logger.warning("market gate fallback due to exception: %s", exc)
        system._record_monitor_incident(
            title="市场闸门降级",
            message=str(exc),
            severity="warning",
            component="monitor.market_gate",
            context={"fallback": True},
        )
        return normal_context


def get_feedback_guard_context(system, now: Optional[datetime] = None) -> Dict[str, Any]:
    timestamp = now or datetime.now()
    guard_enabled = bool(getattr(system, "feedback_guard_enabled", False))
    default_context = {
        "enabled": guard_enabled,
        "level": "normal",
        "active": False,
        "reason": "",
        "threshold_boost": 0.0,
        "push_boost": 0.0,
        "position_multiplier": 1.0,
        "max_signals_cap": None,
        "source": "disabled",
        "end_date": timestamp.strftime("%Y%m%d"),
    }
    if not guard_enabled:
        return default_context

    feedback_guard_obj = getattr(system, "feedback_guard", None)
    if feedback_guard_obj is None:
        return default_context

    cache = getattr(system, "_feedback_guard_cache", None)
    if not isinstance(cache, dict):
        cache = {"ts": None, "state": None}
        system._feedback_guard_cache = cache

    cached_ts = cache.get("ts")
    cached_state = cache.get("state")
    refresh_seconds = int(getattr(system, "feedback_guard_refresh_seconds", 300))
    if (
        cached_ts is not None
        and cached_state is not None
        and (timestamp - cached_ts).total_seconds() <= max(0, refresh_seconds)
    ):
        return dict(cached_state)

    try:
        state = feedback_guard_obj.evaluate(end_date=timestamp.strftime("%Y%m%d"))
        level = str(state.get("level", "normal")).lower()
        context = {
            "enabled": True,
            "level": level,
            "active": level in {"caution", "defensive"},
            "reason": str(state.get("reason", "")),
            "threshold_boost": 0.0,
            "push_boost": 0.0,
            "position_multiplier": 1.0,
            "max_signals_cap": None,
            "source": "feedback_guard",
            "end_date": str(state.get("end_date", timestamp.strftime("%Y%m%d"))),
            "raw_state": state,
        }
        if level == "defensive":
            context["threshold_boost"] = float(
                getattr(system, "feedback_guard_threshold_boost_defensive", 3.0)
            )
            context["push_boost"] = float(
                getattr(system, "feedback_guard_push_boost_defensive", 2.0)
            )
            context["position_multiplier"] = float(
                getattr(system, "feedback_guard_position_multiplier_defensive", 0.65)
            )
            context["max_signals_cap"] = max(
                0,
                int(getattr(system, "feedback_guard_max_signals_defensive", 2)),
            )
        elif level == "caution":
            context["threshold_boost"] = float(
                getattr(system, "feedback_guard_threshold_boost_caution", 1.5)
            )
            context["push_boost"] = float(
                getattr(system, "feedback_guard_push_boost_caution", 1.0)
            )
            context["position_multiplier"] = float(
                getattr(system, "feedback_guard_position_multiplier_caution", 0.85)
            )
            context["max_signals_cap"] = max(
                0,
                int(getattr(system, "feedback_guard_max_signals_caution", 3)),
            )

        cache["ts"] = timestamp
        cache["state"] = dict(context)
        return context
    except Exception as exc:
        logger.warning("feedback guard fallback due to exception: %s", exc)
        return default_context


def fetch_index_pct_change_map(system) -> Dict[str, float]:
    if not AKSHARE_AVAILABLE:
        return {}
    try:
        frame = ak.stock_zh_index_spot_sina()
    except Exception as exc:
        logger.debug("index spot fetch failed: %s", exc)
        return {}

    if frame is None or frame.empty:
        return {}

    code_col = next(
        (
            c
            for c in frame.columns
            if ("代码" in str(c)) or (str(c).lower() in {"code", "symbol"})
        ),
        None,
    )
    pct_col = next(
        (
            c
            for c in frame.columns
            if ("涨跌幅" in str(c)) or (str(c).lower() in {"pct_change", "changepercent"})
        ),
        None,
    )
    if not code_col or not pct_col:
        return {}

    output: Dict[str, float] = {}
    for _, row in frame.iterrows():
        code6 = system._normalize_symbol_6(row.get(code_col))
        if not code6:
            continue
        pct = pd.to_numeric(row.get(pct_col), errors="coerce")
        if pd.isna(pct):
            continue
        output[code6] = float(pct)
    return output


def compute_intraday_market_snapshot(system, quote_df: pd.DataFrame) -> Dict[str, Any]:
    returns = []
    up_count = 0
    total_count = 0

    if quote_df is not None and not quote_df.empty:
        for _, row in quote_df.iterrows():
            price = system._to_float(row.get("price"))
            pre_close = system._to_float(
                row.get("pre_close"),
                default=system._to_float(row.get("open"), default=price),
            )
            if pre_close <= 0:
                continue
            ret_pct = (price / pre_close - 1) * 100
            returns.append(ret_pct)
            total_count += 1
            if ret_pct > 0:
                up_count += 1

    breadth = (up_count / total_count) if total_count > 0 else 0.5
    avg_symbol_ret = float(np.mean(returns)) if returns else 0.0

    index_pct_map = system._fetch_index_pct_change_map()
    index_returns = []
    for code in system.circuit_index_codes:
        code6 = system._normalize_symbol_6(code)
        if not code6:
            continue
        pct = index_pct_map.get(code6)
        if pct is not None:
            index_returns.append(float(pct))

    if index_returns:
        avg_index_pct = float(np.mean(index_returns))
        source = "index_realtime"
    else:
        avg_index_pct = avg_symbol_ret
        source = "candidate_fallback"

    return {
        "avg_index_pct": round(avg_index_pct, 4),
        "avg_symbol_pct": round(avg_symbol_ret, 4),
        "breadth": round(float(breadth), 4),
        "advancers": int(up_count),
        "sample_size": int(total_count),
        "source": source,
        "index_count": int(len(index_returns)),
    }


def evaluate_circuit_breaker(
    system,
    snapshot: Dict[str, Any],
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    timestamp = now or datetime.now()
    if not system.intraday_circuit_breaker_enabled:
        return {
            "enabled": False,
            "state": "normal",
            "changed": False,
            "reason": "disabled",
        }

    avg_index_pct = float(snapshot.get("avg_index_pct", 0.0))
    breadth = float(snapshot.get("breadth", 0.5))

    target_state = "normal"
    trigger_reason = "normal"
    if (
        avg_index_pct <= system.circuit_hard_trigger_drop_pct
        or (
            avg_index_pct <= system.circuit_soft_trigger_drop_pct
            and breadth <= system.circuit_hard_breadth_threshold
        )
    ):
        target_state = "hard"
        trigger_reason = "hard_trigger"
    elif (
        avg_index_pct <= system.circuit_soft_trigger_drop_pct
        and breadth <= system.circuit_soft_breadth_threshold
    ):
        target_state = "soft"
        trigger_reason = "soft_trigger"

    current_state = str(system._circuit_breaker_state.get("state", "normal"))
    severity_rank = {"normal": 0, "soft": 1, "hard": 2}
    changed = False

    if severity_rank.get(target_state, 0) > severity_rank.get(current_state, 0):
        changed = True
        current_state = target_state
        system._circuit_breaker_state["since"] = timestamp
    elif current_state != "normal":
        since = system._circuit_breaker_state.get("since")
        held_seconds = (
            (timestamp - since).total_seconds()
            if isinstance(since, datetime)
            else system.circuit_hold_seconds
        )
        recover_ready = (
            avg_index_pct >= system.circuit_recover_drop_pct
            and breadth >= system.circuit_recover_breadth_threshold
        )
        if held_seconds >= system.circuit_hold_seconds and recover_ready:
            changed = True
            current_state = "normal"
            trigger_reason = "recover"
            system._circuit_breaker_state["since"] = None

    system._circuit_breaker_state["state"] = current_state
    if changed:
        system._circuit_breaker_state["last_change"] = timestamp
        system._circuit_breaker_state["reason"] = trigger_reason

    return {
        "enabled": True,
        "state": current_state,
        "changed": changed,
        "reason": (
            trigger_reason
            if changed
            else system._circuit_breaker_state.get("reason", trigger_reason)
        ),
        "avg_index_pct": avg_index_pct,
        "breadth": breadth,
        "source": snapshot.get("source", "unknown"),
    }


def compose_trade_control_context(
    system,
    now: Optional[datetime] = None,
    quote_df: Optional[pd.DataFrame] = None,
) -> Dict[str, Any]:
    timestamp = now or datetime.now()
    gate = system._get_market_gate_context(timestamp)
    feedback_guard = system._get_feedback_guard_context(timestamp)
    snapshot = system._compute_intraday_market_snapshot(
        quote_df if quote_df is not None else pd.DataFrame()
    )
    circuit = system._evaluate_circuit_breaker(snapshot, now=timestamp)

    circuit_state = str(circuit.get("state", "normal"))
    threshold_boost = float(gate.get("threshold_boost", 0.0))
    push_boost = float(gate.get("push_boost", 0.0))
    position_multiplier = float(gate.get("position_multiplier", 1.0))
    max_signals = int(
        gate.get("max_signals_per_round", system.market_gate_normal_max_signals_per_round)
    )

    if feedback_guard.get("active"):
        threshold_boost += float(feedback_guard.get("threshold_boost", 0.0))
        push_boost += float(feedback_guard.get("push_boost", 0.0))
        position_multiplier *= float(feedback_guard.get("position_multiplier", 1.0))
        cap = feedback_guard.get("max_signals_cap")
        if cap is not None:
            max_signals = min(max_signals, max(0, int(cap)))

    if circuit_state == "soft":
        threshold_boost += system.circuit_soft_score_boost
        push_boost += system.circuit_soft_push_boost
        position_multiplier *= system.circuit_soft_position_multiplier
        max_signals = min(max_signals, max(1, system.market_gate_defensive_max_signals_per_round))
    elif circuit_state == "hard":
        position_multiplier = 0.0
        max_signals = 0

    context = {
        "timestamp": timestamp.strftime("%Y-%m-%d %H:%M:%S"),
        "gate_tier": str(gate.get("tier", "normal")),
        "market_regime": str(gate.get("regime", "NEUTRAL")),
        "risk_state": str(gate.get("risk_state", "MEDIUM")),
        "target_position": float(gate.get("target_position", 0.30)),
        "circuit_state": circuit_state,
        "circuit_reason": str(circuit.get("reason", "normal")),
        "avg_index_pct": float(snapshot.get("avg_index_pct", 0.0)),
        "breadth": float(snapshot.get("breadth", 0.5)),
        "market_snapshot_source": str(snapshot.get("source", "unknown")),
        "threshold_boost": threshold_boost,
        "push_boost": push_boost,
        "position_multiplier": max(0.0, position_multiplier),
        "max_signals_per_round": max(0, int(max_signals)),
        "allow_new_signals": bool(gate.get("allow_new_signals", True)) and circuit_state != "hard",
        "feedback_guard_level": str(feedback_guard.get("level", "normal")),
        "feedback_guard_active": bool(feedback_guard.get("active", False)),
        "feedback_guard_reason": str(feedback_guard.get("reason", "")),
    }
    system.latest_trade_control_context = dict(context)
    system._maybe_emit_trade_control_alert(
        context=context,
        circuit_changed=bool(circuit.get("changed")),
    )
    return context


def maybe_emit_trade_control_alert(
    system,
    context: Dict[str, Any],
    circuit_changed: bool = False,
):
    key = (
        str(context.get("gate_tier", "normal")),
        str(context.get("circuit_state", "normal")),
        str(context.get("market_regime", "NEUTRAL")),
        str(context.get("feedback_guard_level", "normal")),
    )
    if key == system._last_trade_control_snapshot and not circuit_changed:
        return
    system._last_trade_control_snapshot = key

    now = datetime.now()
    if system._last_trade_control_alert_at is not None:
        elapsed = (now - system._last_trade_control_alert_at).total_seconds()
        if elapsed < system.trade_control_alert_cooldown_seconds and not circuit_changed:
            return

    gate_tier = str(context.get("gate_tier", "normal"))
    circuit_state = str(context.get("circuit_state", "normal"))
    feedback_guard_level = str(context.get("feedback_guard_level", "normal"))
    avg_index_pct = _safe_float(context.get("avg_index_pct", 0.0))
    breadth = _safe_float(context.get("breadth", 0.5))
    reason = (
        f"闸门={gate_tier}, 闭环闸门={feedback_guard_level}, 熔断={circuit_state}, 指数均值={avg_index_pct:+.2f}%, "
        f"市场广度={breadth*100:.1f}%"
    )

    if circuit_state == "hard":
        logger.warning("盘中熔断(HARD)触发: %s", reason)
        system._record_monitor_incident(
            title="盘中熔断触发(HARD)",
            message=reason,
            severity="error",
            component="monitor.circuit_breaker",
            context={"state": "hard"},
        )
    elif circuit_state == "soft":
        logger.warning("盘中熔断(SOFT)触发: %s", reason)
        system._record_monitor_incident(
            title="盘中熔断触发(SOFT)",
            message=reason,
            severity="warning",
            component="monitor.circuit_breaker",
            context={"state": "soft"},
        )
    elif gate_tier == "defensive":
        logger.info("市场闸门进入防守档: %s", reason)
    else:
        logger.info("市场防护恢复常态: %s", reason)

    if system.push_enabled and getattr(system.message_pusher, "enabled", False):
        icon = "🔴" if circuit_state == "hard" else "🟠" if circuit_state == "soft" else "🟢"
        content = (
            "## 市场防护状态更新\n"
            f"**状态**: {icon} 闸门 `{gate_tier}` / 闭环闸门 `{feedback_guard_level}` / 熔断 `{circuit_state}`\n"
            f"**市场**: 指数均值 `{avg_index_pct:+.2f}%` | 广度 `{breadth*100:.1f}%`\n"
            f"**仓位联动**: 目标仓位 `{float(context.get('target_position', 0.0))*100:.0f}%` × 系数 `{float(context.get('position_multiplier', 1.0)):.2f}`\n"
            f"**说明**: {context.get('circuit_reason', 'normal')}"
        )
        try:
            system.message_pusher.push_markdown(content)
        except Exception as exc:
            logger.warning("trade control alert push failed: %s", exc)

    system._last_trade_control_alert_at = now


def _safe_float(v, default=0.0):
    try:
        f = float(v)
        import math
        if math.isnan(f) or math.isinf(f):
            return float(default)
        return f
    except (TypeError, ValueError):
        return float(default)


def report_trade_control_status(
    system,
    context: Dict[str, Any],
    now: Optional[datetime] = None,
):
    timestamp = now or datetime.now()
    if system._last_trade_control_status_print_at is not None:
        elapsed = (timestamp - system._last_trade_control_status_print_at).total_seconds()
        if elapsed < system.trade_control_status_print_interval_seconds:
            return
    system._last_trade_control_status_print_at = timestamp
    print(
        "[防护] 闸门=%s 闭环闸门=%s 熔断=%s 指数均值=%+.2f%% 广度=%.1f%% 目标仓位=%.0f%% 系数=%.2f"
        % (
            context.get("gate_tier", "normal"),
            context.get("feedback_guard_level", "normal"),
            context.get("circuit_state", "normal"),
            _safe_float(context.get("avg_index_pct", 0.0)),
            _safe_float(context.get("breadth", 0.5)) * 100.0,
            _safe_float(context.get("target_position", 0.0)) * 100.0,
            _safe_float(context.get("position_multiplier", 1.0)),
        )
    )


def build_position_advice(
    system,
    candidate: Dict[str, Any],
    total_score: float,
    trade_control: Optional[Dict[str, Any]],
    strategy_profile: str = "",
    signal_subtype: str = "",
) -> Dict[str, Any]:
    if not system.position_linkage_enabled:
        return {
            "suggest_position_ratio": 0.0,
            "suggest_position_pct": 0.0,
            "position_note": "position_linkage_disabled",
        }

    control = trade_control or {}
    if not control.get("allow_new_signals", True):
        return {
            "suggest_position_ratio": 0.0,
            "suggest_position_pct": 0.0,
            "position_note": "hard_circuit_blocked",
        }

    base_target = float(control.get("target_position", 0.30))
    control_multiplier = float(control.get("position_multiplier", 1.0))
    pool_factor = 1.0 if candidate.get("pool_type") == "core" else 0.75
    score_factor = max(0.75, min(1.10, float(total_score) / 85.0))
    adaptive_profile = get_feedback_adaptive_profile(
        system=system,
        strategy_profile=strategy_profile,
        signal_subtype=signal_subtype,
    )
    adaptive_multiplier = float(adaptive_profile.get("position_multiplier", 1.0) or 1.0)

    ratio = base_target * control_multiplier * pool_factor * score_factor * adaptive_multiplier
    ratio = min(ratio, system.position_linkage_per_signal_cap)
    ratio = max(0.0, ratio)
    if ratio > 0:
        ratio = max(ratio, system.position_linkage_min_ratio)
    ratio = min(ratio, 1.0)

    note = (
        f"base={base_target:.2f},control={control_multiplier:.2f},"
        f"pool={pool_factor:.2f},score={score_factor:.2f},adaptive={adaptive_multiplier:.2f}"
    )
    adaptive_note = str(adaptive_profile.get("position_note", "") or "").strip()
    if adaptive_note:
        note = f"{note},{adaptive_note}"
    return {
        "suggest_position_ratio": round(ratio, 4),
        "suggest_position_pct": round(ratio * 100.0, 2),
        "position_note": note,
    }
