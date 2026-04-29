from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import time
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def spawn_process(name: str, command: list[str], log_path: Path, env: dict[str, str]) -> subprocess.Popen:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    handle = log_path.open("a", encoding="utf-8")
    process = subprocess.Popen(
        command,
        cwd=str(PROJECT_ROOT),
        stdout=handle,
        stderr=subprocess.STDOUT,
        env=env,
    )
    process._portable_log_handle = handle  # type: ignore[attr-defined]
    print(f"{name} 已启动, PID={process.pid}, 日志={log_path}")
    return process


def stop_processes(processes: list[subprocess.Popen]) -> None:
    for process in processes:
        if process.poll() is not None:
            continue
        try:
            process.send_signal(signal.CTRL_BREAK_EVENT if os.name == "nt" else signal.SIGTERM)
        except Exception:
            process.terminate()
    deadline = time.time() + 10
    while time.time() < deadline:
        if all(process.poll() is not None for process in processes):
            break
        time.sleep(0.3)
    for process in processes:
        if process.poll() is None:
            process.kill()
        handle = getattr(process, "_portable_log_handle", None)
        if handle:
            handle.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="启动可迁移基线的后端服务栈")
    parser.add_argument("--dashboard-host", default=os.environ.get("DASHBOARD_HOST", "0.0.0.0"))
    parser.add_argument("--dashboard-port", default=os.environ.get("DASHBOARD_PORT", "8501"))
    parser.add_argument("--api-host", default=os.environ.get("MOBILE_API_HOST", "0.0.0.0"))
    parser.add_argument("--api-port", default=os.environ.get("MOBILE_API_PORT", "8000"))
    parser.add_argument("--skip-service", action="store_true", help="只启动 Dashboard 和 API")
    args = parser.parse_args()

    env = os.environ.copy()
    env["DASHBOARD_HOST"] = str(args.dashboard_host)
    env["DASHBOARD_PORT"] = str(args.dashboard_port)
    env["MOBILE_API_HOST"] = str(args.api_host)
    env["MOBILE_API_PORT"] = str(args.api_port)

    log_root = PROJECT_ROOT / "logs" / "portable"
    processes: list[subprocess.Popen] = []
    try:
        if not args.skip_service:
            processes.append(
                spawn_process(
                    "quant-service",
                    [sys.executable, "run_service.py"],
                    log_root / "quant-service.log",
                    env,
                )
            )
        processes.append(
            spawn_process(
                "dashboard",
                [sys.executable, "start_dashboard.py"],
                log_root / "dashboard.log",
                env,
            )
        )
        processes.append(
            spawn_process(
                "mobile-api",
                [sys.executable, "src/api/app.py"],
                log_root / "mobile-api.log",
                env,
            )
        )

        print("服务栈已启动，按 Ctrl+C 停止。")
        while True:
            time.sleep(1)
            for process in processes:
                if process.poll() is not None:
                    print(f"检测到进程退出: PID={process.pid}, code={process.returncode}")
                    return process.returncode or 0
    except KeyboardInterrupt:
        print("收到停止信号，正在关闭服务...")
        return 0
    finally:
        stop_processes(processes)


if __name__ == "__main__":
    raise SystemExit(main())
