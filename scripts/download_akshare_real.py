# -*- coding: utf-8 -*-
"""
使用AKShare下载真实分时数据
"""

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from src.modules.backtest.history_recommendation_db import HistoryRecommendationDB
from src.core.logger import get_logger
import time

logger = get_logger("download_akshare_real")


def download_real_intraday_data():
    """使用AKShare下载真实分时数据"""
    print("\n" + "="*70)
    print("使用AKShare下载真实分时数据")
    print("="*70)
    
    # 检查AKShare
    try:
        import akshare as ak
        print("\n[OK] AKShare已安装")
    except ImportError:
        print("\n[ERROR] AKShare未安装")
        print("正在安装AKShare...")
        os.system("pip install akshare -q")
        import akshare as ak
        print("[OK] AKShare安装完成")
    
    # 创建数据库
    db = HistoryRecommendationDB()
    
    # 清空旧数据
    print("\n清空旧数据...")
    import sqlite3
    if os.path.exists(db.db_path):
        conn = sqlite3.connect(db.db_path)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM recommendations")
        cursor.execute("DELETE FROM intraday_data")
        conn.commit()
        conn.close()
        print("[OK] 旧数据已清空")
    
    # 推荐股票列表
    recommendations = [
        {'symbol': '000001', 'name': '平安银行', 'date': '2026-02-03', 'reason': '回踩均线', 'score': 85, 'strategy': 'Pullback'},
        {'symbol': '000002', 'name': '万科A', 'date': '2026-02-10', 'reason': '突破买入', 'score': 78, 'strategy': 'Momentum'},
        {'symbol': '600000', 'name': '浦发银行', 'date': '2026-02-17', 'reason': '量价齐升', 'score': 72, 'strategy': 'Momentum'},
        {'symbol': '600036', 'name': '招商银行', 'date': '2026-02-20', 'reason': '趋势向上', 'score': 80, 'strategy': 'Momentum'},
    ]
    
    print(f"\n准备下载 {len(recommendations)} 只股票的分时数据")
    print("\n注意：AKShare获取的是最近的分时数据，不是历史数据")
    print("如果需要历史数据，建议使用Tushare日线数据或模拟数据")
    
    # 下载分时数据
    success_count = 0
    for i, rec in enumerate(recommendations, 1):
        symbol = rec['symbol']
        name = rec['name']
        rec_date = rec['date']
        
        print(f"\n[{i}/{len(recommendations)}] {symbol} - {name}")
        print(f"  推荐日期: {rec_date}")
        
        try:
            # 转换股票代码格式
            if symbol.startswith('6'):
                ak_symbol = f"sh{symbol}"
            else:
                ak_symbol = f"sz{symbol}"
            
            print(f"  正在下载 {ak_symbol} 分时数据...")
            
            # 使用AKShare获取分时数据
            df = ak.stock_zh_a_minute(symbol=ak_symbol, period='1')
            
            if df.empty:
                print(f"  [WARN] 未获取到数据")
                continue
            
            # 处理数据
            print(f"  原始数据: {len(df)}条")
            print(f"  数据列: {list(df.columns)}")
            
            # 重命名列
            column_mapping = {}
            for col in df.columns:
                if 'day' in col.lower() or 'time' in col.lower():
                    column_mapping[col] = 'trade_time'
                elif col.lower() == 'open':
                    column_mapping[col] = 'open'
                elif col.lower() == 'high':
                    column_mapping[col] = 'high'
                elif col.lower() == 'low':
                    column_mapping[col] = 'low'
                elif col.lower() == 'close':
                    column_mapping[col] = 'close'
                elif 'volume' in col.lower() or 'vol' in col.lower():
                    column_mapping[col] = 'volume'
            
            df = df.rename(columns=column_mapping)
            
            # 确保必要的列存在
            if 'trade_time' not in df.columns:
                print(f"  [ERROR] 缺少时间列")
                continue
            
            df['trade_time'] = pd.to_datetime(df['trade_time'])
            df['trade_date'] = df['trade_time'].dt.date
            df['symbol'] = symbol
            
            # 如果缺少某些列，用默认值填充
            if 'open' not in df.columns:
                df['open'] = df.get('close', 10.0)
            if 'high' not in df.columns:
                df['high'] = df.get('close', 10.0) * 1.01
            if 'low' not in df.columns:
                df['low'] = df.get('close', 10.0) * 0.99
            if 'volume' not in df.columns:
                df['volume'] = 100000
            if 'amount' not in df.columns:
                df['amount'] = df.get('close', 10.0) * 100000
            
            df = df.sort_values('trade_time').reset_index(drop=True)
            
            print(f"  [OK] 处理后数据: {len(df)}条")
            print(f"  时间范围: {df['trade_time'].min()} ~ {df['trade_time'].max()}")
            
            # 保存到数据库
            db.add_intraday_data(symbol, df)
            print(f"  [OK] 数据已保存到数据库")
            
            # 保存推荐记录
            recommendation = {
                'symbol': symbol,
                'name': name,
                'recommendation_date': rec_date,
                'recommendation_reason': rec['reason'],
                'recommendation_score': rec['score'],
                'strategy_type': rec['strategy'],
                'status': 'active',
            }
            db.add_recommendation(recommendation)
            
            success_count += 1
            
            # 添加延迟避免请求过快
            time.sleep(2)
            
        except Exception as e:
            print(f"  [ERROR] 下载失败: {e}")
            import traceback
            traceback.print_exc()
    
    # 打印统计
    print("\n" + "="*70)
    print("下载完成统计")
    print("="*70)
    print(f"成功下载: {success_count}/{len(recommendations)}只股票")
    
    db.print_statistics()
    
    print("\n" + "="*70)
    print("[OK] 完成")
    print("="*70)


if __name__ == "__main__":
    download_real_intraday_data()
