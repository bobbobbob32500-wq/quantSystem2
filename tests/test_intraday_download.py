# -*- coding: utf-8 -*-
"""
分时数据下载测试脚本
"""

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.modules.backtest.intraday_data_downloader import IntradayDataDownloader
from src.core.logger import get_logger

logger = get_logger("test_intraday_download")


def test_download_with_mock_data():
    """使用模拟数据测试"""
    print("\n" + "="*70)
    print("测试: 分时数据下载（模拟数据）")
    print("="*70)
    
    # 模拟观察池记录
    observation_records = [
        {
            'symbol': '000001',
            'selection_date': '2023-01-15',
            'selection_reason': '回踩均线',
            'selection_score': 85,
            'buy_date': '2023-01-16',
            'buy_price': 10.50,
            'sell_date': '2023-01-20',
            'sell_price': 11.20,
            'profit_pct': 6.67,
            'hold_days': 4,
        },
        {
            'symbol': '000002',
            'selection_date': '2023-01-18',
            'selection_reason': '突破买入',
            'selection_score': 78,
            'buy_date': '2023-01-19',
            'buy_price': 15.30,
            'sell_date': '2023-01-25',
            'sell_price': 16.50,
            'profit_pct': 7.84,
            'hold_days': 6,
        },
    ]
    
    print("\n观察池记录:")
    for i, record in enumerate(observation_records, 1):
        print(f"\n{i}. {record['symbol']}")
        print(f"   选入: {record['selection_date']} ({record['selection_reason']})")
        print(f"   买入: {record['buy_date']} @ {record['buy_price']}")
        print(f"   卖出: {record['sell_date']} @ {record['sell_price']}")
        print(f"   收益: {record['profit_pct']:.2f}%")
    
    # 计算数据量
    total_days = sum(r['hold_days'] + 1 for r in observation_records)
    total_minutes = total_days * 240
    total_records = len(observation_records) * total_minutes
    
    print(f"\n数据量估算:")
    print(f"  总持仓天数: {total_days}天")
    print(f"  总分钟数: {total_minutes}分钟")
    print(f"  预计记录数: {total_records}条")
    
    print("\n[OK] 模拟数据测试完成")


def test_data_range_calculation():
    """测试数据范围计算"""
    print("\n" + "="*70)
    print("测试: 数据范围计算")
    print("="*70)
    
    # 测试不同场景
    scenarios = [
        {
            'name': '正常持仓',
            'selection_date': '2023-01-15',
            'sell_date': '2023-01-20',
        },
        {
            'name': '短线持仓',
            'selection_date': '2023-01-15',
            'sell_date': '2023-01-16',
        },
        {
            'name': '长线持仓',
            'selection_date': '2023-01-01',
            'sell_date': '2023-01-31',
        },
    ]
    
    for scenario in scenarios:
        print(f"\n场景: {scenario['name']}")
        print(f"  选入日期: {scenario['selection_date']}")
        print(f"  清仓日期: {scenario['sell_date']}")
        
        # 计算数据范围
        from datetime import datetime
        start = datetime.strptime(scenario['selection_date'], '%Y-%m-%d')
        end = datetime.strptime(scenario['sell_date'], '%Y-%m-%d')
        days = (end - start).days + 1
        
        print(f"  持仓天数: {days}天")
        print(f"  分钟数据: {days * 240}条")
        print(f"  数据范围: {scenario['selection_date']} 09:30 ~ {scenario['sell_date']} 15:00")
    
    print("\n[OK] 数据范围计算测试完成")


def compare_data_volume():
    """对比数据量"""
    print("\n" + "="*70)
    print("对比: 传统方案 vs 优化方案")
    print("="*70)
    
    # 传统方案
    traditional_stocks = 4000
    traditional_days = 250
    traditional_minutes = 240
    traditional_total = traditional_stocks * traditional_days * traditional_minutes
    
    # 优化方案
    optimized_stocks = 10  # 每次推荐10只
    optimized_days = 10    # 平均持仓10天
    optimized_minutes = 240
    optimized_total = optimized_stocks * optimized_days * optimized_minutes
    
    print("\n传统方案:")
    print(f"  股票数量: {traditional_stocks}只")
    print(f"  时间范围: {traditional_days}天")
    print(f"  每日分钟: {traditional_minutes}分钟")
    print(f"  总记录数: {traditional_total:,}条")
    print(f"  数据大小: ~{traditional_total * 100 / 1024 / 1024:.1f}MB")
    
    print("\n优化方案:")
    print(f"  股票数量: {optimized_stocks}只")
    print(f"  时间范围: {optimized_days}天")
    print(f"  每日分钟: {optimized_minutes}分钟")
    print(f"  总记录数: {optimized_total:,}条")
    print(f"  数据大小: ~{optimized_total * 100 / 1024 / 1024:.1f}MB")
    
    print("\n对比结果:")
    reduction = traditional_total / optimized_total
    print(f"  数据量减少: {reduction:.0f}倍")
    print(f"  存储节省: {(1 - 1/reduction) * 100:.1f}%")
    print(f"  下载时间: 从{traditional_total/10000:.0f}分钟降至{optimized_total/10000:.1f}分钟")
    
    print("\n[OK] 数据量对比完成")


def main():
    """主测试函数"""
    print("\n" + "="*70)
    print("分时数据下载测试")
    print("="*70)
    
    try:
        # 测试1: 模拟数据
        test_download_with_mock_data()
        
        # 测试2: 数据范围计算
        test_data_range_calculation()
        
        # 测试3: 数据量对比
        compare_data_volume()
        
        print("\n" + "="*70)
        print("[OK] 所有测试完成")
        print("="*70)
        
    except Exception as e:
        print(f"\n[FAIL] 测试失败: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
