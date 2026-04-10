# -*- coding: utf-8 -*-
"""
数据访问层基类
"""

from typing import List, Optional, Dict, Any
from abc import ABC, abstractmethod

from src.core.logger import get_logger
from src.core.database import DatabaseManager

logger = get_logger("dao_base")


class BaseDAO(ABC):
    """数据访问层基类"""
    
    def __init__(self, db: DatabaseManager = None):
        if db is None:
            db = DatabaseManager()
        self.db = db
    
    @property
    @abstractmethod
    def table_name(self) -> str:
        """表名"""
        pass
    
    def find_by_id(self, id: int) -> Optional[Dict]:
        """根据ID查询"""
        sql = f"SELECT * FROM {self.table_name} WHERE id = ?"
        return self.db.query_one(sql, (id,))
    
    def find_all(self, limit: int = 1000) -> List[Dict]:
        """查询所有记录"""
        sql = f"SELECT * FROM {self.table_name} LIMIT ?"
        return self.db.query(sql, (limit,))
    
    def count(self) -> int:
        """统计记录数"""
        return self.db.get_table_count(self.table_name)
    
    def delete_by_id(self, id: int) -> int:
        """根据ID删除"""
        sql = f"DELETE FROM {self.table_name} WHERE id = ?"
        return self.db.execute(sql, (id,))
    
    def execute_query(self, sql: str, params: tuple = None) -> List[Dict]:
        """执行查询"""
        return self.db.query(sql, params)
    
    def execute_one(self, sql: str, params: tuple = None) -> Optional[Dict]:
        """执行查询返回单条"""
        return self.db.query_one(sql, params)
    
    def execute_update(self, sql: str, params: tuple = None) -> int:
        """执行更新"""
        return self.db.execute(sql, params)
