# -*- coding: utf-8 -*-
"""
使用真实分时数据执行单会话模拟实盘回放。
"""

from __future__ import annotations

import argparse
import json
import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.modules.live_replay_engine import build_live_replay_engine


def _json_default(value):
    if hasattr(value, "item"):
        return value.item()
    return str(value)


def main():
    parser = argparse.ArgumentParser(description="真实分时模拟实盘回放")
    parser.add_argument("--symbol", help="股票代码，例如 000001.SZ")
    parser.add_argument("--trade-date", help="交易日期，例如 2026-03-26")
    parser.add_argument("--market-score", type=float, default=65.0, help="回放使用的市场评分")
    parser.add_argument("--warmup-bars", type=int, default=30, help="预热K线数量")
    parser.add_argument("--debounce-window", type=int, default=2, help="信号防抖窗口")
    parser.add_argument("--min-rows", type=int, default=120, help="最少分时条数")
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    args = parser.parse_args()

    engine = build_live_replay_engine()
    engine.warmup_bars = args.warmup_bars
    engine.debounce_window = args.debounce_window

    report = engine.replay_session(
        symbol=args.symbol,
        trade_date=args.trade_date,
        market_score=args.market_score,
        min_rows=args.min_rows,
    )

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2, default=_json_default))
        return

    print("=" * 72)
    print("真实分时模拟实盘回放")
    print("=" * 72)
    print(f"股票: {report['symbol']}")
    print(f"交易日: {report['trade_date']}")
    print(f"总分时: {report['bars_total']}")
    print(f"处理分时: {report['bars_processed']}")
    print(f"检测信号数: {report['signals_detected']}")
    print(f"平均时延: {report['avg_latency_ms']} ms")
    print(f"P95 时延: {report['p95_latency_ms']} ms")
    print(f"最大时延: {report['max_latency_ms']} ms")
    print(f"错误数: {report['error_count']}")
    print("-" * 72)

    if not report["signals"]:
        print("本次回放未触发确认买点。")
        return

    for index, signal in enumerate(report["signals"], start=1):
        print(
            f"{index:02d}. {signal['trade_time']} | {signal['signal_type']} | "
            f"price={signal['price']:.4f} | confidence={signal['confidence']:.2f}"
        )


if __name__ == "__main__":
    main()
