from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from src.core.config import ConfigManager
from src.core.logger import get_logger

logger = get_logger("monitor_session_service")


class MonitorSessionService:
    """轻量监控会话状态存储，用于看板展示盘中盯盘状态。"""

    def __init__(
        self,
        config: Optional[ConfigManager] = None,
        project_root: Optional[str | Path] = None,
        session_path: Optional[str | Path] = None,
    ):
        self.config = config or ConfigManager()
        self.project_root = Path(project_root or Path(__file__).resolve().parents[2])
        raw_path = session_path or "data/cache/monitor_session.json"
        self.session_path = self._resolve_path(raw_path)

    def start_session(self, source: str = "dashboard") -> Dict[str, Any]:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        payload = {
            "is_active": True,
            "source": source,
            "started_at": now,
            "last_action_at": now,
            "last_refresh_at": now,
            "status_label": "正在盯盘",
        }
        self._save(payload)
        return payload

    def refresh_session(self) -> Dict[str, Any]:
        payload = self.get_session()
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        payload.update(
            {
                "last_refresh_at": now,
                "last_action_at": now,
                "status_label": "正在盯盘",
            }
        )
        if not payload.get("started_at"):
            payload["started_at"] = now
        payload["is_active"] = True
        self._save(payload)
        return payload

    def stop_session(self, reason: str = "manual") -> Dict[str, Any]:
        payload = self.get_session()
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        payload.update(
            {
                "is_active": False,
                "stopped_at": now,
                "last_action_at": now,
                "status_label": "已停止",
                "stop_reason": reason,
            }
        )
        self._save(payload)
        return payload

    def get_session(self) -> Dict[str, Any]:
        if not self.session_path.exists():
            return {
                "is_active": False,
                "status_label": "未开始",
            }
        try:
            with self.session_path.open("r", encoding="utf-8") as handle:
                payload = json.load(handle)
            if not isinstance(payload, dict):
                return {"is_active": False, "status_label": "未开始"}
            return payload
        except Exception as exc:
            logger.warning("读取监控会话状态失败: %s", exc)
            return {"is_active": False, "status_label": "未知"}

    def _save(self, payload: Dict[str, Any]) -> None:
        self.session_path.parent.mkdir(parents=True, exist_ok=True)
        with self.session_path.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)

    def _resolve_path(self, raw_path: str | Path) -> Path:
        path = Path(raw_path)
        if path.is_absolute():
            return path
        return self.project_root / path
