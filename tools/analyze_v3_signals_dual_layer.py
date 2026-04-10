#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
对 V3 最终信号 CSV（134 条）做双层对齐分析：

- 层 A：日线机械回测（与 run_secondary_launch_v3_final_backtest 产出的 trades CSV 一致，
        信号日开盘买入、持仓 hold_days 日收盘卖出）
- 层 B：分钟回放真实触发价 + 日线闸门字段，计算 T+1/T+2/T+3 收益

输出 JSON + Markdown 对照表。
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(ROOT / "tools"))

import analyze_secondary_launch_unified_truth as unified_truth

from src.modules.backtest.history_recommendation_db import HistoryRecommendationDB
from scripts.analyze_secondary_launch_intraday import _load_session, _resolve_entry

_fetch_daily_features = unified_truth._fetch_daily_features
build_insights = unified_truth.build_insights
build_metric = unified_truth.build_metric
fmt_pct = unified_truth.fmt_pct
infer_time_bucket = unified_truth.infer_time_bucket
summarize_group = unified_truth.summarize_group


def _to_signal_yyyymmdd(val: Any) -> str:
    """CSV 中 signal_date 可能是 2025-12-03 或 20251203。"""
    s = str(val).strip()
    if not s:
        return ""
    if "-" in s:
        return s.replace("-", "")[:8]
    return s[:8]


def main() -> int:
    parser = argparse.ArgumentParser(description="V3 信号 CSV 双层对齐分析")
    parser.add_argument(
        "--signals-csv",
        default="results/secondary_launch_v3_signals_FINAL.csv",
        help="V3 最终信号名单 CSV",
    )
    parser.add_argument(
        "--trades-csv",
        default="results/secondary_launch_v3_trades_20260402_135420.csv",
        help="同批次日线机械回测 trades CSV（层 A）",
    )
    parser.add_argument("--minute-db", default="data/history_recommendation.db")
    parser.add_argument("--daily-db", default="data/database/quant_system.db")
    args = parser.parse_args()

    sig_path = ROOT / args.signals_csv
    tr_path = ROOT / args.trades_csv
    if not sig_path.exists():
        print(f"错误: 找不到 {sig_path}", flush=True)
        return 1

    df_sig = pd.read_csv(sig_path)
    df_tr = pd.read_csv(tr_path) if tr_path.exists() else pd.DataFrame()

    minute_db = HistoryRecommendationDB(str(ROOT / args.minute_db))
    conn = sqlite3.connect(str(ROOT / args.daily_db))
    conn.row_factory = sqlite3.Row

    # 层 A：按 (signal_date, ts_code) 索引 net_ret
    layer_a_map: dict[tuple[str, str], float] = {}
    if not df_tr.empty:
        for _, r in df_tr.iterrows():
            sd = _to_signal_yyyymmdd(r.get("signal_date"))
            code = str(r.get("ts_code", "")).strip().upper()
            if sd and code and "net_ret" in df_tr.columns:
                try:
                    layer_a_map[(sd, code)] = float(r["net_ret"])
                except (TypeError, ValueError):
                    pass

    details: list[dict[str, Any]] = []
    for _, row in df_sig.iterrows():
        sd_raw = row.get("signal_date")
        signal_date = _to_signal_yyyymmdd(sd_raw)
        ts_code = str(row.get("ts_code", "") or "").strip().upper()
        details.append(
            {
                "ts_code": ts_code,
                "signal_date": signal_date,
                "name": str(row.get("name", "") or ""),
                "rank": int(row.get("rank") or 0),
                "signal_score": float(row.get("signal_score", 0) or 0),
                "rs20": float(row.get("rs20", 0) or 0),
            }
        )

    entries: list[dict[str, Any]] = []
    non_entries: list[dict[str, Any]] = []
    layer_a_rets: list[float] = []
    layer_b_t2: list[float] = []

    for item in details:
        symbol = item["ts_code"]
        signal_date = item["signal_date"]
        frame = _load_session(minute_db, symbol, signal_date)
        layer_a_ret = layer_a_map.get((signal_date, symbol))

        if frame.empty:
            non_entries.append(
                {
                    "signal_date": signal_date,
                    "symbol": symbol,
                    "rank": item["rank"],
                    "no_entry_reason": "缺少当日分钟数据",
                    "layer_a_net_ret": layer_a_ret,
                }
            )
            if layer_a_ret is not None:
                layer_a_rets.append(layer_a_ret)
            continue

        daily_features = _fetch_daily_features(conn, symbol, signal_date)
        entry = _resolve_entry(item, frame, daily_features=daily_features)
        if entry is None:
            non_entries.append(
                {
                    "signal_date": signal_date,
                    "symbol": symbol,
                    "rank": item["rank"],
                    "no_entry_reason": "未触发盘中买点",
                    "layer_a_net_ret": layer_a_ret,
                }
            )
            if layer_a_ret is not None:
                layer_a_rets.append(layer_a_ret)
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
            "rank": item["rank"],
            "signal_score": item.get("signal_score"),
            "rs20": item.get("rs20"),
            "signal_type": str(entry.get("signal_type", "") or ""),
            "entry_time": entry["entry_time"].strftime("%H:%M:%S"),
            "time_bucket": infer_time_bucket(entry["entry_time"].strftime("%H:%M:%S")),
            "entry_price": entry_price,
            "same_day_close_ret": same_day_close / entry_price - 1.0,
            "layer_a_net_ret": layer_a_ret,
        }
        if layer_a_ret is not None:
            layer_a_rets.append(layer_a_ret)

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

        t2 = record.get("T+2_close_ret")
        if t2 is not None:
            layer_b_t2.append(float(t2))
        entries.append(record)

    conn.close()

    n_total = len(details)
    n_both_a = sum(1 for e in entries if e.get("layer_a_net_ret") is not None)
    n_a_only = len(layer_a_rets)

    payload: dict[str, Any] = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "signals_csv": str(sig_path),
        "trades_csv": str(tr_path) if tr_path.exists() else None,
        "sample_count": n_total,
        "layer_a": {
            "description": "信号日开盘买入、持仓2日收盘卖出（含费用滑点），与回测器 trades 一致",
            "matched_rows": len(layer_a_rets),
            "metrics_net_ret": build_metric(layer_a_rets) if layer_a_rets else {},
        },
        "layer_b": {
            "description": "分钟首次触发价买入，T+N 为相对触发价的持有收益",
            "entry_count": len(entries),
            "no_entry_count": len(non_entries),
            "entry_rate_pct": round(len(entries) / n_total * 100, 2) if n_total else 0.0,
            "metrics": {
                "same_day_close": build_metric([row.get("same_day_close_ret") for row in entries]),
                "T+1_close": build_metric([row.get("T+1_close_ret") for row in entries]),
                "T+2_close": build_metric([row.get("T+2_close_ret") for row in entries]),
                "T+3_close": build_metric([row.get("T+3_close_ret") for row in entries]),
            },
            "by_rank": summarize_group(entries, "rank"),
            "by_time_bucket": summarize_group(entries, "time_bucket"),
        },
        "entries": entries,
        "non_entries": non_entries,
    }
    payload["insights"] = build_insights(entries, non_entries, n_total)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_json = ROOT / "results" / f"secondary_launch_v3_dual_layer_{ts}.json"
    out_md = ROOT / "results" / f"secondary_launch_v3_dual_layer_{ts}.md"
    out_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    la = payload["layer_a"]["metrics_net_ret"]
    lb = payload["layer_b"]["metrics"]
    t2b = lb.get("T+2_close") or {}

    lines = [
        "# V3 二次启动：层 A（日线机械）与层 B（分钟触发）对齐报告",
        "",
        f"- 生成时间: {payload['generated_at']}",
        f"- 信号名单: `{args.signals_csv}`",
        f"- 层 A 回测成交: `{args.trades_csv}`" if tr_path.exists() else "- 层 A trades 文件未找到",
        f"- 样本数: **{n_total}**（与 V3 最终 CSV 行数一致）",
        "",
        "## 层 A：日线机械持仓 2 日（net_ret）",
        "",
        f"- 与 trades 匹配条数: **{payload['layer_a']['matched_rows']}** / {n_total}",
    ]
    if la.get("count"):
        lines.append(
            f"- 胜率: **{la.get('win_rate')}%** | 均收益: **{la.get('avg_return_pct')}%** | "
            f"中位: **{la.get('median_return_pct')}%** | 最差: **{la.get('worst_return_pct')}%** | 最优: **{la.get('best_return_pct')}%**"
        )
    lines.extend(
        [
            "",
            "## 层 B：分钟首次触发价",
            "",
            f"- 触发买点: **{len(entries)}** | 未触发: **{len(non_entries)}** | 触发率: **{payload['layer_b']['entry_rate_pct']}%**",
        ]
    )
    if t2b.get("count"):
        lines.append(
            f"- **T+2 收盘**（相对触发价）: 胜率 **{t2b.get('win_rate')}%**，均收益 **{t2b.get('avg_return_pct')}%**，中位 **{t2b.get('median_return_pct')}%**"
        )
    lines.extend(["", "## 对照摘要", "", "| 维度 | 层 A 净收益（2 日） | 层 B T+2 收盘（触发价） |", "| --- | --- | --- |"])
    la_wr = la.get("win_rate")
    lb_wr = t2b.get("win_rate")
    la_avg = la.get("avg_return_pct")
    lb_avg = t2b.get("avg_return_pct")
    lines.append(
        f"| 胜率 | {la_wr if la_wr is not None else '-'}% | {lb_wr if lb_wr is not None else '-'}% |"
    )
    lines.append(
        f"| 平均收益 | {la_avg if la_avg is not None else '-'}% | {lb_avg if lb_avg is not None else '-'}% |"
    )
    lines.extend(
        [
            "",
            "> 说明：层 A 为「假设信号日开盘成交」的简化回测；层 B 为「实际等到分时买点」的价量口径，二者样本集合相同但**成交价与时间不同**，不可直接比绝对数值高低，只宜看方向是否一致。",
            "",
            "## 规律提炼",
            "",
        ]
    )
    for ins in payload["insights"]:
        lines.append(f"- {ins}")

    lines.extend(
        [
            "",
            "### 层 B：按排名",
            "",
            "| 排名 | 样本数 | T+2 胜率 | T+2 均值 |",
            "| --- | ---: | ---: | ---: |",
        ]
    )
    for row in payload["layer_b"]["by_rank"]:
        t2m = row["T+2_close"]
        lines.append(
            f"| {row['rank']} | {row['sample_count']} | "
            f"{t2m.get('win_rate') if t2m.get('win_rate') is not None else '-'}% | "
            f"{t2m.get('avg_return_pct') if t2m.get('avg_return_pct') is not None else '-'}% |"
        )

    lines.extend(
        [
            "",
            "### 明细（前 30 条，完整见 JSON）",
            "",
            "| 信号日 | 代码 | 排名 | 层A净收益 | 触发时间 | T+2 |",
            "| --- | --- | ---: | ---: | --- | ---: |",
        ]
    )
    for rec in entries[:30]:
        a = rec.get("layer_a_net_ret")
        t2v = rec.get("T+2_close_ret")
        lines.append(
            f"| {rec['signal_date']} | {rec['symbol']} | {rec['rank']} | "
            f"{fmt_pct(a) if a is not None else '-'} | {rec.get('entry_time', '')} | "
            f"{fmt_pct(t2v) if t2v is not None else '-'} |"
        )

    out_md.write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({"json": str(out_json), "markdown": str(out_md)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
