from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from uuid import uuid4

from src.modules.ai_integration.ai_assistant import AIAssistant
import src.modules.ai_integration.ai_assistant as ai_assistant_module


class _DummyLLM:
    is_available = True

    def chat(self, **kwargs):  # pragma: no cover
        return "ok"

    def chat_with_code(self, **kwargs):  # pragma: no cover
        return "ok"


def _make_local_cache_dir() -> Path:
    base = Path.cwd() / ".pytest_tmp_run" / "ai_shortcuts_cache"
    base.mkdir(parents=True, exist_ok=True)
    target = base / f"case_{uuid4().hex}"
    target.mkdir(parents=True, exist_ok=True)
    return target


def test_recent_winrate_shortcut(monkeypatch):
    cache_dir = _make_local_cache_dir()
    payload = {
        "closed_trades": [
            {"sell_time": (datetime.now() - timedelta(days=1)).isoformat(), "pnl_pct": 3.2},
            {"sell_time": (datetime.now() - timedelta(days=2)).isoformat(), "pnl_pct": -1.1},
            {"sell_time": (datetime.now() - timedelta(days=3)).isoformat(), "pnl_pct": 2.4},
        ]
    }
    (cache_dir / "virtual_trades.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(ai_assistant_module, "DATA_CACHE_DIR", cache_dir)

    assistant = AIAssistant(llm_client=_DummyLLM(), enable_actions=False)
    result = assistant.chat("最近10天我的胜率多少")
    assert "胜率" in result
    assert "平仓笔数" in result


def test_stock_buy_check_shortcut(monkeypatch):
    cache_dir = _make_local_cache_dir()
    pool = {
        "candidates": [
            {"ts_code": "000001.SZ", "name": "平安银行", "score": 82.5},
        ]
    }
    (cache_dir / "candidate_pool.json").write_text(json.dumps(pool, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(ai_assistant_module, "DATA_CACHE_DIR", cache_dir)

    class _FakeDashboardDataService:
        def __init__(self, project_root=None):
            self.project_root = project_root

        def build_snapshot(self):
            return {
                "signals": {
                    "latest_items": [
                        {"ts_code": "000001.SZ", "signal_type": "BREAKOUT", "trigger_time": "10:30:00"}
                    ]
                }
            }

    import src.services.dashboard_service as dashboard_service_module

    monkeypatch.setattr(dashboard_service_module, "DashboardDataService", _FakeDashboardDataService)

    assistant = AIAssistant(llm_client=_DummyLLM(), enable_actions=False)
    result = assistant.chat("000001.SZ 现在走势如何，符合我的买入条件吗")
    assert "买点条件检查" in result
    assert "候选池命中：是" in result


def test_system_health_shortcut(monkeypatch):
    assistant = AIAssistant(llm_client=_DummyLLM(), enable_actions=False)
    monkeypatch.setattr(
        assistant,
        "_read_dashboard_snapshot",
        lambda: {
            "meta": {"generated_label": "2026-04-16 23:00:00"},
            "candidate_pool": {"count": 12},
            "signals": {"recent_count": 5, "latest_signal_label": "000001.SZ BREAKOUT"},
            "virtual_trades": {"open_count": 3, "closed_count": 20},
            "monitor_session": {"status_label": "实时监控在线"},
        },
    )
    result = assistant.chat("系统运行情况怎么样")
    assert "AI管家系统体检" in result
    assert "候选池：12" in result


def test_add_holding_nl_action(monkeypatch):
    assistant = AIAssistant(
        llm_client=_DummyLLM(),
        enable_actions=True,
        action_whitelist=["update_holding"],
        require_action_confirmation=True,
        action_confirmation_keywords=["确认"],
    )

    captured = {}

    def _ok(action: str, payload=None):
        captured["action"] = action
        captured["payload"] = payload or {}
        return {"success": True, "data": {"action": action}}

    monkeypatch.setattr(assistant, "_execute_system_action", _ok)

    result = assistant._detect_and_execute_action("确认新增持仓 000001.SZ 名称平安银行 成本12.5 数量1000")
    assert "新增持仓执行成功" in result
    assert captured["action"] == "update_holding"
    assert captured["payload"]["ts_code"] == "000001.SZ"
    assert captured["payload"]["hold_num"] == 1000


def test_remove_holding_nl_action(monkeypatch):
    assistant = AIAssistant(
        llm_client=_DummyLLM(),
        enable_actions=True,
        action_whitelist=["remove_holding"],
        require_action_confirmation=True,
        action_confirmation_keywords=["确认"],
    )
    captured = {}

    def _ok(action: str, payload=None):
        captured["action"] = action
        captured["payload"] = payload or {}
        return {"success": True}

    monkeypatch.setattr(assistant, "_execute_system_action", _ok)
    result = assistant._detect_and_execute_action("确认删除持仓 600519")
    assert "删除持仓执行成功" in result
    assert captured["action"] == "remove_holding"
    assert captured["payload"]["ts_code"] == "600519.SH"
