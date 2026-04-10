# -*- coding: utf-8 -*-
"""
事件驱动重优化模块（Event-Driven Reoptimization）
关键事件触发紧急重优化
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Callable
from dataclasses import dataclass
from enum import Enum

from src.core.logger import get_logger

logger = get_logger("event_driven_reoptimizer")


class EventType(Enum):
    """事件类型"""
    REGIME_CHANGE = "regime_change"           # 市场状态突变
    CONSECUTIVE_LOSS = "consecutive_loss"     # 连续亏损
    PERFORMANCE_DROP = "performance_drop"     # 策略表现下降
    VOLATILITY_SPIKE = "volatility_spike"     # 波动率飙升
    DRAWDOWN_BREACH = "drawdown_breach"       # 回撤突破阈值
    MARKET_CRASH = "market_crash"             # 市场崩盘


@dataclass
class MarketEvent:
    """市场事件"""
    type: EventType
    timestamp: datetime
    severity: float  # 0-1, 1最严重
    details: Dict


class EventDrivenReoptimizer:
    """事件驱动重优化器"""
    
    def __init__(self,
                 consecutive_loss_threshold: int = 3,
                 performance_drop_threshold: float = 0.5,
                 drawdown_threshold: float = 0.15,
                 volatility_threshold: float = 3.0):
        """
        初始化事件驱动重优化器
        
        Args:
            consecutive_loss_threshold: 连续亏损阈值
            performance_drop_threshold: 表现下降阈值
            drawdown_threshold: 回撤阈值
            volatility_threshold: 波动率阈值（标准差倍数）
        """
        self.consecutive_loss_threshold = consecutive_loss_threshold
        self.performance_drop_threshold = performance_drop_threshold
        self.drawdown_threshold = drawdown_threshold
        self.volatility_threshold = volatility_threshold
        
        # 事件历史
        self.event_history: List[MarketEvent] = []
        
        # 统计
        self.consecutive_losses = 0
        self.recent_pnl: List[float] = []
        self.recent_drawdown = 0.0
        self.baseline_performance = 0.0
        
        # 回调函数
        self.on_emergency_reoptimize: Optional[Callable] = None
        
        logger.info("事件驱动重优化器初始化完成")
    
    def on_trade_result(self, pnl: float) -> Optional[MarketEvent]:
        """
        交易结果处理
        
        Args:
            pnl: 盈亏
        
        Returns:
            触发的事件（如果有）
        """
        # 更新统计
        self.recent_pnl.append(pnl)
        if len(self.recent_pnl) > 100:
            self.recent_pnl.pop(0)
        
        # 检查连续亏损
        if pnl < 0:
            self.consecutive_losses += 1
        else:
            self.consecutive_losses = 0
        
        # 检查事件
        event = None
        
        # 1. 连续亏损事件
        if self.consecutive_losses >= self.consecutive_loss_threshold:
            event = MarketEvent(
                type=EventType.CONSECUTIVE_LOSS,
                timestamp=datetime.now(),
                severity=min(self.consecutive_losses / 10, 1.0),
                details={'count': self.consecutive_losses}
            )
        
        # 2. 表现下降事件
        if len(self.recent_pnl) >= 20:
            recent_performance = np.mean(self.recent_pnl[-20:])
            if self.baseline_performance > 0:
                drop = (self.baseline_performance - recent_performance) / self.baseline_performance
                if drop > self.performance_drop_threshold:
                    event = MarketEvent(
                        type=EventType.PERFORMANCE_DROP,
                        timestamp=datetime.now(),
                        severity=min(drop, 1.0),
                        details={'drop': drop, 'recent': recent_performance}
                    )
        
        # 触发事件
        if event:
            self._handle_event(event)
        
        return event
    
    def on_drawdown_update(self, drawdown: float) -> Optional[MarketEvent]:
        """
        回撤更新处理
        
        Args:
            drawdown: 当前回撤
        
        Returns:
            触发的事件（如果有）
        """
        self.recent_drawdown = drawdown
        
        # 检查回撤突破
        if drawdown > self.drawdown_threshold:
            event = MarketEvent(
                type=EventType.DRAWDOWN_BREACH,
                timestamp=datetime.now(),
                severity=min(drawdown / 0.3, 1.0),  # 30%为最大
                details={'drawdown': drawdown}
            )
            self._handle_event(event)
            return event
        
        return None
    
    def on_volatility_update(self, volatility: float, baseline_vol: float) -> Optional[MarketEvent]:
        """
        波动率更新处理
        
        Args:
            volatility: 当前波动率
            baseline_vol: 基准波动率
        
        Returns:
            触发的事件（如果有）
        """
        if baseline_vol > 0:
            vol_ratio = volatility / baseline_vol
            
            # 检查波动率飙升
            if vol_ratio > self.volatility_threshold:
                event = MarketEvent(
                    type=EventType.VOLATILITY_SPIKE,
                    timestamp=datetime.now(),
                    severity=min((vol_ratio - 1) / 5, 1.0),
                    details={'ratio': vol_ratio, 'volatility': volatility}
                )
                self._handle_event(event)
                return event
        
        return None
    
    def on_market_regime_change(self, old_regime: str, new_regime: str) -> MarketEvent:
        """
        市场状态变化处理
        
        Args:
            old_regime: 旧状态
            new_regime: 新状态
        
        Returns:
            触发的事件
        """
        event = MarketEvent(
            type=EventType.REGIME_CHANGE,
            timestamp=datetime.now(),
            severity=0.8,  # 高严重性
            details={'old': old_regime, 'new': new_regime}
        )
        self._handle_event(event)
        return event
    
    def _handle_event(self, event: MarketEvent) -> None:
        """
        处理事件
        
        Args:
            event: 市场事件
        """
        # 记录事件
        self.event_history.append(event)
        
        # 保留最近100个事件
        if len(self.event_history) > 100:
            self.event_history.pop(0)
        
        logger.warning(f"检测到关键事件: {event.type.value}, 严重性={event.severity:.2f}")
        
        # 触发紧急重优化
        if self.on_emergency_reoptimize:
            self.on_emergency_reoptimize(event)
    
    def is_critical_event(self, event: MarketEvent) -> bool:
        """
        判断是否为关键事件
        
        Args:
            event: 市场事件
        
        Returns:
            是否关键
        """
        # 高严重性事件
        if event.severity > 0.7:
            return True
        
        # 特定类型事件
        critical_types = {
            EventType.REGIME_CHANGE,
            EventType.MARKET_CRASH,
            EventType.DRAWDOWN_BREACH
        }
        
        return event.type in critical_types
    
    def get_event_statistics(self) -> Dict:
        """
        获取事件统计
        
        Returns:
            统计信息
        """
        if not self.event_history:
            return {
                'total_events': 0,
                'recent_events': 0
            }
        
        # 最近24小时事件
        recent = [
            e for e in self.event_history
            if (datetime.now() - e.timestamp) < timedelta(hours=24)
        ]
        
        # 按类型统计
        type_counts = {}
        for event in self.event_history:
            type_name = event.type.value
            type_counts[type_name] = type_counts.get(type_name, 0) + 1
        
        return {
            'total_events': len(self.event_history),
            'recent_events': len(recent),
            'type_counts': type_counts,
            'consecutive_losses': self.consecutive_losses,
            'recent_drawdown': self.recent_drawdown
        }
    
    def reset_statistics(self) -> None:
        """重置统计"""
        self.consecutive_losses = 0
        self.recent_pnl = []
        self.recent_drawdown = 0.0
        logger.info("统计已重置")
    
    def set_baseline_performance(self, performance: float) -> None:
        """
        设置基准表现
        
        Args:
            performance: 基准表现
        """
        self.baseline_performance = performance
        logger.info(f"基准表现已设置: {performance:.4f}")
