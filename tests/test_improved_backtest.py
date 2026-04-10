# -*- coding: utf-8 -*-
"""
测试改进版回测引擎
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime, timedelta
from src.modules.backtest.improved_backtest_engine import (
    ImprovedBacktestEngine,
    BacktestConfig,
    StockState
)
from src.modules.backtest.history_recommendation_db import HistoryRecommendationDB


def test_improved_engine():
    """测试改进版引擎"""
    print("=" * 70)
    print("测试改进版事件驱动回测引擎")
    print("=" * 70)
    
    config = BacktestConfig(
        initial_capital=100000.0,
        position_size=0.2,
        max_positions=5,
        window_size=50,
        signal_window=20,
        stop_loss_pct=-0.03,
        take_profit_pct=0.05,
        trailing_stop_pct=0.02,
        trailing_stop_activate=0.03,
        commission_rate=0.0003,
        stamp_duty_rate=0.001,
        slippage_rate=0.001,
        cooldown_minutes=60,
        min_signal_score=0.3
    )
    
    print("\n【配置参数】")
    print(f"  初始资金: {config.initial_capital:,.0f}")
    print(f"  单只仓位: {config.position_size*100:.0f}%")
    print(f"  最大持仓: {config.max_positions}只")
    print(f"  止损比例: {config.stop_loss_pct*100:.0f}%")
    print(f"  止盈比例: {config.take_profit_pct*100:.0f}%")
    print(f"  跟踪止损: {config.trailing_stop_pct*100:.0f}% (激活: {config.trailing_stop_activate*100:.0f}%)")
    print(f"  冷却时间: {config.cooldown_minutes}分钟")
    print(f"  最小信号分数: {config.min_signal_score}")
    
    db = HistoryRecommendationDB()
    
    engine = ImprovedBacktestEngine(db=db, config=config)
    
    end_date = datetime.now().strftime('%Y-%m-%d')
    start_date = (datetime.now() - timedelta(days=60)).strftime('%Y-%m-%d')
    
    print(f"\n【回测时间范围】")
    print(f"  开始: {start_date}")
    print(f"  结束: {end_date}")
    
    results = engine.run(start_date=start_date, end_date=end_date, show_progress=True)
    
    engine.print_results()
    
    print("\n【改进点验证】")
    print("-" * 70)
    
    trades = results.get('trades', [])
    
    if trades:
        t1_violations = 0
        for t in trades:
            if t.entry_time and t.exit_time:
                entry_date = t.entry_time.strftime('%Y-%m-%d')
                exit_date = t.exit_time.strftime('%Y-%m-%d')
                if entry_date == exit_date:
                    t1_violations += 1
        
        print(f"  ✓ T+1检查: {len(trades)}笔交易中 {t1_violations}笔违反T+1规则")
        
        signal_types = {}
        for t in trades:
            reason = t.exit_reason or "未知"
            signal_types[reason] = signal_types.get(reason, 0) + 1
        
        print(f"  ✓ 卖出原因分布:")
        for reason, count in sorted(signal_types.items(), key=lambda x: -x[1]):
            print(f"      - {reason}: {count}笔")
        
        avg_score = sum(t.signal_score for t in trades if t.signal_score) / max(1, len([t for t in trades if t.signal_score]))
        print(f"  ✓ 平均信号分数: {avg_score:.2f}")
    
    print("\n" + "=" * 70)
    print("测试完成")
    print("=" * 70)
    
    assert isinstance(results, dict)
    assert 'stats' in results
    assert 'trades' in results


def compare_engines():
    """对比原版和改进版引擎"""
    print("\n" + "=" * 70)
    print("对比原版引擎 vs 改进版引擎")
    print("=" * 70)
    
    from src.modules.backtest.event_backtest_engine import EventDrivenBacktest, BacktestConfig as OldConfig
    
    db = HistoryRecommendationDB()
    
    end_date = datetime.now().strftime('%Y-%m-%d')
    start_date = (datetime.now() - timedelta(days=60)).strftime('%Y-%m-%d')
    
    print("\n【运行原版引擎】")
    old_config = OldConfig(
        initial_capital=100000.0,
        position_size=0.2,
        max_positions=5,
        stop_loss_pct=-0.03,
        take_profit_pct=0.05
    )
    old_engine = EventDrivenBacktest(db=db, config=old_config)
    old_results = old_engine.run(start_date=start_date, end_date=end_date)
    
    print("\n【运行改进版引擎】")
    new_config = BacktestConfig(
        initial_capital=100000.0,
        position_size=0.2,
        max_positions=5,
        stop_loss_pct=-0.03,
        take_profit_pct=0.05,
        trailing_stop_pct=0.02,
        trailing_stop_activate=0.03
    )
    new_engine = ImprovedBacktestEngine(db=db, config=new_config)
    new_results = new_engine.run(start_date=start_date, end_date=end_date)
    
    print("\n" + "=" * 70)
    print("对比结果")
    print("=" * 70)
    
    print(f"\n{'指标':<20} {'原版引擎':>15} {'改进版引擎':>15} {'变化':>15}")
    print("-" * 70)
    
    old_stats = old_results.get('stats', {})
    new_stats = new_results.get('stats', {})
    
    metrics = [
        ('总收益率', 'total_pnl_pct', lambda x: f"{x*100:.2f}%"),
        ('总交易次数', 'total_trades', lambda x: f"{x}"),
        ('胜率', 'win_rate', lambda x: f"{x*100:.1f}%"),
        ('平均盈利', 'avg_win', lambda x: f"{x*100:.2f}%"),
        ('平均亏损', 'avg_loss', lambda x: f"{x*100:.2f}%"),
        ('盈亏比', 'profit_loss_ratio', lambda x: f"{x:.2f}"),
    ]
    
    for name, key, fmt in metrics:
        old_val = old_stats.get(key, 0)
        new_val = new_stats.get(key, 0)
        
        if key in ['total_pnl_pct', 'win_rate', 'avg_win', 'avg_loss']:
            change = (new_val - old_val) * 100
            change_str = f"{change:+.2f}%"
        else:
            change = new_val - old_val
            change_str = f"{change:+.2f}"
        
        print(f"{name:<20} {fmt(old_val):>15} {fmt(new_val):>15} {change_str:>15}")
    
    print("\n" + "=" * 70)


if __name__ == "__main__":
    test_improved_engine()
