# -*- coding: utf-8 -*-
"""
获取2026年2月所有推荐股票，然后下载对应的分时数据
流程：
1. 先获取整个2月每天的所有推荐股票
2. 再下载每只股票推荐后7天的分时数据
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

logger = get_logger("download_feb_complete")


def get_all_february_recommendations():
    """
    步骤1: 获取2026年2月每天的所有推荐股票
    """
    print("\n" + "="*70)
    print("步骤1: 获取2026年2月所有推荐股票")
    print("="*70)
    
    try:
        # 导入选股模块
        from src.modules.stock_selector import StockSelector
        
        print("\n[OK] 选股模块导入成功")
        
        # 创建选股器
        selector = StockSelector()
        
        # 2026年2月的所有交易日
        february_dates = [
            '2026-02-03', '2026-02-04', '2026-02-05', '2026-02-06',
            '2026-02-09', '2026-02-10', '2026-02-11', '2026-02-12',
            '2026-02-13', '2026-02-17', '2026-02-18', '2026-02-19',
            '2026-02-20', '2026-02-23', '2026-02-24', '2026-02-25',
            '2026-02-26', '2026-02-27',
        ]
        
        print(f"\n准备对 {len(february_dates)} 个交易日进行选股")
        print("这可能需要一些时间，请耐心等待...\n")
        
        all_recommendations = []
        
        for i, date in enumerate(february_dates, 1):
            print(f"\n[{i}/{len(february_dates)}] 选股日期: {date}")
            
            try:
                # 调用选股模块
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
    """
    步骤2: 保存所有推荐记录到数据库
    """
    print("\n" + "="*70)
    print("步骤2: 缓存推荐记录到数据库")
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


def download_all_intraday_data(db, recommendations, days=7):
    """
    步骤3: 下载所有推荐股票的分时数据
    
    Args:
        db: 数据库对象
        recommendations: 推荐股票列表
        days: 每只股票下载的天数（默认7天）
    """
    print("\n" + "="*70)
    print(f"步骤3: 下载推荐后{days}天的分时数据")
    print("="*70)
    
    if not recommendations:
        print("[WARN] 无推荐记录，跳过下载")
        return 0, 0
    
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
    
    # 按股票分组，记录每只股票的推荐日期
    stock_dates = {}
    for rec in recommendations:
        symbol = rec['symbol']
        rec_date = rec['recommendation_date']
        
        if symbol not in stock_dates:
            stock_dates[symbol] = {
                'name': rec['name'],
                'dates': [],
            }
        
        stock_dates[symbol]['dates'].append(rec_date)
    
    print(f"\n准备下载 {len(stock_dates)} 只不同股票的分时数据")
    print(f"每只股票下载推荐后 {days} 天的数据\n")
    
    success_count = 0
    total_records = 0
    
    for i, (symbol, data) in enumerate(stock_dates.items(), 1):
        name = data['name']
        dates = data['dates']
        
        print(f"\n[{i}/{len(stock_dates)}] {symbol} - {name}")
        print(f"  推荐次数: {len(dates)}次")
        print(f"  推荐日期: {', '.join(dates[:3])}{'...' if len(dates) > 3 else ''}")
        
        # 计算数据范围：最早推荐日期 ~ 最晚推荐日期+7天
        min_date = min(dates)
        max_date = max(dates)
        
        start_dt = datetime.strptime(min_date, '%Y-%m-%d')
        end_dt = datetime.strptime(max_date, '%Y-%m-%d') + timedelta(days=days)
        
        print(f"  数据范围: {start_dt.strftime('%Y-%m-%d')} ~ {end_dt.strftime('%Y-%m-%d')}")
        
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
            df_filtered = df[(df['trade_time'] >= start_dt) & (df['trade_time'] <= end_dt)]
            
            if df_filtered.empty:
                print(f"  [WARN] 筛选后无数据")
                continue
            
            df_filtered = df_filtered.sort_values('trade_time').reset_index(drop=True)
            
            # 添加amount列
            if 'amount' not in df_filtered.columns:
                df_filtered['amount'] = df_filtered['close'] * df_filtered['volume']
            
            print(f"  [OK] 数据量: {len(df_filtered)}条")
            print(f"  时间范围: {df_filtered['trade_time'].min()} ~ {df_filtered['trade_time'].max()}")
            
            # 保存到数据库
            db.add_intraday_data(symbol, df_filtered)
            print(f"  [OK] 数据已保存到数据库")
            
            success_count += 1
            total_records += len(df_filtered)
            
            # 添加延迟避免请求过快
            time.sleep(2)
            
        except Exception as e:
            print(f"  [ERROR] 下载失败: {e}")
    
    return success_count, total_records


def main():
    """主函数"""
    print("\n" + "="*70)
    print("获取2026年2月所有推荐股票并下载分时数据")
    print("="*70)
    
    # 创建数据库
    db = HistoryRecommendationDB()
    
    # 步骤1: 获取所有推荐股票
    recommendations = get_all_february_recommendations()
    
    if not recommendations:
        print("\n[ERROR] 未获取到推荐股票，无法继续")
        return
    
    # 步骤2: 保存推荐记录
    save_recommendations_to_db(db, recommendations)
    
    # 步骤3: 下载分时数据
    success_count, total_records = download_all_intraday_data(db, recommendations, days=7)
    
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
