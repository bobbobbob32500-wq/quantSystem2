#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
核验“原本缺少当日分钟数据”的样本在补数后新增买点的真实收益。

统计口径：
1. 仅针对原跟踪报表里 `not_pushed_reason == 缺少当日分钟数据` 的样本
2. 使用补齐后的分钟数据重新检测盘中买点
3. 若出现买点，以触发分钟的收盘价作为真实买入价
4. 计算当日收盘、T+1 开盘、T+1 收盘、T+2 收盘、T+3 收盘收益
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import statistics
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.modules.backtest.history_recommendation_db import HistoryRecommendationDB
from scripts.analyze_secondary_launch_intraday import _load_session, _resolve_entry


def build_summary(values: list[float | None]) -> dict[str, Any]:
    clean = [float(v) for v in values if v is not None]
    if not clean:
        return {
            "count": 0,
            "win_rate": None,
            "avg_return_pct": None,
            "median_return_pct": None,
        }
    return {
        "count": len(clean),
        "win_rate": round(sum(1 for v in clean if v > 0) / len(clean) * 100, 2),
        "avg_return_pct": round(sum(clean) / len(clean) * 100, 2),
        "median_return_pct": round(statistics.median(clean) * 100, 2),
    }


def fmt_pct(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{value * 100:.2f}%"


def main() -> int:
    parser = argparse.ArgumentParser(description="核验缺分钟数据样本的真实触发价收益")
    parser.add_argument(
        "--report-json",
        default="results/secondary_launch_recent_tracking_20260402_005557.json",
        help="原始跟踪报表 JSON 路径",
    )
    parser.add_argument(
        "--minute-db",
        default="data/history_recommendation.db",
        help="分钟数据数据库路径",
    )
    parser.add_argument(
        "--daily-db",
        default="data/database/quant_system.db",
        help="日线数据库路径",
    )
    args = parser.parse_args()

    report_path = ROOT / args.report_json
    minute_db_path = ROOT / args.minute_db
    daily_db_path = ROOT / args.daily_db

    report = json.loads(report_path.read_text(encoding="utf-8"))
    targets = [
        item
        for item in report.get("details", [])
        if str(item.get("not_pushed_reason", "") or "") == "缺少当日分钟数据"
    ]

    minute_db = HistoryRecommendationDB(str(minute_db_path))
    conn = sqlite3.connect(str(daily_db_path))
    conn.row_factory = sqlite3.Row

    rows: list[dict[str, Any]] = []
    for item in targets:
        symbol = str(item.get("ts_code", "") or "").strip().upper()
        signal_date = str(item.get("signal_date", "") or "").strip()
        if not symbol or not signal_date:
            continue

        frame = _load_session(minute_db, symbol, signal_date)
        if frame.empty:
            continue

        entry = _resolve_entry(item, frame)
        if entry is None:
            continue

        entry_price = float(entry["entry_price"])
        same_day_close = float(frame.iloc[-1]["close"])
        daily_rows = list(
            conn.execute(
                """
                SELECT trade_date, open, close, high, low
                FROM stock_daily
                WHERE ts_code = ? AND trade_date >= ?
                ORDER BY trade_date ASC
                """,
                (symbol, signal_date),
            )
        )
        future_rows = [row for row in daily_rows if str(row["trade_date"]) > signal_date]

        record: dict[str, Any] = {
            "signal_date": signal_date,
            "symbol": symbol,
            "name": item.get("name", ""),
            "rank": int(item.get("rank") or 0),
            "signal_type": str(entry.get("signal_type", "") or ""),
            "entry_time": entry["entry_time"].strftime("%H:%M:%S"),
            "entry_price": entry_price,
            "same_day_close_ret": same_day_close / entry_price - 1.0,
        }

        for idx, label in enumerate(["T+1", "T+2", "T+3"], start=1):
            if len(future_rows) >= idx:
                bar = future_rows[idx - 1]
                record[f"{label}_date"] = str(bar["trade_date"])
                record[f"{label}_open_ret"] = (
                    float(bar["open"]) / entry_price - 1.0 if bar["open"] is not None else None
                )
                record[f"{label}_close_ret"] = (
                    float(bar["close"]) / entry_price - 1.0 if bar["close"] is not None else None
                )
            else:
                record[f"{label}_date"] = None
                record[f"{label}_open_ret"] = None
                record[f"{label}_close_ret"] = None

        rows.append(record)

    conn.close()

    metrics = {
        "same_day_close": build_summary([row["same_day_close_ret"] for row in rows]),
        "T+1_open": build_summary([row["T+1_open_ret"] for row in rows]),
        "T+1_close": build_summary([row["T+1_close_ret"] for row in rows]),
        "T+2_close": build_summary([row["T+2_close_ret"] for row in rows]),
        "T+3_close": build_summary([row["T+3_close_ret"] for row in rows]),
    }

    payload = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "source_report": str(report_path),
        "sample_count": len(rows),
        "metrics": metrics,
        "rows": rows,
    }

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_json = ROOT / "results" / f"secondary_launch_missing_intraday_truth_{ts}.json"
    out_md = ROOT / "results" / f"secondary_launch_missing_intraday_truth_{ts}.md"
    out_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        "# 新补分钟数据新增买点真实收益核验报表",
        "",
        f"- 生成时间: {payload['generated_at']}",
        f"- 源报表: `{args.report_json}`",
        f"- 样本数: {payload['sample_count']}",
        "",
        "## 汇总",
        "",
    ]
    for key, metric in metrics.items():
        lines.append(
            f"- {key}: 样本 {metric['count']}，"
            f"胜率 {'-' if metric['win_rate'] is None else str(metric['win_rate']) + '%'}，"
            f"平均收益 {'-' if metric['avg_return_pct'] is None else str(metric['avg_return_pct']) + '%'}，"
            f"中位收益 {'-' if metric['median_return_pct'] is None else str(metric['median_return_pct']) + '%'}"
        )

    lines.extend(
        [
            "",
            "## 明细",
            "",
            "| 信号日 | 股票 | 排名 | 触发时间 | 买入价 | 当日收盘 | T+1开盘 | T+1收盘 | T+2收盘 | T+3收盘 |",
            "| --- | --- | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for row in rows:
        lines.append(
            f"| {row['signal_date']} | {row['symbol']} | {row['rank']} | {row['entry_time']} | "
            f"{row['entry_price']:.2f} | {fmt_pct(row['same_day_close_ret'])} | "
            f"{fmt_pct(row['T+1_open_ret'])} | {fmt_pct(row['T+1_close_ret'])} | "
            f"{fmt_pct(row['T+2_close_ret'])} | {fmt_pct(row['T+3_close_ret'])} |"
        )

    out_md.write_text("\n".join(lines), encoding="utf-8")

    print(f"Markdown: {out_md}")
    print(f"JSON: {out_json}")
    print(json.dumps(metrics, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
