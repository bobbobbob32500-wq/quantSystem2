# -*- coding: utf-8 -*-
"""检查数据库中的数据"""
import sqlite3

conn = sqlite3.connect('data/database/history_recommendation.db')
cursor = conn.cursor()

# 查询分时数据统计
cursor.execute('SELECT symbol, COUNT(*) as cnt FROM intraday_data GROUP BY symbol')
rows = cursor.fetchall()

print('\n股票代码 | 数据量')
print('-' * 30)
for row in rows:
    print(f'{row[0]:8s} | {row[1]:,}条')

# 查询推荐记录
cursor.execute('SELECT COUNT(*) FROM recommendations')
rec_count = cursor.fetchone()[0]

print(f'\n推荐记录总数: {rec_count}条')

conn.close()
