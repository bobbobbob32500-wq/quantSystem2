# -*- coding: utf-8 -*-
"""
Tushare增强数据获取模块
获取每日指标、资金流向、融资融券等数据用于特征工程
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Optional
from datetime import datetime, timedelta
import time
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.core.database import DatabaseManager
from src.core.config import ConfigManager
from src.core.logger import get_logger

logger = get_logger("tushare_enhanced_data")

try:
    import tushare as ts
    TUSHARE_AVAILABLE = True
except ImportError:
    TUSHARE_AVAILABLE = False


class TushareEnhancedDataFetcher:
    """Tushare增强数据获取器"""
    
    def __init__(self, config: ConfigManager = None):
        if not TUSHARE_AVAILABLE:
            raise ImportError("请安装tushare: pip install tushare")
        
        self.config = config or ConfigManager()
        self.token = self.config.get("data_source.tushare_token")
        
        if not self.token:
            raise ValueError("未配置Tushare Token")
        
        ts.set_token(self.token)
        self.pro = ts.pro_api()
        logger.info("Tushare初始化成功")
    
    def fetch_daily_basic(
        self,
        start_date: str,
        end_date: str,
        save_to_db: bool = True,
        db: DatabaseManager = None
    ) -> pd.DataFrame:
        """
        获取每日指标数据
        
        包含: pe, pb, ps, turnover_rate, volume_ratio, total_mv, circ_mv
        
        Args:
            start_date: 开始日期 YYYYMMDD
            end_date: 结束日期 YYYYMMDD
            save_to_db: 是否保存到数据库
            db: 数据库管理器
        
        Returns:
            DataFrame: 每日指标数据
        """
        logger.info(f"获取每日指标: {start_date} ~ {end_date}")
        
        all_data = []
        
        # 获取交易日历
        cal_df = self.pro.trade_cal(
            exchange='SSE',
            start_date=start_date,
            end_date=end_date,
            is_open='1'
        )
        
        trade_dates = cal_df['cal_date'].tolist()
        logger.info(f"交易日数: {len(trade_dates)}")
        
        for i, td in enumerate(trade_dates):
            try:
                df = self.pro.daily_basic(trade_date=td)
                if df is not None and not df.empty:
                    all_data.append(df)
                    logger.debug(f"{td}: {len(df)}条")
                
                # 避免请求过快
                time.sleep(0.1)
                
            except Exception as e:
                logger.warning(f"{td}: {e}")
                continue
        
        if not all_data:
            logger.warning("未获取到数据")
            return pd.DataFrame()
        
        result = pd.concat(all_data, ignore_index=True)
        logger.info(f"获取每日指标完成: {len(result)}条")
        
        if save_to_db and db:
            self._save_daily_basic_to_db(result, db)
        
        return result
    
    def fetch_moneyflow(
        self,
        start_date: str,
        end_date: str,
        save_to_db: bool = True,
        db: DatabaseManager = None
    ) -> pd.DataFrame:
        """
        获取资金流向数据
        
        包含: buy_lg_vol(大单买入), sell_lg_vol(大单卖出), net_mf_vol(净流入)
        
        Args:
            start_date: 开始日期
            end_date: 结束日期
            save_to_db: 是否保存到数据库
            db: 数据库管理器
        
        Returns:
            DataFrame: 资金流向数据
        """
        logger.info(f"获取资金流向: {start_date} ~ {end_date}")
        
        all_data = []
        
        cal_df = self.pro.trade_cal(
            exchange='SSE',
            start_date=start_date,
            end_date=end_date,
            is_open='1'
        )
        
        trade_dates = cal_df['cal_date'].tolist()
        
        for i, td in enumerate(trade_dates):
            try:
                df = self.pro.moneyflow(trade_date=td)
                if df is not None and not df.empty:
                    all_data.append(df)
                
                time.sleep(0.1)
                
            except Exception as e:
                logger.warning(f"{td}: {e}")
                continue
        
        if not all_data:
            return pd.DataFrame()
        
        result = pd.concat(all_data, ignore_index=True)
        logger.info(f"获取资金流向完成: {len(result)}条")
        
        if save_to_db and db:
            self._save_moneyflow_to_db(result, db)
        
        return result
    
    def fetch_margin(
        self,
        start_date: str,
        end_date: str,
        save_to_db: bool = True,
        db: DatabaseManager = None
    ) -> pd.DataFrame:
        """
        获取融资融券数据
        
        包含: rzye(融资余额), rqye(融券余额)
        
        Args:
            start_date: 开始日期
            end_date: 结束日期
            save_to_db: 是否保存到数据库
            db: 数据库管理器
        
        Returns:
            DataFrame: 融资融券数据
        """
        logger.info(f"获取融资融券: {start_date} ~ {end_date}")
        
        try:
            # margin接口支持日期范围
            result = self.pro.margin(
                start_date=start_date,
                end_date=end_date
            )
            
            if result is None or result.empty:
                return pd.DataFrame()
            
            logger.info(f"获取融资融券完成: {len(result)}条")
            
            if save_to_db and db:
                self._save_margin_to_db(result, db)
            
            return result
            
        except Exception as e:
            logger.error(f"获取融资融券失败: {e}")
            return pd.DataFrame()
    
    def _save_daily_basic_to_db(self, df: pd.DataFrame, db: DatabaseManager):
        """保存每日指标到数据库"""
        logger.info("保存每日指标到数据库...")
        
        # 创建表（如果不存在）
        db.execute("""
            CREATE TABLE IF NOT EXISTS tushare_daily_basic (
                ts_code TEXT,
                trade_date TEXT,
                pe REAL,
                pb REAL,
                ps REAL,
                turnover_rate REAL,
                volume_ratio REAL,
                total_mv REAL,
                circ_mv REAL,
                update_time TEXT,
                PRIMARY KEY (ts_code, trade_date)
            )
        """)
        
        saved = 0
        for _, row in df.iterrows():
            try:
                db.execute("""
                    INSERT OR REPLACE INTO tushare_daily_basic
                    (ts_code, trade_date, pe, pb, ps, turnover_rate, volume_ratio, total_mv, circ_mv, update_time)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    row.get('ts_code'),
                    row.get('trade_date'),
                    row.get('pe'),
                    row.get('pb'),
                    row.get('ps'),
                    row.get('turnover_rate'),
                    row.get('volume_ratio'),
                    row.get('total_mv'),
                    row.get('circ_mv'),
                    datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                ))
                saved += 1
            except Exception as e:
                continue
        
        logger.info(f"保存每日指标: {saved}条")
    
    def _save_moneyflow_to_db(self, df: pd.DataFrame, db: DatabaseManager):
        """保存资金流向到数据库"""
        logger.info("保存资金流向到数据库...")
        
        db.execute("""
            CREATE TABLE IF NOT EXISTS tushare_moneyflow (
                ts_code TEXT,
                trade_date TEXT,
                buy_lg_vol REAL,
                sell_lg_vol REAL,
                net_mf_vol REAL,
                net_mf_amount REAL,
                update_time TEXT,
                PRIMARY KEY (ts_code, trade_date)
            )
        """)
        
        saved = 0
        for _, row in df.iterrows():
            try:
                db.execute("""
                    INSERT OR REPLACE INTO tushare_moneyflow
                    (ts_code, trade_date, buy_lg_vol, sell_lg_vol, net_mf_vol, net_mf_amount, update_time)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    row.get('ts_code'),
                    row.get('trade_date'),
                    row.get('buy_lg_vol'),
                    row.get('sell_lg_vol'),
                    row.get('net_mf_vol'),
                    row.get('net_mf_amount'),
                    datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                ))
                saved += 1
            except Exception:
                continue
        
        logger.info(f"保存资金流向: {saved}条")
    
    def _save_margin_to_db(self, df: pd.DataFrame, db: DatabaseManager):
        """保存融资融券到数据库"""
        logger.info("保存融资融券到数据库...")
        
        db.execute("""
            CREATE TABLE IF NOT EXISTS tushare_margin (
                trade_date TEXT PRIMARY KEY,
                rzye REAL,
                rqye REAL,
                rzrqye REAL,
                update_time TEXT
            )
        """)
        
        saved = 0
        for _, row in df.iterrows():
            try:
                db.execute("""
                    INSERT OR REPLACE INTO tushare_margin
                    (trade_date, rzye, rqye, rzrqye, update_time)
                    VALUES (?, ?, ?, ?, ?)
                """, (
                    row.get('trade_date'),
                    row.get('rzye'),
                    row.get('rqye'),
                    row.get('rzrqye'),
                    datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                ))
                saved += 1
            except Exception:
                continue
        
        logger.info(f"保存融资融券: {saved}条")
    
    def fetch_all_enhanced_data(
        self,
        start_date: str,
        end_date: str,
        db: DatabaseManager = None
    ) -> Dict[str, pd.DataFrame]:
        """
        获取所有增强数据
        
        Returns:
            Dict: {
                'daily_basic': DataFrame,
                'moneyflow': DataFrame,
                'margin': DataFrame
            }
        """
        logger.info(f"获取所有增强数据: {start_date} ~ {end_date}")
        
        result = {}
        
        # 1. 每日指标
        result['daily_basic'] = self.fetch_daily_basic(
            start_date, end_date, save_to_db=True, db=db
        )
        
        # 2. 资金流向
        result['moneyflow'] = self.fetch_moneyflow(
            start_date, end_date, save_to_db=True, db=db
        )
        
        # 3. 融资融券
        result['margin'] = self.fetch_margin(
            start_date, end_date, save_to_db=True, db=db
        )
        
        return result


def main():
    """主函数"""
    print("=" * 72)
    print("  Tushare增强数据获取")
    print("=" * 72)
    
    config = ConfigManager()
    db = DatabaseManager(config)
    
    # 获取最近60个交易日
    all_dates = [
        r["trade_date"]
        for r in db.query(
            "SELECT DISTINCT trade_date FROM stock_daily ORDER BY trade_date DESC LIMIT 60"
        )
    ]
    
    if not all_dates:
        print("未找到交易日数据")
        return
    
    start_date = min(all_dates)
    end_date = max(all_dates)
    
    print(f"日期范围: {start_date} ~ {end_date}")
    print(f"交易日数: {len(all_dates)}")
    
    # 创建获取器
    fetcher = TushareEnhancedDataFetcher(config)
    
    # 获取数据
    print("\n[1/3] 获取每日指标...")
    daily_basic = fetcher.fetch_daily_basic(start_date, end_date, save_to_db=True, db=db)
    print(f"  获取 {len(daily_basic)} 条")
    
    print("\n[2/3] 获取资金流向...")
    moneyflow = fetcher.fetch_moneyflow(start_date, end_date, save_to_db=True, db=db)
    print(f"  获取 {len(moneyflow)} 条")
    
    print("\n[3/3] 获取融资融券...")
    margin = fetcher.fetch_margin(start_date, end_date, save_to_db=True, db=db)
    print(f"  获取 {len(margin)} 条")
    
    print("\n" + "=" * 72)
    print("  完成")
    print("=" * 72)


if __name__ == "__main__":
    main()
