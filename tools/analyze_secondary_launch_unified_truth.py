#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
按统一口径分析二次启动样本真实收益。

统一口径：
1. 使用跟踪报表中的全部样本
2. 对每个样本用分钟数据重新检测盘中买点
3. 若出现买点，以触发分钟收盘价作为真实买入价
4. 用主库日线数据计算当日收盘、T+1 开盘/收盘、T+2 收盘、T+3 收盘收益
5. 同时按排名、时间段等维度做统计，输出可用于实盘的规律
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


def _fetch_daily_features(conn: sqlite3.Connection, symbol: str, signal_date: str) -> dict[str, Any]:
    """从日线库取信号日日线特征，供日线过滤闸门使用。"""
    rows = list(conn.execute(
        """SELECT open, close, high, low, vol, pct_chg
           FROM stock_daily
           WHERE ts_code = ? AND trade_date <= ?
           ORDER BY trade_date DESC LIMIT 5""",
        (symbol, signal_date),
    ))
    if not rows:
        return {}
    today = rows[0]
    pct_chg = float(today["pct_chg"]) if today["pct_chg"] is not None else None

    vols = [float(r["vol"]) for r in rows[:5] if r["vol"] is not None]
    avg_vol_5 = sum(vols) / len(vols) if vols else None
    today_vol = float(today["vol"]) if today["vol"] else None
    vol_ratio_5 = (today_vol / avg_vol_5) if today_vol and avg_vol_5 and avg_vol_5 > 0 else None

    upper_shadow_pct = None
    if today["high"] and today["close"] and today["open"] and today["low"]:
        h, c, o, l = float(today["high"]), float(today["close"]), float(today["open"]), float(today["low"])
        total_range = h - l
        if total_range > 0:
            upper_shadow_pct = (h - max(c, o)) / total_range * 100

    return {
        "pct_chg": pct_chg,
        "vol_ratio_5": round(vol_ratio_5, 4) if vol_ratio_5 is not None else None,
        "upper_shadow_pct": round(upper_shadow_pct, 1) if upper_shadow_pct is not None else None,
    }


def build_metric(values: list[float | None]) -> dict[str, Any]:
    clean = [float(v) for v in values if v is not None]
    if not clean:
        return {
            "count": 0,
            "win_rate": None,
            "avg_return_pct": None,
            "median_return_pct": None,
            "best_return_pct": None,
            "worst_return_pct": None,
        }
    return {
        "count": len(clean),
        "win_rate": round(sum(1 for v in clean if v > 0) / len(clean) * 100, 2),
        "avg_return_pct": round(sum(clean) / len(clean) * 100, 2),
        "median_return_pct": round(statistics.median(clean) * 100, 2),
        "best_return_pct": round(max(clean) * 100, 2),
        "worst_return_pct": round(min(clean) * 100, 2),
    }


def fmt_pct(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{value * 100:.2f}%"


def summarize_group(rows: list[dict[str, Any]], key_name: str) -> list[dict[str, Any]]:
    values = sorted({row.get(key_name) for row in rows})
    result: list[dict[str, Any]] = []
    for key in values:
        subset = [row for row in rows if row.get(key_name) == key]
        if not subset:
            continue
        result.append(
            {
                key_name: key,
                "sample_count": len(subset),
                "same_day_close": build_metric([row.get("same_day_close_ret") for row in subset]),
                "T+1_close": build_metric([row.get("T+1_close_ret") for row in subset]),
                "T+2_close": build_metric([row.get("T+2_close_ret") for row in subset]),
                "T+3_close": build_metric([row.get("T+3_close_ret") for row in subset]),
            }
        )
    return result


def infer_time_bucket(entry_time: str) -> str:
    if not entry_time:
        return "未知"
    if entry_time < "11:30:00":
        return "上午"
    return "午后"


def build_insights(entries: list[dict[str, Any]], non_entries: list[dict[str, Any]], total_samples: int) -> list[str]:
    insights: list[str] = []
    if total_samples > 0:
        insights.append(
            f"全部样本 `{total_samples}` 条中，真正出现盘中买点 `{len(entries)}` 条，触发率 "
            f"`{len(entries) / total_samples * 100:.2f}%`。"
        )
    if entries:
        t1 = build_metric([row.get("T+1_close_ret") for row in entries])
        t2 = build_metric([row.get("T+2_close_ret") for row in entries])
        t3 = build_metric([row.get("T+3_close_ret") for row in entries])
        insights.append(
            f"真实触发价口径下，`T+1收盘` 平均收益 `{t1['avg_return_pct']:.2f}%`，"
            f"`T+2收盘` `{t2['avg_return_pct']:.2f}%`，`T+3收盘` `{t3['avg_return_pct']:.2f}%`。"
        )

        rank1 = [row for row in entries if row.get("rank") == 1]
        non_rank1 = [row for row in entries if row.get("rank") != 1]
        if rank1 and non_rank1:
            rank1_t2 = build_metric([row.get("T+2_close_ret") for row in rank1])
            other_t2 = build_metric([row.get("T+2_close_ret") for row in non_rank1])
            insights.append(
                f"`排名第1` 买点在 `T+2收盘` 的平均收益为 `{rank1_t2['avg_return_pct']:.2f}%`，"
                f"其余排名为 `{other_t2['avg_return_pct']:.2f}%`。"
            )

        morning = [row for row in entries if row.get("time_bucket") == "上午"]
        afternoon = [row for row in entries if row.get("time_bucket") == "午后"]
        if morning and afternoon:
            morning_t2 = build_metric([row.get("T+2_close_ret") for row in morning])
            afternoon_t2 = build_metric([row.get("T+2_close_ret") for row in afternoon])
            insights.append(
                f"`上午触发` 买点在 `T+2收盘` 的平均收益为 `{morning_t2['avg_return_pct']:.2f}%`，"
                f"`午后触发` 为 `{afternoon_t2['avg_return_pct']:.2f}%`。"
            )

    if non_entries:
        reason_counter: dict[str, int] = {}
        for row in non_entries:
            reason = str(row.get("no_entry_reason", "") or "未触发")
            reason_counter[reason] = reason_counter.get(reason, 0) + 1
        top_reason = sorted(reason_counter.items(), key=lambda x: x[1], reverse=True)[0]
        insights.append(f"未触发样本最多的原因是 `{top_reason[0]}`，共 `{top_reason[1]}` 条。")
    return insights


def main() -> int:
    parser = argparse.ArgumentParser(description="统一口径分析二次启动真实买点收益")
    parser.add_argument(
        "--report-json",
        default="results/secondary_launch_recent_tracking_20260402_014509.json",
        help="跟踪报表 JSON 路径",
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
    report = json.loads(report_path.read_text(encoding="utf-8"))
    details = list(report.get("details", []) or [])

    minute_db = HistoryRecommendationDB(str(ROOT / args.minute_db))
    conn = sqlite3.connect(str(ROOT / args.daily_db))
    conn.row_factory = sqlite3.Row

    entries: list[dict[str, Any]] = []
    non_entries: list[dict[str, Any]] = []

    for item in details:
        symbol = str(item.get("ts_code", "") or "").strip().upper()
        signal_date = str(item.get("signal_date", "") or "").strip()
        if not symbol or not signal_date:
            continue

        frame = _load_session(minute_db, symbol, signal_date)
        if frame.empty:
            non_entries.append(
                {
                    "signal_date": signal_date,
                    "symbol": symbol,
                    "rank": int(item.get("rank") or 0),
                    "no_entry_reason": "缺少当日分钟数据",
                }
            )
            continue

        daily_features = _fetch_daily_features(conn, symbol, signal_date)
        entry = _resolve_entry(item, frame, daily_features=daily_features)
        if entry is None:
            non_entries.append(
                {
                    "signal_date": signal_date,
                    "symbol": symbol,
                    "rank": int(item.get("rank") or 0),
                    "no_entry_reason": "未触发盘中买点",
                }
            )
            continue

        entry_price = float(entry["entry_price"])
        same_day_close = float(frame.iloc[-1]["close"])
        daily_rows = list(
            conn.execute(
                """
                SELECT trade_date, open, close
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
            "time_bucket": infer_time_bucket(entry["entry_time"].strftime("%H:%M:%S")),
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

        entries.append(record)

    conn.close()

    payload = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "source_report": str(report_path),
        "signal_count": len(details),
        "entry_count": len(entries),
        "no_entry_count": len(non_entries),
        "entry_rate_pct": round(len(entries) / len(details) * 100, 2) if details else 0.0,
        "metrics": {
            "same_day_close": build_metric([row.get("same_day_close_ret") for row in entries]),
            "T+1_open": build_metric([row.get("T+1_open_ret") for row in entries]),
            "T+1_close": build_metric([row.get("T+1_close_ret") for row in entries]),
            "T+2_close": build_metric([row.get("T+2_close_ret") for row in entries]),
            "T+3_close": build_metric([row.get("T+3_close_ret") for row in entries]),
        },
        "by_rank": summarize_group(entries, "rank"),
        "by_time_bucket": summarize_group(entries, "time_bucket"),
        "entries": entries,
        "non_entries": non_entries,
    }
    payload["insights"] = build_insights(entries, non_entries, len(details))

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_json = ROOT / "results" / f"secondary_launch_unified_truth_{ts}.json"
    out_md = ROOT / "results" / f"secondary_launch_unified_truth_{ts}.md"
    out_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        "# 二次启动策略统一口径真实收益分析",
        "",
        f"- 生成时间: {payload['generated_at']}",
        f"- 源报表: `{args.report_json}`",
        f"- 总样本数: {payload['signal_count']}",
        f"- 真实买点数: {payload['entry_count']}",
        f"- 未触发数: {payload['no_entry_count']}",
        f"- 买点触发率: {payload['entry_rate_pct']:.2f}%",
        "",
        "## 总体表现",
        "",
    ]
    for key, metric in payload["metrics"].items():
        lines.append(
            f"- {key}: 样本 {metric['count']}，胜率 "
            f"{'-' if metric['win_rate'] is None else str(metric['win_rate']) + '%'}，平均收益 "
            f"{'-' if metric['avg_return_pct'] is None else str(metric['avg_return_pct']) + '%'}，中位收益 "
            f"{'-' if metric['median_return_pct'] is None else str(metric['median_return_pct']) + '%'}"
        )

    lines.extend(["", "## 规律提炼", ""])
    for insight in payload["insights"]:
        lines.append(f"- {insight}")

    lines.extend(
        [
            "",
            "## 分组统计",
            "",
            "### 按排名",
            "",
            "| 排名 | 样本数 | T+1收盘胜率 | T+1收盘均值 | T+2收盘胜率 | T+2收盘均值 | T+3收盘胜率 | T+3收盘均值 |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for row in payload["by_rank"]:
        t1 = row["T+1_close"]
        t2 = row["T+2_close"]
        t3 = row["T+3_close"]
        lines.append(
            f"| {row['rank']} | {row['sample_count']} | "
            f"{'-' if t1['win_rate'] is None else str(t1['win_rate']) + '%'} | "
            f"{'-' if t1['avg_return_pct'] is None else str(t1['avg_return_pct']) + '%'} | "
            f"{'-' if t2['win_rate'] is None else str(t2['win_rate']) + '%'} | "
            f"{'-' if t2['avg_return_pct'] is None else str(t2['avg_return_pct']) + '%'} | "
            f"{'-' if t3['win_rate'] is None else str(t3['win_rate']) + '%'} | "
            f"{'-' if t3['avg_return_pct'] is None else str(t3['avg_return_pct']) + '%'} |"
        )

    lines.extend(
        [
            "",
            "### 按时间段",
            "",
            "| 时间段 | 样本数 | T+1收盘胜率 | T+1收盘均值 | T+2收盘胜率 | T+2收盘均值 | T+3收盘胜率 | T+3收盘均值 |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for row in payload["by_time_bucket"]:
        t1 = row["T+1_close"]
        t2 = row["T+2_close"]
        t3 = row["T+3_close"]
        lines.append(
            f"| {row['time_bucket']} | {row['sample_count']} | "
            f"{'-' if t1['win_rate'] is None else str(t1['win_rate']) + '%'} | "
            f"{'-' if t1['avg_return_pct'] is None else str(t1['avg_return_pct']) + '%'} | "
            f"{'-' if t2['win_rate'] is None else str(t2['win_rate']) + '%'} | "
            f"{'-' if t2['avg_return_pct'] is None else str(t2['avg_return_pct']) + '%'} | "
            f"{'-' if t3['win_rate'] is None else str(t3['win_rate']) + '%'} | "
            f"{'-' if t3['avg_return_pct'] is None else str(t3['avg_return_pct']) + '%'} |"
        )

    lines.extend(
        [
            "",
            "## 买点明细",
            "",
            "| 信号日 | 股票 | 排名 | 触发时间 | 时间段 | 买入价 | 当日收盘 | T+1收盘 | T+2收盘 | T+3收盘 |",
            "| --- | --- | ---: | --- | --- | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for row in entries:
        lines.append(
            f"| {row['signal_date']} | {row['symbol']} | {row['rank']} | {row['entry_time']} | "
            f"{row['time_bucket']} | {row['entry_price']:.2f} | {fmt_pct(row['same_day_close_ret'])} | "
            f"{fmt_pct(row['T+1_close_ret'])} | {fmt_pct(row['T+2_close_ret'])} | {fmt_pct(row['T+3_close_ret'])} |"
        )

    out_md.write_text("\n".join(lines), encoding="utf-8")
    print(f"Markdown: {out_md}")
    print(f"JSON: {out_json}")
    print(json.dumps({"metrics": payload["metrics"], "insights": payload["insights"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
