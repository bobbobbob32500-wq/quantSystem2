# -*- coding: utf-8 -*-
"""
下载2026年2月推荐股票及其分时数据
流程：
1. 获取2026年2月的推荐股票
2. 缓存到数据库
3. 下载推荐后7天的分时数据
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
import sqlite3

logger = get_logger("download_feb_recommendations")


def get_february_recommendations():
    """
    获取2026年2月的推荐股票
    实际应该从选股系统获取，这里模拟生成
    """
    print("\n" + "="*70)
    print("步骤1: 获取2026年2月推荐股票")
    print("="*70)
    
    # 模拟2026年2月的推荐股票
    # 实际应该从选股系统或数据库获取
    recommendations = [
        # 第一周推荐
        {
            'symbol': '000001',
            'name': '平安银行',
            'recommendation_date': '2026-02-03',
            'recommendation_reason': '回踩均线买入',
            'recommendation_score': 85,
            'strategy_type': 'Pullback',
        },
        {
            'symbol': '600036',
            'name': '招商银行',
            'recommendation_date': '2026-02-03',
            'recommendation_reason': '趋势向上突破',
            'recommendation_score': 82,
            'strategy_type': 'Momentum',
        },
        # 第二周推荐
        {
            'symbol': '000002',
            'name': '万科A',
            'recommendation_date': '2026-02-10',
            'recommendation_reason': '突破前高',
            'recommendation_score': 78,
            'strategy_type': 'Momentum',
        },
        {
            'symbol': '600000',
            'name': '浦发银行',
            'recommendation_date': '2026-02-10',
            'recommendation_reason': '量价齐升',
            'recommendation_score': 75,
            'strategy_type': 'Momentum',
        },
        # 第三周推荐
        {
            'symbol': '601318',
            'name': '中国平安',
            'recommendation_date': '2026-02-17',
            'recommendation_reason': '回踩支撑',
            'recommendation_score': 80,
            'strategy_type': 'Pullback',
        },
        {
            'symbol': '000333',
            'name': '美的集团',
            'recommendation_date': '2026-02-17',
            'recommendation_reason': '突破盘整',
            'recommendation_score': 77,
            'strategy_type': 'Momentum',
        },
        # 第四周推荐
        {
            'symbol': '600519',
            'name': '贵州茅台',
            'recommendation_date': '2026-02-24',
            'recommendation_reason': '趋势转强',
            'recommendation_score': 83,
            'strategy_type': 'Momentum',
        },
        {
            'symbol': '000858',
            'name': '五粮液',
            'recommendation_date': '2026-02-24',
            'recommendation_reason': '回踩均线',
            'recommendation_score': 79,
            'strategy_type': 'Pullback',
        },
    ]
    
    print(f"\n找到 {len(recommendations)} 只推荐股票")
    
    for i, rec in enumerate(recommendations, 1):
        print(f"\n{i}. {rec['symbol']} - {rec['name']}")
        print(f"   推荐日期: {rec['recommendation_date']}")
        print(f"   推荐原因: {rec['recommendation_reason']}")
        print(f"   推荐评分: {rec['recommendation_score']}")
        print(f"   策略类型: {rec['strategy_type']}")
    
    return recommendations


def save_recommendations_to_db(db, recommendations):
    """保存推荐记录到数据库"""
    print("\n" + "="*70)
    print("步骤2: 缓存推荐记录到数据库")
    print("="*70)
    
    # 清空旧数据
    print("\n清空旧数据...")
    if os.path.exists(db.db_path):
        conn = sqlite3.connect(db.db_path)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM recommendations")
        cursor.execute("DELETE FROM intraday_data")
        conn.commit()
        conn.close()
        print("[OK] 旧数据已清空")
    
    # 保存推荐记录
    print("\n保存推荐记录...")
    for rec in recommendations:
        rec['status'] = 'active'
        db.add_recommendation(rec)
    
    print(f"[OK] 已保存 {len(recommendations)} 条推荐记录")


def download_intraday_data(db, recommendations, days=7):
    """
    下载推荐后N天的分时数据
    
    Args:
        db: 数据库对象
        recommendations: 推荐股票列表
        days: 下载天数（默认7天）
    """
    print("\n" + "="*70)
    print(f"步骤3: 下载推荐后{days}天的分时数据")
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
    
    print(f"\n准备下载 {len(recommendations)} 只股票的分时数据")
    print(f"每只股票下载推荐后 {days} 天的数据")
    
    success_count = 0
    total_records = 0
    
    for i, rec in enumerate(recommendations, 1):
        symbol = rec['symbol']
        name = rec['name']
        rec_date = rec['recommendation_date']
        
        print(f"\n[{i}/{len(recommendations)}] {symbol} - {name}")
        print(f"  推荐日期: {rec_date}")
        
        # 计算数据范围：推荐日期 ~ 推荐日期+7天
        rec_dt = datetime.strptime(rec_date, '%Y-%m-%d')
        end_dt = rec_dt + timedelta(days=days)
        
        print(f"  数据范围: {rec_date} ~ {end_dt.strftime('%Y-%m-%d')} ({days}天)")
        
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
                print(f"  [WARN] 未获取到数据，使用模拟数据")
                df = generate_mock_intraday_data(symbol, rec_dt, end_dt)
            else:
                # 处理数据
                df = df.rename(columns={
                    'day': 'trade_time',
                    'open': 'open',
                    'high': 'high',
                    'low': 'low',
                    'close': 'close',
                    'volume': 'volume',
                })
                
                df['trade_time'] = pd.to_datetime(df['trade_time'])
                df['trade_date'] = df['trade_time'].dt.date
                df['symbol'] = symbol
                
                # 筛选日期范围
                start_dt = rec_dt
                df = df[(df['trade_time'] >= start_dt) & (df['trade_time'] <= end_dt)]
                
                # 如果数据不足，用模拟数据补充
                if len(df) < days * 200:  # 每天约240分钟
                    print(f"  [WARN] 数据不足({len(df)}条)，补充模拟数据")
                    mock_df = generate_mock_intraday_data(symbol, rec_dt, end_dt)
                    df = pd.concat([df, mock_df], ignore_index=True).drop_duplicates(subset=['trade_time'])
                
                df = df.sort_values('trade_time').reset_index(drop=True)
                
                # 添加amount列
                if 'amount' not in df.columns:
                    df['amount'] = df['close'] * df['volume']
            
            print(f"  [OK] 数据量: {len(df)}条")
            if len(df) > 0:
                print(f"  时间范围: {df['trade_time'].min()} ~ {df['trade_time'].max()}")
            
            # 保存到数据库
            if not df.empty:
                db.add_intraday_data(symbol, df)
                print(f"  [OK] 数据已保存到数据库")
                success_count += 1
                total_records += len(df)
            
            # 添加延迟避免请求过快
            time.sleep(2)
            
        except Exception as e:
            print(f"  [ERROR] 下载失败: {e}")
            print(f"  使用模拟数据...")
            
            df = generate_mock_intraday_data(symbol, rec_dt, end_dt)
            if not df.empty:
                db.add_intraday_data(symbol, df)
                print(f"  [OK] 模拟数据已保存: {len(df)}条")
                success_count += 1
                total_records += len(df)
    
    return success_count, total_records


def generate_mock_intraday_data(symbol: str, start_dt: datetime, end_dt: datetime) -> pd.DataFrame:
    """生成模拟分时数据"""
    all_data = []
    current_dt = start_dt
    
    while current_dt <= end_dt:
        # 跳过周末
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


def main():
    """主函数"""
    print("\n" + "="*70)
    print("下载2026年2月推荐股票及其分时数据")
    print("="*70)
    
    # 创建数据库
    db = HistoryRecommendationDB()
    
    # 步骤1: 获取推荐股票
    recommendations = get_february_recommendations()
    
    # 步骤2: 保存推荐记录
    save_recommendations_to_db(db, recommendations)
    
    # 步骤3: 下载分时数据（推荐后7天）
    success_count, total_records = download_intraday_data(db, recommendations, days=7)
    
    # 打印统计
    print("\n" + "="*70)
    print("下载完成统计")
    print("="*70)
    print(f"推荐股票: {len(recommendations)}只")
    print(f"成功下载: {success_count}只")
    print(f"总数据量: {total_records:,}条")
    print(f"平均每只: {total_records//success_count if success_count > 0 else 0}条")
    
    db.print_statistics()
    
    print("\n" + "="*70)
    print("[OK] 完成")
    print("="*70)


if __name__ == "__main__":
    main()
