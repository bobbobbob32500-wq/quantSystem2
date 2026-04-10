# -*- coding: utf-8 -*-
"""
分析分时数据详细情况
"""
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import pandas as pd
import sqlite3
from datetime import datetime

print("\n" + "="*70)
print("分时数据详细分析")
print("="*70)

# 连接数据库
db_path = "data/history_recommendation.db"
conn = sqlite3.connect(db_path)

# 1. 推荐记录统计
print("\n【1. 推荐记录统计】")
print("-" * 70)

cursor = conn.cursor()
cursor.execute("""
    SELECT 
        recommendation_date,
        COUNT(*) as count
    FROM recommendations
    GROUP BY recommendation_date
    ORDER BY recommendation_date
""")
rows = cursor.fetchall()

print(f"\n按日期统计:")
for row in rows:
    print(f"  {row[0]}: {row[1]}只股票")

cursor.execute("SELECT COUNT(DISTINCT symbol) FROM recommendations")
unique_symbols = cursor.fetchone()[0]
print(f"\n不同股票总数: {unique_symbols}只")

# 2. 分时数据统计
print("\n【2. 分时数据统计】")
print("-" * 70)

cursor.execute("""
    SELECT 
        symbol,
        COUNT(*) as count,
        MIN(trade_time) as min_time,
        MAX(trade_time) as max_time
    FROM intraday_data
    GROUP BY symbol
    ORDER BY count DESC
""")
rows = cursor.fetchall()

print(f"\n各股票数据量:")
for row in rows:
    symbol, count, min_time, max_time = row
    print(f"  {symbol:8s}: {count:5,}条 | {min_time[:10]} ~ {max_time[:10]}")

# 3. 数据质量检查
print("\n【3. 数据质量检查】")
print("-" * 70)

# 检查缺失值
cursor.execute("""
    SELECT 
        COUNT(*) as total,
        SUM(CASE WHEN open IS NULL OR open = 0 THEN 1 ELSE 0 END) as null_open,
        SUM(CASE WHEN close IS NULL OR close = 0 THEN 1 ELSE 0 END) as null_close,
        SUM(CASE WHEN volume IS NULL OR volume = 0 THEN 1 ELSE 0 END) as null_volume
    FROM intraday_data
""")
row = cursor.fetchone()
total, null_open, null_close, null_volume = row

print(f"\n总数据量: {total:,}条")
print(f"开盘价缺失: {null_open}条 ({null_open/total*100:.2f}%)")
print(f"收盘价缺失: {null_close}条 ({null_close/total*100:.2f}%)")
print(f"成交量缺失: {null_volume}条 ({null_volume/total*100:.2f}%)")

# 4. 时间分布分析
print("\n【4. 时间分布分析】")
print("-" * 70)

cursor.execute("""
    SELECT 
        trade_date,
        COUNT(*) as count
    FROM intraday_data
    GROUP BY trade_date
    ORDER BY trade_date
""")
rows = cursor.fetchall()

print(f"\n按交易日统计:")
for row in rows:
    date, count = row
    weekday = datetime.strptime(date, '%Y-%m-%d').strftime('%A')
    print(f"  {date} ({weekday[:3]}): {count:4,}条")

# 5. 价格分布分析
print("\n【5. 价格分布分析】")
print("-" * 70)

cursor.execute("""
    SELECT 
        symbol,
        AVG(close) as avg_price,
        MIN(close) as min_price,
        MAX(close) as max_price,
        AVG(volume) as avg_volume
    FROM intraday_data
    GROUP BY symbol
    ORDER BY avg_price DESC
""")
rows = cursor.fetchall()

print(f"\n各股票价格统计:")
for row in rows:
    symbol, avg_price, min_price, max_price, avg_volume = row
    price_range = (max_price - min_price) / avg_price * 100
    print(f"  {symbol:8s}: 均价{avg_price:8.2f} | 范围{min_price:8.2f}~{max_price:8.2f} | 波动{price_range:5.1f}% | 均量{avg_volume/10000:6.1f}万")

# 6. 分钟分布分析
print("\n【6. 分钟分布分析】")
print("-" * 70)

cursor.execute("""
    SELECT 
        strftime('%H:%M', trade_time) as minute,
        COUNT(*) as count
    FROM intraday_data
    GROUP BY minute
    ORDER BY minute
    LIMIT 10
""")
rows = cursor.fetchall()

print(f"\n每分钟数据量（前10个时间点）:")
for row in rows:
    minute, count = row
    print(f"  {minute}: {count:4,}条")

# 7. 推荐股票详情
print("\n【7. 推荐股票详情】")
print("-" * 70)

cursor.execute("""
    SELECT 
        r.symbol,
        r.name,
        r.recommendation_date,
        r.recommendation_score,
        r.strategy_type,
        r.recommendation_reason
    FROM recommendations r
    ORDER BY r.recommendation_date, r.recommendation_score DESC
""")
rows = cursor.fetchall()

print(f"\n推荐股票列表:")
current_date = None
for row in rows:
    symbol, name, rec_date, score, strategy, reason = row
    if rec_date != current_date:
        print(f"\n  [{rec_date}]")
        current_date = rec_date
    print(f"    {symbol} {name:8s} | 评分{score:5.0f} | {strategy:10s} | {reason[:20]}")

conn.close()

print("\n" + "="*70)
print("[OK] 分析完成")
print("="*70)
