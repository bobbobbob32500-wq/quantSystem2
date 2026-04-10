"""Monitor-loop orchestration helpers for EnhancedHybridSystem."""

from __future__ import annotations

from datetime import datetime
import logging
import time as time_module
from typing import Any, Dict, List

import pandas as pd

logger = logging.getLogger(__name__)


def show_non_trade_time(system, now: datetime):
    """Display non-trading session status."""
    if now.weekday() >= 5:
        status = "周末"
    else:
        current_time = now.strftime("%H:%M")
        if current_time < "09:30":
            status = "盘前"
        elif "11:30" < current_time < "13:00":
            status = "午休"
        else:
            status = "盘后"

    print(
        f"\r[{now.strftime('%H:%M:%S')}] 当前为{status}时间，等待交易时段...",
        end="",
        flush=True,
    )


def update_latest_quotes(system, df: pd.DataFrame):
    """Update cached latest quote snapshot."""
    for _, row in df.iterrows():
        symbol = row["symbol"]
        system.latest_quotes[symbol] = {
            "price": float(row["price"]),
            "open": float(row["open"]),
            "high": float(row["high"]),
            "low": float(row["low"]),
            "volume": float(row["volume"]),
            "amount": float(row.get("amount", 0)),
            "time": datetime.now().strftime("%H:%M:%S"),
        }


def _format_volume(volume: float) -> str:
    if volume >= 100000000:
        return f"{volume / 100000000:.2f}亿"
    if volume >= 10000:
        return f"{volume / 10000:.2f}万"
    return f"{volume:.0f}"


def _show_candidate_group(df: pd.DataFrame, candidates: List[Dict[str, Any]], title: str):
    if not candidates:
        return

    print(f"\n【{title}】")
    print("-" * 80)
    print(f"{'序号':<4} {'代码':<8} {'名称':<10} {'现价':>8} {'涨跌幅':>8} {'成交量':>12} {'评分':>6}")
    print("-" * 80)

    for i, candidate in enumerate(candidates, 1):
        symbol = candidate["symbol"]
        stock_data = df[df["symbol"] == symbol]
        if stock_data.empty:
            continue

        row = stock_data.iloc[0]
        price = float(row["price"])
        pre_close = float(row.get("pre_close", row.get("open", price)))
        volume = float(row["volume"])
        change_pct = (price - pre_close) / pre_close * 100 if pre_close > 0 else 0.0
        change_str = f"+{change_pct:.2f}%" if change_pct > 0 else f"{change_pct:.2f}%"
        vol_str = _format_volume(volume)
        print(
            f"{i:<4} {symbol:<8} {candidate['name']:<10} {price:>8.2f} "
            f"{change_str:>8} {vol_str:>12} {candidate['score']:>6.1f}"
        )


def show_monitor_info(system, df: pd.DataFrame, now: datetime):
    """Print monitor snapshot grouped by candidate pool."""
    print("\n" + "=" * 80)
    print(f"[{now.strftime('%H:%M:%S')}] 实时监控中...")
    print("=" * 80)

    core_stocks = [c for c in system.candidate_pool if c["pool_type"] == "core"]
    reserve_stocks = [c for c in system.candidate_pool if c["pool_type"] == "reserve"]
    _show_candidate_group(df, core_stocks, "核心池")
    _show_candidate_group(df, reserve_stocks, "备选池")

    print("=" * 80)


def push_buy_signals(system, signals: List[Dict], now: datetime):
    """Push buy signals with score and cooldown filtering."""
    try:
        signals_to_push = []

        for signal in signals:
            symbol = signal["symbol"]
            signal_type = signal["signal_type"]
            total_score = signal["total_score"]
            push_threshold = signal.get("push_threshold", system.min_signal_score_for_push)

            if total_score < push_threshold:
                logger.debug(
                    "%s score %.1f below push threshold %.1f, skip",
                    symbol,
                    total_score,
                    push_threshold,
                )
                continue

            if symbol in system.pushed_signals:
                last_push = system.pushed_signals[symbol]
                time_diff = (now - last_push["push_time"]).total_seconds()
                strategy_profile = str(signal.get("strategy_profile", "") or "")

                # 同类型信号在冷却窗口内跳过
                if last_push["signal_type"] == signal_type and time_diff < system.push_cooldown:
                    logger.debug(
                        "%s %s in cooldown (%ss < %ss), skip",
                        symbol,
                        signal_type,
                        int(time_diff),
                        system.push_cooldown,
                    )
                    continue

                # 二次启动策略更强调等待下一次全新结构，冷却内无论信号类型都不重复推送
                if strategy_profile == "secondary_launch" and time_diff < system.push_cooldown:
                    logger.debug(
                        "%s secondary_launch signal blocked by strict cooldown (%ss < %ss)",
                        symbol,
                        int(time_diff),
                        system.push_cooldown,
                    )
                    continue

                # 不同类型信号的最短间隔保护（60s），但必须在 push_cooldown 之后才生效
                # 修复：仅在尚未过 push_cooldown 时应用 60s 保护，避免误拦截
                if time_diff < system.push_cooldown and time_diff < 60:
                    logger.debug("%s pushed only %ss ago (< 60s and < cooldown), skip", symbol, int(time_diff))
                    continue

            signals_to_push.append(signal)
            system.pushed_signals[symbol] = {
                "signal_type": signal_type,
                "push_time": now,
                "total_score": total_score,
            }

        if not signals_to_push:
            logger.info("All %s buy signals filtered, nothing to push", len(signals))
            return

        success = system.message_pusher.push_trade_signals(
            signals=signals_to_push,
            now=now,
            filtered_count=len(signals) - len(signals_to_push),
            side="buy",
        )

        if success:
            logger.info("Buy signal push success: %s", len(signals_to_push))
            print(f"\n[推送] 买点信号已推送到企业微信（{len(signals_to_push)}个）")
        else:
            failed_symbols = ", ".join(s.get("symbol", "?") for s in signals_to_push)
            logger.warning("Buy signal push failed for symbols: %s", failed_symbols)
            print(f"\n[推送] 买点信号推送失败（{len(signals_to_push)}个）: {failed_symbols}")
    except Exception as exc:
        logger.error("Push buy signals failed: %s", exc)
        print(f"\n[推送] 推送异常: {exc}")


def _apply_limit_filter(system, signals: List[Dict], df: pd.DataFrame, now: datetime) -> List[Dict]:
    if not signals:
        return signals
    if not system.enable_limit_filter or not system.limit_filter or df.empty:
        return signals

    quotes = {row["symbol"]: row.to_dict() for _, row in df.iterrows()}
    original_count = len(signals)
    filtered = system.limit_filter.filter_signals(signals, quotes)
    filtered_count = original_count - len(filtered)
    if filtered_count > 0:
        print(f"\n[{now.strftime('%H:%M:%S')}] Filtered limit-up signals: {filtered_count}")
    return filtered


def _handle_new_signals(
    system,
    signals: List[Dict],
    now: datetime,
):
    if not signals:
        return

    system._show_buy_signals(signals, now)
    if system.push_enabled:
        system._push_buy_signals(signals, now)

    if system.enable_virtual_trade and system.virtual_tracker:
        for signal in signals:
            system.virtual_tracker.on_buy_signal(signal)
        system.virtual_tracker.save_state()
        logger.info("Virtual trades persisted after new buy signals")


def _handle_closed_trades(
    system,
    df: pd.DataFrame,
    now: datetime,
    trade_control: Dict[str, Any],
):
    if not system.enable_virtual_trade or not system.virtual_tracker or df.empty:
        return

    current_prices = {row["symbol"]: float(row["price"]) for _, row in df.iterrows()}
    closed_trades = system.virtual_tracker.check_and_close(current_prices)
    if not closed_trades:
        return

    system._show_virtual_trades_closed(closed_trades, now)
    if system.push_enabled:
        sell_signals = system._build_sell_signals_from_closed_trades(
            closed_trades=closed_trades,
            trade_control=trade_control,
        )
        if sell_signals:
            system.message_pusher.push_trade_signals(
                signals=sell_signals,
                now=now,
                filtered_count=0,
                side="sell",
            )
    system.virtual_tracker.save_state()
    logger.info("Virtual trades persisted after close events")


def _maybe_interval_save(system, now: datetime, last_save_time: datetime, save_interval: int) -> datetime:
    if (now - last_save_time).total_seconds() >= save_interval:
        if system.enable_virtual_trade and system.virtual_tracker:
            system.virtual_tracker.save_state()
            logger.info("Virtual trades persisted on interval")
        return now
    return last_save_time


def _record_monitor_success(system, signals: List[Dict], trade_control: Dict[str, Any]):
    if not system.runtime_monitor or not hasattr(system.runtime_monitor, "record_success"):
        return
    try:
        system.runtime_monitor.record_success(
            "monitor.loop",
            context={
                "signals": len(signals),
                "gate_tier": trade_control.get("gate_tier", "normal"),
                "circuit_state": trade_control.get("circuit_state", "normal"),
            },
        )
    except Exception:
        pass


def monitor_loop(system, interval_seconds: int):
    """Background monitor loop with realtime minute source."""
    last_save_time = datetime.now()
    save_interval = 300

    while system.is_monitoring:
        try:
            now = datetime.now()
            if not system._is_trade_time(now):
                system._show_non_trade_time(now)
                time_module.sleep(interval_seconds)
                continue

            symbols = [c["symbol"] for c in system.candidate_pool]
            df, minute_map = system._fetch_realtime_context(symbols)

            if df.empty and not minute_map:
                print(f"\n[{now.strftime('%H:%M:%S')}] No realtime market data available")
                time_module.sleep(interval_seconds)
                continue

            if not df.empty:
                system._update_latest_quotes(df)
                system._show_monitor_info(df, now)

            trade_control = system._compose_trade_control_context(now=now, quote_df=df)
            system._report_trade_control_status(trade_control, now=now)

            industry_context = system._build_intraday_industry_context(
                minute_map=minute_map,
                now=now,
            )
            signals = system._detect_signals(
                df,
                now,
                minute_map=minute_map,
                industry_context=industry_context,
                trade_control=trade_control,
            )

            signals = _apply_limit_filter(system, signals, df, now)
            _handle_new_signals(system, signals, now)
            _handle_closed_trades(system, df, now, trade_control)
            last_save_time = _maybe_interval_save(system, now, last_save_time, save_interval)
            _record_monitor_success(system, signals, trade_control)

        except Exception as exc:
            logger.error("Monitor loop exception: %s", exc)
            print(f"\nMonitor loop exception: {exc}")
            system._record_monitor_incident(
                title="盘中监控循环异常",
                message=str(exc),
                severity="error",
                component="monitor.loop",
            )

        time_module.sleep(interval_seconds)
