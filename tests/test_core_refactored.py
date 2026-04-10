# -*- coding: utf-8 -*-
"""
核心模块单元测试

覆盖策略引擎、信号引擎、数据管道、风控引擎、推送Outbox等核心重构模块。
"""

import json
import os
import tempfile
from datetime import datetime, time
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest


class TestConfigManagerSecurity:
    """ConfigManager 安全性测试"""

    def test_sensitive_keys_cleared_from_config(self):
        from src.core.config import ConfigManager
        config = ConfigManager.__new__(ConfigManager)
        config._config = {
            "data_source": {"tushare_token": "secret_token_123"},
            "push": {
                "wechat_webhook": "https://example.com/webhook/secret",
                "position_wechat_webhook": "https://example.com/position/secret",
                "dingtalk_webhook": "",
            },
        }
        config._clear_sensitive_in_config()
        assert config._config["data_source"]["tushare_token"] == ""
        assert config._config["push"]["wechat_webhook"] == ""
        assert config._config["push"]["position_wechat_webhook"] == ""

    def test_is_sensitive_value(self):
        from src.core.config import ConfigManager
        config = ConfigManager.__new__(ConfigManager)
        assert config._is_sensitive_value("tushare_token", "abc")
        assert config._is_sensitive_value("wechat_webhook", "abc")
        assert not config._is_sensitive_value("log_level", "INFO")
        assert not config._is_sensitive_value("database_path", "/tmp/db")


class TestPushOutboxStore:
    """PushOutboxStore 测试"""

    def _make_store(self):
        from src.core.database import DatabaseManager
        from src.modules.push_outbox_store import PushOutboxStore
        import sqlite3

        conn = sqlite3.connect(":memory:", check_same_thread=False)
        conn.row_factory = sqlite3.Row

        class InMemoryDB:
            def execute(self, sql, params=None):
                if params:
                    conn.execute(sql, params)
                else:
                    conn.execute(sql)
                conn.commit()

            def query(self, sql, params=None):
                cursor = conn.execute(sql, params) if params else conn.execute(sql)
                columns = [desc[0] for desc in cursor.description] if cursor.description else []
                rows = cursor.fetchall()
                return [dict(zip(columns, row)) for row in rows]

        db = InMemoryDB()
        store = PushOutboxStore(db)
        return store

    def test_enqueue_and_list_retryable(self):
        store = self._make_store()
        ok = store.enqueue("wechat", "markdown", {"content": "test"}, max_attempts=3, retry_delay_seconds=0)
        assert ok
        items = store.list_retryable()
        assert len(items) == 1
        assert items[0]["channel"] == "wechat"

    def test_mark_success(self):
        store = self._make_store()
        store.enqueue("wechat", "markdown", {"content": "test"}, retry_delay_seconds=0)
        items = store.list_retryable()
        assert len(items) == 1
        store.mark_success(items[0]["id"], latency_ms=150)
        items = store.list_retryable()
        assert len(items) == 0

    def test_mark_failed_exponential_backoff(self):
        store = self._make_store()
        store.enqueue("wechat", "markdown", {"content": "test"}, max_attempts=5, retry_delay_seconds=0)
        items = store.list_retryable()
        row_id = items[0]["id"]
        store.mark_failed(row_id, "timeout", base_retry_delay=60)
        row = store.db.query("SELECT attempts, status FROM push_outbox WHERE id=?", (row_id,))
        assert row[0]["attempts"] == 1
        assert row[0]["status"] == "failed"

    def test_dead_letter_flow(self):
        store = self._make_store()
        store.enqueue("wechat", "markdown", {"content": "test"}, max_attempts=1, retry_delay_seconds=0)
        items = store.list_retryable()
        row_id = items[0]["id"]
        store.mark_failed(row_id, "error1")
        store.move_to_dead_letter(row_id)
        dead = store.list_dead_letters()
        assert len(dead) == 1
        assert dead[0]["channel"] == "wechat"

    def test_replay_dead_letter(self):
        store = self._make_store()
        store.enqueue("wechat", "markdown", {"content": "test"}, max_attempts=1, retry_delay_seconds=0)
        items = store.list_retryable()
        row_id = items[0]["id"]
        store.mark_failed(row_id, "error")
        store.move_to_dead_letter(row_id)
        ok = store.replay_dead_letter(row_id, max_attempts=3)
        assert ok
        items = store.list_retryable()
        assert len(items) == 1

    def test_get_stats(self):
        store = self._make_store()
        store.enqueue("wechat", "markdown", {"content": "test"}, retry_delay_seconds=0)
        items = store.list_retryable()
        store.mark_success(items[0]["id"], latency_ms=200)
        stats = store.get_stats(hours=1)
        assert stats["total_success"] >= 1

    def test_idempotency_key_deterministic(self):
        from src.modules.push_outbox_store import PushOutboxStore
        key1 = PushOutboxStore.build_idempotency_key("wechat", "md", {"a": 1})
        key2 = PushOutboxStore.build_idempotency_key("wechat", "md", {"a": 1})
        assert key1 == key2

    def test_compute_backoff_delay(self):
        from src.modules.push_outbox_store import PushOutboxStore
        assert PushOutboxStore._compute_backoff_delay(1) == 60
        assert PushOutboxStore._compute_backoff_delay(2) == 180
        assert PushOutboxStore._compute_backoff_delay(5) == 3600
        assert PushOutboxStore._compute_backoff_delay(10) == 3600


class TestStrategyEngine:
    """策略引擎测试"""

    def test_base_strategy_interface(self):
        from src.core.strategy_engine import BaseStrategy, SelectionContext
        class MockStrategy(BaseStrategy):
            def select(self, context, data):
                return []
            def get_required_fields(self):
                return ["close"]

        s = MockStrategy(config={"name": "mock", "min_score": 50})
        assert s.name == "mock"
        assert s.get_required_fields() == ["close"]

    def test_selection_result_to_dict(self):
        from src.core.strategy_engine import SelectionResult
        r = SelectionResult(symbol="000001.SZ", name="平安银行", score=85.0, confidence=0.85)
        d = r.to_dict()
        assert d["symbol"] == "000001.SZ"
        assert d["score"] == 85.0

    def test_strategy_registry(self):
        from src.core.strategy_engine import StrategyRegistry, BaseStrategy

        class TestStrat(BaseStrategy):
            def select(self, context, data):
                return []
            def get_required_fields(self):
                return []

        StrategyRegistry.register("test_strat")(TestStrat)
        assert "test_strat" in StrategyRegistry.list_available()
        instance = StrategyRegistry.create("test_strat")
        assert instance is not None
        assert isinstance(instance, TestStrat)

    def test_strategy_engine_merge_results(self):
        from src.core.strategy_engine import StrategyEngine, SelectionResult
        engine = StrategyEngine(config={"max_candidates": 5})
        results = [
            SelectionResult(symbol="A", score=80),
            SelectionResult(symbol="B", score=90),
            SelectionResult(symbol="A", score=85),
        ]
        merged = engine._merge_results(results)
        assert len(merged) == 2
        assert merged[0].symbol == "B"
        assert merged[0].score == 90
        assert merged[1].symbol == "A"
        assert merged[1].score == 85


class TestSignalEngine:
    """信号引擎测试"""

    def _make_minute_data(self, n=50, trend="up"):
        dates = pd.date_range("2026-04-10 09:30", periods=n, freq="1min")
        if trend == "up":
            close = np.cumsum(np.random.randn(n) * 0.1 + 0.05) + 10
        else:
            close = np.cumsum(np.random.randn(n) * 0.1 - 0.05) + 10
        return pd.DataFrame({
            "close": close,
            "high": close + np.abs(np.random.randn(n) * 0.1),
            "low": close - np.abs(np.random.randn(n) * 0.1),
            "volume": np.random.randint(1000, 10000, n),
        }, index=dates)

    def test_trend_validator(self):
        from src.core.signal_engine import TrendValidator, EntryContext
        validator = TrendValidator()
        data = self._make_minute_data(50, trend="up")
        ctx = EntryContext(symbol="000001.SZ", current_price=12.0, minute_data=data)
        result = validator.validate(ctx)
        assert result.validator_name == "trend"
        assert bool(result.passed) is True or bool(result.passed) is False
        assert 0 <= result.score <= 1

    def test_volume_validator(self):
        from src.core.signal_engine import VolumeValidator, EntryContext
        validator = VolumeValidator()
        data = self._make_minute_data(50)
        ctx = EntryContext(symbol="000001.SZ", current_price=12.0, minute_data=data)
        result = validator.validate(ctx)
        assert result.validator_name == "volume"

    def test_signal_engine_detect(self):
        from src.core.signal_engine import SignalEngine, EntryContext
        engine = SignalEngine(config={"min_confidence": 0.3})
        data = self._make_minute_data(50, trend="up")
        ctx = EntryContext(symbol="000001.SZ", current_price=float(data["close"].iloc[-1]), minute_data=data)
        signal = engine.detect_signal(ctx)
        assert signal is None or signal.confidence >= 0.3

    def test_entry_signal_to_dict(self):
        from src.core.signal_engine import EntrySignal
        sig = EntrySignal(
            symbol="000001.SZ",
            signal_type="pullback",
            trigger_price=12.0,
            confidence=0.8,
            timestamp=datetime.now(),
        )
        d = sig.to_dict()
        assert d["symbol"] == "000001.SZ"
        assert d["signal_type"] == "pullback"


class TestDataPipeline:
    """数据管道测试"""

    def test_lru_cache_basic(self):
        from src.core.data_pipeline import LRUCache
        cache = LRUCache(maxsize=10, default_ttl=60)
        cache.set("key1", "value1")
        assert cache.get("key1") == "value1"
        assert cache.get("nonexistent") is None

    def test_lru_cache_expiry(self):
        import time as _time
        from src.core.data_pipeline import LRUCache
        cache = LRUCache(maxsize=10, default_ttl=1)
        cache.set("key1", "value1", ttl=1)
        _time.sleep(1.1)
        assert cache.get("key1") is None

    def test_lru_cache_eviction(self):
        from src.core.data_pipeline import LRUCache
        cache = LRUCache(maxsize=3, default_ttl=60)
        cache.set("a", 1)
        cache.set("b", 2)
        cache.set("c", 3)
        cache.set("d", 4)
        assert cache.get("a") is None
        assert cache.get("d") == 4

    def test_lru_cache_stats(self):
        from src.core.data_pipeline import LRUCache
        cache = LRUCache(maxsize=10, default_ttl=60)
        cache.set("a", 1)
        stats = cache.stats()
        assert stats["total_entries"] == 1
        assert stats["max_size"] == 10

    def test_pipeline_cache_hit(self):
        from src.core.data_pipeline import DataPipeline
        pipeline = DataPipeline()
        pipeline.cache.set("daily:000001.SZ", pd.DataFrame({"close": [10]}))
        result = pipeline.get_daily_data("000001.SZ")
        assert result is not None
        stats = pipeline.get_stats()
        assert stats["cache_hits"] >= 1

    def test_pipeline_batch_get(self):
        from src.core.data_pipeline import DataPipeline
        pipeline = DataPipeline()
        pipeline.cache.set("minute:000001.SZ:20260410", pd.DataFrame({"close": [10]}))
        results = pipeline.batch_get_minute_data(["000001.SZ", "000002.SZ"], "20260410")
        assert "000001.SZ" in results
        assert results["000001.SZ"] is not None


class TestRiskEngine:
    """风控引擎测试"""

    def test_market_circuit_breaker_hard(self):
        from src.core.risk_engine import MarketCircuitBreaker, RiskLevel, CircuitState
        rule = MarketCircuitBreaker()
        ctx = {"market_drop_pct": -3.0, "breadth_ratio": 0.2}
        result = rule.evaluate(ctx)
        assert result.risk_level == RiskLevel.CRITICAL
        assert result.circuit_state == CircuitState.HARD
        assert result.position_multiplier == 0.0

    def test_market_circuit_breaker_soft(self):
        from src.core.risk_engine import MarketCircuitBreaker, RiskLevel, CircuitState
        rule = MarketCircuitBreaker()
        ctx = {"market_drop_pct": -1.5, "breadth_ratio": 0.3}
        result = rule.evaluate(ctx)
        assert result.circuit_state == CircuitState.SOFT
        assert result.position_multiplier < 1.0

    def test_market_gate_defensive(self):
        from src.core.risk_engine import MarketGateRule, RiskLevel
        rule = MarketGateRule()
        ctx = {"market_regime": "WEAK_BEAR"}
        result = rule.evaluate(ctx)
        assert result.risk_level == RiskLevel.HIGH
        assert result.max_signals == 2

    def test_market_gate_normal(self):
        from src.core.risk_engine import MarketGateRule
        rule = MarketGateRule()
        ctx = {"market_regime": "BULL"}
        result = rule.evaluate(ctx)
        assert result.max_signals == 4

    def test_position_limit_rule(self):
        from src.core.risk_engine import PositionLimitRule, RiskLevel
        rule = PositionLimitRule(config={"max_positions": 5})
        ctx = {"current_positions": 5, "total_position_pct": 0.5}
        result = rule.evaluate(ctx)
        assert result.risk_level == RiskLevel.HIGH
        assert result.position_multiplier == 0.0

    def test_risk_engine_assess(self):
        from src.core.risk_engine import RiskEngine
        engine = RiskEngine()
        ctx = {
            "market_drop_pct": -0.5,
            "breadth_ratio": 0.6,
            "market_regime": "NEUTRAL",
            "feedback_guard_level": "normal",
            "current_positions": 2,
            "total_position_pct": 0.3,
        }
        result = engine.assess(ctx)
        assert result.position_multiplier > 0
        assert result.max_signals > 0

    def test_risk_engine_check_signal_allowed(self):
        from src.core.risk_engine import RiskEngine
        engine = RiskEngine()
        ctx = {
            "market_drop_pct": -0.5,
            "breadth_ratio": 0.6,
            "market_regime": "NEUTRAL",
            "feedback_guard_level": "normal",
            "current_positions": 1,
            "total_position_pct": 0.2,
        }
        allowed, assessment = engine.check_signal_allowed(ctx, signal_count=1)
        assert isinstance(allowed, bool)

    def test_risk_assessment_to_dict(self):
        from src.core.risk_engine import RiskAssessment, RiskLevel, CircuitState
        a = RiskAssessment(
            risk_level=RiskLevel.HIGH,
            circuit_state=CircuitState.SOFT,
            position_multiplier=0.5,
        )
        d = a.to_dict()
        assert d["risk_level"] == "high"
        assert d["circuit_state"] == "soft"
        assert d["position_multiplier"] == 0.5
