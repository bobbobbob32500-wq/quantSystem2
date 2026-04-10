# -*- coding: utf-8 -*-
"""
完全自动优化系统（Fully Automatic Optimization System）
结合所有模块，实现完全自动的策略优化和盘中动态调整
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Callable
from threading import Thread, Event
import time

from src.core.logger import get_logger
from src.core.database import DatabaseManager
from src.modules.hybrid_reoptimizer import HybridReoptimizer
from src.modules.strategy_switcher import StrategySwitcher, SwitchMode

logger = get_logger("fully_automatic_system")


class FullyAutomaticOptimizationSystem:
    """完全自动优化系统"""
    
    def __init__(self,
                 db: DatabaseManager = None,
                 
                 # 混合重优化参数
                 online_max_history: int = 1000,
                 scheduled_interval_minutes: int = 30,
                 consecutive_loss_threshold: int = 3,
                 drawdown_threshold: float = 0.15,
                 
                 # 策略切换参数
                 switch_mode: SwitchMode = SwitchMode.GRADUAL):
        """
        初始化完全自动优化系统
        
        Args:
            db: 数据库管理器
            online_max_history: 在线学习最大历史
            scheduled_interval_minutes: 定时重优化间隔
            consecutive_loss_threshold: 连续亏损阈值
            drawdown_threshold: 回撤阈值
            switch_mode: 策略切换模式
        """
        self.db = db or DatabaseManager()
        
        # 混合重优化器
        self.reoptimizer = HybridReoptimizer(
            online_max_history=online_max_history,
            scheduled_interval_minutes=scheduled_interval_minutes,
            consecutive_loss_threshold=consecutive_loss_threshold,
            drawdown_threshold=drawdown_threshold
        )
        
        # 策略切换器
        self.switcher = StrategySwitcher(switch_mode=switch_mode)
        
        # 运行状态
        self.is_running = False
        self.stop_event = Event()
        
        # 统计
        self.trade_count = 0
        self.total_pnl = 0.0
        self.start_time = None
        
        # 回调函数
        self.on_signal: Optional[Callable] = None
        self.on_position_change: Optional[Callable] = None
        
        # 设置内部回调
        self._setup_callbacks()
        
        logger.info("完全自动优化系统初始化完成")
    
    def _setup_callbacks(self) -> None:
        """设置内部回调"""
        # 策略切换回调
        self.reoptimizer.on_strategy_change = self._on_strategy_change
        self.reoptimizer.on_trade = self._on_trade
        
        # 持仓回调
        self.switcher.on_close_position = self._on_close_position
        self.switcher.on_open_position = self._on_open_position
    
    def _on_strategy_change(self, old_strategy, new_strategy, source: str) -> None:
        """策略切换回调"""
        logger.info(f"策略已切换 (来源={source})")
        
        # 使用切换器平滑切换
        if old_strategy and new_strategy:
            self.switcher.switch_strategy(
                old_strategy,
                new_strategy,
                self.switcher.positions
            )
    
    def _on_trade(self, signal: Dict) -> None:
        """交易回调"""
        self.trade_count += 1
        
        # 触发外部回调
        if self.on_signal:
            self.on_signal(signal)
    
    def _on_close_position(self, symbol: str, position) -> None:
        """平仓回调"""
        logger.info(f"平仓: {symbol}, PnL={position.pnl:.2f}")
        self.total_pnl += position.pnl
        
        # 触发外部回调
        if self.on_position_change:
            self.on_position_change('close', symbol, position)
    
    def _on_open_position(self, symbol: str, position) -> None:
        """开仓回调"""
        logger.info(f"开仓: {symbol}")
        
        # 触发外部回调
        if self.on_position_change:
            self.on_position_change('open', symbol, position)
    
    def start(self,
             data_getter: Callable,
             initial_strategy: Optional[Callable] = None) -> None:
        """
        启动系统
        
        Args:
            data_getter: 数据获取函数
            initial_strategy: 初始策略
        """
        logger.info("启动完全自动优化系统...")
        
        self.start_time = datetime.now()
        
        # 启动混合重优化器
        self.reoptimizer.start(data_getter, initial_strategy)
        
        self.is_running = True
        logger.info("系统已启动")
    
    def stop(self) -> None:
        """停止系统"""
        logger.info("停止完全自动优化系统...")
        
        self.reoptimizer.stop()
        self.stop_event.set()
        self.is_running = False
        
        logger.info("系统已停止")
    
    def on_new_bar(self, bar: Dict) -> Optional[Dict]:
        """
        新K线处理（核心方法）
        
        Args:
            bar: K线数据
        
        Returns:
            交易信号
        """
        if not self.is_running:
            return None
        
        # 通过混合重优化器处理
        signal = self.reoptimizer.on_new_bar(bar)
        
        return signal
    
    def on_trade_result(self, trade: Dict) -> None:
        """
        交易结果处理
        
        Args:
            trade: 交易结果
        """
        pnl = trade.get('pnl', 0)
        
        # 更新统计
        self.total_pnl += pnl
        
        # 更新重优化器
        self.reoptimizer.on_trade_result(pnl)
    
    def on_drawdown_update(self, drawdown: float) -> None:
        """
        回撤更新
        
        Args:
            drawdown: 当前回撤
        """
        self.reoptimizer.on_drawdown_update(drawdown)
    
    def force_reoptimize(self) -> Optional[Dict]:
        """
        强制重优化
        
        Returns:
            优化结果
        """
        return self.reoptimizer.force_reoptimize()
    
    def get_current_strategy(self) -> Optional[Callable]:
        """
        获取当前策略
        
        Returns:
            当前策略
        """
        return self.reoptimizer.get_current_strategy()
    
    def get_statistics(self) -> Dict:
        """
        获取统计信息
        
        Returns:
            统计信息
        """
        runtime = None
        if self.start_time:
            runtime = (datetime.now() - self.start_time).total_seconds()
        
        return {
            'is_running': self.is_running,
            'runtime_seconds': runtime,
            'trade_count': self.trade_count,
            'total_pnl': self.total_pnl,
            'reoptimizer': self.reoptimizer.get_statistics(),
            'switcher': self.switcher.get_statistics()
        }
    
    def save_state(self, filepath: str) -> None:
        """
        保存状态
        
        Args:
            filepath: 文件路径
        """
        self.reoptimizer.save_state(filepath)
        logger.info(f"系统状态已保存: {filepath}")
    
    def load_state(self, filepath: str) -> None:
        """
        加载状态
        
        Args:
            filepath: 文件路径
        """
        self.reoptimizer.load_state(filepath)
        logger.info(f"系统状态已加载: {filepath}")


# 使用示例
def example_usage():
    """使用示例"""
    
    # 1. 创建系统
    system = FullyAutomaticOptimizationSystem(
        scheduled_interval_minutes=30,  # 每30分钟重优化
        consecutive_loss_threshold=3,   # 连续亏损3次触发
        drawdown_threshold=0.15         # 回撤15%触发
    )
    
    # 2. 定义数据获取器
    def get_data():
        # 从数据库获取最近30天数据
        db = DatabaseManager()
        data = db.get_recent_data(days=30)
        return data
    
    # 3. 定义初始策略
    def initial_strategy(bar):
        # 简单的RSI策略
        rsi = bar.get('rsi', 50)
        if rsi < 30:
            return {'action': 'buy', 'reason': 'RSI超卖'}
        elif rsi > 70:
            return {'action': 'sell', 'reason': 'RSI超买'}
        return None
    
    # 4. 设置回调
    def on_signal(signal):
        print(f"信号: {signal}")
    
    def on_position_change(action, symbol, position):
        print(f"持仓变化: {action} {symbol}")
    
    system.on_signal = on_signal
    system.on_position_change = on_position_change
    
    # 5. 启动系统
    system.start(get_data, initial_strategy)
    
    # 6. 模拟实时数据流
    for i in range(100):
        # 模拟K线数据
        bar = {
            'symbol': '000001',
            'close': 10.0 + np.random.randn() * 0.1,
            'rsi': 50 + np.random.randn() * 10,
            'volume': 1000000
        }
        
        # 处理K线
        signal = system.on_new_bar(bar)
        
        if signal:
            print(f"K线{i}: {signal}")
        
        time.sleep(0.1)
    
    # 7. 获取统计
    stats = system.get_statistics()
    print(f"统计: {stats}")
    
    # 8. 停止系统
    system.stop()


if __name__ == "__main__":
    example_usage()
