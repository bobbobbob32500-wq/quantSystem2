# -*- coding: utf-8 -*-
"""
持仓对象
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass
class Position:
    """持仓对象"""
    
    symbol: str                    # 股票代码
    entry_price: float             # 买入价格
    quantity: int                  # 持仓数量（股）
    entry_time: datetime           # 买入时间
    entry_date: str                # 买入日期（YYYY-MM-DD）
    
    # 信号信息
    buy_signal_type: str = ""      # 买入信号类型
    buy_signal_score: float = 0.0  # 买入信号评分
    
    # 状态信息
    highest_price: float = 0.0     # 持仓期间最高价
    current_price: float = 0.0     # 当前价格
    current_value: float = 0.0     # 当前市值
    
    def __post_init__(self):
        """初始化后处理"""
        if self.highest_price == 0.0:
            self.highest_price = self.entry_price
        if self.current_price == 0.0:
            self.current_price = self.entry_price
        if self.current_value == 0.0:
            self.current_value = self.quantity * self.entry_price
    
    def update_price(self, current_price: float) -> None:
        """更新当前价格"""
        self.current_price = current_price
        self.current_value = self.quantity * current_price
        
        # 更新最高价
        if current_price > self.highest_price:
            self.highest_price = current_price
    
    def get_profit_pct(self) -> float:
        """计算盈亏比例"""
        return (self.current_price - self.entry_price) / self.entry_price
    
    def get_profit_amount(self) -> float:
        """计算盈亏金额"""
        return (self.current_price - self.entry_price) * self.quantity
    
    def get_value(self) -> float:
        """获取当前市值"""
        return self.current_value
    
    def get_cost(self) -> float:
        """获取成本"""
        return self.entry_price * self.quantity
    
    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            'symbol': self.symbol,
            'entry_price': self.entry_price,
            'quantity': self.quantity,
            'entry_time': self.entry_time.strftime('%Y-%m-%d %H:%M:%S'),
            'entry_date': self.entry_date,
            'buy_signal_type': self.buy_signal_type,
            'buy_signal_score': self.buy_signal_score,
            'highest_price': self.highest_price,
            'current_price': self.current_price,
            'current_value': self.current_value,
            'profit_pct': self.get_profit_pct(),
            'profit_amount': self.get_profit_amount(),
        }
