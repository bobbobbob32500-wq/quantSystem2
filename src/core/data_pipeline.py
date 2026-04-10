# -*- coding: utf-8 -*-
"""
数据管道模块

提供统一的数据获取、缓存、超时控制和降级策略，
解决当前监控轮询P95延迟97秒的核心性能问题。
"""

from __future__ import annotations

import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List, Optional, Tuple

import pandas as pd

from src.core.logger import get_logger

logger = get_logger("data_pipeline")


class LRUCache:
    """线程安全的LRU缓存"""

    def __init__(self, maxsize: int = 1000, default_ttl: int = 300):
        self.maxsize = maxsize
        self.default_ttl = default_ttl
        self._cache: OrderedDict[str, Tuple[Any, float]] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key: str) -> Optional[Any]:
        with self._lock:
            if key in self._cache:
                value, expire_at = self._cache[key]
                if time.time() < expire_at:
                    self._cache.move_to_end(key)
                    return value
                else:
                    del self._cache[key]
            return None

    def set(self, key: str, value: Any, ttl: Optional[int] = None):
        with self._lock:
            expire_at = time.time() + (ttl or self.default_ttl)
            if key in self._cache:
                self._cache.move_to_end(key)
                self._cache[key] = (value, expire_at)
            else:
                self._cache[key] = (value, expire_at)
                if len(self._cache) > self.maxsize:
                    self._cache.popitem(last=False)

    def invalidate(self, key: str):
        with self._lock:
            self._cache.pop(key, None)

    def clear(self):
        with self._lock:
            self._cache.clear()

    def stats(self) -> Dict[str, Any]:
        with self._lock:
            now = time.time()
            active = sum(1 for _, (_, expire_at) in self._cache.items() if expire_at > now)
            return {
                "total_entries": len(self._cache),
                "active_entries": active,
                "max_size": self.maxsize,
            }


class DataPipeline:
    """数据管道 - 统一数据获取、缓存与超时控制"""

    CACHE_TTL_MAP = {
        "minute": 8,
        "quote": 5,
        "daily": 3600,
        "chip": 86400,
        "industry": 3600,
        "market_snapshot": 30,
    }

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        self.cache = LRUCache(
            maxsize=self.config.get("cache_maxsize", 5000),
            default_ttl=self.config.get("cache_default_ttl", 300),
        )
        self._timeout_seconds = self.config.get("timeout_seconds", 3.0)
        self._fallback_enabled = self.config.get("fallback_enabled", True)
        self._stats = {
            "cache_hits": 0,
            "cache_misses": 0,
            "timeouts": 0,
            "fallbacks": 0,
            "errors": 0,
        }

    def get_minute_data(
        self,
        symbol: str,
        trade_date: str,
        fetcher: Optional[Callable] = None,
        timeout_ms: Optional[int] = None,
    ) -> Optional[pd.DataFrame]:
        """获取分钟数据 - 带缓存和超时"""
        cache_key = f"minute:{symbol}:{trade_date}"

        cached = self.cache.get(cache_key)
        if cached is not None:
            self._stats["cache_hits"] += 1
            return cached

        self._stats["cache_misses"] += 1

        if fetcher is None:
            return None

        timeout = (timeout_ms or int(self._timeout_seconds * 1000)) / 1000.0
        result = self._fetch_with_timeout(fetcher, symbol, trade_date, timeout)

        if result is not None:
            ttl = self.CACHE_TTL_MAP.get("minute", 8)
            self.cache.set(cache_key, result, ttl=ttl)
            return result

        if self._fallback_enabled:
            self._stats["fallbacks"] += 1
            return self._fallback_to_daily(symbol, trade_date)

        return None

    def get_daily_data(
        self,
        symbol: str,
        fetcher: Optional[Callable] = None,
    ) -> Optional[pd.DataFrame]:
        """获取日线数据 - 带缓存"""
        cache_key = f"daily:{symbol}"

        cached = self.cache.get(cache_key)
        if cached is not None:
            self._stats["cache_hits"] += 1
            return cached

        self._stats["cache_misses"] += 1

        if fetcher is None:
            return None

        try:
            result = fetcher(symbol)
            if result is not None:
                ttl = self.CACHE_TTL_MAP.get("daily", 3600)
                self.cache.set(cache_key, result, ttl=ttl)
            return result
        except Exception as exc:
            self._stats["errors"] += 1
            logger.error("get_daily_data failed: %s -> %s", symbol, exc)
            return None

    def get_market_snapshot(
        self,
        fetcher: Optional[Callable] = None,
    ) -> Optional[Dict[str, Any]]:
        """获取市场快照 - 带缓存"""
        cache_key = "market:snapshot"

        cached = self.cache.get(cache_key)
        if cached is not None:
            self._stats["cache_hits"] += 1
            return cached

        self._stats["cache_misses"] += 1

        if fetcher is None:
            return None

        try:
            result = fetcher()
            if result is not None:
                ttl = self.CACHE_TTL_MAP.get("market_snapshot", 30)
                self.cache.set(cache_key, result, ttl=ttl)
            return result
        except Exception as exc:
            self._stats["errors"] += 1
            logger.error("get_market_snapshot failed: %s", exc)
            return None

    def batch_get_minute_data(
        self,
        symbols: List[str],
        trade_date: str,
        fetcher: Optional[Callable] = None,
        batch_timeout_ms: int = 2800,
    ) -> Dict[str, Optional[pd.DataFrame]]:
        """批量获取分钟数据 - 带整体超时"""
        results: Dict[str, Optional[pd.DataFrame]] = {}
        uncached_symbols: List[str] = []

        for symbol in symbols:
            cache_key = f"minute:{symbol}:{trade_date}"
            cached = self.cache.get(cache_key)
            if cached is not None:
                self._stats["cache_hits"] += 1
                results[symbol] = cached
            else:
                self._stats["cache_misses"] += 1
                uncached_symbols.append(symbol)

        if not uncached_symbols or fetcher is None:
            return results

        timeout = batch_timeout_ms / 1000.0
        batch_result = self._fetch_with_timeout(
            fetcher, uncached_symbols, trade_date, timeout
        )

        if batch_result is not None:
            if isinstance(batch_result, dict):
                for symbol, data in batch_result.items():
                    results[symbol] = data
                    cache_key = f"minute:{symbol}:{trade_date}"
                    ttl = self.CACHE_TTL_MAP.get("minute", 8)
                    self.cache.set(cache_key, data, ttl=ttl)
            elif isinstance(batch_result, pd.DataFrame):
                for symbol in uncached_symbols:
                    results[symbol] = batch_result

        for symbol in uncached_symbols:
            if symbol not in results:
                results[symbol] = None

        return results

    def _fetch_with_timeout(
        self,
        fetcher: Callable,
        *args,
        timeout: float = 3.0,
    ) -> Optional[Any]:
        """带超时的数据获取"""
        result_container: Dict[str, Any] = {"result": None, "error": None}
        thread = threading.Thread(
            target=self._fetch_worker,
            args=(fetcher, args, result_container),
            daemon=True,
        )
        thread.start()
        thread.join(timeout=timeout)

        if thread.is_alive():
            self._stats["timeouts"] += 1
            logger.warning("Data fetch timeout after %.1fs", timeout)
            return None

        if result_container["error"] is not None:
            self._stats["errors"] += 1
            logger.error("Data fetch error: %s", result_container["error"])
            return None

        return result_container["result"]

    @staticmethod
    def _fetch_worker(fetcher: Callable, args: tuple, result_container: Dict):
        """数据获取工作线程"""
        try:
            result_container["result"] = fetcher(*args)
        except Exception as exc:
            result_container["error"] = str(exc)

    def _fallback_to_daily(self, symbol: str, trade_date: str) -> Optional[pd.DataFrame]:
        """降级到日线数据"""
        cache_key = f"daily:{symbol}"
        cached = self.cache.get(cache_key)
        if cached is not None:
            logger.info("Fallback to daily data for %s", symbol)
            return cached
        return None

    def get_stats(self) -> Dict[str, Any]:
        """获取管道统计"""
        total = self._stats["cache_hits"] + self._stats["cache_misses"]
        return {
            **self._stats,
            "cache_hit_rate": round(self._stats["cache_hits"] / total * 100, 2) if total > 0 else 0.0,
            "cache_stats": self.cache.stats(),
        }

    def invalidate_symbol(self, symbol: str, trade_date: Optional[str] = None):
        """失效指定股票的缓存"""
        if trade_date:
            self.cache.invalidate(f"minute:{symbol}:{trade_date}")
        self.cache.invalidate(f"daily:{symbol}")
