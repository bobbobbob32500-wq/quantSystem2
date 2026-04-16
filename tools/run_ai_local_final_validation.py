# -*- coding: utf-8 -*-
"""
Run local final-release validation for AI integration.

Usage:
  python tools/run_ai_local_final_validation.py
  python tools/run_ai_local_final_validation.py --config config/ai_local_final_validation.yaml
"""

from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import sys
import time
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Tuple

import yaml


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "config" / "ai_local_final_validation.yaml"


@dataclass
class CheckResult:
    name: str
    stage: str
    passed: bool
    required: bool
    duration_sec: float
    summary: str
    details: Dict[str, Any]


def _load_yaml(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _run_command(cmd: List[str], timeout_sec: int) -> Tuple[int, str, str, float]:
    start = time.perf_counter()
    proc = subprocess.run(
        cmd,
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=timeout_sec,
        encoding="utf-8",
        errors="replace",
    )
    duration = time.perf_counter() - start
    return proc.returncode, proc.stdout, proc.stderr, duration


def run_pytest_suites(config: Dict[str, Any]) -> List[CheckResult]:
    suites = list(config.get("validation", {}).get("pytest_suites") or [])
    results: List[CheckResult] = []
    for suite in suites:
        name = str(suite.get("name") or "unnamed_suite")
        stage = str(suite.get("stage") or "functional")
        required = bool(suite.get("required", True))
        timeout_sec = int(suite.get("timeout_sec", 600))
        raw_cmd = [str(x) for x in (suite.get("command") or [])]
        cmd = [x.replace("{python}", sys.executable) for x in raw_cmd]
        if not cmd:
            results.append(
                CheckResult(
                    name=name,
                    stage=stage,
                    passed=False,
                    required=required,
                    duration_sec=0.0,
                    summary="Missing command in suite config",
                    details={"suite": suite},
                )
            )
            continue

        try:
            code, out, err, duration = _run_command(cmd, timeout_sec=timeout_sec)
            passed = code == 0
            summary = "Passed" if passed else f"Failed (exit_code={code})"
            results.append(
                CheckResult(
                    name=name,
                    stage=stage,
                    passed=passed,
                    required=required,
                    duration_sec=duration,
                    summary=summary,
                    details={
                        "command": cmd,
                        "stdout_tail": out[-5000:],
                        "stderr_tail": err[-5000:],
                    },
                )
            )
        except subprocess.TimeoutExpired:
            results.append(
                CheckResult(
                    name=name,
                    stage=stage,
                    passed=False,
                    required=required,
                    duration_sec=float(timeout_sec),
                    summary=f"Timeout ({timeout_sec}s)",
                    details={"command": cmd},
                )
            )
    return results


def run_api_perf_probe(config: Dict[str, Any]) -> CheckResult:
    perf_cfg = config.get("validation", {}).get("performance", {}) or {}
    endpoint = str(perf_cfg.get("endpoint", "/api/ai/status"))
    iterations = int(perf_cfg.get("iterations", 30))
    warmup = int(perf_cfg.get("warmup", 5))
    p95_threshold_ms = float(perf_cfg.get("p95_threshold_ms", 500.0))
    max_unavailable_ratio = float(perf_cfg.get("max_unavailable_ratio", 0.0))

    start = time.perf_counter()
    try:
        if str(ROOT) not in sys.path:
            sys.path.insert(0, str(ROOT))
        from fastapi.testclient import TestClient
        from src.api.app import app

        client = TestClient(app)
        for _ in range(max(warmup, 0)):
            client.get(endpoint)

        costs_ms: List[float] = []
        failures = 0
        unavailable_count = 0
        for _ in range(max(iterations, 1)):
            t0 = time.perf_counter()
            resp = client.get(endpoint)
            elapsed_ms = (time.perf_counter() - t0) * 1000.0
            if resp.status_code != 200:
                failures += 1
            else:
                try:
                    body = resp.json()
                    if isinstance(body, dict) and body.get("available") is False:
                        unavailable_count += 1
                except Exception:
                    pass
            costs_ms.append(elapsed_ms)

        costs_ms.sort()
        p95_index = min(int(len(costs_ms) * 0.95), len(costs_ms) - 1)
        p95_ms = costs_ms[p95_index]
        p50_ms = statistics.median(costs_ms)
        max_ms = max(costs_ms)
        unavailable_ratio = unavailable_count / max(len(costs_ms), 1)

        passed = (
            failures == 0
            and p95_ms <= p95_threshold_ms
            and unavailable_ratio <= max_unavailable_ratio
        )
        summary = (
            f"p95={p95_ms:.1f}ms <= {p95_threshold_ms:.1f}ms, unavailable_ratio={unavailable_ratio:.2%}"
            if passed
            else f"p95={p95_ms:.1f}ms, failures={failures}, unavailable_ratio={unavailable_ratio:.2%}"
        )
        return CheckResult(
            name="api_status_perf_probe",
            stage="performance",
            passed=passed,
            required=True,
            duration_sec=time.perf_counter() - start,
            summary=summary,
            details={
                "endpoint": endpoint,
                "iterations": iterations,
                "p50_ms": round(p50_ms, 3),
                "p95_ms": round(p95_ms, 3),
                "max_ms": round(max_ms, 3),
                "failures": failures,
                "threshold_ms": p95_threshold_ms,
                "unavailable_count": unavailable_count,
                "unavailable_ratio": round(unavailable_ratio, 6),
                "max_unavailable_ratio": max_unavailable_ratio,
            },
        )
    except Exception as exc:  # pragma: no cover - defensive path
        return CheckResult(
            name="api_status_perf_probe",
            stage="performance",
            passed=False,
            required=True,
            duration_sec=time.perf_counter() - start,
            summary=f"Probe crashed: {exc}",
            details={"error": str(exc)},
        )


def run_security_checks(config: Dict[str, Any]) -> CheckResult:
    sec_cfg = config.get("validation", {}).get("security", {}) or {}
    require_action_execution_disabled = bool(sec_cfg.get("require_action_execution_disabled", True))
    require_empty_static_api_key = bool(sec_cfg.get("require_empty_static_api_key", True))

    start = time.perf_counter()
    issues: List[str] = []
    checks: Dict[str, Any] = {}

    ai_cfg_path = ROOT / "config" / "ai_config.yaml"
    ai_cfg = _load_yaml(ai_cfg_path) if ai_cfg_path.exists() else {}
    ai_section = ai_cfg.get("ai", {}) if isinstance(ai_cfg, dict) else {}
    features = ai_section.get("features", {}) if isinstance(ai_section, dict) else {}

    action_execution = bool(features.get("action_execution", False))
    checks["action_execution"] = action_execution
    if require_action_execution_disabled and action_execution:
        issues.append("ai.features.action_execution must stay false for local final release.")

    for provider in ("deepseek", "local_deepseek"):
        provider_cfg = ai_section.get(provider, {}) if isinstance(ai_section, dict) else {}
        api_key = str(provider_cfg.get("api_key", "") or "").strip()
        checks[f"{provider}.api_key_len"] = len(api_key)
        if require_empty_static_api_key and api_key:
            issues.append(f"config.ai.{provider}.api_key should be empty and read from env.")

    passed = not issues
    return CheckResult(
        name="ai_security_baseline",
        stage="security",
        passed=passed,
        required=True,
        duration_sec=time.perf_counter() - start,
        summary="No blocking security baseline issue" if passed else "; ".join(issues),
        details={"checks": checks, "issues": issues},
    )


def run_ux_checks(config: Dict[str, Any]) -> CheckResult:
    ux_cfg = config.get("validation", {}).get("ux", {}) or {}
    require_alias = bool(ux_cfg.get("require_butler_hyphen_alias", True))

    start = time.perf_counter()
    checks: Dict[str, Any] = {}
    issues: List[str] = []

    app_path = ROOT / "src" / "api" / "app.py"
    app_text = app_path.read_text(encoding="utf-8", errors="replace")
    required_routes = [
        "/api/butler/risk-check",
        "/api/butler/signal-analysis",
        "/api/butler/last-briefing",
        "/api/butler/last-review",
    ]
    for route in required_routes:
        checks[route] = route in app_text
    if require_alias and not all(checks.values()):
        issues.append("Butler hyphen aliases are missing in API routes.")

    passed = not issues
    return CheckResult(
        name="ai_ux_compatibility",
        stage="ux",
        passed=passed,
        required=True,
        duration_sec=time.perf_counter() - start,
        summary="UX compatibility checks passed" if passed else "; ".join(issues),
        details={"checks": checks, "issues": issues},
    )


def _gate_summary(results: List[CheckResult]) -> Dict[str, Any]:
    required_failed = [r.name for r in results if r.required and not r.passed]
    by_stage: Dict[str, Dict[str, int]] = {}
    for r in results:
        stage = r.stage
        by_stage.setdefault(stage, {"total": 0, "passed": 0, "failed": 0})
        by_stage[stage]["total"] += 1
        by_stage[stage]["passed" if r.passed else "failed"] += 1
    return {
        "overall_passed": len(required_failed) == 0,
        "required_failed": required_failed,
        "by_stage": by_stage,
    }


def _write_reports(
    report_dir: Path,
    timestamp: str,
    results: List[CheckResult],
    summary: Dict[str, Any],
) -> Tuple[Path, Path]:
    report_dir.mkdir(parents=True, exist_ok=True)
    json_path = report_dir / f"ai_local_final_validation_{timestamp}.json"
    md_path = report_dir / f"ai_local_final_validation_{timestamp}.md"

    payload = {
        "generated_at": timestamp,
        "results": [asdict(r) for r in results],
        "summary": summary,
    }
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        "# AI本地最终版验证报告",
        "",
        f"- 生成时间: {timestamp}",
        f"- 总体结论: {'通过' if summary.get('overall_passed') else '未通过'}",
        "",
        "## 阶段统计",
    ]
    by_stage = summary.get("by_stage", {})
    for stage in ("functional", "performance", "security", "ux"):
        item = by_stage.get(stage)
        if not item:
            continue
        lines.append(
            f"- {stage}: 通过 {item['passed']} / 总计 {item['total']} / 失败 {item['failed']}"
        )

    lines.extend(["", "## 检查明细"])
    for r in results:
        lines.append(
            f"- [{ 'PASS' if r.passed else 'FAIL' }] {r.stage}/{r.name}: {r.summary} ({r.duration_sec:.2f}s)"
        )

    if summary.get("required_failed"):
        lines.extend(["", "## 修复优先级建议"])
        for idx, name in enumerate(summary["required_failed"], start=1):
            lines.append(f"{idx}. 优先修复阻塞项: `{name}`")
    else:
        lines.extend(["", "## 发布建议", "1. 可进入最终版本确认与本地部署。"])

    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return json_path, md_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Run local final-release validation for AI integration.")
    parser.add_argument("--config", type=str, default=str(DEFAULT_CONFIG), help="Validation config YAML path.")
    args = parser.parse_args()

    cfg_path = Path(args.config)
    if not cfg_path.is_absolute():
        cfg_path = ROOT / cfg_path
    if not cfg_path.exists():
        raise FileNotFoundError(f"Config not found: {cfg_path}")

    config = _load_yaml(cfg_path)
    validation_cfg = config.get("validation", {}) if isinstance(config, dict) else {}
    report_dir = ROOT / str(validation_cfg.get("report_dir", "reports/release"))

    results: List[CheckResult] = []
    results.extend(run_pytest_suites(config))
    results.append(run_api_perf_probe(config))
    results.append(run_security_checks(config))
    results.append(run_ux_checks(config))

    summary = _gate_summary(results)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path, md_path = _write_reports(report_dir=report_dir, timestamp=timestamp, results=results, summary=summary)

    print(f"[AI Final Validation] overall_passed={summary['overall_passed']}")
    print(f"[AI Final Validation] markdown_report={md_path}")
    print(f"[AI Final Validation] json_report={json_path}")

    return 0 if summary["overall_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
