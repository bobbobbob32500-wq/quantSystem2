from __future__ import annotations

import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.core.logger import get_logger

logger = get_logger("terminal_runtime_service")


class TerminalRuntimeService:
    """读取 Cursor 终端文本，识别真实监控运行态。"""

    MONITOR_PATTERNS = ("python main.py", "python run_service.py")
    WINDOWS_TITLES = ("QuantService", "QuantDashboard")

    def __init__(self, terminals_directory: Optional[str | Path] = None):
        self.terminals_directory = Path(terminals_directory) if terminals_directory else None

    def inspect(self, now: Optional[datetime] = None) -> Dict[str, Any]:
        current_time = now or datetime.now()
        windows_state = self._inspect_windows_background()
        if windows_state.get("terminal_online"):
            return windows_state

        if self.terminals_directory is None or not self.terminals_directory.exists():
            return {
                "terminal_online": False,
                "status_label": "未接入终端运行态",
                "display_text": "当前未配置终端状态读取目录。",
                "matched_terminal": None,
                "last_monitor_at": None,
                "degraded_reasons": [],
            }

        terminal_files = sorted(self.terminals_directory.glob("*.txt"))
        for path in terminal_files:
            state = self._inspect_one(path, current_time)
            if state.get("matched_terminal"):
                return state

        return {
            "terminal_online": False,
            "status_label": "未检测到监控终端",
            "display_text": "当前没有发现正在运行的主监控终端。",
            "matched_terminal": None,
            "last_monitor_at": None,
            "degraded_reasons": [],
        }

    def _inspect_windows_background(self) -> Dict[str, Any]:
        """
        Windows 下支持 start_all.bat 这类后台窗口启动方式：
        - 通过窗口标题 QuantService / QuantDashboard 粗略判断服务是否在跑
        - 作为看板“监控在线”判定的补充，不依赖 Cursor 终端目录
        """
        if sys.platform != "win32":
            return {"terminal_online": False}
        try:
            # /V 输出窗口标题，匹配 start "QuantService" 创建的任务
            output = subprocess.check_output(
                ["tasklist", "/V", "/FO", "CSV"],
                text=True,
                encoding="utf-8",
                errors="ignore",
            )
        except Exception:
            return {"terminal_online": False}

        hit = None
        for title in self.WINDOWS_TITLES:
            if title.lower() in output.lower():
                hit = title
                break
        if not hit:
            return {"terminal_online": False}

        return {
            "terminal_online": True,
            "status_label": "后台服务运行中",
            "display_text": f"检测到后台窗口 `{hit}` 正在运行（来自 start_all.bat）。",
            "matched_terminal": f"windows:{hit}",
            "last_monitor_at": None,
            "degraded_reasons": [],
        }

    def _inspect_one(self, path: Path, now: datetime) -> Dict[str, Any]:
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            content = path.read_text(encoding="utf-8", errors="ignore")
        except Exception as exc:
            logger.warning("读取终端状态失败 %s: %s", path, exc)
            return {"matched_terminal": None}

        lines = content.splitlines()
        header = lines[:12]
        body = "\n".join(lines)
        active_command = self._extract_header_value(header, "active_command")
        cwd = self._extract_header_value(header, "cwd")
        if not any(pattern in active_command for pattern in self.MONITOR_PATTERNS):
            return {"matched_terminal": None}

        monitor_times = re.findall(r"\[(\d{2}:\d{2}:\d{2})\]\s*实时监控中\.\.\.", body)
        last_monitor_at = monitor_times[-1] if monitor_times else None
        degraded_reasons: List[str] = []
        if "降级到候选分钟聚合" in body:
            degraded_reasons.append("行业实时主源获取失败，已降级到候选分钟聚合")
        if "No realtime market data available" in body:
            degraded_reasons.append("实时行情暂无可用数据")
        if "候选池为空" in body:
            degraded_reasons.append("候选池为空")

        terminal_online = bool(last_monitor_at)
        status_label = "终端监控运行中" if terminal_online else "终端已启动但未见监控输出"
        display_text = f"已识别终端命令 `{active_command}`。"
        if last_monitor_at:
            display_text = f"已识别终端命令 `{active_command}`，最近一次监控输出时间 {last_monitor_at}。"
        if degraded_reasons:
            status_label = "终端监控运行中，但存在降级"
            display_text = f"{display_text} 当前存在降级：{degraded_reasons[0]}。"

        return {
            "terminal_online": terminal_online,
            "status_label": status_label,
            "display_text": display_text,
            "matched_terminal": str(path),
            "active_command": active_command,
            "cwd": cwd,
            "last_monitor_at": last_monitor_at,
            "degraded_reasons": degraded_reasons[:3],
        }

    @staticmethod
    def _extract_header_value(lines: List[str], key: str) -> str:
        prefix = f"{key}:"
        for line in lines:
            if line.startswith(prefix):
                return line[len(prefix):].strip()
        return ""
