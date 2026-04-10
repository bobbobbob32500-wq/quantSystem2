# -*- coding: utf-8 -*-
"""
快速回填脚本 - 仅回填少量数据用于测试
"""

import sys
import os
from datetime import datetime, timedelta

# 添加项目根目录到路径
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from tools.backfill_factor_data import backfill_factor_data

def quick_backfill():
    """快速回填 - 仅回填5个交易日"""
    print("\n" + "=" * 80)
    print("快速回填 - 仅回填5个交易日")
    print("=" * 80 + "\n")
    
    end_date = datetime.now().strftime("%Y%m%d")
    start_date = (datetime.now() - timedelta(days=10)).strftime("%Y%m%d")
    
    print(f"回填日期范围: {start_date} ~ {end_date}")
    print("这将回填约5个交易日的因子值\n")
    
    backfill_factor_data(start_date, end_date)
    
    print("\n" + "=" * 80)
    print("✓ 快速回填完成！")
    print("=" * 80)

if __name__ == "__main__":
    quick_backfill()
