# -*- coding: utf-8 -*-
"""
后台持续回填脚本
自动在后台运行，持续增加因子值样本数量
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

logger = get_logger("continuous_backfill")


def get_missing_dates(db: DatabaseManager, start_date: str, end_date: str) -> list:
    """
    获取缺失的交易日
    
    Args:
        db: 数据库管理器
        start_date: 开始日期
        end_date: 结束日期
    
    Returns:
        缺失的交易日列表
    """
    # 1. 获取数据库中已有的日期
    sql = """
        SELECT DISTINCT trade_date
        FROM factor_values
        WHERE trade_date >= ? AND trade_date <= ?
        ORDER BY trade_date
    """
    existing_dates = [row['trade_date'] for row in db.query(sql, (start_date, end_date))]
    
    # 2. 生成所有交易日（排除周末）
    all_dates = []
    start_dt = datetime.strptime(start_date, "%Y%m%d")
    end_dt = datetime.strptime(end_date, "%Y%m%d")
    
    current_dt = start_dt
    while current_dt <= end_dt:
        if current_dt.weekday() < 5:  # 排除周末
            all_dates.append(current_dt.strftime("%Y%m%d"))
        current_dt += timedelta(days=1)
    
    # 3. 找出缺失的日期
    missing_dates = [d for d in all_dates if d not in existing_dates]
    
    return missing_dates


def continuous_backfill(interval_hours: int = 24, max_days_back: int = 365):
    """
    持续回填脚本
    
    Args:
        interval_hours: 运行间隔（小时），默认24小时（每天运行一次）
        max_days_back: 最多回填多少天，默认365天（1年）
    """
    logger.info("=" * 80)
    logger.info("后台持续回填脚本启动")
    logger.info("=" * 80)
    logger.info(f"运行间隔: {interval_hours} 小时")
    logger.info(f"最多回填: {max_days_back} 天")
    logger.info("=" * 80)
    
    # 1. 初始化
    config = ConfigManager()
    db = DatabaseManager(config)
    selector = StockSelector(config, db)
    
    # 2. 主循环
    while True:
        try:
            logger.info("\n" + "=" * 80)
            logger.info(f"开始新一轮回填 - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            logger.info("=" * 80)
            
            # 3. 计算日期范围
            end_date = datetime.now().strftime("%Y%m%d")
            start_date = (datetime.now() - timedelta(days=max_days_back)).strftime("%Y%m%d")
            
            logger.info(f"回填范围: {start_date} ~ {end_date}")
            
            # 4. 检查缺失的日期
            missing_dates = get_missing_dates(db, start_date, end_date)
            
            if missing_dates:
                logger.info(f"发现 {len(missing_dates)} 个缺失的交易日")
                
                # 5. 回填缺失的日期
                success_count = 0
                fail_count = 0
                
                for i, trade_date in enumerate(missing_dates, 1):
                    logger.info(f"\n处理 {i}/{len(missing_dates)}: {trade_date}")
                    
                    try:
                        results = selector.run_selection(end_date=trade_date)
                        
                        if results:
                            success_count += 1
                            logger.info(f"  ✓ 成功，筛选出 {len(results)} 只股票")
                        else:
                            fail_count += 1
                            logger.warning(f"  ⚠ 未筛选出股票（可能数据不足或市场休市）")
                            
                            # 连续失败5次就跳过剩余日期
                            if fail_count >= 5:
                                logger.warning(f"\n连续 {fail_count} 次未筛选出股票，跳过剩余日期")
                                break
                    
                    except Exception as e:
                        fail_count += 1
                        logger.error(f"  ✗ 失败: {e}")
                
                # 6. 总结
                logger.info("\n" + "-" * 80)
                logger.info("本轮回填完成")
                logger.info(f"成功: {success_count} 天")
                logger.info(f"失败: {fail_count} 天")
                logger.info("-" * 80)
                
                # 7. 检查总数据量
                sql = "SELECT COUNT(*) as count FROM factor_values"
                result = db.query_one(sql)
                total_count = result['count'] if result else 0
                
                logger.info(f"\nfactor_values表中共有 {total_count} 条记录")
                
                sql = "SELECT COUNT(DISTINCT trade_date) as count FROM factor_values"
                result = db.query_one(sql)
                day_count = result['count'] if result else 0
                
                logger.info(f"共 {day_count} 个交易日")
                
                if day_count >= 30:
                    logger.info("✓ 数据充足，可以进行IC分析")
                if day_count >= 60:
                    logger.info("✓ 数据充足，可以进行因子验证")
                if day_count >= 250:
                    logger.info("✓ 数据充足，可以进行回测对比")
            
            else:
                logger.info("✓ 数据已是最新，无需回填")
            
            # 8. 等待下一次运行
            logger.info(f"\n等待 {interval_hours} 小时后继续...")
            logger.info("按 Ctrl+C 停止脚本")
            
            # 转换为秒
            wait_seconds = interval_hours * 3600
            
            # 每10分钟输出一次等待状态
            for i in range(wait_seconds // 600):
                time.sleep(600)
                remaining = wait_seconds - (i + 1) * 600
                hours = remaining // 3600
                minutes = (remaining % 3600) // 60
                logger.info(f"等待中... 剩余 {hours} 小时 {minutes} 分钟")
            
            # 剩余时间
            time.sleep(wait_seconds % 600)
        
        except KeyboardInterrupt:
            logger.info("\n" + "=" * 80)
            logger.info("用户中断，脚本停止")
            logger.info("=" * 80)
            break
        
        except Exception as e:
            logger.error(f"发生错误: {e}")
            import traceback
            traceback.print_exc()
            logger.info("等待1小时后重试...")
            time.sleep(3600)


if __name__ == "__main__":
    print("\n" + "=" * 80)
    print("后台持续回填脚本")
    print("=" * 80)
    print("\n功能说明:")
    print("1. 自动检测缺失的交易日")
    print("2. 自动回填缺失的因子值")
    print("3. 持续运行，每天检查一次")
    print("4. 最多回填365天的数据")
    print("\n使用建议:")
    print("1. 在后台运行此脚本")
    print("2. 脚本会自动持续增加样本数量")
    print("3. 数据会越来越多，分析结果会越来越准确")
    print("\n停止脚本: 按 Ctrl+C")
    print("=" * 80 + "\n")
    
    # 启动持续回填
    continuous_backfill(interval_hours=24, max_days_back=365)
