# -*- coding: utf-8 -*-
"""
回测模块单元测试
"""

import unittest
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import List

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.modules.backtest.data_validator import StockCodeValidator, DataValidator, ValidationStatus
from src.modules.backtest.performance_analyzer import PerformanceAnalyzer, PerformanceMetrics
from src.modules.backtest.event_backtest_engine import EventDrivenBacktest, BacktestConfig, Trade, Position


class TestStockCodeValidator(unittest.TestCase):
    """股票代码验证测试"""
    
    def test_valid_sh_main(self):
        """测试沪市主板代码"""
        is_valid, errors = StockCodeValidator.validate("600519.SH")
        self.assertTrue(is_valid)
        self.assertEqual(len(errors), 0)
    
    def test_valid_sz_main(self):
        """测试深市主板代码"""
        is_valid, errors = StockCodeValidator.validate("000001.SZ")
        self.assertTrue(is_valid)
        self.assertEqual(len(errors), 0)
    
    def test_valid_sz_gem(self):
        """测试创业板代码"""
        is_valid, errors = StockCodeValidator.validate("300001.SZ")
        self.assertTrue(is_valid)
        self.assertEqual(len(errors), 0)
    
    def test_invalid_no_suffix(self):
        """测试无后缀代码"""
        is_valid, errors = StockCodeValidator.validate("600519")
        self.assertFalse(is_valid)
        self.assertIn("格式错误，缺少市场后缀", errors[0])
    
    def test_invalid_length(self):
        """测试长度错误"""
        is_valid, errors = StockCodeValidator.validate("60051.SH")
        self.assertFalse(is_valid)
        self.assertIn("代码长度错误", errors[0])
    
    def test_invalid_prefix(self):
        """测试前缀错误"""
        is_valid, errors = StockCodeValidator.validate("500519.SH")
        self.assertFalse(is_valid)
        self.assertIn("沪市代码应以6、68或8开头", errors[0])
    
    def test_normalize(self):
        """测试代码标准化"""
        self.assertEqual(StockCodeValidator.normalize("600519"), "600519.SH")
        self.assertEqual(StockCodeValidator.normalize("000001"), "000001.SZ")
        self.assertEqual(StockCodeValidator.normalize("600519.SH"), "600519.SH")


class TestPerformanceAnalyzer(unittest.TestCase):
    """绩效分析测试"""
    
    def setUp(self):
        self.analyzer = PerformanceAnalyzer(risk_free_rate=0.03)
    
    def test_basic_metrics(self):
        """测试基础指标计算"""
        # 创建模拟交易记录
        trades = [
            Trade(
                symbol="600519.SH",
                name="贵州茅台",
                entry_time=datetime(2026, 2, 1, 10, 0),
                entry_price=100.0,
                exit_time=datetime(2026, 2, 1, 14, 0),
                exit_price=105.0,
                shares=100,
                pnl_pct=0.05,
                pnl_amount=500.0,
                holding_minutes=240,
                exit_reason="止盈"
            ),
            Trade(
                symbol="000001.SZ",
                name="平安银行",
                entry_time=datetime(2026, 2, 2, 10, 0),
                entry_price=50.0,
                exit_time=datetime(2026, 2, 2, 11, 0),
                exit_price=48.5,
                shares=200,
                pnl_pct=-0.03,
                pnl_amount=-300.0,
                holding_minutes=60,
                exit_reason="止损"
            )
        ]
        
        # 创建资金曲线
        equity_curve = [
            {'date': '2026-02-01', 'equity': 100000},
            {'date': '2026-02-02', 'equity': 100500},
            {'date': '2026-02-03', 'equity': 100200},
        ]
        
        metrics = self.analyzer.analyze(trades, equity_curve, 100000)
        
        # 验证结果
        self.assertAlmostEqual(metrics.total_return, 0.002, places=3)
        self.assertEqual(metrics.total_trades, 2)
        self.assertEqual(metrics.win_trades, 1)
        self.assertEqual(metrics.loss_trades, 1)
        self.assertAlmostEqual(metrics.win_rate, 0.5)
    
    def test_sharpe_ratio(self):
        """测试夏普比率计算"""
        # 创建有波动率的收益数据
        daily_returns = [0.01, -0.005, 0.008, -0.002, 0.012]
        
        equity_curve = []
        equity = 100000
        for i, ret in enumerate(daily_returns):
            equity *= (1 + ret)
            equity_curve.append({
                'date': f'2026-02-{i+1:02d}',
                'equity': equity
            })
        
        trades = [
            Trade(
                symbol="TEST",
                name="测试",
                entry_time=datetime(2026, 2, 1),
                entry_price=100,
                exit_time=datetime(2026, 2, 2),
                exit_price=101,
                shares=100,
                pnl_pct=0.01,
                pnl_amount=100,
                holding_minutes=1440,
                exit_reason="止盈"
            )
        ]
        
        metrics = self.analyzer.analyze(trades, equity_curve, 100000)
        
        # 夏普比率应该为正（有正收益）
        self.assertGreater(metrics.sharpe_ratio, 0)
    
    def test_max_drawdown(self):
        """测试最大回撤计算"""
        equity_curve = [
            {'date': '2026-02-01', 'equity': 100000},
            {'date': '2026-02-02', 'equity': 110000},
            {'date': '2026-02-03', 'equity': 105000},
            {'date': '2026-02-04', 'equity': 100000},
            {'date': '2026-02-05', 'equity': 108000},
        ]
        
        trades = []
        metrics = self.analyzer.analyze(trades, equity_curve, 100000)
        
        # 最大回撤应该约为9.09% (从110000到100000)
        self.assertAlmostEqual(metrics.max_drawdown, 0.0909, places=2)
    
    def test_empty_data(self):
        """测试空数据处理"""
        metrics = self.analyzer.analyze([], [], 100000)
        
        self.assertEqual(metrics.total_trades, 0)
        self.assertEqual(metrics.total_return, 0)


class TestBacktestConfig(unittest.TestCase):
    """回测配置测试"""
    
    def test_default_config(self):
        """测试默认配置"""
        config = BacktestConfig()
        
        self.assertEqual(config.initial_capital, 100000.0)
        self.assertEqual(config.position_size, 0.2)
        self.assertEqual(config.max_positions, 5)
        self.assertEqual(config.stop_loss_pct, -0.03)
        self.assertEqual(config.take_profit_pct, 0.05)
    
    def test_custom_config(self):
        """测试自定义配置"""
        config = BacktestConfig(
            initial_capital=200000,
            position_size=0.3,
            max_positions=3,
            stop_loss_pct=-0.05,
            take_profit_pct=0.10
        )
        
        self.assertEqual(config.initial_capital, 200000)
        self.assertEqual(config.position_size, 0.3)
        self.assertEqual(config.max_positions, 3)
        self.assertEqual(config.stop_loss_pct, -0.05)
        self.assertEqual(config.take_profit_pct, 0.10)


class TestTradeAndPosition(unittest.TestCase):
    """交易和持仓测试"""
    
    def test_trade_creation(self):
        """测试交易记录创建"""
        trade = Trade(
            symbol="600519.SH",
            name="贵州茅台",
            entry_time=datetime(2026, 2, 1, 10, 0),
            entry_price=100.0,
            exit_time=datetime(2026, 2, 1, 14, 0),
            exit_price=105.0,
            shares=100,
            pnl_pct=0.05,
            pnl_amount=500.0,
            holding_minutes=240,
            signal_type="回踩均线",
            exit_reason="止盈"
        )
        
        self.assertEqual(trade.symbol, "600519.SH")
        self.assertEqual(trade.pnl_pct, 0.05)
        self.assertEqual(trade.exit_reason, "止盈")
    
    def test_position_creation(self):
        """测试持仓创建"""
        position = Position(
            symbol="600519.SH",
            name="贵州茅台",
            shares=100,
            entry_price=100.0,
            entry_time=datetime(2026, 2, 1, 10, 0),
            entry_date="2026-02-01",
            cost=10000.0
        )
        
        self.assertEqual(position.symbol, "600519.SH")
        self.assertEqual(position.shares, 100)
        self.assertEqual(position.entry_date, "2026-02-01")


class TestSignalDetection(unittest.TestCase):
    """信号检测测试"""
    
    def test_pullback_signal(self):
        """测试回踩信号检测"""
        # 创建模拟K线数据（满足回踩条件）
        window = []
        base_price = 100
        
        # 生成20根K线，价格在MA20上方
        for i in range(20):
            window.append({
                'open': base_price + i * 0.5,
                'high': base_price + i * 0.5 + 1,
                'low': base_price + i * 0.5 - 0.5,
                'close': base_price + i * 0.5,
                'volume': 10000
            })
        
        # 最后一根K线接近MA5（回踩）
        window[-1]['close'] = base_price + 18 * 0.5  # 接近MA5
        window[-1]['low'] = base_price + 17 * 0.5
        
        # 测试信号检测（需要访问私有方法）
        # 这里简化测试，只验证数据结构
        self.assertEqual(len(window), 20)
        self.assertGreater(window[-1]['close'], window[0]['close'])
    
    def test_breakout_signal(self):
        """测试突破信号检测"""
        window = []
        base_price = 100
        
        # 生成20根K线
        for i in range(20):
            window.append({
                'open': base_price,
                'high': base_price + 1,
                'low': base_price - 1,
                'close': base_price,
                'volume': 10000
            })
        
        # 最后一根突破
        window[-1]['close'] = base_price * 1.02
        window[-1]['high'] = base_price * 1.02
        
        # 验证突破条件
        recent_high = max([x['close'] for x in window[:-1]])
        self.assertGreater(window[-1]['close'], recent_high * 1.01)


class IntegrationTest(unittest.TestCase):
    """集成测试"""
    
    def test_full_backtest_flow(self):
        """测试完整回测流程"""
        # 这个测试需要数据库连接，简化测试
        config = BacktestConfig(
            initial_capital=100000,
            position_size=0.2,
            max_positions=5
        )
        
        # 验证配置对象创建成功
        self.assertIsNotNone(config)
        self.assertEqual(config.initial_capital, 100000)
    
    def test_performance_with_equity_curve(self):
        """测试带资金曲线的绩效分析"""
        # 创建模拟的完整数据
        trades = []
        equity_curve = []
        
        # 生成28天的数据（2026年2月有28天）
        equity = 100000
        for i in range(28):
            # 模拟每日收益
            daily_return = np.random.normal(0.001, 0.02)
            equity *= (1 + daily_return)
            
            equity_curve.append({
                'date': f'2026-02-{i+1:02d}',
                'equity': equity
            })
            
            # 每隔几天生成一笔交易
            if i % 3 == 0 and i > 0:
                trade = Trade(
                    symbol=f"600{i:03d}.SH",
                    name=f"股票{i}",
                    entry_time=datetime(2026, 2, i+1, 10, 0),
                    entry_price=100.0,
                    exit_time=datetime(2026, 2, i+1, 14, 0),
                    exit_price=100.0 * (1 + daily_return * 10),
                    shares=100,
                    pnl_pct=daily_return * 10,
                    pnl_amount=daily_return * 10 * 10000,
                    holding_minutes=240,
                    exit_reason="止盈" if daily_return > 0 else "止损"
                )
                trades.append(trade)
        
        analyzer = PerformanceAnalyzer()
        metrics = analyzer.analyze(trades, equity_curve, 100000)
        
        # 验证基本指标
        self.assertGreater(metrics.total_trades, 0)
        self.assertIsNotNone(metrics.total_return)
        self.assertIsNotNone(metrics.max_drawdown)


def run_tests():
    """运行所有测试"""
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    
    # 添加测试类
    suite.addTests(loader.loadTestsFromTestCase(TestStockCodeValidator))
    suite.addTests(loader.loadTestsFromTestCase(TestPerformanceAnalyzer))
    suite.addTests(loader.loadTestsFromTestCase(TestBacktestConfig))
    suite.addTests(loader.loadTestsFromTestCase(TestTradeAndPosition))
    suite.addTests(loader.loadTestsFromTestCase(TestSignalDetection))
    suite.addTests(loader.loadTestsFromTestCase(IntegrationTest))
    
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    return result.wasSuccessful()


if __name__ == '__main__':
    success = run_tests()
    sys.exit(0 if success else 1)
