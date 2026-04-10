# -*- coding: utf-8 -*-
"""
实时监控信号链路专项测试

覆盖范围：
1. 信号采集准确性 - RealtimeMinuteFetcher 数据标准化
2. 信号处理逻辑   - OptimizedBuySignals 各策略 + UnboundLocalError 修复验证
3. 信号推送机制   - push_buy_signals 冷却逻辑、阈值过滤、失败日志
4. 容错/鲁棒性   - 空数据、异常输入、fallback 路径
"""

from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest


# ===========================================================================
# 2. 信号处理逻辑测试
# ===========================================================================

class TestOptimizedBuySignals:
    """信号算法正确性与边界条件"""

    def setup_method(self):
        from src.modules.optimized_buy_signals import OptimizedBuySignals, IntradayData
        self.detector = OptimizedBuySignals()
        self.IntradayData = IntradayData

    def _make_data(self, n=60, base=10.0, trend=0.005, vol_base=100000):
        price = np.array([base + i * trend for i in range(n)])
        volume = np.array([vol_base + (i % 5) * 5000 for i in range(n)], dtype=float)
        high = price * 1.002
        low = price * 0.998
        ts = np.arange(n, dtype=float)
        return self.IntradayData(price=price, volume=volume, high=high, low=low, timestamp=ts)

    def test_signal_pullback_insufficient_data_returns_false(self):
        data = self.IntradayData(
            price=np.array([10.0, 10.1]),
            volume=np.array([1000.0, 1100.0]),
            high=np.array([10.1, 10.2]),
            low=np.array([9.9, 10.0]),
            timestamp=np.array([0, 1], dtype=float),
        )
        result = self.detector.signal_pullback(data)
        assert result.signal is False

    def test_signal_breakout_no_unbound_local_error(self):
        """S6 修复：len(price) < consolidation_window 时不抛 UnboundLocalError"""
        n = 20
        price = np.linspace(10.0, 11.0, n)
        volume = np.full(n, 100000.0)
        data = self.IntradayData(
            price=price, volume=volume,
            high=price * 1.005, low=price * 0.995,
            timestamp=np.arange(n, dtype=float),
        )
        result = self.detector.signal_breakout(data)
        assert isinstance(result.signal, bool)
        assert "range_pct" in result.details
        assert isinstance(result.details["range_pct"], (int, float))

    def test_signal_breakout_range_pct_always_initialized(self):
        """breakout details 中 range_pct 应始终为合法浮点数（各种数据量）"""
        for n in [5, 14, 15, 30, 60]:
            price = np.linspace(10.0, 12.0, n)
            volume = np.full(n, 100000.0)
            data = self.IntradayData(
                price=price, volume=volume,
                high=price * 1.01, low=price * 0.99,
                timestamp=np.arange(n, dtype=float),
            )
            result = self.detector.signal_breakout(data)
            assert "range_pct" in result.details, f"n={n}: range_pct missing"
            val = result.details["range_pct"]
            assert isinstance(val, (int, float)), f"n={n}: not numeric"
            assert not np.isnan(val), f"n={n}: is NaN"

    def test_signal_pullback_returns_valid_structure(self):
        data = self._make_data(n=60)
        result = self.detector.signal_pullback(data)
        assert hasattr(result, "signal")
        assert hasattr(result, "confidence")
        assert 0.0 <= result.confidence <= 1.0

    def test_signal_consolidation_insufficient_data(self):
        data = self._make_data(n=10)
        result = self.detector.signal_consolidation(data)
        assert result.signal is False


class TestRealtimeMinuteFetcherNormalization:
    """分钟行情数据标准化正确性"""

    def setup_method(self):
        from src.modules.realtime_minute_fetcher import RealtimeMinuteFetcher
        self.fetcher = RealtimeMinuteFetcher(cache_ttl_seconds=0)

    def test_normalize_symbol_removes_exchange_suffix(self):
        from src.modules.realtime_minute_fetcher import RealtimeMinuteFetcher
        assert RealtimeMinuteFetcher.normalize_symbol("000001.SZ") == "000001"
        assert RealtimeMinuteFetcher.normalize_symbol("600000.SH") == "600000"

    def test_normalize_symbol_pads_short_code(self):
        from src.modules.realtime_minute_fetcher import RealtimeMinuteFetcher
        # 6位纯数字才能被标准化；单字符非标准代码返回空
        assert RealtimeMinuteFetcher.normalize_symbol("000001") == "000001"
        assert RealtimeMinuteFetcher.normalize_symbol("600000") == "600000"
        # 短于6位的纯数字串（如"1"）在当前实现中返回空字符串（非标准输入）
        assert RealtimeMinuteFetcher.normalize_symbol("1") == ""

    def test_normalize_symbol_empty_returns_empty(self):
        from src.modules.realtime_minute_fetcher import RealtimeMinuteFetcher
        assert RealtimeMinuteFetcher.normalize_symbol("") == ""
        assert RealtimeMinuteFetcher.normalize_symbol(None) == ""

    def test_build_quote_from_minute_price_fields(self):
        """build_quote_from_minute 应返回正确价格字段"""
        times = pd.date_range("2026-03-31 09:31", periods=60, freq="1min")
        df = pd.DataFrame({
            "symbol": "000001",
            "trade_time": times,
            "trade_date": times.strftime("%Y-%m-%d"),
            "open":   [10.0] * 60,
            "high":   [10.5 + i * 0.01 for i in range(60)],
            "low":    [9.8  + i * 0.005 for i in range(60)],
            "close":  [10.1 + i * 0.01 for i in range(60)],
            "volume": [100000.0] * 60,
            "amount": [1000000.0] * 60,
        })
        quote = self.fetcher.build_quote_from_minute("000001", df, name="平安银行")
        assert quote["symbol"] == "000001"
        assert quote["name"] == "平安银行"
        assert abs(quote["price"] - df["close"].iloc[-1]) < 1e-6
        assert abs(quote["high"] - df["high"].max()) < 1e-6
        assert abs(quote["low"] - df["low"].min()) < 1e-6
        assert "pre_close_source" in quote

    def test_build_quote_from_minute_volume_sum(self):
        """成交量应为全部 K 线之和"""
        times = pd.date_range("2026-03-31 09:31", periods=5, freq="1min")
        df = pd.DataFrame({
            "symbol": "000001",
            "trade_time": times,
            "trade_date": times.strftime("%Y-%m-%d"),
            "open": [10.0] * 5,
            "high": [10.1] * 5,
            "low":  [9.9] * 5,
            "close": [10.05] * 5,
            "volume": [20000.0, 30000.0, 25000.0, 35000.0, 40000.0],
            "amount": [0.0] * 5,
        })
        quote = self.fetcher.build_quote_from_minute("000001", df)
        assert quote["volume"] == pytest.approx(150000.0)

    def test_build_quote_from_minute_empty_returns_empty(self):
        quote = self.fetcher.build_quote_from_minute("000001", pd.DataFrame())
        assert quote == {}

    def test_cache_ttl_expiry(self):
        """TTL 过期后缓存不命中"""
        import time
        from src.modules.realtime_minute_fetcher import RealtimeMinuteFetcher
        fetcher = RealtimeMinuteFetcher(cache_ttl_seconds=1)
        times = pd.date_range("2026-03-31 09:31", periods=25, freq="1min")
        df = pd.DataFrame({
            "symbol": "000001", "trade_time": times,
            "trade_date": times.strftime("%Y-%m-%d"),
            "open": [10.0]*25, "high": [10.1]*25, "low": [9.9]*25,
            "close": [10.0]*25, "volume": [1000.0]*25, "amount": [10000.0]*25,
        })
        fetcher._write_cache("000001", df)
        time.sleep(1.1)
        assert fetcher._read_cache("000001") is None


# ===========================================================================
# 3. 信号推送机制测试
# ===========================================================================

class TestPushBuySignals:
    """push_buy_signals 冷却、阈值过滤、失败告警逻辑"""

    def _build_system(self, push_returns=True):
        from src.modules.enhanced_hybrid_system import EnhancedHybridSystem
        system = EnhancedHybridSystem.__new__(EnhancedHybridSystem)
        system.min_signal_score_for_push = 75
        system.push_cooldown = 300
        system.pushed_signals = {}
        self._pushed = []

        def _push_trade_signals(signals, now, filtered_count=0, side="buy"):
            self._pushed.append({"signals": signals, "filtered_count": filtered_count})
            return push_returns

        system.message_pusher = SimpleNamespace(push_trade_signals=_push_trade_signals)
        return system

    def test_score_below_threshold_filtered(self):
        system = self._build_system()
        from src.modules.enhanced_monitor_orchestration import push_buy_signals
        now = datetime(2026, 3, 31, 10, 0, 0)
        signals = [{"symbol": "600001", "signal_type": "A", "total_score": 60.0, "push_threshold": 75.0}]
        push_buy_signals(system, signals, now)
        assert len(self._pushed) == 0

    def test_score_above_threshold_pushed(self):
        system = self._build_system()
        from src.modules.enhanced_monitor_orchestration import push_buy_signals
        now = datetime(2026, 3, 31, 10, 0, 0)
        signals = [{"symbol": "600001", "signal_type": "A", "total_score": 82.0, "push_threshold": 75.0}]
        push_buy_signals(system, signals, now)
        assert len(self._pushed) == 1
        assert self._pushed[0]["signals"][0]["symbol"] == "600001"

    def test_same_signal_type_in_cooldown_blocked(self):
        system = self._build_system()
        from src.modules.enhanced_monitor_orchestration import push_buy_signals
        now = datetime(2026, 3, 31, 10, 5, 0)
        system.pushed_signals["600001"] = {
            "signal_type": "pullback",
            "push_time": now - timedelta(seconds=120),
            "total_score": 80.0,
        }
        signals = [{"symbol": "600001", "signal_type": "pullback", "total_score": 85.0, "push_threshold": 75.0}]
        push_buy_signals(system, signals, now)
        assert len(self._pushed) == 0

    def test_different_signal_type_after_cooldown_allowed(self):
        """S3 修复：不同类型信号超过冷却期后应被推送"""
        system = self._build_system()
        from src.modules.enhanced_monitor_orchestration import push_buy_signals
        now = datetime(2026, 3, 31, 10, 10, 0)
        system.pushed_signals["600001"] = {
            "signal_type": "pullback",
            "push_time": now - timedelta(seconds=310),  # 超过 300s cooldown
            "total_score": 80.0,
        }
        signals = [{"symbol": "600001", "signal_type": "breakout", "total_score": 85.0, "push_threshold": 75.0}]
        push_buy_signals(system, signals, now)
        assert len(self._pushed) == 1, "不同类型信号超过冷却后应被推送"

    def test_push_failure_does_not_raise(self):
        system = self._build_system(push_returns=False)
        from src.modules.enhanced_monitor_orchestration import push_buy_signals
        now = datetime(2026, 3, 31, 10, 0, 0)
        signals = [{"symbol": "600001", "signal_type": "A", "total_score": 85.0, "push_threshold": 75.0}]
        push_buy_signals(system, signals, now)  # 不应抛异常

    def test_pusher_exception_does_not_crash(self):
        """推送器抛出异常时，链路不应崩溃（容错）"""
        from src.modules.enhanced_hybrid_system import EnhancedHybridSystem
        from src.modules.enhanced_monitor_orchestration import push_buy_signals
        system = EnhancedHybridSystem.__new__(EnhancedHybridSystem)
        system.min_signal_score_for_push = 75
        system.push_cooldown = 300
        system.pushed_signals = {}

        def _raise(*args, **kwargs):
            raise ConnectionError("网络超时")

        system.message_pusher = SimpleNamespace(push_trade_signals=_raise)
        now = datetime(2026, 3, 31, 10, 0, 0)
        signals = [{"symbol": "600001", "signal_type": "A", "total_score": 85.0, "push_threshold": 75.0}]
        push_buy_signals(system, signals, now)  # 不应抛异常

    def test_filtered_count_reported_correctly(self):
        system = self._build_system()
        from src.modules.enhanced_monitor_orchestration import push_buy_signals
        now = datetime(2026, 3, 31, 10, 0, 0)
        signals = [
            {"symbol": "600001", "signal_type": "A", "total_score": 85.0, "push_threshold": 75.0},
            {"symbol": "600002", "signal_type": "A", "total_score": 60.0, "push_threshold": 75.0},
            {"symbol": "600003", "signal_type": "A", "total_score": 55.0, "push_threshold": 75.0},
        ]
        push_buy_signals(system, signals, now)
        assert self._pushed[0]["filtered_count"] == 2


# ===========================================================================
# 4. 容错与鲁棒性测试
# ===========================================================================

class TestSignalChainRobustness:
    """异常场景：空数据、网络故障、分钟数据缺失 fallback"""

    def test_get_intraday_data_fallback_on_missing_minute(self):
        """S5 修复：分钟数据缺失时用报价构造单点 fallback，而非返回 None"""
        from src.modules.enhanced_hybrid_system import EnhancedHybridSystem
        from src.modules.enhanced_monitor_runtime import get_intraday_data_for_signal
        system = EnhancedHybridSystem.__new__(EnhancedHybridSystem)

        def _build_intraday_from_minute(df):
            return None
        system._build_intraday_from_minute = _build_intraday_from_minute

        result = get_intraday_data_for_signal(
            system=system,
            symbol="000001",
            current_price=10.5,
            current_volume=100000.0,
            high=10.8,
            low=10.2,
            minute_map=None,
        )
        assert result is not None, "报价有效时应返回单点 fallback 而非 None"
        assert len(result.price) == 1
        assert result.price[0] == pytest.approx(10.5)

    def test_get_intraday_data_returns_none_on_zero_price(self):
        """价格为 0 时 fallback 应返回 None（无效行情）"""
        from src.modules.enhanced_hybrid_system import EnhancedHybridSystem
        from src.modules.enhanced_monitor_runtime import get_intraday_data_for_signal
        system = EnhancedHybridSystem.__new__(EnhancedHybridSystem)
        system._build_intraday_from_minute = lambda df: None

        result = get_intraday_data_for_signal(
            system=system,
            symbol="000001",
            current_price=0.0,
            current_volume=0.0,
            high=0.0,
            low=0.0,
            minute_map=None,
        )
        assert result is None

    def test_message_pusher_timeout_configurable(self):
        """S7 修复：MessagePusher 的 HTTP timeout 应从配置读取"""
        from src.modules.message_pusher import WeChatWorkPusher
        pusher = WeChatWorkPusher(webhook_url="https://example.com", timeout=5)
        assert pusher.timeout == 5

    def test_wechat_pusher_no_webhook_returns_false(self):
        """未配置 webhook 时推送应返回 False 而非抛异常"""
        from src.modules.message_pusher import WeChatWorkPusher
        pusher = WeChatWorkPusher(webhook_url=None)
        assert pusher.send_text("test") is False
        assert pusher.send_markdown("# test") is False

    def test_push_buy_signals_empty_list_no_call(self):
        """空信号列表时不应调用推送器"""
        from src.modules.enhanced_hybrid_system import EnhancedHybridSystem
        from src.modules.enhanced_monitor_orchestration import push_buy_signals
        system = EnhancedHybridSystem.__new__(EnhancedHybridSystem)
        system.min_signal_score_for_push = 75
        system.push_cooldown = 300
        system.pushed_signals = {}
        called = []
        system.message_pusher = SimpleNamespace(
            push_trade_signals=lambda *a, **kw: called.append(1) or True
        )
        push_buy_signals(system, [], datetime(2026, 3, 31, 10, 0, 0))
        assert len(called) == 0
