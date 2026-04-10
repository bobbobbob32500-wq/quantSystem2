# -*- coding: utf-8 -*-
"""
数据驱动层
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Optional, Tuple
from datetime import datetime
from src.core.logger import get_logger

logger = get_logger("data_handler")


class DataHandler:
    """数据驱动层"""
    
    def __init__(self, 
                 data_dict: Dict[str, pd.DataFrame],
                 start_date: Optional[str] = None,
                 end_date: Optional[str] = None):
        """
        初始化
        
        Args:
            data_dict: 数据字典 {symbol: DataFrame}
            start_date: 开始日期
            end_date: 结束日期
        """
        self.data_dict = {}
        self.symbols = []
        self.current_index = 0
        self.total_bars = 0
        
        # 处理数据
        for symbol, df in data_dict.items():
            if df.empty:
                continue
            
            # 确保时间列
            if 'trade_date' in df.columns:
                df['trade_date'] = pd.to_datetime(df['trade_date'])
            elif 'timestamp' in df.columns:
                df['trade_date'] = pd.to_datetime(df['timestamp'])
            else:
                logger.warning(f"{symbol} 缺少时间列")
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
                self.data_dict[symbol] = df
                self.symbols.append(symbol)
        
        # 计算总bar数
        if self.data_dict:
            self.total_bars = max(len(df) for df in self.data_dict.values())
        
        logger.info(f"数据加载完成: {len(self.symbols)}只股票, {self.total_bars}个交易日")
    
    def get_next_bar(self) -> Optional[List[Dict]]:
        """
        获取下一个bar的数据
        
        Returns:
            所有股票的当前bar数据
        """
        if self.current_index >= self.total_bars:
            return None
        
        bars = []
        
        for symbol in self.symbols:
            df = self.data_dict[symbol]
            
            # 检查是否有数据
            if self.current_index >= len(df):
                continue
            
            row = df.iloc[self.current_index]
            
            # 构建bar数据
            bar = {
                'symbol': symbol,
                'timestamp': row['trade_date'],
                'date': row['trade_date'].strftime('%Y-%m-%d'),
                'open': row.get('open', row.get('open_price', 0)),
                'high': row.get('high', row.get('high_price', 0)),
                'low': row.get('low', row.get('low_price', 0)),
                'close': row.get('close', row.get('close_price', 0)),
                'volume': row.get('vol', row.get('volume', 0)),
                'amount': row.get('amount', 0),
            }
            
            # 计算涨跌幅（用于涨跌停判断）
            if self.current_index > 0:
                prev_close = df.iloc[self.current_index - 1]['close']
                bar['pct_change'] = (bar['close'] - prev_close) / prev_close
            else:
                bar['pct_change'] = 0.0
            
            bars.append(bar)
        
        self.current_index += 1
        
        return bars if bars else None
    
    def get_current_date(self) -> Optional[str]:
        """获取当前日期"""
        if self.current_index >= self.total_bars:
            return None
        
        # 获取第一个股票的日期
        for symbol in self.symbols:
            df = self.data_dict[symbol]
            if self.current_index < len(df):
                return df.iloc[self.current_index]['trade_date'].strftime('%Y-%m-%d')
        
        return None
    
    def get_bar_by_index(self, symbol: str, index: int) -> Optional[Dict]:
        """根据索引获取bar数据"""
        if symbol not in self.data_dict:
            return None
        
        df = self.data_dict[symbol]
        
        if index >= len(df):
            return None
        
        row = df.iloc[index]
        
        return {
            'symbol': symbol,
            'timestamp': row['trade_date'],
            'date': row['trade_date'].strftime('%Y-%m-%d'),
            'open': row.get('open', row.get('open_price', 0)),
            'high': row.get('high', row.get('high_price', 0)),
            'low': row.get('low', row.get('low_price', 0)),
            'close': row.get('close', row.get('close_price', 0)),
            'volume': row.get('vol', row.get('volume', 0)),
            'amount': row.get('amount', 0),
        }
    
    def get_window_data(self, symbol: str, window_size: int) -> Optional[pd.DataFrame]:
        """获取窗口数据"""
        if symbol not in self.data_dict:
            return None
        
        df = self.data_dict[symbol]
        
        start_idx = max(0, self.current_index - window_size)
        end_idx = self.current_index
        
        if start_idx >= end_idx:
            return None
        
        return df.iloc[start_idx:end_idx].copy()
    
    def reset(self) -> None:
        """重置索引"""
        self.current_index = 0
    
    def get_progress(self) -> Tuple[int, int]:
        """获取进度"""
        return self.current_index, self.total_bars
