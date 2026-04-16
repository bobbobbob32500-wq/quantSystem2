# -*- coding: utf-8 -*-
"""
Run real LLM smoke gate for release readiness.

Usage:
  python tools/run_real_llm_smoke_gate.py
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List


ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "reports" / "release"


def _run_cmd(cmd: List[str], env: Dict[str, str], timeout_sec: int = 1200) -> Dict[str, object]:
    started = time.perf_counter()
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
            timeout=timeout_sec,
        )
        return {
            "exit_code": proc.returncode,
            "stdout": proc.stdout[-10000:],
            "stderr": proc.stderr[-10000:],
            "duration_sec": time.perf_counter() - started,
            "timed_out": False,
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "exit_code": 124,
            "stdout": (exc.stdout or "")[-10000:],
            "stderr": (exc.stderr or "")[-10000:],
            "duration_sec": time.perf_counter() - started,
            "timed_out": True,
        }


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = OUT_DIR / f"ai_real_llm_smoke_{ts}.json"
    md_path = OUT_DIR / f"ai_real_llm_smoke_{ts}.md"

    env = dict(os.environ)
    env["RUN_AI_LLM_SMOKE"] = "1"
    cmd = [
        sys.executable,
        "-m",
        "pytest",
        "tests/test_ai_mobile_api_smoke.py",
        "-k",
        "test_ai_chat_and_quick_ask_llm",
    ]
    result = _run_cmd(cmd, env=env)
    passed = int(result["exit_code"]) == 0

    payload = {
        "generated_at": ts,
        "passed": passed,
        "command": cmd,
        "run": result,
    }
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        "# Real LLM Smoke Gate",
        "",
        f"- Generated: {ts}",
        f"- Command: `{' '.join(cmd)}`",
        f"- Result: {'PASS' if passed else 'FAIL'}",
        f"- Duration: {float(result['duration_sec']):.2f}s",
        "",
        "## Notes",
        "- This gate verifies real model connectivity and end-to-end response path.",
        "- It should pass before local final release sign-off.",
    ]
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"[AI Real LLM Smoke] passed={passed}")
    print(f"[AI Real LLM Smoke] markdown_report={md_path}")
    print(f"[AI Real LLM Smoke] json_report={json_path}")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())

