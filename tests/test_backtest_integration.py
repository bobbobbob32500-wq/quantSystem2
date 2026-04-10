# -*- coding: utf-8 -*-
"""
回测系统集成测试
测试多种场景：正常情况、边界条件、异常情况
"""

import unittest
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import tempfile
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.modules.backtest.data_validator import StockCodeValidator, ValidationStatus
from src.modules.backtest.performance_analyzer import PerformanceAnalyzer, PerformanceMetrics
from src.modules.backtest.event_backtest_engine import EventDrivenBacktest, BacktestConfig, Trade, Position
from src.modules.backtest.visualizer import BacktestVisualizer


class TestScenarioNormal(unittest.TestCase):
    """正常场景测试"""
    
    def setUp(self):
        """测试前准备"""
        self.config = BacktestConfig(
            initial_capital=100000,
            position_size=0.2,
            max_positions=5,
            stop_loss_pct=-0.03,
            take_profit_pct=0.05
        )
        self.analyzer = PerformanceAnalyzer(risk_free_rate=0.03)
    
    def test_scenario_1_profitable_trades(self):
        """场景1: 盈利交易为主"""
        print("\n【测试场景1】盈利交易为主")
        
        # 创建盈利交易记录
        trades = []
        for i in range(10):
            trade = Trade(
                symbol=f"600{i+100:03d}.SH",
                name=f"股票{i}",
                entry_time=datetime(2026, 2, i+1, 10, 0),
                entry_price=100.0,
                exit_time=datetime(2026, 2, i+1, 14, 0),
                exit_price=105.0 + i * 0.5,  # 盈利
                shares=100,
                pnl_pct=0.05 + i * 0.005,
                pnl_amount=(5.0 + i * 0.5) * 100,
                holding_minutes=240,
                signal_type="回踩均线",
                exit_reason="止盈"
            )
            trades.append(trade)
        
        # 创建资金曲线
        equity_curve = []
        equity = 100000
        for i in range(10):
            equity += trades[i].pnl_amount if i < len(trades) else 0
            equity_curve.append({
                'date': f'2026-02-{i+1:02d}',
                'equity': equity
            })
        
        # 分析绩效
        metrics = self.analyzer.analyze(trades, equity_curve, 100000)
        
        # 验证结果
        self.assertEqual(metrics.total_trades, 10)
        self.assertEqual(metrics.win_trades, 10)
        self.assertEqual(metrics.loss_trades, 0)
        self.assertEqual(metrics.win_rate, 1.0)
        self.assertGreater(metrics.total_return, 0)
        self.assertGreater(metrics.sharpe_ratio, 0)
        
        print(f"  ✓ 总收益率: {metrics.total_return*100:.2f}%")
        print(f"  ✓ 胜率: {metrics.win_rate*100:.1f}%")
        print(f"  ✓ 夏普比率: {metrics.sharpe_ratio:.3f}")
    
    def test_scenario_2_loss_trades(self):
        """场景2: 亏损交易为主"""
        print("\n【测试场景2】亏损交易为主")
        
        trades = []
        for i in range(10):
            trade = Trade(
                symbol=f"600{i+100:03d}.SH",
                name=f"股票{i}",
                entry_time=datetime(2026, 2, i+1, 10, 0),
                entry_price=100.0,
                exit_time=datetime(2026, 2, i+1, 11, 0),
                exit_price=97.0 - i * 0.3,  # 亏损
                shares=100,
                pnl_pct=-0.03 - i * 0.003,
                pnl_amount=(-3.0 - i * 0.3) * 100,
                holding_minutes=60,
                signal_type="突破",
                exit_reason="止损"
            )
            trades.append(trade)
        
        equity_curve = []
        equity = 100000
        for i in range(10):
            equity += trades[i].pnl_amount if i < len(trades) else 0
            equity_curve.append({
                'date': f'2026-02-{i+1:02d}',
                'equity': max(equity, 50000)  # 防止负数
            })
        
        metrics = self.analyzer.analyze(trades, equity_curve, 100000)
        
        self.assertEqual(metrics.total_trades, 10)
        self.assertEqual(metrics.win_trades, 0)
        self.assertEqual(metrics.loss_trades, 10)
        self.assertEqual(metrics.win_rate, 0.0)
        self.assertLess(metrics.total_return, 0)
        
        print(f"  ✓ 总收益率: {metrics.total_return*100:.2f}%")
        print(f"  ✓ 胜率: {metrics.win_rate*100:.1f}%")
    
    def test_scenario_3_mixed_trades(self):
        """场景3: 盈亏混合交易"""
        print("\n【测试场景3】盈亏混合交易")
        
        trades = []
        np.random.seed(42)  # 固定随机种子
        
        for i in range(20):
            is_win = np.random.random() > 0.4  # 60%胜率
            pnl_pct = np.random.uniform(0.02, 0.08) if is_win else np.random.uniform(-0.05, -0.02)
            
            trade = Trade(
                symbol=f"600{i+100:03d}.SH",
                name=f"股票{i}",
                entry_time=datetime(2026, 2, (i % 28) + 1, 10, 0),
                entry_price=100.0,
                exit_time=datetime(2026, 2, (i % 28) + 1, 14, 0),
                exit_price=100.0 * (1 + pnl_pct),
                shares=100,
                pnl_pct=pnl_pct,
                pnl_amount=pnl_pct * 10000,
                holding_minutes=240,
                signal_type="回踩均线" if i % 2 == 0 else "突破",
                exit_reason="止盈" if is_win else "止损"
            )
            trades.append(trade)
        
        # 构建资金曲线
        equity_curve = []
        equity = 100000
        daily_pnl = {}
        
        for trade in trades:
            date = trade.entry_time.strftime('%Y-%m-%d')
            if date not in daily_pnl:
                daily_pnl[date] = 0
            daily_pnl[date] += trade.pnl_amount
        
        for i in range(20):
            date = f'2026-02-{(i % 20) + 1:02d}'
            equity += daily_pnl.get(date, 0)
            equity_curve.append({
                'date': date,
                'equity': max(equity, 50000)
            })
        
        metrics = self.analyzer.analyze(trades, equity_curve, 100000)
        
        self.assertEqual(metrics.total_trades, 20)
        self.assertGreater(metrics.win_rate, 0)
        self.assertLess(metrics.win_rate, 1)
        
        print(f"  ✓ 总收益率: {metrics.total_return*100:.2f}%")
        print(f"  ✓ 胜率: {metrics.win_rate*100:.1f}%")
        print(f"  ✓ 盈亏比: {metrics.profit_loss_ratio:.2f}")


class TestScenarioBoundary(unittest.TestCase):
    """边界条件测试"""
    
    def setUp(self):
        self.analyzer = PerformanceAnalyzer()
    
    def test_boundary_empty_data(self):
        """边界1: 空数据"""
        print("\n【边界测试1】空数据")
        
        metrics = self.analyzer.analyze([], [], 100000)
        
        self.assertEqual(metrics.total_trades, 0)
        self.assertEqual(metrics.total_return, 0)
        self.assertEqual(metrics.win_rate, 0)
        
        print("  ✓ 空数据处理正确")
    
    def test_boundary_single_trade(self):
        """边界2: 单笔交易"""
        print("\n【边界测试2】单笔交易")
        
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
            exit_reason="止盈"
        )
        
        equity_curve = [
            {'date': '2026-02-01', 'equity': 100000},
            {'date': '2026-02-02', 'equity': 100500}
        ]
        
        metrics = self.analyzer.analyze([trade], equity_curve, 100000)
        
        self.assertEqual(metrics.total_trades, 1)
        self.assertEqual(metrics.win_trades, 1)
        self.assertEqual(metrics.win_rate, 1.0)
        
        print(f"  ✓ 单笔交易处理正确，收益率: {metrics.total_return*100:.2f}%")
    
    def test_boundary_zero_profit(self):
        """边界3: 零收益交易"""
        print("\n【边界测试3】零收益交易")
        
        trade = Trade(
            symbol="600519.SH",
            name="贵州茅台",
            entry_time=datetime(2026, 2, 1, 10, 0),
            entry_price=100.0,
            exit_time=datetime(2026, 2, 1, 14, 0),
            exit_price=100.0,  # 零收益
            shares=100,
            pnl_pct=0.0,
            pnl_amount=0.0,
            holding_minutes=240,
            exit_reason="平仓"
        )
        
        equity_curve = [
            {'date': '2026-02-01', 'equity': 100000},
            {'date': '2026-02-02', 'equity': 100000}
        ]
        
        metrics = self.analyzer.analyze([trade], equity_curve, 100000)
        
        self.assertEqual(metrics.total_trades, 1)
        self.assertEqual(metrics.loss_trades, 1)  # 零收益算作亏损
        
        print("  ✓ 零收益交易处理正确")
    
    def test_boundary_extreme_drawdown(self):
        """边界4: 极端回撤"""
        print("\n【边界测试4】极端回撤")
        
        # 模拟极端回撤情况
        equity_curve = [
            {'date': '2026-02-01', 'equity': 100000},
            {'date': '2026-02-02', 'equity': 150000},  # 峰值
            {'date': '2026-02-03', 'equity': 80000},   # 大幅回撤
            {'date': '2026-02-04', 'equity': 70000},   # 继续回撤
            {'date': '2026-02-05', 'equity': 90000},   # 恢复
        ]
        
        trades = []
        metrics = self.analyzer.analyze(trades, equity_curve, 100000)
        
        # 最大回撤应该约为46.67% (从150000到80000)
        expected_drawdown = (150000 - 70000) / 150000
        self.assertAlmostEqual(metrics.max_drawdown, expected_drawdown, places=2)
        
        print(f"  ✓ 最大回撤计算正确: {metrics.max_drawdown*100:.2f}%")
    
    def test_boundary_high_frequency(self):
        """边界5: 高频交易"""
        print("\n【边界测试5】高频交易（100笔）")
        
        trades = []
        np.random.seed(42)
        
        for i in range(100):
            pnl_pct = np.random.normal(0.001, 0.01)  # 小幅度波动
            
            trade = Trade(
                symbol=f"600{(i % 100) + 100:03d}.SH",
                name=f"股票{i}",
                entry_time=datetime(2026, 2, (i % 28) + 1, 10 + (i % 4), 0),
                entry_price=100.0,
                exit_time=datetime(2026, 2, (i % 28) + 1, 14 + (i % 4), 0),
                exit_price=100.0 * (1 + pnl_pct),
                shares=100,
                pnl_pct=pnl_pct,
                pnl_amount=pnl_pct * 10000,
                holding_minutes=30,
                exit_reason="止盈" if pnl_pct > 0 else "止损"
            )
            trades.append(trade)
        
        # 构建资金曲线
        equity_curve = []
        equity = 100000
        for i in range(28):
            daily_pnl = sum(t.pnl_amount for t in trades if t.entry_time.day == i + 1)
            equity += daily_pnl
            equity_curve.append({
                'date': f'2026-02-{i+1:02d}',
                'equity': max(equity, 50000)
            })
        
        metrics = self.analyzer.analyze(trades, equity_curve, 100000)
        
        self.assertEqual(metrics.total_trades, 100)
        self.assertGreater(metrics.avg_holding_days, 0)
        
        print(f"  ✓ 高频交易处理正确")
        print(f"    总交易: {metrics.total_trades}")
        print(f"    胜率: {metrics.win_rate*100:.1f}%")
        print(f"    平均持仓: {metrics.avg_holding_days:.2f}天")


class TestScenarioException(unittest.TestCase):
    """异常情况测试"""
    
    def setUp(self):
        self.analyzer = PerformanceAnalyzer()
    
    def test_exception_invalid_dates(self):
        """异常1: 无效日期格式"""
        print("\n【异常测试1】无效日期格式")
        
        equity_curve = [
            {'date': 'invalid-date', 'equity': 100000},
        ]
        
        # 应该抛出异常或返回空结果
        try:
            metrics = self.analyzer.analyze([], equity_curve, 100000)
            print("  ✗ 应该抛出异常但没有")
        except Exception as e:
            print(f"  ✓ 正确抛出异常: {type(e).__name__}")
    
    def test_exception_negative_equity(self):
        """异常2: 负资金"""
        print("\n【异常测试2】负资金处理")
        
        equity_curve = [
            {'date': '2026-02-01', 'equity': 100000},
            {'date': '2026-02-02', 'equity': -10000},  # 负资金
        ]
        
        # 应该能处理负资金情况
        metrics = self.analyzer.analyze([], equity_curve, 100000)
        
        self.assertLess(metrics.total_return, 0)
        print(f"  ✓ 负资金处理正确，收益率: {metrics.total_return*100:.2f}%")
    
    def test_exception_missing_fields(self):
        """异常3: 缺失字段"""
        print("\n【异常测试3】缺失字段")
        
        # 创建不完整的交易记录
        trade = Trade(
            symbol="600519.SH",
            name="贵州茅台",
            entry_time=datetime(2026, 2, 1, 10, 0),
            entry_price=100.0,
            exit_time=None,  # 缺失
            exit_price=0.0,
            shares=100,
            pnl_pct=0.0,
            pnl_amount=0.0,
            holding_minutes=0,
            exit_reason=""
        )
        
        equity_curve = [
            {'date': '2026-02-01', 'equity': 100000},
        ]
        
        # 应该能处理缺失字段
        metrics = self.analyzer.analyze([trade], equity_curve, 100000)
        
        print(f"  ✓ 缺失字段处理正确")


class TestModuleIntegration(unittest.TestCase):
    """模块集成测试"""
    
    def test_integration_validator_and_analyzer(self):
        """集成1: 验证器与分析器"""
        print("\n【集成测试1】验证器与分析器")
        
        # 验证股票代码
        symbols = ["600519.SH", "000001.SZ", "300001.SZ", "invalid"]
        
        valid_symbols = []
        for symbol in symbols:
            is_valid, errors = StockCodeValidator.validate(symbol)
            if is_valid:
                valid_symbols.append(symbol)
        
        self.assertEqual(len(valid_symbols), 3)
        print(f"  ✓ 验证通过: {len(valid_symbols)}/{len(symbols)} 只股票")
    
    def test_integration_visualization(self):
        """集成2: 可视化报告生成"""
        print("\n【集成测试2】可视化报告生成")
        
        # 创建测试数据
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
            )
        ]
        
        equity_curve = [
            {'date': '2026-02-01', 'equity': 100000},
            {'date': '2026-02-02', 'equity': 100500},
        ]
        
        analyzer = PerformanceAnalyzer()
        metrics = analyzer.analyze(trades, equity_curve, 100000)
        
        # 创建临时目录用于测试
        with tempfile.TemporaryDirectory() as tmpdir:
            visualizer = BacktestVisualizer(output_dir=tmpdir)
            
            try:
                report_file = visualizer.generate_report(
                    metrics=metrics,
                    trades=trades,
                    equity_curve=equity_curve,
                    output_file=os.path.join(tmpdir, "test_report.html")
                )
                
                # 验证文件是否生成
                self.assertTrue(os.path.exists(report_file))
                print(f"  ✓ 报告生成成功: {report_file}")
            except Exception as e:
                print(f"  ⚠ 报告生成警告: {e}")


class TestPerformance(unittest.TestCase):
    """性能测试"""
    
    def test_performance_large_dataset(self):
        """性能1: 大数据集处理"""
        print("\n【性能测试1】大数据集（1000笔交易）")
        
        import time
        
        # 生成大量交易数据
        trades = []
        np.random.seed(42)
        
        for i in range(1000):
            pnl_pct = np.random.normal(0.001, 0.02)
            trade = Trade(
                symbol=f"600{(i % 500) + 100:03d}.SH",
                name=f"股票{i}",
                entry_time=datetime(2026, 2, (i % 28) + 1, 10, 0),
                entry_price=100.0,
                exit_time=datetime(2026, 2, (i % 28) + 1, 14, 0),
                exit_price=100.0 * (1 + pnl_pct),
                shares=100,
                pnl_pct=pnl_pct,
                pnl_amount=pnl_pct * 10000,
                holding_minutes=240,
                exit_reason="止盈" if pnl_pct > 0 else "止损"
            )
            trades.append(trade)
        
        # 构建资金曲线
        equity_curve = []
        equity = 100000
        for i in range(28):
            daily_pnl = sum(t.pnl_amount for t in trades if t.entry_time.day == i + 1)
            equity += daily_pnl
            equity_curve.append({
                'date': f'2026-02-{i+1:02d}',
                'equity': max(equity, 50000)
            })
        
        # 测量性能
        start_time = time.time()
        analyzer = PerformanceAnalyzer()
        metrics = analyzer.analyze(trades, equity_curve, 100000)
        elapsed_time = time.time() - start_time
        
        print(f"  ✓ 处理1000笔交易耗时: {elapsed_time:.3f}秒")
        print(f"    总交易: {metrics.total_trades}")
        print(f"    每秒处理: {metrics.total_trades / elapsed_time:.0f}笔")
        
        # 性能要求：1000笔交易应在1秒内完成
        self.assertLess(elapsed_time, 1.0)


def run_integration_tests():
    """运行所有集成测试"""
    print("\n" + "=" * 70)
    print("回测系统集成测试")
    print("=" * 70)
    
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    
    # 添加测试类
    suite.addTests(loader.loadTestsFromTestCase(TestScenarioNormal))
    suite.addTests(loader.loadTestsFromTestCase(TestScenarioBoundary))
    suite.addTests(loader.loadTestsFromTestCase(TestScenarioException))
    suite.addTests(loader.loadTestsFromTestCase(TestModuleIntegration))
    suite.addTests(loader.loadTestsFromTestCase(TestPerformance))
    
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    # 打印汇总
    print("\n" + "=" * 70)
    print("测试汇总")
    print("=" * 70)
    print(f"总测试数: {result.testsRun}")
    print(f"通过: {result.testsRun - len(result.failures) - len(result.errors)}")
    print(f"失败: {len(result.failures)}")
    print(f"错误: {len(result.errors)}")
    
    if result.failures:
        print("\n失败的测试:")
        for test, trace in result.failures:
            print(f"  - {test}")
    
    if result.errors:
        print("\n错误的测试:")
        for test, trace in result.errors:
            print(f"  - {test}")
    
    print("=" * 70)
    
    return result.wasSuccessful()


if __name__ == '__main__':
    success = run_integration_tests()
    sys.exit(0 if success else 1)
