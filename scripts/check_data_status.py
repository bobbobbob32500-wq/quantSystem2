# -*- coding: utf-8 -*-
"""
数据状态检查脚本
检查股票数据下载情况、完整性和格式
"""

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import pandas as pd
import sqlite3
from datetime import datetime
from pathlib import Path

from src.core.logger import get_logger
from src.modules.backtest.history_recommendation_db import HistoryRecommendationDB
from src.modules.backtest.data_validator import StockCodeValidator, DataValidator

logger = get_logger("check_data_status")


def check_database_exists(db_path: str) -> bool:
    """检查数据库文件是否存在"""
    exists = os.path.exists(db_path)
    if exists:
        size_mb = os.path.getsize(db_path) / (1024 * 1024)
        print(f"✓ 数据库文件存在: {db_path}")
        print(f"  文件大小: {size_mb:.2f} MB")
    else:
        print(f"✗ 数据库文件不存在: {db_path}")
    return exists


def check_recommendations(db: HistoryRecommendationDB):
    """检查推荐记录"""
    print("\n" + "=" * 70)
    print("1. 推荐记录检查")
    print("=" * 70)
    
    conn = sqlite3.connect(db.db_path)
    cursor = conn.cursor()
    
    # 检查表是否存在
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='recommendations'")
    if not cursor.fetchone():
        print("✗ recommendations 表不存在")
        conn.close()
        return
    
    # 统计推荐记录
    cursor.execute("SELECT COUNT(*) FROM recommendations")
    total_count = cursor.fetchone()[0]
    print(f"✓ 推荐记录总数: {total_count}")
    
    if total_count == 0:
        print("⚠ 无推荐记录")
        conn.close()
        return
    
    # 按日期统计
    cursor.execute("""
        SELECT recommendation_date, COUNT(*) as count 
        FROM recommendations 
        GROUP BY recommendation_date 
        ORDER BY recommendation_date
    """)
    date_counts = cursor.fetchall()
    
    print(f"\n按日期分布:")
    for date, count in date_counts[:10]:  # 显示前10个日期
        print(f"  {date}: {count}条")
    
    if len(date_counts) > 10:
        print(f"  ... 共 {len(date_counts)} 个日期")
    
    # 股票代码统计
    cursor.execute("""
        SELECT symbol, COUNT(*) as count 
        FROM recommendations 
        GROUP BY symbol 
        ORDER BY count DESC
    """)
    symbol_counts = cursor.fetchall()
    
    print(f"\n股票代码覆盖:")
    print(f"  唯一股票数: {len(symbol_counts)}")
    print(f"  前5只股票:")
    for symbol, count in symbol_counts[:5]:
        print(f"    {symbol}: {count}次推荐")
    
    # 验证股票代码格式
    print(f"\n股票代码格式验证:")
    invalid_symbols = []
    for symbol, _ in symbol_counts:
        is_valid, errors = StockCodeValidator.validate(symbol)
        if not is_valid:
            invalid_symbols.append((symbol, errors))
    
    if invalid_symbols:
        print(f"  ✗ 发现 {len(invalid_symbols)} 个无效代码:")
        for symbol, errors in invalid_symbols[:5]:
            print(f"    {symbol}: {', '.join(errors)}")
    else:
        print(f"  ✓ 所有 {len(symbol_counts)} 个股票代码格式正确")
    
    conn.close()


def check_intraday_data(db: HistoryRecommendationDB):
    """检查分时数据"""
    print("\n" + "=" * 70)
    print("2. 分时数据检查")
    print("=" * 70)
    
    conn = sqlite3.connect(db.db_path)
    cursor = conn.cursor()
    
    # 检查表是否存在
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='intraday_data'")
    if not cursor.fetchone():
        print("✗ intraday_data 表不存在")
        conn.close()
        return
    
    # 统计分时数据
    cursor.execute("SELECT COUNT(*) FROM intraday_data")
    total_count = cursor.fetchone()[0]
    print(f"✓ 分时数据总条数: {total_count:,}")
    
    if total_count == 0:
        print("⚠ 无分时数据")
        conn.close()
        return
    
    # 股票覆盖情况
    cursor.execute("""
        SELECT symbol, COUNT(*) as count 
        FROM intraday_data 
        GROUP BY symbol 
        ORDER BY count DESC
    """)
    symbol_counts = cursor.fetchall()
    
    print(f"\n股票覆盖情况:")
    print(f"  有数据的股票数: {len(symbol_counts)}")
    
    # 统计每只股票的数据条数分布
    data_counts = [count for _, count in symbol_counts]
    avg_records = sum(data_counts) / len(data_counts) if data_counts else 0
    min_records = min(data_counts) if data_counts else 0
    max_records = max(data_counts) if data_counts else 0
    
    print(f"  平均每只股票: {avg_records:.0f}条")
    print(f"  最少记录: {min_records}条")
    print(f"  最多记录: {max_records}条")
    
    # 检查数据时间范围
    cursor.execute("SELECT MIN(trade_date), MAX(trade_date) FROM intraday_data")
    min_date, max_date = cursor.fetchone()
    print(f"\n数据时间范围:")
    print(f"  最早日期: {min_date}")
    print(f"  最晚日期: {max_date}")
    
    # 检查数据字段完整性
    print(f"\n数据字段检查:")
    cursor.execute("""
        SELECT 
            COUNT(*) as total,
            COUNT(open) as open_count,
            COUNT(high) as high_count,
            COUNT(low) as low_count,
            COUNT(close) as close_count,
            COUNT(volume) as volume_count
        FROM intraday_data
    """)
    row = cursor.fetchone()
    total, open_c, high_c, low_c, close_c, volume_c = row
    
    print(f"  总记录: {total:,}")
    print(f"  open字段: {open_c:,} ({open_c/total*100:.1f}%)")
    print(f"  high字段: {high_c:,} ({high_c/total*100:.1f}%)")
    print(f"  low字段: {low_c:,} ({low_c/total*100:.1f}%)")
    print(f"  close字段: {close_c:,} ({close_c/total*100:.1f}%)")
    print(f"  volume字段: {volume_c:,} ({volume_c/total*100:.1f}%)")
    
    # 检查异常数据
    print(f"\n异常数据检查:")
    cursor.execute("SELECT COUNT(*) FROM intraday_data WHERE open = 0 OR high = 0 OR low = 0 OR close = 0")
    zero_price_count = cursor.fetchone()[0]
    if zero_price_count > 0:
        print(f"  ⚠ 发现 {zero_price_count} 条零价格数据")
    else:
        print(f"  ✓ 无零价格数据")
    
    cursor.execute("SELECT COUNT(*) FROM intraday_data WHERE volume = 0")
    zero_volume_count = cursor.fetchone()[0]
    if zero_volume_count > 0:
        print(f"  ⚠ 发现 {zero_volume_count} 条零成交量数据")
    else:
        print(f"  ✓ 无零成交量数据")
    
    conn.close()


def check_data_completeness(db: HistoryRecommendationDB, follow_days: int = 7):
    """检查数据完整性（推荐股票是否有对应的分时数据）"""
    print("\n" + "=" * 70)
    print("3. 数据完整性检查")
    print("=" * 70)
    
    conn = sqlite3.connect(db.db_path)
    cursor = conn.cursor()
    
    # 获取所有推荐记录
    cursor.execute("SELECT DISTINCT symbol, recommendation_date FROM recommendations")
    recommendations = cursor.fetchall()
    
    print(f"推荐记录数: {len(recommendations)}")
    
    if not recommendations:
        conn.close()
        return
    
    # 检查每只股票的数据覆盖情况
    complete_count = 0
    partial_count = 0
    missing_count = 0
    
    print(f"\n检查每只股票的数据覆盖（需要推荐后{follow_days}个交易日数据）:")
    
    for i, (symbol, rec_date) in enumerate(recommendations[:20]):  # 检查前20条
        # 计算需要的数据范围
        rec_date_obj = datetime.strptime(rec_date, '%Y-%m-%d')
        start_date = rec_date_obj.strftime('%Y-%m-%d')
        end_date = (rec_date_obj + pd.Timedelta(days=follow_days + 5)).strftime('%Y-%m-%d')
        
        # 查询该股票的数据
        cursor.execute("""
            SELECT DISTINCT trade_date 
            FROM intraday_data 
            WHERE symbol = ? AND trade_date >= ? AND trade_date <= ?
            ORDER BY trade_date
        """, (symbol, start_date, end_date))
        
        dates = [row[0] for row in cursor.fetchall()]
        
        if len(dates) >= follow_days:
            complete_count += 1
            status = "✓ 完整"
        elif len(dates) > 0:
            partial_count += 1
            status = f"~ 部分({len(dates)}/{follow_days}天)"
        else:
            missing_count += 1
            status = "✗ 缺失"
        
        if i < 10:  # 显示前10条详情
            print(f"  {symbol} ({rec_date}): {status}")
    
    if len(recommendations) > 20:
        print(f"  ... 共 {len(recommendations)} 条记录")
    
    print(f"\n完整性统计:")
    print(f"  ✓ 完整数据: {complete_count} ({complete_count/len(recommendations)*100:.1f}%)")
    print(f"  ~ 部分数据: {partial_count} ({partial_count/len(recommendations)*100:.1f}%)")
    print(f"  ✗ 数据缺失: {missing_count} ({missing_count/len(recommendations)*100:.1f}%)")
    
    conn.close()


def check_data_quality(db: HistoryRecommendationDB):
    """检查数据质量"""
    print("\n" + "=" * 70)
    print("4. 数据质量检查")
    print("=" * 70)
    
    conn = sqlite3.connect(db.db_path)
    cursor = conn.cursor()
    
    # 检查价格合理性
    print("价格合理性检查:")
    cursor.execute("""
        SELECT 
            MIN(close) as min_price,
            MAX(close) as max_price,
            AVG(close) as avg_price
        FROM intraday_data
    """)
    min_price, max_price, avg_price = cursor.fetchone()
    print(f"  最低价格: {min_price:.2f}")
    print(f"  最高价格: {max_price:.2f}")
    print(f"  平均价格: {avg_price:.2f}")
    
    if min_price and min_price < 1:
        print(f"  ⚠ 发现极低价格数据，可能异常")
    
    if max_price and max_price > 10000:
        print(f"  ⚠ 发现极高价格数据，可能异常")
    
    # 检查成交量合理性
    print(f"\n成交量检查:")
    cursor.execute("""
        SELECT 
            MIN(volume) as min_vol,
            MAX(volume) as max_vol,
            AVG(volume) as avg_vol
        FROM intraday_data
    """)
    min_vol, max_vol, avg_vol = cursor.fetchone()
    print(f"  最小成交量: {min_vol:,.0f}")
    print(f"  最大成交量: {max_vol:,.0f}")
    print(f"  平均成交量: {avg_vol:,.0f}")
    
    # 检查时间连续性
    print(f"\n时间连续性检查:")
    cursor.execute("""
        SELECT symbol, trade_date, COUNT(*) as count
        FROM intraday_data
        GROUP BY symbol, trade_date
        ORDER BY count DESC
        LIMIT 5
    """)
    top_volume_days = cursor.fetchall()
    print(f"  数据量最多的5个交易日:")
    for symbol, date, count in top_volume_days:
        print(f"    {symbol} {date}: {count}条")
    
    conn.close()


def main():
    """主函数"""
    print("=" * 70)
    print("股票数据状态检查报告")
    print("=" * 70)
    print(f"检查时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    db_path = "data/history_recommendation.db"
    
    # 1. 检查数据库文件
    if not check_database_exists(db_path):
        print("\n✗ 数据库文件不存在，无法继续检查")
        return
    
    # 初始化数据库连接
    db = HistoryRecommendationDB(db_path)
    
    # 2. 检查推荐记录
    check_recommendations(db)
    
    # 3. 检查分时数据
    check_intraday_data(db)
    
    # 4. 检查数据完整性
    check_data_completeness(db, follow_days=7)
    
    # 5. 检查数据质量
    check_data_quality(db)
    
    print("\n" + "=" * 70)
    print("检查完成")
    print("=" * 70)


if __name__ == "__main__":
    main()
