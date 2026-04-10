# -*- coding: utf-8 -*-
"""
股票数据访问层
"""

from typing import List, Optional, Dict
from datetime import datetime, timedelta
import pandas as pd

from src.core.logger import get_logger
from src.core.database import DatabaseManager
from src.dao.base_dao import BaseDAO

logger = get_logger("stock_dao")


class StockBasicDAO(BaseDAO):
    """股票基础信息DAO"""
    
    @property
    def table_name(self) -> str:
        return "stock_basic"
    
    def find_by_ts_code(self, ts_code: str) -> Optional[Dict]:
        """根据股票代码查询"""
        sql = "SELECT * FROM stock_basic WHERE ts_code = ?"
        return self.execute_one(sql, (ts_code,))
    
    def find_by_industry(self, industry: str) -> List[Dict]:
        """根据行业查询"""
        sql = "SELECT * FROM stock_basic WHERE industry = ?"
        return self.execute_query(sql, (industry,))
    
    def find_all_main_board(self) -> List[Dict]:
        """查询所有主板股票"""
        sql = """
            SELECT * FROM stock_basic 
            WHERE (ts_code LIKE '600%' OR ts_code LIKE '601%' OR ts_code LIKE '603%' 
                   OR ts_code LIKE '000%' OR ts_code LIKE '001%' OR ts_code LIKE '002%')
        """
        return self.execute_query(sql)
    
    def insert_or_update(self, data: Dict) -> int:
        """插入或更新"""
        sql = """
            INSERT INTO stock_basic (ts_code, symbol, name, industry, list_date)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(ts_code) DO UPDATE SET
                name = excluded.name,
                industry = excluded.industry,
                list_date = excluded.list_date,
                update_time = CURRENT_TIMESTAMP
        """
        return self.execute_update(sql, (
            data.get('ts_code'),
            data.get('symbol'),
            data.get('name'),
            data.get('industry'),
            data.get('list_date')
        ))
    
    def batch_insert(self, df: pd.DataFrame) -> int:
        """批量插入"""
        if df.empty:
            return 0
        
        params_list = [
            (
                row['ts_code'],
                row['symbol'],
                row['name'],
                row.get('industry'),
                row.get('list_date')
            )
            for _, row in df.iterrows()
        ]
        
        sql = """
            INSERT OR REPLACE INTO stock_basic (ts_code, symbol, name, industry, list_date)
            VALUES (?, ?, ?, ?, ?)
        """
        
        return self.db.execute_many(sql, params_list)


class StockDailyDAO(BaseDAO):
    """股票日线数据DAO"""
    
    @property
    def table_name(self) -> str:
        return "stock_daily"
    
    def find_by_code_and_date(
        self, 
        ts_code: str, 
        start_date: str, 
        end_date: str
    ) -> List[Dict]:
        """根据股票代码和日期范围查询"""
        sql = """
            SELECT * FROM stock_daily 
            WHERE ts_code = ? AND trade_date >= ? AND trade_date <= ?
            ORDER BY trade_date
        """
        return self.execute_query(sql, (ts_code, start_date, end_date))
    
    def find_by_date(self, trade_date: str) -> List[Dict]:
        """根据交易日期查询所有股票数据"""
        sql = "SELECT * FROM stock_daily WHERE trade_date = ?"
        return self.execute_query(sql, (trade_date,))
    
    def find_latest_date(self) -> Optional[str]:
        """查询最新交易日期"""
        sql = "SELECT MAX(trade_date) as latest FROM stock_daily"
        result = self.execute_one(sql)
        return result.get('latest') if result else None
    
    def get_dataframe(
        self, 
        ts_code: str, 
        start_date: str, 
        end_date: str
    ) -> pd.DataFrame:
        """获取DataFrame格式的数据"""
        sql = """
            SELECT trade_date, open, close, high, low, vol, amount, pct_chg
            FROM stock_daily
            WHERE ts_code = ? AND trade_date >= ? AND trade_date <= ?
            ORDER BY trade_date
        """
        return self.db.query_to_dataframe(sql, (ts_code, start_date, end_date))
    
    def batch_insert(self, df: pd.DataFrame) -> int:
        """批量插入"""
        if df.empty:
            return 0
        
        params_list = [
            (
                row['ts_code'],
                row['trade_date'],
                row.get('open'),
                row.get('close'),
                row.get('high'),
                row.get('low'),
                row.get('vol'),
                row.get('amount'),
                row.get('pct_chg')
            )
            for _, row in df.iterrows()
        ]
        
        sql = """
            INSERT OR REPLACE INTO stock_daily 
            (ts_code, trade_date, open, close, high, low, vol, amount, pct_chg)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        
        return self.db.execute_many(sql, params_list)


class SignalHistoryDAO(BaseDAO):
    """信号历史DAO"""
    
    @property
    def table_name(self) -> str:
        return "signal_history"
    
    def find_by_code(self, ts_code: str, limit: int = 100) -> List[Dict]:
        """根据股票代码查询信号历史"""
        sql = """
            SELECT * FROM signal_history 
            WHERE ts_code = ?
            ORDER BY signal_time DESC
            LIMIT ?
        """
        return self.execute_query(sql, (ts_code, limit))
    
    def find_unpushed(self) -> List[Dict]:
        """查询未推送的信号"""
        sql = "SELECT * FROM signal_history WHERE push_status = 0"
        return self.execute_query(sql)
    
    def mark_pushed(self, id: int) -> int:
        """标记为已推送"""
        sql = "UPDATE signal_history SET push_status = 1 WHERE id = ?"
        return self.execute_update(sql, (id,))
    
    def insert(self, data: Dict) -> int:
        """插入信号记录"""
        sql = """
            INSERT INTO signal_history 
            (ts_code, name, signal_type, signal_time, trigger_reason, suggestion)
            VALUES (?, ?, ?, ?, ?, ?)
        """
        return self.execute_update(sql, (
            data.get('ts_code'),
            data.get('name'),
            data.get('signal_type'),
            data.get('signal_time'),
            data.get('trigger_reason'),
            data.get('suggestion')
        ))


class HoldStockDAO(BaseDAO):
    """持仓股票DAO"""
    
    @property
    def table_name(self) -> str:
        return "hold_stock"
    
    def find_active(self) -> List[Dict]:
        """查询活跃持仓"""
        sql = "SELECT * FROM hold_stock WHERE status = 1"
        return self.execute_query(sql)
    
    def find_by_code(self, ts_code: str) -> Optional[Dict]:
        """根据股票代码查询"""
        sql = "SELECT * FROM hold_stock WHERE ts_code = ?"
        return self.execute_one(sql, (ts_code,))
    
    def insert_or_update(self, data: Dict) -> int:
        """插入或更新持仓"""
        sql = """
            INSERT INTO hold_stock 
            (ts_code, name, hold_price, hold_num, target_profit, target_stop, hold_date)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(ts_code) DO UPDATE SET
                hold_price = excluded.hold_price,
                hold_num = excluded.hold_num,
                target_profit = excluded.target_profit,
                target_stop = excluded.target_stop,
                status = 1,
                update_time = CURRENT_TIMESTAMP
        """
        return self.execute_update(sql, (
            data.get('ts_code'),
            data.get('name'),
            data.get('hold_price'),
            data.get('hold_num'),
            data.get('target_profit'),
            data.get('target_stop'),
            data.get('hold_date')
        ))
    
    def update_status(self, ts_code: str, status: int) -> int:
        """更新状态"""
        sql = "UPDATE hold_stock SET status = ? WHERE ts_code = ?"
        return self.execute_update(sql, (status, ts_code))
    
    def delete(self, ts_code: str) -> int:
        """删除持仓"""
        sql = "DELETE FROM hold_stock WHERE ts_code = ?"
        return self.execute_update(sql, (ts_code,))
