# -*- coding: utf-8 -*-
"""
Generate daily AI SLO summary from local validation JSON reports.

Usage:
  python tools/generate_ai_slo_daily_report.py
  python tools/generate_ai_slo_daily_report.py --days 7
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List


ROOT = Path(__file__).resolve().parents[1]
REPORT_DIR = ROOT / "reports" / "release"
PATTERN = "ai_local_final_validation_*.json"


def _load_json(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _extract_perf(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    for item in results:
        if item.get("name") == "api_status_perf_probe":
            return dict(item.get("details") or {})
    return {}


def _extract_status(summary: Dict[str, Any]) -> bool:
    return bool(summary.get("overall_passed", False))


def _parse_report_time(path: Path) -> datetime | None:
    # filename: ai_local_final_validation_YYYYMMDD_HHMMSS.json
    stem = path.stem
    tail = stem.replace("ai_local_final_validation_", "")
    try:
        return datetime.strptime(tail, "%Y%m%d_%H%M%S")
    except ValueError:
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate daily AI SLO summary.")
    parser.add_argument("--days", type=int, default=1, help="Look-back days for summary window.")
    args = parser.parse_args()

    now = datetime.now()
    start = now - timedelta(days=max(args.days, 1))
    files = sorted(REPORT_DIR.glob(PATTERN))
    records: List[Dict[str, Any]] = []
    for path in files:
        ts = _parse_report_time(path)
        if ts is None or ts < start:
            continue
        payload = _load_json(path)
        summary = payload.get("summary") or {}
        results = payload.get("results") or []
        perf = _extract_perf(results)
        records.append(
            {
                "time": ts,
                "file": str(path),
                "overall_passed": _extract_status(summary),
                "p95_ms": perf.get("p95_ms"),
                "unavailable_ratio": perf.get("unavailable_ratio"),
            }
        )

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    out_stamp = now.strftime("%Y%m%d")
    md_path = REPORT_DIR / f"ai_slo_daily_{out_stamp}.md"
    json_path = REPORT_DIR / f"ai_slo_daily_{out_stamp}.json"

    total = len(records)
    success = sum(1 for r in records if r["overall_passed"])
    success_rate = (success / total) if total else 0.0
    p95_values = [float(r["p95_ms"]) for r in records if r["p95_ms"] is not None]
    unavailable_values = [
        float(r["unavailable_ratio"]) for r in records if r["unavailable_ratio"] is not None
    ]
    avg_p95 = (sum(p95_values) / len(p95_values)) if p95_values else None
    max_p95 = max(p95_values) if p95_values else None
    avg_unavailable = (sum(unavailable_values) / len(unavailable_values)) if unavailable_values else None

    output = {
        "generated_at": now.strftime("%Y-%m-%d %H:%M:%S"),
        "window_days": args.days,
        "total_validations": total,
        "success_count": success,
        "success_rate": success_rate,
        "avg_p95_ms": avg_p95,
        "max_p95_ms": max_p95,
        "avg_unavailable_ratio": avg_unavailable,
        "records": records,
    }
    json_path.write_text(json.dumps(output, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    lines = [
        "# AI SLO Daily Report",
        "",
        f"- Generated: {output['generated_at']}",
        f"- Window: last {args.days} day(s)",
        f"- Validation runs: {total}",
        f"- Success rate: {success_rate:.2%}",
        f"- Avg p95: {avg_p95:.3f} ms" if avg_p95 is not None else "- Avg p95: N/A",
        f"- Max p95: {max_p95:.3f} ms" if max_p95 is not None else "- Max p95: N/A",
        f"- Avg unavailable ratio: {avg_unavailable:.2%}" if avg_unavailable is not None else "- Avg unavailable ratio: N/A",
        "",
        "## Records",
    ]
    if not records:
        lines.append("- No validation records in the selected window.")
    else:
        for r in records:
            lines.append(
                f"- {r['time'].strftime('%Y-%m-%d %H:%M:%S')}: passed={r['overall_passed']}, p95_ms={r['p95_ms']}, unavailable_ratio={r['unavailable_ratio']}"
            )

    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"[AI SLO Daily] markdown_report={md_path}")
    print(f"[AI SLO Daily] json_report={json_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

