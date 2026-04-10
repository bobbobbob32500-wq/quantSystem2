# -*- coding: utf-8 -*-
"""
分时数据驱动层
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Optional, Tuple
from datetime import datetime, time
from src.core.logger import get_logger

logger = get_logger("intraday_data_handler")


class IntradayDataHandler:
    """分时数据驱动层"""
    
    def __init__(self, 
                 daily_data_dict: Dict[str, pd.DataFrame],
                 minute_data_dict: Dict[str, pd.DataFrame],
                 start_date: Optional[str] = None,
                 end_date: Optional[str] = None):
        """
        初始化
        
        Args:
            daily_data_dict: 日线数据 {symbol: DataFrame}
            minute_data_dict: 分钟数据 {symbol: DataFrame}
            start_date: 开始日期
            end_date: 结束日期
        """
        self.daily_data_dict = {}
        self.minute_data_dict = {}
        self.symbols = []
        
        # 当前日期索引
        self.current_date_index = 0
        self.dates = []
        
        # 当前分钟索引
        self.current_minute_index = 0
        self.current_date = None
        
        # 处理日线数据
        self._process_daily_data(daily_data_dict, start_date, end_date)
        
        # 处理分钟数据
        self._process_minute_data(minute_data_dict)
        
        logger.info(f"分时数据加载完成: {len(self.symbols)}只股票, {len(self.dates)}个交易日")
    
    def _process_daily_data(self, 
                           daily_data_dict: Dict[str, pd.DataFrame],
                           start_date: Optional[str],
                           end_date: Optional[str]) -> None:
        """处理日线数据"""
        for symbol, df in daily_data_dict.items():
            if df.empty:
                continue
            
            # 确保时间列
            if 'trade_date' in df.columns:
                df['trade_date'] = pd.to_datetime(df['trade_date'])
            else:
                logger.warning(f"{symbol} 日线数据缺少时间列")
                continue
            
            # 按时间排序
            df = df.sort_values('trade_date').reset_index(drop=True)
            
            # 日期过滤
            if start_date:
                start_dt = pd.to_datetime(start_date)
                df = df[df['trade_date'] >= start_dt]
            
            if end_date:
                end_dt = pd.to_datetime(end_date)
                df = df[df['trade_date'] <= end_dt]
            
            if not df.empty:
                self.daily_data_dict[symbol] = df
                self.symbols.append(symbol)
        
        # 提取日期序列
        if self.daily_data_dict:
            first_symbol = self.symbols[0]
            self.dates = self.daily_data_dict[first_symbol]['trade_date'].tolist()
    
    def _process_minute_data(self, minute_data_dict: Dict[str, pd.DataFrame]) -> None:
        """处理分钟数据"""
        for symbol, df in minute_data_dict.items():
            if symbol not in self.symbols:
                continue
            
            if df.empty:
                continue
            
            # 确保时间列
            if 'trade_time' in df.columns:
                df['trade_time'] = pd.to_datetime(df['trade_time'])
            elif 'timestamp' in df.columns:
                df['trade_time'] = pd.to_datetime(df['timestamp'])
            else:
                logger.warning(f"{symbol} 分钟数据缺少时间列")
                continue
            
            # 按时间排序
            df = df.sort_values('trade_time').reset_index(drop=True)
            
            # 提取日期
            df['trade_date'] = df['trade_time'].dt.date
            
            self.minute_data_dict[symbol] = df
    
    def get_next_date(self) -> Optional[datetime]:
        """获取下一个交易日"""
        if self.current_date_index >= len(self.dates):
            return None
        
        date = self.dates[self.current_date_index]
        self.current_date = date
        self.current_date_index += 1
        
        # 重置分钟索引
        self.current_minute_index = 0
        
        return date
    
    def get_daily_bars(self, date: datetime) -> Optional[List[Dict]]:
        """获取日线数据"""
        bars = []
        
        for symbol in self.symbols:
            df = self.daily_data_dict[symbol]
            
            # 找到对应日期的数据
            mask = df['trade_date'] == date
            if not mask.any():
                continue
            
            row = df[mask].iloc[0]
            
            bar = {
                'symbol': symbol,
                'timestamp': date,
                'date': date.strftime('%Y-%m-%d'),
                'open': row.get('open', 0),
                'high': row.get('high', 0),
                'low': row.get('low', 0),
                'close': row.get('close', 0),
                'volume': row.get('vol', row.get('volume', 0)),
                'amount': row.get('amount', 0),
            }
            
            bars.append(bar)
        
        return bars if bars else None
    
    def get_minute_bars(self, date: datetime) -> Optional[List[Dict]]:
        """获取当日所有分钟数据"""
        if not self.current_date:
            return None
        
        bars = []
        date_str = date.strftime('%Y-%m-%d')
        
        for symbol in self.symbols:
            if symbol not in self.minute_data_dict:
                continue
            
            df = self.minute_data_dict[symbol]
            
            # 筛选当日数据
            mask = df['trade_date'] == date.date()
            if not mask.any():
                continue
            
            day_df = df[mask]
            
            for idx, row in day_df.iterrows():
                bar = {
                    'symbol': symbol,
                    'timestamp': row['trade_time'],
                    'date': date_str,
                    'time': row['trade_time'].strftime('%H:%M:%S'),
                    'open': row.get('open', 0),
                    'high': row.get('high', 0),
                    'low': row.get('low', 0),
                    'close': row.get('close', 0),
                    'volume': row.get('vol', row.get('volume', 0)),
                    'amount': row.get('amount', 0),
                }
                
                bars.append(bar)
        
        # 按时间排序
        bars.sort(key=lambda x: (x['timestamp'], x['symbol']))
        
        return bars if bars else None
    
    def get_next_minute_bar(self) -> Optional[Dict]:
        """获取下一个分钟bar（逐分钟推进）"""
        if not self.current_date:
            return None
        
        # 获取当日所有分钟数据
        minute_bars = self.get_minute_bars(self.current_date)
        
        if not minute_bars:
            return None
        
        if self.current_minute_index >= len(minute_bars):
            return None
        
        bar = minute_bars[self.current_minute_index]
        self.current_minute_index += 1
        
        return bar
    
    def get_minute_window(self, 
                         symbol: str, 
                         window_size: int = 50) -> Optional[pd.DataFrame]:
        """获取分钟数据窗口"""
        if symbol not in self.minute_data_dict:
            return None
        
        df = self.minute_data_dict[symbol]
        
        # 获取当前时间之前的数据
        if not self.current_date:
            return None
        
        current_time = self.current_date
        
        # 筛选当前时间之前的数据
        mask = df['trade_time'] <= current_time
        filtered_df = df[mask]
        
        if len(filtered_df) < window_size:
            return None
        
        return filtered_df.tail(window_size).copy()
    
    def reset(self) -> None:
        """重置索引"""
        self.current_date_index = 0
        self.current_minute_index = 0
        self.current_date = None
    
    def get_progress(self) -> Tuple[int, int, int, int]:
        """获取进度"""
        return (
            self.current_date_index, 
            len(self.dates),
            self.current_minute_index,
            240  # 假设每天240分钟
        )
