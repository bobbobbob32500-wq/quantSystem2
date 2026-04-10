# -*- coding: utf-8 -*-
"""
测试Tushare API权限
"""

import tushare as ts
import time

print("\n" + "="*70)
print("测试Tushare API权限")
print("="*70)

# 设置token
token = '17c11d0c60a9196354a0be60abfa853bfdf5ebd96263e3c9ba8e38e5'
ts.set_token(token)
pro = ts.pro_api()

print(f"\nToken: {token[:20]}...")

# 测试1: 获取股票列表
print("\n测试1: 获取股票列表")
try:
    df = pro.stock_basic(exchange='', list_status='L', fields='ts_code,symbol,name')
    print(f"[OK] 获取成功: {len(df)}只股票")
except Exception as e:
    print(f"[ERROR] {e}")

time.sleep(1)

# 测试2: 获取日线数据
print("\n测试2: 获取日线数据")
try:
    df = pro.daily(ts_code='000001.SZ', start_date='20260201', end_date='20260210')
    print(f"[OK] 获取成功: {len(df)}条记录")
    if not df.empty:
        print(df.head())
except Exception as e:
    print(f"[ERROR] {e}")

time.sleep(1)

# 测试3: 获取分时数据
print("\n测试3: 获取分时数据")
try:
    df = pro.query('stk_mins', 
                   ts_code='000001.SZ', 
                   start_date='20260201093000', 
                   end_date='20260201150000',
                   freq='1min')
    print(f"[OK] 获取成功: {len(df)}条记录")
    if not df.empty:
        print(df.head())
except Exception as e:
    print(f"[ERROR] {e}")

print("\n" + "="*70)
print("测试完成")
print("="*70)
