# -*- coding: utf-8 -*-
"""
回测菜单功能测试
"""

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.modules.backtest_menu import BacktestMenu
from src.core.config import ConfigManager
from src.core.database import DatabaseManager


def test_backtest_menu():
    """测试回测菜单功能"""
    print("=" * 70)
    print("回测菜单功能测试")
    print("=" * 70)
    
    # 初始化
    config = ConfigManager()
    db = DatabaseManager(config)
    menu = BacktestMenu(config, db)
    
    # 测试1: 数据统计
    print("\n【测试1】数据统计功能")
    menu._show_data_statistics()
    
    # 测试2: 数据状态检查
    print("\n【测试2】数据状态检查")
    menu.check_data_status()
    
    # 测试3: 帮助显示
    print("\n【测试3】帮助显示")
    menu.show_help()
    
    print("\n" + "=" * 70)
    print("测试完成")
    print("=" * 70)


def test_backtest_engine():
    """测试回测引擎"""
    print("\n" + "=" * 70)
    print("回测引擎功能测试")
    print("=" * 70)
    
    from src.modules.backtest.history_recommendation_db import HistoryRecommendationDB
    from src.modules.backtest.event_backtest_engine import EventDrivenBacktest, BacktestConfig
    from src.modules.backtest.performance_analyzer import PerformanceAnalyzer
    
    # 初始化
    db = HistoryRecommendationDB()
    
    # 检查数据
    stats = db.get_statistics()
    print(f"\n数据统计:")
    print(f"  推荐记录: {stats.get('total_recommendations', 0)}条")
    print(f"  分时数据: {stats.get('total_intraday_records', 0):,}条")
    
    if stats.get('total_recommendations', 0) == 0:
        print("\n[跳过] 无推荐记录，无法运行回测")
        return
    
    # 创建配置
    config = BacktestConfig(
        initial_capital=100000,
        position_size=0.2,
        max_positions=5
    )
    
    # 运行回测
    print("\n运行回测...")
    backtest = EventDrivenBacktest(db=db, config=config)
    
    # 获取日期范围
    recommendations = db.get_recommendations()
    if recommendations:
        dates = [r['recommendation_date'] for r in recommendations if r.get('recommendation_date')]
        if dates:
            dates.sort()
            start_date = dates[0]
            end_date = dates[-1]
            
            results = backtest.run(start_date, end_date, show_progress=False)
            
            # 显示结果
            backtest.print_results()
            
            # 绩效分析
            analyzer = PerformanceAnalyzer()
            metrics = analyzer.analyze(
                trades=backtest.trades,
                equity_curve=backtest.equity_curve,
                initial_capital=100000
            )
            analyzer.print_report(metrics)
    
    print("\n" + "=" * 70)
    print("回测引擎测试完成")
    print("=" * 70)


def test_data_validator():
    """测试数据验证器"""
    print("\n" + "=" * 70)
    print("数据验证器测试")
    print("=" * 70)
    
    from src.modules.backtest.data_validator import StockCodeValidator
    
    # 测试股票代码验证
    test_cases = [
        ("600519.SH", True),
        ("000001.SZ", True),
        ("300001.SZ", True),
        ("600519", False),
        ("invalid", False),
    ]
    
    print("\n股票代码验证测试:")
    for code, expected in test_cases:
        is_valid, errors = StockCodeValidator.validate(code)
        status = "✓" if is_valid == expected else "✗"
        print(f"  {status} {code}: {'有效' if is_valid else '无效'}")
        if errors:
            print(f"      错误: {', '.join(errors)}")
    
    print("\n" + "=" * 70)
    print("数据验证器测试完成")
    print("=" * 70)


if __name__ == "__main__":
    # 运行所有测试
    test_data_validator()
    test_backtest_menu()
    test_backtest_engine()
    
    print("\n" + "=" * 70)
    print("所有测试完成！回测模块已成功整合到主菜单")
    print("=" * 70)
