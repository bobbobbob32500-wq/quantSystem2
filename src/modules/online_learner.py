# -*- coding: utf-8 -*-
"""
在线学习模块（Online Learning）
实时更新Pattern，适应市场变化
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Callable
from dataclasses import dataclass
from collections import deque

from src.core.logger import get_logger

logger = get_logger("online_learner")


@dataclass
class OnlinePattern:
    """在线Pattern数据结构"""
    conditions: Dict
    sample_size: int
    win_rate: float
    expected_return: float
    last_update: datetime
    
    # 增量统计
    sum_pnl: float
    sum_pnl_sq: float
    win_count: int
    loss_count: int


class OnlineLearner:
    """在线学习器"""
    
    def __init__(self,
                 max_history: int = 1000,
                 decay_factor: float = 0.95,
                 min_samples: int = 20):
        """
        初始化在线学习器
        
        Args:
            max_history: 最大历史记录数
            decay_factor: 衰减因子（旧数据权重衰减）
            min_samples: 最小样本数
        """
        self.max_history = max_history
        self.decay_factor = decay_factor
        self.min_samples = min_samples
        
        # Pattern存储
        self.patterns: Dict[str, OnlinePattern] = {}
        
        # 历史数据
        self.history = deque(maxlen=max_history)
        
        logger.info("在线学习器初始化完成")
    
    def update(self, trade: Dict) -> None:
        """
        增量更新（核心方法）
        
        Args:
            trade: 新交易记录
        """
        # 添加到历史
        self.history.append(trade)
        
        # 提取Pattern条件
        pattern_key = self._extract_pattern_key(trade)
        
        # 更新或创建Pattern
        if pattern_key in self.patterns:
            self._update_pattern(pattern_key, trade)
        else:
            self._create_pattern(pattern_key, trade)
        
        logger.debug(f"在线更新: {pattern_key}")
    
    def _extract_pattern_key(self, trade: Dict) -> str:
        """
        提取Pattern键
        
        Args:
            trade: 交易记录
        
        Returns:
            Pattern键
        """
        # 简化：使用信号类型和RSI区间
        signal_type = trade.get('signal_type', 'unknown')
        rsi = trade.get('rsi', 50)
        
        # RSI分箱
        if rsi < 50:
            rsi_bin = '<50'
        elif rsi < 55:
            rsi_bin = '50-55'
        elif rsi < 60:
            rsi_bin = '55-60'
        elif rsi < 65:
            rsi_bin = '60-65'
        else:
            rsi_bin = '>65'
        
        return f"{signal_type}_{rsi_bin}"
    
    def _create_pattern(self, pattern_key: str, trade: Dict) -> None:
        """
        创建新Pattern
        
        Args:
            pattern_key: Pattern键
            trade: 交易记录
        """
        pnl = trade.get('pnl', 0)
        
        self.patterns[pattern_key] = OnlinePattern(
            conditions={'pattern_key': pattern_key},
            sample_size=1,
            win_rate=1.0 if pnl > 0 else 0.0,
            expected_return=pnl,
            last_update=datetime.now(),
            sum_pnl=pnl,
            sum_pnl_sq=pnl ** 2,
            win_count=1 if pnl > 0 else 0,
            loss_count=1 if pnl < 0 else 0
        )
    
    def _update_pattern(self, pattern_key: str, trade: Dict) -> None:
        """
        增量更新Pattern
        
        Args:
            pattern_key: Pattern键
            trade: 交易记录
        """
        pattern = self.patterns[pattern_key]
        pnl = trade.get('pnl', 0)
        
        # 应用衰减
        pattern.sum_pnl *= self.decay_factor
        pattern.sum_pnl_sq *= self.decay_factor
        pattern.win_count = int(pattern.win_count * self.decay_factor)
        pattern.loss_count = int(pattern.loss_count * self.decay_factor)
        
        # 添加新数据
        pattern.sum_pnl += pnl
        pattern.sum_pnl_sq += pnl ** 2
        if pnl > 0:
            pattern.win_count += 1
        else:
            pattern.loss_count += 1
        
        # 更新统计
        pattern.sample_size = pattern.win_count + pattern.loss_count
        
        if pattern.sample_size > 0:
            pattern.win_rate = pattern.win_count / pattern.sample_size
            pattern.expected_return = pattern.sum_pnl / pattern.sample_size
        
        pattern.last_update = datetime.now()
    
    def get_pattern(self, pattern_key: str) -> Optional[OnlinePattern]:
        """
        获取Pattern
        
        Args:
            pattern_key: Pattern键
        
        Returns:
            Pattern
        """
        return self.patterns.get(pattern_key)
    
    def get_all_patterns(self) -> List[OnlinePattern]:
        """
        获取所有Pattern
        
        Returns:
            Pattern列表
        """
        return list(self.patterns.values())
    
    def get_best_pattern(self) -> Optional[OnlinePattern]:
        """
        获取最佳Pattern
        
        Returns:
            最佳Pattern
        """
        valid_patterns = [
            p for p in self.patterns.values()
            if p.sample_size >= self.min_samples and p.expected_return > 0
        ]
        
        if not valid_patterns:
            return None
        
        # 按期望收益排序
        return max(valid_patterns, key=lambda x: x.expected_return)
    
    def should_trade(self, trade: Dict) -> bool:
        """
        判断是否应该交易
        
        Args:
            trade: 交易记录
        
        Returns:
            是否应该交易
        """
        pattern_key = self._extract_pattern_key(trade)
        pattern = self.get_pattern(pattern_key)
        
        if pattern is None:
            return False
        
        # 条件：样本数足够 + 期望收益>0 + 胜率>50%
        return (
            pattern.sample_size >= self.min_samples and
            pattern.expected_return > 0 and
            pattern.win_rate > 0.5
        )
    
    def get_statistics(self) -> Dict:
        """
        获取统计信息
        
        Returns:
            统计信息
        """
        patterns = self.get_all_patterns()
        
        if not patterns:
            return {
                'total_patterns': 0,
                'valid_patterns': 0,
                'best_pattern': None
            }
        
        valid_patterns = [
            p for p in patterns
            if p.sample_size >= self.min_samples
        ]
        
        profit_patterns = [
            p for p in valid_patterns
            if p.expected_return > 0
        ]
        
        return {
            'total_patterns': len(patterns),
            'valid_patterns': len(valid_patterns),
            'profit_patterns': len(profit_patterns),
            'best_pattern': self.get_best_pattern(),
            'history_size': len(self.history)
        }
    
    def save_state(self, filepath: str) -> None:
        """
        保存状态
        
        Args:
            filepath: 文件路径
        """
        import pickle
        
        state = {
            'patterns': self.patterns,
            'history': list(self.history)
        }
        
        with open(filepath, 'wb') as f:
            pickle.dump(state, f)
        
        logger.info(f"状态已保存: {filepath}")
    
    def load_state(self, filepath: str) -> None:
        """
        加载状态
        
        Args:
            filepath: 文件路径
        """
        import pickle
        
        with open(filepath, 'rb') as f:
            state = pickle.load(f)
        
        self.patterns = state['patterns']
        self.history = deque(state['history'], maxlen=self.max_history)
        
        logger.info(f"状态已加载: {filepath}")
