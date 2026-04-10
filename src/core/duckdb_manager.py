# -*- coding: utf-8 -*-
"""
DuckDB数据库管理器
DuckDB是高性能分析型数据库，比SQLite快5-10倍
支持向量化计算和复杂SQL查询
"""

import pandas as pd
import numpy as np
import os
from typing import Dict, List, Optional, Tuple, Any
from datetime import datetime

try:
    import duckdb
    DUCKDB_AVAILABLE = True
except ImportError:
    DUCKDB_AVAILABLE = False

from src.core.logger import get_logger
from src.core.config import ConfigManager

logger = get_logger("duckdb_manager")


class DuckDBManager:
    """DuckDB数据库管理器"""
    
    def __init__(self, config: ConfigManager = None, db_path: str = None):
        """
        初始化DuckDB管理器
        
        Args:
            config: 配置管理器
            db_path: 数据库路径
        """
        if not DUCKDB_AVAILABLE:
            raise ImportError("DuckDB未安装，请运行: pip install duckdb")
        
        if config is None:
            config = ConfigManager()
        
        self.config = config
        
        if db_path is None:
            db_path = config.get("database.duckdb_path", "data/database/quant_system.duckdb")
        
        self.db_path = db_path
        
        # 确保目录存在
        os.makedirs(os.path.dirname(db_path) or '.', exist_ok=True)
        
        # 连接数据库
        self.conn = duckdb.connect(db_path)
        
        # 创建表
        self._create_tables()
        
        logger.info(f"DuckDB管理器初始化完成: {db_path}")
    
    def _create_tables(self):
        """创建数据表"""
        # 股票日线数据表
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS stock_daily (
                ts_code VARCHAR,
                trade_date DATE,
                open DOUBLE,
                high DOUBLE,
                low DOUBLE,
                close DOUBLE,
                pre_close DOUBLE,
                vol DOUBLE,
                amount DOUBLE,
                pct_chg DOUBLE
            )
        """)
        
        # 创建索引
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_stock_daily_code ON stock_daily(ts_code)")
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_stock_daily_date ON stock_daily(trade_date)")
        
        # 股票基础信息表
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS stock_basic (
                ts_code VARCHAR PRIMARY KEY,
                symbol VARCHAR,
                name VARCHAR,
                area VARCHAR,
                industry VARCHAR,
                market VARCHAR,
                list_date DATE,
                is_st INTEGER,
                update_time TIMESTAMP
            )
        """)
        
        # 因子值表
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS factor_values (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts_code VARCHAR,
                trade_date DATE,
                factor_name VARCHAR,
                factor_value DOUBLE,
                create_time TIMESTAMP,
                UNIQUE(ts_code, trade_date, factor_name)
            )
        """)
        
        # 创建索引
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_factor_values_name ON factor_values(factor_name)")
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_factor_values_date ON factor_values(trade_date)")
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_factor_values_code ON factor_values(ts_code)")
        
        # 持仓表
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS hold_stock (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts_code VARCHAR,
                stock_name VARCHAR,
                buy_price DOUBLE,
                buy_date DATE,
                shares INTEGER,
                target_profit_price DOUBLE,
                stop_loss_price DOUBLE,
                update_time TIMESTAMP
            )
        """)
        
        logger.info("DuckDB数据表创建完成")
    
    def execute(self, sql: str, params: Tuple = None) -> int:
        """
        执行SQL语句（增删改）
        
        Args:
            sql: SQL语句
            params: 参数
        
        Returns:
            影响的行数
        """
        if params:
            result = self.conn.execute(sql, params)
        else:
            result = self.conn.execute(sql)
        
        return result.rowcount
    
    def execute_many(self, sql: str, params_list: List[Tuple]) -> int:
        """
        批量执行SQL语句
        
        Args:
            sql: SQL语句
            params_list: 参数列表
        
        Returns:
            影响的行数
        """
        result = self.conn.executemany(sql, params_list)
        return result.rowcount
    
    def query(self, sql: str, params: Tuple = None) -> List[Dict]:
        """
        查询数据（返回列表）
        
        Args:
            sql: SQL语句
            params: 参数
        
        Returns:
            查询结果列表
        """
        if params:
            result_df = self.conn.execute(sql, params).fetchdf()
        else:
            result_df = self.conn.execute(sql).fetchdf()
        
        return result_df.to_dict('records')
    
    def query_df(self, sql: str, params: Tuple = None) -> pd.DataFrame:
        """
        查询数据（返回DataFrame）
        
        Args:
            sql: SQL语句
            params: 参数
        
        Returns:
            查询结果DataFrame
        """
        if params:
            return self.conn.execute(sql, params).fetchdf()
        else:
            return self.conn.execute(sql).fetchdf()
    
    def batch_insert_df(self, table_name: str, df: pd.DataFrame):
        """
        批量插入DataFrame
        
        Args:
            table_name: 表名
            df: DataFrame
        """
        if df.empty:
            return
        
        # 使用DuckDB的高效插入方式
        self.conn.execute(f"INSERT INTO {table_name} SELECT * FROM df")
        
        logger.info(f"批量插入完成: {table_name}, {len(df)}条记录")
    
    def get_stock_daily(self, ts_code: str, start_date: str = None,
                       end_date: str = None) -> pd.DataFrame:
        """
        获取股票日线数据
        
        Args:
            ts_code: 股票代码
            start_date: 开始日期
            end_date: 结束日期
        
        Returns:
            日线数据DataFrame
        """
        sql = """
            SELECT trade_date, open, close, high, low, vol, amount, pct_chg
            FROM stock_daily
            WHERE ts_code = ?
        """
        params = [ts_code]
        
        if start_date:
            sql += " AND trade_date >= ?"
            params.append(start_date)
        
        if end_date:
            sql += " AND trade_date <= ?"
            params.append(end_date)
        
        sql += " ORDER BY trade_date"
        
        return self.query_df(sql, tuple(params))
    
    def get_all_stocks_daily(self, trade_date: str) -> pd.DataFrame:
        """
        获取指定日期所有股票的日线数据
        
        Args:
            trade_date: 交易日期
        
        Returns:
            日线数据DataFrame
        """
        sql = """
            SELECT ts_code, open, close, high, low, vol, amount, pct_chg
            FROM stock_daily
            WHERE trade_date = ?
        """
        
        return self.query_df(sql, (trade_date,))
    
    def calculate_factor_for_all_stocks(self, trade_date: str, factor_name: str,
                                       window: int = 20) -> pd.DataFrame:
        """
        为所有股票计算指定因子（向量化计算）
        
        Args:
            trade_date: 交易日期
            factor_name: 因子名称
            window: 窗口大小
        
        Returns:
            因子值DataFrame
        """
        # 获取历史数据
        end_dt = datetime.strptime(trade_date, "%Y%m%d")
        start_dt = end_dt - pd.Timedelta(days=window * 2)
        start_date = start_dt.strftime("%Y%m%d")
        
        sql = """
            SELECT ts_code, trade_date, close, vol, pct_chg
            FROM stock_daily
            WHERE trade_date >= ? AND trade_date <= ?
            ORDER BY ts_code, trade_date
        """
        
        df = self.query_df(sql, (start_date, trade_date))
        
        if df.empty:
            return pd.DataFrame()
        
        # 计算因子
        if factor_name == 'ma5':
            result_df = df.groupby('ts_code').apply(
                lambda x: pd.DataFrame({
                    'ts_code': [x.iloc[-1]['ts_code']],
                    'trade_date': [x.iloc[-1]['trade_date']],
                    'factor_value': [x['close'].tail(5).mean()]
                })
            ).reset_index(drop=True)
        elif factor_name == 'ma20':
            result_df = df.groupby('ts_code').apply(
                lambda x: pd.DataFrame({
                    'ts_code': [x.iloc[-1]['ts_code']],
                    'trade_date': [x.iloc[-1]['trade_date']],
                    'factor_value': [x['close'].tail(20).mean()]
                })
            ).reset_index(drop=True)
        elif factor_name == 'volatility':
            result_df = df.groupby('ts_code').apply(
                lambda x: pd.DataFrame({
                    'ts_code': [x.iloc[-1]['ts_code']],
                    'trade_date': [x.iloc[-1]['trade_date']],
                    'factor_value': [x['pct_chg'].tail(20).std()]
                })
            ).reset_index(drop=True)
        else:
            return pd.DataFrame()
        
        # 添加因子名称
        result_df['factor_name'] = factor_name
        
        return result_df
    
    def backup_database(self, backup_path: str = None):
        """
        备份数据库
        
        Args:
            backup_path: 备份路径
        """
        if backup_path is None:
            backup_dir = self.config.get("database.backup_path", "data/database/backup/")
            os.makedirs(backup_dir, exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_path = os.path.join(backup_dir, f"quant_system_duckdb_{timestamp}.duckdb")
        
        # 复制数据库文件
        import shutil
        shutil.copy2(self.db_path, backup_path)
        
        logger.info(f"数据库备份完成: {backup_path}")
    
    def close(self):
        """关闭数据库连接"""
        self.conn.close()
        logger.info("DuckDB连接已关闭")
    
    def __enter__(self):
        """上下文管理器入口"""
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """上下文管理器出口"""
        self.close()


class DuckDBBenchmark:
    """DuckDB性能测试"""
    
    def __init__(self, duckdb_manager: DuckDBManager):
        """
        初始化性能测试
        
        Args:
            duckdb_manager: DuckDB管理器
        """
        self.db = duckdb_manager
    
    def benchmark_query_performance(self, query_name: str, sql: str, params: Tuple = None,
                                   iterations: int = 10) -> Dict:
        """
        测试查询性能
        
        Args:
            query_name: 查询名称
            sql: SQL语句
            params: 参数
            iterations: 迭代次数
        
        Returns:
            性能统计字典
        """
        import time
        
        times = []
        
        for i in range(iterations):
            start_time = time.time()
            self.db.query(sql, params)
            end_time = time.time()
            times.append(end_time - start_time)
        
        return {
            'query_name': query_name,
            'avg_time': np.mean(times),
            'min_time': np.min(times),
            'max_time': np.max(times),
            'std_time': np.std(times),
            'iterations': iterations
        }
    
    def run_benchmark(self):
        """运行性能基准测试"""
        logger.info("=" * 80)
        logger.info("DuckDB性能基准测试")
        logger.info("=" * 80)
        
        # 测试1: 查询单只股票数据
        sql1 = """
            SELECT * FROM stock_daily
            WHERE ts_code = '000001.SZ'
            ORDER BY trade_date DESC
            LIMIT 1000
        """
        result1 = self.benchmark_query_performance("查询单只股票数据", sql1)
        logger.info(f"{result1['query_name']}: 平均 {result1['avg_time']:.4f}秒")
        
        # 测试2: 查询指定日期所有股票
        sql2 = """
            SELECT ts_code, close, vol, amount
            FROM stock_daily
            WHERE trade_date = '20231229'
        """
        result2 = self.benchmark_query_performance("查询指定日期所有股票", sql2)
        logger.info(f"{result2['query_name']}: 平均 {result2['avg_time']:.4f}秒")
        
        # 测试3: 聚合查询
        sql3 = """
            SELECT ts_code, AVG(pct_chg) as avg_return, STD(pct_chg) as std_return
            FROM stock_daily
            WHERE trade_date >= '20230101' AND trade_date <= '20231231'
            GROUP BY ts_code
        """
        result3 = self.benchmark_query_performance("聚合查询", sql3)
        logger.info(f"{result3['query_name']}: 平均 {result3['avg_time']:.4f}秒")
        
        # 测试4: 因子计算
        sql4 = """
            SELECT 
                ts_code,
                AVG(close) OVER (PARTITION BY ts_code ORDER BY trade_date ROWS BETWEEN 19 PRECEDING AND CURRENT ROW) as ma20,
                STD(pct_chg) OVER (PARTITION BY ts_code ORDER BY trade_date ROWS BETWEEN 19 PRECEDING AND CURRENT ROW) as volatility
            FROM stock_daily
            WHERE ts_code = '000001.SZ' AND trade_date >= '20230101'
        """
        result4 = self.benchmark_query_performance("因子计算（窗口函数）", sql4)
        logger.info(f"{result4['query_name']}: 平均 {result4['avg_time']:.4f}秒")
        
        logger.info("=" * 80)


if __name__ == "__main__":
    # 测试代码
    try:
        from src.core.config import ConfigManager
        
        config = ConfigManager()
        db = DuckDBManager(config)
        
        # 运行性能测试
        benchmark = DuckDBBenchmark(db)
        benchmark.run_benchmark()
        
        db.close()
        
    except ImportError as e:
        print(f"错误: {e}")
        print("请安装DuckDB: pip install duckdb")
