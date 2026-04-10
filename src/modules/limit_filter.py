# -*- coding: utf-8 -*-
"""
涨停股票过滤功能
过滤涨停、跌停股票，避免无效交易记录
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Optional
from datetime import datetime
import logging

logger = logging.getLogger("LimitFilter")


class LimitFilter:
    """
    涨停/跌停过滤器
    过滤无法实际交易的股票
    """
    
    def __init__(self,
                 limit_up_threshold: float = 0.095,   # 涨停阈值（9.5%视为涨停）
                 limit_down_threshold: float = -0.095, # 跌停阈值
                 enable_filter: bool = True):
        """
        初始化涨停过滤器
        
        Args:
            limit_up_threshold: 涨停阈值（默认9.5%）
            limit_down_threshold: 跌停阈值（默认-9.5%）
            enable_filter: 是否启用过滤
        """
        self.limit_up_threshold = limit_up_threshold
        self.limit_down_threshold = limit_down_threshold
        self.enable_filter = enable_filter
        
        logger.info(f"涨停过滤器初始化: 涨停阈值={limit_up_threshold:.1%}, "
                   f"跌停阈值={limit_down_threshold:.1%}, 启用={enable_filter}")
    
    def is_limit_up(self, quote: Dict) -> bool:
        """
        判断是否涨停
        
        Args:
            quote: 行情数据 {'price', 'pre_close', 'change_pct', ...}
        
        Returns:
            是否涨停
        """
        if not self.enable_filter:
            return False
        
        # 方法1: 使用涨跌幅
        change_pct = quote.get('change_pct', 0)
        if change_pct >= self.limit_up_threshold * 100:
            return True
        
        # 方法2: 使用价格对比
        price = quote.get('price', 0)
        pre_close = quote.get('pre_close', 0)
        if pre_close > 0:
            pct_change = (price - pre_close) / pre_close
            if pct_change >= self.limit_up_threshold:
                return True
        
        return False
    
    def is_limit_down(self, quote: Dict) -> bool:
        """
        判断是否跌停
        
        Args:
            quote: 行情数据
        
        Returns:
            是否跌停
        """
        if not self.enable_filter:
            return False
        
        # 方法1: 使用涨跌幅
        change_pct = quote.get('change_pct', 0)
        if change_pct <= self.limit_down_threshold * 100:
            return True
        
        # 方法2: 使用价格对比
        price = quote.get('price', 0)
        pre_close = quote.get('pre_close', 0)
        if pre_close > 0:
            pct_change = (price - pre_close) / pre_close
            if pct_change <= self.limit_down_threshold:
                return True
        
        return False
    
    def is_tradable(self, quote: Dict) -> bool:
        """
        判断是否可交易
        
        Args:
            quote: 行情数据
        
        Returns:
            是否可交易
        """
        if not self.enable_filter:
            return True
        
        # 涨停不可买入
        if self.is_limit_up(quote):
            return False
        
        # 跌停不可卖出（但可以买入，这里不限制）
        # 如果需要限制跌停买入，可以取消注释
        # if self.is_limit_down(quote):
        #     return False
        
        return True
    
    def filter_signals(self, 
                      signals: List[Dict], 
                      quotes: Dict[str, Dict]) -> List[Dict]:
        """
        过滤信号（移除涨停股票）
        
        Args:
            signals: 买点信号列表
            quotes: 行情数据 {symbol: quote}
        
        Returns:
            过滤后的信号列表
        """
        if not self.enable_filter:
            return signals
        
        filtered_signals = []
        rejected_signals = []
        
        for signal in signals:
            symbol = signal.get('symbol', '')
            quote = quotes.get(symbol, {})
            
            if self.is_tradable(quote):
                filtered_signals.append(signal)
            else:
                # 记录被过滤的信号
                reject_reason = ''
                if self.is_limit_up(quote):
                    reject_reason = '涨停'
                elif self.is_limit_down(quote):
                    reject_reason = '跌停'
                
                rejected_signals.append({
                    'signal': signal,
                    'reason': reject_reason,
                    'change_pct': quote.get('change_pct', 0)
                })
        
        # 日志记录
        if rejected_signals:
            logger.info(f"过滤涨停/跌停信号: {len(rejected_signals)}个")
            for reject in rejected_signals:
                logger.info(f"  {reject['signal']['symbol']} {reject['signal']['name']}: "
                           f"{reject['reason']} ({reject['change_pct']:+.2f}%)")
        
        return filtered_signals
    
    def get_filter_summary(self, 
                          signals: List[Dict], 
                          quotes: Dict[str, Dict]) -> Dict:
        """
        获取过滤统计
        
        Args:
            signals: 原始信号列表
            quotes: 行情数据
        
        Returns:
            过滤统计
        """
        total = len(signals)
        limit_up_count = 0
        limit_down_count = 0
        tradable_count = 0
        
        for signal in signals:
            symbol = signal.get('symbol', '')
            quote = quotes.get(symbol, {})
            
            if self.is_limit_up(quote):
                limit_up_count += 1
            elif self.is_limit_down(quote):
                limit_down_count += 1
            else:
                tradable_count += 1
        
        return {
            'total_signals': total,
            'limit_up_count': limit_up_count,
            'limit_down_count': limit_down_count,
            'tradable_count': tradable_count,
            'filtered_count': limit_up_count + limit_down_count,
        }
    
    def check_quote_dataframe(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        检查DataFrame中的涨停股票
        
        Args:
            df: 行情DataFrame
        
        Returns:
            添加了涨停标记的DataFrame
        """
        if not self.enable_filter:
            return df
        
        df = df.copy()
        
        # 添加涨停标记
        df['is_limit_up'] = df.apply(
            lambda row: self.is_limit_up(row.to_dict()), 
            axis=1
        )
        df['is_limit_down'] = df.apply(
            lambda row: self.is_limit_down(row.to_dict()), 
            axis=1
        )
        df['is_tradable'] = df.apply(
            lambda row: self.is_tradable(row.to_dict()), 
            axis=1
        )
        
        return df


def check_limit_status(quote: Dict) -> Dict:
    """
    检查股票涨跌停状态（便捷函数）
    
    Args:
        quote: 行情数据
    
    Returns:
        状态信息
    """
    filter_obj = LimitFilter()
    
    return {
        'symbol': quote.get('symbol', ''),
        'name': quote.get('name', ''),
        'price': quote.get('price', 0),
        'change_pct': quote.get('change_pct', 0),
        'is_limit_up': filter_obj.is_limit_up(quote),
        'is_limit_down': filter_obj.is_limit_down(quote),
        'is_tradable': filter_obj.is_tradable(quote),
    }
