"""Sell-signal and virtual-trade display helpers for EnhancedHybridSystem."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional


def map_sell_reason(reason: str) -> str:
    mapping = {
        "stop_loss": "止损卖点",
        "take_profit": "止盈卖点",
        "trailing_stop": "移动止盈卖点",
        "trailing_stop_after_partial": "移动止盈卖点",
        "break_even_stop": "保本卖点",
        "time_exit": "超时卖点",
    }
    return mapping.get(str(reason or "").lower(), "卖点信号")


def build_sell_signals_from_closed_trades(
    system,
    closed_trades: List,
    trade_control: Optional[Dict[str, Any]] = None,
) -> List[Dict]:
    signals: List[Dict] = []
    control = trade_control or {}

    for trade in closed_trades or []:
        sell_reason = str(getattr(trade, "sell_reason", "") or "")
        sell_price = float(getattr(trade, "sell_price", 0.0) or 0.0)
        buy_price = float(getattr(trade, "buy_price", 0.0) or 0.0)
        pnl_pct = float(getattr(trade, "pnl_pct", 0.0) or 0.0)
        hold_minutes = int(getattr(trade, "hold_duration", 0) or 0)
        buy_score = float(getattr(trade, "buy_score", 0.0) or 0.0)
        details = getattr(trade, "details", {}) or {}
        risk_profile = str(
            getattr(trade, "risk_profile", details.get("risk_profile", "balanced")) or "balanced"
        )
        entry_gate_tier = str(
            getattr(
                trade,
                "entry_market_gate_tier",
                details.get("entry_market_gate_tier", "normal"),
            )
            or "normal"
        )
        entry_circuit_state = str(
            getattr(
                trade,
                "entry_circuit_state",
                details.get("entry_circuit_state", "normal"),
            )
            or "normal"
        )
        dynamic_stop_loss_pct = float(
            getattr(trade, "stop_loss_pct", details.get("dynamic_stop_loss_pct", 0.0)) or 0.0
        )
        dynamic_tp1_pct = float(
            getattr(trade, "take_profit_stage1_pct", details.get("dynamic_tp1_pct", 0.0)) or 0.0
        )
        dynamic_take_profit_pct = float(
            getattr(trade, "take_profit_pct", details.get("dynamic_take_profit_pct", 0.0)) or 0.0
        )
        dynamic_trailing_stop_pct = float(
            getattr(
                trade,
                "trailing_stop_pct",
                details.get("dynamic_trailing_stop_pct", 0.0),
            )
            or 0.0
        )
        peak_pnl_pct = float(getattr(trade, "highest_pnl_pct", pnl_pct) or pnl_pct)
        partial_take_done = bool(
            getattr(trade, "partial_take_done", details.get("partial_take_done", False))
        )
        signal_type = system._map_sell_reason(sell_reason)

        signals.append(
            {
                "symbol": str(getattr(trade, "symbol", "")),
                "name": str(getattr(trade, "name", "")),
                "price": sell_price,
                "action": "SELL",
                "signal_type": signal_type,
                "total_score": max(0.0, min(100.0, 50.0 + pnl_pct * 1000.0)),
                "overnight_score": buy_score,
                "intraday_score": max(0.0, min(100.0, 50.0 + pnl_pct * 1200.0)),
                "suggest_position_pct": 0.0,
                "market_gate_tier": control.get("gate_tier", "normal"),
                "circuit_state": control.get("circuit_state", "normal"),
                "signal_details": {
                    "sell_reason": sell_reason,
                    "buy_price": buy_price,
                    "sell_price": sell_price,
                    "pnl_pct": pnl_pct * 100.0,
                    "hold_minutes": hold_minutes,
                    "risk_profile": risk_profile,
                    "entry_gate_tier": entry_gate_tier,
                    "entry_circuit_state": entry_circuit_state,
                    "dynamic_stop_loss_pct": dynamic_stop_loss_pct * 100.0,
                    "dynamic_tp1_pct": dynamic_tp1_pct * 100.0,
                    "dynamic_take_profit_pct": dynamic_take_profit_pct * 100.0,
                    "dynamic_trailing_stop_pct": dynamic_trailing_stop_pct * 100.0,
                    "peak_pnl_pct": peak_pnl_pct * 100.0,
                    "partial_take_done": partial_take_done,
                },
                "industry_confirm": {
                    "industry": details.get("industry", "未知"),
                    "score": 50.0,
                    "level": "neutral",
                },
            }
        )

    return signals


def show_virtual_trades_closed(system, closed_trades: List, now: datetime):
    print("\n" + "=" * 80)
    print(f"[{now.strftime('%H:%M:%S')}] 虚拟交易平仓")
    print("=" * 80)

    for trade in closed_trades:
        pnl_str = f"{trade.pnl_pct:+.2%}"
        print(f"\n{trade.symbol} {trade.name}")
        print(f"  买入: {trade.buy_price:.2f} @ {trade.buy_time.strftime('%H:%M:%S')}")
        print(f"  卖出: {trade.sell_price:.2f} @ {trade.sell_time.strftime('%H:%M:%S')}")
        print(f"  盈亏: {pnl_str}")
        print(f"  原因: {trade.sell_reason}")
        if hasattr(trade, "risk_profile"):
            print(f"  风格: {getattr(trade, 'risk_profile', 'balanced')}")
        if hasattr(trade, "highest_pnl_pct"):
            print(f"  峰值: {float(getattr(trade, 'highest_pnl_pct', 0.0)):+.2%}")
        print(f"  持仓: {trade.hold_duration}分钟")

    if system.virtual_tracker:
        stats = system.virtual_tracker.get_statistics()
        print(
            f"\n统计: 已平仓={stats['total_closed']}, "
            f"胜率={stats['win_rate']:.1%}, "
            f"累计盈亏={stats['cumulative_pnl']:+.2%}"
        )

    print("=" * 80)
