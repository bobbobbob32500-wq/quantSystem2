# -*- coding: utf-8 -*-
"""测试AKShare获取近一个月分时数据"""
import akshare as ak
import pandas as pd
from datetime import datetime, timedelta

# ====================== 测试配置 ======================
stock_code = "600519"  # 股票代码（贵州茅台）
# ======================================================

# 自动计算：今天 - 30天 = 近一个月开始日期
end_date = datetime.now().strftime("%Y-%m-%d")
start_date = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")

print(f"\n正在获取 {stock_code} 从 {start_date} 到 {end_date} 的分时数据...")

try:
    # 获取 1 分钟级分时数据
    df = ak.stock_zh_a_hist_min_em(
        symbol=stock_code,
        period="1",        # 1 分钟数据
        start_date=start_date,
        end_date=end_date
    )
    
    # 打印数据概览
    print("\n[OK] 数据获取成功！")
    print(f"数据条数：{len(df)}")
    print(f"\n列名：{df.columns.tolist()}")
    print(f"\n前5条数据：")
    print(df.head())
    
    print(f"\n后5条数据：")
    print(df.tail())
    
    # 保存到本地 CSV 文件
    filename = f"{stock_code}_近一个月_1分钟分时数据.csv"
    df.to_csv(filename, encoding="utf-8-sig", index=False)
    print(f"\n[OK] 文件已保存：{filename}")
    
except Exception as e:
    print(f"\n[ERROR] 获取失败: {e}")
    import traceback
    traceback.print_exc()
