# -*- coding: utf-8 -*-
"""
因子缓存模块
提供因子值的缓存和增量计算功能
"""

import pandas as pd
import numpy as np
import pickle
import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

from src.core.logger import get_logger
from src.core.database import DatabaseManager
from src.core.config import ConfigManager

logger = get_logger("factor_cache")


class FactorCache:
    """因子缓存管理器"""
    
    def __init__(self, cache_dir: str = 'data/cache/factors'):
        """
        初始化因子缓存
        
        Args:
            cache_dir: 缓存目录
        """
        self.cache_dir = cache_dir
        os.makedirs(cache_dir, exist_ok=True)
        logger.info(f"因子缓存目录: {cache_dir}")
    
    def get_cache_key(self, ts_code: str, trade_date: str, factor_name: str) -> str:
        """
        生成缓存键
        
        Args:
            ts_code: 股票代码
            trade_date: 交易日期
            factor_name: 因子名称
        
        Returns:
            缓存键
        """
        return f"{ts_code}_{trade_date}_{factor_name}.pkl"
    
    def get_factor(self, ts_code: str, trade_date: str, factor_name: str) -> Optional[float]:
        """
        获取缓存因子
        
        Args:
            ts_code: 股票代码
            trade_date: 交易日期
            factor_name: 因子名称
        
        Returns:
            因子值，如果不存在则返回None
        """
        cache_key = self.get_cache_key(ts_code, trade_date, factor_name)
        cache_path = os.path.join(self.cache_dir, cache_key)
        
        if os.path.exists(cache_path):
            try:
                with open(cache_path, 'rb') as f:
                    return pickle.load(f)
            except Exception as e:
                logger.warning(f"读取缓存失败: {cache_path}, 错误: {e}")
        
        return None
    
    def set_factor(self, ts_code: str, trade_date: str, factor_name: str, value: float):
        """
        设置缓存因子
        
        Args:
            ts_code: 股票代码
            trade_date: 交易日期
            factor_name: 因子名称
            value: 因子值
        """
        cache_key = self.get_cache_key(ts_code, trade_date, factor_name)
        cache_path = os.path.join(self.cache_dir, cache_key)
        
        try:
            with open(cache_path, 'wb') as f:
                pickle.dump(value, f)
        except Exception as e:
            logger.warning(f"写入缓存失败: {cache_path}, 错误: {e}")
    
    def clear_cache(self, before_date: str = None):
        """
        清理缓存
        
        Args:
            before_date: 清理指定日期之前的缓存，None表示清理全部
        """
        cleared_count = 0
        
        for filename in os.listdir(self.cache_dir):
            if before_date is None:
                # 清理所有缓存
                os.remove(os.path.join(self.cache_dir, filename))
                cleared_count += 1
            else:
                # 清理指定日期之前的缓存
                try:
                    date_str = filename.split('_')[1]
                    if date_str < before_date:
                        os.remove(os.path.join(self.cache_dir, filename))
                        cleared_count += 1
                except:
                    continue
        
        logger.info(f"清理缓存完成，共清理 {cleared_count} 个文件")


class IncrementalFactorCalculator:
    """增量因子计算器"""
    
    def __init__(self, db: DatabaseManager, cache: FactorCache = None):
        """
        初始化增量计算器
        
        Args:
            db: 数据库管理器
            cache: 因子缓存
        """
        self.db = db
        self.cache = cache or FactorCache()
        logger.info("增量因子计算器初始化完成")
    
    def calculate_factor_incremental(self, ts_code: str, trade_date: str,
                                    factor_name: str, window: int = 20) -> Optional[float]:
        """
        增量计算因子
        
        Args:
            ts_code: 股票代码
            trade_date: 交易日期
            factor_name: 因子名称
            window: 窗口大小
        
        Returns:
            因子值
        """
        # 1. 检查缓存
        cached_value = self.cache.get_factor(ts_code, trade_date, factor_name)
        if cached_value is not None:
            return cached_value
        
        # 2. 获取历史数据
        sql = """
            SELECT trade_date, close, high, low, vol, amount, pct_chg
            FROM stock_daily
            WHERE ts_code = ? AND trade_date <= ?
            ORDER BY trade_date DESC
            LIMIT ?
        """
        data = self.db.query(sql, (ts_code, trade_date, window))
        
        if len(data) < window:
            return None
        
        # 3. 计算因子
        factor_value = self._calculate_factor(data, factor_name)
        
        if factor_value is not None:
            # 4. 写入缓存
            self.cache.set_factor(ts_code, trade_date, factor_name, factor_value)
        
        return factor_value
    
    def _calculate_factor(self, data: List[Dict], factor_name: str) -> Optional[float]:
        """
        计算因子
        
        Args:
            data: 历史数据列表
            factor_name: 因子名称
        
        Returns:
            因子值
        """
        df = pd.DataFrame(data)
        df = df.sort_values('trade_date').reset_index(drop=True)
        
        if factor_name == 'ma5':
            return df['close'].rolling(5).mean().iloc[-1]
        elif factor_name == 'ma10':
            return df['close'].rolling(10).mean().iloc[-1]
        elif factor_name == 'ma20':
            return df['close'].rolling(20).mean().iloc[-1]
        elif factor_name == 'ma60':
            return df['close'].rolling(60).mean().iloc[-1] if len(df) >= 60 else None
        elif factor_name == 'volatility':
            if len(df) >= 20:
                return df['pct_chg'].tail(20).std()
            return None
        elif factor_name == 'volume_ma20':
            return df['vol'].rolling(20).mean().iloc[-1]
        else:
            return None
    
    def batch_calculate_factors(self, ts_codes: List[str], trade_date: str,
                               factor_names: List[str]) -> pd.DataFrame:
        """
        批量计算因子
        
        Args:
            ts_codes: 股票代码列表
            trade_date: 交易日期
            factor_names: 因子名称列表
        
        Returns:
            因子值DataFrame
        """
        results = []
        
        for ts_code in ts_codes:
            row = {'ts_code': ts_code, 'trade_date': trade_date}
            
            for factor_name in factor_names:
                factor_value = self.calculate_factor_incremental(
                    ts_code, trade_date, factor_name
                )
                row[factor_name] = factor_value
            
            results.append(row)
        
        return pd.DataFrame(results)


class FactorValueStorage:
    """因子值存储管理器"""
    
    def __init__(self, db: DatabaseManager):
        """
        初始化因子值存储
        
        Args:
            db: 数据库管理器
        """
        self.db = db
        self._create_tables()
        logger.info("因子值存储管理器初始化完成")
    
    def _create_tables(self):
        """创建数据表"""
        # 创建factor_values表
        sql = """
            CREATE TABLE IF NOT EXISTS factor_values (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts_code TEXT,
                trade_date TEXT,
                factor_name TEXT,
                factor_value REAL,
                create_time TEXT,
                UNIQUE(ts_code, trade_date, factor_name)
            )
        """
        self.db.execute(sql)
        
        # 创建索引
        indexes = [
            "CREATE INDEX IF NOT EXISTS idx_factor_values_name ON factor_values(factor_name)",
            "CREATE INDEX IF NOT EXISTS idx_factor_values_date ON factor_values(trade_date)",
            "CREATE INDEX IF NOT EXISTS idx_factor_values_code ON factor_values(ts_code)",
            "CREATE INDEX IF NOT EXISTS idx_factor_values_code_date_name ON factor_values(ts_code, trade_date, factor_name)"
        ]
        
        for index_sql in indexes:
            self.db.execute(index_sql)
        
        logger.info("factor_values表和索引创建完成")
    
    def save_factor_values(self, df: pd.DataFrame):
        """
        批量保存因子值
        
        Args:
            df: 因子值DataFrame，包含列：ts_code, trade_date, factor_name, factor_value
        """
        if df.empty:
            return
        
        # 重命名列以匹配数据库
        df = df.rename(columns={
            'factor_value': 'factor_value'
        })
        
        # 添加创建时间
        df['create_time'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        # 批量插入（使用INSERT OR REPLACE避免重复）
        sql = """
            INSERT OR REPLACE INTO factor_values 
            (ts_code, trade_date, factor_name, factor_value, create_time)
            VALUES (?, ?, ?, ?, ?)
        """
        
        data = df[['ts_code', 'trade_date', 'factor_name', 'factor_value', 'create_time']].values.tolist()
        
        self.db.execute_many(sql, data)
        
        logger.info(f"保存因子值完成，共 {len(df)} 条记录")
    
    def get_factor_values(self, ts_code: str, factor_name: str,
                         start_date: str = None, end_date: str = None) -> pd.DataFrame:
        """
        获取因子值
        
        Args:
            ts_code: 股票代码
            factor_name: 因子名称
            start_date: 开始日期
            end_date: 结束日期
        
        Returns:
            因子值DataFrame
        """
        sql = """
            SELECT trade_date, factor_value
            FROM factor_values
            WHERE ts_code = ? AND factor_name = ?
        """
        params = [ts_code, factor_name]
        
        if start_date:
            sql += " AND trade_date >= ?"
            params.append(start_date)
        
        if end_date:
            sql += " AND trade_date <= ?"
            params.append(end_date)
        
        sql += " ORDER BY trade_date"
        
        results = self.db.query(sql, tuple(params))
        
        if not results:
            return pd.DataFrame()
        
        df = pd.DataFrame(results)
        df['trade_date'] = pd.to_datetime(df['trade_date'])
        
        return df
    
    def get_all_factor_values(self, trade_date: str, factor_names: List[str] = None) -> pd.DataFrame:
        """
        获取指定日期所有股票的因子值
        
        Args:
            trade_date: 交易日期
            factor_names: 因子名称列表，None表示获取所有因子
        
        Returns:
            因子值DataFrame
        """
        sql = """
            SELECT ts_code, factor_name, factor_value
            FROM factor_values
            WHERE trade_date = ?
        """
        params = [trade_date]
        
        if factor_names:
            placeholders = ','.join(['?'] * len(factor_names))
            sql += f" AND factor_name IN ({placeholders})"
            params.extend(factor_names)
        
        results = self.db.query(sql, tuple(params))
        
        if not results:
            return pd.DataFrame()
        
        return pd.DataFrame(results)
    
    def clear_old_factors(self, days: int = 365):
        """
        清理旧因子值
        
        Args:
            days: 保留天数
        """
        cutoff_date = (datetime.now() - timedelta(days=days)).strftime('%Y%m%d')
        
        sql = "DELETE FROM factor_values WHERE trade_date < ?"
        self.db.execute(sql, (cutoff_date,))
        
        logger.info(f"清理旧因子值完成，保留最近 {days} 天")


if __name__ == "__main__":
    # 测试代码
    from src.core.database import DatabaseManager
    from src.core.config import ConfigManager
    
    config = ConfigManager()
    db = DatabaseManager(config)
    
    # 测试因子值存储
    storage = FactorValueStorage(db)
    
    # 保存测试数据
    test_data = pd.DataFrame({
        'ts_code': ['000001.SZ', '000002.SZ', '000001.SZ'],
        'trade_date': ['20240101', '20240101', '20240102'],
        'factor_name': ['trend_score', 'trend_score', 'trend_score'],
        'factor_value': [75.5, 80.3, 78.2]
    })
    
    storage.save_factor_values(test_data)
    
    # 查询测试
    result = storage.get_factor_values('000001.SZ', 'trend_score')
    print(result)
