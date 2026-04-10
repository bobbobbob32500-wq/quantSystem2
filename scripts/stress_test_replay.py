# -*- coding: utf-8 -*-
"""
使用真实分时数据执行模拟实盘压力测试。
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
    parser = argparse.ArgumentParser(description="真实分时模拟实盘压力测试")
    parser.add_argument("--session-limit", type=int, default=20, help="参与测试的会话数量")
    parser.add_argument("--loop-count", type=int, default=1, help="回放循环次数")
    parser.add_argument("--market-score", type=float, default=65.0, help="回放使用的市场评分")
    parser.add_argument("--warmup-bars", type=int, default=30, help="预热K线数量")
    parser.add_argument("--debounce-window", type=int, default=2, help="信号防抖窗口")
    parser.add_argument("--min-rows", type=int, default=120, help="最少分时条数")
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    args = parser.parse_args()

    engine = build_live_replay_engine()
    engine.warmup_bars = args.warmup_bars
    engine.debounce_window = args.debounce_window

    summary = engine.stress_test(
        session_limit=args.session_limit,
        loop_count=args.loop_count,
        min_rows=args.min_rows,
        market_score=args.market_score,
    )

    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2, default=_json_default))
        return

    print("=" * 72)
    print("真实分时模拟实盘压力测试")
    print("=" * 72)
    print(f"选取会话数: {summary['sessions_selected']}")
    print(f"回放轮数: {summary['loop_count']}")
    print(f"实际运行会话数: {summary['session_runs']}")
    print(f"失败数: {summary['failures']}")
    print(f"总处理分时: {summary['total_bars_processed']}")
    print(f"总检测信号: {summary['total_signals_detected']}")
    print(f"总耗时: {summary['duration_seconds']} s")
    print(f"吞吐: {summary['bars_per_second']} bars/s")
    print(f"平均会话时延: {summary['avg_session_latency_ms']} ms")
    print(f"P95 会话时延: {summary['p95_session_latency_ms']} ms")
    print(f"峰值内存: {summary['peak_memory_mb']} MB")
    print("-" * 72)
    for item in summary["sample_sessions"]:
        print(
            f"{item['symbol']} {item['trade_date']} | "
            f"signals={item['signals_detected']} | avg_latency={item['avg_latency_ms']} ms"
        )


if __name__ == "__main__":
    main()
