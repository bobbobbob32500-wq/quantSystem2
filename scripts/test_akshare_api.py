# -*- coding: utf-8 -*-
"""测试AKShare分时数据接口"""
import akshare as ak
import time

print("\n测试AKShare分时数据接口")
print("="*70)

# 测试1: stock_zh_a_hist_min_em (历史分时)
print("\n[测试1] stock_zh_a_hist_min_em - 历史分时数据")
try:
    df = ak.stock_zh_a_hist_min_em(
        symbol="600519",
        start_date="2025-03-20",
        end_date="2025-03-20",
        period='1',
        adjust=''
    )
    print(f"[OK] 成功获取数据: {len(df)}条")
    print(df.head())
except Exception as e:
    print(f"[ERROR] 失败: {e}")

time.sleep(2)

# 测试2: stock_zh_a_minute (当日分时)
print("\n[测试2] stock_zh_a_minute - 当日分时数据")
try:
    df = ak.stock_zh_a_minute(symbol="sh600519", period='1')
    print(f"[OK] 成功获取数据: {len(df)}条")
    print(df.head())
except Exception as e:
    print(f"[ERROR] 失败: {e}")

time.sleep(2)

# 测试3: stock_zh_a_hist (日K线)
print("\n[测试3] stock_zh_a_hist - 日K线数据")
try:
    df = ak.stock_zh_a_hist(
        symbol="600519",
        period="daily",
        start_date="20250301",
        end_date="20250320",
        adjust=""
    )
    print(f"[OK] 成功获取数据: {len(df)}条")
    print(df.head())
except Exception as e:
    print(f"[ERROR] 失败: {e}")

print("\n" + "="*70)
