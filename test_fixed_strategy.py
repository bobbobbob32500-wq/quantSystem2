"""
测试修复后的策略
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

from src.modules.final_strategy_fixed import FinalStrategyFixed

# 设置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)


def test_fixed_strategy():
    """测试修复后的策略"""
    print("=" * 80)
    print("测试修复后的策略")
    print("=" * 80)
    
    # 连接数据库
    db_path = 'data/database/quant_system.db'
    conn = sqlite3.connect(db_path)
    
    try:
        # 加载最新数据
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
        WHERE d.trade_date = '20260327'
        AND (d.ts_code LIKE '600%' OR d.ts_code LIKE '601%' OR 
             d.ts_code LIKE '603%' OR d.ts_code LIKE '605%' OR
             d.ts_code LIKE '000%' OR d.ts_code LIKE '001%' OR 
             d.ts_code LIKE '002%')
        ORDER BY d.ts_code
        """
        
        df = pd.read_sql_query(query, conn)
        print(f"加载数据: {df.shape}")
        
        if len(df) == 0:
            print("没有数据")
            return
        
        # 创建策略实例
        strategy = FinalStrategyFixed()
        
        # 运行选股
        print("\n运行选股...")
        candidates = strategy.select_candidates(df, date='20260327')
        
        if len(candidates) == 0:
            print("没有找到候选股票")
            print("\n可能原因:")
            print("1. 市场环境不适合")
            print("2. 数据质量问题")
            print("3. 策略条件仍然过严")
            return
        
        # 生成买点建议
        print("\n生成买点建议...")
        buy_points = strategy.get_buy_points(candidates)
        
        # 输出结果
        print(f"\n找到 {len(candidates)} 只候选股票:")
        print("-" * 80)
        
        for i, (_, row) in enumerate(buy_points.iterrows(), 1):
            print(f"\n{i}. {row['ts_code']} - {row['name']}")
            print(f"   综合评分: {row['total_score']:.1f}")
            print(f"   收盘价: {row['close']:.2f}")
            print(f"   强势类型: {row['strength_type']}")
            print(f"   强势后{row['days_since_strength']:.0f}天, 回撤: {row['drawdown']:.2%}")
            print(f"   量比: {row['volume_ratio']:.2f}")
            print(f"   MA5: {row['ma5']:.2f}, MA10: {row['ma10']:.2f}")
            print(f"   买点类型: {row['buy_type']}")
            print(f"   建议买入价: {row['buy_price']:.2f}")
            print(f"   买入理由: {row['buy_reason']}")
        
        # 保存结果
        print("\n保存结果...")
        output_dir = 'reports/real_trading'
        os.makedirs(output_dir, exist_ok=True)
        
        output_path = os.path.join(output_dir, 'fixed_strategy_candidates.csv')
        candidates.to_csv(output_path, index=False, encoding='utf-8-sig')
        print(f"候选列表已保存到: {output_path}")
        
        buy_points_path = os.path.join(output_dir, 'fixed_strategy_buy_points.csv')
        buy_points.to_csv(buy_points_path, index=False, encoding='utf-8-sig')
        print(f"买点建议已保存到: {buy_points_path}")
        
        print("\n" + "=" * 80)
        print("测试完成!")
        print("=" * 80)
        
    finally:
        conn.close()


def test_with_history_data():
    """使用历史数据测试"""
    print("\n" + "=" * 80)
    print("使用历史数据测试")
    print("=" * 80)
    
    # 连接数据库
    db_path = 'data/database/quant_system.db'
    conn = sqlite3.connect(db_path)
    
    try:
        # 加载多日数据
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
        WHERE d.trade_date >= '20260301' AND d.trade_date <= '20260327'
        AND (d.ts_code LIKE '600%' OR d.ts_code LIKE '601%' OR 
             d.ts_code LIKE '603%' OR d.ts_code LIKE '605%' OR
             d.ts_code LIKE '000%' OR d.ts_code LIKE '001%' OR 
             d.ts_code LIKE '002%')
        ORDER BY d.trade_date, d.ts_code
        """
        
        df = pd.read_sql_query(query, conn)
        print(f"加载数据: {df.shape}")
        print(f"日期范围: {df['trade_date'].min()} 到 {df['trade_date'].max()}")
        
        if len(df) == 0:
            print("没有数据")
            return
        
        # 创建策略实例
        strategy = FinalStrategyFixed()
        
        # 按日期测试
        dates = sorted(df['trade_date'].unique())
        results = []
        
        print("\n按日期测试策略:")
        print("-" * 80)
        
        for date in dates[-10:]:  # 最近10个交易日
            print(f"测试日期: {date}", end='\r')
            
            # 选股
            candidates = strategy.select_candidates(df, date=date)
            
            results.append({
                'date': date,
                'candidates': len(candidates)
            })
        
        print("\n测试结果:")
        print("-" * 80)
        
        results_df = pd.DataFrame(results)
        print(f"测试天数: {len(results_df)}")
        print(f"平均每日候选数: {results_df['candidates'].mean():.1f}")
        print(f"最大候选数: {results_df['candidates'].max()}")
        print(f"最小候选数: {results_df['candidates'].min()}")
        print(f"有候选的天数: {(results_df['candidates'] > 0).sum()}")
        
        # 保存结果
        output_dir = 'reports/real_trading'
        os.makedirs(output_dir, exist_ok=True)
        
        history_path = os.path.join(output_dir, 'history_test_results.csv')
        results_df.to_csv(history_path, index=False, encoding='utf-8-sig')
        print(f"\n历史测试结果已保存到: {history_path}")
        
    finally:
        conn.close()


def main():
    """主函数"""
    print("修复版策略测试")
    print("=" * 80)
    
    # 测试修复后的策略
    test_fixed_strategy()
    
    # 使用历史数据测试
    test_with_history_data()
    
    print("\n" + "=" * 80)
    print("总结:")
    print("=" * 80)
    print("\n修复内容:")
    print("1. 放宽了基础过滤条件(股价、成交额、跌停次数)")
    print("2. 放宽了强势过滤条件(涨幅、放量倍数)")
    print("3. 放宽了回调过滤条件(回调天数、回撤幅度)")
    print("4. 修复了特征计算问题(处理NaN值)")
    print("5. 调整了涨停检测逻辑")
    
    print("\n预期效果:")
    print("• 能够选出候选股票")
    print("• 条件更加合理")
    print("• 适应更多市场环境")
    
    print("\n使用建议:")
    print("1. 每日收盘后运行选股")
    print("2. 关注买点建议")
    print("3. 严格执行交易纪律")
    print("4. 定期复盘优化")


if __name__ == "__main__":
    main()
