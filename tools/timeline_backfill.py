# -*- coding: utf-8 -*-
"""
时间线回填脚本 - 从今天往前推，一天天填充
"""

import sys
import os
import time
from datetime import datetime, timedelta

# 添加项目根目录到路径
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.core.config import ConfigManager
from src.core.database import DatabaseManager
from src.modules.stock_selector import StockSelector
from src.core.logger import get_logger

logger = get_logger("timeline_backfill")


def get_existing_dates(db: DatabaseManager) -> set:
    """
    获取数据库中已有的交易日

    Returns:
        已有的交易日集合
    """
    sql = "SELECT DISTINCT trade_date FROM factor_values ORDER BY trade_date DESC"
    existing_dates = {row['trade_date'] for row in db.query(sql)}
    return existing_dates


def generate_trade_dates(start_date: str, end_date: str) -> list:
    """
    生成交易日列表（排除周末）

    Args:
        start_date: 开始日期
        end_date: 结束日期

    Returns:
        交易日列表
    """
    dates = []
    start_dt = datetime.strptime(start_date, "%Y%m%d")
    end_dt = datetime.strptime(end_date, "%Y%m%d")

    current_dt = start_dt
    while current_dt >= end_dt:
        if current_dt.weekday() < 5:  # 排除周末
            dates.append(current_dt.strftime("%Y%m%d"))
        current_dt -= timedelta(days=1)

    return dates


def timeline_backfill(days_back: int = 365):
    """
    时间线回填 - 从最新数据开始，继续往更早的日期填充

    Args:
        days_back: 往前推多少天
    """
    logger.info("=" * 80)
    logger.info("时间线回填脚本启动")
    logger.info("=" * 80)
    logger.info(f"从最新数据开始，继续往前填充 {days_back} 天")
    logger.info("=" * 80)

    # 1. 初始化
    print("正在初始化配置...")
    config = ConfigManager()

    print("正在连接数据库...")
    db = DatabaseManager(config)

    print("正在初始化选股器...")
    selector = StockSelector(config, db)

    print("初始化完成！\n")

    # 2. 获取已有的日期
    print("正在查询已有数据...")
    existing_dates = get_existing_dates(db)
    logger.info(f"数据库中已有 {len(existing_dates)} 个交易日的数据")
    print(f"✓ 数据库中已有 {len(existing_dates)} 个交易日的数据")

    # 3. 找到最新的日期
    if existing_dates:
        latest_date = max(existing_dates)
        logger.info(f"最新数据日期: {latest_date}")
        print(f"✓ 最新数据日期: {latest_date}")
    else:
        latest_date = datetime.now().strftime("%Y%m%d")
        logger.info(f"数据库为空，从今天开始: {latest_date}")
        print(f"✓ 数据库为空，从今天开始: {latest_date}")

    # 4. 计算起始日期（从最新日期往前推）
    start_date = (datetime.strptime(latest_date, "%Y%m%d") - timedelta(days=days_back)).strftime("%Y%m%d")

    logger.info(f"回填范围: {start_date} ~ {latest_date}（从最新数据往前推）")
    print(f"✓ 回填范围: {start_date} ~ {latest_date}（从最新数据往前推）")

    # 5. 生成交易日列表（从最新日期往前推）
    print("\n正在生成交易日列表...")
    trade_dates = generate_trade_dates(latest_date, start_date)
    logger.info(f"共需填充 {len(trade_dates)} 个交易日（排除已有数据）")
    print(f"✓ 共需填充 {len(trade_dates)} 个交易日（排除已有数据）")

    if len(trade_dates) == 0:
        print("\n✓ 没有需要填充的日期，所有数据已存在！")
        return

    print(f"\n开始填充历史数据...")
    print("=" * 80)

    # 5. 回填每个交易日
    success_count = 0
    fail_count = 0
    skip_count = 0
    total_stocks = 0

    for i, trade_date in enumerate(trade_dates, 1):
        # 检查是否已有数据
        if trade_date in existing_dates:
            skip_count += 1
            print(f"[{i}/{len(trade_dates)}] {trade_date} - 跳过（已有数据）")
            logger.info(f"\n进度: {i}/{len(trade_dates)} - {trade_date} (跳过，已有数据)")
            continue

        print(f"\n[{i}/{len(trade_dates)}] 正在处理: {trade_date}")
        logger.info(f"\n进度: {i}/{len(trade_dates)} - {trade_date}")

        try:
            # 执行选股（会自动保存因子值）
            print(f"  → 正在筛选股票...")
            results = selector.run_selection(end_date=trade_date)

            if results:
                success_count += 1
                total_stocks += len(results)
                print(f"  → ✓ 成功，筛选出 {len(results)} 只股票")
                logger.info(f"  ✓ 成功，筛选出 {len(results)} 只股票")
            else:
                fail_count += 1
                print(f"  → ⚠ 未筛选出股票（可能数据不足或市场休市）")
                logger.warning(f"  ⚠ 未筛选出股票（可能数据不足或市场休市）")

        except Exception as e:
            fail_count += 1
            print(f"  → ✗ 失败: {e}")
            logger.error(f"  ✗ 失败: {e}")

        # 每回填10个日期，检查一次进度
        if i % 10 == 0:
            print(f"\n{'='*80}")
            print(f"进度更新:")
            print(f"  已处理: {i}/{len(trade_dates)} ({i/len(trade_dates)*100:.1f}%)")
            print(f"  成功: {success_count}, 失败: {fail_count}, 跳过: {skip_count}")
            print(f"  总股票数: {total_stocks}")

            # 检查总数据量
            sql = "SELECT COUNT(*) as count FROM factor_values"
            result = db.query_one(sql)
            total_count = result['count'] if result else 0
            print(f"  总记录数: {total_count}")

            # 检查交易日数
            sql = "SELECT COUNT(DISTINCT trade_date) as count FROM factor_values"
            result = db.query_one(sql)
            day_count = result['count'] if result else 0
            print(f"  交易日数: {day_count}")
            print(f"{'='*80}\n")

            logger.info(f"\n--- 进度更新 ---")
            logger.info(f"已处理: {i}/{len(trade_dates)} ({i/len(trade_dates)*100:.1f}%)")
            logger.info(f"成功: {success_count}, 失败: {fail_count}, 跳过: {skip_count}")
            logger.info(f"总记录数: {total_count}")
            logger.info(f"交易日数: {day_count}")
            logger.info(f"----------------")

    # 6. 总结
    print(f"\n{'='*80}")
    print("回填完成")
    print(f"{'='*80}")
    print(f"成功: {success_count} 天")
    print(f"失败: {fail_count} 天")
    print(f"跳过: {skip_count} 天（已有数据）")
    print(f"总股票数: {total_stocks}")

    # 7. 检查回填结果
    sql = "SELECT COUNT(*) as count FROM factor_values"
    result = db.query_one(sql)
    total_count = result['count'] if result else 0

    print(f"\nfactor_values表中共有 {total_count} 条记录")

    sql = "SELECT COUNT(DISTINCT trade_date) as count FROM factor_values"
    result = db.query_one(sql)
    day_count = result['count'] if result else 0

    print(f"共 {day_count} 个交易日")

    if day_count >= 30:
        print("✓ 数据充足，可以进行IC分析")
    if day_count >= 60:
        print("✓ 数据充足，可以进行因子验证")
    if day_count >= 250:
        print("✓ 数据充足，可以进行回测对比")

    logger.info("\n" + "=" * 80)
    logger.info("回填完成")
    logger.info("=" * 80)
    logger.info(f"成功: {success_count} 天")
    logger.info(f"失败: {fail_count} 天")
    logger.info(f"跳过: {skip_count} 天（已有数据）")
    logger.info(f"总股票数: {total_stocks}")
    logger.info(f"\nfactor_values表中共有 {total_count} 条记录")
    logger.info(f"共 {day_count} 个交易日")

    if day_count >= 30:
        logger.info("✓ 数据充足，可以进行IC分析")
    if day_count >= 60:
        logger.info("✓ 数据充足，可以进行因子验证")
    if day_count >= 250:
        logger.info("✓ 数据充足，可以进行回测对比")

    # 8. 显示数据分布
    sql = """
        SELECT trade_date, COUNT(*) as count
        FROM factor_values
        GROUP BY trade_date
        ORDER BY trade_date DESC
        LIMIT 10
    """
    date_counts = db.query(sql)

    if date_counts:
        print(f"\n最近10天的数据分布:")
        for row in date_counts:
            print(f"  {row['trade_date']}: {row['count']} 条")

        logger.info(f"\n最近10天的数据分布:")
        for row in date_counts:
            logger.info(f"  {row['trade_date']}: {row['count']} 条")


if __name__ == "__main__":
    print("\n" + "=" * 80)
    print("历史数据回填脚本 - 从最新数据继续往前填充")
    print("=" * 80)
    print("\n功能说明:")
    print("1. 从最新数据开始，继续往更早的日期填充")
    print("2. 例如: 有20260320的数据，就继续填充20260319, 20260318...")
    print("3. 自动跳过已有数据的日期")
    print("4. 按10个日期为单位显示进度")
    print("5. 最多回填365天的数据")
    print("\n使用场景:")
    print("- 已有最近数据，继续增加历史回测数据")
    print("- 数据会越来越完整，可以进行更长时间的回测")
    print("\n停止脚本: 按 Ctrl+C")
    print("=" * 80 + "\n")

    # 启动时间线回填
    timeline_backfill(days_back=365)
