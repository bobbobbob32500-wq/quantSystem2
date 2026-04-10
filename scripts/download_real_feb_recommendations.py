# -*- coding: utf-8 -*-
"""
使用真实选股模块获取2026年2月推荐股票
并下载对应的分时数据
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

logger = get_logger("download_real_feb_recommendations")


def get_real_february_recommendations():
    """
    调用选股模块获取2026年2月的真实推荐股票
    """
    print("\n" + "="*70)
    print("步骤1: 调用选股模块获取2026年2月推荐股票")
    print("="*70)
    
    try:
        # 导入选股模块
        from src.modules.stock_selector import StockSelector
        
        print("\n[OK] 选股模块导入成功")
        
        # 创建选股器
        selector = StockSelector()
        
        # 2026年2月的交易日（选择代表性的几个日期）
        february_dates = [
            '2026-02-03',  # 第一周
            '2026-02-10',  # 第二周
            '2026-02-17',  # 第三周
            '2026-02-24',  # 第四周
        ]
        
        print(f"\n准备对 {len(february_dates)} 个交易日进行选股")
        
        all_recommendations = []
        
        for i, date in enumerate(february_dates, 1):
            print(f"\n[{i}/{len(february_dates)}] 选股日期: {date}")
            
            try:
                # 调用选股模块
                # 接口：run_selection(end_date='YYYYMMDD')
                date_yyyymmdd = date.replace('-', '')
                result = selector.run_selection(end_date=date_yyyymmdd)
                
                if not result or len(result) == 0:
                    print(f"  [WARN] 无推荐股票")
                    continue
                
                # 处理选股结果
                for stock in result[:5]:  # 只取前5只
                    recommendation = {
                        'symbol': stock.get('ts_code', '').split('.')[0],
                        'name': stock.get('name', ''),
                        'recommendation_date': date,
                        'recommendation_reason': stock.get('reason', '综合评分'),
                        'recommendation_score': float(stock.get('total_score', 0)),
                        'strategy_type': stock.get('strategy', 'unknown'),
                    }
                    all_recommendations.append(recommendation)
                    print(f"  [OK] {recommendation['symbol']} - {recommendation['name']} (评分:{recommendation['recommendation_score']:.0f})")
                
                # 添加延迟避免请求过快
                time.sleep(1)
                
            except Exception as e:
                print(f"  [ERROR] 选股失败: {e}")
                continue
        
        print(f"\n共获取 {len(all_recommendations)} 条推荐记录")
        
        return all_recommendations
        
    except Exception as e:
        print(f"\n[ERROR] 选股模块调用失败: {e}")
        print("使用备用方案：从数据库获取历史推荐记录")
        
        # 备用方案：从数据库获取
        return get_recommendations_from_database()


def get_recommendations_from_database():
    """从数据库获取历史推荐记录"""
    print("\n从数据库获取历史推荐记录...")
    
    try:
        # 尝试从信号数据库获取
        db_path = "data/quant_system.db"
        
        if not os.path.exists(db_path):
            print(f"[WARN] 数据库不存在: {db_path}")
            return []
        
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # 查询2026年2月的买入信号
        sql = """
            SELECT 
                ts_code,
                name,
                trigger_time,
                reason,
                priority_score,
                strategy_type
            FROM signals
            WHERE signal_type = 'buy'
              AND trigger_time >= '2026-02-01'
              AND trigger_time < '2026-03-01'
            ORDER BY trigger_time
        """
        
        cursor.execute(sql)
        rows = cursor.fetchall()
        
        conn.close()
        
        if not rows:
            print("[WARN] 数据库中无推荐记录")
            return []
        
        recommendations = []
        for row in rows:
            ts_code, name, trigger_time, reason, score, strategy = row
            
            symbol = ts_code.split('.')[0] if ts_code else ''
            date = trigger_time[:10] if trigger_time else ''
            
            recommendation = {
                'symbol': symbol,
                'name': name or '',
                'recommendation_date': date,
                'recommendation_reason': reason or '',
                'recommendation_score': float(score) if score else 0,
                'strategy_type': strategy or 'unknown',
            }
            recommendations.append(recommendation)
        
        print(f"[OK] 从数据库获取 {len(recommendations)} 条推荐记录")
        
        return recommendations
        
    except Exception as e:
        print(f"[ERROR] 从数据库获取失败: {e}")
        return []


def save_recommendations_to_db(db, recommendations):
    """保存推荐记录到数据库"""
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


def download_intraday_data(db, recommendations, days=7):
    """下载推荐后N天的分时数据"""
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
    
    # 去重：同一只股票只下载一次
    unique_stocks = {}
    for rec in recommendations:
        symbol = rec['symbol']
        if symbol not in unique_stocks:
            unique_stocks[symbol] = rec
    
    print(f"\n准备下载 {len(unique_stocks)} 只不同股票的分时数据")
    print(f"每只股票下载推荐后 {days} 天的数据")
    
    success_count = 0
    total_records = 0
    
    for i, (symbol, rec) in enumerate(unique_stocks.items(), 1):
        name = rec['name']
        rec_date = rec['recommendation_date']
        
        print(f"\n[{i}/{len(unique_stocks)}] {symbol} - {name}")
        print(f"  推荐日期: {rec_date}")
        
        # 计算数据范围
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
            start_dt = rec_dt
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
    print("使用真实选股模块获取2026年2月推荐股票")
    print("="*70)
    
    # 创建数据库
    db = HistoryRecommendationDB()
    
    # 步骤1: 获取真实推荐股票
    recommendations = get_real_february_recommendations()
    
    if not recommendations:
        print("\n[ERROR] 未获取到推荐股票，无法继续")
        return
    
    # 步骤2: 保存推荐记录
    save_recommendations_to_db(db, recommendations)
    
    # 步骤3: 下载分时数据
    success_count, total_records = download_intraday_data(db, recommendations, days=7)
    
    # 打印统计
    print("\n" + "="*70)
    print("下载完成统计")
    print("="*70)
    print(f"推荐股票: {len(recommendations)}条记录")
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
