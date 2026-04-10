# -*- coding: utf-8 -*-
"""
股票数据服务
"""

from typing import List, Optional, Dict
from datetime import datetime, timedelta
import pandas as pd

from src.core.logger import get_logger
from src.core.database import DatabaseManager
from src.core.config import ConfigManager
from src.services.base_service import BaseService
from src.dao.stock_dao import StockBasicDAO, StockDailyDAO

logger = get_logger("stock_service")


class StockService(BaseService):
    """股票数据服务"""
    
    def __init__(self, config: ConfigManager = None, db: DatabaseManager = None):
        super().__init__(config, db)
        self.stock_basic_dao = StockBasicDAO(db)
        self.stock_daily_dao = StockDailyDAO(db)
    
    def get_stock_info(self, ts_code: str) -> Optional[Dict]:
        """获取股票基础信息"""
        return self.stock_basic_dao.find_by_ts_code(ts_code)
    
    def get_stock_list(self, industry: str = None) -> List[Dict]:
        """获取股票列表"""
        if industry:
            return self.stock_basic_dao.find_by_industry(industry)
        return self.stock_basic_dao.find_all_main_board()
    
    def get_daily_data(
        self, 
        ts_code: str, 
        start_date: str = None, 
        end_date: str = None,
        days: int = 60
    ) -> pd.DataFrame:
        """获取日线数据"""
        if end_date is None:
            end_date = datetime.now().strftime("%Y%m%d")
        
        if start_date is None:
            start_date = (datetime.strptime(end_date, "%Y%m%d") - timedelta(days=days * 2)).strftime("%Y%m%d")
        
        return self.stock_daily_dao.get_dataframe(ts_code, start_date, end_date)
    
    def get_latest_trade_date(self) -> Optional[str]:
        """获取最新交易日期"""
        return self.stock_daily_dao.find_latest_date()
    
    def get_market_data(self, trade_date: str = None) -> pd.DataFrame:
        """获取市场全量数据"""
        if trade_date is None:
            trade_date = self.get_latest_trade_date()
        
        if trade_date is None:
            return pd.DataFrame()
        
        sql = """
            SELECT s.ts_code, s.name, d.trade_date, d.close, d.pct_chg, d.vol, d.amount
            FROM stock_daily d
            JOIN stock_basic s ON d.ts_code = s.ts_code
            WHERE d.trade_date = ?
        """
        
        return self.db.query_to_dataframe(sql, (trade_date,))
    
    def get_index_data(
        self, 
        index_code: str = "000001.SH",
        days: int = 60
    ) -> pd.DataFrame:
        """获取指数数据"""
        end_date = datetime.now().strftime("%Y%m%d")
        start_date = (datetime.now() - timedelta(days=days * 2)).strftime("%Y%m%d")
        
        sql = """
            SELECT trade_date, open, close, high, low, vol, amount
            FROM stock_daily
            WHERE ts_code = ? AND trade_date >= ? AND trade_date <= ?
            ORDER BY trade_date
        """
        
        df = self.db.query_to_dataframe(sql, (index_code, start_date, end_date))
        
        if not df.empty:
            df['trade_date'] = pd.to_datetime(df['trade_date'], format='%Y%m%d', errors='coerce')
        
        return df
    
    def save_stock_basic(self, df: pd.DataFrame) -> int:
        """保存股票基础信息"""
        return self.stock_basic_dao.batch_insert(df)
    
    def save_stock_daily(self, df: pd.DataFrame) -> int:
        """保存日线数据"""
        return self.stock_daily_dao.batch_insert(df)
    
    def get_top_gainers(self, trade_date: str = None, limit: int = 10) -> List[Dict]:
        """获取涨幅榜"""
        if trade_date is None:
            trade_date = self.get_latest_trade_date()
        
        sql = """
            SELECT s.ts_code, s.name, d.close, d.pct_chg, d.vol, d.amount
            FROM stock_daily d
            JOIN stock_basic s ON d.ts_code = s.ts_code
            WHERE d.trade_date = ?
            ORDER BY d.pct_chg DESC
            LIMIT ?
        """
        
        return self.db.query(sql, (trade_date, limit))
    
    def get_top_losers(self, trade_date: str = None, limit: int = 10) -> List[Dict]:
        """获取跌幅榜"""
        if trade_date is None:
            trade_date = self.get_latest_trade_date()
        
        sql = """
            SELECT s.ts_code, s.name, d.close, d.pct_chg, d.vol, d.amount
            FROM stock_daily d
            JOIN stock_basic s ON d.ts_code = s.ts_code
            WHERE d.trade_date = ?
            ORDER BY d.pct_chg ASC
            LIMIT ?
        """
        
        return self.db.query(sql, (trade_date, limit))
    
    def get_top_volume(self, trade_date: str = None, limit: int = 10) -> List[Dict]:
        """获取成交额榜"""
        if trade_date is None:
            trade_date = self.get_latest_trade_date()
        
        sql = """
            SELECT s.ts_code, s.name, d.close, d.pct_chg, d.vol, d.amount
            FROM stock_daily d
            JOIN stock_basic s ON d.ts_code = s.ts_code
            WHERE d.trade_date = ?
            ORDER BY d.amount DESC
            LIMIT ?
        """
        
        return self.db.query(sql, (trade_date, limit))


class SignalService(BaseService):
    """信号服务"""
    
    def __init__(self, config: ConfigManager = None, db: DatabaseManager = None):
        super().__init__(config, db)
        from src.dao.stock_dao import SignalHistoryDAO
        self.signal_dao = SignalHistoryDAO(db)
    
    def get_signals(self, ts_code: str = None, limit: int = 100) -> List[Dict]:
        """获取信号列表"""
        if ts_code:
            return self.signal_dao.find_by_code(ts_code, limit)
        
        sql = """
            SELECT * FROM signal_history
            ORDER BY signal_time DESC
            LIMIT ?
        """
        return self.db.query(sql, (limit,))
    
    def get_unpushed_signals(self) -> List[Dict]:
        """获取未推送信号"""
        return self.signal_dao.find_unpushed()
    
    def save_signal(self, data: Dict) -> int:
        """保存信号"""
        return self.signal_dao.insert(data)
    
    def mark_pushed(self, id: int) -> int:
        """标记已推送"""
        return self.signal_dao.mark_pushed(id)


class HoldStockService(BaseService):
    """持仓服务"""
    
    def __init__(self, config: ConfigManager = None, db: DatabaseManager = None):
        super().__init__(config, db)
        from src.dao.stock_dao import HoldStockDAO
        self.hold_dao = HoldStockDAO(db)
    
    def get_active_holds(self) -> List[Dict]:
        """获取活跃持仓"""
        return self.hold_dao.find_active()
    
    def get_hold(self, ts_code: str) -> Optional[Dict]:
        """获取单个持仓"""
        return self.hold_dao.find_by_code(ts_code)
    
    def add_hold(self, data: Dict) -> int:
        """添加持仓"""
        return self.hold_dao.insert_or_update(data)
    
    def remove_hold(self, ts_code: str) -> int:
        """移除持仓"""
        return self.hold_dao.delete(ts_code)
    
    def update_hold_status(self, ts_code: str, status: int) -> int:
        """更新持仓状态"""
        return self.hold_dao.update_status(ts_code, status)
    
    def get_hold_profit(self, ts_code: str, current_price: float) -> Optional[Dict]:
        """计算持仓盈亏"""
        hold = self.get_hold(ts_code)
        
        if not hold:
            return None
        
        hold_price = hold.get('hold_price', 0)
        hold_num = hold.get('hold_num', 0)
        
        if hold_price <= 0 or hold_num <= 0:
            return None
        
        profit_pct = (current_price - hold_price) / hold_price
        profit_amount = (current_price - hold_price) * hold_num
        market_value = current_price * hold_num
        
        return {
            'ts_code': ts_code,
            'name': hold.get('name'),
            'hold_price': hold_price,
            'current_price': current_price,
            'hold_num': hold_num,
            'profit_pct': round(profit_pct * 100, 2),
            'profit_amount': round(profit_amount, 2),
            'market_value': round(market_value, 2)
        }
