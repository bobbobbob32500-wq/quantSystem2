# -*- coding: utf-8 -*-
"""测试批量选股"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.modules.stock_selector import StockSelector
from src.modules.backtest.history_recommendation_db import HistoryRecommendationDB
from datetime import datetime, timedelta

print('测试批量选股...')

selector = StockSelector()
db = HistoryRecommendationDB()

# 测试指定日期选股
print('\n测试指定日期选股 (20260318)...')
results = selector.run_selection(end_date='20260318')

if results:
    print(f'获取到 {len(results)} 只股票')
    for s in results[:3]:
        code = s['ts_code']
        name = s['name']
        score = s['total_score']
        print(f'  {code} {name} - {score}分')
    
    # 保存到数据库
    print('\n保存到数据库...')
    for stock in results:
        recommendation = {
            'symbol': stock['ts_code'],
            'name': stock['name'],
            'recommendation_date': '2026-03-18',
            'recommendation_score': stock['total_score'],
            'recommendation_reason': stock.get('level', ''),
            'strategy_type': stock.get('industry', ''),
        }
        db.add_recommendation(recommendation)
    print('保存成功')
else:
    print('无结果')
