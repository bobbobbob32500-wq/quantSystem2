# -*- coding: utf-8 -*-
"""
代码规范工具单元测试
"""

import pytest
import time
from src.core.code_standards import (
    handle_exceptions,
    monitor_performance,
    cached,
    clear_cache,
    get_cache_stats,
    ParallelExecutor,
    ConfigValidator
)


class TestExceptionHandling:
    """异常处理测试"""
    
    def test_handle_exceptions_with_default_return(self):
        """测试异常处理 - 返回默认值"""
        @handle_exceptions(default_return=[])
        def failing_function():
            raise ValueError("测试错误")
        
        result = failing_function()
        assert result == []
    
    def test_handle_exceptions_success(self):
        """测试异常处理 - 正常执行"""
        @handle_exceptions(default_return=None)
        def success_function():
            return "success"
        
        result = success_function()
        assert result == "success"


class TestPerformanceMonitoring:
    """性能监控测试"""
    
    def test_monitor_performance(self):
        """测试性能监控"""
        @monitor_performance(threshold_ms=1000)
        def test_function():
            return "result"
        
        result = test_function()
        assert result == "result"


class TestCaching:
    """缓存测试"""
    
    def test_cache_hit(self, cleanup_cache):
        """测试缓存命中"""
        call_count = 0
        
        @cached(ttl_seconds=60)
        def expensive_function(x):
            nonlocal call_count
            call_count += 1
            return x * 2
        
        result1 = expensive_function(5)
        result2 = expensive_function(5)
        
        assert result1 == 10
        assert result2 == 10
        assert call_count == 1
    
    def test_cache_different_params(self, cleanup_cache):
        """测试缓存 - 不同参数"""
        call_count = 0
        
        @cached(ttl_seconds=60)
        def expensive_function(x):
            nonlocal call_count
            call_count += 1
            return x * 2
        
        result1 = expensive_function(5)
        result2 = expensive_function(10)
        
        assert result1 == 10
        assert result2 == 20
        assert call_count == 2


class TestParallelExecutor:
    """并行执行器测试"""
    
    def test_map_threads(self):
        """测试多线程执行"""
        def process_item(x):
            return x * 2
        
        items = [1, 2, 3, 4, 5]
        results = ParallelExecutor.map_threads(process_item, items, max_workers=2)
        
        assert len(results) == 5
        assert all(r is not None for r in results)


class TestConfigValidator:
    """配置验证器测试"""
    
    def test_validate_range_valid(self):
        """测试范围验证"""
        assert ConfigValidator.validate_range(50, 0, 100, "score")
    
    def test_validate_range_invalid(self):
        """测试范围验证 - 无效"""
        with pytest.raises(ValueError):
            ConfigValidator.validate_range(150, 0, 100, "score")
    
    def test_validate_positive(self):
        """测试正数验证"""
        assert ConfigValidator.validate_positive(10, "count")
    
    def test_validate_choice(self):
        """测试选择验证"""
        assert ConfigValidator.validate_choice("active", ["active", "inactive"], "status")
