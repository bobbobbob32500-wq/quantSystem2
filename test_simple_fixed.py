"""
简化版测试 - 只测试最新日期
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

from src.modules.strong_pullback_fixed_v2 import StrongPullbackStrategyFixed

# 设置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)


def load_historical_data_simple(latest_date: str, lookback_days: int = 60):
    """简化版历史数据加载"""
    db_path = 'data/database/quant_system.db'
    conn = sqlite3.connect(db_path)
    
    try:
        # 获取最近N个交易日
        date_query = f"""
        SELECT DISTINCT trade_date
        FROM stock_daily
        WHERE trade_date <= '{latest_date}'
        ORDER BY trade_date DESC
        LIMIT {lookback_days}
        """
        
        date_df = pd.read_sql_query(date_query, conn)
        if date_df.empty:
            print("没有找到交易日数据")
            return pd.DataFrame()
        
        date_list = date_df['trade_date'].tolist()
        date_condition = "', '".join(date_list)
        
        # 只加载主板股票
        query = f"""
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
        WHERE d.trade_date IN ('{date_condition}')
        AND (d.ts_code LIKE '600%' OR d.ts_code LIKE '601%' OR 
             d.ts_code LIKE '603%' OR d.ts_code LIKE '605%' OR
             d.ts_code LIKE '000%' OR d.ts_code LIKE '001%' OR 
             d.ts_code LIKE '002%')
        AND d.close > 0
        AND d.vol > 0
        ORDER BY d.ts_code, d.trade_date
        """
        
        df = pd.read_sql_query(query, conn)
        print(f"加载历史数据: {df.shape}")
        print(f"日期范围: {df['trade_date'].min()} 到 {df['trade_date'].max()}")
        print(f"交易日数量: {df['trade_date'].nunique()}")
        print(f"股票数量: {df['ts_code'].nunique()}")
        
        return df
        
    finally:
        conn.close()


def test_single_date():
    """测试单个日期"""
    print("=" * 80)
    print("修正版策略 - 单日测试")
    print("=" * 80)
    
    # 连接数据库
    db_path = 'data/database/quant_system.db'
    conn = sqlite3.connect(db_path)
    
    try:
        # 获取最新日期
        query_date = """
        SELECT MAX(trade_date) as latest_date FROM stock_daily
        WHERE trade_date >= '20251201'
        """
        df_date = pd.read_sql_query(query_date, conn)
        latest_date = df_date['latest_date'].iloc[0]
        
        print(f"测试日期: {latest_date}")
        
        # 加载历史数据
        df = load_historical_data_simple(latest_date, lookback_days=60)
        
        if df.empty:
            print("无法加载历史数据")
            return
        
        # 创建策略实例
        strategy = StrongPullbackStrategyFixed()
        
        # 准备特征
        print("\n准备特征数据...")
        df_features = strategy.prepare_features(df)
        print(f"特征数据形状: {df_features.shape}")
        
        # 检查特征列
        print("\n特征列:")
        print(df_features.columns.tolist())
        
        # 检查最新日期的数据
        latest_data = df_features[df_features['trade_date'] == latest_date]
        print(f"\n最新日期数据行数: {len(latest_data)}")
        
        if len(latest_data) > 0:
            print("\n最新日期数据示例:")
            print(latest_data[['ts_code', 'close', 'pct_chg', 'is_limit_up', 'return_5', 'return_10']].head())
        
        # 运行选股
        print(f"\n运行选股...")
        candidates = strategy.select_candidates(df, date=latest_date)
        
        if len(candidates) == 0:
            print("警告: 今日无符合条件的候选股票")
            
            # 检查过滤层
            print("\n检查过滤层:")
            
            # 基础过滤
            df1 = strategy.apply_base_filter(df_features)
            print(f"1. 基础过滤后: {len(df1)}")
            
            if len(df1) > 0:
                # 强势过滤
                df2 = strategy.apply_strength_filter(df1)
                print(f"2. 强势过滤后: {len(df2)}")
                
                if len(df2) > 0:
                    # 回调过滤
                    df3 = strategy.apply_pullback_filter(df2)
                    print(f"3. 回调过滤后: {len(df3)}")
                    
                    if len(df3) > 0:
                        # 缩量过滤
                        df4 = strategy.apply_volume_filter(df3)
                        print(f"4. 缩量过滤后: {len(df4)}")
                        
                        if len(df4) > 0:
                            # 趋势过滤
                            df5 = strategy.apply_trend_filter(df4)
                            print(f"5. 趋势过滤后: {len(df5)}")
                            
                            if len(df5) > 0:
                                # 趋势方向过滤
                                df6 = strategy.apply_trend_direction_filter(df5)
                                print(f"6. 趋势方向过滤后: {len(df6)}")
                                
                                if len(df6) > 0:
                                    # 评分
                                    df_scored = strategy.calculate_scores(df6)
                                    min_score = strategy.config['scoring']['min_total_score']
                                    df_scored = df_scored[df_scored['total_score'] >= min_score]
                                    print(f"7. 评分过滤后(≥{min_score}): {len(df_scored)}")
            
            print("\n可能原因:")
            print("1. 市场环境不适合(如大跌、恐慌)")
            print("2. 策略条件过于严格")
            print("3. 数据质量问题")
            print("\n建议:")
            print("1. 检查市场整体涨跌情况")
            print("2. 适当放宽条件(如回调天数、回撤幅度)")
            print("3. 等待下一个交易日")
            return
        
        # 生成观察建议
        print("\n生成观察建议...")
        watchlist = strategy.get_watchlist_notes(candidates)
        
        # 输出结果
        print(f"\n选股结果(共{len(candidates)}只):")
        print("-" * 80)
        print(f"日期: {latest_date}")
        print("-" * 80)
        
        for i, (_, row) in enumerate(watchlist.iterrows(), 1):
            print(f"\n{i}. {row['ts_code']} - {row['name']}")
            print(f"   综合评分: {row['total_score']:.1f}")
            print(f"   收盘价: {row['close']:.2f}")
            print(f"   强势类型: {row['strength_type']}")
            if pd.notna(row['strength_event_date']):
                print(f"   强势日: {row['strength_event_date']}")
            print(f"   强势后天数: {row['days_since_strength']:.0f}")
            print(f"   回撤: {row['drawdown']:.2%}")
            print(f"   量比: {row['volume_ratio']:.2f}")
            print(f"   MA5: {row['ma5']:.2f}, MA10: {row['ma10']:.2f}")
            print(f"   观察重点: {row['watch_notes']}")
        
        # 保存结果
        print("\n保存结果...")
        output_dir = 'reports/real_trading'
        os.makedirs(output_dir, exist_ok=True)
        
        # 保存候选列表
        output_path = os.path.join(output_dir, f'candidates_fixed_{latest_date}.csv')
        candidates.to_csv(output_path, index=False, encoding='utf-8-sig')
        print(f"候选列表已保存到: {output_path}")
        
        # 保存观察建议
        watchlist_path = os.path.join(output_dir, f'watchlist_fixed_{latest_date}.csv')
        watchlist.to_csv(watchlist_path, index=False, encoding='utf-8-sig')
        print(f"观察建议已保存到: {watchlist_path}")
        
        print("\n" + "=" * 80)
        print("测试完成!")
        print("=" * 80)
        
    finally:
        conn.close()


def main():
    """主函数"""
    print("修正版策略 - 简化测试")
    print("=" * 80)
    
    print("\n关键修复:")
    print("1. 历史数据加载: 加载60个交易日数据，避免单日数据问题")
    print("2. 强势事件锚点: 只标记当天发生的强势事件，避免滚动计数问题")
    print("3. 回调基准计算: 正确计算从强势日起的回撤和收益")
    print("4. 前高计算: 使用shift(1)避免包含当天")
    print("5. NaN值处理: 不再全局fillna(0)，使用notna()过滤")
    print("6. 趋势评分: 修复跨股票shift问题")
    print("7. 条件收紧: 跌停次数限制为1次，MA10斜率≥0")
    print("8. 观察建议: 替代买点建议，更符合T+1盘中交易逻辑")
    
    print("\n" + "=" * 80)
    print("开始测试...")
    print("=" * 80)
    
    # 运行单日测试
    test_single_date()


if __name__ == "__main__":
    main()