# -*- coding: utf-8 -*-
"""
交易执行引擎
"""

from typing import Dict, Optional
from datetime import datetime
from .portfolio import Portfolio
from .config import BacktestConfig
from src.core.logger import get_logger

logger = get_logger("execution_engine")


class ExecutionEngine:
    """交易执行引擎"""
    
    def __init__(self, config: BacktestConfig):
        """初始化"""
        self.config = config
        
        # 当日买入记录（用于T+1检查）
        self.today_buys: Dict[str, str] = {}  # {symbol: date}
    
    def execute(self, 
                bars: list, 
                signals: Dict[str, Dict],
                portfolio: Portfolio,
                current_date: str) -> None:
        """
        执行交易
        
        Args:
            bars: 当前bar数据
            signals: 信号字典 {symbol: signal}
            portfolio: 组合
            current_date: 当前日期
        """
        # 清理过期的今日买入记录
        self._clean_today_buys(current_date)
        
        for bar in bars:
            symbol = bar['symbol']
            signal = signals.get(symbol)
            
            if not signal:
                continue
            
            # 检查涨跌停
            if self.config.enable_limit_rule:
                if self._is_limit_up(bar):
                    logger.debug(f"{symbol} 涨停，无法买入")
                    continue
                
                if self._is_limit_down(bar):
                    logger.debug(f"{symbol} 跌停，无法卖出")
                    continue
            
            # 执行买入
            if signal['buy'] and signal['buy_score'] >= self.config.buy_signal_threshold:
                self._execute_buy(bar, signal, portfolio, current_date)
            
            # 执行卖出
            elif signal['sell'] and signal['sell_score'] >= self.config.sell_signal_threshold:
                self._execute_sell(bar, signal, portfolio, current_date)
    
    def _execute_buy(self, 
                    bar: Dict, 
                    signal: Dict,
                    portfolio: Portfolio,
                    current_date: str) -> bool:
        """执行买入"""
        symbol = bar['symbol']
        
        # 检查是否可以开仓
        if not portfolio.can_open_position():
            return False
        
        # 检查是否已持有
        if portfolio.has_position(symbol):
            return False
        
        # 计算仓位
        price = bar['open']  # 使用开盘价
        quantity = portfolio.calculate_position_size(price)
        
        if quantity < 100:  # 最小交易单位
            return False
        
        # 开仓
        success = portfolio.open_position(
            symbol=symbol,
            price=price,
            quantity=quantity,
            entry_time=bar['timestamp'],
            entry_date=current_date,
            buy_signal_type=signal['buy_type'],
            buy_signal_score=signal['buy_score'],
        )
        
        if success:
            # 记录今日买入（用于T+1检查）
            self.today_buys[symbol] = current_date
            
            logger.info(
                f"买入 {symbol} "
                f"价格:{price:.2f} "
                f"数量:{quantity} "
                f"信号:{signal['buy_type']} "
                f"评分:{signal['buy_score']:.0f}"
            )
        
        return success
    
    def _execute_sell(self,
                     bar: Dict,
                     signal: Dict,
                     portfolio: Portfolio,
                     current_date: str) -> bool:
        """执行卖出"""
        symbol = bar['symbol']
        
        # 检查是否持有
        if not portfolio.has_position(symbol):
            return False
        
        # T+1检查
        if self.config.enable_t1_rule:
            if symbol in self.today_buys:
                buy_date = self.today_buys[symbol]
                if buy_date == current_date:
                    logger.debug(f"{symbol} T+1限制，今日买入不能卖出")
                    return False
        
        # 平仓
        price = bar['open']  # 使用开盘价
        success = portfolio.close_position(
            symbol=symbol,
            price=price,
            exit_time=bar['timestamp'],
            exit_date=current_date,
            sell_signal_type=signal['sell_type'],
            sell_signal_score=signal['sell_score'],
        )
        
        if success:
            logger.info(
                f"卖出 {symbol} "
                f"价格:{price:.2f} "
                f"信号:{signal['sell_type']} "
                f"评分:{signal['sell_score']:.0f}"
            )
        
        return success
    
    def check_risk_control(self,
                          bars: list,
                          portfolio: Portfolio,
                          current_date: str) -> None:
        """风控检查"""
        for bar in bars:
            symbol = bar['symbol']
            
            if not portfolio.has_position(symbol):
                continue
            
            position = portfolio.get_position(symbol)
            current_price = bar['close']
            
            # 计算盈亏
            profit_pct = (current_price - position.entry_price) / position.entry_price
            
            # 止损检查
            if profit_pct <= self.config.stop_loss_pct:
                self._execute_risk_sell(
                    bar, portfolio, current_date, 
                    "止损", 100.0
                )
                continue
            
            # 止盈检查
            if profit_pct >= self.config.take_profit_pct:
                self._execute_risk_sell(
                    bar, portfolio, current_date,
                    "止盈", 85.0
                )
                continue
            
            # 移动止盈检查
            if position.highest_price > position.entry_price * 1.03:  # 已盈利3%
                drawdown = (position.highest_price - current_price) / position.highest_price
                if drawdown >= self.config.trailing_stop_pct:
                    self._execute_risk_sell(
                        bar, portfolio, current_date,
                        "移动止盈", 90.0
                    )
                    continue
            
            # 时间止损检查
            hold_days = (bar['timestamp'] - position.entry_time).days
            if hold_days >= self.config.max_hold_days and profit_pct < 0:
                self._execute_risk_sell(
                    bar, portfolio, current_date,
                    "时间止损", 50.0
                )
                continue
    
    def _execute_risk_sell(self,
                          bar: Dict,
                          portfolio: Portfolio,
                          current_date: str,
                          reason: str,
                          score: float) -> bool:
        """执行风控卖出"""
        symbol = bar['symbol']
        
        # T+1检查
        if self.config.enable_t1_rule:
            if symbol in self.today_buys:
                buy_date = self.today_buys[symbol]
                if buy_date == current_date:
                    return False
        
        price = bar['close']  # 风控卖出使用收盘价
        success = portfolio.close_position(
            symbol=symbol,
            price=price,
            exit_time=bar['timestamp'],
            exit_date=current_date,
            sell_signal_type=reason,
            sell_signal_score=score,
        )
        
        if success:
            logger.warning(
                f"风控卖出 {symbol} "
                f"价格:{price:.2f} "
                f"原因:{reason}"
            )
        
        return success
    
    def _is_limit_up(self, bar: Dict) -> bool:
        """判断是否涨停"""
        pct_change = bar.get('pct_change', 0)
        return pct_change >= self.config.limit_up_pct - 0.001  # 留一点误差
    
    def _is_limit_down(self, bar: Dict) -> bool:
        """判断是否跌停"""
        pct_change = bar.get('pct_change', 0)
        return pct_change <= self.config.limit_down_pct + 0.001  # 留一点误差
    
    def _clean_today_buys(self, current_date: str) -> None:
        """清理过期的今日买入记录"""
        expired_symbols = [
            symbol for symbol, date in self.today_buys.items()
            if date != current_date
        ]
        
        for symbol in expired_symbols:
            del self.today_buys[symbol]
