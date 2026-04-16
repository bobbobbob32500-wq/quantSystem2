from __future__ import annotations

from src.modules.ai_integration.ai_assistant import AIAssistant


class _DummyLLM:
    is_available = True

    def chat(self, **kwargs):  # pragma: no cover - not used in this test
        return "ok"

    def chat_with_code(self, **kwargs):  # pragma: no cover - not used in this test
        return "ok"


def test_action_requires_confirmation_keyword():
    assistant = AIAssistant(
        llm_client=_DummyLLM(),
        enable_actions=True,
        action_whitelist=["run_stock_selection"],
        require_action_confirmation=True,
        action_confirmation_keywords=["确认"],
    )
    result = assistant._detect_and_execute_action("帮我选股")
    assert result is not None
    assert "确认词" in result


def test_action_blocked_by_whitelist():
    assistant = AIAssistant(
        llm_client=_DummyLLM(),
        enable_actions=True,
        action_whitelist=["run_stock_selection"],
        require_action_confirmation=False,
    )
    result = assistant._detect_and_execute_action("清空候选池")
    assert result is not None
    assert "白名单" in result


def test_action_executes_when_confirmed_and_whitelisted(monkeypatch):
    assistant = AIAssistant(
        llm_client=_DummyLLM(),
        enable_actions=True,
        action_whitelist=["run_stock_selection"],
        require_action_confirmation=True,
        action_confirmation_keywords=["确认"],
    )

    def _ok(action: str, payload=None):
        return {"success": True, "data": {"action": action}}

    monkeypatch.setattr(assistant, "_execute_system_action", _ok)
    result = assistant._detect_and_execute_action("确认选股")
    assert result is not None
    assert "执行成功" in result

