# -*- coding: utf-8 -*-
"""
组合管理
"""

from typing import Dict, List, Optional
from datetime import datetime
from .position import Position
from .config import BacktestConfig


class Portfolio:
    """组合管理"""
    
    def __init__(self, config: BacktestConfig):
        """初始化"""
        self.config = config
        
        # 资金
        self.initial_capital = config.initial_capital
        self.cash = config.initial_capital
        self.total_value = config.initial_capital
        
        # 持仓
        self.positions: Dict[str, Position] = {}
        
        # 净值曲线
        self.equity_curve: List[Dict] = []
        
        # 交易记录
        self.trade_history: List[Dict] = []
        
        # 每日记录
        self.daily_records: List[Dict] = []
    
    def get_position(self, symbol: str) -> Optional[Position]:
        """获取持仓"""
        return self.positions.get(symbol)
    
    def has_position(self, symbol: str) -> bool:
        """是否有持仓"""
        return symbol in self.positions
    
    def get_position_count(self) -> int:
        """获取持仓数量"""
        return len(self.positions)
    
    def can_open_position(self) -> bool:
        """是否可以开仓"""
        return self.get_position_count() < self.config.max_positions
    
    def calculate_position_size(self, price: float) -> int:
        """计算仓位大小"""
        # 计算目标金额
        target_amount = self.total_value * self.config.position_size
        
        # 检查可用资金
        if target_amount > self.cash:
            target_amount = self.cash * 0.95  # 留5%备用
        
        # 计算股数（100股整数倍）
        quantity = int(target_amount / price / 100) * 100
        
        return quantity
    
    def open_position(self, 
                     symbol: str, 
                     price: float, 
                     quantity: int,
                     entry_time: datetime,
                     entry_date: str,
                     buy_signal_type: str = "",
                     buy_signal_score: float = 0.0) -> bool:
        """开仓"""
        
        # 检查持仓数量
        if not self.can_open_position():
            return False
        
        # 检查是否已持有
        if self.has_position(symbol):
            return False
        
        # 计算成本（含滑点和手续费）
        actual_price = price * (1 + self.config.buy_slippage)
        cost = actual_price * quantity
        fee = cost * self.config.buy_fee
        total_cost = cost + fee
        
        # 检查资金
        if total_cost > self.cash:
            return False
        
        # 扣除资金
        self.cash -= total_cost
        
        # 创建持仓
        position = Position(
            symbol=symbol,
            entry_price=actual_price,
            quantity=quantity,
            entry_time=entry_time,
            entry_date=entry_date,
            buy_signal_type=buy_signal_type,
            buy_signal_score=buy_signal_score,
        )
        
        self.positions[symbol] = position
        
        # 记录交易
        self.trade_history.append({
            'time': entry_time,
            'date': entry_date,
            'action': 'buy',
            'symbol': symbol,
            'price': actual_price,
            'quantity': quantity,
            'amount': cost,
            'fee': fee,
            'total_cost': total_cost,
            'signal_type': buy_signal_type,
            'signal_score': buy_signal_score,
        })
        
        return True
    
    def close_position(self,
                      symbol: str,
                      price: float,
                      exit_time: datetime,
                      exit_date: str,
                      sell_signal_type: str = "",
                      sell_signal_score: float = 0.0) -> bool:
        """平仓"""
        
        # 检查持仓
        if not self.has_position(symbol):
            return False
        
        position = self.positions[symbol]
        
        # 计算收入（含滑点和手续费）
        actual_price = price * (1 - self.config.sell_slippage)
        revenue = actual_price * position.quantity
        fee = revenue * self.config.sell_fee
        actual_revenue = revenue - fee
        
        # 增加资金
        self.cash += actual_revenue
        
        # 计算盈亏
        cost = position.entry_price * position.quantity
        profit = actual_revenue - cost
        profit_pct = profit / cost
        
        # 记录交易
        self.trade_history.append({
            'time': exit_time,
            'date': exit_date,
            'action': 'sell',
            'symbol': symbol,
            'price': actual_price,
            'quantity': position.quantity,
            'amount': actual_revenue,
            'fee': fee,
            'profit': profit,
            'profit_pct': profit_pct,
            'signal_type': sell_signal_type,
            'signal_score': sell_signal_score,
            'hold_days': (exit_time - position.entry_time).days,
        })
        
        # 删除持仓
        del self.positions[symbol]
        
        return True
    
    def update_positions(self, price_dict: Dict[str, float]) -> None:
        """更新持仓价格"""
        for symbol, price in price_dict.items():
            if self.has_position(symbol):
                self.positions[symbol].update_price(price)
    
    def update_total_value(self) -> None:
        """更新总资产"""
        positions_value = sum(pos.get_value() for pos in self.positions.values())
        self.total_value = self.cash + positions_value
    
    def record_equity(self, time: datetime, date: str) -> None:
        """记录净值"""
        self.update_total_value()
        
        self.equity_curve.append({
            'time': time,
            'date': date,
            'cash': self.cash,
            'positions_value': self.total_value - self.cash,
            'total_value': self.total_value,
            'position_count': self.get_position_count(),
        })
    
    def get_results(self) -> Dict:
        """获取结果"""
        return {
            'initial_capital': self.initial_capital,
            'final_capital': self.total_value,
            'total_return': (self.total_value - self.initial_capital) / self.initial_capital,
            'equity_curve': self.equity_curve,
            'trade_history': self.trade_history,
            'daily_records': self.daily_records,
        }
