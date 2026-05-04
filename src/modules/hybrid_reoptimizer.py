    # -*- coding: utf-8 -*-
"""
混合重优化器（Hybrid Reoptimizer）
结合在线学习、定时重优化、事件驱动三种方式
实现完全自动优化
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Callable
from threading import Thread, Event
import time

from src.core.logger import get_logger
from src.modules.online_learner import OnlineLearner
from src.modules.scheduled_reoptimizer import ScheduledReoptimizer
from src.modules.event_driven_reoptimizer import EventDrivenReoptimizer, MarketEvent

logger = get_logger("hybrid_reoptimizer")


class HybridReoptimizer:
    """混合重优化器"""
    
    def __init__(self,
                 # 在线学习参数
                 online_max_history: int = 1000,
                 online_decay_factor: float = 0.95,
                 
                 # 定时重优化参数
                 scheduled_interval_minutes: int = 30,
                 scheduled_lookback_days: int = 30,
                 
                 # 事件驱动参数
                 consecutive_loss_threshold: int = 3,
                 drawdown_threshold: float = 0.15):
        """
        初始化混合重优化器
        
        Args:
            online_max_history: 在线学习最大历史
            online_decay_factor: 在线学习衰减因子
            scheduled_interval_minutes: 定时重优化间隔
            scheduled_lookback_days: 定时重优化回看天数
            consecutive_loss_threshold: 连续亏损阈值
            drawdown_threshold: 回撤阈值
        """
        # 在线学习器（实时层）
        self.online_learner = OnlineLearner(
            max_history=online_max_history,
            decay_factor=online_decay_factor
        )
        
        # 定时重优化器（定期层）
        self.scheduled_reoptimizer = ScheduledReoptimizer(
            interval_minutes=scheduled_interval_minutes,
            lookback_days=scheduled_lookback_days
        )
        
        # 事件驱动重优化器（紧急层）
        self.event_driven = EventDrivenReoptimizer(
            consecutive_loss_threshold=consecutive_loss_threshold,
            drawdown_threshold=drawdown_threshold
        )
        
        # 当前策略
        self.current_strategy = None
        self.strategy_source = "none"  # online/scheduled/event
        
        # 数据获取器
        self.data_getter: Optional[Callable] = None
        
        # 运行状态
        self.is_running = False
        self.stop_event = Event()
        
        # 回调函数
        self.on_strategy_change: Optional[Callable] = None
        self.on_trade: Optional[Callable] = None
        
        # 设置内部回调
        self._setup_internal_callbacks()
        
        logger.info("混合重优化器初始化完成")
    
    def _setup_internal_callbacks(self) -> None:
        """设置内部回调"""
        # 定时重优化回调
        self.scheduled_reoptimizer.on_strategy_update = self._on_scheduled_update
        
        # 事件驱动回调
        self.event_driven.on_emergency_reoptimize = self._on_emergency_event
    
    def _on_scheduled_update(self, old_strategy, new_strategy) -> None:
        """定时更新回调"""
        self.current_strategy = new_strategy
        self.strategy_source = "scheduled"
        
        logger.info("策略已更新（定时重优化）")
        
        # 触发外部回调
        if self.on_strategy_change:
            self.on_strategy_change(old_strategy, new_strategy, "scheduled")
    
    def _on_emergency_event(self, event: MarketEvent) -> None:
        """紧急事件回调"""
        logger.warning(f"触发紧急重优化: {event.type.value}")
        
        # 强制重优化
        if self.data_getter:
            data = self.data_getter()
            if data is not None:
                result = self.scheduled_reoptimizer.force_reoptimize(data)
                
                if result:
                    self.current_strategy = result['strategy']
                    self.strategy_source = "event"
                    
                    logger.info("策略已更新（事件驱动）")
                    
                    # 触发外部回调
                    if self.on_strategy_change:
                        self.on_strategy_change(
                            None, 
                            self.current_strategy, 
                            "event"
                        )
    
    def on_new_bar(self, bar: Dict) -> Optional[Dict]:
        """
        新K线处理（核心方法）
        
        Args:
            bar: K线数据
        
        Returns:
            交易信号
        """
        # 1. 在线学习（实时更新）
        if 'pnl' in bar:  # 如果有盈亏信息
            self.online_learner.update(bar)
        
        # 2. 检查定时重优化
        if self.scheduled_reoptimizer.should_reoptimize():
            if self.data_getter:
                data = self.data_getter()
                if data is not None:
                    self.scheduled_reoptimizer.reoptimize_in_background(data)
        
        # 3. 使用当前策略检查信号
        signal = None
        if self.current_strategy:
            try:
                signal = self.current_strategy(bar)
            except Exception as e:
                logger.error(f"策略执行错误: {e}")
        
        # 4. 在线学习判断（辅助）
        if signal is None:
            if self.online_learner.should_trade(bar):
                signal = {'action': 'buy', 'source': 'online'}
        
        # 5. 触发交易回调
        if signal and self.on_trade:
            self.on_trade(signal)
        
        return signal
    
    def on_trade_result(self, pnl: float) -> None:
        """
        交易结果处理
        
        Args:
            pnl: 盈亏
        """
        # 更新事件驱动
        event = self.event_driven.on_trade_result(pnl)
        
        if event:
            logger.warning(f"检测到关键事件: {event.type.value}")
    
    def on_drawdown_update(self, drawdown: float) -> None:
        """
        回撤更新
        
        Args:
            drawdown: 当前回撤
        """
        event = self.event_driven.on_drawdown_update(drawdown)
        
        if event:
            logger.warning(f"回撤突破阈值: {drawdown:.2%}")
    
    def start(self, data_getter: Callable, initial_strategy: Optional[Callable] = None) -> None:
        """
        启动混合重优化器
        
        Args:
            data_getter: 数据获取函数
            initial_strategy: 初始策略
        """
        self.data_getter = data_getter
        
        if initial_strategy:
            self.current_strategy = initial_strategy
            self.strategy_source = "initial"
        
        # 启动定时重优化
        self.scheduled_reoptimizer.start_continuous_optimization(data_getter)
        
        self.is_running = True
        logger.info("混合重优化器已启动")
    
    def stop(self) -> None:
        """停止混合重优化器"""
        self.scheduled_reoptimizer.stop_continuous_optimization()
        self.stop_event.set()
        self.is_running = False
        logger.info("混合重优化器已停止")
    
    def force_reoptimize(self) -> Optional[Dict]:
        """
        强制重优化
        
        Returns:
            优化结果
        """
        if not self.data_getter:
            logger.warning("数据获取器未设置")
            return None
        
        data = self.data_getter()
        result = self.scheduled_reoptimizer.force_reoptimize(data)
        
        if result:
            self.current_strategy = result['strategy']
            self.strategy_source = "forced"
        
        return result
    
    def get_current_strategy(self) -> Optional[Callable]:
        """
        获取当前策略
        
        Returns:
            当前策略
        """
        return self.current_strategy
    
    def get_statistics(self) -> Dict:
        """
        获取统计信息
        
        Returns:
            统计信息
        """
        return {
            'is_running': self.is_running,
            'strategy_source': self.strategy_source,
            'online': self.online_learner.get_statistics(),
            'scheduled': self.scheduled_reoptimizer.get_statistics(),
            'event': self.event_driven.get_event_statistics()
        }
    
    def save_state(self, filepath: str) -> None:
        """
        保存状态
        
        Args:
            filepath: 文件路径
        """
        self.online_learner.save_state(f"{filepath}_online.pkl")
        logger.info(f"状态已保存: {filepath}")
    
    def load_state(self, filepath: str) -> None:
        """
        加载状态
        
        Args:
            filepath: 文件路径
        """
        self.online_learner.load_state(f"{filepath}_online.pkl")
        logger.info(f"状态已加载: {filepath}")
