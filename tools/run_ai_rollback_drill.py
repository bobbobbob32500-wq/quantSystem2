# -*- coding: utf-8 -*-
"""
Run a dry-run rollback drill for AI local release.

Usage:
  python tools/run_ai_rollback_drill.py
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List


ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "reports" / "release"


def _run(cmd: List[str], timeout_sec: int = 1200) -> Dict[str, object]:
    started = time.perf_counter()
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_sec,
        )
        return {
            "ok": proc.returncode == 0,
            "exit_code": proc.returncode,
            "duration_sec": time.perf_counter() - started,
            "stdout_tail": proc.stdout[-6000:],
            "stderr_tail": proc.stderr[-6000:],
        }
    except subprocess.TimeoutExpired:
        return {
            "ok": False,
            "exit_code": 124,
            "duration_sec": time.perf_counter() - started,
            "stdout_tail": "",
            "stderr_tail": "timeout",
        }


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = OUT_DIR / f"ai_rollback_drill_{ts}.json"
    md_path = OUT_DIR / f"ai_rollback_drill_{ts}.md"

    checks: Dict[str, Dict[str, object]] = {}
    checks["baseline_smoke"] = _run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-m",
            "smoke",
            "tests/test_ai_mobile_api_smoke.py",
            "tests/test_mobile_api_contract.py",
        ],
        timeout_sec=1200,
    )
    checks["final_validation"] = _run([sys.executable, "tools/run_ai_local_final_validation.py"], timeout_sec=1500)

    prev_reports = sorted(OUT_DIR.glob("ai_local_final_validation_*.json"))
    checks["rollback_anchor_exists"] = {
        "ok": len(prev_reports) > 0,
        "count": len(prev_reports),
        "latest": str(prev_reports[-1]) if prev_reports else "",
    }

    overall = all(bool(item.get("ok")) for item in checks.values())
    payload = {
        "generated_at": ts,
        "overall_passed": overall,
        "checks": checks,
    }
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        "# AI Rollback Drill Report",
        "",
        f"- Generated: {ts}",
        f"- Overall: {'PASS' if overall else 'FAIL'}",
        "",
        "## Checks",
    ]
    for name, item in checks.items():
        lines.append(f"- {name}: {'PASS' if item.get('ok') else 'FAIL'}")
    lines.extend(
        [
            "",
            "## Drill Interpretation",
            "- PASS: baseline smoke and re-validation are reproducible; rollback anchor exists.",
            "- FAIL: do not release before fixing drill failures and rerunning.",
        ]
    )
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"[AI Rollback Drill] overall_passed={overall}")
    print(f"[AI Rollback Drill] markdown_report={md_path}")
    print(f"[AI Rollback Drill] json_report={json_path}")
    return 0 if overall else 1


if __name__ == "__main__":
    raise SystemExit(main())

