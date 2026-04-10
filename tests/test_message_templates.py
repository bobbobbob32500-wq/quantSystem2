# -*- coding: utf-8 -*-
"""Tests for dedicated message templates."""

from __future__ import annotations

from datetime import datetime

from src.modules.message_pusher import MessagePusher


def _build_stub_pusher():
    pusher = MessagePusher.__new__(MessagePusher)
    captured = {"content": "", "channel": ""}

    def _capture(content: str, channel: str = "wechat") -> bool:
        captured["content"] = content
        captured["channel"] = channel
        return True

    pusher.push_markdown = _capture
    return pusher, captured


def test_pre_market_template_has_plan_marker_and_candidate_block():
    pusher, captured = _build_stub_pusher()

    ok = pusher.push_pre_market_selection(
        {
            "report_date": "2026-03-28",
            "report_time": "2026-03-28 09:00:00",
            "strategy_label": "增强策略（enhanced / 6因子）",
            "market_analysis": {
                "market_regime": "NEUTRAL",
                "risk_state": "MEDIUM",
                "target_position": 0.3,
                "strategy_suggestion": "轻仓试错",
            },
            "stock_selection_meta": {
                "selection_end_date": "20260327",
                "tradeability_thresholds": {
                    "min_avg_amount_20d": 120000.0,
                    "max_recent_limit_up_count_20d": 2,
                    "max_recent_return_20d": 24.5,
                    "max_avg_amplitude_10d": 6.2,
                },
            },
            "stock_selection": [
                {
                    "ts_code": "000001.SZ",
                    "name": "平安银行",
                    "total_score": 78.3,
                    "level": "推荐",
                    "industry": "银行",
                    "short_cycle_score": 71.5,
                    "tradeability_score": 84.1,
                }
            ],
        }
    )

    assert ok is True
    assert "盘前计划" in captured["content"]
    assert "000001.SZ 平安银行" in captured["content"]
    assert "盘中只处理真正触发的买卖点信号" in captured["content"]


def test_intraday_trade_template_has_mobile_readable_layout():
    pusher, captured = _build_stub_pusher()

    ok = pusher.push_trade_signals(
        signals=[
            {
                "symbol": "600519",
                "name": "贵州茅台",
                "price": 1520.88,
                "signal_type": "原策略开盘强势买点",
                "total_score": 86.5,
                "overnight_score": 82.0,
                "intraday_score": 90.0,
                "suggest_position_pct": 8.5,
                "market_gate_tier": "defensive",
                "circuit_state": "soft",
                "strategy_profile": "legacy_opt",
                "strategy_label": "原策略优化版",
                "buy_template_source": "legacy_gap_open_v1",
                "buy_route_label": "中强开盘直入",
                "position_note": "防守市况下轻仓试错",
                "action": "buy",
                "industry_confirm": {
                    "industry": "白酒",
                    "score": 72.3,
                    "level": "strong",
                },
            }
        ],
        now=datetime(2026, 3, 28, 10, 15, 0),
        filtered_count=2,
        side="buy",
    )

    assert ok is True
    assert "盘中买点信号" in captured["content"]
    assert "当前动作: `BUY` | 价格 `1520.88`" in captured["content"]
    assert "策略: `原策略优化版` | 类型 `原策略开盘强势买点`" in captured["content"]
    assert "建议仓位: `8.50%`" in captured["content"]
    assert "仓位说明: 防守市况下轻仓试错" in captured["content"]
    assert "行业确认: `白酒` / `strong`" in captured["content"]
    assert "模板: `中强开盘直入` / `legacy_gap_open_v1`" in captured["content"]


def test_intraday_trade_template_includes_secondary_launch_execution_fields():
    pusher, captured = _build_stub_pusher()

    ok = pusher.push_trade_signals(
        signals=[
            {
                "symbol": "600468",
                "name": "百利电气",
                "price": 10.18,
                "signal_type": "二次启动平台突破",
                "signal_subtype": "secondary_launch_breakout",
                "total_score": 88.2,
                "overnight_score": 86.6,
                "intraday_score": 79.0,
                "suggest_position_pct": 6.0,
                "market_gate_tier": "normal",
                "circuit_state": "normal",
                "strategy_profile": "secondary_launch",
                "strategy_label": "二次启动策略",
                "buy_template_source": "secondary_launch_breakout_v1",
                "buy_route_label": "二次启动平台突破",
                "signal_details": {
                    "entry_trigger": "平台上沿放量突破并站稳",
                    "support_price": 10.06,
                    "breakout_price": 10.10,
                    "volume_ratio": 1.56,
                    "invalid_below": 10.04,
                    "expiry_hint": "若3根分钟线内跌回平台则失效",
                },
                "action": "buy",
            }
        ],
        now=datetime(2026, 4, 1, 10, 15, 0),
        side="buy",
    )

    assert ok is True
    assert "二次启动平台突破" in captured["content"]
    assert "子类型标签: `secondary_launch_breakout`" in captured["content"]
    assert "触发机制: 平台上沿放量突破并站稳" in captured["content"]
    assert "失效价位: `10.04`" in captured["content"]


def test_intraday_sell_template_uses_sell_side_label():
    pusher, captured = _build_stub_pusher()

    ok = pusher.push_trade_signals(
        signals=[
            {
                "symbol": "600519",
                "name": "贵州茅台",
                "price": 1512.00,
                "signal_type": "止盈卖点",
                "total_score": 72.0,
                "overnight_score": 86.5,
                "intraday_score": 70.0,
                "suggest_position_pct": 0.0,
                "market_gate_tier": "normal",
                "circuit_state": "normal",
                "action": "SELL",
            }
        ],
        now=datetime(2026, 3, 28, 14, 30, 0),
        side="sell",
    )

    assert ok is True
    assert "盘中卖点信号" in captured["content"]
    assert "当前动作: `SELL` | 价格 `1512.00`" in captured["content"]


def test_position_event_template_uses_mobile_readable_layout():
    pusher, captured = _build_stub_pusher()

    ok = pusher.push_position_events(
        events=[
            {
                "event_id": "evt-001",
                "ts_code": "600519.SH",
                "name": "贵州茅台",
                "signal_type": "价格止损",
                "severity": "high",
                "action": "SELL_ALL",
                "hold_num": 300,
                "hold_price": 1500.0,
                "current_price": 1480.0,
                "profit": -1.33,
                "reconcile_status": "CONFIRMED",
                "is_real_position": True,
                "reason": "跌破动态止损线",
                "suggestion": "先卖出1/3，余仓跟踪",
            }
        ],
        now=datetime(2026, 3, 28, 10, 20, 0),
    )

    assert ok is True
    assert captured["channel"] == "position"
    assert "position_event_v2" in captured["content"]
    assert "持仓管理事件" in captured["content"]
    assert "动作/标的: `SELL_ALL` / `600519.SH 贵州茅台`" in captured["content"]
    assert "信号摘要: `价格止损` | 风险 `high`" in captured["content"]
    assert "持仓概览: `300股` / 成本 `1500.00`" in captured["content"]
    assert "当前表现: 现价 `1480.00` | 盈亏 `-1.33%`" in captured["content"]
    assert "对账状态: `CONFIRMED` | 真实持仓 `True`" in captured["content"]
    assert "触发原因: 跌破动态止损线" in captured["content"]
    assert "操作说明: 先卖出1/3，余仓跟踪" in captured["content"]
    assert "事件ID: `evt-001`" in captured["content"]


def test_pre_market_template_includes_feedback_summary_when_present():
    pusher, captured = _build_stub_pusher()

    ok = pusher.push_pre_market_selection(
        {
            "report_date": "2026-03-28",
            "report_time": "2026-03-28 09:00:00",
            "strategy_label": "原策略（legacy / 5因子）",
            "market_analysis": {},
            "stock_selection_meta": {},
            "stock_selection": [],
            "feedback_summary": {
                "start_date": "20260201",
                "end_date": "20260327",
                "recommendation_detail_count": 220,
                "signal_detail_count": 40,
                "best_recommendation_horizon": 2,
                "best_recommendation_mean_net_return": 0.015,
                "best_recommendation_win_rate": 0.53,
                "best_signal_horizon": 1,
                "best_signal_mean_net_return": 0.021,
                "best_signal_win_rate": 0.56,
            },
        }
    )

    assert ok is True
    assert "最近复盘结论" in captured["content"]
