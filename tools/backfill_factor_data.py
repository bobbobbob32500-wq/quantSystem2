# -*- coding: utf-8 -*-
"""
历史因子值回填脚本
为过去的历史日期回填因子值，快速积累数据
"""

import sys
import os
from datetime import datetime, timedelta

# 添加项目根目录到路径
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.core.config import ConfigManager
from src.core.database import DatabaseManager
from src.modules.stock_selector import StockSelector
from src.core.logger import get_logger

logger = get_logger("backfill_factor_data")


def backfill_factor_data(start_date: str, end_date: str = None):
    """
    回填历史因子值
    
    Args:
        start_date: 开始日期（YYYYMMDD格式）
        end_date: 结束日期（YYYYMMDD格式），默认为今天
    """
    logger.info("=" * 80)
    logger.info("历史因子值回填")
    logger.info("=" * 80)
    
    if end_date is None:
        end_date = datetime.now().strftime("%Y%m%d")
    
    logger.info(f"回填期间: {start_date} ~ {end_date}")
    
    # 1. 初始化
    config = ConfigManager()
    db = DatabaseManager(config)
    selector = StockSelector(config, db)
    
    # 2. 解析日期范围
    start_dt = datetime.strptime(start_date, "%Y%m%d")
    end_dt = datetime.strptime(end_date, "%Y%m%d")
    
    # 3. 计算交易日期（排除周末）
    trade_dates = []
    current_dt = start_dt
    while current_dt <= end_dt:
        # 排除周末（5=周六, 6=周日）
        if current_dt.weekday() < 5:
            trade_dates.append(current_dt.strftime("%Y%m%d"))
        current_dt += timedelta(days=1)
    
    logger.info(f"共 {len(trade_dates)} 个交易日")
    
    # 4. 回填每个交易日的因子值
    success_count = 0
    fail_count = 0
    total_stocks = 0
    
    for i, trade_date in enumerate(trade_dates, 1):
        logger.info(f"\n进度: {i}/{len(trade_dates)} ({i/len(trade_dates)*100:.1f}%) - {trade_date}")
        
        try:
            # 执行选股（会自动保存因子值）
            results = selector.run_selection(end_date=trade_date)
            
            if results:
                success_count += 1
                total_stocks += len(results)
                logger.info(f"  ✓ 成功，筛选出 {len(results)} 只股票")
            else:
                fail_count += 1
                logger.warning(f"  ⚠ 未筛选出股票")
        
        except Exception as e:
            fail_count += 1
            logger.error(f"  ✗ 失败: {e}")
    
    # 5. 总结
    logger.info("\n" + "=" * 80)
    logger.info("回填完成")
    logger.info("=" * 80)
    logger.info(f"成功: {success_count} 天")
    logger.info(f"失败: {fail_count} 天")
    logger.info(f"总股票数: {total_stocks}")
    
    # 6. 检查回填结果
    sql = "SELECT COUNT(*) as count FROM factor_values"
    result = db.query_one(sql)
    total_count = result['count'] if result else 0
    
    logger.info(f"\nfactor_values表中共有 {total_count} 条记录")
    
    if total_count >= 30:
        logger.info("✓ 数据充足，可以进行IC分析了")
    else:
        logger.warning(f"⚠️ 数据不足，建议继续回填到至少30天")
    
    # 7. 显示数据分布
    sql = """
        SELECT trade_date, COUNT(*) as count
        FROM factor_values
        GROUP BY trade_date
        ORDER BY trade_date
    """
    date_counts = db.query(sql)
    
    if date_counts:
        logger.info(f"\n数据分布（按日期）:")
        for row in date_counts[:10]:  # 显示最近10天
            logger.info(f"  {row['trade_date']}: {row['count']} 条")
        if len(date_counts) > 10:
            logger.info(f"  ... 还有 {len(date_counts) - 10} 天")


if __name__ == "__main__":
    print("\n" + "=" * 80)
    print("历史因子值回填工具")
    print("=" * 80 + "\n")
    
    # 设置回填日期范围（可以根据实际情况调整）
    # 回填最近30个交易日（约1.5个月）
    end_date = datetime.now().strftime("%Y%m%d")
    start_date = (datetime.now() - timedelta(days=45)).strftime("%Y%m%d")
    
    print(f"回填日期范围: {start_date} ~ {end_date}")
    print("这将回填约30个交易日的因子值\n")
    
    backfill_factor_data(start_date, end_date)
    
    print("\n" + "=" * 80)
    print("✓ 回填完成！")
    print("现在可以使用P0优化功能了:")
    print("1. 运行主程序: python main.py")
    print("2. 选择 '14. P0优化功能'")
    print("=" * 80)
