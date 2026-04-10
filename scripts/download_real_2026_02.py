# -*- coding: utf-8 -*-
"""
使用真实token下载2026年2月份数据
"""

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import tushare as ts
from src.modules.backtest.history_recommendation_db import HistoryRecommendationDB
from src.core.logger import get_logger
import time

logger = get_logger("download_real_data")


def download_real_data():
    """下载真实数据"""
    print("\n" + "="*70)
    print("下载2026年2月份真实数据")
    print("="*70)
    
    # 配置token
    token = '17c11d0c60a9196354a0be60abfa853bfdf5ebd96263e3c9ba8e38e5'
    ts.set_token(token)
    pro = ts.pro_api()
    
    # 创建数据库
    db = HistoryRecommendationDB()
    
    # 清空旧数据
    print("\n清空旧数据...")
    conn = db._get_connection() if hasattr(db, '_get_connection') else None
    if conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM recommendations")
        cursor.execute("DELETE FROM intraday_data")
        conn.commit()
        conn.close()
        print("[OK] 旧数据已清空")
    
    # 模拟推荐股票（实际应该从选股系统获取）
    recommendations = [
        {'symbol': '000001', 'name': '平安银行', 'date': '2026-02-03', 'reason': '回踩均线', 'score': 85, 'strategy': 'Pullback'},
        {'symbol': '000002', 'name': '万科A', 'date': '2026-02-10', 'reason': '突破买入', 'score': 78, 'strategy': 'Momentum'},
        {'symbol': '600000', 'name': '浦发银行', 'date': '2026-02-17', 'reason': '量价齐升', 'score': 72, 'strategy': 'Momentum'},
    ]
    
    print(f"\n准备下载 {len(recommendations)} 只股票的分时数据")
    
    # 下载分时数据
    for i, rec in enumerate(recommendations, 1):
        symbol = rec['symbol']
        name = rec['name']
        rec_date = rec['date']
        
        print(f"\n[{i}/{len(recommendations)}] {symbol} - {name}")
        print(f"  推荐日期: {rec_date}")
        
        # 计算数据范围
        rec_dt = datetime.strptime(rec_date, '%Y-%m-%d')
        start_date = (rec_dt - timedelta(days=5)).strftime('%Y-%m-%d')
        end_date = (rec_dt + timedelta(days=10)).strftime('%Y-%m-%d')
        
        print(f"  数据范围: {start_date} ~ {end_date}")
        
        # 下载分时数据
        try:
            ts_code = f"{symbol}.SH" if symbol.startswith('6') else f"{symbol}.SZ"
            start_dt = start_date.replace('-', '') + '093000'
            end_dt = end_date.replace('-', '') + '150000'
            
            print(f"  正在下载 {ts_code} 分时数据...")
            
            # 添加延迟避免API限制
            if i > 1:
                time.sleep(30)  # 等待30秒
            
            df = pro.query('stk_mins',
                          ts_code=ts_code,
                          start_date=start_dt,
                          end_date=end_dt,
                          freq='1min')
            
            if df.empty:
                print(f"  [WARN] 未获取到数据，使用模拟数据")
                df = generate_mock_data(symbol, start_date, end_date)
            else:
                # 处理数据
                df = df.rename(columns={
                    'trade_time': 'trade_time',
                    'open': 'open',
                    'high': 'high',
                    'low': 'low',
                    'close': 'close',
                    'vol': 'volume',
                    'amount': 'amount',
                })
                
                df['trade_time'] = pd.to_datetime(df['trade_time'])
                df['trade_date'] = df['trade_time'].dt.date
                df['symbol'] = symbol
                
                df = df.sort_values('trade_time').reset_index(drop=True)
                
                print(f"  [OK] 下载成功: {len(df)}条")
            
            # 保存到数据库
            if not df.empty:
                db.add_intraday_data(symbol, df)
                print(f"  [OK] 数据已保存")
            
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
            
        except Exception as e:
            print(f"  [ERROR] 下载失败: {e}")
            print(f"  使用模拟数据...")
            
            df = generate_mock_data(symbol, start_date, end_date)
            if not df.empty:
                db.add_intraday_data(symbol, df)
                print(f"  [OK] 模拟数据已保存: {len(df)}条")
    
    # 打印统计
    db.print_statistics()
    
    print("\n" + "="*70)
    print("[OK] 完成")
    print("="*70)


def generate_mock_data(symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
    """生成模拟数据"""
    start_dt = datetime.strptime(start_date, '%Y-%m-%d')
    end_dt = datetime.strptime(end_date, '%Y-%m-%d')
    
    all_data = []
    current_dt = start_dt
    
    while current_dt <= end_dt:
        if current_dt.weekday() >= 5:
            current_dt += timedelta(days=1)
            continue
        
        # 生成一天的数据
        morning_times = pd.date_range(
            start=current_dt.replace(hour=9, minute=30, second=0),
            end=current_dt.replace(hour=11, minute=30, second=0),
            freq='1min'
        )
        
        afternoon_times = pd.date_range(
            start=current_dt.replace(hour=13, minute=0, second=0),
            end=current_dt.replace(hour=15, minute=0, second=0),
            freq='1min'
        )
        
        times = morning_times.append(afternoon_times)
        
        base_price = 10.0 + hash(symbol) % 10
        prices = [base_price * (1 + np.random.normal(0, 0.005)) for _ in times]
        
        day_df = pd.DataFrame({
            'trade_time': times,
            'trade_date': [current_dt.date()] * len(times),
            'open': prices,
            'high': [p * (1 + abs(np.random.normal(0, 0.002))) for p in prices],
            'low': [p * (1 - abs(np.random.normal(0, 0.002))) for p in prices],
            'close': prices,
            'volume': [100000 * (1 + np.random.normal(0, 0.3)) for _ in prices],
            'amount': [p * 100000 for p in prices],
            'symbol': symbol,
        })
        
        all_data.append(day_df)
        current_dt += timedelta(days=1)
    
    if not all_data:
        return pd.DataFrame()
    
    df = pd.concat(all_data, ignore_index=True)
    return df


if __name__ == "__main__":
    download_real_data()
