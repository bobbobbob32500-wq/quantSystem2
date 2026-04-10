# -*- coding: utf-8 -*-
"""
虚拟交易跟踪器
基于买点信号记录持仓，并在盘中根据动态卖点规则自动平仓。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import json
import os
from typing import Any, Callable, Dict, List, Optional

import numpy as np

from src.core.logger import get_logger

logger = get_logger("virtual_trade_tracker")


@dataclass
class VirtualTrade:
    """虚拟交易记录"""

    # 买入信息
    trade_id: str
    symbol: str
    name: str
    buy_time: datetime
    buy_price: float
    buy_signal: str
    buy_score: float
    signal_instance_id: str = ""

    # 卖出信息（平仓后写入）
    sell_time: Optional[datetime] = None
    sell_price: Optional[float] = None
    sell_reason: Optional[str] = None

    # 盈亏
    pnl: Optional[float] = None
    pnl_pct: Optional[float] = None

    # 状态
    status: str = "holding"  # holding / closed
    hold_duration: Optional[int] = None  # 分钟

    # 动态风控参数（每笔交易独立）
    stop_loss_pct: Optional[float] = None
    take_profit_stage1_pct: Optional[float] = None
    take_profit_pct: Optional[float] = None
    trailing_stop_pct: Optional[float] = None
    max_hold_hours: Optional[float] = None

    # 持仓过程状态
    highest_pnl_pct: float = 0.0
    lowest_pnl_pct: float = 0.0
    partial_take_done: bool = False
    partial_take_time: Optional[datetime] = None
    partial_take_price: Optional[float] = None
    partial_take_pnl_pct: Optional[float] = None

    # 入场上下文
    risk_profile: str = "balanced"
    entry_market_gate_tier: str = "normal"
    entry_circuit_state: str = "normal"

    # 扩展信息
    details: Dict[str, Any] = field(default_factory=dict)


class VirtualTradeTracker:
    """虚拟交易跟踪器"""

    def __init__(
        self,
        stop_loss_pct: float = -0.05,
        take_profit_pct: float = 0.10,
        max_hold_hours: Optional[int] = None,
        enable_auto_feedback: bool = True,
        enable_dynamic_exit: bool = True,
        fallback_max_hold_hours: Optional[int] = 96,
        partial_take_ratio: float = 0.5,
        partial_take_profit_pct: Optional[float] = None,
        trailing_stop_pct: float = 0.035,
    ):
        """
        初始化虚拟交易跟踪器。

        Args:
            stop_loss_pct: 默认止损阈值（收益率）
            take_profit_pct: 默认止盈阈值（收益率）
            max_hold_hours: 全局最大持仓小时（None 表示按 fallback 或交易级参数）
            enable_auto_feedback: 保留字段，与上游自动优化模块兼容
            enable_dynamic_exit: 是否启用动态退出（分批止盈+移动止盈）
            fallback_max_hold_hours: 当交易级和全局均未设置时使用的默认超时（建议 3-5 天）
            partial_take_ratio: 触发首档止盈时视作已锁定的仓位比例（仅用于记录，不做资金撮合）
            partial_take_profit_pct: 首档止盈阈值（None 时按 take_profit_pct 动态推导）
            trailing_stop_pct: 首档后移动止盈回撤阈值
        """
        self.stop_loss_pct = float(stop_loss_pct)
        self.take_profit_pct = float(take_profit_pct)
        self.max_hold_hours = float(max_hold_hours) if max_hold_hours is not None else None
        self.enable_auto_feedback = bool(enable_auto_feedback)
        self.enable_dynamic_exit = bool(enable_dynamic_exit)
        self.fallback_max_hold_hours = (
            float(fallback_max_hold_hours) if fallback_max_hold_hours is not None else None
        )

        self.partial_take_ratio = float(max(0.0, min(1.0, partial_take_ratio)))
        if partial_take_profit_pct is None:
            partial_take_profit_pct = max(0.03, self.take_profit_pct * 0.65)
        self.partial_take_profit_pct = float(partial_take_profit_pct)
        self.trailing_stop_pct = float(max(0.01, trailing_stop_pct))

        self.open_trades: Dict[str, VirtualTrade] = {}
        self.closed_trades: List[VirtualTrade] = []
        self.all_trades: List[VirtualTrade] = []
        self._trade_seq = 0

        self.total_signals = 0
        self.total_closed = 0

        self.on_trade_closed: Optional[Callable[[VirtualTrade], None]] = None

        self.cache_dir = "data/cache"
        os.makedirs(self.cache_dir, exist_ok=True)

        logger.info(
            "虚拟交易跟踪器初始化: stop=%+.2f%% tp2=%+.2f%% dynamic=%s fallback_hold=%.1fh",
            self.stop_loss_pct * 100.0,
            self.take_profit_pct * 100.0,
            self.enable_dynamic_exit,
            self.fallback_max_hold_hours if self.fallback_max_hold_hours is not None else -1.0,
        )

    @staticmethod
    def _safe_float(value: Any, default: float = 0.0) -> float:
        try:
            return float(value)
        except Exception:
            return float(default)

    def _resolve_max_hold_hours(self, trade: VirtualTrade) -> Optional[float]:
        if trade.max_hold_hours is not None:
            return float(trade.max_hold_hours)
        if self.max_hold_hours is not None:
            return float(self.max_hold_hours)
        if self.fallback_max_hold_hours is not None:
            return float(self.fallback_max_hold_hours)
        return None

    def _resolve_min_hold_trading_days(self, trade: VirtualTrade) -> int:
        details = trade.details if isinstance(trade.details, dict) else {}
        raw_value = details.get("min_hold_trading_days", 0)
        try:
            return max(0, int(float(raw_value)))
        except Exception:
            return 0

    def _has_satisfied_min_hold(self, trade: VirtualTrade, now: datetime) -> bool:
        min_days = self._resolve_min_hold_trading_days(trade)
        if min_days <= 0:
            return True
        buy_date = trade.buy_time.date()
        current_date = now.date()
        elapsed_days = (current_date - buy_date).days
        return elapsed_days >= min_days

    def _next_trade_id(self, symbol: str, signal_time: datetime) -> str:
        self._trade_seq += 1
        return f"{symbol}_{signal_time.strftime('%Y%m%d%H%M%S')}_{self._trade_seq:05d}"

    def get_latest_open_trade(self, symbol: str) -> Optional[VirtualTrade]:
        matched = [trade for trade in self.open_trades.values() if trade.symbol == symbol]
        if not matched:
            return None
        matched.sort(key=lambda item: item.buy_time)
        return matched[-1]

    def _derive_risk_profile(self, signal: Dict[str, Any]) -> Dict[str, Any]:
        score = self._safe_float(signal.get("total_score", 0.0), 0.0)
        gate_tier = str(signal.get("market_gate_tier", "normal") or "normal").lower()
        circuit_state = str(signal.get("circuit_state", "normal") or "normal").lower()

        profiles = {
            "defensive": {
                "stop_loss_pct": -0.035,
                "tp1_pct": 0.050,
                "tp2_pct": 0.085,
                "trailing_stop_pct": 0.025,
                "max_hold_hours": 72.0,
            },
            "balanced": {
                "stop_loss_pct": -0.045,
                "tp1_pct": 0.065,
                "tp2_pct": 0.110,
                "trailing_stop_pct": 0.032,
                "max_hold_hours": 96.0,
            },
            "aggressive": {
                "stop_loss_pct": -0.055,
                "tp1_pct": 0.080,
                "tp2_pct": 0.130,
                "trailing_stop_pct": 0.038,
                "max_hold_hours": 120.0,
            },
        }

        if gate_tier == "defensive" or circuit_state in {"soft", "hard"}:
            profile_name = "defensive"
        elif score >= 88 and gate_tier == "normal" and circuit_state == "normal":
            profile_name = "aggressive"
        else:
            profile_name = "balanced"

        profile = dict(profiles[profile_name])

        # 评分微调：高分允许更大空间，低分更快保护
        if score >= 92:
            profile["stop_loss_pct"] -= 0.003
            profile["tp1_pct"] += 0.005
            profile["tp2_pct"] += 0.008
            profile["trailing_stop_pct"] += 0.004
        elif score < 75:
            profile["stop_loss_pct"] += 0.005
            profile["tp1_pct"] -= 0.006
            profile["tp2_pct"] -= 0.008
            profile["trailing_stop_pct"] -= 0.004

        # 支持信号侧覆盖（如后续模型输出个股级风险参数）
        if "dynamic_stop_loss_pct" in signal:
            profile["stop_loss_pct"] = self._safe_float(
                signal.get("dynamic_stop_loss_pct"), profile["stop_loss_pct"]
            )
        if "dynamic_take_profit_pct" in signal:
            profile["tp2_pct"] = self._safe_float(
                signal.get("dynamic_take_profit_pct"), profile["tp2_pct"]
            )
        if "dynamic_tp1_pct" in signal:
            profile["tp1_pct"] = self._safe_float(
                signal.get("dynamic_tp1_pct"), profile["tp1_pct"]
            )
        if bool(signal.get("disable_dynamic_trailing_stop", False)):
            profile["trailing_stop_pct"] = None
        if "dynamic_trailing_stop_pct" in signal:
            if profile["trailing_stop_pct"] is not None:
                profile["trailing_stop_pct"] = self._safe_float(
                    signal.get("dynamic_trailing_stop_pct"), profile["trailing_stop_pct"]
                )

        signal_hold_hours = signal.get("max_hold_hours", None)
        if signal_hold_hours is not None:
            try:
                profile["max_hold_hours"] = float(signal_hold_hours)
            except Exception:
                pass

        # 与初始化默认参数做保护性融合
        profile["stop_loss_pct"] = max(-0.08, min(-0.02, profile["stop_loss_pct"]))
        profile["tp1_pct"] = max(0.03, min(0.12, profile["tp1_pct"]))
        profile["tp2_pct"] = max(profile["tp1_pct"] + 0.02, min(0.18, profile["tp2_pct"]))
        if profile["trailing_stop_pct"] is not None:
            profile["trailing_stop_pct"] = max(0.015, min(0.06, profile["trailing_stop_pct"]))

        # 若全局显式指定 max_hold_hours，优先全局；否则使用 profile + fallback
        if self.max_hold_hours is not None:
            profile["max_hold_hours"] = self.max_hold_hours
        elif self.fallback_max_hold_hours is None and signal_hold_hours is None:
            profile["max_hold_hours"] = None

        profile["risk_profile"] = profile_name
        profile["entry_market_gate_tier"] = gate_tier
        profile["entry_circuit_state"] = circuit_state
        return profile

    def on_buy_signal(self, signal: Dict[str, Any]) -> bool:
        """
        记录买点信号并创建虚拟持仓。
        """
        symbol = str(signal.get("symbol", "") or "").strip()
        if not symbol:
            return False

        buy_price = self._safe_float(signal.get("price", 0.0), 0.0)
        if buy_price <= 0:
            logger.warning("%s 买入信号价格非法: %s", symbol, signal.get("price"))
            return False

        signal_time = None
        for key in ("signal_time", "timestamp", "buy_time"):
            value = signal.get(key)
            if value is None:
                continue
            if isinstance(value, datetime):
                signal_time = value
                break
            text = str(value).strip()
            if not text:
                continue
            try:
                signal_time = datetime.fromisoformat(text)
                break
            except Exception:
                continue
        if signal_time is None:
            signal_time = datetime.now()

        trade_id = self._next_trade_id(symbol, signal_time)
        signal_instance_id = str(signal.get("signal_instance_id") or trade_id)
        profile = self._derive_risk_profile(signal)
        details = {
            "trade_id": trade_id,
            "signal_instance_id": signal_instance_id,
            "pool_type": signal.get("pool_type", ""),
            "overnight_score": self._safe_float(signal.get("overnight_score", 0.0), 0.0),
            "intraday_score": self._safe_float(signal.get("intraday_score", 0.0), 0.0),
            "industry": signal.get("industry", ""),
            "strategy_profile": signal.get("strategy_profile", ""),
            "signal_subtype": signal.get("signal_subtype", ""),
            "buy_template_source": signal.get("buy_template_source", ""),
            "buy_route": signal.get("buy_route", ""),
            "buy_route_label": signal.get("buy_route_label", ""),
            "carry_peak_arm_on_t1": bool(signal.get("carry_peak_arm_on_t1", False)),
            "risk_profile": profile["risk_profile"],
            "entry_market_gate_tier": profile["entry_market_gate_tier"],
            "entry_circuit_state": profile["entry_circuit_state"],
            "dynamic_stop_loss_pct": profile["stop_loss_pct"],
            "dynamic_tp1_pct": profile["tp1_pct"],
            "dynamic_take_profit_pct": profile["tp2_pct"],
            "dynamic_trailing_stop_pct": profile["trailing_stop_pct"],
            "disable_dynamic_trailing_stop": bool(signal.get("disable_dynamic_trailing_stop", False)),
            "min_hold_trading_days": signal.get("min_hold_trading_days", 0),
            "remaining_position_ratio": 1.0,
        }

        trade = VirtualTrade(
            trade_id=trade_id,
            symbol=symbol,
            name=str(signal.get("name", "") or ""),
            buy_time=signal_time,
            buy_price=buy_price,
            buy_signal=str(signal.get("signal_type", "") or ""),
            buy_score=self._safe_float(signal.get("total_score", 0.0), 0.0),
            signal_instance_id=signal_instance_id,
            stop_loss_pct=profile["stop_loss_pct"],
            take_profit_stage1_pct=profile["tp1_pct"],
            take_profit_pct=profile["tp2_pct"],
            trailing_stop_pct=profile["trailing_stop_pct"],
            max_hold_hours=profile.get("max_hold_hours", None),
            risk_profile=profile["risk_profile"],
            entry_market_gate_tier=profile["entry_market_gate_tier"],
            entry_circuit_state=profile["entry_circuit_state"],
            details=details,
        )

        self.open_trades[trade.trade_id] = trade
        self.all_trades.append(trade)
        self.total_signals += 1

        logger.info(
            "[虚拟买入] %s %s %s @ %.2f, score=%.1f, profile=%s, stop=%+.2f%%, tp1=%+.2f%%, tp2=%+.2f%%",
            trade.trade_id,
            trade.symbol,
            trade.name,
            trade.buy_price,
            trade.buy_score,
            trade.risk_profile,
            (trade.stop_loss_pct or self.stop_loss_pct) * 100.0,
            (trade.take_profit_stage1_pct or self.partial_take_profit_pct) * 100.0,
            (trade.take_profit_pct or self.take_profit_pct) * 100.0,
        )
        return True

    def check_and_close(
        self,
        current_prices: Dict[str, float],
        now: Optional[datetime] = None,
        blocked_symbols: Optional[List[str]] = None,
    ) -> List[VirtualTrade]:
        """
        根据当前价格检查持仓是否应平仓。
        """
        now = now or datetime.now()
        blocked = {
            str(symbol).strip() for symbol in (blocked_symbols or []) if str(symbol).strip()
        }
        closed_trades: List[VirtualTrade] = []

        for trade_id, trade in list(self.open_trades.items()):
            symbol = trade.symbol
            if symbol not in current_prices:
                continue

            current_price = self._safe_float(current_prices.get(symbol), 0.0)
            if current_price <= 0:
                continue

            if trade.buy_price <= 0:
                continue

            pnl_pct = (current_price - trade.buy_price) / trade.buy_price
            trade.highest_pnl_pct = max(float(trade.highest_pnl_pct or 0.0), pnl_pct)
            trade.lowest_pnl_pct = min(float(trade.lowest_pnl_pct or 0.0), pnl_pct)
            trade.details["last_price"] = current_price
            trade.details["last_pnl_pct"] = pnl_pct
            trade.details["peak_pnl_pct"] = trade.highest_pnl_pct
            trade.details["lowest_pnl_pct"] = trade.lowest_pnl_pct

            stop_loss_pct = (
                trade.stop_loss_pct if trade.stop_loss_pct is not None else self.stop_loss_pct
            )
            take_profit_pct = (
                trade.take_profit_pct if trade.take_profit_pct is not None else self.take_profit_pct
            )
            tp1_pct = (
                trade.take_profit_stage1_pct
                if trade.take_profit_stage1_pct is not None
                else self.partial_take_profit_pct
            )
            disable_trailing_stop = bool((trade.details or {}).get("disable_dynamic_trailing_stop", False))
            trailing_stop_pct = None
            if not disable_trailing_stop:
                trailing_stop_pct = (
                    trade.trailing_stop_pct
                    if trade.trailing_stop_pct is not None
                    else self.trailing_stop_pct
                )

            carry_peak_arm_on_t1 = bool(trade.details.get("carry_peak_arm_on_t1", False))
            if (
                carry_peak_arm_on_t1
                and not trade.partial_take_done
                and trade.highest_pnl_pct >= tp1_pct
            ):
                trade.details["tp1_armed_from_peak"] = True

            if symbol in blocked:
                continue

            can_exit_today = self._has_satisfied_min_hold(trade, now)
            trade.details["min_hold_satisfied"] = can_exit_today

            peak_armed = bool(trade.details.get("tp1_armed_from_peak", False))
            if self.enable_dynamic_exit and not trade.partial_take_done and (
                pnl_pct >= tp1_pct or peak_armed
            ):
                trade.partial_take_done = True
                trade.partial_take_time = now
                trade.partial_take_price = current_price
                trade.partial_take_pnl_pct = pnl_pct
                trade.details["partial_take"] = {
                    "time": now.isoformat(),
                    "price": current_price,
                    "pnl_pct": pnl_pct,
                    "ratio": self.partial_take_ratio,
                    "trigger": "peak_arm_t1" if peak_armed and pnl_pct < tp1_pct else "tp1_reached",
                }
                trade.details["remaining_position_ratio"] = max(0.0, 1.0 - self.partial_take_ratio)
                logger.info(
                    "[虚拟分批止盈] %s %s 触发首档止盈 @ %.2f, pnl=%+.2f%%, 锁定仓位=%.0f%%",
                    trade.symbol,
                    trade.name,
                    current_price,
                    pnl_pct * 100.0,
                    self.partial_take_ratio * 100.0,
                )

            should_close = False
            close_reason = ""

            if not can_exit_today:
                pass
            elif pnl_pct <= stop_loss_pct:
                should_close = True
                close_reason = "stop_loss"
            elif pnl_pct >= take_profit_pct:
                should_close = True
                close_reason = "take_profit"
            elif self.enable_dynamic_exit and trade.partial_take_done:
                retrace_pct = trade.highest_pnl_pct - pnl_pct
                if trailing_stop_pct is not None and retrace_pct >= trailing_stop_pct:
                    should_close = True
                    close_reason = "trailing_stop"
                    trade.details["trailing_retrace_pct"] = retrace_pct
            else:
                max_hold_hours = self._resolve_max_hold_hours(trade)
                if max_hold_hours is not None:
                    hold_hours = (now - trade.buy_time).total_seconds() / 3600.0
                    if hold_hours >= max_hold_hours:
                        should_close = True
                        close_reason = "time_exit"

            # 分批止盈后，若持仓回落到保本以下，主动离场
            if (
                not should_close
                and self.enable_dynamic_exit
                and trade.partial_take_done
                and pnl_pct <= -0.001
            ):
                should_close = True
                close_reason = "break_even_stop"

            if should_close:
                self._close_trade(
                    trade=trade,
                    sell_price=current_price,
                    reason=close_reason,
                    sell_time=now,
                )
                closed_trades.append(trade)
                del self.open_trades[trade_id]

                if self.on_trade_closed:
                    try:
                        self.on_trade_closed(trade)
                    except Exception as callback_error:
                        logger.error("trade closed callback failed: %s", callback_error)

        return closed_trades

    def _close_trade(
        self, trade: VirtualTrade, sell_price: float, reason: str, sell_time: datetime
    ) -> None:
        trade.sell_time = sell_time
        trade.sell_price = float(sell_price)
        trade.sell_reason = str(reason)
        trade.pnl = trade.sell_price - trade.buy_price
        trade.pnl_pct = (
            (trade.sell_price - trade.buy_price) / trade.buy_price if trade.buy_price > 0 else 0.0
        )
        trade.status = "closed"
        trade.hold_duration = int((sell_time - trade.buy_time).total_seconds() / 60)

        trade.details.setdefault("exit_context", {})
        trade.details["exit_context"].update(
            {
                "reason": trade.sell_reason,
                "sell_time": sell_time.isoformat(),
                "sell_price": trade.sell_price,
                "pnl_pct": trade.pnl_pct,
                "peak_pnl_pct": trade.highest_pnl_pct,
                "lowest_pnl_pct": trade.lowest_pnl_pct,
                "risk_profile": trade.risk_profile,
            }
        )

        self.closed_trades.append(trade)
        self.total_closed += 1

        logger.info(
            "[虚拟卖出] %s %s %s @ %.2f, pnl=%+.2f%%, reason=%s, hold=%dmin, peak=%+.2f%%",
            trade.trade_id,
            trade.symbol,
            trade.name,
            trade.sell_price,
            trade.pnl_pct * 100.0,
            trade.sell_reason,
            trade.hold_duration or 0,
            trade.highest_pnl_pct * 100.0,
        )

    def get_statistics(self) -> Dict[str, Any]:
        if not self.closed_trades:
            return {
                "total_signals": self.total_signals,
                "total_closed": 0,
                "open_trades": len(self.open_trades),
                "win_rate": 0.0,
                "avg_pnl_pct": 0.0,
            }

        total_trades = len(self.closed_trades)
        win_trades = [t for t in self.closed_trades if (t.pnl or 0) > 0]
        loss_trades = [t for t in self.closed_trades if (t.pnl or 0) < 0]

        win_rate = len(win_trades) / total_trades if total_trades > 0 else 0.0
        pnl_pcts = [float(t.pnl_pct or 0.0) for t in self.closed_trades]
        avg_pnl_pct = float(np.mean(pnl_pcts)) if pnl_pcts else 0.0

        avg_win = float(np.mean([float(t.pnl_pct or 0.0) for t in win_trades])) if win_trades else 0.0
        avg_loss = (
            float(np.mean([float(t.pnl_pct or 0.0) for t in loss_trades])) if loss_trades else 0.0
        )
        profit_loss_ratio = abs(avg_win / avg_loss) if avg_loss != 0 else 0.0

        cumulative_pnl = float(np.sum(pnl_pcts))
        cumulative_series = np.cumsum(pnl_pcts) if pnl_pcts else np.array([])
        if len(cumulative_series) > 0:
            running_max = np.maximum.accumulate(cumulative_series)
            drawdowns = cumulative_series - running_max
            max_drawdown = float(np.min(drawdowns))
        else:
            max_drawdown = 0.0

        hold_durations = [int(t.hold_duration or 0) for t in self.closed_trades if t.hold_duration is not None]
        avg_hold_duration = float(np.mean(hold_durations)) if hold_durations else 0.0

        close_reasons: Dict[str, int] = {}
        for trade in self.closed_trades:
            reason = trade.sell_reason or "unknown"
            close_reasons[reason] = close_reasons.get(reason, 0) + 1

        return {
            "total_signals": self.total_signals,
            "total_closed": total_trades,
            "open_trades": len(self.open_trades),
            "win_rate": win_rate,
            "win_count": len(win_trades),
            "loss_count": len(loss_trades),
            "avg_pnl_pct": avg_pnl_pct,
            "cumulative_pnl": cumulative_pnl,
            "profit_loss_ratio": profit_loss_ratio,
            "max_drawdown": max_drawdown,
            "avg_hold_duration": avg_hold_duration,
            "close_reasons": close_reasons,
        }

    def get_open_trades_info(self) -> List[Dict[str, Any]]:
        result: List[Dict[str, Any]] = []
        now = datetime.now()
        for trade in self.open_trades.values():
            hold_hours = (now - trade.buy_time).total_seconds() / 3600.0
            result.append(
                {
                    "trade_id": trade.trade_id,
                    "signal_instance_id": trade.signal_instance_id,
                    "symbol": trade.symbol,
                    "name": trade.name,
                    "buy_price": trade.buy_price,
                    "buy_time": trade.buy_time.strftime("%H:%M:%S"),
                    "buy_signal": trade.buy_signal,
                    "buy_score": trade.buy_score,
                    "hold_hours": hold_hours,
                    "status": trade.status,
                    "risk_profile": trade.risk_profile,
                    "stop_loss_pct": trade.stop_loss_pct,
                    "take_profit_stage1_pct": trade.take_profit_stage1_pct,
                    "take_profit_pct": trade.take_profit_pct,
                    "trailing_stop_pct": trade.trailing_stop_pct,
                    "partial_take_done": trade.partial_take_done,
                    "highest_pnl_pct": trade.highest_pnl_pct,
                    "lowest_pnl_pct": trade.lowest_pnl_pct,
                }
            )
        return result

    @staticmethod
    def _trade_to_dict(trade: VirtualTrade) -> Dict[str, Any]:
        return {
            "trade_id": trade.trade_id,
            "symbol": trade.symbol,
            "name": trade.name,
            "buy_time": trade.buy_time.isoformat(),
            "buy_price": trade.buy_price,
            "buy_signal": trade.buy_signal,
            "buy_score": trade.buy_score,
            "signal_instance_id": trade.signal_instance_id,
            "sell_time": trade.sell_time.isoformat() if trade.sell_time else None,
            "sell_price": trade.sell_price,
            "sell_reason": trade.sell_reason,
            "pnl": trade.pnl,
            "pnl_pct": trade.pnl_pct,
            "status": trade.status,
            "hold_duration": trade.hold_duration,
            "stop_loss_pct": trade.stop_loss_pct,
            "take_profit_stage1_pct": trade.take_profit_stage1_pct,
            "take_profit_pct": trade.take_profit_pct,
            "trailing_stop_pct": trade.trailing_stop_pct,
            "max_hold_hours": trade.max_hold_hours,
            "highest_pnl_pct": trade.highest_pnl_pct,
            "lowest_pnl_pct": trade.lowest_pnl_pct,
            "partial_take_done": trade.partial_take_done,
            "partial_take_time": trade.partial_take_time.isoformat() if trade.partial_take_time else None,
            "partial_take_price": trade.partial_take_price,
            "partial_take_pnl_pct": trade.partial_take_pnl_pct,
            "risk_profile": trade.risk_profile,
            "entry_market_gate_tier": trade.entry_market_gate_tier,
            "entry_circuit_state": trade.entry_circuit_state,
            "details": trade.details,
        }

    @staticmethod
    def _trade_from_dict(data: Dict[str, Any], default_status: str = "holding") -> VirtualTrade:
        sell_time_raw = data.get("sell_time")
        partial_take_time_raw = data.get("partial_take_time")
        return VirtualTrade(
            trade_id=str(data.get("trade_id", "")),
            symbol=str(data.get("symbol", "")),
            name=str(data.get("name", "")),
            buy_time=datetime.fromisoformat(str(data["buy_time"])),
            buy_price=float(data.get("buy_price", 0.0)),
            buy_signal=str(data.get("buy_signal", "")),
            buy_score=float(data.get("buy_score", 0.0)),
            signal_instance_id=str(data.get("signal_instance_id", data.get("trade_id", ""))),
            sell_time=datetime.fromisoformat(str(sell_time_raw)) if sell_time_raw else None,
            sell_price=data.get("sell_price", None),
            sell_reason=data.get("sell_reason", None),
            pnl=data.get("pnl", None),
            pnl_pct=data.get("pnl_pct", None),
            status=str(data.get("status", default_status)),
            hold_duration=data.get("hold_duration", None),
            stop_loss_pct=data.get("stop_loss_pct", None),
            take_profit_stage1_pct=data.get("take_profit_stage1_pct", None),
            take_profit_pct=data.get("take_profit_pct", None),
            trailing_stop_pct=data.get("trailing_stop_pct", None),
            max_hold_hours=data.get("max_hold_hours", None),
            highest_pnl_pct=float(data.get("highest_pnl_pct", 0.0) or 0.0),
            lowest_pnl_pct=float(data.get("lowest_pnl_pct", 0.0) or 0.0),
            partial_take_done=bool(data.get("partial_take_done", False)),
            partial_take_time=(
                datetime.fromisoformat(str(partial_take_time_raw)) if partial_take_time_raw else None
            ),
            partial_take_price=data.get("partial_take_price", None),
            partial_take_pnl_pct=data.get("partial_take_pnl_pct", None),
            risk_profile=str(data.get("risk_profile", "balanced")),
            entry_market_gate_tier=str(data.get("entry_market_gate_tier", "normal")),
            entry_circuit_state=str(data.get("entry_circuit_state", "normal")),
            details=data.get("details", {}) if isinstance(data.get("details", {}), dict) else {},
        )

    def save_state(self, filepath: str = None) -> None:
        if filepath is None:
            filepath = os.path.join(self.cache_dir, "virtual_trades.json")

        data = {
            "config": {
                "stop_loss_pct": self.stop_loss_pct,
                "take_profit_pct": self.take_profit_pct,
                "max_hold_hours": self.max_hold_hours,
                "fallback_max_hold_hours": self.fallback_max_hold_hours,
                "enable_dynamic_exit": self.enable_dynamic_exit,
                "partial_take_ratio": self.partial_take_ratio,
                "partial_take_profit_pct": self.partial_take_profit_pct,
                "trailing_stop_pct": self.trailing_stop_pct,
            },
            "open_trades": [self._trade_to_dict(t) for t in self.open_trades.values()],
            "closed_trades": [self._trade_to_dict(t) for t in self.closed_trades],
            "statistics": self.get_statistics(),
            "save_time": datetime.now().isoformat(),
        }

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        logger.info("虚拟交易状态已保存: %s", filepath)

    def load_state(self, filepath: str = None) -> None:
        if filepath is None:
            filepath = os.path.join(self.cache_dir, "virtual_trades.json")

        if not os.path.exists(filepath):
            logger.warning("状态文件不存在: %s", filepath)
            return

        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)

        self.open_trades = {}
        self.closed_trades = []
        self.all_trades = []
        self._trade_seq = 0

        for t_data in data.get("open_trades", []):
            try:
                trade = self._trade_from_dict(t_data, default_status="holding")
                if not trade.trade_id:
                    trade.trade_id = self._next_trade_id(trade.symbol, trade.buy_time)
                if not trade.signal_instance_id:
                    trade.signal_instance_id = trade.trade_id
                trade.status = "holding"
                self.open_trades[trade.trade_id] = trade
                self.all_trades.append(trade)
            except Exception as e:
                logger.warning("跳过非法 open trade: %s", e)

        for t_data in data.get("closed_trades", []):
            try:
                trade = self._trade_from_dict(t_data, default_status="closed")
                if not trade.trade_id:
                    trade.trade_id = self._next_trade_id(trade.symbol, trade.buy_time)
                if not trade.signal_instance_id:
                    trade.signal_instance_id = trade.trade_id
                trade.status = "closed"
                self.closed_trades.append(trade)
                self.all_trades.append(trade)
            except Exception as e:
                logger.warning("跳过非法 closed trade: %s", e)

        self.total_signals = len(self.all_trades)
        self.total_closed = len(self.closed_trades)

        logger.info(
            "虚拟交易状态已加载: open=%d, closed=%d",
            len(self.open_trades),
            len(self.closed_trades),
        )

    def print_statistics(self) -> None:
        stats = self.get_statistics()
        print("\n" + "=" * 80)
        print("虚拟交易统计")
        print("=" * 80)
        print(f"总信号数: {stats['total_signals']}")
        print(f"已平仓: {stats['total_closed']}")
        print(f"未平仓: {stats['open_trades']}")

        if stats["total_closed"] > 0:
            print(f"\n胜率: {stats['win_rate']:.2%} ({stats['win_count']}胜/{stats['loss_count']}负)")
            print(f"平均盈亏: {stats['avg_pnl_pct']:+.2%}")
            print(f"累计盈亏: {stats['cumulative_pnl']:+.2%}")
            print(f"盈亏比: {stats['profit_loss_ratio']:.2f}")
            print(f"最大回撤: {stats['max_drawdown']:.2%}")
            print(f"平均持仓: {stats['avg_hold_duration']:.1f}分钟")
            print("\n平仓原因:")
            for reason, count in stats["close_reasons"].items():
                print(f"  - {reason}: {count}次")

        print("=" * 80)
