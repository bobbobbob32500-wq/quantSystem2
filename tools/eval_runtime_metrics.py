#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
从量化系统数据库中提取运行监控指标（health_snapshot/runtime_incident），用于稳定性评估报告。

使用：
  python tools/eval_runtime_metrics.py
  python tools/eval_runtime_metrics.py --db data/database/quant_system.db --hours 24
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def _safe_json_loads(payload: Optional[str]) -> Dict[str, Any]:
    if not payload:
        return {}
    try:
        return json.loads(payload)
    except Exception:
        return {}


def _table_exists(cur: sqlite3.Cursor, name: str) -> bool:
    row = cur.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (name,),
    ).fetchone()
    return row is not None


def _parse_time(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M:%S.%f"):
        try:
            return datetime.strptime(value, fmt)
        except Exception:
            pass
    return None


def _percentile(values: List[float], p: float) -> Optional[float]:
    if not values:
        return None
    ordered = sorted(values)
    idx = int(max(0, min(len(ordered) - 1, round((len(ordered) - 1) * p))))
    return float(ordered[idx])


@dataclass
class RuntimeReport:
    meta: Dict[str, Any]
    health_snapshot: Dict[str, Any]
    runtime_incident: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "meta": self.meta,
            "health_snapshot": self.health_snapshot,
            "runtime_incident": self.runtime_incident,
        }


def build_runtime_report(db_path: Path, lookback_hours: int = 24) -> RuntimeReport:
    if not db_path.exists():
        raise FileNotFoundError(f"数据库不存在: {db_path}")

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    now = datetime.now()
    since = now - timedelta(hours=max(1, int(lookback_hours)))
    since_str = since.strftime("%Y-%m-%d %H:%M:%S")

    meta = {
        "db_path": str(db_path),
        "generated_at": now.strftime("%Y-%m-%d %H:%M:%S"),
        "lookback_hours": int(lookback_hours),
        "since": since_str,
    }

    health_summary: Dict[str, Any] = {"available": _table_exists(cur, "health_snapshot")}
    incident_summary: Dict[str, Any] = {"available": _table_exists(cur, "runtime_incident")}

    if health_summary["available"]:
        row = cur.execute(
            "SELECT COUNT(1) c, MIN(snapshot_time) mn, MAX(snapshot_time) mx FROM health_snapshot"
        ).fetchone()
        health_summary.update(
            {
                "count": int(row["c"] or 0),
                "min_snapshot_time": row["mn"],
                "max_snapshot_time": row["mx"],
            }
        )

        recent = cur.execute(
            """
            SELECT snapshot_time, source, uptime_seconds, success_total, incident_total,
                   severity_json, latency_summary_json, snapshot_json
            FROM health_snapshot
            WHERE snapshot_time >= ?
            ORDER BY snapshot_time DESC
            """,
            (since_str,),
        ).fetchall()

        by_source = Counter()
        incident_totals = []
        success_totals = []
        uptime_samples = []
        latency_p95_by_component: Dict[str, List[float]] = defaultdict(list)

        latest_snapshot: Optional[Dict[str, Any]] = None
        for i, r in enumerate(recent):
            by_source[str(r["source"] or "unknown")] += 1
            incident_totals.append(float(r["incident_total"] or 0))
            success_totals.append(float(r["success_total"] or 0))
            uptime_samples.append(float(r["uptime_seconds"] or 0))

            latency_summary = _safe_json_loads(r["latency_summary_json"])
            for comp, metrics in (latency_summary or {}).items():
                if not isinstance(metrics, dict):
                    continue
                p95 = metrics.get("p95_ms")
                if p95 is None:
                    continue
                try:
                    latency_p95_by_component[str(comp)].append(float(p95))
                except Exception:
                    pass

            if i == 0:
                latest_snapshot = {
                    "snapshot_time": r["snapshot_time"],
                    "source": r["source"],
                    "uptime_seconds": r["uptime_seconds"],
                    "success_total": r["success_total"],
                    "incident_total": r["incident_total"],
                    "severity_counter": _safe_json_loads(r["severity_json"]),
                    "snapshot": _safe_json_loads(r["snapshot_json"]),
                }

        latency_component_p95 = {
            comp: {
                "p95_ms_of_p95": round(_percentile(values, 0.95) or 0.0, 3),
                "samples": len(values),
            }
            for comp, values in sorted(latency_p95_by_component.items(), key=lambda x: (-len(x[1]), x[0]))
        }

        health_summary["lookback"] = {
            "snapshot_rows": len(recent),
            "by_source": dict(by_source),
            "incident_total_p95": round(_percentile(incident_totals, 0.95) or 0.0, 3),
            "success_total_p95": round(_percentile(success_totals, 0.95) or 0.0, 3),
            "uptime_seconds_p95": round(_percentile(uptime_samples, 0.95) or 0.0, 3),
            "latency_component_p95": latency_component_p95,
        }
        health_summary["latest_snapshot"] = latest_snapshot

    if incident_summary["available"]:
        row = cur.execute(
            "SELECT COUNT(1) c, MIN(incident_time) mn, MAX(incident_time) mx FROM runtime_incident"
        ).fetchone()
        incident_summary.update(
            {
                "count": int(row["c"] or 0),
                "min_incident_time": row["mn"],
                "max_incident_time": row["mx"],
            }
        )

        recent = cur.execute(
            """
            SELECT incident_time, severity, category, component, title, error_code, retryable
            FROM runtime_incident
            WHERE incident_time >= ?
            ORDER BY incident_time DESC
            """,
            (since_str,),
        ).fetchall()

        severity_counter = Counter()
        category_counter = Counter()
        component_counter = Counter()
        retryable_counter = Counter()

        latest_rows = []
        for r in recent[:20]:
            severity_counter[str(r["severity"] or "unknown")] += 1
            category_counter[str(r["category"] or "unknown")] += 1
            component_counter[str(r["component"] or "unknown")] += 1
            retryable_counter["retryable" if int(r["retryable"] or 0) else "non_retryable"] += 1
            latest_rows.append(
                {
                    "incident_time": r["incident_time"],
                    "severity": r["severity"],
                    "category": r["category"],
                    "component": r["component"],
                    "title": r["title"],
                    "error_code": r["error_code"],
                    "retryable": bool(int(r["retryable"] or 0)),
                }
            )

        # 粗略 MTBF：仅在“近 lookback”内按 incident_time 排序计算相邻间隔均值
        times = [_parse_time(r["incident_time"]) for r in recent]
        times = [t for t in times if t is not None]
        times = sorted(set(times))
        mtbf_seconds = None
        if len(times) >= 2:
            gaps = [(times[i] - times[i - 1]).total_seconds() for i in range(1, len(times))]
            if gaps:
                mtbf_seconds = sum(gaps) / len(gaps)

        incident_summary["lookback"] = {
            "incident_rows": len(recent),
            "severity_counter": dict(severity_counter),
            "category_counter": dict(category_counter),
            "top_components": dict(component_counter.most_common(15)),
            "retryable_counter": dict(retryable_counter),
            "mtbf_seconds_estimate": round(mtbf_seconds, 3) if mtbf_seconds is not None else None,
            "latest": latest_rows,
        }

    conn.close()
    return RuntimeReport(meta=meta, health_snapshot=health_summary, runtime_incident=incident_summary)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default="data/database/quant_system.db", help="SQLite 数据库路径")
    parser.add_argument("--hours", type=int, default=24, help="统计回看窗口（小时）")
    parser.add_argument("--json", action="store_true", help="以 JSON 输出（便于机器处理）")
    args = parser.parse_args()

    report = build_runtime_report(Path(args.db), lookback_hours=args.hours)
    payload = report.to_dict()

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return

    # 人类友好输出
    print("=== 运行监控指标摘要 ===")
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

