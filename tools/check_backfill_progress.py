# -*- coding: utf-8 -*-
"""
检查回填进度脚本
"""

import sys
import os

# 添加项目根目录到路径
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.core.config import ConfigManager
from src.core.database import DatabaseManager
from src.core.logger import get_logger

logger = get_logger("check_backfill_progress")

def check_progress():
    """检查回填进度"""
    print("\n" + "=" * 80)
    print("回填进度检查")
    print("=" * 80 + "\n")
    
    # 1. 初始化
    config = ConfigManager()
    db = DatabaseManager(config)
    
    # 2. 检查factor_values表
    sql = "SELECT COUNT(*) as count FROM factor_values"
    result = db.query_one(sql)
    total_count = result['count'] if result else 0
    
    print(f"factor_values表中共有 {total_count} 条记录\n")
    
    if total_count == 0:
        print("⚠️ factor_values表为空，还没有任何数据")
        print("建议: 运行回填脚本")
        return
    
    # 3. 检查日期分布
    sql = """
        SELECT trade_date, COUNT(*) as count
        FROM factor_values
        GROUP BY trade_date
        ORDER BY trade_date DESC
    """
    date_counts = db.query(sql)
    
    print(f"数据分布（共 {len(date_counts)} 个交易日）:")
    print("-" * 80)
    
    for row in date_counts:
        print(f"  {row['trade_date']}: {row['count']} 条记录")
    
    print("-" * 80)
    
    # 4. 检查因子分布
    sql = """
        SELECT factor_name, COUNT(*) as count
        FROM factor_values
        GROUP BY factor_name
        ORDER BY factor_name
    """
    factor_counts = db.query(sql)
    
    print(f"\n因子分布（共 {len(factor_counts)} 个因子）:")
    print("-" * 80)
    
    for row in factor_counts:
        print(f"  {row['factor_name']}: {row['count']} 条记录")
    
    print("-" * 80)
    
    # 5. 评估数据充足性
    print(f"\n数据充足性评估:")
    print("-" * 80)
    
    if len(date_counts) >= 30:
        print(f"  ✓ IC分析: 数据充足（{len(date_counts)} 天）")
    else:
        print(f"  ⚠️ IC分析: 数据不足（{len(date_counts)} 天，需要至少30天）")
    
    if len(date_counts) >= 250:
        print(f"  ✓ 回测对比: 数据充足（{len(date_counts)} 天）")
    else:
        print(f"  ⚠️ 回测对比: 数据不足（{len(date_counts)} 天，建议至少250天）")
    
    print("-" * 80)
    
    # 6. 建议
    print(f"\n建议:")
    print("-" * 80)
    
    if len(date_counts) < 30:
        print("  1. 运行快速回填（5天）: python tools/quick_backfill.py")
        print("  2. 或运行完整回填（30天）: python tools/backfill_factor_data.py")
    elif len(date_counts) < 250:
        print("  1. 已可以进行IC分析")
        print("  2. 如需回测对比，继续回填到250天")
    else:
        print("  1. 数据充足，可以使用所有P0优化功能")
        print("  2. 运行主程序: python main.py")
        print("  3. 选择 '14. P0优化功能'")
    
    print("-" * 80)

if __name__ == "__main__":
    check_progress()
