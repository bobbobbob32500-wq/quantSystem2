#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
LLM 结果缓存（SQLite）

用途：
- 缓存“同一输入 → 同一输出”的高成本调用（例如选股解释、信号解释、报告生成）
- 本地部署零依赖；后续可替换为 Redis
"""

import json
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple

from src.core.logger import get_logger

logger = get_logger("llm_cache")


@dataclass(frozen=True)
class LLMCacheConfig:
    db_path: str
    enabled: bool = True
    ttl_seconds: int = 3600
    max_items: int = 2000


class LLMCache:
    def __init__(self, config: LLMCacheConfig):
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
                    CREATE TABLE IF NOT EXISTS llm_cache (
                      cache_key TEXT PRIMARY KEY,
                      value TEXT NOT NULL,
                      created_at INTEGER NOT NULL,
                      expires_at INTEGER NOT NULL,
                      hit_count INTEGER NOT NULL DEFAULT 0
                    )
                    """
                )
                conn.execute("CREATE INDEX IF NOT EXISTS idx_llm_cache_expires ON llm_cache(expires_at)")
        except Exception as e:
            logger.warning(f"初始化缓存数据库失败: {e}")

    def get(self, cache_key: str) -> Optional[str]:
        if not self._config.enabled:
            return None
        cache_key = str(cache_key or "").strip()
        if not cache_key:
            return None
        now = int(time.time())
        try:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT value, expires_at, hit_count FROM llm_cache WHERE cache_key = ?",
                    (cache_key,),
                ).fetchone()
                if row is None:
                    return None
                if int(row["expires_at"]) <= now:
                    conn.execute("DELETE FROM llm_cache WHERE cache_key = ?", (cache_key,))
                    return None
                conn.execute(
                    "UPDATE llm_cache SET hit_count = ? WHERE cache_key = ?",
                    (int(row["hit_count"]) + 1, cache_key),
                )
                return str(row["value"] or "")
        except Exception as e:
            logger.debug(f"读取缓存失败: {e}")
            return None

    def set(self, cache_key: str, value: str, ttl_seconds: Optional[int] = None) -> None:
        if not self._config.enabled:
            return
        cache_key = str(cache_key or "").strip()
        if not cache_key:
            return
        value = str(value or "")
        now = int(time.time())
        ttl = int(ttl_seconds) if ttl_seconds is not None else int(self._config.ttl_seconds)
        ttl = max(30, ttl)
        expires_at = now + ttl
        try:
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO llm_cache(cache_key, value, created_at, expires_at, hit_count)
                    VALUES (?, ?, ?, ?, 0)
                    ON CONFLICT(cache_key) DO UPDATE SET
                      value = excluded.value,
                      created_at = excluded.created_at,
                      expires_at = excluded.expires_at
                    """,
                    (cache_key, value, now, expires_at),
                )
                self._evict_if_needed(conn)
        except Exception as e:
            logger.debug(f"写入缓存失败: {e}")

    def _evict_if_needed(self, conn: sqlite3.Connection) -> None:
        """简单淘汰：先清理过期，再按 created_at 淘汰最旧数据。"""
        try:
            now = int(time.time())
            conn.execute("DELETE FROM llm_cache WHERE expires_at <= ?", (now,))
            max_items = max(100, int(self._config.max_items))
            row = conn.execute("SELECT COUNT(1) AS cnt FROM llm_cache").fetchone()
            if row is None:
                return
            cnt = int(row["cnt"])
            if cnt <= max_items:
                return
            excess = cnt - max_items
            conn.execute(
                """
                DELETE FROM llm_cache
                WHERE cache_key IN (
                  SELECT cache_key FROM llm_cache
                  ORDER BY created_at ASC
                  LIMIT ?
                )
                """,
                (excess,),
            )
        except Exception:
            pass

