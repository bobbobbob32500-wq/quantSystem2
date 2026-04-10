"""
调试特征计算问题
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

from src.modules.final_strategy import FinalStrategy

# 设置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)


def debug_feature_calculation():
    """调试特征计算"""
    print("=" * 80)
    print("调试特征计算")
    print("=" * 80)
    
    # 连接数据库
    db_path = 'data/database/quant_system.db'
    conn = sqlite3.connect(db_path)
    
    try:
        # 加载一只股票的历史数据
        query = """
        SELECT 
            ts_code,
            trade_date,
            open,
            high,
            low,
            close,
            vol,
            amount,
            pct_chg
        FROM stock_daily
        WHERE ts_code = '000001.SZ'
        AND trade_date >= '20250301'
        AND trade_date <= '20260327'
        ORDER BY trade_date
        """
        
        df = pd.read_sql_query(query, conn)
        print(f"加载数据: {df.shape}")
        print(f"日期范围: {df['trade_date'].min()} 到 {df['trade_date'].max()}")
        
        if len(df) == 0:
            print("没有数据")
            return
        
        # 显示数据
        print("\n前5行数据:")
        print(df.head())
        
        print("\n后5行数据:")
        print(df.tail())
        
        # 检查数据质量
        print("\n数据质量检查:")
        print(f"总行数: {len(df)}")
        print(f"空值统计:")
        print(df.isnull().sum())
        
        # 检查价格数据
        print("\n价格数据统计:")
        print(df[['open', 'high', 'low', 'close']].describe())
        
        # 检查成交量数据
        print("\n成交量数据统计:")
        print(df[['vol', 'amount']].describe())
        
        # 检查涨跌幅
        print("\n涨跌幅统计:")
        print(df['pct_chg'].describe())
        
        # 手动计算特征
        print("\n" + "=" * 80)
        print("手动计算特征")
        print("=" * 80)
        
        # 计算移动平均
        df['ma5'] = df['close'].rolling(window=5, min_periods=1).mean()
        df['ma10'] = df['close'].rolling(window=10, min_periods=1).mean()
        df['ma20'] = df['close'].rolling(window=20, min_periods=1).mean()
        
        # 计算涨跌幅
        df['return_5'] = df['close'].pct_change(5)
        df['return_10'] = df['close'].pct_change(10)
        
        # 计算成交额移动平均
        df['ma_amount_20'] = df['amount'].rolling(window=20, min_periods=1).mean()
        
        # 计算量比
        df['volume_ratio'] = df['vol'] / df['vol'].rolling(window=5, min_periods=1).mean()
        
        # 计算最高价
        df['high_20'] = df['high'].rolling(window=20, min_periods=1).max()
        
        # 检查最新数据
        latest = df.iloc[-1]
        print(f"\n最新数据(2026-03-27):")
        print(f"股票代码: {latest['ts_code']}")
        print(f"收盘价: {latest['close']:.2f}")
        print(f"MA5: {latest['ma5']:.2f}")
        print(f"MA10: {latest['ma10']:.2f}")
        print(f"MA20: {latest['ma20']:.2f}")
        print(f"5日涨幅: {latest['return_5']:.2%}")
        print(f"10日涨幅: {latest['return_10']:.2%}")
        print(f"20日均额: {latest['ma_amount_20']/1e8:.2f}亿")
        print(f"量比: {latest['volume_ratio']:.2f}")
        print(f"20日最高: {latest['high_20']:.2f}")
        
        # 检查涨停
        print("\n涨停检测:")
        # 涨停条件: 最高价=收盘价且涨幅≥9.5%
        is_limit_up = (latest['high'] == latest['close']) and (latest['pct_chg'] >= 9.5)
        print(f"是否涨停: {is_limit_up}")
        print(f"最高价: {latest['high']:.2f}")
        print(f"收盘价: {latest['close']:.2f}")
        print(f"涨幅: {latest['pct_chg']:.2f}%")
        
        # 检查跌停
        print("\n跌停检测:")
        # 跌停条件: 最低价=收盘价且涨幅≤-9.5%
        is_limit_down = (latest['low'] == latest['close']) and (latest['pct_chg'] <= -9.5)
        print(f"是否跌停: {is_limit_down}")
        print(f"最低价: {latest['low']:.2f}")
        print(f"收盘价: {latest['close']:.2f}")
        print(f"涨幅: {latest['pct_chg']:.2f}%")
        
        # 检查接近前高
        print("\n接近前高检测:")
        near_high_ratio = latest['close'] / latest['high_20']
        print(f"当前价/20日最高: {near_high_ratio:.2%}")
        print(f"是否接近前高(≥98%): {near_high_ratio >= 0.98}")
        
    finally:
        conn.close()


def debug_multiple_stocks():
    """调试多只股票"""
    print("\n" + "=" * 80)
    print("调试多只股票")
    print("=" * 80)
    
    # 连接数据库
    db_path = 'data/database/quant_system.db'
    conn = sqlite3.connect(db_path)
    
    try:
        # 加载多只股票的最新数据
        query = """
        SELECT 
            ts_code,
            trade_date,
            open,
            high,
            low,
            close,
            vol,
            amount,
            pct_chg
        FROM stock_daily
        WHERE trade_date = '20260327'
        AND ts_code IN ('000001.SZ', '000002.SZ', '000004.SZ', '000005.SZ', '000006.SZ')
        ORDER BY ts_code
        """
        
        df = pd.read_sql_query(query, conn)
        print(f"加载数据: {df.shape}")
        
        if len(df) == 0:
            print("没有数据")
            return
        
        print("\n股票数据:")
        for _, row in df.iterrows():
            print(f"\n{row['ts_code']}:")
            print(f"  日期: {row['trade_date']}")
            print(f"  收盘价: {row['close']:.2f}")
            print(f"  涨幅: {row['pct_chg']:.2f}%")
            print(f"  成交额: {row['amount']/1e8:.2f}亿")
            
            # 检查涨停
            is_limit_up = (row['high'] == row['close']) and (row['pct_chg'] >= 9.5)
            print(f"  是否涨停: {is_limit_up}")
            
            # 检查跌停
            is_limit_down = (row['low'] == row['close']) and (row['pct_chg'] <= -9.5)
            print(f"  是否跌停: {is_limit_down}")
        
        # 检查数据完整性
        print("\n数据完整性检查:")
        print(f"空值数量:")
        print(df.isnull().sum())
        
        # 检查价格合理性
        print("\n价格合理性检查:")
        for col in ['open', 'high', 'low', 'close']:
            invalid = df[df[col] <= 0]
            print(f"{col} ≤ 0: {len(invalid)}行")
        
        # 检查涨跌幅范围
        print("\n涨跌幅范围检查:")
        print(f"最小涨幅: {df['pct_chg'].min():.2f}%")
        print(f"最大涨幅: {df['pct_chg'].max():.2f}%")
        
        # 检查成交额
        print("\n成交额检查:")
        print(f"最小成交额: {df['amount'].min()/1e4:.0f}万")
        print(f"最大成交额: {df['amount'].max()/1e8:.2f}亿")
        
    finally:
        conn.close()


def main():
    """主函数"""
    print("特征计算调试")
    print("=" * 80)
    
    # 调试单只股票特征计算
    debug_feature_calculation()
    
    # 调试多只股票
    debug_multiple_stocks()
    
    print("\n" + "=" * 80)
    print("问题分析:")
    print("=" * 80)
    
    print("\n可能的问题:")
    print("1. 数据质量问题: 某些字段可能为空或异常")
    print("2. 特征计算错误: 移动平均计算可能有问题")
    print("3. 数据范围问题: 只加载了单日数据,无法计算历史特征")
    print("4. 涨停检测逻辑: 可能条件过于严格")
    
    print("\n建议解决方案:")
    print("1. 检查数据完整性,确保所有必要字段都有值")
    print("2. 验证特征计算逻辑,特别是移动平均和涨跌幅")
    print("3. 确保加载足够的历史数据用于特征计算")
    print("4. 调整涨停检测条件,考虑使用涨幅≥9.5%作为条件")
    print("5. 添加数据清洗步骤,处理异常值和空值")


if __name__ == "__main__":
    main()
