#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
定向下载二次启动策略相关股票的历史分钟数据。

默认从指定的二次启动跟踪 JSON 中提取股票清单，
并把对应时间窗口内的 5 分钟数据写入 history_recommendation.db。
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Iterable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.modules.backtest.batch_intraday_downloader import BatchIntradayDownloader
from src.modules.backtest.history_recommendation_db import HistoryRecommendationDB


def _iter_symbols(report: dict) -> Iterable[str]:
    for item in report.get("details", []) or []:
        symbol = str(item.get("ts_code") or item.get("symbol") or "").strip().upper()
        if symbol:
            yield symbol


def main() -> int:
    parser = argparse.ArgumentParser(description="下载二次启动相关股票 5 分钟历史数据")
    parser.add_argument(
        "--report-json",
        default="results/secondary_launch_recent_tracking_20260401_023338.json",
        help="二次启动跟踪 JSON 路径",
    )
    parser.add_argument(
        "--db-path",
        default="data/history_recommendation.db",
        help="分钟数据目标数据库路径",
    )
    parser.add_argument(
        "--start-date",
        default="2026-01-27",
        help="下载开始日期，格式 YYYY-MM-DD",
    )
    parser.add_argument(
        "--end-date",
        default="2026-03-31",
        help="下载结束日期，格式 YYYY-MM-DD",
    )
    args = parser.parse_args()

    report_path = Path(args.report_json)
    if not report_path.is_absolute():
        report_path = Path.cwd() / report_path
    if not report_path.exists():
        raise FileNotFoundError(f"找不到跟踪报表: {report_path}")

    db_path = Path(args.db_path)
    if not db_path.is_absolute():
        db_path = Path.cwd() / db_path

    report = json.loads(report_path.read_text(encoding="utf-8"))
    symbols = sorted(set(_iter_symbols(report)))
    if not symbols:
        print("未从报表中提取到股票代码，终止下载。")
        return 1

    history_db = HistoryRecommendationDB(str(db_path))
    downloader = BatchIntradayDownloader(db=history_db)
    if downloader.bs is None:
        print("baostock 初始化失败，无法下载分钟数据。")
        return 2

    print(f"开始下载二次启动分钟数据，共 {len(symbols)} 只股票")
    print(f"时间范围: {args.start_date} ~ {args.end_date}")
    print(f"目标数据库: {db_path}")

    stats = {}
    for idx, symbol in enumerate(symbols, 1):
        print(f"[{idx}/{len(symbols)}] 下载 {symbol}")
        frame = downloader.download_intraday_data(symbol, args.start_date, args.end_date)
        if frame.empty:
            stats[symbol] = 0
            print(f"  无可用数据: {symbol}")
            continue
        ok = history_db.add_intraday_data(symbol, frame)
        stats[symbol] = int(len(frame)) if ok else 0
        print(f"  {'成功' if ok else '失败'}: {stats[symbol]} 条")

    success_symbols = sum(1 for value in stats.values() if value > 0)
    total_records = sum(stats.values())
    print("-" * 70)
    print(f"下载完成: 成功 {success_symbols}/{len(symbols)} 只, 总记录 {total_records}")
    failed = [symbol for symbol, value in stats.items() if value <= 0]
    if failed:
        print("失败股票:")
        for symbol in failed:
            print(f"  - {symbol}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
