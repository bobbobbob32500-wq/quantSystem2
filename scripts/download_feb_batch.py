# -*- coding: utf-8 -*-
"""
分批获取2026年2月推荐股票
可以分批运行，避免超时
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

logger = get_logger("download_feb_batch")


def get_batch_recommendations(start_idx=0, batch_size=5):
    """
    分批获取推荐股票
    
    Args:
        start_idx: 开始索引
        batch_size: 批次大小
    """
    print("\n" + "="*70)
    print(f"获取推荐股票 (批次: {start_idx//batch_size + 1})")
    print("="*70)
    
    # 2026年2月的所有交易日
    february_dates = [
        '2026-02-03', '2026-02-04', '2026-02-05', '2026-02-06',
        '2026-02-09', '2026-02-10', '2026-02-11', '2026-02-12',
        '2026-02-13', '2026-02-17', '2026-02-18', '2026-02-19',
        '2026-02-20', '2026-02-23', '2026-02-24', '2026-02-25',
        '2026-02-26', '2026-02-27',
    ]
    
    # 选择当前批次的日期
    batch_dates = february_dates[start_idx:start_idx+batch_size]
    
    if not batch_dates:
        print("[INFO] 已完成所有批次")
        return []
    
    print(f"\n当前批次日期: {batch_dates}")
    
    try:
        from src.modules.stock_selector import StockSelector
        
        print("\n[OK] 选股模块导入成功")
        
        selector = StockSelector()
        
        all_recommendations = []
        
        for i, date in enumerate(batch_dates, 1):
            print(f"\n[{i}/{len(batch_dates)}] 选股日期: {date}")
            
            try:
                date_yyyymmdd = date.replace('-', '')
                result = selector.run_selection(end_date=date_yyyymmdd)
                
                if not result or len(result) == 0:
                    print(f"  [WARN] 无推荐股票")
                    continue
                
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
                
            except Exception as e:
                print(f"  [ERROR] 选股失败: {e}")
                continue
        
        return all_recommendations
        
    except Exception as e:
        print(f"\n[ERROR] 选股模块调用失败: {e}")
        return []


def save_recommendations(db, recommendations):
    """保存推荐记录"""
    if not recommendations:
        return
    
    print("\n保存推荐记录...")
    for rec in recommendations:
        rec['status'] = 'active'
        db.add_recommendation(rec)
    
    print(f"[OK] 已保存 {len(recommendations)} 条推荐记录")


def download_intraday_data(db, recommendations, days=7):
    """下载分时数据"""
    print("\n" + "="*70)
    print(f"下载分时数据")
    print("="*70)
    
    if not recommendations:
        return 0, 0
    
    try:
        import akshare as ak
        print("\n[OK] AKShare已安装")
    except ImportError:
        print("\n正在安装AKShare...")
        os.system("pip install akshare -q")
        import akshare as ak
    
    # 按股票分组
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
    
    print(f"\n准备下载 {len(stock_dates)} 只股票的分时数据\n")
    
    success_count = 0
    total_records = 0
    
    for i, (symbol, data) in enumerate(stock_dates.items(), 1):
        name = data['name']
        dates = data['dates']
        
        print(f"\n[{i}/{len(stock_dates)}] {symbol} - {name}")
        
        min_date = min(dates)
        max_date = max(dates)
        
        start_dt = datetime.strptime(min_date, '%Y-%m-%d')
        end_dt = datetime.strptime(max_date, '%Y-%m-%d') + timedelta(days=days)
        
        print(f"  数据范围: {start_dt.strftime('%Y-%m-%d')} ~ {end_dt.strftime('%Y-%m-%d')}")
        
        try:
            # 由于 stock_zh_a_hist_min_em 接口不可用
            # 使用 stock_zh_a_minute 获取最近的分时数据
            print(f"  正在下载 {symbol} 分时数据...")
            
            # 转换股票代码格式
            if symbol.startswith('6'):
                ak_symbol = f"sh{symbol}"
            else:
                ak_symbol = f"sz{symbol}"
            
            # 添加重试机制
            max_retries = 3
            for retry in range(max_retries):
                try:
                    # 使用 stock_zh_a_minute 获取分时数据
                    df = ak.stock_zh_a_minute(symbol=ak_symbol, period='1')
                    break  # 成功则跳出重试循环
                except Exception as e:
                    if retry < max_retries - 1:
                        print(f"  [WARN] 第{retry+1}次尝试失败，等待3秒后重试...")
                        time.sleep(3)
                    else:
                        raise e  # 最后一次重试失败则抛出异常
            
            if df.empty:
                print(f"  [ERROR] 未获取到数据")
                continue
            
            # 处理数据 - stock_zh_a_minute 返回的列名
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
            
            df_filtered = df[(df['trade_time'] >= start_dt) & (df['trade_time'] <= end_dt)]
            
            if df_filtered.empty:
                print(f"  [ERROR] 筛选后无数据，跳过该股票")
                continue
            
            df_filtered = df_filtered.sort_values('trade_time').reset_index(drop=True)
            
            if 'amount' not in df_filtered.columns:
                df_filtered['amount'] = df_filtered['close'] * df_filtered['volume']
            
            print(f"  [OK] 数据量: {len(df_filtered)}条")
            
            db.add_intraday_data(symbol, df_filtered)
            print(f"  [OK] 数据已保存")
            
            success_count += 1
            total_records += len(df_filtered)
            
            time.sleep(2)
            
        except Exception as e:
            print(f"  [ERROR] 下载失败: {e}")
    
    return success_count, total_records


def main():
    """主函数"""
    print("\n" + "="*70)
    print("分批获取2026年2月推荐股票")
    print("="*70)
    
    # 参数设置
    start_idx = 0  # 开始索引（0, 5, 10, 15）
    batch_size = 5  # 每批处理5个日期
    
    print(f"\n当前批次: 第{start_idx//batch_size + 1}批")
    print(f"处理日期索引: {start_idx} ~ {start_idx + batch_size - 1}")
    
    # 创建数据库
    db = HistoryRecommendationDB()
    
    # 如果是第一批，清空旧数据
    if start_idx == 0:
        print("\n清空旧数据...")
        if os.path.exists(db.db_path):
            conn = sqlite3.connect(db.db_path)
            cursor = conn.cursor()
            cursor.execute("DELETE FROM recommendations")
            cursor.execute("DELETE FROM intraday_data")
            conn.commit()
            conn.close()
            print("[OK] 旧数据已清空")
    
    # 获取推荐股票
    recommendations = get_batch_recommendations(start_idx, batch_size)
    
    if not recommendations:
        print("\n[WARN] 未获取到推荐股票")
        return
    
    # 保存推荐记录
    save_recommendations(db, recommendations)
    
    # 下载分时数据
    success_count, total_records = download_intraday_data(db, recommendations, days=7)
    
    # 打印统计
    print("\n" + "="*70)
    print("本批次完成统计")
    print("="*70)
    print(f"推荐记录: {len(recommendations)}条")
    print(f"成功下载: {success_count}只")
    print(f"总数据量: {total_records:,}条")
    
    db.print_statistics()
    
    print("\n" + "="*70)
    print(f"[OK] 第{start_idx//batch_size + 1}批完成")
    print(f"下一批请设置: start_idx = {start_idx + batch_size}")
    print("="*70)


if __name__ == "__main__":
    main()
