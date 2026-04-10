"""
测试宽进严选策略框架
"""

import sqlite3
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import logging
import sys
import os

# 添加项目路径
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, current_dir)

from src.modules.wide_entry_strict_selection import WideEntryStrictSelection

# 设置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)


def load_real_data():
    """加载真实数据"""
    db_path = 'data/database/quant_system.db'
    conn = sqlite3.connect(db_path)
    
    try:
        # 加载最近3个月的数据
        query = """
        SELECT 
            d.ts_code,
            d.trade_date,
            d.open,
            d.high,
            d.low,
            d.close,
            d.vol,
            d.amount,
            d.pct_chg,
            b.name,
            b.list_date
        FROM stock_daily d
        LEFT JOIN stock_basic b ON d.ts_code = b.ts_code
        WHERE d.trade_date >= '20251201' AND d.trade_date <= '20260327'
        AND (d.ts_code LIKE '600%' OR d.ts_code LIKE '601%' OR 
             d.ts_code LIKE '603%' OR d.ts_code LIKE '605%' OR
             d.ts_code LIKE '000%' OR d.ts_code LIKE '001%' OR 
             d.ts_code LIKE '002%')
        ORDER BY d.ts_code, d.trade_date
        """
        
        df = pd.read_sql_query(query, conn)
        print(f"加载数据: {df.shape}")
        print(f"股票数量: {df['ts_code'].nunique()}")
        print(f"日期范围: {df['trade_date'].min()} 到 {df['trade_date'].max()}")
        
        return df
        
    finally:
        conn.close()


def test_wide_entry_strategy():
    """测试宽进严选策略"""
    print("=" * 80)
    print("测试宽进严选策略框架")
    print("=" * 80)
    
    # 1. 加载数据
    print("\n1. 加载数据...")
    df = load_real_data()
    
    if df is None or len(df) == 0:
        print("无法加载数据")
        return
    
    # 2. 创建策略引擎
    print("\n2. 创建策略引擎...")
    strategy = WideEntryStrictSelection()
    
    # 3. 运行策略
    print("\n3. 运行策略...")
    df_signals = strategy.run_strategy(df)
    
    # 4. 分析结果
    print("\n4. 分析结果...")
    results = strategy.analyze_results(df_signals)
    
    if results:
        print(f"总信号数量: {results['total_signals']}")
        print(f"有信号的交易日数量: {results['dates_with_signals']}")
        print(f"平均每日信号数: {results['avg_signals_per_day']:.2f}")
        print(f"最大单日信号数: {results['max_signals_per_day']}")
        print(f"有信号的股票数量: {results['stocks_with_signals']}")
        print(f"平均每股票信号数: {results['avg_signals_per_stock']:.2f}")
        
        # 显示过滤层统计
        print("\n过滤层通过率:")
        for filter_name, stats in results['filter_stats'].items():
            filter_display = filter_name.replace('_filter_pass', '').replace('_', ' ')
            print(f"  {filter_display:15}: {stats['通过数']:6d} ({stats['通过率']:.2%})")
    
    # 5. 查看具体信号
    print("\n5. 最近5个交易日的信号:")
    print("-" * 80)
    
    # 获取有信号的日期
    signal_dates = df_signals[df_signals['signal'] == 1]['trade_date'].unique()
    if len(signal_dates) > 0:
        recent_dates = sorted(signal_dates, reverse=True)[:5]
        
        for date in recent_dates:
            date_signals = df_signals[(df_signals['trade_date'] == date) & (df_signals['signal'] == 1)]
            if len(date_signals) > 0:
                print(f"\n{date}: {len(date_signals)}个信号")
                
                # 按评分排序
                date_signals = date_signals.sort_values('total_score', ascending=False)
                
                for i, (_, row) in enumerate(date_signals.head(3).iterrows(), 1):
                    print(f"\n{i}. {row['ts_code']} - {row['name']}")
                    print(f"   综合评分: {row['total_score']:.1f}")
                    print(f"   收盘价: {row['close']:.2f} | 涨幅: {row['pct_chg']:.2f}%")
                    
                    # 强势类型
                    if pd.notna(row['strength_type']):
                        print(f"   强势类型: {row['strength_type']}")
                    
                    # 回调信息
                    if pd.notna(row['days_since_last_strength']):
                        print(f"   强势后{row['days_since_last_strength']:.0f}天, 回撤: {row['drawdown']:.2%}")
                    
                    # 量能信息
                    print(f"   量比: {row['volume_ratio']:.2f}")
                    
                    # 趋势信息
                    print(f"   MA5: {row['ma5']:.2f} | MA10: {row['ma10']:.2f}")
                    print(f"   MA5斜率: {row['ma5_slope']:.4f} | MA10斜率: {row['ma10_slope']:.4f}")
                    
                    # 评分详情
                    print(f"   强势分: {row['strength_score']:.1f} | 回调分: {row['pullback_score']:.1f}")
                    print(f"   趋势分: {row['trend_score']:.1f} | 量能分: {row['volume_score']:.1f}")
            else:
                print(f"{date}: 无信号")
    else:
        print("没有找到任何信号")
    
    # 6. 保存结果
    print("\n6. 保存结果...")
    output_dir = 'reports/wide_entry_strategy'
    os.makedirs(output_dir, exist_ok=True)
    
    # 保存信号
    signals_df = df_signals[df_signals['signal'] == 1].copy()
    if len(signals_df) > 0:
        columns_to_save = [
            'trade_date', 'ts_code', 'name', 'close', 'pct_chg',
            'total_score', 'strength_score', 'pullback_score', 
            'trend_score', 'volume_score', 'strength_type',
            'days_since_last_strength', 'drawdown', 'volume_ratio',
            'ma5', 'ma10', 'ma5_slope', 'ma10_slope'
        ]
        
        output_path = os.path.join(output_dir, 'signals.csv')
        signals_df[columns_to_save].to_csv(output_path, index=False, encoding='utf-8-sig')
        print(f"信号已保存到: {output_path}")
        
        # 保存统计信息
        stats_path = os.path.join(output_dir, 'stats.txt')
        with open(stats_path, 'w', encoding='utf-8') as f:
            f.write("宽进严选策略信号统计\n")
            f.write("=" * 50 + "\n")
            f.write(f"总信号数量: {results['total_signals']}\n")
            f.write(f"有信号的交易日数量: {results['dates_with_signals']}\n")
            f.write(f"平均每日信号数: {results['avg_signals_per_day']:.2f}\n")
            f.write(f"最大单日信号数: {results['max_signals_per_day']}\n")
            f.write(f"有信号的股票数量: {results['stocks_with_signals']}\n")
            f.write(f"平均每股票信号数: {results['avg_signals_per_stock']:.2f}\n")
            
            f.write("\n过滤层通过率:\n")
            for filter_name, stats in results['filter_stats'].items():
                filter_display = filter_name.replace('_filter_pass', '').replace('_', ' ')
                f.write(f"{filter_display:15}: {stats['通过数']:6d} ({stats['通过率']:.2%})\n")
            
            f.write("\n按日期统计:\n")
            date_counts = signals_df.groupby('trade_date').size()
            for date, count in date_counts.head(20).items():
                f.write(f"{date}: {count}个信号\n")
            
            f.write("\n按股票统计(前20):\n")
            stock_counts = signals_df.groupby(['ts_code', 'name']).size().sort_values(ascending=False).head(20)
            for (code, name), count in stock_counts.items():
                f.write(f"{code} - {name}: {count}次\n")
        
        print(f"统计信息已保存到: {stats_path}")
    
    print("\n" + "=" * 80)
    print("测试完成!")
    print("=" * 80)


def compare_with_old_strategy():
    """对比新旧策略效果"""
    print("\n" + "=" * 80)
    print("对比新旧策略效果")
    print("=" * 80)
    
    # 加载数据
    df = load_real_data()
    if df is None or len(df) == 0:
        print("无法加载数据")
        return
    
    # 测试原策略(简化版)
    print("\n1. 测试原策略(简化版)...")
    from src.modules.strong_pullback_simple import StrongPullbackSimple
    old_strategy = StrongPullbackSimple()
    old_signals = old_strategy.run_strategy(df)
    old_total = old_signals['signal'].sum()
    
    # 测试新策略
    print("\n2. 测试新策略(宽进严选)...")
    new_strategy = WideEntryStrictSelection()
    new_signals = new_strategy.run_strategy(df)
    new_total = new_signals['signal'].sum()
    
    # 对比结果
    print("\n3. 策略对比:")
    print("-" * 80)
    print(f"{'指标':<20} {'原策略':>10} {'新策略':>10} {'变化':>10}")
    print("-" * 80)
    print(f"{'总信号数量':<20} {old_total:>10} {new_total:>10} {new_total-old_total:>+10}")
    
    # 按日期对比
    old_by_date = old_signals.groupby('trade_date')['signal'].sum()
    new_by_date = new_signals.groupby('trade_date')['signal'].sum()
    
    old_dates = (old_by_date > 0).sum()
    new_dates = (new_by_date > 0).sum()
    print(f"{'有信号交易日数':<20} {old_dates:>10} {new_dates:>10} {new_dates-old_dates:>+10}")
    
    old_avg = old_by_date.mean() if len(old_by_date) > 0 else 0
    new_avg = new_by_date.mean() if len(new_by_date) > 0 else 0
    print(f"{'平均每日信号数':<20} {old_avg:>10.2f} {new_avg:>10.2f} {new_avg-old_avg:>+10.2f}")
    
    # 按股票对比
    old_by_stock = old_signals.groupby('ts_code')['signal'].sum()
    new_by_stock = new_signals.groupby('ts_code')['signal'].sum()
    
    old_stocks = (old_by_stock > 0).sum()
    new_stocks = (new_by_stock > 0).sum()
    print(f"{'有信号股票数':<20} {old_stocks:>10} {new_stocks:>10} {new_stocks-old_stocks:>+10}")
    
    # 信号重叠分析
    if old_total > 0 and new_total > 0:
        # 获取有信号的日期
        old_signal_dates = set(old_signals[old_signals['signal'] == 1]['trade_date'].unique())
        new_signal_dates = set(new_signals[new_signals['signal'] == 1]['trade_date'].unique())
        
        overlap_dates = old_signal_dates.intersection(new_signal_dates)
        overlap_ratio = len(overlap_dates) / len(new_signal_dates) if len(new_signal_dates) > 0 else 0
        
        print(f"{'日期重叠率':<20} {'-':>10} {'-':>10} {overlap_ratio:>10.1%}")
        
        # 获取有信号的股票
        old_signal_stocks = set(old_signals[old_signals['signal'] == 1]['ts_code'].unique())
        new_signal_stocks = set(new_signals[new_signals['signal'] == 1]['ts_code'].unique())
        
        overlap_stocks = old_signal_stocks.intersection(new_signal_stocks)
        overlap_stock_ratio = len(overlap_stocks) / len(new_signal_stocks) if len(new_signal_stocks) > 0 else 0
        
        print(f"{'股票重叠率':<20} {'-':>10} {'-':>10} {overlap_stock_ratio:>10.1%}")
    
    print("-" * 80)
    print("\n结论:")
    if new_total > old_total * 1.5:
        print("✅ 新策略显著增加了信号数量")
    elif new_total > old_total:
        print("✅ 新策略略微增加了信号数量")
    elif new_total == 0:
        print("❌ 新策略仍然没有信号，需要进一步调整")
    else:
        print("⚠️  新策略信号数量变化不大")
    
    if new_dates > old_dates:
        print("✅ 新策略增加了有信号的交易日")
    
    if new_stocks > old_stocks:
        print("✅ 新策略覆盖了更多股票")


def analyze_sample_progression():
    """分析样本数量变化"""
    print("\n" + "=" * 80)
    print("分析样本数量变化")
    print("=" * 80)
    
    # 加载数据
    df = load_real_data()
    if df is None or len(df) == 0:
        print("无法加载数据")
        return
    
    # 使用最后一天的数据进行分析
    last_date = df['trade_date'].max()
    df_last = df[df['trade_date'] == last_date].copy()
    
    print(f"分析日期: {last_date}")
    print(f"总股票数: {len(df_last)}")
    
    # 创建策略实例
    strategy = WideEntryStrictSelection()
    
    # 准备特征
    df_features = strategy.prepare_features(df_last)
    
    # 逐步应用过滤
    print("\n过滤层样本变化:")
    print("-" * 80)
    
    # 基础过滤
    df_basic = strategy.apply_basic_filter(df_features)
    basic_count = df_basic['basic_filter_pass'].sum()
    print(f"1. 基础过滤后: {basic_count}/{len(df_last)} ({basic_count/len(df_last):.2%})")
    
    # 强势过滤
    df_strength = strategy.apply_strength_filter(df_basic[df_basic['basic_filter_pass'] == 1])
    strength_count = df_strength['strength_filter_pass'].sum()
    print(f"2. 强势过滤后: {strength_count}/{basic_count} ({strength_count/basic_count:.2%})")
    
    # 回调过滤
    df_pullback = strategy.apply_pullback_filter(df_strength[df_strength['strength_filter_pass'] == 1])
    pullback_count = df_pullback['pullback_filter_pass'].sum()
    print(f"3. 回调过滤后: {pullback_count}/{strength_count} ({pullback_count/strength_count:.2%})")
    
    # 缩量过滤
    df_volume = strategy.apply_volume_filter(df_pullback[df_pullback['pullback_filter_pass'] == 1])
    volume_count = df_volume['volume_filter_pass'].sum()
    print(f"4. 缩量过滤后: {volume_count}/{pullback_count} ({volume_count/pullback_count:.2%})")
    
    # 趋势过滤
    df_trend = strategy.apply_trend_filter(df_volume[df_volume['volume_filter_pass'] == 1])
    trend_count = df_trend['trend_filter_pass'].sum()
    print(f"5. 趋势过滤后: {trend_count}/{volume_count} ({trend_count/volume_count:.2%})")
    
    # 波动过滤
    df_volatility = strategy.apply_volatility_filter(df_trend[df_trend['trend_filter_pass'] == 1])
    volatility_count = df_volatility['volatility_filter_pass'].sum()
    print(f"6. 波动过滤后: {volatility_count}/{trend_count} ({volatility_count/trend_count:.2%})")
    
    print("-" * 80)
    print(f"最终候选: {volatility_count}/{len(df_last)} ({volatility_count/len(df_last):.2%})")
    
    # 分析过滤瓶颈
    print("\n过滤瓶颈分析:")
    print("-" * 80)
    
    filter_stats = [
        ("基础过滤", basic_count, len(df_last), basic_count/len(df_last)),
        ("强势过滤", strength_count, basic_count, strength_count/basic_count if basic_count > 0 else 0),
        ("回调过滤", pullback_count, strength_count, pullback_count/strength_count if strength_count > 0 else 0),
        ("缩量过滤", volume_count, pullback_count, volume_count/pullback_count if pullback_count > 0 else 0),
        ("趋势过滤", trend_count, volume_count, trend_count/volume_count if volume_count > 0 else 0),
        ("波动过滤", volatility_count, trend_count, volatility_count/trend_count if trend_count > 0 else 0),
    ]
    
    for name, passed, total, rate in filter_stats:
        print(f"{name:10}: {passed:4d}/{total:4d} ({rate:.2%})")
    
    # 找出最严格的过滤层
    min_rate = min(rate for _, _, _, rate in filter_stats if rate > 0)
    bottleneck = [name for name, _, _, rate in filter_stats if rate == min_rate][0]
    print(f"\n最严格过滤层: {bottleneck} (通过率: {min_rate:.2%})")


def main():
    """主函数"""
    print("宽进严选策略测试")
    print("=" * 80)
    
    # 测试新策略
    test_wide_entry_strategy()
    
    # 对比新旧策略
    compare_with_old_strategy()
    
    # 分析样本变化
    analyze_sample_progression()
    
    print("\n" + "=" * 80)
    print("测试完成!")
    print("=" * 80)
    
    print("\n策略改进总结:")
    print("1. ✅ 宽进: 使用'强势事件集合'替代单一涨停条件")
    print("2. ✅ 严选: 多层质量过滤确保信号质量")
    print("3. ✅ 评分: 综合评分系统选出最优候选")
    print("4. ✅ 调试: 清晰的过滤层统计便于优化")
    print("\n下一步建议:")
    print("1. 如果信号仍然不足，可以进一步放宽强势入口条件")
    print("2. 如果信号过多，可以收紧回调或趋势条件")
    print("3. 进行回测验证信号有效性")
    print("4. 优化评分权重参数")


if __name__ == "__main__":
    main()
