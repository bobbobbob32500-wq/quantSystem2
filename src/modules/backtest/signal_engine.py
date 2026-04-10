# -*- coding: utf-8 -*-
"""
信号计算引擎
"""

import numpy as np
import pandas as pd
from typing import Dict, Optional, Tuple
from collections import deque
from .config import BacktestConfig
from src.core.logger import get_logger

logger = get_logger("signal_engine")


class SignalEngine:
    """信号计算引擎"""
    
    def __init__(self, config: BacktestConfig):
        """初始化"""
        self.config = config
        
        # 数据窗口
        self.data_windows: Dict[str, deque] = {}
        
        # 信号历史
        self.signal_history: Dict[str, list] = {}
    
    def update_data(self, bars: list) -> None:
        """更新数据窗口"""
        for bar in bars:
            symbol = bar['symbol']
            
            # 初始化窗口
            if symbol not in self.data_windows:
                self.data_windows[symbol] = deque(maxlen=self.config.window_size)
            
            # 添加数据
            self.data_windows[symbol].append(bar)
    
    def generate_signal(self, symbol: str, position_exists: bool = False) -> Optional[Dict]:
        """
        生成信号
        
        Args:
            symbol: 股票代码
            position_exists: 是否有持仓
        
        Returns:
            信号字典
        """
        if symbol not in self.data_windows:
            return None
        
        window = list(self.data_windows[symbol])
        
        if len(window) < 10:  # 至少需要10个bar
            return None
        
        # 买入信号
        if not position_exists:
            buy_signal, buy_type, buy_score = self._detect_buy_signal(window)
        else:
            buy_signal, buy_type, buy_score = False, "", 0.0
        
        # 卖出信号
        if position_exists:
            sell_signal, sell_type, sell_score = self._detect_sell_signal(window)
        else:
            sell_signal, sell_type, sell_score = False, "", 0.0
        
        return {
            'buy': buy_signal,
            'buy_type': buy_type,
            'buy_score': buy_score,
            'sell': sell_signal,
            'sell_type': sell_type,
            'sell_score': sell_score,
        }
    
    def _detect_buy_signal(self, window: list) -> Tuple[bool, str, float]:
        """检测买入信号"""
        if len(window) < 10:
            return False, "", 0.0
        
        current = window[-1]
        prices = np.array([x['close'] for x in window])
        volumes = np.array([x['volume'] for x in window])
        
        # 信号1: 强势突破
        if len(window) >= 5:
            prev_high = max(x['high'] for x in window[-5:-1])
            breakout_pct = (current['close'] - prev_high) / prev_high
            
            # 量比
            avg_vol = np.mean(volumes[-5:-1])
            vol_ratio = current['volume'] / avg_vol if avg_vol > 0 else 1
            
            # 强势突破（涨幅>3%，量比>1.5）
            if breakout_pct > 0.03 and vol_ratio > 1.5:
                score = 80 + min(breakout_pct * 50, 15)
                return True, "强势突破", score
            
            # 中等突破（涨幅>2%，量比>1.3）
            elif breakout_pct > 0.02 and vol_ratio > 1.3:
                score = 70 + min(breakout_pct * 50, 10)
                return True, "中等突破", score
        
        # 信号2: 回踩均线
        if len(window) >= 5:
            ma5 = np.mean(prices[-5:])
            price_diff = abs(current['close'] - ma5) / ma5
            
            if price_diff < 0.015:  # 接近MA5
                recent_low = min(x['low'] for x in window[-3:])
                if current['close'] > recent_low * 1.005:  # 止跌
                    # 检查量能
                    avg_vol = np.mean(volumes[-5:-1])
                    vol_ratio = current['volume'] / avg_vol if avg_vol > 0 else 1
                    
                    if vol_ratio > 1.0:
                        score = 45 + min(vol_ratio * 5, 10)
                        return True, "回踩均线", score
        
        # 信号3: 量价齐升
        if len(window) >= 2:
            prev_close = window[-2]['close']
            rise_pct = (current['close'] - prev_close) / prev_close
            
            # 量比
            avg_vol = np.mean(volumes[-5:-1]) if len(volumes) >= 5 else volumes[-1]
            vol_ratio = current['volume'] / avg_vol if avg_vol > 0 else 1
            
            # 量价齐升（涨幅>2%，量比>1.3）
            if rise_pct > 0.02 and vol_ratio > 1.3:
                score = 55 + min(rise_pct * 50, 15)
                return True, "量价齐升", score
        
        return False, "", 0.0
    
    def _detect_sell_signal(self, window: list) -> Tuple[bool, str, float]:
        """检测卖出信号"""
        if len(window) < 2:
            return False, "", 0.0
        
        current = window[-1]
        prices = np.array([x['close'] for x in window])
        
        # 需要买入价格来计算盈亏（这里简化处理）
        # 实际使用时需要传入持仓信息
        
        # 信号1: 快速下跌
        if len(window) >= 3:
            prev_price = window[-3]['close']
            drop_pct = (current['close'] - prev_price) / prev_price
            if drop_pct < -0.05:  # 3天跌5%
                return True, "快速下跌", 60
        
        # 信号2: 趋势转弱
        if len(window) >= 10:
            ma5 = np.mean(prices[-5:])
            ma10 = np.mean(prices[-10:])
            
            # 跌破MA5 5%且趋势转弱
            if current['close'] < ma5 * 0.95 and ma5 < ma10:
                return True, "趋势转弱", 65
        
        return False, "", 0.0
    
    def get_signal_history(self, symbol: str) -> list:
        """获取信号历史"""
        return self.signal_history.get(symbol, [])
    
    def clear_signal_history(self, symbol: str) -> None:
        """清除信号历史"""
        if symbol in self.signal_history:
            self.signal_history[symbol] = []
