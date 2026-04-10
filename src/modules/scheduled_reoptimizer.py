# -*- coding: utf-8 -*-
"""
定时重优化模块（Scheduled Reoptimization）
定期在后台重新优化策略
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Callable
from threading import Thread, Event
import time

from src.core.logger import get_logger
from src.modules.complete_strategy_system import CompleteStrategySystem

logger = get_logger("scheduled_reoptimizer")


class ScheduledReoptimizer:
    """定时重优化器"""
    
    def __init__(self,
                 interval_minutes: int = 30,
                 lookback_days: int = 30,
                 min_improvement: float = 0.1):
        """
        初始化定时重优化器
        
        Args:
            interval_minutes: 重优化间隔（分钟）
            lookback_days: 回看天数
            min_improvement: 最小改进阈值
        """
        self.interval_minutes = interval_minutes
        self.lookback_days = lookback_days
        self.min_improvement = min_improvement
        
        # 策略系统
        self.strategy_system = CompleteStrategySystem()
        
        # 当前策略
        self.current_strategy = None
        self.current_score = 0.0
        
        # 时间记录
        self.last_optimize_time = None
        self.optimize_count = 0
        
        # 后台线程
        self.background_thread = None
        self.stop_event = Event()
        
        # 回调函数
        self.on_strategy_update: Optional[Callable] = None
        
        logger.info(f"定时重优化器初始化完成 (间隔={interval_minutes}分钟)")
    
    def should_reoptimize(self) -> bool:
        """
        检查是否需要重优化
        
        Returns:
            是否需要重优化
        """
        if self.last_optimize_time is None:
            return True
        
        elapsed = datetime.now() - self.last_optimize_time
        return elapsed > timedelta(minutes=self.interval_minutes)
    
    def reoptimize_in_background(self, data: pd.DataFrame) -> None:
        """
        后台重优化（不阻塞主线程）
        
        Args:
            data: 数据
        """
        if self.background_thread and self.background_thread.is_alive():
            logger.warning("后台优化正在进行中，跳过")
            return
        
        def _optimize():
            try:
                self._do_reoptimize(data)
            except Exception as e:
                logger.error(f"后台优化失败: {e}")
        
        self.background_thread = Thread(target=_optimize, daemon=True)
        self.background_thread.start()
        
        logger.info("后台优化已启动")
    
    def _do_reoptimize(self, data: pd.DataFrame) -> None:
        """
        执行重优化
        
        Args:
            data: 数据
        """
        logger.info("开始后台重优化...")
        start_time = time.time()
        
        # 运行完整策略系统
        result = self.strategy_system.run_complete_pipeline(data)
        
        # 检查是否改进
        if result is None:
            logger.warning("优化结果为空")
            return
        
        new_score = float(getattr(result, "composite_score", 0.0) or 0.0)
        
        # 判断是否显著改进
        improvement = (new_score - self.current_score) / max(abs(self.current_score), 0.01)
        
        if improvement > self.min_improvement:
            # 更新策略
            old_strategy = self.current_strategy
            self.current_strategy = result.strategy_func
            self.current_score = new_score
            
            # 触发回调
            if self.on_strategy_update:
                self.on_strategy_update(old_strategy, self.current_strategy)
            
            logger.info(f"策略已更新: 改进={improvement:.2%}, 新分数={new_score:.4f}")
        else:
            logger.info(f"改进不足: {improvement:.2%} < {self.min_improvement:.2%}")
        
        # 更新时间
        self.last_optimize_time = datetime.now()
        self.optimize_count += 1
        
        elapsed = time.time() - start_time
        logger.info(f"后台优化完成: 耗时={elapsed:.2f}秒")
    
    def force_reoptimize(self, data: pd.DataFrame) -> Optional[Dict]:
        """
        强制重优化（同步）
        
        Args:
            data: 数据
        
        Returns:
            优化结果
        """
        logger.info("开始强制重优化...")
        start_time = time.time()
        
        # 运行完整策略系统
        result = self.strategy_system.run_complete_pipeline(data)
        
        if result is None:
            logger.warning("优化结果为空")
            return None
        
        # 更新策略
        old_strategy = self.current_strategy
        self.current_strategy = result.strategy_func
        self.current_score = float(getattr(result, "composite_score", 0.0) or 0.0)
        
        # 触发回调
        if self.on_strategy_update:
            self.on_strategy_update(old_strategy, self.current_strategy)
        
        # 更新时间
        self.last_optimize_time = datetime.now()
        self.optimize_count += 1
        
        elapsed = time.time() - start_time
        logger.info(f"强制优化完成: 耗时={elapsed:.2f}秒")
        
        return {
            'strategy': self.current_strategy,
            'score': self.current_score,
            'elapsed': elapsed,
            'summary': getattr(result, 'summary', {}) or {},
        }
    
    def get_current_strategy(self) -> Optional[Callable]:
        """
        获取当前策略
        
        Returns:
            当前策略函数
        """
        return self.current_strategy
    
    def get_statistics(self) -> Dict:
        """
        获取统计信息
        
        Returns:
            统计信息
        """
        return {
            'interval_minutes': self.interval_minutes,
            'last_optimize_time': self.last_optimize_time,
            'optimize_count': self.optimize_count,
            'current_score': self.current_score,
            'next_optimize_time': (
                self.last_optimize_time + timedelta(minutes=self.interval_minutes)
                if self.last_optimize_time else None
            )
        }
    
    def start_continuous_optimization(self, data_getter: Callable) -> None:
        """
        启动持续优化（后台线程）
        
        Args:
            data_getter: 数据获取函数
        """
        def _continuous():
            while not self.stop_event.is_set():
                try:
                    # 检查是否需要优化
                    if self.should_reoptimize():
                        data = data_getter()
                        if data is not None:
                            self._do_reoptimize(data)
                    
                    # 等待
                    time.sleep(60)  # 每分钟检查一次
                
                except Exception as e:
                    logger.error(f"持续优化错误: {e}")
                    time.sleep(60)
        
        self.stop_event.clear()
        thread = Thread(target=_continuous, daemon=True)
        thread.start()
        
        logger.info("持续优化已启动")
    
    def stop_continuous_optimization(self) -> None:
        """停止持续优化"""
        self.stop_event.set()
        logger.info("持续优化已停止")
