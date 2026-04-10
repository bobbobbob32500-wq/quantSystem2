"""
调试回调过滤条件
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


def debug_pullback_filter():
    """调试回调过滤条件"""
    print("调试回调过滤条件")
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
        
        if len(df2) == 0:
            print("强势过滤后无数据")
            return
        
        # 检查回调过滤条件
        cfg = strategy.config['pullback_structure']
        print(f"\n回调过滤条件:")
        print(f"1. 回调天数: {cfg['days_range'][0]}-{cfg['days_range'][1]}天")
        print(f"2. 回撤幅度: {cfg['drawdown_range'][0]*100:.1f}%-{cfg['drawdown_range'][1]*100:.1f}%")
        print(f"3. 回调速度: ≤{cfg['decay_ratio_max']}")
        print(f"4. 下跌天数比例: ≤{cfg['down_days_ratio_max']*100:.0f}%")
        
        # 检查回调相关字段
        print(f"\n回调字段统计:")
        
        # days_since_last_strength
        print(f"days_since_last_strength:")
        print(f"  非空值: {df2['days_since_last_strength'].notna().sum()}/{len(df2)}")
        print(f"  范围: {df2['days_since_last_strength'].min():.0f} - {df2['days_since_last_strength'].max():.0f}")
        print(f"  在[{cfg['days_range'][0]}, {cfg['days_range'][1]}]内: {df2['days_since_last_strength'].between(cfg['days_range'][0], cfg['days_range'][1]).sum()}")
        
        # drawdown
        print(f"\ndrawdown:")
        print(f"  非空值: {df2['drawdown'].notna().sum()}/{len(df2)}")
        print(f"  范围: {df2['drawdown'].min():.3f} - {df2['drawdown'].max():.3f}")
        print(f"  在[{cfg['drawdown_range'][0]}, {cfg['drawdown_range'][1]}]内: {df2['drawdown'].between(cfg['drawdown_range'][0], cfg['drawdown_range'][1]).sum()}")
        
        # decay_ratio
        print(f"\ndecay_ratio:")
        print(f"  非空值: {df2['decay_ratio'].notna().sum()}/{len(df2)}")
        print(f"  范围: {df2['decay_ratio'].min():.3f} - {df2['decay_ratio'].max():.3f}")
        print(f"  ≤{cfg['decay_ratio_max']}: {(df2['decay_ratio'] <= cfg['decay_ratio_max']).sum()}")
        
        # down_days_ratio
        print(f"\ndown_days_ratio:")
        print(f"  非空值: {df2['down_days_ratio'].notna().sum()}/{len(df2)}")
        print(f"  范围: {df2['down_days_ratio'].min():.3f} - {df2['down_days_ratio'].max():.3f}")
        print(f"  ≤{cfg['down_days_ratio_max']}: {(df2['down_days_ratio'] <= cfg['down_days_ratio_max']).sum()}")
        
        # 检查强势事件
        print(f"\n强势事件统计:")
        print(f"is_strong_day: {df2['is_strong_day'].sum()}/{len(df2)}")
        print(f"strength_type 非空: {df2['strength_type'].notna().sum()}/{len(df2)}")
        print(f"strength_event_date 非空: {df2['strength_event_date'].notna().sum()}/{len(df2)}")
        
        # 显示强势事件类型分布
        if df2['strength_type'].notna().sum() > 0:
            print(f"\n强势事件类型分布:")
            print(df2['strength_type'].value_counts().head(10))
        
        # 显示一些示例数据
        print(f"\n强势股票示例:")
        strong_stocks = df2[df2['is_strong_day'] == 1]
        if len(strong_stocks) > 0:
            print(strong_stocks[['ts_code', 'name', 'close', 'pct_chg', 'strength_type', 'days_since_last_strength', 'drawdown']].head(10))
        
        # 检查回调过滤
        print(f"\n应用回调过滤...")
        df3 = strategy.apply_pullback_filter(df2)
        print(f"回调过滤后: {len(df3)}")
        
        if len(df3) == 0:
            print("\n回调过滤条件太严格，检查具体原因:")
            
            # 检查每个条件
            cond1 = df2['days_since_last_strength'].notna()
            cond2 = df2['drawdown'].notna()
            cond3 = df2['decay_ratio'].notna()
            cond4 = df2['down_days_ratio'].notna()
            cond5 = df2['days_since_last_strength'].between(cfg['days_range'][0], cfg['days_range'][1])
            cond6 = df2['drawdown'].between(cfg['drawdown_range'][0], cfg['drawdown_range'][1])
            cond7 = df2['decay_ratio'] <= cfg['decay_ratio_max']
            cond8 = df2['down_days_ratio'] <= cfg['down_days_ratio_max']
            
            print(f"条件1 (days_since_last_strength非空): {cond1.sum()}/{len(df2)}")
            print(f"条件2 (drawdown非空): {cond2.sum()}/{len(df2)}")
            print(f"条件3 (decay_ratio非空): {cond3.sum()}/{len(df2)}")
            print(f"条件4 (down_days_ratio非空): {cond4.sum()}/{len(df2)}")
            print(f"条件5 (回调天数在范围内): {cond5.sum()}/{len(df2)}")
            print(f"条件6 (回撤幅度在范围内): {cond6.sum()}/{len(df2)}")
            print(f"条件7 (回调速度≤{cfg['decay_ratio_max']}): {cond7.sum()}/{len(df2)}")
            print(f"条件8 (下跌天数比例≤{cfg['down_days_ratio_max']}): {cond8.sum()}/{len(df2)}")
            
            # 检查组合条件
            all_cond = cond1 & cond2 & cond3 & cond4 & cond5 & cond6 & cond7 & cond8
            print(f"所有条件都满足: {all_cond.sum()}/{len(df2)}")
            
            # 显示不满足条件的股票
            for i in range(len(df2)):
                row = df2.iloc[i]
                if not cond1.iloc[i]:
                    print(f"\n股票 {row['ts_code']} - {row['name']}: days_since_last_strength 为空")
                    break
                elif not cond2.iloc[i]:
                    print(f"\n股票 {row['ts_code']} - {row['name']}: drawdown 为空")
                    break
                elif not cond3.iloc[i]:
                    print(f"\n股票 {row['ts_code']} - {row['name']}: decay_ratio 为空")
                    break
                elif not cond4.iloc[i]:
                    print(f"\n股票 {row['ts_code']} - {row['name']}: down_days_ratio 为空")
                    break
                elif not cond5.iloc[i]:
                    print(f"\n股票 {row['ts_code']} - {row['name']}: days_since_last_strength={row['days_since_last_strength']} 不在范围内")
                    break
                elif not cond6.iloc[i]:
                    print(f"\n股票 {row['ts_code']} - {row['name']}: drawdown={row['drawdown']:.3f} 不在范围内")
                    break
                elif not cond7.iloc[i]:
                    print(f"\n股票 {row['ts_code']} - {row['name']}: decay_ratio={row['decay_ratio']:.3f} > {cfg['decay_ratio_max']}")
                    break
                elif not cond8.iloc[i]:
                    print(f"\n股票 {row['ts_code']} - {row['name']}: down_days_ratio={row['down_days_ratio']:.3f} > {cfg['down_days_ratio_max']}")
                    break
        
        # 显示回调过滤后的股票
        if len(df3) > 0:
            print(f"\n回调过滤后的股票:")
            print(df3[['ts_code', 'name', 'close', 'days_since_last_strength', 'drawdown', 'decay_ratio', 'down_days_ratio']].head(10))
        
    finally:
        conn.close()


if __name__ == "__main__":
    debug_pullback_filter()