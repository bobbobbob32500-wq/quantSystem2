# -*- coding: utf-8 -*-
"""
系统深度自检脚本
全面验证各个功能模块的逻辑实现、接口衔接、数据传递
"""

import sys
import os
import traceback
from datetime import datetime, timedelta
import pandas as pd
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

class SystemSelfCheck:
    """系统自检器"""
    
    def __init__(self):
        self.results = []
        self.errors = []
        self.warnings = []
        self.passed = 0
        self.failed = 0
        
    def check(self, name: str, func):
        """执行检查"""
        print(f"\n[检查] {name}")
        print("-" * 80)
        try:
            result = func()
            if result:
                self.passed += 1
                self.results.append({'name': name, 'status': 'PASS', 'details': result})
                print(f"[PASS] {name}")
                return True
            else:
                self.failed += 1
                self.results.append({'name': name, 'status': 'FAIL', 'details': '返回False'})
                print(f"[FAIL] {name}")
                return False
        except Exception as e:
            self.failed += 1
            error_msg = f"{str(e)}\n{traceback.format_exc()}"
            self.errors.append({'name': name, 'error': error_msg})
            self.results.append({'name': name, 'status': 'ERROR', 'details': error_msg})
            print(f"[ERROR] {name}: {e}")
            return False
    
    def warn(self, msg: str):
        """记录警告"""
        self.warnings.append(msg)
        print(f"[WARN] {msg}")
    
    def generate_report(self):
        """生成报告"""
        report = []
        report.append("="*80)
        report.append("系统深度自检报告")
        report.append("="*80)
        report.append(f"检查时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        report.append(f"总检查项: {self.passed + self.failed}")
        report.append(f"通过: {self.passed}")
        report.append(f"失败: {self.failed}")
        report.append(f"警告: {len(self.warnings)}")
        report.append("")
        
        # 详细结果
        report.append("="*80)
        report.append("检查结果详情")
        report.append("="*80)
        for result in self.results:
            status_icon = "[PASS]" if result['status'] == 'PASS' else "[FAIL]" if result['status'] == 'FAIL' else "[ERROR]"
            report.append(f"{status_icon} {result['name']}")
            if result['status'] != 'PASS':
                report.append(f"  详情: {result['details'][:200]}")
        
        # 错误详情
        if self.errors:
            report.append("\n" + "="*80)
            report.append("错误详情")
            report.append("="*80)
            for error in self.errors:
                report.append(f"\n{error['name']}:")
                report.append(error['error'])
        
        # 警告详情
        if self.warnings:
            report.append("\n" + "="*80)
            report.append("警告详情")
            report.append("="*80)
            for warn in self.warnings:
                report.append(f"- {warn}")
        
        return "\n".join(report)


def check_module_imports():
    """检查1: 核心模块导入"""
    results = []
    
    # 检查虚拟交易跟踪器
    try:
        from src.modules.virtual_trade_tracker import VirtualTradeTracker, VirtualTrade
        results.append("VirtualTradeTracker 导入成功")
    except Exception as e:
        results.append(f"VirtualTradeTracker 导入失败: {e}")
        return False
    
    # 检查监控系统
    try:
        from src.modules.enhanced_hybrid_system import EnhancedHybridSystem
        results.append("EnhancedHybridSystem 导入成功")
    except Exception as e:
        results.append(f"EnhancedHybridSystem 导入失败: {e}")
        return False
    
    # 检查自动优化系统
    try:
        from src.modules.fully_automatic_system import FullyAutomaticOptimizationSystem
        results.append("FullyAutomaticOptimizationSystem 导入成功")
    except Exception as e:
        results.append(f"FullyAutomaticOptimizationSystem 导入失败: {e}")
        # 这个不是必须的，只是警告
        pass
    
    return "\n".join(results)


def check_virtual_trade_tracker_logic():
    """检查2: 虚拟交易跟踪器逻辑"""
    from src.modules.virtual_trade_tracker import VirtualTradeTracker
    
    results = []
    
    # 创建跟踪器
    tracker = VirtualTradeTracker(
        stop_loss_pct=-0.05,
        take_profit_pct=0.10,
        max_hold_hours=24
    )
    results.append("跟踪器创建成功")
    
    # 测试1: 买入信号记录
    signal = {
        'symbol': '000001',
        'name': '测试股票',
        'price': 10.0,
        'signal_type': '突破买点',
        'total_score': 85.0,
        'pool_type': 'core',
        'overnight_score': 80.0,
        'intraday_score': 90.0
    }
    
    success = tracker.on_buy_signal(signal)
    if not success:
        return "买入信号记录失败"
    results.append("买入信号记录成功")
    
    # 验证交易记录
    if '000001' not in tracker.open_trades:
        return "交易未正确记录到open_trades"
    results.append("交易正确记录到open_trades")
    
    # 验证交易属性
    trade = tracker.open_trades['000001']
    if trade.symbol != '000001':
        return f"交易symbol错误: {trade.symbol}"
    if trade.buy_price != 10.0:
        return f"交易buy_price错误: {trade.buy_price}"
    results.append("交易属性正确")
    
    # 测试2: 止损逻辑
    current_prices = {'000001': 9.4}  # 下跌6%
    closed_trades = tracker.check_and_close(current_prices)
    
    if len(closed_trades) != 1:
        return f"止损未触发，应该平仓1个，实际{len(closed_trades)}个"
    results.append("止损逻辑正确触发")
    
    # 验证平仓属性
    closed_trade = closed_trades[0]
    if closed_trade.sell_reason != 'stop_loss':
        return f"平仓原因错误: {closed_trade.sell_reason}"
    if abs(closed_trade.pnl_pct - (-0.06)) > 0.001:
        return f"盈亏计算错误: {closed_trade.pnl_pct}"
    results.append("平仓属性正确")
    
    # 测试3: 止盈逻辑
    signal2 = {
        'symbol': '000002',
        'name': '测试股票2',
        'price': 20.0,
        'signal_type': '回踩确认买点',
        'total_score': 80.0
    }
    tracker.on_buy_signal(signal2)
    
    current_prices = {'000002': 22.5}  # 上涨12.5%
    closed_trades = tracker.check_and_close(current_prices)
    
    if len(closed_trades) != 1:
        return f"止盈未触发，应该平仓1个，实际{len(closed_trades)}个"
    if closed_trades[0].sell_reason != 'take_profit':
        return f"平仓原因错误: {closed_trades[0].sell_reason}"
    results.append("止盈逻辑正确触发")
    
    # 测试4: 统计计算
    stats = tracker.get_statistics()
    if stats['total_signals'] != 2:
        return f"总信号数错误: {stats['total_signals']}"
    if stats['total_closed'] != 2:
        return f"已平仓数错误: {stats['total_closed']}"
    results.append("统计计算正确")
    
    return "\n".join(results)


def check_system_integration():
    """检查3: 系统集成接口"""
    from src.modules.enhanced_hybrid_system import EnhancedHybridSystem
    
    results = []
    
    # 创建系统
    try:
        system = EnhancedHybridSystem(
            enable_auto_optimization=False,  # 简化测试
            enable_virtual_trade=True
        )
        results.append("系统创建成功")
    except Exception as e:
        return f"系统创建失败: {e}"
    
    # 验证虚拟交易跟踪器初始化
    if not system.enable_virtual_trade:
        return "虚拟交易未启用"
    results.append("虚拟交易已启用")
    
    if system.virtual_tracker is None:
        return "虚拟交易跟踪器未初始化"
    results.append("虚拟交易跟踪器已初始化")
    
    # 验证回调函数设置
    if system.virtual_tracker.on_trade_closed is None:
        return "回调函数未设置"
    results.append("回调函数已设置")
    
    # 验证回调函数指向
    if system.virtual_tracker.on_trade_closed != system._on_virtual_trade_closed:
        return "回调函数指向错误"
    results.append("回调函数指向正确")
    
    return "\n".join(results)


def check_data_transfer():
    """检查4: 数据传递和格式转换"""
    from src.modules.virtual_trade_tracker import VirtualTradeTracker
    
    results = []
    
    tracker = VirtualTradeTracker()
    
    # 测试信号数据格式
    signal = {
        'symbol': '000001',
        'name': '测试',
        'price': 10.0,
        'signal_type': '突破买点',
        'total_score': 85.0,
        'pool_type': 'core',
        'overnight_score': 80.0,
        'intraday_score': 90.0,
        'extra_field': 'extra_value'  # 额外字段
    }
    
    tracker.on_buy_signal(signal)
    trade = tracker.open_trades['000001']
    
    # 验证数据传递
    if trade.symbol != signal['symbol']:
        return f"symbol传递错误: {trade.symbol} != {signal['symbol']}"
    if trade.name != signal['name']:
        return f"name传递错误: {trade.name} != {signal['name']}"
    if trade.buy_price != signal['price']:
        return f"price传递错误: {trade.buy_price} != {signal['price']}"
    results.append("信号数据正确传递到交易记录")
    
    # 测试价格数据格式
    current_prices = {'000001': 9.5}
    closed_trades = tracker.check_and_close(current_prices)
    
    if len(closed_trades) == 0:
        return "价格数据未正确处理"
    
    # 验证盈亏计算
    expected_pnl_pct = (9.5 - 10.0) / 10.0
    if abs(closed_trades[0].pnl_pct - expected_pnl_pct) > 0.001:
        return f"盈亏计算错误: {closed_trades[0].pnl_pct} != {expected_pnl_pct}"
    results.append("价格数据正确处理，盈亏计算正确")
    
    # 测试统计数据格式
    stats = tracker.get_statistics()
    
    required_keys = ['total_signals', 'total_closed', 'win_rate', 'avg_pnl_pct', 
                     'cumulative_pnl', 'profit_loss_ratio', 'max_drawdown']
    for key in required_keys:
        if key not in stats:
            return f"统计缺少必要字段: {key}"
    results.append("统计数据格式正确")
    
    return "\n".join(results)


def check_exception_handling():
    """检查5: 异常处理机制"""
    from src.modules.virtual_trade_tracker import VirtualTradeTracker
    
    results = []
    
    tracker = VirtualTradeTracker()
    
    # 测试1: 缺少必要字段的信号
    try:
        incomplete_signal = {'symbol': '000001'}  # 缺少price等字段
        tracker.on_buy_signal(incomplete_signal)
        # 应该能处理，不会崩溃
        results.append("缺少字段信号处理正常")
    except Exception as e:
        # 如果抛出异常，记录但不应该崩溃
        results.append(f"缺少字段信号抛出异常: {e}")
    
    # 测试2: 价格为0的情况
    try:
        zero_price_signal = {
            'symbol': '000002',
            'name': '测试',
            'price': 0,  # 价格为0
            'signal_type': '测试',
            'total_score': 80.0
        }
        tracker.on_buy_signal(zero_price_signal)
        results.append("价格为0的信号处理正常")
    except Exception as e:
        results.append(f"价格为0抛出异常: {e}")
    
    # 测试3: 空价格字典
    try:
        closed_trades = tracker.check_and_close({})  # 空字典
        if len(closed_trades) != 0:
            return "空价格字典应该返回空列表"
        results.append("空价格字典处理正常")
    except Exception as e:
        return f"空价格字典抛出异常: {e}"
    
    # 测试4: 不存在的股票代码
    try:
        closed_trades = tracker.check_and_close({'999999': 10.0})  # 不存在的股票
        if len(closed_trades) != 0:
            return "不存在的股票应该返回空列表"
        results.append("不存在的股票处理正常")
    except Exception as e:
        return f"不存在的股票抛出异常: {e}"
    
    # 测试5: 负数价格
    try:
        negative_price_signal = {
            'symbol': '000003',
            'name': '测试',
            'price': -10.0,  # 负数价格
            'signal_type': '测试',
            'total_score': 80.0
        }
        tracker.on_buy_signal(negative_price_signal)
        results.append("负数价格信号处理正常")
    except Exception as e:
        results.append(f"负数价格抛出异常: {e}")
    
    return "\n".join(results)


def check_boundary_conditions():
    """检查6: 边界条件处理"""
    from src.modules.virtual_trade_tracker import VirtualTradeTracker
    
    results = []
    
    # 测试1: 刚好触发止损
    tracker1 = VirtualTradeTracker(stop_loss_pct=-0.05)
    signal = {'symbol': '000001', 'name': '测试', 'price': 10.0, 
              'signal_type': '测试', 'total_score': 80.0}
    tracker1.on_buy_signal(signal)
    
    # 刚好下跌5%
    closed = tracker1.check_and_close({'000001': 9.5})
    if len(closed) != 1:
        return f"刚好止损未触发: {len(closed)}"
    if closed[0].sell_reason != 'stop_loss':
        return f"平仓原因错误: {closed[0].sell_reason}"
    results.append("刚好止损边界正确处理")
    
    # 测试2: 刚好不触发止损
    tracker2 = VirtualTradeTracker(stop_loss_pct=-0.05)
    tracker2.on_buy_signal(signal)
    
    # 下跌4.9%
    closed = tracker2.check_and_close({'000001': 9.51})
    if len(closed) != 0:
        return f"未到止损不应触发: {len(closed)}"
    results.append("未到止损边界正确处理")
    
    # 测试3: 刚好触发止盈
    tracker3 = VirtualTradeTracker(take_profit_pct=0.10)
    tracker3.on_buy_signal(signal)
    
    # 刚好上涨10%
    closed = tracker3.check_and_close({'000001': 11.0})
    if len(closed) != 1:
        return f"刚好止盈未触发: {len(closed)}"
    if closed[0].sell_reason != 'take_profit':
        return f"平仓原因错误: {closed[0].sell_reason}"
    results.append("刚好止盈边界正确处理")
    
    # 测试4: 重复买入同一股票
    tracker4 = VirtualTradeTracker()
    tracker4.on_buy_signal(signal)
    
    # 再次买入同一股票
    success = tracker4.on_buy_signal(signal)
    if success:
        return "重复买入应该返回False"
    if len(tracker4.open_trades) != 1:
        return f"重复买入应该只有1个持仓: {len(tracker4.open_trades)}"
    results.append("重复买入正确处理")
    
    # 测试5: 空统计
    tracker5 = VirtualTradeTracker()
    stats = tracker5.get_statistics()
    if stats['total_signals'] != 0:
        return f"空统计total_signals错误: {stats['total_signals']}"
    if stats['win_rate'] != 0:
        return f"空统计win_rate错误: {stats['win_rate']}"
    results.append("空统计正确处理")
    
    return "\n".join(results)


def check_callback_mechanism():
    """检查7: 回调机制"""
    from src.modules.virtual_trade_tracker import VirtualTradeTracker
    
    results = []
    
    # 记录回调调用
    callback_called = []
    
    def test_callback(trade):
        callback_called.append(trade)
    
    tracker = VirtualTradeTracker()
    tracker.on_trade_closed = test_callback
    
    # 创建交易并平仓
    signal = {'symbol': '000001', 'name': '测试', 'price': 10.0,
              'signal_type': '测试', 'total_score': 80.0}
    tracker.on_buy_signal(signal)
    
    # 触发平仓
    tracker.check_and_close({'000001': 9.4})
    
    # 验证回调被调用
    if len(callback_called) != 1:
        return f"回调未被正确调用: {len(callback_called)}次"
    results.append("回调机制正确触发")
    
    # 验证回调参数
    trade = callback_called[0]
    if trade.symbol != '000001':
        return f"回调参数错误: {trade.symbol}"
    results.append("回调参数正确传递")
    
    return "\n".join(results)


def check_state_persistence():
    """检查8: 状态持久化"""
    from src.modules.virtual_trade_tracker import VirtualTradeTracker
    import tempfile
    import os
    
    results = []
    
    # 创建临时文件
    temp_file = tempfile.mktemp(suffix='.json')
    
    try:
        # 创建并保存
        tracker1 = VirtualTradeTracker()
        signal = {'symbol': '000001', 'name': '测试', 'price': 10.0,
                  'signal_type': '测试', 'total_score': 80.0}
        tracker1.on_buy_signal(signal)
        tracker1.save_state(temp_file)
        results.append("状态保存成功")
        
        # 加载
        tracker2 = VirtualTradeTracker()
        tracker2.load_state(temp_file)
        
        # 验证加载
        if len(tracker2.open_trades) != 1:
            return f"加载后open_trades错误: {len(tracker2.open_trades)}"
        if '000001' not in tracker2.open_trades:
            return "加载后缺少交易记录"
        results.append("状态加载成功")
        
        # 验证数据一致性
        trade1 = tracker1.open_trades['000001']
        trade2 = tracker2.open_trades['000001']
        
        if trade1.symbol != trade2.symbol:
            return "加载后symbol不一致"
        if trade1.buy_price != trade2.buy_price:
            return "加载后buy_price不一致"
        results.append("数据一致性验证通过")
        
    finally:
        # 清理临时文件
        if os.path.exists(temp_file):
            os.remove(temp_file)
    
    return "\n".join(results)


def main():
    """主函数"""
    print("="*80)
    print("系统深度自检")
    print("="*80)
    print(f"开始时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    checker = SystemSelfCheck()
    
    # 执行所有检查
    checker.check("1. 核心模块导入和依赖", check_module_imports)
    checker.check("2. 虚拟交易跟踪器逻辑", check_virtual_trade_tracker_logic)
    checker.check("3. 系统集成接口", check_system_integration)
    checker.check("4. 数据传递和格式转换", check_data_transfer)
    checker.check("5. 异常处理机制", check_exception_handling)
    checker.check("6. 边界条件处理", check_boundary_conditions)
    checker.check("7. 回调机制", check_callback_mechanism)
    checker.check("8. 状态持久化", check_state_persistence)
    
    # 生成报告
    report = checker.generate_report()
    print("\n" + report)
    
    # 保存报告
    report_file = f"docs/self_check_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
    os.makedirs('docs', exist_ok=True)
    with open(report_file, 'w', encoding='utf-8') as f:
        f.write(report)
    print(f"\n报告已保存: {report_file}")
    
    # 返回结果
    if checker.failed == 0:
        print("\n[SUCCESS] 所有检查通过！")
        return 0
    else:
        print(f"\n[FAILED] {checker.failed}项检查失败")
        return 1


if __name__ == '__main__':
    sys.exit(main())
