"""
调试基础过滤条件
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


def debug_base_filter():
    """调试基础过滤条件"""
    print("调试基础过滤条件")
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
        
        if len(latest_data) == 0:
            print("没有最新日期数据")
            return
        
        # 检查基础过滤条件
        cfg = strategy.config['base_filter']
        print(f"\n基础过滤条件:")
        print(f"1. 主板股票: {cfg['sh_prefixes']} + {cfg['sz_prefixes']}")
        print(f"2. 非ST股: is_st == 0")
        print(f"3. 非停牌: is_suspended == 0")
        print(f"4. 上市天数 >= {cfg['min_listing_days']}")
        print(f"5. 价格 >= {cfg['min_price']}")
        print(f"6. 20日均成交额: {cfg['min_avg_amount_20']:,} ~ {cfg['max_avg_amount_20']:,}")
        print(f"7. 20日内跌停次数 <= {cfg['max_limit_down_20']}")
        
        # 逐个检查条件
        print(f"\n条件检查:")
        
        # 1. 主板股票
        is_main_board = latest_data['is_main_board']
        print(f"主板股票: {is_main_board.sum()}/{len(latest_data)}")
        
        # 2. 非ST股
        is_st = latest_data['is_st'] == 0
        print(f"非ST股: {is_st.sum()}/{len(latest_data)}")
        
        # 3. 非停牌
        is_suspended = latest_data['is_suspended'] == 0
        print(f"非停牌: {is_suspended.sum()}/{len(latest_data)}")
        
        # 4. 上市天数
        listed_days_ok = latest_data['listed_days'] >= cfg['min_listing_days']
        print(f"上市天数≥{cfg['min_listing_days']}: {listed_days_ok.sum()}/{len(latest_data)}")
        
        # 5. 价格
        price_ok = latest_data['close'] >= cfg['min_price']
        print(f"价格≥{cfg['min_price']}: {price_ok.sum()}/{len(latest_data)}")
        
        # 6. 20日均成交额
        amount_ok = latest_data['ma_amount_20'].between(
            cfg['min_avg_amount_20'], cfg['max_avg_amount_20']
        )
        print(f"20日均成交额在范围内: {amount_ok.sum()}/{len(latest_data)}")
        
        # 7. 20日内跌停次数
        limit_down_ok = latest_data['count_limit_down_20'] <= cfg['max_limit_down_20']
        print(f"20日内跌停≤{cfg['max_limit_down_20']}: {limit_down_ok.sum()}/{len(latest_data)}")
        
        # 显示不满足条件的股票
        print(f"\n不满足条件的股票统计:")
        
        # 主板股票
        non_main_board = latest_data[~is_main_board]
        if len(non_main_board) > 0:
            print(f"非主板股票: {len(non_main_board)}只")
            print(non_main_board[['ts_code', 'name']].head())
        
        # ST股
        st_stocks = latest_data[latest_data['is_st'] == 1]
        if len(st_stocks) > 0:
            print(f"\nST股票: {len(st_stocks)}只")
            print(st_stocks[['ts_code', 'name']].head())
        
        # 停牌
        suspended = latest_data[latest_data['is_suspended'] == 1]
        if len(suspended) > 0:
            print(f"\n停牌股票: {len(suspended)}只")
            print(suspended[['ts_code', 'name', 'vol']].head())
        
        # 上市天数不足
        new_stocks = latest_data[latest_data['listed_days'] < cfg['min_listing_days']]
        if len(new_stocks) > 0:
            print(f"\n上市天数<{cfg['min_listing_days']}: {len(new_stocks)}只")
            print(new_stocks[['ts_code', 'name', 'listed_days']].head())
        
        # 价格过低
        low_price = latest_data[latest_data['close'] < cfg['min_price']]
        if len(low_price) > 0:
            print(f"\n价格<{cfg['min_price']}: {len(low_price)}只")
            print(low_price[['ts_code', 'name', 'close']].head())
        
        # 成交额不足
        low_amount = latest_data[latest_data['ma_amount_20'] < cfg['min_avg_amount_20']]
        if len(low_amount) > 0:
            print(f"\n20日均成交额<{cfg['min_avg_amount_20']:,}: {len(low_amount)}只")
            print(low_amount[['ts_code', 'name', 'ma_amount_20']].head())
        
        # 跌停次数过多
        high_limit_down = latest_data[latest_data['count_limit_down_20'] > cfg['max_limit_down_20']]
        if len(high_limit_down) > 0:
            print(f"\n20日内跌停>{cfg['max_limit_down_20']}: {len(high_limit_down)}只")
            print(high_limit_down[['ts_code', 'name', 'count_limit_down_20']].head())
        
        # 检查特征值
        print(f"\n特征值统计:")
        print(f"is_main_board: {latest_data['is_main_board'].value_counts()}")
        print(f"is_st: {latest_data['is_st'].value_counts()}")
        print(f"is_suspended: {latest_data['is_suspended'].value_counts()}")
        print(f"listed_days min: {latest_data['listed_days'].min()}, max: {latest_data['listed_days'].max()}")
        print(f"close min: {latest_data['close'].min():.2f}, max: {latest_data['close'].max():.2f}")
        print(f"ma_amount_20 min: {latest_data['ma_amount_20'].min():,.0f}, max: {latest_data['ma_amount_20'].max():,.0f}")
        print(f"count_limit_down_20 min: {latest_data['count_limit_down_20'].min()}, max: {latest_data['count_limit_down_20'].max()}")
        
        # 检查是否有NaN值
        print(f"\nNaN值检查:")
        for col in ['is_main_board', 'is_st', 'is_suspended', 'listed_days', 'close', 'ma_amount_20', 'count_limit_down_20']:
            nan_count = latest_data[col].isna().sum()
            print(f"{col}: {nan_count}个NaN")
        
        # 检查基础过滤函数
        print(f"\n应用基础过滤...")
        df_filtered = strategy.apply_base_filter(latest_data)
        print(f"过滤后: {len(df_filtered)}/{len(latest_data)}")
        
        if len(df_filtered) == 0:
            print("\n所有股票都被过滤掉了，检查具体原因:")
            
            # 逐个条件检查
            conditions = [
                ('主板股票', is_main_board),
                ('非ST股', is_st),
                ('非停牌', is_suspended),
                ('上市天数', listed_days_ok),
                ('价格', price_ok),
                ('成交额', amount_ok),
                ('跌停次数', limit_down_ok)
            ]
            
            for name, cond in conditions:
                count = cond.sum()
                print(f"{name}: {count}/{len(latest_data)} ({count/len(latest_data)*100:.1f}%)")
            
            # 检查组合条件
            print(f"\n组合条件检查:")
            all_cond = is_main_board & is_st & is_suspended & listed_days_ok & price_ok & amount_ok & limit_down_ok
            print(f"所有条件都满足: {all_cond.sum()}/{len(latest_data)}")
            
            # 检查哪个条件最严格
            for i in range(len(conditions)):
                temp_cond = conditions[0][1]
                for j in range(1, len(conditions)):
                    if j != i:
                        temp_cond = temp_cond & conditions[j][1]
                print(f"排除{conditions[i][0]}: {temp_cond.sum()}/{len(latest_data)}")
        
    finally:
        conn.close()


if __name__ == "__main__":
    debug_base_filter()