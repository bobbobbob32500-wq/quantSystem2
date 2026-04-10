#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
基于二次启动真实信号日与历史 5 分钟数据，回放盘中最佳买点并搜索卖点/止损规则。
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.modules.backtest.history_recommendation_db import HistoryRecommendationDB
from src.modules.secondary_launch_intraday import detect_secondary_launch_signal


WINDOW_MINUTES = [5, 15, 30, 60]
STOP_LOSS_GRID = [-0.015, -0.02, -0.025, -0.03, -0.04]
TAKE_PROFIT_GRID = [0.02, 0.03, 0.04, 0.05, 0.06, 0.08]
TRAILING_GRID = [None, 0.012, 0.015, 0.02, 0.025]
MAX_HOLD_GRID = [15, 30, 60, 120, 240]


@dataclass
class ExitRule:
    stop_loss_pct: float
    take_profit_pct: float
    trailing_stop_pct: Optional[float]
    max_hold_minutes: int

    @property
    def label(self) -> str:
        trailing = "none" if self.trailing_stop_pct is None else f"{self.trailing_stop_pct:.3f}"
        return (
            f"SL {self.stop_loss_pct:.1%} | TP {self.take_profit_pct:.1%} | "
            f"TR {trailing} | HOLD {self.max_hold_minutes}m"
        )


def _iter_exit_rules() -> Iterable[ExitRule]:
    for sl in STOP_LOSS_GRID:
        for tp in TAKE_PROFIT_GRID:
            for trailing in TRAILING_GRID:
                for hold in MAX_HOLD_GRID:
                    yield ExitRule(sl, tp, trailing, hold)


def _load_report(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _trade_date(signal_date: str) -> str:
    s = str(signal_date)
    return f"{s[:4]}-{s[4:6]}-{s[6:8]}"


def _load_session(db: HistoryRecommendationDB, symbol: str, signal_date: str) -> pd.DataFrame:
    frame = db.get_intraday_data(symbol)
    if frame.empty:
        return frame
    frame = frame.copy()
    frame["trade_date_str"] = frame["trade_time"].dt.strftime("%Y-%m-%d")
    day = _trade_date(signal_date)
    frame = frame[frame["trade_date_str"] == day].copy()
    frame = frame.sort_values("trade_time").reset_index(drop=True)
    return frame


def _resolve_entry(
    detail: Dict[str, Any],
    frame: pd.DataFrame,
    daily_features: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    if frame.empty:
        return None
    candidate = {
        "symbol": detail["ts_code"],
        "name": detail.get("name", ""),
        "score": 80.0 if int(detail.get("rank", 9) or 9) == 1 else 74.0,
        "pool_type": "core" if int(detail.get("rank", 9) or 9) == 1 else "reserve",
        "industry": "",
        "strategy_profile": "secondary_launch",
    }
    if daily_features:
        candidate.update(daily_features)
    neutral_industry = {"score": 50.0, "level": "neutral", "industry": "未知"}

    for idx in range(len(frame)):
        now = pd.Timestamp(frame.iloc[idx]["trade_time"]).to_pydatetime()
        window = frame.iloc[: idx + 1].copy()
        current_price = float(window.iloc[-1]["close"])
        quote = {"price": current_price}
        signal = detect_secondary_launch_signal(
            candidate=candidate,
            quote=quote,
            now=now,
            minute_df=window,
            industry_confirm=neutral_industry,
        )
        if signal.signal:
            return {
                "entry_idx": idx,
                "entry_time": now,
                "entry_price": current_price,
                "signal_type": str(signal.signal_type or ""),
                "reason": str(signal.reason or ""),
                "confidence": float(signal.confidence or 0.0),
                "details": dict(signal.details or {}),
                "candidate": candidate,
            }
    return None


def _forward_returns(frame: pd.DataFrame, entry_idx: int, entry_price: float) -> Dict[str, Optional[float]]:
    result: Dict[str, Optional[float]] = {}
    entry_time = pd.Timestamp(frame.iloc[entry_idx]["trade_time"])
    for minutes in WINDOW_MINUTES:
        target_time = entry_time + timedelta(minutes=minutes)
        future = frame[frame["trade_time"] >= target_time]
        if future.empty:
            result[f"{minutes}m"] = None
            continue
        exit_price = float(future.iloc[0]["close"])
        result[f"{minutes}m"] = exit_price / entry_price - 1.0
    return result


def _simulate_exit(frame: pd.DataFrame, entry_idx: int, rule: ExitRule) -> Dict[str, Any]:
    entry_row = frame.iloc[entry_idx]
    entry_time = pd.Timestamp(entry_row["trade_time"])
    entry_price = float(entry_row["close"])
    stop_price = entry_price * (1.0 + rule.stop_loss_pct)
    take_price = entry_price * (1.0 + rule.take_profit_pct)
    deadline = entry_time + timedelta(minutes=rule.max_hold_minutes)
    peak_price = entry_price

    for idx in range(entry_idx + 1, len(frame)):
        row = frame.iloc[idx]
        trade_time = pd.Timestamp(row["trade_time"])
        high = float(row["high"])
        low = float(row["low"])
        close = float(row["close"])
        peak_price = max(peak_price, high)

        if low <= stop_price:
            return {
                "exit_reason": "stop_loss",
                "exit_time": trade_time.strftime("%Y-%m-%d %H:%M:%S"),
                "exit_price": stop_price,
                "return_pct": stop_price / entry_price - 1.0,
            }
        if high >= take_price:
            return {
                "exit_reason": "take_profit",
                "exit_time": trade_time.strftime("%Y-%m-%d %H:%M:%S"),
                "exit_price": take_price,
                "return_pct": take_price / entry_price - 1.0,
            }
        if rule.trailing_stop_pct is not None and peak_price > entry_price:
            trailing_floor = peak_price * (1.0 - rule.trailing_stop_pct)
            if low <= trailing_floor:
                return {
                    "exit_reason": "trailing_stop",
                    "exit_time": trade_time.strftime("%Y-%m-%d %H:%M:%S"),
                    "exit_price": trailing_floor,
                    "return_pct": trailing_floor / entry_price - 1.0,
                }
        if trade_time >= deadline:
            return {
                "exit_reason": "time_exit",
                "exit_time": trade_time.strftime("%Y-%m-%d %H:%M:%S"),
                "exit_price": close,
                "return_pct": close / entry_price - 1.0,
            }

    last_row = frame.iloc[-1]
    last_price = float(last_row["close"])
    return {
        "exit_reason": "session_close",
        "exit_time": pd.Timestamp(last_row["trade_time"]).strftime("%Y-%m-%d %H:%M:%S"),
        "exit_price": last_price,
        "return_pct": last_price / entry_price - 1.0,
    }


def _summarize_rows(rows: List[Dict[str, Any]], key_name: str) -> List[Dict[str, Any]]:
    if not rows:
        return []
    df = pd.DataFrame(rows)
    grouped = df.groupby(key_name, dropna=False)
    results: List[Dict[str, Any]] = []
    for key, grp in grouped:
        ret = pd.to_numeric(grp["return_pct"], errors="coerce").dropna()
        if ret.empty:
            continue
        results.append(
            {
                key_name: key,
                "sample_count": int(len(grp)),
                "win_rate": float((ret > 0).mean()),
                "avg_return": float(ret.mean()),
                "median_return": float(ret.median()),
                "best_return": float(ret.max()),
                "worst_return": float(ret.min()),
            }
        )
    results.sort(key=lambda x: (float(x["avg_return"]), int(x["sample_count"])), reverse=True)
    return results


def _best_rule(rows: List[Dict[str, Any]], signal_type: Optional[str] = None) -> Optional[Dict[str, Any]]:
    subset = rows
    if signal_type:
        subset = [row for row in rows if row.get("signal_type") == signal_type]
    if not subset:
        return None
    df = pd.DataFrame(subset)
    grouped = df.groupby("rule_label", dropna=False)
    ranked = []
    for label, grp in grouped:
        ret = pd.to_numeric(grp["return_pct"], errors="coerce").dropna()
        if ret.empty:
            continue
        ranked.append(
            {
                "rule_label": str(label),
                "signal_type": signal_type or "all",
                "sample_count": int(len(grp)),
                "win_rate": float((ret > 0).mean()),
                "avg_return": float(ret.mean()),
                "median_return": float(ret.median()),
            }
        )
    if not ranked:
        return None
    ranked.sort(key=lambda x: (x["avg_return"], x["win_rate"], x["sample_count"]), reverse=True)
    return ranked[0]


def _format_pct(value: Optional[float]) -> str:
    if value is None:
        return "-"
    return f"{float(value):.2%}"


def build_report(payload: Dict[str, Any]) -> str:
    lines = [
        "# 二次启动盘中最佳买点回放报告",
        "",
        f"- 生成时间: {payload.get('generated_at', '')}",
        f"- 信号样本数: {payload.get('signal_count', 0)}",
        f"- 有效盘中入场数: {payload.get('entry_count', 0)}",
        f"- 未触发盘中入场数: {payload.get('no_entry_count', 0)}",
        f"- 分钟数据来源: `{payload.get('db_path', '')}`",
        "",
        "## 买点子类型对比",
        "",
        "| 子类型 | 样本数 | 胜率 | 平均收益 | 中位收益 | 最佳 | 最差 |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    subtype_summary = payload.get("subtype_summary", [])
    if subtype_summary:
        for item in subtype_summary:
            lines.append(
                f"| {item.get('signal_type', '')} | {item.get('sample_count', 0)} | "
                f"{_format_pct(item.get('win_rate'))} | {_format_pct(item.get('avg_return'))} | "
                f"{_format_pct(item.get('median_return'))} | {_format_pct(item.get('best_return'))} | "
                f"{_format_pct(item.get('worst_return'))} |"
            )
    else:
        lines.append("| - | 0 | - | - | - | - | - |")

    lines.extend(
        [
            "",
            "## 分钟窗口胜率对比",
            "",
            "| 子类型 | 窗口 | 样本数 | 胜率 | 平均收益 | 中位收益 |",
            "| --- | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for item in payload.get("window_summary", []):
        lines.append(
            f"| {item.get('signal_type', '')} | {item.get('window', '')} | {item.get('sample_count', 0)} | "
            f"{_format_pct(item.get('win_rate'))} | {_format_pct(item.get('avg_return'))} | "
            f"{_format_pct(item.get('median_return'))} |"
        )

    lines.extend(
        [
            "",
            "## 最优卖点 / 止损规则",
            "",
            "| 适用范围 | 规则 | 样本数 | 胜率 | 平均收益 | 中位收益 |",
            "| --- | --- | ---: | ---: | ---: | ---: |",
        ]
    )
    for item in payload.get("best_rules", []):
        lines.append(
            f"| {item.get('signal_type', '')} | {item.get('rule_label', '')} | {item.get('sample_count', 0)} | "
            f"{_format_pct(item.get('win_rate'))} | {_format_pct(item.get('avg_return'))} | "
            f"{_format_pct(item.get('median_return'))} |"
        )

    lines.extend(
        [
            "",
            "## 观察结论",
            "",
        ]
    )
    for item in payload.get("insights", []):
        lines.append(f"- {item}")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="回放二次启动盘中最佳买点并搜索卖点规则")
    parser.add_argument(
        "--report-json",
        default="results/secondary_launch_recent_tracking_20260401_023338.json",
        help="二次启动跟踪 JSON",
    )
    parser.add_argument(
        "--db-path",
        default="data/history_recommendation.db",
        help="分钟数据库路径",
    )
    args = parser.parse_args()

    report_path = ROOT / args.report_json
    db_path = ROOT / args.db_path
    report = _load_report(report_path)
    db = HistoryRecommendationDB(str(db_path))

    entries: List[Dict[str, Any]] = []
    window_rows: List[Dict[str, Any]] = []
    rule_rows: List[Dict[str, Any]] = []
    no_entry = 0

    for detail in report.get("details", []):
        symbol = str(detail.get("ts_code") or "").strip().upper()
        signal_date = str(detail.get("signal_date") or "").strip()
        if not symbol or not signal_date:
            continue
        frame = _load_session(db, symbol, signal_date)
        if frame.empty:
            no_entry += 1
            continue
        entry = _resolve_entry(detail, frame)
        if entry is None:
            no_entry += 1
            continue

        subtype = str(entry["signal_type"])
        forward = _forward_returns(frame, entry["entry_idx"], entry["entry_price"])
        entry_record = {
            "symbol": symbol,
            "signal_date": signal_date,
            "name": detail.get("name", ""),
            "signal_type": subtype,
            "entry_time": entry["entry_time"].strftime("%Y-%m-%d %H:%M:%S"),
            "entry_price": entry["entry_price"],
            "confidence": entry["confidence"],
            "rank": detail.get("rank"),
            "return_pct": forward.get("30m"),
        }
        entries.append(entry_record)
        for window_name, ret in forward.items():
            if ret is None:
                continue
            window_rows.append(
                {
                    "signal_type": subtype,
                    "window": window_name,
                    "sample_count": 1,
                    "return_pct": ret,
                }
            )
        for rule in _iter_exit_rules():
            sim = _simulate_exit(frame, entry["entry_idx"], rule)
            rule_rows.append(
                {
                    "signal_type": subtype,
                    "symbol": symbol,
                    "signal_date": signal_date,
                    "rule_label": rule.label,
                    "exit_reason": sim["exit_reason"],
                    "return_pct": sim["return_pct"],
                }
            )

    subtype_summary = _summarize_rows(entries, "signal_type")
    window_summary: List[Dict[str, Any]] = []
    if window_rows:
        wdf = pd.DataFrame(window_rows)
        for (signal_type, window), grp in wdf.groupby(["signal_type", "window"], dropna=False):
            ret = pd.to_numeric(grp["return_pct"], errors="coerce").dropna()
            if ret.empty:
                continue
            window_summary.append(
                {
                    "signal_type": str(signal_type),
                    "window": str(window),
                    "sample_count": int(len(grp)),
                    "win_rate": float((ret > 0).mean()),
                    "avg_return": float(ret.mean()),
                    "median_return": float(ret.median()),
                }
            )
        window_summary.sort(key=lambda x: (x["signal_type"], x["window"]))

    best_rules = []
    overall_best = _best_rule(rule_rows)
    if overall_best:
        best_rules.append({"signal_type": "全部信号", **overall_best})
    for subtype in sorted({item["signal_type"] for item in entries}):
        best = _best_rule(rule_rows, signal_type=subtype)
        if best:
            best_rules.append(best)

    insights: List[str] = []
    if subtype_summary:
        top = subtype_summary[0]
        insights.append(
            f"当前分钟级回放中，`{top.get('signal_type', '')}` 表现最佳，"
            f"样本 `{top.get('sample_count', 0)}` 条，平均收益 `{_format_pct(top.get('avg_return'))}`。"
        )
    if window_summary:
        best_window = sorted(window_summary, key=lambda x: (x["avg_return"], x["sample_count"]), reverse=True)[0]
        insights.append(
            f"最佳观察窗口为 `{best_window.get('signal_type', '')} / {best_window.get('window', '')}`，"
            f"平均收益 `{_format_pct(best_window.get('avg_return'))}`。"
        )
    if best_rules:
        best = best_rules[0]
        insights.append(
            f"当前全样本最优卖点规则为 `{best.get('rule_label', '')}`，"
            f"平均收益 `{_format_pct(best.get('avg_return'))}`，胜率 `{_format_pct(best.get('win_rate'))}`。"
        )
    if not insights:
        insights.append("当前分钟数据虽已补齐，但本轮回放未找到足够有效买点。")

    payload = {
        "generated_at": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S"),
        "report_json": str(report_path),
        "db_path": str(db_path),
        "signal_count": int(len(report.get("details", []))),
        "entry_count": int(len(entries)),
        "no_entry_count": int(no_entry),
        "subtype_summary": subtype_summary,
        "window_summary": window_summary,
        "best_rules": best_rules,
        "entries": entries,
        "insights": insights,
    }

    ts = pd.Timestamp.now().strftime("%Y%m%d_%H%M%S")
    out_json = ROOT / "results" / f"secondary_launch_intraday_replay_{ts}.json"
    out_md = ROOT / "results" / f"secondary_launch_intraday_replay_{ts}.md"
    out_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    out_md.write_text(build_report(payload), encoding="utf-8")
    print(f"Markdown: {out_md}")
    print(f"JSON: {out_json}")
    print(f"Entries: {payload['entry_count']}")
    print(f"NoEntry: {payload['no_entry_count']}")
    for item in insights:
        print(f"- {item}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
