# -*- coding: utf-8 -*-
"""
数据库迁移工具
从SQLite迁移到DuckDB
"""

import sys
import os

# 添加项目根目录到路径
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.core.config import ConfigManager
from src.core.database import DatabaseManager
from src.core.duckdb_manager import DuckDBManager
from src.core.logger import get_logger
import pandas as pd
from datetime import datetime

logger = get_logger("migrate_to_duckdb")


def migrate_stock_basic(sqlite_db: DatabaseManager, duckdb_db: DuckDBManager):
    """迁移股票基础信息"""
    logger.info("迁移股票基础信息...")
    
    # 从SQLite读取
    sql = "SELECT * FROM stock_basic"
    sqlite_data = sqlite_db.query(sql)
    
    if sqlite_data:
        df = pd.DataFrame(sqlite_data)
        
        # 处理日期格式
        if 'list_date' in df.columns:
            df['list_date'] = pd.to_datetime(df['list_date'], format='%Y%m%d', errors='coerce')
        
        if 'update_time' in df.columns:
            df['update_time'] = pd.to_datetime(df['update_time'], errors='coerce')
        
        # 写入DuckDB
        duckdb_db.batch_insert_df('stock_basic', df)
        logger.info(f"  迁移完成: {len(df)}条记录")
    else:
        logger.warning("  无数据")


def migrate_stock_daily(sqlite_db: DatabaseManager, duckdb_db: DuckDBManager,
                       batch_size: int = 10000):
    """迁移股票日线数据（分批）"""
    logger.info("迁移股票日线数据...")
    
    # 获取总记录数
    count_sql = "SELECT COUNT(*) as total FROM stock_daily"
    total_count = sqlite_db.query(count_sql)[0]['total']
    
    logger.info(f"  总记录数: {total_count}")
    
    # 分批迁移
    offset = 0
    migrated_count = 0
    
    while offset < total_count:
        sql = f"SELECT * FROM stock_daily ORDER BY ts_code, trade_date LIMIT {batch_size} OFFSET {offset}"
        batch_data = sqlite_db.query(sql)
        
        if batch_data:
            df = pd.DataFrame(batch_data)
            
            # 处理日期格式
            if 'trade_date' in df.columns:
                df['trade_date'] = pd.to_datetime(df['trade_date'], format='%Y%m%d', errors='coerce')
            
            # 写入DuckDB
            duckdb_db.batch_insert_df('stock_daily', df)
            
            migrated_count += len(df)
            logger.info(f"  已迁移: {migrated_count}/{total_count} ({migrated_count/total_count*100:.1f}%)")
        
        offset += batch_size
    
    logger.info(f"  迁移完成: {migrated_count}条记录")


def migrate_factor_values(sqlite_db: DatabaseManager, duckdb_db: DuckDBManager,
                          batch_size: int = 10000):
    """迁移因子值（分批）"""
    logger.info("迁移因子值...")
    
    # 获取总记录数
    count_sql = "SELECT COUNT(*) as total FROM factor_values"
    total_count = sqlite_db.query(count_sql)[0]['total']
    
    if total_count == 0:
        logger.info("  无数据")
        return
    
    logger.info(f"  总记录数: {total_count}")
    
    # 分批迁移
    offset = 0
    migrated_count = 0
    
    while offset < total_count:
        sql = f"SELECT * FROM factor_values ORDER BY ts_code, trade_date LIMIT {batch_size} OFFSET {offset}"
        batch_data = sqlite_db.query(sql)
        
        if batch_data:
            df = pd.DataFrame(batch_data)
            
            # 处理日期格式
            if 'trade_date' in df.columns:
                df['trade_date'] = pd.to_datetime(df['trade_date'], format='%Y%m%d', errors='coerce')
            
            if 'create_time' in df.columns:
                df['create_time'] = pd.to_datetime(df['create_time'], errors='coerce')
            
            # 写入DuckDB
            duckdb_db.batch_insert_df('factor_values', df)
            
            migrated_count += len(df)
            logger.info(f"  已迁移: {migrated_count}/{total_count} ({migrated_count/total_count*100:.1f}%)")
        
        offset += batch_size
    
    logger.info(f"  迁移完成: {migrated_count}条记录")


def migrate_hold_stock(sqlite_db: DatabaseManager, duckdb_db: DuckDBManager):
    """迁移持仓数据"""
    logger.info("迁移持仓数据...")
    
    sql = "SELECT * FROM hold_stock"
    sqlite_data = sqlite_db.query(sql)
    
    if sqlite_data:
        df = pd.DataFrame(sqlite_data)
        
        # 处理日期格式
        if 'buy_date' in df.columns:
            df['buy_date'] = pd.to_datetime(df['buy_date'], format='%Y%m%d', errors='coerce')
        
        if 'update_time' in df.columns:
            df['update_time'] = pd.to_datetime(df['update_time'], errors='coerce')
        
        # 写入DuckDB
        duckdb_db.batch_insert_df('hold_stock', df)
        logger.info(f"  迁移完成: {len(df)}条记录")
    else:
        logger.warning("  无数据")


def migrate_all():
    """执行完整迁移"""
    logger.info("=" * 80)
    logger.info("开始从SQLite迁移到DuckDB")
    logger.info("=" * 80)
    
    # 1. 初始化
    config = ConfigManager()
    
    sqlite_db = DatabaseManager(config)
    duckdb_db = DuckDBManager(config)
    
    # 2. 迁移数据
    try:
        migrate_stock_basic(sqlite_db, duckdb_db)
        migrate_stock_daily(sqlite_db, duckdb_db)
        migrate_factor_values(sqlite_db, duckdb_db)
        migrate_hold_stock(sqlite_db, duckdb_db)
        
        logger.info("=" * 80)
        logger.info("迁移完成！")
        logger.info("=" * 80)
        
        # 3. 验证数据
        logger.info("\n验证迁移结果...")
        
        # 验证stock_basic
        sqlite_count = sqlite_db.query("SELECT COUNT(*) as total FROM stock_basic")[0]['total']
        duckdb_count = duckdb_db.query("SELECT COUNT(*) as total FROM stock_basic")[0]['total']
        logger.info(f"  stock_basic: SQLite={sqlite_count}, DuckDB={duckdb_count}, {'✓' if sqlite_count == duckdb_count else '✗'}")
        
        # 验证stock_daily
        sqlite_count = sqlite_db.query("SELECT COUNT(*) as total FROM stock_daily")[0]['total']
        duckdb_count = duckdb_db.query("SELECT COUNT(*) as total FROM stock_daily")[0]['total']
        logger.info(f"  stock_daily: SQLite={sqlite_count}, DuckDB={duckdb_count}, {'✓' if sqlite_count == duckdb_count else '✗'}")
        
        # 验证factor_values
        sqlite_count = sqlite_db.query("SELECT COUNT(*) as total FROM factor_values")[0]['total']
        duckdb_count = duckdb_db.query("SELECT COUNT(*) as total FROM factor_values")[0]['total']
        logger.info(f"  factor_values: SQLite={sqlite_count}, DuckDB={duckdb_count}, {'✓' if sqlite_count == duckdb_count else '✗'}")
        
    except Exception as e:
        logger.error(f"迁移失败: {e}")
        raise
    
    finally:
        sqlite_db.close()
        duckdb_db.close()
    
    logger.info("\n迁移成功！现在可以使用DuckDB了。")
    logger.info("请在配置文件中设置: database.type = duckdb")


if __name__ == "__main__":
    migrate_all()
