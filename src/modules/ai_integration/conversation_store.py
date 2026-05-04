#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
对话历史存储（SQLite）

设计目标：
- 无额外依赖，适合本地部署
- 支持按 session_id 隔离会话
- 支持裁剪历史，避免上下文膨胀导致质量下降/超时
"""

import os
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from src.core.logger import get_logger

logger = get_logger("conversation_store")


@dataclass(frozen=True)
class ConversationStoreConfig:
    db_path: str
    max_messages: int = 200


class ConversationStore:
    """SQLite 会话存储"""

    def __init__(self, config: ConversationStoreConfig):
        self._config = config
        self._db_path = self._ensure_db_path(config.db_path)
        self._init_db()

    @staticmethod
    def _ensure_db_path(db_path: str) -> str:
        path = Path(db_path).expanduser().resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        return str(path)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, timeout=30, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        try:
            with self._connect() as conn:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS conversation_messages (
                      id INTEGER PRIMARY KEY AUTOINCREMENT,
                      session_id TEXT NOT NULL,
                      role TEXT NOT NULL,
                      content TEXT NOT NULL,
                      created_at INTEGER NOT NULL
                    )
                    """
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_conversation_session_created "
                    "ON conversation_messages(session_id, created_at)"
                )
        except Exception as e:
            logger.warning(f"初始化对话数据库失败: {e}")

    def append(self, session_id: str, role: str, content: str) -> None:
        if not session_id:
            return
        if role not in ("user", "assistant", "system"):
            role = "user"
        content = (content or "").strip()
        if not content:
            return

        now = int(time.time())
        try:
            with self._connect() as conn:
                conn.execute(
                    "INSERT INTO conversation_messages(session_id, role, content, created_at) VALUES (?, ?, ?, ?)",
                    (session_id, role, content, now),
                )
                self._enforce_max_messages(conn, session_id)
        except Exception as e:
            logger.warning(f"写入对话历史失败: {e}")

    def get_history(self, session_id: str, limit: int = 50) -> List[Dict]:
        if not session_id:
            return []
        limit = max(0, min(int(limit), 500))
        try:
            with self._connect() as conn:
                rows = conn.execute(
                    """
                    SELECT role, content
                    FROM conversation_messages
                    WHERE session_id = ?
                    ORDER BY created_at DESC, id DESC
                    LIMIT ?
                    """,
                    (session_id, limit),
                ).fetchall()
            # 取出后需要按时间正序
            rows = list(reversed(rows))
            return [{"role": r["role"], "content": r["content"]} for r in rows]
        except Exception as e:
            logger.warning(f"读取对话历史失败: {e}")
            return []

    def clear(self, session_id: str) -> None:
        if not session_id:
            return
        try:
            with self._connect() as conn:
                conn.execute("DELETE FROM conversation_messages WHERE session_id = ?", (session_id,))
        except Exception as e:
            logger.warning(f"清空对话历史失败: {e}")

    def _enforce_max_messages(self, conn: sqlite3.Connection, session_id: str) -> None:
        """控制单会话最大消息数，避免无限膨胀。"""
        max_messages = max(10, int(self._config.max_messages))
        try:
            count = conn.execute(
                "SELECT COUNT(1) AS cnt FROM conversation_messages WHERE session_id = ?",
                (session_id,),
            ).fetchone()["cnt"]
            if count <= max_messages:
                return
            excess = count - max_messages
            conn.execute(
                """
                DELETE FROM conversation_messages
                WHERE id IN (
                  SELECT id FROM conversation_messages
                  WHERE session_id = ?
                  ORDER BY created_at ASC, id ASC
                  LIMIT ?
                )
                """,
                (session_id, excess),
            )
        except Exception as e:
            logger.debug(f"裁剪历史条数失败: {e}")


def estimate_message_tokens(text: str) -> int:
    """
    粗略估算 token 数（用于裁剪，不追求精确）。

    经验上中文/混合文本 token 密度较高，这里用一个偏保守的估算：
    - 按字符数的一半估算
    """
    text = text or ""
    return max(1, len(text) // 2)


def trim_history_by_token_budget(
    history: List[Dict],
    max_prompt_tokens: int,
    reserved_for_answer_tokens: int,
) -> List[Dict]:
    """
    按 token 预算裁剪对话历史（从最早开始删除），避免把上下文塞爆。

    max_prompt_tokens: prompt + history 允许占用的最大 token（粗估）
    reserved_for_answer_tokens: 为回答预留 token（粗估）
    """
    if not history:
        return []

    budget = int(max_prompt_tokens) - int(reserved_for_answer_tokens)
    if budget <= 50:
        # 预算太小，保留最后 4 条
        return history[-4:]

    total = 0
    kept: List[Dict] = []
    # 从后往前累加，保证优先保留最新轮次
    for msg in reversed(history):
        total += estimate_message_tokens(msg.get("content", ""))
        kept.append(msg)
        if total >= budget:
            break

    kept = list(reversed(kept))
    # 保证 user/assistant 成对更稳一点：若开头是 assistant，则丢掉第一条
    if kept and kept[0].get("role") == "assistant":
        kept = kept[1:]
    return kept


def default_conversation_db_path() -> str:
    """
    默认 DB 路径：<项目根>/data/cache/ai_conversations.sqlite3
    """
    # 约定：本文件位于 src/modules/ai_integration/，向上 3 层到项目根
    project_root = Path(__file__).resolve().parents[3]
    return str(project_root / "data" / "cache" / "ai_conversations.sqlite3")

