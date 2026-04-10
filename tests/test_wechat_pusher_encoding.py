# -*- coding: utf-8 -*-
"""Ensure WeChat webhook payload keeps UTF-8 Chinese content."""

from __future__ import annotations

from src.modules.message_pusher import WeChatWorkPusher


class _DummyResponse:
    def json(self):
        return {"errcode": 0, "errmsg": "ok"}


def test_wechat_pusher_send_request_uses_utf8_bytes(monkeypatch):
    captured = {}

    def _fake_post(url, data, headers, timeout):
        captured["url"] = url
        captured["data"] = data
        captured["headers"] = headers
        captured["timeout"] = timeout
        return _DummyResponse()

    monkeypatch.setattr("src.modules.message_pusher.requests.post", _fake_post)

    pusher = WeChatWorkPusher("https://example.com/webhook")
    payload = {
        "msgtype": "markdown",
        "markdown": {"content": "中文字段验证：止盈卖点，建议减仓"},
    }

    ok = pusher._send_request(payload)

    assert ok is True
    assert captured["url"] == "https://example.com/webhook"
    assert captured["headers"]["Content-Type"] == "application/json; charset=utf-8"
    assert isinstance(captured["data"], (bytes, bytearray))
    text = captured["data"].decode("utf-8")
    assert "止盈卖点" in text
    assert "建议减仓" in text
