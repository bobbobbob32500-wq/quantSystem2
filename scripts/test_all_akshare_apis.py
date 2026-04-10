# -*- coding: utf-8 -*-
"""
测试多种AKShare分时数据接口
找出可用的接口
"""
import akshare as ak
import pandas as pd
from datetime import datetime, timedelta
import time

print("\n" + "="*70)
print("测试AKShare分时数据接口")
print("="*70)

stock_code = "600519"

# 测试1: stock_zh_a_hist_min_em (历史分时 - 东方财富)
print("\n[测试1] stock_zh_a_hist_min_em - 历史分时（东方财富）")
try:
    end_date = datetime.now().strftime("%Y-%m-%d")
    start_date = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
    
    df = ak.stock_zh_a_hist_min_em(
        symbol=stock_code,
        period="1",
        start_date=start_date,
        end_date=end_date
    )
    print(f"[OK] 成功: {len(df)}条数据")
    print(f"列名: {df.columns.tolist()}")
except Exception as e:
    print(f"[ERROR] 失败: {str(e)[:100]}")

time.sleep(2)

# 测试2: stock_zh_a_minute (当日分时)
print("\n[测试2] stock_zh_a_minute - 当日分时")
try:
    ak_symbol = f"sh{stock_code}"
    df = ak.stock_zh_a_minute(symbol=ak_symbol, period='1')
    print(f"[OK] 成功: {len(df)}条数据")
    print(f"列名: {df.columns.tolist()}")
    print(f"时间范围: {df['day'].min()} ~ {df['day'].max()}")
except Exception as e:
    print(f"[ERROR] 失败: {str(e)[:100]}")

time.sleep(2)

# 测试3: stock_zh_a_hist (日K线)
print("\n[测试3] stock_zh_a_hist - 日K线")
try:
    end_date = datetime.now().strftime("%Y%m%d")
    start_date = (datetime.now() - timedelta(days=30)).strftime("%Y%m%d")
    
    df = ak.stock_zh_a_hist(
        symbol=stock_code,
        period="daily",
        start_date=start_date,
        end_date=end_date,
        adjust=""
    )
    print(f"[OK] 成功: {len(df)}条数据")
    print(f"列名: {df.columns.tolist()}")
except Exception as e:
    print(f"[ERROR] 失败: {str(e)[:100]}")

time.sleep(2)

# 测试4: stock_zh_a_spot_em (实时行情)
print("\n[测试4] stock_zh_a_spot_em - A股实时行情")
try:
    df = ak.stock_zh_a_spot_em()
    # 筛选特定股票
    df_stock = df[df['代码'] == stock_code]
    print(f"[OK] 成功: 共{len(df)}只股票")
    if not df_stock.empty:
        print(f"目标股票: {df_stock.iloc[0]['名称']}")
        print(f"最新价: {df_stock.iloc[0]['最新价']}")
except Exception as e:
    print(f"[ERROR] 失败: {str(e)[:100]}")

print("\n" + "="*70)
print("测试完成")
print("="*70)
