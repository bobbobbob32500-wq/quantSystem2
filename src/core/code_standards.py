# -*- coding: utf-8 -*-
"""
代码规范和工具库
提供统一的异常处理、类型检查、性能监控装饰器
"""

from typing import Any, Dict, List, Optional, Callable
from functools import wraps
import logging
import time
from concurrent.futures import ThreadPoolExecutor

logger = logging.getLogger(__name__)


# ============================================================================
# 1. 异常处理装饰器
# ============================================================================

def handle_exceptions(default_return: Any = None):
    """统一异常处理装饰器"""

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except ValueError as e:
                logger.error(f"{func.__name__} 参数错误: {e}", exc_info=True)
                if default_return is not None:
                    return default_return
                raise
            except Exception as e:
                logger.error(f"{func.__name__} 执行失败: {e}", exc_info=True)
                if default_return is not None:
                    return default_return
                raise

        return wrapper

    return decorator


# ============================================================================
# 2. 性能监控装饰器
# ============================================================================

def monitor_performance(threshold_ms: float = 1000):
    """性能监控装饰器"""

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            start_time = time.time()
            result = func(*args, **kwargs)
            elapsed_ms = (time.time() - start_time) * 1000

            if elapsed_ms > threshold_ms:
                logger.warning(
                    f"{func.__name__} 执行耗时 {elapsed_ms:.0f}ms (阈值: {threshold_ms}ms)"
                )
            else:
                logger.debug(f"{func.__name__} 执行耗时 {elapsed_ms:.0f}ms")

            return result

        return wrapper

    return decorator


# ============================================================================
# 3. 缓存装饰器
# ============================================================================

class CacheManager:
    """简单的内存缓存管理器"""

    def __init__(self, ttl_seconds: int = 3600):
        self.cache: Dict[str, tuple] = {}
        self.ttl = ttl_seconds

    def _make_key(self, func_name: str, args: tuple, kwargs: dict) -> Optional[str]:
        """生成缓存键"""
        import hashlib
        import json

        try:
            key_data = f"{func_name}:{json.dumps(args)}:{json.dumps(kwargs, sort_keys=True)}"
            return hashlib.md5(key_data.encode()).hexdigest()
        except Exception:
            return None

    def get(self, key: Optional[str]) -> Optional[Any]:
        """获取缓存"""
        if key is None or key not in self.cache:
            return None

        value, timestamp = self.cache[key]
        if time.time() - timestamp < self.ttl:
            return value

        del self.cache[key]
        return None

    def set(self, key: Optional[str], value: Any):
        """设置缓存"""
        if key is not None:
            self.cache[key] = (value, time.time())

    def clear(self):
        """清空缓存"""
        self.cache.clear()

    def stats(self) -> Dict[str, Any]:
        """返回缓存统计"""
        return {
            "size": len(self.cache),
            "ttl_seconds": self.ttl,
        }


_cache_manager = CacheManager(ttl_seconds=3600)


def clear_cache() -> None:
    """清空全局缓存"""
    _cache_manager.clear()


def get_cache_stats() -> Dict[str, Any]:
    """获取全局缓存统计"""
    return _cache_manager.stats()


def cached(ttl_seconds: int = 3600):
    """缓存装饰器"""

    def decorator(func: Callable) -> Callable:
        local_cache = CacheManager(ttl_seconds=ttl_seconds)

        @wraps(func)
        def wrapper(*args, **kwargs):
            cache_key = local_cache._make_key(func.__name__, args, kwargs)
            cached_value = local_cache.get(cache_key)
            if cached_value is not None:
                logger.debug(f"缓存命中: {func.__name__}")
                return cached_value

            result = func(*args, **kwargs)
            local_cache.set(cache_key, result)
            return result

        return wrapper

    return decorator


# ============================================================================
# 4. 并行执行工具
# ============================================================================

class ParallelExecutor:
    """并行执行器"""

    @staticmethod
    def map_threads(func: Callable, items: List[Any], max_workers: int = 8) -> List[Any]:
        """多线程执行"""
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [executor.submit(func, item) for item in items]
            results: List[Any] = []
            for future in futures:
                try:
                    results.append(future.result(timeout=30))
                except Exception as e:
                    logger.error(f"执行失败: {e}")
                    results.append(None)
            return results


# ============================================================================
# 5. 配置验证工具
# ============================================================================

class ConfigValidator:
    """配置验证工具"""

    @staticmethod
    def validate_range(value: float, min_value: float, max_value: float, field: str) -> bool:
        if value < min_value or value > max_value:
            raise ValueError(f"{field} 必须在 [{min_value}, {max_value}] 范围内")
        return True

    @staticmethod
    def validate_positive(value: float, field: str) -> bool:
        if value <= 0:
            raise ValueError(f"{field} 必须为正数")
        return True

    @staticmethod
    def validate_choice(value: Any, choices: List[Any], field: str) -> bool:
        if value not in choices:
            raise ValueError(f"{field} 必须是以下之一: {choices}")
        return True
