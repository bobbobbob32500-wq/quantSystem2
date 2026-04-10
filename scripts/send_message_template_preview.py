# -*- coding: utf-8 -*-
"""Send UTF-8 message template previews to WeCom webhooks."""

from __future__ import annotations

from datetime import datetime
import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.core.config import ConfigManager
from src.modules.message_pusher import MessagePusher


def main() -> None:
    config = ConfigManager()
    pusher = MessagePusher(config)
    now = datetime.now()

    results = {
        "pre_market": pusher.push_pre_market_selection(
            {
                "report_date": now.strftime("%Y-%m-%d"),
                "report_time": now.strftime("%Y-%m-%d %H:%M:%S"),
                "strategy_label": "原策略优化版（legacy_opt / 5因子）",
                "market_analysis": {
                    "market_regime": "NEUTRAL",
                    "risk_state": "MEDIUM",
                    "target_position": 0.4,
                    "strategy_suggestion": "测试消息：轻仓跟踪强势候选，盘中等待买卖点确认",
                },
                "stock_selection_meta": {
                    "selection_end_date": now.strftime("%Y%m%d"),
                    "tradeability_thresholds": {
                        "min_avg_amount_20d": 120000.0,
                        "max_recent_limit_up_count_20d": 2,
                        "max_recent_return_20d": 24.0,
                        "max_avg_amplitude_10d": 6.0,
                    },
                },
                "stock_selection": [
                    {
                        "ts_code": "600519.SH",
                        "name": "贵州茅台",
                        "total_score": 88.6,
                        "level": "推荐",
                        "industry": "白酒",
                        "short_cycle_score": 78.0,
                        "tradeability_score": 92.0,
                    },
                    {
                        "ts_code": "000858.SZ",
                        "name": "五粮液",
                        "total_score": 84.2,
                        "level": "推荐",
                        "industry": "白酒",
                        "short_cycle_score": 72.0,
                        "tradeability_score": 89.0,
                    },
                ],
            }
        ),
        "buy_signal": pusher.push_trade_signals(
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
                    "position_note": "测试消息：防守市况下轻仓试错",
                    "industry_confirm": {
                        "industry": "白酒",
                        "score": 72.3,
                        "level": "strong",
                    },
                    "action": "BUY",
                }
            ],
            now=now,
            filtered_count=1,
            side="buy",
        ),
        "sell_signal": pusher.push_trade_signals(
            signals=[
                {
                    "symbol": "000858",
                    "name": "五粮液",
                    "price": 128.56,
                    "signal_type": "止盈卖点",
                    "total_score": 74.0,
                    "overnight_score": 80.0,
                    "intraday_score": 68.0,
                    "suggest_position_pct": 0.0,
                    "market_gate_tier": "normal",
                    "circuit_state": "normal",
                    "strategy_profile": "legacy_opt",
                    "strategy_label": "原策略优化版",
                    "buy_template_source": "legacy_gap_open_v1",
                    "buy_route_label": "中强开盘直入",
                    "industry_confirm": {
                        "industry": "白酒",
                        "score": 68.0,
                        "level": "strong",
                    },
                    "action": "SELL",
                }
            ],
            now=now,
            filtered_count=0,
            side="sell",
        ),
        "position_event": pusher.push_position_events(
            events=[
                {
                    "event_id": f"test-{now.strftime('%Y%m%d%H%M%S')}",
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
                    "reason": "测试消息：跌破动态止损线",
                    "suggestion": "先卖出1/3，余仓继续跟踪",
                }
            ],
            now=now,
        ),
    }

    print(results)


if __name__ == "__main__":
    main()
