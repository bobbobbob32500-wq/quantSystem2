# -*- coding: utf-8 -*-
"""
增强系统监控主链协调层。
把实时分钟数据、买点路由和盘中监控协调逻辑从主系统类中拆出。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

import pandas as pd

from src.core.logger import get_logger
from src.modules.optimized_buy_signals import IntradayData, SignalOutput
from src.modules.secondary_launch_intraday import detect_secondary_launch_signal

logger = get_logger("enhanced_monitor_runtime")


def detect_confirmation_signal(
    system,
    candidate: Dict[str, Any],
    quote: Dict[str, float],
    now: datetime,
    minute_map: Optional[Dict[str, pd.DataFrame]],
    market_env: Dict[str, Any],
    template_source: str,
    route_name: str,
    route_label: str,
    breakout_intraday_param_key: str = "breakout",
) -> SignalOutput:
    symbol = str(candidate.get("symbol", ""))
    intraday_data = system._get_intraday_data_for_signal(
        symbol=symbol,
        current_price=system._to_float(quote.get("price")),
        current_volume=system._to_float(quote.get("volume")),
        high=system._to_float(quote.get("high"), default=system._to_float(quote.get("price"))),
        low=system._to_float(quote.get("low"), default=system._to_float(quote.get("price"))),
        minute_map=minute_map,
    )
    if intraday_data is None:
        return system._build_false_signal(
            strategy_profile=system._resolve_candidate_strategy_profile(candidate),
            template_source=template_source,
            route_name=route_name,
            route_label=route_label,
            reason="缺少真实分钟数据，跳过执行信号",
            debounce_window=1,
            route_blocked=True,
            extra_details={
                "data_source": "missing_realtime_minute",
                "symbol": symbol,
            },
        )
    signal = system.signal_detector.mutual_exclusive_signal(
        intraday_data,
        now,
        open_pct=system._calc_open_pct(
            system._to_float(quote.get("open"), default=system._to_float(quote.get("price"))),
            system._to_float(quote.get("pre_close"), default=system._to_float(quote.get("open"))),
        ),
        market_score=market_env.get("market_score", 50.0),
        breakout_intraday_param_key=breakout_intraday_param_key,
    )
    wrapped = system._wrap_signal_metadata(
        signal=signal,
        strategy_profile=system._resolve_candidate_strategy_profile(candidate),
        template_source=template_source,
        route_name=route_name,
        route_label=route_label,
        debounce_window=int(system.config.get("debounce_window", 2)),
    )
    source = "unknown"
    source_state = getattr(system, "_last_intraday_source", None)
    if isinstance(source_state, dict):
        source = str(source_state.get(symbol, "unknown"))
    details = wrapped.details if isinstance(wrapped.details, dict) else {}
    details["data_source"] = source
    if source == "quote_fallback":
        details["degraded_mode"] = True
        details["degraded_reason"] = "minute_unavailable_quote_fallback"
        if wrapped.signal:
            wrapped.confidence = max(0.0, min(1.0, float(wrapped.confidence) * 0.92))
    wrapped.details = details
    return wrapped


def resolve_strategy_routed_signal(
    system,
    candidate: Dict[str, Any],
    quote: Dict[str, float],
    now: datetime,
    minute_map: Optional[Dict[str, pd.DataFrame]],
    market_env: Dict[str, Any],
) -> SignalOutput:
    strategy_profile = system._resolve_candidate_strategy_profile(candidate)

    if strategy_profile == "secondary_launch":
        minute_df = (minute_map or {}).get(str(candidate.get("symbol", "")))
        industry_confirm = system._resolve_candidate_industry_confirm(candidate, None)
        secondary_signal = detect_secondary_launch_signal(
            candidate=candidate,
            quote=quote,
            now=now,
            minute_df=minute_df,
            industry_confirm=industry_confirm,
            market_confirm=market_env,
        )
        return system._wrap_signal_metadata(
            signal=secondary_signal,
            strategy_profile="secondary_launch",
            template_source=str(
                (secondary_signal.details or {}).get(
                    "buy_template_source",
                    "secondary_launch_confirmation_v1",
                )
            ),
            route_name=str(
                (secondary_signal.details or {}).get(
                    "buy_route",
                    "secondary_launch_confirmation",
                )
            ),
            route_label=str(
                (secondary_signal.details or {}).get(
                    "buy_route_label",
                    "二次启动分时确认",
                )
            ),
            debounce_window=int(system.config.get("debounce_window", 2)),
        )

    if strategy_profile in {"breakout", "wide_breakout"}:
        label = "宽进突破观察池确认" if strategy_profile == "wide_breakout" else "突破观察池确认"
        # 日线 wide_pool_strict_entry_v2 已用更严买点；分时突破分支用 breakout_wide 参数组对齐
        bk_key = "breakout_wide" if strategy_profile == "wide_breakout" else "breakout"
        return system._detect_confirmation_signal(
            candidate=candidate,
            quote=quote,
            now=now,
            minute_map=minute_map,
            market_env=market_env,
            template_source="breakout_confirmation_v1",
            route_name="breakout_watch_confirm",
            route_label=label,
            breakout_intraday_param_key=bk_key,
        )

    if strategy_profile in {"legacy", "legacy_opt"} and bool(
        getattr(system, "legacy_gap_entry_enabled", True)
    ):
        legacy_signal = system._detect_legacy_gap_signal(
            candidate=candidate,
            quote=quote,
            now=now,
            minute_map=minute_map,
        )
        if legacy_signal is not None:
            return legacy_signal
        return system._detect_confirmation_signal(
            candidate=candidate,
            quote=quote,
            now=now,
            minute_map=minute_map,
            market_env=market_env,
            template_source="legacy_confirmation_fallback_v1",
            route_name="legacy_confirmation_fallback",
            route_label="原策略确认兜底",
        )

    return system._detect_confirmation_signal(
        candidate=candidate,
        quote=quote,
        now=now,
        minute_map=minute_map,
        market_env=market_env,
        template_source="enhanced_confirmation_v1",
        route_name="enhanced_confirmation",
        route_label="增强分时确认",
    )


def get_intraday_data_for_signal(
    system,
    symbol: str,
    current_price: float,
    current_volume: float,
    high: float,
    low: float,
    minute_map: Optional[Dict[str, pd.DataFrame]] = None,
    allow_quote_fallback: bool = True,
) -> Optional[IntradayData]:
    """从分钟数据构建 IntradayData。

    约束说明：
    - allow_quote_fallback=True：允许在分钟数据缺失时用“单点实时报价”构造 IntradayData 兜底，
      用于链路健壮性/展示/降级阶段。
    - allow_quote_fallback=False：实盘信号检测默认关闭兜底，避免在分钟源缺失时产生不可审计的伪信号。
    """
    minute_df = (minute_map or {}).get(symbol)
    intraday_data = system._build_intraday_from_minute(minute_df) if minute_df is not None else None
    if intraday_data is not None:
        source_state = getattr(system, "_last_intraday_source", None)
        if isinstance(source_state, dict):
            source_state[symbol] = "minute"
        return intraday_data

    if not allow_quote_fallback:
        source_state = getattr(system, "_last_intraday_source", None)
        if isinstance(source_state, dict):
            source_state[symbol] = "unavailable"
        return None

    # 兜底：分钟数据缺失时，用实时报价构造单点 IntradayData。
    if current_price > 0:
        import numpy as np
        from datetime import datetime as _dt
        from src.modules.optimized_buy_signals import IntradayData as _IntradayData

        price_arr = np.array([current_price], dtype=float)
        vol_arr = np.array([max(0.0, current_volume)], dtype=float)
        high_arr = np.array([max(current_price, high)], dtype=float)
        low_arr = np.array([min(current_price, low)], dtype=float)
        ts_arr = np.array([_dt.now()], dtype=object)
        intraday = _IntradayData(
            price=price_arr,
            volume=vol_arr,
            high=high_arr,
            low=low_arr,
            timestamp=ts_arr,
        )
        source_state = getattr(system, "_last_intraday_source", None)
        if isinstance(source_state, dict):
            source_state[symbol] = "quote_fallback"
        return intraday
    source_state = getattr(system, "_last_intraday_source", None)
    if isinstance(source_state, dict):
        source_state[symbol] = "unavailable"
    return None


def run_intraday_buy_router_healthcheck(system) -> List[Dict[str, Any]]:
    """
    盘中买点路由自检：对各类 strategy_profile 各做一次 resolve_strategy_routed_signal 冒烟调用。

    不依赖候选池是否有票、不要求真实分钟线；若调用抛异常则该档记为失败。
    用于验证融合监控能覆盖各策略对应的分支（二次启动 / 突破 / 宽进 / 原策略 / 增强兜底 / 强势股启动）。
    """
    now = datetime.now()
    market_env: Dict[str, Any] = {"market_score": 65.0}
    minute_map: Optional[Dict[str, pd.DataFrame]] = {}
    quote: Dict[str, float] = {
        "price": 10.0,
        "open": 9.9,
        "high": 10.1,
        "low": 9.8,
        "pre_close": 9.85,
        "volume": 100000.0,
    }
    profiles: List[tuple[str, str]] = [
        ("legacy", "原策略"),
        ("legacy_opt", "原策略优化"),
        ("enhanced", "增强策略"),
        ("secondary_launch", "二次启动"),
        ("breakout", "突破观察池"),
        ("wide_breakout", "宽进突破"),
        ("strong_start", "强势股刚启动"),
    ]
    rows: List[Dict[str, Any]] = []
    for pid, label in profiles:
        cand: Dict[str, Any] = {
            "symbol": "600000",
            "name": "路由自检",
            "strategy_profile": pid,
            "pool_type": "core",
            "score": 50.0,
        }
        try:
            sig = resolve_strategy_routed_signal(
                system=system,
                candidate=cand,
                quote=quote,
                now=now,
                minute_map=minute_map,
                market_env=market_env,
            )
            blocked = bool((sig.details or {}).get("route_blocked")) if isinstance(sig.details, dict) else False
            rows.append(
                {
                    "profile": pid,
                    "label": label,
                    "ok": True,
                    "error": "",
                    "signal": bool(getattr(sig, "signal", False)),
                    "route_blocked": blocked,
                }
            )
        except Exception as exc:
            logger.exception("intraday router healthcheck failed profile=%s", pid)
            rows.append(
                {
                    "profile": pid,
                    "label": label,
                    "ok": False,
                    "error": str(exc),
                    "signal": False,
                    "route_blocked": False,
                }
            )
    return rows


def print_intraday_buy_router_healthcheck_report(rows: List[Dict[str, Any]]) -> None:
    """终端打印自检表格。"""
    print("\n    ---------- 盘中买点路由自检（各策略一条冒烟路径）----------")
    for r in rows:
        status = "通过" if r.get("ok") else "失败"
        extra = ""
        if r.get("ok"):
            extra = f" signal={r.get('signal')} route_blocked={r.get('route_blocked')}"
        else:
            extra = f" err={r.get('error', '')[:80]}"
        print(f"    [{status}] {r.get('label')} ({r.get('profile')}){extra}")
    ok_n = sum(1 for x in rows if x.get("ok"))
    print(f"    合计: {ok_n}/{len(rows)} 档链路可调用")
    print("    说明: 无分钟线时部分档位可能 route_blocked=True，属预期；仅「失败」表示代码异常。")
    print("    --------------------------------------------------------")


def monitor_candidates(system) -> List[Dict]:
    """盘中候选监控总入口。"""
    if not system.candidate_pool:
        logger.warning("Candidate pool is empty")
        return []

    now = datetime.now()
    market_env = system._get_market_environment()
    if not system._signal_monitor_window_open(now, market_env):
        logger.info("Current time %s is outside monitor window", now.strftime("%H:%M"))
        return []

    logger.info("Monitoring %s candidate symbols", len(system.candidate_pool))
    symbols = [c["symbol"] for c in system.candidate_pool]
    df, minute_map = system._fetch_realtime_context(symbols)

    if df.empty and not minute_map:
        logger.warning("Neither realtime quotes nor minute data is available")
        return []

    trade_control = system._compose_trade_control_context(now=now, quote_df=df)
    system._report_trade_control_status(trade_control, now=now)
    if system.runtime_monitor and hasattr(system.runtime_monitor, "heartbeat"):
        try:
            system.runtime_monitor.heartbeat(
                "monitor.trade_control",
                {
                    "gate_tier": trade_control.get("gate_tier", "normal"),
                    "circuit_state": trade_control.get("circuit_state", "normal"),
                    "allow_new_signals": bool(trade_control.get("allow_new_signals", True)),
                },
            )
        except Exception:
            pass
    if not trade_control.get("allow_new_signals", True):
        logger.warning(
            "Signals blocked by hard circuit breaker: avg_index_pct=%+.2f%%, breadth=%.1f%%",
            _safe_float(trade_control.get("avg_index_pct", 0.0)),
            _safe_float(trade_control.get("breadth", 0.5)) * 100.0,
        )
        return []

    industry_context = system._build_intraday_industry_context(minute_map=minute_map, now=now)
    top_industries = industry_context.get("top_industries", [])
    if top_industries:
        top_desc = ", ".join(
            f"{item.get('industry', '')}({float(item.get('score', 50.0)):.1f})"
            for item in top_industries[:3]
        )
        logger.info(
            "Intraday industry context [%s]: %s",
            industry_context.get("source", "unknown"),
            top_desc,
        )
    buy_signals = detect_signals(
        system=system,
        df=df,
        now=now,
        minute_map=minute_map,
        industry_context=industry_context,
        trade_control=trade_control,
    )
    logger.info("Detected %s buy signals", len(buy_signals))
    return buy_signals


def detect_signals(
    system,
    df: pd.DataFrame,
    now: datetime,
    minute_map: Optional[Dict[str, pd.DataFrame]] = None,
    industry_context: Optional[Dict] = None,
    trade_control: Optional[Dict[str, Any]] = None,
) -> List[Dict]:
    """盘中信号检测。"""
    buy_signals: List[Dict] = []
    market_env = system._get_market_environment()
    control = trade_control or system._compose_trade_control_context(now=now, quote_df=df)
    if not control.get("allow_new_signals", True):
        logger.warning(
            "Signal detection skipped by trade control: gate=%s, circuit=%s",
            control.get("gate_tier", "normal"),
            control.get("circuit_state", "normal"),
        )
        return []

    for candidate in system.candidate_pool:
        symbol = candidate["symbol"]
        stock_data = df[df["symbol"] == symbol] if not df.empty else pd.DataFrame()
        quote = system._resolve_quote_row(
            symbol=symbol,
            stock_data=stock_data,
            minute_map=minute_map,
            candidate_name=candidate.get("name", ""),
        )
        if not quote:
            continue

        current_price = quote["price"]
        current_volume = quote["volume"]
        high = quote["high"]
        low = quote["low"]

        bar = {
            "symbol": symbol,
            "price": current_price,
            "volume": current_volume,
            "high": high,
            "low": low,
            "time": now,
        }

        signal = resolve_strategy_routed_signal(
            system=system,
            candidate=candidate,
            quote=quote,
            now=now,
            minute_map=minute_map,
            market_env=market_env,
        )
        signal_details = signal.details if isinstance(getattr(signal, "details", None), dict) else {}
        route_blocked = bool(signal_details.get("route_blocked", False))

        if (
            not signal.signal
            and not route_blocked
            and system.enable_auto_optimization
            and system.auto_optimizer
        ):
            try:
                auto_signal = system.auto_optimizer.on_new_bar(bar)
                if auto_signal:
                    runtime_signal = SignalOutput(
                        signal=True,
                        signal_type="runtime_auto_optimized",
                        confidence=float(auto_signal.get("confidence", 0.7) or 0.7),
                        reason=auto_signal.get("reason", "auto_optimized"),
                        details=dict(auto_signal),
                    )
                    signal = system._wrap_signal_metadata(
                        signal=runtime_signal,
                        strategy_profile=system._resolve_candidate_strategy_profile(candidate),
                        template_source="runtime_auto_optimizer_v1",
                        route_name="runtime_auto_optimized",
                        route_label="自动优化补充触发",
                        debounce_window=int(system.config.get("debounce_window", 2)),
                    )
            except Exception as exc:
                logger.error("Auto-optimization signal detection failed: %s", exc)

        if symbol not in system.signal_history:
            system.signal_history[symbol] = []
        system.signal_history[symbol].append(signal.signal)

        if system.signal_detector.debounce(
            system.signal_history[symbol],
            system._resolve_signal_debounce_window(signal),
        ):
            buy_signal = system._build_buy_signal(
                candidate=candidate,
                current_price=current_price,
                signal=signal,
                now=now,
                market_env=market_env,
                industry_context=industry_context,
                trade_control=control,
            )
            if buy_signal:
                buy_signals.append(buy_signal)

    buy_signals.sort(key=lambda x: x["total_score"], reverse=True)
    max_signals = int(control.get("max_signals_per_round", len(buy_signals)))
    if max_signals >= 0:
        buy_signals = buy_signals[:max_signals]
    return buy_signals


def show_buy_signals(signals: List[Dict], now: datetime) -> None:
    """终端展示盘中买点信号。"""
    print("\n" + "!" * 80)
    print(f"[{now.strftime('%H:%M:%S')}] 发现 {len(signals)} 个买点信号")
    print("!" * 80)

    for i, signal in enumerate(signals, 1):
        print(f"\n[信号{i}] {signal['symbol']} - {signal['name']}")
        print(f"   价格: {signal['price']:.2f}")
        print(f"   池类型: {signal['pool_type']}")
        print(
            "   策略/模板: %s / %s"
            % (
                signal.get("strategy_label", signal.get("strategy_profile", "legacy")),
                signal.get("buy_route_label", signal.get("buy_template_source", "unknown")),
            )
        )
        print(f"   隔夜评分: {signal['overnight_score']:.1f}")
        print(f"   盘中信号: {signal['intraday_score']:.1f}")
        print(f"   综合评分: {signal['total_score']:.1f}")
        print(
            "   建议仓位: %.2f%% (闸门:%s / 熔断:%s)"
            % (
                float(signal.get("suggest_position_pct", 0.0)),
                signal.get("market_gate_tier", "normal"),
                signal.get("circuit_state", "normal"),
            )
        )
        industry_confirm = signal.get("industry_confirm", {})
        print(
            "   行业确认: %s %.1f (%s)"
            % (
                industry_confirm.get("industry", "未知"),
                float(industry_confirm.get("score", 50.0)),
                industry_confirm.get("level", "neutral"),
            )
        )
        print(f"   信号类型: {signal['signal_type']}")

        if signal.get("signal_details"):
            details = signal["signal_details"]
            detail_parts = []
            for key, value in details.items():
                if isinstance(value, dict):
                    continue
                if isinstance(value, float):
                    detail_parts.append(f"{key}={value:.2f}")
                else:
                    detail_parts.append(f"{key}={value}")
            if detail_parts:
                print(f"   详情: {' | '.join(detail_parts)}")

    print("\n" + "!" * 80)
    print("执行建议:")
    print("- 评分>=80: 可优先执行")
    print("- 评分70-80: 结合分时再确认")
    print("- 评分<70: 等待确认")
    print("!" * 80)
