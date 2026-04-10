# -*- coding: utf-8 -*-
"""
数据库管理模块
基于SQLite实现本地数据存储
优化版本：支持上下文管理器、批量查询、连接池
"""

import os
import sqlite3
from datetime import datetime, timedelta
from typing import List, Optional, Tuple, Dict, Any, Generator
from contextlib import contextmanager
import threading
import pandas as pd

from src.core.logger import get_logger
from src.core.config import ConfigManager
from src.core.exceptions import DatabaseException

logger = get_logger("database")


class ConnectionPool:
    """简易数据库连接池"""
    
    def __init__(self, db_path: str, pool_size: int = 5):
        self.db_path = db_path
        self.pool_size = pool_size
        self._pool: List[sqlite3.Connection] = []
        self._lock = threading.Lock()
    
    def get_connection(self) -> sqlite3.Connection:
        """获取连接"""
        with self._lock:
            if self._pool:
                conn = self._pool.pop()
                try:
                    conn.execute("SELECT 1")
                    return conn
                except sqlite3.Error:
                    pass
            
            conn = sqlite3.connect(self.db_path, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            return conn
    
    def return_connection(self, conn: sqlite3.Connection):
        """归还连接"""
        with self._lock:
            if len(self._pool) < self.pool_size:
                self._pool.append(conn)
            else:
                conn.close()
    
    def close_all(self):
        """关闭所有连接"""
        with self._lock:
            for conn in self._pool:
                try:
                    conn.close()
                except:
                    pass
            self._pool.clear()


class DatabaseManager:
    """数据库管理器 - 优化版

    说明：
    - 严禁全局单例/全局缓存：会导致多库场景串库污染（看板临时库影响主库）。
    - 实盘级要求：每个 DatabaseManager 实例必须与其 db_path 强绑定，互不影响。
    """
    
    def __init__(self, config: ConfigManager = None, db_path: str | None = None):
        if config is None:
            config = ConfigManager()
        
        self.config = config
        self.db_path = self._get_db_path(override_path=db_path)
        self._ensure_db_dir()
        self._connection_pool = ConnectionPool(self.db_path)
        self._init_database()
    
    def _get_db_path(self, override_path: str | None = None) -> str:
        """获取数据库文件路径"""
        db_path = override_path or self.config.get("database.path", "data/database/quant_system.db")
        if not os.path.isabs(db_path):
            db_path = os.path.join(
                os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
                db_path
            )
        return db_path
    
    def _ensure_db_dir(self):
        """确保数据库目录存在"""
        db_dir = os.path.dirname(self.db_path)
        os.makedirs(db_dir, exist_ok=True)
    
    @contextmanager
    def get_connection(self) -> Generator[sqlite3.Connection, None, None]:
        """获取数据库连接（上下文管理器）"""
        conn = self._connection_pool.get_connection()
        try:
            yield conn
        finally:
            self._connection_pool.return_connection(conn)
    
    def _get_connection(self) -> sqlite3.Connection:
        """获取数据库连接（兼容旧代码）"""
        return self._connection_pool.get_connection()
    
    def _init_database(self):
        """初始化数据库，创建所有表"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            try:
                cursor.execute("PRAGMA journal_mode=WAL")
                cursor.execute("PRAGMA busy_timeout=5000")
                self._create_tables(cursor)
                self._create_indexes(cursor)
                conn.commit()
                logger.info(f"数据库初始化完成: {self.db_path} (WAL模式)")
            except Exception as e:
                conn.rollback()
                logger.error(f"数据库初始化失败: {e}")
                raise DatabaseException(f"数据库初始化失败: {e}")
    
    def _create_tables(self, cursor):
        """创建所有表"""
        tables = {
            'stock_basic': """
                CREATE TABLE IF NOT EXISTS stock_basic (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts_code TEXT UNIQUE NOT NULL,
                    symbol TEXT NOT NULL,
                    name TEXT NOT NULL,
                    industry TEXT,
                    list_date TEXT,
                    create_time TEXT DEFAULT CURRENT_TIMESTAMP,
                    update_time TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """,
            'stock_daily': """
                CREATE TABLE IF NOT EXISTS stock_daily (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts_code TEXT NOT NULL,
                    trade_date TEXT NOT NULL,
                    open REAL,
                    close REAL,
                    high REAL,
                    low REAL,
                    vol REAL,
                    amount REAL,
                    pct_chg REAL,
                    create_time TEXT DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(ts_code, trade_date)
                )
            """,
            'block_data': """
                CREATE TABLE IF NOT EXISTS block_data (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    block_name TEXT NOT NULL,
                    block_type TEXT NOT NULL,
                    ts_code TEXT NOT NULL,
                    block_rise REAL,
                    trade_date TEXT,
                    create_time TEXT DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(block_name, ts_code, trade_date)
                )
            """,
            'north_money': """
                CREATE TABLE IF NOT EXISTS north_money (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    trade_date TEXT NOT NULL,
                    market_north REAL,
                    ts_code TEXT,
                    stock_north REAL,
                    create_time TEXT DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(trade_date, ts_code)
                )
            """,
            'hold_stock': """
                CREATE TABLE IF NOT EXISTS hold_stock (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts_code TEXT UNIQUE NOT NULL,
                    name TEXT NOT NULL,
                    hold_price REAL NOT NULL,
                    hold_num INTEGER NOT NULL,
                    target_profit REAL,
                    target_stop REAL,
                    hold_date TEXT,
                    status INTEGER DEFAULT 1,
                    create_time TEXT DEFAULT CURRENT_TIMESTAMP,
                    update_time TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """,
            'signal_history': """
                CREATE TABLE IF NOT EXISTS signal_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts_code TEXT NOT NULL,
                    name TEXT,
                    signal_type TEXT NOT NULL,
                    signal_time TEXT NOT NULL,
                    trigger_reason TEXT,
                    suggestion TEXT,
                    push_status INTEGER DEFAULT 0,
                    create_time TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """,
            'trade_log': """
                CREATE TABLE IF NOT EXISTS trade_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts_code TEXT NOT NULL,
                    name TEXT,
                    trade_type TEXT NOT NULL,
                    trade_price REAL NOT NULL,
                    trade_num INTEGER NOT NULL,
                    trade_time TEXT NOT NULL,
                    profit REAL,
                    remark TEXT,
                    create_time TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """,
            'system_log': """
                CREATE TABLE IF NOT EXISTS system_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    log_time TEXT NOT NULL,
                    log_level TEXT NOT NULL,
                    module_name TEXT,
                    log_content TEXT,
                    create_time TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """,
            'factor_values': """
                CREATE TABLE IF NOT EXISTS factor_values (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts_code TEXT NOT NULL,
                    trade_date TEXT NOT NULL,
                    factor_name TEXT NOT NULL,
                    factor_value REAL,
                    create_time TEXT DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(ts_code, trade_date, factor_name)
                )
            """,
            'stock_chip_perf': """
                CREATE TABLE IF NOT EXISTS stock_chip_perf (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts_code TEXT NOT NULL,
                    trade_date TEXT NOT NULL,
                    cost_5pct REAL,
                    cost_15pct REAL,
                    cost_50pct REAL,
                    cost_85pct REAL,
                    cost_95pct REAL,
                    weight_avg REAL,
                    winner_rate REAL,
                    create_time TEXT DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(ts_code, trade_date)
                )
            """,
            'stock_chip_dist': """
                CREATE TABLE IF NOT EXISTS stock_chip_dist (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts_code TEXT NOT NULL,
                    trade_date TEXT NOT NULL,
                    price REAL NOT NULL,
                    weight REAL NOT NULL,
                    create_time TEXT DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(ts_code, trade_date, price)
                )
            """,
            'task_execution_log': """
                CREATE TABLE IF NOT EXISTS task_execution_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    start_time TEXT,
                    end_time TEXT,
                    duration_ms INTEGER,
                    error_message TEXT,
                    create_time TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """
        }
        
        for table_name, sql in tables.items():
            cursor.execute(sql)
    
    def _create_indexes(self, cursor):
        """创建索引"""
        indexes = [
            "CREATE INDEX IF NOT EXISTS idx_stock_daily_code ON stock_daily(ts_code)",
            "CREATE INDEX IF NOT EXISTS idx_stock_daily_date ON stock_daily(trade_date)",
            "CREATE INDEX IF NOT EXISTS idx_stock_daily_code_date ON stock_daily(ts_code, trade_date)",
            "CREATE INDEX IF NOT EXISTS idx_north_money_date ON north_money(trade_date)",
            "CREATE INDEX IF NOT EXISTS idx_signal_history_code ON signal_history(ts_code)",
            "CREATE INDEX IF NOT EXISTS idx_signal_history_time ON signal_history(signal_time)",
            "CREATE INDEX IF NOT EXISTS idx_trade_log_code ON trade_log(ts_code)",
            "CREATE INDEX IF NOT EXISTS idx_trade_log_time ON trade_log(trade_time)",
            "CREATE INDEX IF NOT EXISTS idx_system_log_time ON system_log(log_time)",
            "CREATE INDEX IF NOT EXISTS idx_factor_values_code ON factor_values(ts_code)",
            "CREATE INDEX IF NOT EXISTS idx_factor_values_date ON factor_values(trade_date)",
            "CREATE INDEX IF NOT EXISTS idx_factor_values_name ON factor_values(factor_name)",
            "CREATE INDEX IF NOT EXISTS idx_stock_chip_perf_code ON stock_chip_perf(ts_code)",
            "CREATE INDEX IF NOT EXISTS idx_stock_chip_perf_date ON stock_chip_perf(trade_date)",
            "CREATE INDEX IF NOT EXISTS idx_stock_chip_perf_code_date ON stock_chip_perf(ts_code, trade_date)",
            "CREATE INDEX IF NOT EXISTS idx_stock_chip_dist_code ON stock_chip_dist(ts_code)",
            "CREATE INDEX IF NOT EXISTS idx_stock_chip_dist_date ON stock_chip_dist(trade_date)",
            "CREATE INDEX IF NOT EXISTS idx_stock_chip_dist_code_date ON stock_chip_dist(ts_code, trade_date)",
        ]
        
        for index_sql in indexes:
            cursor.execute(index_sql)
    
    def execute(self, sql: str, params: tuple = None) -> int:
        """执行SQL语句（INSERT/UPDATE/DELETE），带写重试"""
        max_retries = 3
        for attempt in range(max_retries):
            with self.get_connection() as conn:
                cursor = conn.cursor()
                try:
                    if params:
                        cursor.execute(sql, params)
                    else:
                        cursor.execute(sql)
                    conn.commit()
                    return cursor.rowcount
                except sqlite3.OperationalError as e:
                    if "locked" in str(e).lower() and attempt < max_retries - 1:
                        conn.rollback()
                        import time as _time
                        _time.sleep(0.5 * (attempt + 1))
                        logger.warning(f"数据库锁定，重试 {attempt + 1}/{max_retries}: {sql}")
                        continue
                    conn.rollback()
                    logger.error(f"SQL执行失败: {sql}, 错误: {e}")
                    raise DatabaseException(f"SQL执行失败: {e}")
                except Exception as e:
                    conn.rollback()
                    logger.error(f"SQL执行失败: {sql}, 错误: {e}")
                    raise DatabaseException(f"SQL执行失败: {e}")
        return 0
    
    def execute_many(self, sql: str, params_list: List[tuple]) -> int:
        """批量执行SQL语句"""
        if not params_list:
            return 0
        
        with self.get_connection() as conn:
            cursor = conn.cursor()
            try:
                cursor.executemany(sql, params_list)
                conn.commit()
                return cursor.rowcount
            except Exception as e:
                conn.rollback()
                logger.error(f"批量SQL执行失败: {sql}, 错误: {e}")
                raise DatabaseException(f"批量SQL执行失败: {e}")
    
    def query(self, sql: str, params: tuple = None) -> List[dict]:
        """查询数据"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            try:
                if params:
                    cursor.execute(sql, params)
                else:
                    cursor.execute(sql)
                rows = cursor.fetchall()
                return [dict(row) for row in rows]
            except Exception as e:
                logger.error(f"SQL查询失败: {sql}, 错误: {e}")
                raise DatabaseException(f"SQL查询失败: {e}")
    
    def query_one(self, sql: str, params: tuple = None) -> Optional[dict]:
        """查询单条数据"""
        results = self.query(sql, params)
        return results[0] if results else None
    
    def query_to_dataframe(self, sql: str, params: tuple = None) -> pd.DataFrame:
        """查询数据并返回DataFrame"""
        with self.get_connection() as conn:
            try:
                return pd.read_sql_query(sql, conn, params=params)
            except Exception as e:
                logger.error(f"SQL查询失败: {sql}, 错误: {e}")
                raise DatabaseException(f"SQL查询失败: {e}")
    
    def get_batch_daily_data(
        self, 
        ts_codes: List[str], 
        start_date: str, 
        end_date: str
    ) -> Dict[str, pd.DataFrame]:
        """
        批量获取多只股票的日线数据（优化版）
        
        Args:
            ts_codes: 股票代码列表
            start_date: 开始日期 YYYYMMDD
            end_date: 结束日期 YYYYMMDD
        
        Returns:
            {ts_code: DataFrame} 字典
        """
        if not ts_codes:
            return {}
        
        placeholders = ','.join(['?'] * len(ts_codes))
        sql = f"""
            SELECT ts_code, trade_date, open, close, high, low, vol, amount, pct_chg
            FROM stock_daily
            WHERE ts_code IN ({placeholders})
            AND trade_date >= ? AND trade_date <= ?
            ORDER BY ts_code, trade_date
        """
        
        params = tuple(ts_codes) + (start_date, end_date)
        
        with self.get_connection() as conn:
            try:
                df = pd.read_sql_query(sql, conn, params=params)
                
                if df.empty:
                    return {}
                
                result = {}
                for ts_code, group in df.groupby('ts_code'):
                    group = group.sort_values('trade_date').reset_index(drop=True)
                    result[ts_code] = group
                
                logger.info(f"批量查询日线数据: {len(ts_codes)}只股票, 返回{len(result)}只")
                return result
            except Exception as e:
                logger.error(f"批量查询日线数据失败: {e}")
                raise DatabaseException(f"批量查询日线数据失败: {e}")
    
    def get_batch_daily_data_by_date(
        self,
        trade_date: str,
        ts_codes: List[str] = None
    ) -> pd.DataFrame:
        """
        批量获取某日所有股票数据
        
        Args:
            trade_date: 交易日期 YYYYMMDD
            ts_codes: 股票代码列表（可选，为空则获取全部）
        
        Returns:
            DataFrame
        """
        if ts_codes:
            placeholders = ','.join(['?'] * len(ts_codes))
            sql = f"""
                SELECT ts_code, trade_date, open, close, high, low, vol, amount, pct_chg
                FROM stock_daily
                WHERE trade_date = ? AND ts_code IN ({placeholders})
            """
            params = (trade_date,) + tuple(ts_codes)
        else:
            sql = """
                SELECT ts_code, trade_date, open, close, high, low, vol, amount, pct_chg
                FROM stock_daily
                WHERE trade_date = ?
            """
            params = (trade_date,)
        
        return self.query_to_dataframe(sql, params)
    
    def get_table_count(self, table_name: str) -> int:
        """获取表记录数"""
        sql = f"SELECT COUNT(*) as count FROM {table_name}"
        result = self.query_one(sql)
        return result["count"] if result else 0
    
    def get_latest_trade_date(self, table_name: str = "stock_daily") -> Optional[str]:
        """获取最新交易日期"""
        sql = f"SELECT MAX(trade_date) as latest_date FROM {table_name}"
        result = self.query_one(sql)
        return result["latest_date"] if result else None
    
    def get_trade_dates(
        self, 
        start_date: str, 
        end_date: str
    ) -> List[str]:
        """获取交易日期列表"""
        sql = """
            SELECT DISTINCT trade_date 
            FROM stock_daily 
            WHERE trade_date >= ? AND trade_date <= ?
            ORDER BY trade_date
        """
        results = self.query(sql, (start_date, end_date))
        return [r['trade_date'] for r in results]
    
    def backup_database(self) -> str:
        """备份数据库"""
        backup_dir = self.config.get("database.backup_path", "data/database/backup/")
        if not os.path.isabs(backup_dir):
            backup_dir = os.path.join(
                os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
                backup_dir
            )
        os.makedirs(backup_dir, exist_ok=True)
        
        backup_file = os.path.join(
            backup_dir,
            f"quant_system_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
        )
        
        with self.get_connection() as source_conn:
            dest_conn = sqlite3.connect(backup_file)
            try:
                source_conn.backup(dest_conn)
                logger.info(f"数据库备份成功: {backup_file}")
                return backup_file
            except Exception as e:
                logger.error(f"数据库备份失败: {e}")
                raise DatabaseException(f"数据库备份失败: {e}")
            finally:
                dest_conn.close()
    
    def clean_old_backups(self, keep_days: int = 30):
        """清理旧备份文件"""
        backup_dir = self.config.get("database.backup_path", "data/database/backup/")
        if not os.path.isabs(backup_dir):
            backup_dir = os.path.join(
                os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
                backup_dir
            )
        
        if not os.path.exists(backup_dir):
            return
        
        import time
        current_time = time.time()
        cutoff_time = current_time - (keep_days * 24 * 60 * 60)
        
        for filename in os.listdir(backup_dir):
            filepath = os.path.join(backup_dir, filename)
            if os.path.isfile(filepath):
                file_mtime = os.path.getmtime(filepath)
                if file_mtime < cutoff_time:
                    os.remove(filepath)
                    logger.info(f"删除旧备份: {filename}")
    
    def close(self):
        """关闭连接池"""
        self._connection_pool.close_all()
        logger.info("数据库连接池已关闭")
