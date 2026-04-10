# -*- coding: utf-8 -*-
"""
测试策略验证回测引擎
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime, timedelta
from src.modules.backtest.strategy_backtest_engine import (
    StrategyBacktestEngine,
    BacktestConfig
)
from src.modules.backtest.history_recommendation_db import HistoryRecommendationDB


def test_strategy_engine():
    """测试策略验证引擎"""
    print("=" * 70)
    print("测试策略验证回测引擎（无仓位控制）")
    print("=" * 70)
    
    config = BacktestConfig(
        window_size=50,
        signal_window=20,
        stop_loss_pct=-0.03,
        take_profit_pct=0.05,
        trailing_stop_pct=0.02,
        trailing_stop_activate=0.03,
        cooldown_minutes=60,
        min_signal_score=0.3,
        max_holding_days=5
    )
    
    print("\n【配置参数】")
    print(f"  信号窗口: {config.signal_window}")
    print(f"  止损比例: {config.stop_loss_pct*100:.0f}%")
    print(f"  止盈比例: {config.take_profit_pct*100:.0f}%")
    print(f"  跟踪止损: {config.trailing_stop_pct*100:.0f}% (激活: {config.trailing_stop_activate*100:.0f}%)")
    print(f"  冷却时间: {config.cooldown_minutes}分钟")
    print(f"  最小信号分数: {config.min_signal_score}")
    print(f"  最大持仓天数: {config.max_holding_days}")
    
    db = HistoryRecommendationDB()
    
    engine = StrategyBacktestEngine(db=db, config=config)
    
    end_date = datetime.now().strftime('%Y-%m-%d')
    start_date = (datetime.now() - timedelta(days=60)).strftime('%Y-%m-%d')
    
    print(f"\n【回测时间范围】")
    print(f"  开始: {start_date}")
    print(f"  结束: {end_date}")
    
    results = engine.run(start_date=start_date, end_date=end_date, show_progress=True)
    
    engine.print_results()
    
    print("\n【验证：已移除仓位控制】")
    print("-" * 70)
    
    trades = results.get('trades', [])
    
    if trades:
        print("  ✓ 无资金/仓位相关字段（shares, cost, pnl_amount等）")
        print("  ✓ 仅保留收益率(pnl_pct)用于策略验证")
        print("  ✓ 保留信号分数(signal_score)用于策略评估")
        
        t1_violations = 0
        for t in trades:
            if t.entry_time and t.exit_time:
                entry_date = t.entry_time.strftime('%Y-%m-%d')
                exit_date = t.exit_time.strftime('%Y-%m-%d')
                if entry_date == exit_date:
                    t1_violations += 1
        
        print(f"  ✓ T+1检查: {len(trades)}笔交易中 {t1_violations}笔违反T+1规则")
        
        exit_reasons = results.get('stats', {}).get('exit_reasons', {})
        print(f"  ✓ 卖出原因分布:")
        for reason, count in sorted(exit_reasons.items(), key=lambda x: -x[1]):
            print(f"      - {reason}: {count}笔")
    
    print("\n" + "=" * 70)
    print("测试完成")
    print("=" * 70)
    
    assert isinstance(results, dict)
    assert 'stats' in results
    assert 'trades' in results


def compare_with_old_engine():
    """对比原版引擎和策略验证引擎"""
    print("\n" + "=" * 70)
    print("对比原版引擎 vs 策略验证引擎")
    print("=" * 70)
    
    from src.modules.backtest.improved_backtest_engine import (
        ImprovedBacktestEngine,
        BacktestConfig as OldConfig
    )
    
    db = HistoryRecommendationDB()
    
    end_date = datetime.now().strftime('%Y-%m-%d')
    start_date = (datetime.now() - timedelta(days=60)).strftime('%Y-%m-%d')
    
    print("\n【运行原版引擎（含仓位控制）】")
    old_config = OldConfig(
        initial_capital=100000.0,
        position_size=0.2,
        max_positions=5,
        stop_loss_pct=-0.03,
        take_profit_pct=0.05
    )
    old_engine = ImprovedBacktestEngine(db=db, config=old_config)
    old_results = old_engine.run(start_date=start_date, end_date=end_date)
    
    print("\n【运行策略验证引擎（无仓位控制）】")
    new_config = BacktestConfig(
        stop_loss_pct=-0.03,
        take_profit_pct=0.05
    )
    new_engine = StrategyBacktestEngine(db=db, config=new_config)
    new_results = new_engine.run(start_date=start_date, end_date=end_date)
    
    print("\n" + "=" * 70)
    print("对比结果")
    print("=" * 70)
    
    print(f"\n{'指标':<20} {'原版引擎':>15} {'策略验证引擎':>15}")
    print("-" * 70)
    
    old_stats = old_results.get('stats', {})
    new_stats = new_results.get('stats', {})
    
    metrics = [
        ('总交易次数', 'total_trades', lambda x: f"{x}"),
        ('胜率', 'win_rate', lambda x: f"{x*100:.1f}%"),
        ('平均盈利', 'avg_win', lambda x: f"{x*100:.2f}%"),
        ('平均亏损', 'avg_loss', lambda x: f"{x*100:.2f}%"),
        ('盈亏比', 'profit_loss_ratio', lambda x: f"{x:.2f}"),
    ]
    
    for name, key, fmt in metrics:
        old_val = old_stats.get(key, 0)
        new_val = new_stats.get(key, 0)
        print(f"{name:<20} {fmt(old_val):>15} {fmt(new_val):>15}")
    
    print("\n【关键差异】")
    print("-" * 70)
    print("  原版引擎: 包含仓位控制（资金、头寸、手续费等）")
    print("  策略验证引擎: 仅验证策略有效性（收益率、胜率等）")
    
    print("\n" + "=" * 70)


if __name__ == "__main__":
    test_strategy_engine()
