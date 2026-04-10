# -*- coding: utf-8 -*-
"""
历史推荐股票数据库管理
存储推荐股票记录及其分时数据
"""

import sqlite3
import pandas as pd
import numpy as np
from typing import Dict, List, Optional
from datetime import datetime, timedelta
import json
import os
from src.core.logger import get_logger

logger = get_logger("history_recommendation_db")


class HistoryRecommendationDB:
    """历史推荐股票数据库管理"""
    
    def __init__(self, db_path: str = "data/history_recommendation.db"):
        """初始化"""
        self.db_path = db_path
        
        # 确保目录存在
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        
        # 初始化数据库
        self._init_database()
    
    def _init_database(self) -> None:
        """初始化数据库表结构"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # 1. 推荐股票记录表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS recommendations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                name TEXT,
                recommendation_date TEXT NOT NULL,
                recommendation_reason TEXT,
                recommendation_score REAL,
                strategy_type TEXT,
                
                -- 买入信息
                buy_date TEXT,
                buy_price REAL,
                buy_signal TEXT,
                buy_signal_score REAL,
                
                -- 卖出信息
                sell_date TEXT,
                sell_price REAL,
                sell_signal TEXT,
                sell_signal_score REAL,
                
                -- 收益信息
                profit_pct REAL,
                hold_days INTEGER,
                
                -- 状态
                status TEXT DEFAULT 'active',
                
                -- 元数据
                created_time TEXT,
                updated_time TEXT,
                
                UNIQUE(symbol, recommendation_date)
            )
        """)
        
        # 2. 分时数据表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS intraday_data (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                trade_time TEXT NOT NULL,
                trade_date TEXT NOT NULL,
                
                open REAL,
                high REAL,
                low REAL,
                close REAL,
                volume REAL,
                amount REAL,
                
                created_time TEXT,
                
                UNIQUE(symbol, trade_time)
            )
        """)
        
        # 3. 创建索引
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_recommendations_symbol 
            ON recommendations(symbol)
        """)
        
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_recommendations_date 
            ON recommendations(recommendation_date)
        """)
        
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_intraday_symbol 
            ON intraday_data(symbol)
        """)
        
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_intraday_time 
            ON intraday_data(trade_time)
        """)
        
        conn.commit()
        conn.close()
        
        logger.info(f"数据库初始化完成: {self.db_path}")
    
    def add_recommendation(self, recommendation: Dict) -> bool:
        """
        添加推荐记录
        
        Args:
            recommendation: 推荐记录字典
        
        Returns:
            是否成功
        """
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            now = datetime.now().isoformat()
            
            sql = """
                INSERT OR REPLACE INTO recommendations (
                    symbol, name, recommendation_date, recommendation_reason,
                    recommendation_score, strategy_type, buy_date, buy_price,
                    buy_signal, buy_signal_score, sell_date, sell_price,
                    sell_signal, sell_signal_score, profit_pct, hold_days,
                    status, created_time, updated_time
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """
            
            cursor.execute(sql, (
                recommendation.get('symbol'),
                recommendation.get('name'),
                recommendation.get('recommendation_date'),
                recommendation.get('recommendation_reason'),
                recommendation.get('recommendation_score'),
                recommendation.get('strategy_type'),
                recommendation.get('buy_date'),
                recommendation.get('buy_price'),
                recommendation.get('buy_signal'),
                recommendation.get('buy_signal_score'),
                recommendation.get('sell_date'),
                recommendation.get('sell_price'),
                recommendation.get('sell_signal'),
                recommendation.get('sell_signal_score'),
                recommendation.get('profit_pct'),
                recommendation.get('hold_days'),
                recommendation.get('status', 'active'),
                recommendation.get('created_time', now),
                now,
            ))
            
            conn.commit()
            conn.close()
            
            logger.info(f"推荐记录已添加: {recommendation.get('symbol')} {recommendation.get('recommendation_date')}")
            return True
            
        except Exception as e:
            logger.error(f"添加推荐记录失败: {e}")
            return False
    
    def add_intraday_data(self, symbol: str, intraday_df: pd.DataFrame) -> bool:
        """
        添加分时数据
        
        Args:
            symbol: 股票代码
            intraday_df: 分时数据DataFrame
        
        Returns:
            是否成功
        """
        if intraday_df.empty:
            return False
        
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            now = datetime.now().isoformat()
            
            # 批量插入
            records = []
            for _, row in intraday_df.iterrows():
                trade_time = row.get('trade_time', '')
                if isinstance(trade_time, datetime):
                    trade_time = trade_time.isoformat()
                
                trade_date = row.get('trade_date', '')
                if hasattr(trade_date, 'strftime'):
                    trade_date = trade_date.strftime('%Y-%m-%d')
                
                records.append((
                    symbol,
                    trade_time,
                    trade_date,
                    row.get('open', 0),
                    row.get('high', 0),
                    row.get('low', 0),
                    row.get('close', 0),
                    row.get('volume', 0),
                    row.get('amount', 0),
                    now,
                ))
            
            # 使用批量插入
            sql = """
                INSERT OR REPLACE INTO intraday_data (
                    symbol, trade_time, trade_date, open, high, low,
                    close, volume, amount, created_time
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """
            
            cursor.executemany(sql, records)
            
            conn.commit()
            conn.close()
            
            logger.info(f"分时数据已添加: {symbol} {len(records)}条")
            return True
            
        except Exception as e:
            logger.error(f"添加分时数据失败: {e}")
            return False
    
    def get_recommendations(self, 
                           start_date: Optional[str] = None,
                           end_date: Optional[str] = None,
                           status: Optional[str] = None) -> List[Dict]:
        """
        获取推荐记录
        
        Args:
            start_date: 开始日期
            end_date: 结束日期
            status: 状态
        
        Returns:
            推荐记录列表
        """
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            sql = "SELECT * FROM recommendations WHERE 1=1"
            params = []
            
            if start_date:
                sql += " AND recommendation_date >= ?"
                params.append(start_date)
            
            if end_date:
                sql += " AND recommendation_date <= ?"
                params.append(end_date)
            
            if status:
                sql += " AND status = ?"
                params.append(status)
            
            sql += " ORDER BY recommendation_date DESC"
            
            cursor.execute(sql, params)
            rows = cursor.fetchall()
            
            columns = [description[0] for description in cursor.description]
            recommendations = [dict(zip(columns, row)) for row in rows]
            
            conn.close()
            
            return recommendations
            
        except Exception as e:
            logger.error(f"获取推荐记录失败: {e}")
            return []
    
    def get_intraday_data(self,
                         symbol: str,
                         start_time: Optional[str] = None,
                         end_time: Optional[str] = None) -> pd.DataFrame:
        """
        获取分时数据
        
        Args:
            symbol: 股票代码
            start_time: 开始时间
            end_time: 结束时间
        
        Returns:
            分时数据DataFrame
        """
        try:
            conn = sqlite3.connect(self.db_path)
            
            sql = "SELECT * FROM intraday_data WHERE symbol = ?"
            params = [symbol]
            
            if start_time:
                sql += " AND trade_time >= ?"
                params.append(start_time)
            
            if end_time:
                sql += " AND trade_time <= ?"
                params.append(end_time)
            
            sql += " ORDER BY trade_time ASC"
            
            df = pd.read_sql_query(sql, conn, params=params)
            
            conn.close()
            
            if not df.empty:
                df['trade_time'] = pd.to_datetime(df['trade_time'])
            
            return df
            
        except Exception as e:
            logger.error(f"获取分时数据失败: {e}")
            return pd.DataFrame()
    
    def get_statistics(self) -> Dict:
        """获取统计信息"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # 推荐记录统计
            cursor.execute("SELECT COUNT(*) FROM recommendations")
            total_recommendations = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(*) FROM recommendations WHERE status = 'completed'")
            completed_recommendations = cursor.fetchone()[0]
            
            # 分时数据统计
            cursor.execute("SELECT COUNT(*) FROM intraday_data")
            total_intraday_records = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(DISTINCT symbol) FROM intraday_data")
            symbols_with_data = cursor.fetchone()[0]
            
            # 收益统计
            cursor.execute("""
                SELECT AVG(profit_pct), MAX(profit_pct), MIN(profit_pct)
                FROM recommendations
                WHERE profit_pct IS NOT NULL
            """)
            row = cursor.fetchone()
            avg_profit, max_profit, min_profit = row if row[0] else (0, 0, 0)
            
            conn.close()
            
            return {
                'total_recommendations': total_recommendations,
                'completed_recommendations': completed_recommendations,
                'total_intraday_records': total_intraday_records,
                'symbols_with_data': symbols_with_data,
                'avg_profit': avg_profit or 0,
                'max_profit': max_profit or 0,
                'min_profit': min_profit or 0,
            }
            
        except Exception as e:
            logger.error(f"获取统计信息失败: {e}")
            return {}
    
    def print_statistics(self) -> None:
        """打印统计信息"""
        stats = self.get_statistics()
        
        print("\n" + "="*70)
        print("历史推荐股票数据库统计")
        print("="*70)
        
        print(f"\n【推荐记录】")
        print(f"  总记录数: {stats.get('total_recommendations', 0)}")
        print(f"  已完成: {stats.get('completed_recommendations', 0)}")
        
        print(f"\n【分时数据】")
        print(f"  总记录数: {stats.get('total_intraday_records', 0):,}")
        print(f"  股票数量: {stats.get('symbols_with_data', 0)}")
        
        print(f"\n【收益统计】")
        print(f"  平均收益: {stats.get('avg_profit', 0):.2f}%")
        print(f"  最大收益: {stats.get('max_profit', 0):.2f}%")
        print(f"  最小收益: {stats.get('min_profit', 0):.2f}%")
        
        print("="*70)
