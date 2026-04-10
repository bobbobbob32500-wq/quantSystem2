# -*- coding: utf-8 -*-
"""
获取最近推荐股票并下载分时数据
流程：
1. 获取最近10个交易日的推荐股票
2. 下载这些股票的分时数据
3. 保存到数据库
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

logger = get_logger("download_recent_recommendations")


def get_recent_trading_days(days=10):
    """
    获取最近N个交易日
    
    Args:
        days: 天数
    
    Returns:
        交易日列表
    """
    print("\n" + "="*70)
    print("获取最近交易日")
    print("="*70)
    
    # 简单方法：从今天往前推，跳过周末
    trading_days = []
    current = datetime.now()
    
    while len(trading_days) < days:
        # 跳过周末
        if current.weekday() < 5:  # 0-4 是周一到周五
            trading_days.append(current.strftime('%Y-%m-%d'))
        current -= timedelta(days=1)
    
    # 反转，使日期从小到大
    trading_days.reverse()
    
    print(f"\n最近{days}个交易日:")
    for i, date in enumerate(trading_days, 1):
        print(f"  {i}. {date}")
    
    return trading_days


def get_recent_recommendations(trading_days):
    """
    获取最近推荐股票
    
    Args:
        trading_days: 交易日列表
    
    Returns:
        推荐股票列表
    """
    print("\n" + "="*70)
    print("获取最近推荐股票")
    print("="*70)
    
    try:
        from src.modules.stock_selector import StockSelector
        
        print("\n[OK] 选股模块导入成功")
        
        selector = StockSelector()
        
        print(f"\n准备对 {len(trading_days)} 个交易日进行选股")
        print("这可能需要一些时间，请耐心等待...\n")
        
        all_recommendations = []
        
        for i, date in enumerate(trading_days, 1):
            print(f"\n[{i}/{len(trading_days)}] 选股日期: {date}")
            
            try:
                date_yyyymmdd = date.replace('-', '')
                result = selector.run_selection(end_date=date_yyyymmdd)
                
                if not result or len(result) == 0:
                    print(f"  [WARN] 无推荐股票")
                    continue
                
                # 处理选股结果（取前5只）
                for stock in result[:5]:
                    ts_code = stock.get('ts_code', '')
                    symbol = ts_code.split('.')[0] if ts_code else ''
                    
                    recommendation = {
                        'symbol': symbol,
                        'name': stock.get('name', ''),
                        'recommendation_date': date,
                        'recommendation_reason': stock.get('reason', '综合评分'),
                        'recommendation_score': float(stock.get('total_score', 0)),
                        'strategy_type': stock.get('strategy', 'unknown'),
                    }
                    all_recommendations.append(recommendation)
                    print(f"  [OK] {symbol} - {recommendation['name']} (评分:{recommendation['recommendation_score']:.0f})")
                
                print(f"  本日推荐: {len(result[:5])}只")
                
            except Exception as e:
                print(f"  [ERROR] 选股失败: {e}")
                continue
        
        print(f"\n" + "="*70)
        print(f"选股完成: 共获取 {len(all_recommendations)} 条推荐记录")
        print("="*70)
        
        return all_recommendations
        
    except Exception as e:
        print(f"\n[ERROR] 选股模块调用失败: {e}")
        import traceback
        traceback.print_exc()
        return []


def save_recommendations_to_db(db, recommendations):
    """保存推荐记录到数据库"""
    print("\n" + "="*70)
    print("保存推荐记录到数据库")
    print("="*70)
    
    if not recommendations:
        print("[WARN] 无推荐记录需要保存")
        return
    
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
    
    # 统计信息
    unique_symbols = set(r['symbol'] for r in recommendations)
    print(f"[OK] 不同股票: {len(unique_symbols)}只")


def download_intraday_data(db, recommendations):
    """下载分时数据"""
    print("\n" + "="*70)
    print("下载分时数据")
    print("="*70)
    
    if not recommendations:
        print("[WARN] 无推荐记录，跳过下载")
        return 0, 0
    
    try:
        import akshare as ak
        print("\n[OK] AKShare已安装")
    except ImportError:
        print("\n正在安装AKShare...")
        os.system("pip install akshare -q")
        import akshare as ak
    
    # 按股票分组
    stock_info = {}
    for rec in recommendations:
        symbol = rec['symbol']
        if symbol not in stock_info:
            stock_info[symbol] = {
                'name': rec['name'],
                'dates': [],
            }
        stock_info[symbol]['dates'].append(rec['recommendation_date'])
    
    print(f"\n准备下载 {len(stock_info)} 只股票的分时数据\n")
    
    success_count = 0
    total_records = 0
    
    for i, (symbol, data) in enumerate(stock_info.items(), 1):
        name = data['name']
        
        print(f"\n[{i}/{len(stock_info)}] {symbol} - {name}")
        print(f"  推荐次数: {len(data['dates'])}次")
        
        try:
            # 转换股票代码格式
            if symbol.startswith('6'):
                ak_symbol = f"sh{symbol}"
            else:
                ak_symbol = f"sz{symbol}"
            
            print(f"  正在下载 {ak_symbol} 分时数据...")
            
            # 添加重试机制
            max_retries = 3
            df = None
            
            for retry in range(max_retries):
                try:
                    df = ak.stock_zh_a_minute(symbol=ak_symbol, period='1')
                    break
                except Exception as e:
                    if retry < max_retries - 1:
                        print(f"  [WARN] 第{retry+1}次尝试失败，等待3秒后重试...")
                        time.sleep(3)
                    else:
                        raise e
            
            if df is None or df.empty:
                print(f"  [ERROR] 未获取到数据")
                continue
            
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
            
            # 转换数值类型
            df['open'] = pd.to_numeric(df['open'], errors='coerce')
            df['high'] = pd.to_numeric(df['high'], errors='coerce')
            df['low'] = pd.to_numeric(df['low'], errors='coerce')
            df['close'] = pd.to_numeric(df['close'], errors='coerce')
            df['volume'] = pd.to_numeric(df['volume'], errors='coerce')
            
            # 添加amount列
            df['amount'] = df['close'] * df['volume']
            
            print(f"  [OK] 数据量: {len(df)}条")
            print(f"  时间范围: {df['trade_time'].min()} ~ {df['trade_time'].max()}")
            
            # 保存到数据库
            db.add_intraday_data(symbol, df)
            print(f"  [OK] 数据已保存到数据库")
            
            success_count += 1
            total_records += len(df)
            
            # 添加延迟避免请求过快
            time.sleep(2)
            
        except Exception as e:
            print(f"  [ERROR] 下载失败: {e}")
    
    return success_count, total_records


def main():
    """主函数"""
    print("\n" + "="*70)
    print("获取最近推荐股票并下载分时数据")
    print("="*70)
    
    # 步骤1: 获取最近交易日（减少到5个）
    trading_days = get_recent_trading_days(days=5)
    
    # 步骤2: 获取推荐股票
    recommendations = get_recent_recommendations(trading_days)
    
    if not recommendations:
        print("\n[ERROR] 未获取到推荐股票，无法继续")
        return
    
    # 步骤3: 保存推荐记录
    db = HistoryRecommendationDB()
    save_recommendations_to_db(db, recommendations)
    
    # 步骤4: 下载分时数据
    success_count, total_records = download_intraday_data(db, recommendations)
    
    # 打印统计
    print("\n" + "="*70)
    print("下载完成统计")
    print("="*70)
    print(f"推荐记录: {len(recommendations)}条")
    print(f"不同股票: {len(set(r['symbol'] for r in recommendations))}只")
    print(f"成功下载: {success_count}只")
    print(f"总数据量: {total_records:,}条")
    
    if success_count > 0:
        print(f"平均每只: {total_records//success_count}条")
    
    db.print_statistics()
    
    print("\n" + "="*70)
    print("[OK] 完成")
    print("="*70)


if __name__ == "__main__":
    main()
