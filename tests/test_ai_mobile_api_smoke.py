# -*- coding: utf-8 -*-
"""
移动端 FastAPI 上 AI / 管家相关路由的冒烟测试。

- 默认只校验路由注册与状态类接口（不消耗大模型 token）。
- 若需连真实 DeepSeek/Ollama 做一次对话与快捷问，请在项目根目录执行：
  set RUN_AI_LLM_SMOKE=1   （Windows）
  export RUN_AI_LLM_SMOKE=1  （Linux/macOS）
  并配置好 config/ai_config.yaml 或环境变量中的 API Key。
"""
from __future__ import annotations

import os

import pytest

pytest.importorskip("fastapi")


@pytest.fixture(scope="module")
def api_client():
    from fastapi.testclient import TestClient

    from src.api.app import app

    return TestClient(app)


@pytest.mark.smoke
def test_openapi_lists_ai_and_butler(api_client):
    r = api_client.get("/openapi.json")
    assert r.status_code == 200, r.text
    paths = r.json().get("paths") or {}
    assert "/api/ai/status" in paths, "AI 模块未挂载，请检查 src.api.app 中 _ai_available 与依赖导入"
    assert "/api/ai/chat" in paths
    assert "/api/ai/quick_ask" in paths
    assert "/api/butler/status" in paths
    assert "/api/butler/start" in paths
    assert "/api/butler/stop" in paths


@pytest.mark.smoke
def test_ai_status_shape(api_client):
    r = api_client.get("/api/ai/status")
    assert r.status_code == 200, r.text
    body = r.json()
    assert "enabled" in body
    assert "available" in body


@pytest.mark.smoke
def test_butler_status_shape(api_client):
    r = api_client.get("/api/butler/status")
    assert r.status_code == 200, r.text
    body = r.json()
    assert "running" in body
    assert "llm_available" in body
    assert "active_alerts_count" in body
    assert "active_alerts" in body


@pytest.mark.smoke
def test_butler_start_stop_roundtrip(api_client):
    r1 = api_client.post("/api/butler/start")
    assert r1.status_code == 200, r1.text
    assert r1.json().get("success") is True

    r2 = api_client.get("/api/butler/status")
    assert r2.status_code == 200
    assert r2.json().get("running") is True

    r3 = api_client.post("/api/butler/stop")
    assert r3.status_code == 200, r3.text
    assert r3.json().get("success") is True

    r4 = api_client.get("/api/butler/status")
    assert r4.status_code == 200
    assert r4.json().get("running") is False


@pytest.mark.skipif(
    os.environ.get("RUN_AI_LLM_SMOKE") != "1",
    reason="Export RUN_AI_LLM_SMOKE=1 to call real LLM (uses API tokens).",
)
def test_ai_chat_and_quick_ask_llm(api_client):
    r_chat = api_client.post(
        "/api/ai/chat",
        json={
            "message": "请仅回复一个字：好",
            "context": {"smoke_test": "1"},
        },
    )
    assert r_chat.status_code == 200, r_chat.text
    chat_body = r_chat.json()
    assert chat_body.get("success") is True
    assert isinstance(chat_body.get("response"), str) and len(chat_body["response"]) > 0

    r_quick = api_client.post(
        "/api/ai/quick_ask",
        json={
            "key": "市场分析",
            "context": {"candidate_count": "0", "smoke_test": "1"},
        },
    )
    assert r_quick.status_code == 200, r_quick.text
    quick_body = r_quick.json()
    assert quick_body.get("success") is True
    assert isinstance(quick_body.get("response"), str) and len(quick_body["response"]) > 0
