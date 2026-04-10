# -*- coding: utf-8 -*-
"""
因子值数据准备脚本
为P0优化功能准备必要的因子值数据
"""

import sys
import os

# 添加项目根目录到路径
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.core.config import ConfigManager
from src.core.database import DatabaseManager
from src.modules.stock_selector import StockSelector
from src.core.logger import get_logger

logger = get_logger("prepare_factor_data")


def prepare_factor_data():
    """准备因子值数据"""
    logger.info("=" * 80)
    logger.info("准备因子值数据")
    logger.info("=" * 80)
    
    # 1. 初始化
    config = ConfigManager()
    db = DatabaseManager(config)
    
    # 2. 检查数据准备情况
    sql = "SELECT COUNT(*) as count FROM stock_daily"
    result = db.query_one(sql)
    daily_count = result['count'] if result else 0
    
    logger.info(f"stock_daily表中有 {daily_count} 条记录")
    
    if daily_count == 0:
        logger.error("stock_daily表为空，请先运行数据更新")
        logger.info("建议:")
        logger.info("1. 运行主程序: python main.py")
        logger.info("2. 选择 '1. 数据管理'")
        logger.info("3. 选择 '1. 全量数据更新'")
        return False
    
    # 3. 检查股票列表
    sql = "SELECT COUNT(*) as count FROM stock_basic"
    result = db.query_one(sql)
    stock_count = result['count'] if result else 0
    
    logger.info(f"stock_basic表中有 {stock_count} 只股票")
    
    if stock_count == 0:
        logger.error("stock_basic表为空，请先运行数据更新")
        return False
    
    # 4. 创建选股器
    try:
        selector = StockSelector(config, db)
        logger.info("✓ 选股器初始化成功")
    except Exception as e:
        logger.error(f"✗ 选股器初始化失败: {e}")
        return False
    
    # 5. 执行选股（会自动保存因子值）
    logger.info("\n开始执行选股...")
    logger.info("注意: 这将计算并保存因子值到数据库")
    
    try:
        results = selector.run_selection()
        
        if results:
            logger.info(f"\n✓ 选股完成，筛选出 {len(results)} 只股票")
            logger.info("因子值已保存到 factor_values 表")
        else:
            logger.warning("⚠️ 未筛选出符合条件的股票")
        
        # 6. 检查因子值保存情况
        sql = "SELECT COUNT(*) as count FROM factor_values"
        result = db.query_one(sql)
        factor_count = result['count'] if result else 0
        
        logger.info(f"\nfactor_values表中有 {factor_count} 条记录")
        
        if factor_count > 0:
            logger.info("✓ 因子值数据准备成功")
            logger.info("\n现在可以使用P0优化功能了:")
            logger.info("1. 运行主程序: python main.py")
            logger.info("2. 选择 '14. P0优化功能'")
            logger.info("3. 选择对应的功能")
            return True
        else:
            logger.warning("⚠️ factor_values表仍为空")
            logger.info("请多执行几次选股功能，积累更多历史因子值")
            return False
    
    except Exception as e:
        logger.error(f"✗ 选股失败: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    print("\n" + "=" * 80)
    print("因子值数据准备")
    print("=" * 80 + "\n")
    
    success = prepare_factor_data()
    
    print("\n" + "=" * 80)
    if success:
        print("✓ 数据准备完成")
    else:
        print("✗ 数据准备失败，请检查错误信息")
    print("=" * 80)
