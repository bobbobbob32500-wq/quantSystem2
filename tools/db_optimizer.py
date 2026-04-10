# -*- coding: utf-8 -*-
"""
数据库优化脚本
添加索引以提升查询性能
"""

import sqlite3
import os
import sys
from pathlib import Path

# 确保可从项目根目录导入 src 包
project_root = Path(__file__).resolve().parents[1]
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from src.core.logger import get_logger
from src.core.config import ConfigManager

logger = get_logger("db_optimizer")


class DatabaseOptimizer:
    """数据库优化器"""
    
    def __init__(self, db_path: str):
        self.db_path = db_path
        self.conn = None
    
    def connect(self):
        """连接数据库"""
        if not os.path.exists(self.db_path):
            logger.warning(f"数据库文件不存在: {self.db_path}")
            return False
        
        try:
            self.conn = sqlite3.connect(self.db_path)
            logger.info(f"数据库连接成功: {self.db_path}")
            return True
        except Exception as e:
            logger.error(f"数据库连接失败: {e}")
            return False
    
    def close(self):
        """关闭连接"""
        if self.conn:
            self.conn.close()
    
    def _table_exists(self, table_name: str) -> bool:
        """检查表是否存在"""
        if not self.conn:
            return False

        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (table_name,),
        )
        return cursor.fetchone() is not None

    def _get_table_columns(self, table_name: str):
        """获取表字段列表"""
        if not self.conn:
            return set()

        cursor = self.conn.cursor()
        cursor.execute(f"PRAGMA table_info({table_name})")
        return {row[1] for row in cursor.fetchall()}

    def create_indexes(self):
        """创建索引（根据实际表结构自适应）"""
        if not self.conn:
            logger.error("数据库未连接")
            return False

        index_candidates = [
            {
                "table": "stock_daily",
                "name": "idx_stock_daily_ts_code_date",
                "column_options": [["ts_code", "trade_date"]],
            },
            {
                "table": "index_daily",
                "name": "idx_index_daily_code_date",
                "column_options": [["ts_code", "trade_date"]],
            },
            {
                "table": "factor_values",
                "name": "idx_factor_values_code_date",
                "column_options": [["ts_code", "trade_date"], ["symbol", "calc_date"]],
            },
            {
                "table": "signal_history",
                "name": "idx_signal_history_code_time",
                "column_options": [["ts_code", "signal_time"], ["ts_code", "signal_date"]],
            },
            {
                "table": "trade_log",
                "name": "idx_trade_log_code_time",
                "column_options": [["ts_code", "trade_time"], ["ts_code", "trade_date"]],
            },
            {
                "table": "hold_stock",
                "name": "idx_hold_stock_ts_code",
                "column_options": [["ts_code"]],
            },
        ]

        cursor = self.conn.cursor()
        success_count = 0

        for item in index_candidates:
            table_name = item["table"]
            if not self._table_exists(table_name):
                logger.warning(f"表不存在，跳过索引创建: {table_name}")
                continue

            existing_columns = self._get_table_columns(table_name)
            selected_columns = None
            for columns in item["column_options"]:
                if all(col in existing_columns for col in columns):
                    selected_columns = columns
                    break

            if selected_columns is None:
                logger.warning(
                    f"表字段不匹配，跳过索引创建: {table_name}, 可用字段: {sorted(existing_columns)}"
                )
                continue

            try:
                column_sql = ", ".join(
                    f"{col} DESC" if col.endswith("date") or col.endswith("time") else col
                    for col in selected_columns
                )
                index_sql = (
                    f"CREATE INDEX IF NOT EXISTS {item['name']} "
                    f"ON {table_name}({column_sql})"
                )
                cursor.execute(index_sql)
                self.conn.commit()
                logger.info(
                    f"索引创建成功: {item['name']} ({table_name}: {', '.join(selected_columns)})"
                )
                success_count += 1
            except Exception as e:
                logger.warning(f"索引创建失败 {item['name']}: {e}")

        logger.info(f"共创建 {success_count} 个索引")
        return success_count > 0
    
    def analyze_tables(self):
        """分析表以优化查询计划"""
        if not self.conn:
            logger.error("数据库未连接")
            return False
        
        try:
            cursor = self.conn.cursor()
            cursor.execute("ANALYZE")
            self.conn.commit()
            logger.info("表分析完成")
            return True
        except Exception as e:
            logger.error(f"表分析失败: {e}")
            return False
    
    def vacuum(self):
        """清理数据库"""
        if not self.conn:
            logger.error("数据库未连接")
            return False
        
        try:
            cursor = self.conn.cursor()
            cursor.execute("VACUUM")
            self.conn.commit()
            logger.info("数据库清理完成")
            return True
        except Exception as e:
            logger.error(f"数据库清理失败: {e}")
            return False
    
    def get_index_info(self):
        """获取索引信息"""
        if not self.conn:
            logger.error("数据库未连接")
            return []
        
        try:
            cursor = self.conn.cursor()
            cursor.execute(
                "SELECT name, tbl_name FROM sqlite_master WHERE type='index' AND name NOT LIKE 'sqlite_%'"
            )
            indexes = cursor.fetchall()
            return indexes
        except Exception as e:
            logger.error(f"获取索引信息失败: {e}")
            return []
    
    def optimize_all(self):
        """执行所有优化操作"""
        logger.info("开始数据库优化...")
        
        if not self.connect():
            return False
        
        try:
            # 1. 创建索引
            self.create_indexes()
            
            # 2. 分析表
            self.analyze_tables()
            
            # 3. 清理数据库
            self.vacuum()
            
            # 4. 显示索引信息
            indexes = self.get_index_info()
            logger.info(f"数据库中共有 {len(indexes)} 个索引")
            for idx_name, tbl_name in indexes:
                logger.info(f"  - {idx_name} (表: {tbl_name})")
            
            logger.info("数据库优化完成")
            return True
        finally:
            self.close()


def main():
    """主函数"""
    config = ConfigManager()
    db_path = config.get("database.path", "data/database/quant_system.db")

    # 转换为绝对路径（以项目根目录为基准）
    if not os.path.isabs(db_path):
        project_root = Path(__file__).resolve().parents[1]
        db_path = str(project_root / db_path)

    optimizer = DatabaseOptimizer(db_path)
    optimizer.optimize_all()


if __name__ == "__main__":
    main()
