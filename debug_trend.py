"""
调试趋势过滤条件
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
logging.basicConfig(level=logging.INFO)

logger = logging.getLogger(__name__)


def debug_trend_filter():
    """调试趋势过滤条件"""
    print("调试趋势过滤条件")
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
        date_query = f"""
        SELECT DISTINCT trade_date
        FROM stock_daily
        WHERE trade_date <= '{latest_date}'
        ORDER BY trade_date DESC
        LIMIT 60
        """
        
        date_df = pd.read_sql_query(date_query, conn)
        date_list = date_df['trade_date'].tolist()
        date_condition = "', '".join(date_list)
        
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
        print(f"加载数据: {df.shape}")
        
        # 创建策略实例
        strategy = StrongPullbackStrategyFixed()
        
        # 准备特征
        print("\n准备特征...")
        df_features = strategy.prepare_features(df)
        print(f"特征数据形状: {df_features.shape}")
        
        # 只取最新日期的数据
        latest_data = df_features[df_features['trade_date'] == latest_date].copy()
        print(f"\n最新日期数据行数: {len(latest_data)}")
        
        # 应用基础过滤
        df1 = strategy.apply_base_filter(latest_data)
        print(f"基础过滤后: {len(df1)}")
        
        # 应用强势过滤
        df2 = strategy.apply_strength_filter(df1)
        print(f"强势过滤后: {len(df2)}")
        
        # 应用回调过滤
        df3 = strategy.apply_pullback_filter(df2)
        print(f"回调过滤后: {len(df3)}")
        
        # 应用缩量过滤
        df4 = strategy.apply_volume_filter(df3)
        print(f"缩量过滤后: {len(df4)}")
        
        if len(df4) == 0:
            print("缩量过滤后无数据")
            return
        
        # 检查趋势过滤条件
        cfg = strategy.config['trend_structure']
        print(f"\n趋势过滤条件:")
        print(f"1. MA5 > MA10")
        print(f"2. 收盘价 ≥ MA10的{cfg['close_above_ma10_ratio']*100:.0f}%")
        print(f"3. 收盘价在MA5的±{cfg['close_near_ma5_pct']*100:.0f}%内")
        
        # 检查趋势相关字段
        print(f"\n趋势字段统计:")
        
        # MA5和MA10
        print(f"MA5非空: {df4['ma5'].notna().sum()}/{len(df4)}")
        print(f"MA10非空: {df4['ma10'].notna().sum()}/{len(df4)}")
        
        # MA5 > MA10
        ma5_above_ma10 = df4['ma5'] > df4['ma10']
        print(f"MA5 > MA10: {ma5_above_ma10.sum()}/{len(df4)}")
        
        # 收盘价 ≥ MA10的99%
        close_above_ma10 = df4['close'] >= df4['ma10'] * cfg['close_above_ma10_ratio']
        print(f"收盘价≥MA10的{cfg['close_above_ma10_ratio']*100:.0f}%: {close_above_ma10.sum()}/{len(df4)}")
        
        # 收盘价在MA5的±3%内
        close_near_ma5 = ((df4['close'] - df4['ma5']).abs() / df4['ma5']) <= cfg['close_near_ma5_pct']
        print(f"收盘价在MA5的±{cfg['close_near_ma5_pct']*100:.0f}%内: {close_near_ma5.sum()}/{len(df4)}")
        
        # 显示一些示例数据
        print(f"\n趋势过滤前的股票示例:")
        sample = df4.head(5)
        for _, row in sample.iterrows():
            print(f"\n{row['ts_code']} - {row['name']}:")
            print(f"  收盘价: {row['close']:.2f}")
            print(f"  MA5: {row['ma5']:.2f}, MA10: {row['ma10']:.2f}")
            print(f"  MA5 > MA10: {row['ma5'] > row['ma10']}")
            print(f"  收盘价/MA10: {row['close']/row['ma10']:.3f} (需要≥{cfg['close_above_ma10_ratio']})")
            print(f"  收盘价-MA5距离: {abs(row['close'] - row['ma5'])/row['ma5']:.3%} (需要≤{cfg['close_near_ma5_pct']*100:.0f}%)")
        
        # 检查趋势过滤
        print(f"\n应用趋势过滤...")
        df5 = strategy.apply_trend_filter(df4)
        print(f"趋势过滤后: {len(df5)}")
        
        if len(df5) == 0:
            print("\n趋势过滤条件太严格，检查具体原因:")
            
            # 检查每个条件
            cond1 = df4['ma5'].notna() & df4['ma10'].notna()
            cond2 = ma5_above_ma10
            cond3 = close_above_ma10
            cond4 = close_near_ma5
            
            print(f"条件1 (MA5和MA10非空): {cond1.sum()}/{len(df4)}")
            print(f"条件2 (MA5 > MA10): {cond2.sum()}/{len(df4)}")
            print(f"条件3 (收盘价≥MA10的{cfg['close_above_ma10_ratio']*100:.0f}%): {cond3.sum()}/{len(df4)}")
            print(f"条件4 (收盘价在MA5的±{cfg['close_near_ma5_pct']*100:.0f}%内): {cond4.sum()}/{len(df4)}")
            
            # 检查组合条件
            all_cond = cond1 & cond2 & cond3 & cond4
            print(f"所有条件都满足: {all_cond.sum()}/{len(df4)}")
            
            # 显示不满足条件的股票
            for i in range(min(5, len(df4))):
                row = df4.iloc[i]
                print(f"\n股票 {row['ts_code']} - {row['name']}:")
                if not cond2.iloc[i]:
                    print(f"  MA5={row['ma5']:.2f} ≤ MA10={row['ma10']:.2f}")
                if not cond3.iloc[i]:
                    print(f"  收盘价/MA10={row['close']/row['ma10']:.3f} < {cfg['close_above_ma10_ratio']}")
                if not cond4.iloc[i]:
                    distance = abs(row['close'] - row['ma5'])/row['ma5']
                    print(f"  收盘价-MA5距离={distance:.3%} > {cfg['close_near_ma5_pct']*100:.0f}%")
        
        # 显示趋势过滤后的股票
        if len(df5) > 0:
            print(f"\n趋势过滤后的股票:")
            print(df5[['ts_code', 'name', 'close', 'ma5', 'ma10', 'ma10_slope']].head(10))
        
    finally:
        conn.close()


if __name__ == "__main__":
    debug_trend_filter()