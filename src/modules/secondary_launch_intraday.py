# -*- coding: utf-8 -*-
"""
二次启动策略盘中买点检测。
"""

from __future__ import annotations

from datetime import datetime, time
from typing import Any, Dict, Optional, Tuple

import numpy as np
import pandas as pd

from src.modules.optimized_buy_signals import SignalOutput


BLOCKER_LABELS = {
    "near_high_supply": "前高抛压",
    "afternoon_threshold": "午后阈值",
    "market_gate_weak": "市场偏弱闸门",
    "industry_blocked": "行业共振不足",
    "daily_profile_gate": "日线形态过滤",
    "pre_window": "过早触发",
    "late_window": "过晚触发",
    "below_threshold": "确认阈值未达",
    "breakout_not_ready": "突破形态未完成",
    "no_setup": "全天无有效形态",
    "missing_minute_data": "缺少分钟数据",
    "unclassified": "未分类阻断",
}


def blocker_tag_to_label(tag: Any) -> str:
    text = str(tag or "").strip()
    if not text:
        return ""
    return BLOCKER_LABELS.get(text, text)


def _resolve_market_gate(market_confirm: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    payload = market_confirm or {}
    raw_score = payload.get("market_score", payload.get("score", 50.0))
    try:
        market_score = float(raw_score or 50.0)
    except (TypeError, ValueError):
        market_score = 50.0
    trend = str(payload.get("trend", payload.get("level", "neutral")) or "neutral").lower()
    index_below_vwap = bool(payload.get("index_below_vwap", False))
    weak_market = (
        market_score < 45.0
        or trend in {"down", "weak", "poor", "defensive", "bear"}
        or index_below_vwap
    )
    return {
        "market_score": market_score,
        "trend": trend,
        "index_below_vwap": index_below_vwap,
        "weak_market": weak_market,
        "label": "偏弱" if weak_market else "正常",
    }


def _resolve_breakout_threshold(now: datetime, market_gate: Dict[str, Any]) -> float:
    threshold = 0.68 if now.time() >= time(13, 30) else 0.60
    if market_gate.get("weak_market"):
        threshold += 0.05
    return threshold


def _resolve_series(df: pd.DataFrame, *candidates: str) -> Optional[pd.Series]:
    for name in candidates:
        if name in df.columns:
            return pd.to_numeric(df[name], errors="coerce")
    return None


def _resolve_timestamp_series(df: pd.DataFrame) -> pd.Series:
    for name in ("timestamp", "datetime", "time", "trade_time"):
        if name in df.columns:
            return pd.to_datetime(df[name], errors="coerce")
    return pd.Series(pd.NaT, index=df.index)


def _prepare_minute_frame(minute_df: Optional[pd.DataFrame]) -> pd.DataFrame:
    if minute_df is None or minute_df.empty:
        return pd.DataFrame()

    df = minute_df.copy()
    price = _resolve_series(df, "close", "price", "last")
    high = _resolve_series(df, "high")
    low = _resolve_series(df, "low")
    open_ = _resolve_series(df, "open")
    volume = _resolve_series(df, "volume", "vol")
    ts = _resolve_timestamp_series(df)

    prepared = pd.DataFrame(
        {
            "timestamp": ts,
            "open": open_ if open_ is not None else price,
            "high": high if high is not None else price,
            "low": low if low is not None else price,
            "close": price,
            "volume": volume if volume is not None else 0.0,
        }
    ).dropna(subset=["close"])
    if prepared.empty:
        return prepared

    prepared = prepared.ffill().bfill()
    prepared = prepared.sort_values("timestamp").reset_index(drop=True)
    prepared["vwap"] = (
        (prepared["close"] * prepared["volume"]).cumsum()
        / prepared["volume"].replace(0, np.nan).cumsum()
    ).fillna(prepared["close"])
    return prepared


def _build_pullback_signal(
    prepared: pd.DataFrame,
    candidate: Dict[str, Any],
    quote: Dict[str, float],
    now: datetime,
) -> SignalOutput:
    if len(prepared) < 8:
        return SignalOutput(False, "", 0.0, "分钟数据不足", details={"route_blocked": True})

    recent = prepared.tail(6).reset_index(drop=True)
    current_price = float(recent.iloc[-1]["close"])
    current_vwap = float(recent.iloc[-1]["vwap"])
    session_open = float(prepared.iloc[0]["open"])
    recent_low = float(recent["low"].min())
    prior_high = float(prepared.iloc[:-1]["high"].tail(20).max()) if len(prepared) > 1 else current_price
    recent_avg_vol = float(recent["volume"].tail(3).mean())
    prev_avg_vol = float(prepared["volume"].tail(12).head(9).mean()) if len(prepared) >= 12 else recent_avg_vol
    volume_ratio = (recent_avg_vol / prev_avg_vol) if prev_avg_vol > 0 else 1.0

    support_price = max(current_vwap, session_open)
    price_support_ratio = current_price / support_price if support_price > 0 else 1.0
    low_support_ratio = recent_low / support_price if support_price > 0 else 1.0

    # 三层支撑判定：严格 / 宽松 / 深回踩
    support_strict = price_support_ratio >= 0.999 and low_support_ratio >= 0.996
    support_loose = price_support_ratio >= 0.985 and low_support_ratio >= 0.970
    support_deep = price_support_ratio >= 0.970 and low_support_ratio >= 0.950

    rebound_strong = current_price >= float(recent.iloc[-2]["close"]) and current_price >= recent["close"].min() * 1.005
    rebound_mild = current_price >= float(recent.iloc[-2]["close"]) and current_price >= recent["close"].min() * 1.002
    not_far_from_break = prior_high <= 0 or current_price >= prior_high * 0.980
    volume_ok_strict = 0.6 <= volume_ratio <= 1.35
    volume_ok_loose = 0.35 <= volume_ratio <= 1.50

    # 加权置信度：允许单条件降级但需要总分达标
    confidence = 0.0

    if support_strict:
        confidence += 0.35
    elif support_loose:
        confidence += 0.22
    elif support_deep:
        confidence += 0.10

    if rebound_strong:
        confidence += 0.25
    elif rebound_mild:
        confidence += 0.15

    if not_far_from_break:
        confidence += 0.20

    if volume_ok_strict:
        confidence += 0.20
    elif volume_ok_loose:
        confidence += 0.10

    # 触发条件：总置信度 >= 0.60 且无硬性否决
    hard_reject = (
        price_support_ratio < 0.970
        or low_support_ratio < 0.950
        or (not rebound_mild)
        or (not not_far_from_break)
        or (not volume_ok_loose)
    )
    signal = (not hard_reject) and confidence >= 0.60

    details = {
        "buy_template_source": "secondary_launch_pullback_v2",
        "buy_route": "secondary_launch_pullback",
        "signal_subtype": "secondary_launch_pullback",
        "buy_route_label": "二次启动回踩确认",
        "entry_trigger": "回踩不破VWAP/开盘价后回拉",
        "support_price": round(float(support_price), 3),
        "reference_breakout_price": round(float(prior_high), 3),
        "trigger_price": round(float(current_price), 3),
        "volume_ratio": round(float(volume_ratio), 3),
        "price_support_ratio": round(float(price_support_ratio), 5),
        "low_support_ratio": round(float(low_support_ratio), 5),
        "invalid_below": round(float(min(recent_low, support_price * 0.948)), 3),
        "expiry_hint": "30分钟内若持续弱于VWAP则失效",
        "strategy_profile": "secondary_launch",
    }
    return SignalOutput(
        signal=signal,
        signal_type="secondary_launch_pullback",
        confidence=confidence,
        reason="二次启动回踩确认" if signal else "二次启动回踩条件未满足",
        details=details,
    )


def _build_breakout_signal(
    prepared: pd.DataFrame,
    candidate: Dict[str, Any],
    quote: Dict[str, float],
    now: datetime,
    market_confirm: Optional[Dict[str, Any]] = None,
) -> SignalOutput:
    if len(prepared) < 15:
        return SignalOutput(False, "", 0.0, "分钟数据不足", details={"route_blocked": True})

    current_price = float(prepared.iloc[-1]["close"])
    current_volume = float(prepared.iloc[-1]["volume"])
    current_vwap = float(prepared.iloc[-1]["vwap"])
    recent_window = prepared.tail(15).iloc[:-1]
    breakout_price = float(recent_window["high"].max())
    consolidation_low = float(recent_window["low"].min())
    range_pct = (breakout_price - consolidation_low) / consolidation_low if consolidation_low > 0 else 0.0
    avg_volume = float(recent_window["volume"].tail(5).mean())
    volume_ratio = (current_volume / avg_volume) if avg_volume > 0 else 0.0
    recent_high = float(prepared["high"].tail(30).max())
    distance_to_recent_high = max(0.0, recent_high / current_price - 1.0) if current_price > 0 else 0.0
    market_gate = _resolve_market_gate(market_confirm)
    afternoon_breakout = now.time() >= time(13, 30)
    # 实盘约束：午后首次突破与弱市共振均需要更严格的放量确认。
    # 约定：
    # - 午后（13:30后）首次突破：最低放量阈值提升到 1.6
    # - 弱市共振偏弱：最低放量阈值提升到 1.6
    # 二者取更严格者（避免“既午后又弱市”时阈值被重复叠加过度抬高）。
    required_volume_ratio = 1.6 if afternoon_breakout else 1.2
    if market_gate.get("weak_market"):
        required_volume_ratio = max(required_volume_ratio, 1.6)
    breakout = current_price > breakout_price * 1.002
    hold_above = all(prepared["close"].tail(3) >= breakout_price * 0.998)
    vwap_support = current_price >= current_vwap * 1.001
    compact_platform = range_pct <= 0.020
    recent_closes = prepared["close"].tail(3).reset_index(drop=True)
    recent_lows = prepared["low"].tail(3)
    follow_through = int((recent_closes.diff() > 0).sum()) >= 2 and float(recent_lows.min()) >= breakout_price * 0.997
    volume_ok = volume_ratio >= required_volume_ratio
    near_high_supply_veto = distance_to_recent_high <= 0.015 and volume_ratio < 1.5

    signal = (
        breakout
        and hold_above
        and vwap_support
        and compact_platform
        and volume_ok
        and follow_through
        and not near_high_supply_veto
    )
    confidence = 0.0
    confidence += 0.30 if breakout else 0.0
    confidence += 0.20 if hold_above else 0.0
    confidence += 0.20 if vwap_support else 0.0
    confidence += 0.15 if compact_platform else 0.0
    confidence += 0.10 if volume_ok else 0.0
    confidence += 0.05 if follow_through else 0.0

    details = {
        "buy_template_source": "secondary_launch_breakout_v1",
        "buy_route": "secondary_launch_breakout",
        "signal_subtype": "secondary_launch_breakout",
        "buy_route_label": "二次启动平台突破",
        "entry_trigger": "平台上沿放量突破并站稳",
        "breakout_price": round(float(breakout_price), 3),
        "platform_low": round(float(consolidation_low), 3),
        "trigger_price": round(float(current_price), 3),
        "volume_ratio": round(float(volume_ratio), 3),
        "required_volume_ratio": round(float(required_volume_ratio), 3),
        "platform_range_pct": round(float(range_pct * 100), 2),
        "follow_through": bool(follow_through),
        "distance_to_recent_high_pct": round(float(distance_to_recent_high * 100), 2),
        "near_high_supply_veto": bool(near_high_supply_veto),
        "afternoon_breakout_tightened": bool(afternoon_breakout),
        "market_gate_tightened": bool(market_gate.get("weak_market")),
        "market_score": round(float(market_gate.get("market_score", 50.0)), 1),
        "market_trend": str(market_gate.get("trend", "neutral")),
        "invalid_below": round(float(max(current_vwap, breakout_price * 0.995)), 3),
        "expiry_hint": "若3根分钟线内跌回平台则失效",
        "strategy_profile": "secondary_launch",
    }
    if near_high_supply_veto:
        reason = "前高抛压过近且量能不足，突破信号否决"
        details["blocker_tag"] = "near_high_supply"
        details["blocker_detail"] = "距离近30分钟前高过近，但量能未明显放大"
    elif afternoon_breakout and not volume_ok:
        reason = "午后首次突破阈值更高，当前量能不足"
        details["blocker_tag"] = "afternoon_threshold"
        details["blocker_detail"] = "13:30后首次突破需要更高放量确认"
    elif market_gate.get("weak_market") and not volume_ok:
        reason = "市场共振偏弱，突破量能未达提高阈值"
        details["blocker_tag"] = "market_gate_weak"
        details["blocker_detail"] = "指数分时偏弱，二次启动突破量能要求已抬高"
    else:
        reason = "二次启动平台突破" if signal else "二次启动突破条件未满足"
        if not signal:
            details["blocker_tag"] = "breakout_not_ready"
            details["blocker_detail"] = "平台突破形态或量价延续尚未形成"
    return SignalOutput(
        signal=signal,
        signal_type="secondary_launch_breakout",
        confidence=confidence,
        reason=reason,
        details=details,
    )


def _check_daily_profile_gate(candidate: Dict[str, Any]) -> Optional[SignalOutput]:
    """日线特征过滤闸门：拦截高亏损概率的日线形态。

    过滤规则（基于 144 条回测数据反推）：
    - 信号日跌幅在 [-5%, -3%) 区间：胜率仅 21.4%
    - 上影线比例 > 60%：大长上影线，次日反转概率高
    - 日线量比(5日) > 1.3：异常放量通常是见顶信号
    三者取 OR，任一命中即拦截。
    """
    pct_chg = candidate.get("pct_chg")
    if pct_chg is not None:
        try:
            pct_chg = float(pct_chg)
        except (TypeError, ValueError):
            pct_chg = None

    upper_shadow_pct = candidate.get("upper_shadow_pct")
    if upper_shadow_pct is None:
        h = candidate.get("high")
        c = candidate.get("close")
        o = candidate.get("open")
        l = candidate.get("low")
        if h is not None and c is not None and o is not None and l is not None:
            try:
                h, c, o, l = float(h), float(c), float(o), float(l)
                total_range = h - l
                if total_range > 0:
                    upper_shadow_pct = (h - max(c, o)) / total_range * 100
            except (TypeError, ValueError):
                pass
    else:
        try:
            upper_shadow_pct = float(upper_shadow_pct)
        except (TypeError, ValueError):
            upper_shadow_pct = None

    vol_ratio_5 = candidate.get("vol_ratio_5")
    if vol_ratio_5 is None:
        vol = candidate.get("vol") or candidate.get("volume")
        vol_ma5 = candidate.get("vol_ma5")
        if vol is not None and vol_ma5 is not None:
            try:
                vol, vol_ma5 = float(vol), float(vol_ma5)
                if vol_ma5 > 0:
                    vol_ratio_5 = vol / vol_ma5
            except (TypeError, ValueError):
                pass
    else:
        try:
            vol_ratio_5 = float(vol_ratio_5)
        except (TypeError, ValueError):
            vol_ratio_5 = None

    blocked_reasons = []
    if pct_chg is not None and -5.0 <= pct_chg < -3.0:
        blocked_reasons.append(f"信号日跌幅{pct_chg:.1f}%处于[-5%,-3%)高危区间")
    if upper_shadow_pct is not None and upper_shadow_pct > 60.0:
        blocked_reasons.append(f"上影线比例{upper_shadow_pct:.0f}%过长")
    if vol_ratio_5 is not None and vol_ratio_5 > 1.3:
        blocked_reasons.append(f"量比{vol_ratio_5:.2f}异常放量")

    if blocked_reasons:
        reason = "日线形态过滤: " + "; ".join(blocked_reasons)
        return SignalOutput(
            signal=False,
            signal_type="",
            confidence=0.0,
            reason=reason,
            details={
                "route_blocked": True,
                "blocker_tag": "daily_profile_gate",
                "blocker_detail": reason,
                "pct_chg": pct_chg,
                "upper_shadow_pct": round(upper_shadow_pct, 1) if upper_shadow_pct is not None else None,
                "vol_ratio_5": round(vol_ratio_5, 3) if vol_ratio_5 is not None else None,
            },
        )
    return None


def _resolve_execution_tier(candidate: Dict[str, Any]) -> Tuple[str, str]:
    """根据日线强弱把候选划分为直通层/确认层。"""
    # 分层阈值：默认与全量寻优结果对齐（2026-04-15 secondary_launch_layered_threshold_opt_20260415_033344）
    # 允许上游在 candidate 中注入覆盖值，避免多处硬编码漂移。
    direct_score_min = float(candidate.get("direct_score_min", 76.0) or 76.0)
    direct_lgb_min = float(candidate.get("direct_lgb_min", 0.58) or 0.58)
    semi_score_min = float(candidate.get("semi_score_min", 70.0) or 70.0)
    semi_lgb_min = float(candidate.get("semi_lgb_min", 0.55) or 0.55)

    rank_raw = candidate.get("rank", 99)
    score_raw = candidate.get("score", candidate.get("signal_score", 0.0))
    lgb_raw = candidate.get("lgb_prob")
    try:
        rank = int(rank_raw)
    except (TypeError, ValueError):
        rank = 99
    try:
        score = float(score_raw or 0.0)
    except (TypeError, ValueError):
        score = 0.0
    try:
        lgb_prob = float(lgb_raw) if lgb_raw is not None else None
    except (TypeError, ValueError):
        lgb_prob = None

    if rank == 1 and score >= direct_score_min and (lgb_prob is None or lgb_prob >= direct_lgb_min):
        return "direct", "A层强票：允许弱确认先执行"
    if rank == 1 and score >= semi_score_min and (lgb_prob is None or lgb_prob >= semi_lgb_min):
        return "semi", "A层次强票：弱确认后执行"
    return "confirm", "B层候选：必须强确认后执行"


def _build_layered_execution_signal(
    prepared: pd.DataFrame,
    candidate: Dict[str, Any],
    quote: Dict[str, float],
    now: datetime,
    industry_confirm: Optional[Dict[str, Any]] = None,
    market_confirm: Optional[Dict[str, Any]] = None,
) -> SignalOutput:
    """分层确认 + 双通道执行。"""
    market_gate = _resolve_market_gate(market_confirm)
    industry_info = industry_confirm or {}
    industry_score = float(industry_info.get("score", 50.0) or 50.0)
    industry_level = str(industry_info.get("level", "neutral") or "neutral")
    industry_blocked = industry_score < 45.0 or industry_level in {"weak", "poor"}

    pullback_signal = _build_pullback_signal(prepared, candidate, quote, now)
    breakout_signal = _build_breakout_signal(prepared, candidate, quote, now, market_confirm=market_confirm)
    execution_tier, execution_note = _resolve_execution_tier(candidate)

    best_signal = pullback_signal if float(pullback_signal.confidence or 0.0) >= float(breakout_signal.confidence or 0.0) else breakout_signal
    best_signal.details = dict(best_signal.details or {})
    best_signal.details["industry_score"] = round(industry_score, 1)
    best_signal.details["industry_level"] = industry_level
    best_signal.details["market_score"] = round(float(market_gate.get("market_score", 50.0)), 1)
    best_signal.details["market_trend"] = str(market_gate.get("trend", "neutral"))
    best_signal.details["execution_tier"] = execution_tier
    best_signal.details["execution_note"] = execution_note

    if industry_blocked:
        best_signal.signal = False
        best_signal.reason = "行业共振不足，分层执行失效"
        best_signal.details["route_blocked"] = True
        best_signal.details["blocker_tag"] = "industry_blocked"
        best_signal.details["blocker_detail"] = "行业分时强度不足"
        return best_signal

    if execution_tier == "direct":
        direct_conf_min = float(candidate.get("direct_conf_min", 0.45) or 0.45)
        direct_ok = (
            now.time() >= time(9, 40)
            and float(best_signal.confidence or 0.0) >= direct_conf_min
            and not bool(best_signal.details.get("route_blocked", False))
            and not market_gate.get("weak_market")
        )
        best_signal.signal = bool(direct_ok)
        best_signal.reason = "A层强票弱确认直通" if direct_ok else "A层强票直通条件未满足"
        best_signal.details["entry_trigger"] = "A层强票弱确认先执行"
        best_signal.details["buy_route"] = "secondary_launch_direct"
        best_signal.details["buy_route_label"] = "二次启动A层直通"
        best_signal.details["confidence_threshold"] = direct_conf_min
        if not direct_ok:
            best_signal.details["blocker_tag"] = "below_threshold"
            best_signal.details["blocker_detail"] = "A层直通弱确认阈值未满足或市场偏弱"
        return best_signal

    if execution_tier == "semi":
        semi_conf_min = float(candidate.get("semi_conf_min", 0.58) or 0.58)
        semi_ok = (
            now.time() >= time(9, 40)
            and float(best_signal.confidence or 0.0) >= semi_conf_min
            and not bool(best_signal.details.get("route_blocked", False))
        )
        best_signal.signal = bool(semi_ok)
        best_signal.reason = "A层次强票弱确认通过" if semi_ok else "A层次强票待进一步确认"
        best_signal.details["entry_trigger"] = "A层次强票弱确认后执行"
        best_signal.details["buy_route"] = "secondary_launch_semi_confirm"
        best_signal.details["buy_route_label"] = "二次启动A层弱确认"
        best_signal.details["confidence_threshold"] = semi_conf_min
        if not semi_ok:
            best_signal.details["blocker_tag"] = "below_threshold"
            best_signal.details["blocker_detail"] = "A层弱确认阈值未满足"
        return best_signal

    breakout_threshold = _resolve_breakout_threshold(now, market_gate)
    confirm_ok = bool(
        (pullback_signal.signal and float(pullback_signal.confidence or 0.0) >= 0.60)
        or (breakout_signal.signal and float(breakout_signal.confidence or 0.0) >= breakout_threshold)
    )
    chosen = pullback_signal if float(pullback_signal.confidence or 0.0) >= float(breakout_signal.confidence or 0.0) else breakout_signal
    chosen.details = dict(chosen.details or {})
    chosen.details["industry_score"] = round(industry_score, 1)
    chosen.details["industry_level"] = industry_level
    chosen.details["market_score"] = round(float(market_gate.get("market_score", 50.0)), 1)
    chosen.details["market_trend"] = str(market_gate.get("trend", "neutral"))
    chosen.details["execution_tier"] = execution_tier
    chosen.details["execution_note"] = execution_note
    chosen.details["confidence_threshold"] = 0.60 if chosen.signal_type == "secondary_launch_pullback" else round(float(breakout_threshold), 2)
    if confirm_ok:
        chosen.reason = "B层强确认通过"
    else:
        chosen.reason = "B层候选待强确认"
        chosen.details.setdefault("blocker_tag", "below_threshold")
        chosen.details.setdefault("blocker_detail", "B层候选尚未满足强确认条件")
    chosen.signal = confirm_ok
    return chosen


def detect_secondary_launch_signal(
    candidate: Dict[str, Any],
    quote: Dict[str, float],
    now: datetime,
    minute_df: Optional[pd.DataFrame],
    industry_confirm: Optional[Dict[str, Any]] = None,
    market_confirm: Optional[Dict[str, Any]] = None,
) -> SignalOutput:
    """二次启动盘中专用路由：分层确认 + 双通道执行。"""
    if now.time() < time(9, 35) or now.time() > time(14, 20):
        return SignalOutput(False, "", 0.0, "非二次启动监控窗口", details={"route_blocked": True})

    daily_gate = _check_daily_profile_gate(candidate)
    if daily_gate is not None:
        return daily_gate

    prepared = _prepare_minute_frame(minute_df)
    if prepared.empty:
        return SignalOutput(False, "", 0.0, "缺少有效分钟数据", details={"route_blocked": True})

    return _build_layered_execution_signal(
        prepared=prepared,
        candidate=candidate,
        quote=quote,
        now=now,
        industry_confirm=industry_confirm,
        market_confirm=market_confirm,
    )


def explain_secondary_launch_blocked(
    candidate: Dict[str, Any],
    minute_df: Optional[pd.DataFrame],
    industry_confirm: Optional[Dict[str, Any]] = None,
    market_confirm: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """解释整日未触发时的主阻断原因，供复盘与看板展示。"""
    prepared = _prepare_minute_frame(minute_df)
    result = {
        "reason": "全天未形成二次启动买点",
        "blocker_tag": "no_setup",
        "blocker_detail": "全天未形成有效回踩确认或平台突破",
        "trigger_time": "",
        "signal_type": "",
        "execution_tier": "",
        "execution_note": "",
        "confidence": 0.0,
    }
    if prepared.empty or "timestamp" not in prepared.columns:
        result["reason"] = "缺少当日分钟数据"
        result["blocker_tag"] = "missing_minute_data"
        result["blocker_detail"] = "无法回放盘中分钟走势"
        return result

    earliest_signal_time = None
    latest_signal_time = None
    earliest_signal_type = ""
    latest_signal_type = ""

    for idx in range(len(prepared)):
        frame = prepared.iloc[: idx + 1].copy()
        ts = pd.Timestamp(frame.iloc[-1]["timestamp"])
        if pd.isna(ts):
            continue
        now = ts.to_pydatetime()
        current_price = float(frame.iloc[-1]["close"])
        layered_signal = _build_layered_execution_signal(
            prepared=frame,
            candidate=candidate,
            quote={"price": current_price},
            now=now,
            industry_confirm=industry_confirm,
            market_confirm=market_confirm,
        )

        signal_type = ""
        confidence = 0.0
        if layered_signal.signal:
            signal_type = str(layered_signal.signal_type or "")
            confidence = float(layered_signal.confidence or 0.0)

        if signal_type:
            if earliest_signal_time is None:
                earliest_signal_time = now
                earliest_signal_type = signal_type
                result["execution_tier"] = str(layered_signal.details.get("execution_tier", "") or "")
                result["execution_note"] = str(layered_signal.details.get("execution_note", "") or "")
            latest_signal_time = now
            latest_signal_type = signal_type
            result["confidence"] = round(max(float(result["confidence"]), confidence), 4)

    if earliest_signal_time is None:
        last_ts = pd.Timestamp(prepared.iloc[-1]["timestamp"]).to_pydatetime()
        last_price = float(prepared.iloc[-1]["close"])
        last_signal = detect_secondary_launch_signal(
            candidate=candidate,
            quote={"price": last_price},
            now=last_ts,
            minute_df=prepared,
            industry_confirm=industry_confirm,
            market_confirm=market_confirm,
        )
        details = dict(last_signal.details or {})
        result["confidence"] = round(float(last_signal.confidence or 0.0), 4)
        result["reason"] = str(last_signal.reason or result["reason"])
        result["blocker_tag"] = str(details.get("blocker_tag") or result["blocker_tag"])
        result["blocker_detail"] = str(details.get("blocker_detail") or result["blocker_detail"])
        return result

    if earliest_signal_time.time() < time(9, 35):
        result["trigger_time"] = earliest_signal_time.strftime("%H:%M:%S")
        result["signal_type"] = earliest_signal_type
        result["reason"] = "早盘过早触发（09:45前）"
        result["blocker_tag"] = "pre_window"
        result["blocker_detail"] = "触发时间早于09:35监控窗口"
        return result

    if latest_signal_time and latest_signal_time.time() > time(14, 20):
        result["trigger_time"] = latest_signal_time.strftime("%H:%M:%S")
        result["signal_type"] = latest_signal_type
        result["reason"] = "尾盘过晚触发（14:20后）"
        result["blocker_tag"] = "late_window"
        result["blocker_detail"] = "触发时间晚于允许监控窗口"
        return result

    result["reason"] = "监控窗口内未达到推送阈值"
    result["blocker_tag"] = "below_threshold"
    result["blocker_detail"] = "形态曾接近触发，但未满足最终确认阈值"
    return result
