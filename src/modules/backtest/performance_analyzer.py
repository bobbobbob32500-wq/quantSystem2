# -*- coding: utf-8 -*-
"""
绩效分析模块
计算收益率、最大回撤、夏普比率、胜率等核心指标
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass
from collections import defaultdict

from src.core.logger import get_logger

logger = get_logger("performance_analyzer")


@dataclass
class PerformanceMetrics:
    """绩效指标数据类"""
    # 收益指标
    total_return: float = 0.0
    annualized_return: float = 0.0
    daily_returns: List[float] = None
    
    # 风险指标
    max_drawdown: float = 0.0
    max_drawdown_duration: int = 0
    volatility: float = 0.0
    
    # 风险调整收益
    sharpe_ratio: float = 0.0
    sortino_ratio: float = 0.0
    calmar_ratio: float = 0.0
    
    # 交易统计
    total_trades: int = 0
    win_trades: int = 0
    loss_trades: int = 0
    win_rate: float = 0.0
    avg_win: float = 0.0
    avg_loss: float = 0.0
    profit_loss_ratio: float = 0.0
    
    # 持仓统计
    avg_holding_days: float = 0.0
    max_holding_days: float = 0.0
    min_holding_days: float = 0.0
    
    # 资金曲线
    equity_curve: List[Dict] = None
    
    def __post_init__(self):
        if self.daily_returns is None:
            self.daily_returns = []
        if self.equity_curve is None:
            self.equity_curve = []


class PerformanceAnalyzer:
    """绩效分析器"""
    
    def __init__(self, risk_free_rate: float = 0.03):
        """
        初始化
        
        Args:
            risk_free_rate: 无风险收益率（年化），默认3%
        """
        self.risk_free_rate = risk_free_rate
        logger.info(f"绩效分析器初始化，无风险收益率: {risk_free_rate*100:.2f}%")
    
    def analyze(
        self,
        trades: List,
        equity_curve: List[Dict],
        initial_capital: float
    ) -> PerformanceMetrics:
        """
        分析绩效
        
        Args:
            trades: 交易记录列表
            equity_curve: 资金曲线
            initial_capital: 初始资金
        
        Returns:
            绩效指标
        """
        metrics = PerformanceMetrics()
        
        # 1. 计算收益指标
        metrics = self._calculate_return_metrics(
            metrics, equity_curve, initial_capital
        )
        
        # 2. 计算风险指标
        metrics = self._calculate_risk_metrics(metrics, equity_curve)
        
        # 3. 计算风险调整收益
        metrics = self._calculate_risk_adjusted_returns(metrics)
        
        # 4. 计算交易统计
        metrics = self._calculate_trade_statistics(metrics, trades)
        
        # 5. 计算持仓统计
        metrics = self._calculate_holding_statistics(metrics, trades)
        
        metrics.equity_curve = equity_curve
        
        return metrics
    
    def _calculate_return_metrics(
        self,
        metrics: PerformanceMetrics,
        equity_curve: List[Dict],
        initial_capital: float
    ) -> PerformanceMetrics:
        """计算收益指标"""
        if not equity_curve:
            return metrics
        
        # 总收益率
        final_equity = equity_curve[-1].get('equity', initial_capital)
        metrics.total_return = (final_equity - initial_capital) / initial_capital
        
        # 计算日收益率
        daily_returns = []
        for i in range(1, len(equity_curve)):
            prev_equity = equity_curve[i-1].get('equity', initial_capital)
            curr_equity = equity_curve[i].get('equity', initial_capital)
            daily_return = (curr_equity - prev_equity) / prev_equity
            daily_returns.append(daily_return)
        
        metrics.daily_returns = daily_returns
        
        # 年化收益率
        if len(equity_curve) > 1:
            start_date = datetime.strptime(equity_curve[0].get('date', ''), '%Y-%m-%d')
            end_date = datetime.strptime(equity_curve[-1].get('date', ''), '%Y-%m-%d')
            days = (end_date - start_date).days
            
            if days > 0 and (1 + metrics.total_return) > 0:
                # 使用复利公式
                metrics.annualized_return = (1 + metrics.total_return) ** (252 / days) - 1
            elif days > 0:
                metrics.annualized_return = -1.0
        
        return metrics
    
    def _calculate_risk_metrics(
        self,
        metrics: PerformanceMetrics,
        equity_curve: List[Dict]
    ) -> PerformanceMetrics:
        """计算风险指标"""
        if not equity_curve or not metrics.daily_returns:
            return metrics
        
        # 计算最大回撤
        peak = equity_curve[0].get('equity', 0)
        max_drawdown = 0
        max_drawdown_duration = 0
        current_drawdown_duration = 0
        
        for point in equity_curve:
            equity = point.get('equity', 0)
            
            if equity > peak:
                peak = equity
                current_drawdown_duration = 0
            else:
                drawdown = (peak - equity) / peak
                if drawdown > max_drawdown:
                    max_drawdown = drawdown
                    max_drawdown_duration = current_drawdown_duration
                current_drawdown_duration += 1
        
        metrics.max_drawdown = max_drawdown
        metrics.max_drawdown_duration = max_drawdown_duration
        
        # 计算波动率（年化）
        if len(metrics.daily_returns) > 1:
            metrics.volatility = np.std(metrics.daily_returns) * np.sqrt(252)
        
        return metrics
    
    def _calculate_risk_adjusted_returns(
        self,
        metrics: PerformanceMetrics
    ) -> PerformanceMetrics:
        """计算风险调整收益"""
        # 夏普比率
        if metrics.volatility > 0:
            excess_return = metrics.annualized_return - self.risk_free_rate
            metrics.sharpe_ratio = excess_return / metrics.volatility
        
        # Sortino比率（只考虑下行波动）
        if metrics.daily_returns:
            downside_returns = [r for r in metrics.daily_returns if r < 0]
            if downside_returns:
                downside_std = np.std(downside_returns) * np.sqrt(252)
                if downside_std > 0:
                    excess_return = metrics.annualized_return - self.risk_free_rate
                    metrics.sortino_ratio = excess_return / downside_std
        
        # Calmar比率（收益/最大回撤）
        if metrics.max_drawdown > 0:
            metrics.calmar_ratio = metrics.annualized_return / metrics.max_drawdown
        
        return metrics
    
    def _calculate_trade_statistics(
        self,
        metrics: PerformanceMetrics,
        trades: List
    ) -> PerformanceMetrics:
        """计算交易统计"""
        if not trades:
            return metrics
        
        metrics.total_trades = len(trades)
        
        # 分离盈利和亏损交易
        win_trades = [t for t in trades if t.pnl_pct > 0]
        loss_trades = [t for t in trades if t.pnl_pct <= 0]
        
        metrics.win_trades = len(win_trades)
        metrics.loss_trades = len(loss_trades)
        
        # 胜率
        metrics.win_rate = len(win_trades) / len(trades) if trades else 0
        
        # 平均盈亏
        if win_trades:
            metrics.avg_win = np.mean([t.pnl_pct for t in win_trades])
        
        if loss_trades:
            metrics.avg_loss = np.mean([t.pnl_pct for t in loss_trades])
        
        # 盈亏比
        if metrics.avg_loss != 0:
            metrics.profit_loss_ratio = abs(metrics.avg_win / metrics.avg_loss)
        
        return metrics
    
    def _calculate_holding_statistics(
        self,
        metrics: PerformanceMetrics,
        trades: List
    ) -> PerformanceMetrics:
        """计算持仓统计"""
        if not trades:
            return metrics
        
        holding_days = []
        for trade in trades:
            if hasattr(trade, 'holding_minutes') and trade.holding_minutes:
                holding_days.append(trade.holding_minutes / (24 * 60))
            elif trade.entry_time and trade.exit_time:
                days = (trade.exit_time - trade.entry_time).days
                holding_days.append(days)
        
        if holding_days:
            metrics.avg_holding_days = np.mean(holding_days)
            metrics.max_holding_days = max(holding_days)
            metrics.min_holding_days = min(holding_days)
        
        return metrics
    
    def calculate_monthly_returns(
        self,
        equity_curve: List[Dict]
    ) -> pd.DataFrame:
        """
        计算月度收益分布
        
        Returns:
            月度收益DataFrame
        """
        if not equity_curve:
            return pd.DataFrame()
        
        df = pd.DataFrame(equity_curve)
        df['date'] = pd.to_datetime(df['date'])
        df['month'] = df['date'].dt.to_period('M')
        
        monthly_returns = df.groupby('month').agg({
            'equity': ['first', 'last']
        }).reset_index()
        
        monthly_returns.columns = ['month', 'start_equity', 'end_equity']
        monthly_returns['monthly_return'] = (
            monthly_returns['end_equity'] - monthly_returns['start_equity']
        ) / monthly_returns['start_equity']
        
        return monthly_returns
    
    def calculate_weekly_returns(
        self,
        equity_curve: List[Dict]
    ) -> pd.DataFrame:
        """
        计算周度收益分布
        
        Returns:
            周度收益DataFrame
        """
        if not equity_curve:
            return pd.DataFrame()
        
        df = pd.DataFrame(equity_curve)
        df['date'] = pd.to_datetime(df['date'])
        df['week'] = df['date'].dt.to_period('W')
        
        weekly_returns = df.groupby('week').agg({
            'equity': ['first', 'last']
        }).reset_index()
        
        weekly_returns.columns = ['week', 'start_equity', 'end_equity']
        weekly_returns['weekly_return'] = (
            weekly_returns['end_equity'] - weekly_returns['start_equity']
        ) / weekly_returns['start_equity']
        
        return weekly_returns
    
    def generate_report(self, metrics: PerformanceMetrics) -> str:
        """
        生成文本报告
        
        Returns:
            报告字符串
        """
        lines = []
        lines.append("=" * 70)
        lines.append("回测绩效报告")
        lines.append("=" * 70)
        
        lines.append("\n【收益指标】")
        lines.append(f"  总收益率: {metrics.total_return*100:+.2f}%")
        lines.append(f"  年化收益率: {metrics.annualized_return*100:+.2f}%")
        
        lines.append("\n【风险指标】")
        lines.append(f"  最大回撤: {metrics.max_drawdown*100:.2f}%")
        lines.append(f"  回撤持续时间: {metrics.max_drawdown_duration}天")
        lines.append(f"  波动率(年化): {metrics.volatility*100:.2f}%")
        
        lines.append("\n【风险调整收益】")
        lines.append(f"  夏普比率: {metrics.sharpe_ratio:.3f}")
        lines.append(f"  Sortino比率: {metrics.sortino_ratio:.3f}")
        lines.append(f"  Calmar比率: {metrics.calmar_ratio:.3f}")
        
        lines.append("\n【交易统计】")
        lines.append(f"  总交易次数: {metrics.total_trades}")
        lines.append(f"  盈利次数: {metrics.win_trades}")
        lines.append(f"  亏损次数: {metrics.loss_trades}")
        lines.append(f"  胜率: {metrics.win_rate*100:.1f}%")
        lines.append(f"  平均盈利: {metrics.avg_win*100:+.2f}%")
        lines.append(f"  平均亏损: {metrics.avg_loss*100:+.2f}%")
        lines.append(f"  盈亏比: {metrics.profit_loss_ratio:.2f}")
        
        lines.append("\n【持仓统计】")
        lines.append(f"  平均持仓天数: {metrics.avg_holding_days:.1f}")
        lines.append(f"  最长持仓: {metrics.max_holding_days:.1f}天")
        lines.append(f"  最短持仓: {metrics.min_holding_days:.1f}天")
        
        lines.append("=" * 70)
        
        return "\n".join(lines)
    
    def print_report(self, metrics: PerformanceMetrics):
        """打印报告"""
        print(self.generate_report(metrics))

