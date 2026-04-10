# -*- coding: utf-8 -*-
"""
平滑策略切换模块（Smooth Strategy Switcher）
实现策略的无缝切换，避免持仓冲突
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Callable
from dataclasses import dataclass
from enum import Enum

from src.core.logger import get_logger

logger = get_logger("strategy_switcher")


class SwitchMode(Enum):
    """切换模式"""
    IMMEDIATE = "immediate"       # 立即切换
    GRADUAL = "gradual"           # 逐步切换
    WAIT_CLOSE = "wait_close"     # 等待平仓后切换


@dataclass
class Position:
    """持仓"""
    symbol: str
    quantity: int
    entry_price: float
    entry_time: datetime
    current_price: float
    pnl: float


class StrategySwitcher:
    """策略切换器"""
    
    def __init__(self,
                 switch_mode: SwitchMode = SwitchMode.GRADUAL,
                 max_position_age_hours: int = 24,
                 min_pnl_to_close: float = -0.05):
        """
        初始化策略切换器
        
        Args:
            switch_mode: 切换模式
            max_position_age_hours: 最大持仓时间（小时）
            min_pnl_to_close: 最小盈亏才平仓
        """
        self.switch_mode = switch_mode
        self.max_position_age_hours = max_position_age_hours
        self.min_pnl_to_close = min_pnl_to_close
        
        # 当前持仓
        self.positions: Dict[str, Position] = {}
        
        # 策略
        self.old_strategy: Optional[Callable] = None
        self.new_strategy: Optional[Callable] = None
        self.current_strategy: Optional[Callable] = None
        
        # 切换状态
        self.is_switching = False
        self.switch_progress = 0.0  # 0-1
        
        # 回调函数
        self.on_close_position: Optional[Callable] = None
        self.on_open_position: Optional[Callable] = None
        
        logger.info(f"策略切换器初始化完成 (模式={switch_mode.value})")
    
    def switch_strategy(self,
                       old_strategy: Callable,
                       new_strategy: Callable,
                       current_positions: Optional[Dict[str, Position]] = None) -> bool:
        """
        切换策略
        
        Args:
            old_strategy: 旧策略
            new_strategy: 新策略
            current_positions: 当前持仓
        
        Returns:
            是否成功
        """
        logger.info("开始策略切换...")
        
        self.old_strategy = old_strategy
        self.new_strategy = new_strategy
        
        if current_positions:
            self.positions = current_positions
        
        # 根据模式切换
        if self.switch_mode == SwitchMode.IMMEDIATE:
            return self._switch_immediate()
        elif self.switch_mode == SwitchMode.GRADUAL:
            return self._switch_gradual()
        elif self.switch_mode == SwitchMode.WAIT_CLOSE:
            return self._switch_wait_close()
        
        return False
    
    def _switch_immediate(self) -> bool:
        """立即切换"""
        logger.info("立即切换策略")
        
        # 平掉所有持仓
        self._close_all_positions()
        
        # 切换策略
        self.current_strategy = self.new_strategy
        self.is_switching = False
        self.switch_progress = 1.0
        
        logger.info("策略切换完成")
        return True
    
    def _switch_gradual(self) -> bool:
        """逐步切换"""
        logger.info("逐步切换策略")
        
        self.is_switching = True
        self.switch_progress = 0.0
        
        # 检查每个持仓
        positions_to_close = []
        
        for symbol, pos in self.positions.items():
            # 新策略是否支持该持仓
            should_hold = self._check_new_strategy(pos)
            
            if not should_hold:
                positions_to_close.append(symbol)
        
        # 平掉不支持的持仓
        for symbol in positions_to_close:
            self._close_position(symbol)
        
        # 切换策略
        self.current_strategy = self.new_strategy
        
        # 计算进度
        if self.positions:
            closed_ratio = len(positions_to_close) / len(self.positions)
            self.switch_progress = closed_ratio
        else:
            self.switch_progress = 1.0
        
        self.is_switching = False
        logger.info(f"策略切换完成 (进度={self.switch_progress:.2%})")
        
        return True
    
    def _switch_wait_close(self) -> bool:
        """等待平仓后切换"""
        logger.info("等待平仓后切换策略")
        
        self.is_switching = True
        self.switch_progress = 0.0
        
        # 检查是否有持仓
        if not self.positions:
            # 无持仓，直接切换
            self.current_strategy = self.new_strategy
            self.is_switching = False
            self.switch_progress = 1.0
            logger.info("无持仓，策略切换完成")
            return True
        
        # 有持仓，等待平仓
        logger.info(f"等待{len(self.positions)}个持仓平仓...")
        return False
    
    def _check_new_strategy(self, position: Position) -> bool:
        """
        检查新策略是否支持持仓
        
        Args:
            position: 持仓
        
        Returns:
            是否支持
        """
        if self.new_strategy is None:
            return False
        
        try:
            # 构造模拟数据
            mock_data = {
                'symbol': position.symbol,
                'close': position.current_price,
                'position': position.quantity
            }
            
            # 检查新策略
            signal = self.new_strategy(mock_data)
            
            # 如果返回hold或buy，则支持
            if signal:
                action = signal.get('action', 'hold')
                return action in ['hold', 'buy']
            
            return False
        
        except Exception as e:
            logger.error(f"检查新策略失败: {e}")
            return False
    
    def _close_position(self, symbol: str) -> bool:
        """
        平仓
        
        Args:
            symbol: 股票代码
        
        Returns:
            是否成功
        """
        if symbol not in self.positions:
            return False
        
        position = self.positions[symbol]
        
        # 触发回调
        if self.on_close_position:
            self.on_close_position(symbol, position)
        
        # 移除持仓
        del self.positions[symbol]
        
        logger.info(f"平仓: {symbol}")
        return True
    
    def _close_all_positions(self) -> int:
        """
        平掉所有持仓
        
        Returns:
            平仓数量
        """
        count = 0
        for symbol in list(self.positions.keys()):
            if self._close_position(symbol):
                count += 1
        
        logger.info(f"平掉所有持仓: {count}个")
        return count
    
    def on_position_close(self, symbol: str) -> None:
        """
        持仓平仓回调
        
        Args:
            symbol: 股票代码
        """
        if symbol in self.positions:
            del self.positions[symbol]
        
        # 检查是否可以完成切换
        if self.is_switching and not self.positions:
            self.current_strategy = self.new_strategy
            self.is_switching = False
            self.switch_progress = 1.0
            logger.info("所有持仓已平仓，策略切换完成")
    
    def on_new_position(self, symbol: str, position: Position) -> None:
        """
        新持仓回调
        
        Args:
            symbol: 股票代码
            position: 持仓
        """
        self.positions[symbol] = position
    
    def check_position_age(self) -> List[str]:
        """
        检查持仓时间
        
        Returns:
            需要平仓的股票列表
        """
        to_close = []
        now = datetime.now()
        
        for symbol, pos in self.positions.items():
            age = (now - pos.entry_time).total_seconds() / 3600
            
            if age > self.max_position_age_hours:
                to_close.append(symbol)
                logger.warning(f"持仓超时: {symbol}, 年龄={age:.1f}小时")
        
        return to_close
    
    def get_statistics(self) -> Dict:
        """
        获取统计信息
        
        Returns:
            统计信息
        """
        total_pnl = sum(pos.pnl for pos in self.positions.values())
        
        return {
            'switch_mode': self.switch_mode.value,
            'is_switching': self.is_switching,
            'switch_progress': self.switch_progress,
            'position_count': len(self.positions),
            'total_pnl': total_pnl,
            'current_strategy': self.current_strategy is not None
        }
