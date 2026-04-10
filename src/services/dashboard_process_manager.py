from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from src.core.logger import get_logger

logger = get_logger("dashboard_process_manager")


class DashboardProcessManager:
    """管理 Web 面板拉起的后台进程。"""

    PROCESS_KEY_MONITOR = "monitor_runtime"

    def __init__(
        self,
        project_root: Optional[str | Path] = None,
        state_path: Optional[str | Path] = None,
        logs_dir: Optional[str | Path] = None,
    ):
        self.project_root = Path(project_root or Path(__file__).resolve().parents[2])
        self.state_path = Path(state_path or self.project_root / "data" / "cache" / "web_runtime_tasks.json")
        self.logs_dir = Path(logs_dir or self.project_root / "data" / "logs" / "web_tasks")
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.logs_dir.mkdir(parents=True, exist_ok=True)

    def list_processes(self) -> Dict[str, Dict[str, Any]]:
        state = self._load_state()
        processes = state.get("processes", {})
        normalized: Dict[str, Dict[str, Any]] = {}
        for process_key, row in processes.items():
            current = dict(row)
            current["running"] = self._is_pid_running(current.get("pid"))
            if current["running"]:
                current["status"] = "running"
            elif current.get("status") == "running":
                current["status"] = "stopped"
            normalized[process_key] = current
        state["processes"] = normalized
        self._save_state(state)
        return normalized

    def get_process(self, process_key: str) -> Optional[Dict[str, Any]]:
        return self.list_processes().get(process_key)

    def start_monitor_runtime(self) -> Dict[str, Any]:
        existing = self.get_process(self.PROCESS_KEY_MONITOR)
        if existing and existing.get("running"):
            return {
                "success": True,
                "process_key": self.PROCESS_KEY_MONITOR,
                "status": "already_running",
                "message": f"监控服务已在运行，PID={existing.get('pid')}",
                "process": existing,
            }

        command = [sys.executable, str(self.project_root / "run_service.py")]
        started_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_path = self.logs_dir / f"monitor_runtime_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
        log_file = open(log_path, "a", encoding="utf-8")
        creationflags = 0
        if os.name == "nt":
            creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(subprocess, "DETACHED_PROCESS", 0)

        process = subprocess.Popen(
            command,
            cwd=str(self.project_root),
            stdout=log_file,
            stderr=subprocess.STDOUT,
            creationflags=creationflags,
        )
        log_file.close()

        state = self._load_state()
        state.setdefault("processes", {})[self.PROCESS_KEY_MONITOR] = {
            "process_key": self.PROCESS_KEY_MONITOR,
            "label": "实时监控服务",
            "status": "running",
            "pid": process.pid,
            "command": command,
            "cwd": str(self.project_root),
            "log_path": str(log_path),
            "started_at": started_at,
            "updated_at": started_at,
        }
        self._save_state(state)
        return {
            "success": True,
            "process_key": self.PROCESS_KEY_MONITOR,
            "status": "running",
            "message": f"监控服务已启动，PID={process.pid}",
            "process": state["processes"][self.PROCESS_KEY_MONITOR],
        }

    def stop_monitor_runtime(self) -> Dict[str, Any]:
        existing = self.get_process(self.PROCESS_KEY_MONITOR)
        if not existing:
            return {
                "success": True,
                "process_key": self.PROCESS_KEY_MONITOR,
                "status": "not_found",
                "message": "当前没有 Web 托管的监控服务。",
                "process": None,
            }

        pid = existing.get("pid")
        if pid and self._is_pid_running(pid):
            self._terminate_pid(int(pid))
        existing["status"] = "stopped"
        existing["running"] = False
        existing["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        state = self._load_state()
        state.setdefault("processes", {})[self.PROCESS_KEY_MONITOR] = existing
        self._save_state(state)
        return {
            "success": True,
            "process_key": self.PROCESS_KEY_MONITOR,
            "status": "stopped",
            "message": f"监控服务已停止，PID={pid}",
            "process": existing,
        }

    def _load_state(self) -> Dict[str, Any]:
        if not self.state_path.exists():
            return {"processes": {}}
        try:
            return json.loads(self.state_path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("读取进程状态文件失败: %s", exc)
            return {"processes": {}}

    def _save_state(self, state: Dict[str, Any]) -> None:
        self.state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")

    @staticmethod
    def _is_pid_running(pid: Any) -> bool:
        try:
            if pid in (None, "", 0):
                return False
            os.kill(int(pid), 0)
            return True
        except Exception:
            return False

    @staticmethod
    def _terminate_pid(pid: int) -> None:
        if os.name == "nt":
            os.kill(pid, signal.SIGTERM)
            return
        os.kill(pid, signal.SIGTERM)
