# -*- coding: utf-8 -*-
"""
绩效指标计算
"""

import numpy as np
import pandas as pd
from typing import Dict, List
from src.core.logger import get_logger

logger = get_logger("backtest_metrics")


def compute_metrics(equity_curve: List[Dict], 
                   trade_history: List[Dict],
                   risk_free_rate: float = 0.03) -> Dict:
    """
    计算绩效指标
    
    Args:
        equity_curve: 净值曲线
        trade_history: 交易历史
        risk_free_rate: 无风险利率
    
    Returns:
        绩效指标字典
    """
    if not equity_curve:
        return {}
    
    equity_values = [e['total_value'] for e in equity_curve]
    equity_series = pd.Series(equity_values)
    
    returns = equity_series.pct_change().dropna()
    
    initial_capital = equity_values[0]
    final_capital = equity_values[-1]
    total_return = (final_capital - initial_capital) / initial_capital
    
    days = len(equity_values)
    annual_return = (1 + total_return) ** (252 / days) - 1 if days > 0 else 0
    
    if len(returns) > 1 and returns.std() > 0:
        sharpe_ratio = (returns.mean() * 252 - risk_free_rate) / (returns.std() * np.sqrt(252))
    else:
        sharpe_ratio = 0.0
    
    max_drawdown = calculate_max_drawdown(equity_values)
    
    calmar_ratio = annual_return / abs(max_drawdown) if max_drawdown != 0 else 0.0
    
    volatility = returns.std() * np.sqrt(252) if len(returns) > 1 else 0.0
    
    buy_trades = [t for t in trade_history if t['action'] == 'buy']
    sell_trades = [t for t in trade_history if t['action'] == 'sell']
    
    total_trades = len(buy_trades)
    win_trades = len([t for t in sell_trades if t.get('profit', 0) > 0])
    lose_trades = len([t for t in sell_trades if t.get('profit', 0) < 0])
    
    win_rate = win_trades / total_trades if total_trades > 0 else 0.0
    
    total_profit = sum(t.get('profit', 0) for t in sell_trades if t.get('profit', 0) > 0)
    total_loss = abs(sum(t.get('profit', 0) for t in sell_trades if t.get('profit', 0) < 0))
    profit_factor = total_profit / total_loss if total_loss > 0 else 0.0
    
    hold_days_list = [t.get('hold_days', 0) for t in sell_trades]
    avg_hold_days = np.mean(hold_days_list) if hold_days_list else 0.0
    
    profits = [t.get('profit_pct', 0) for t in sell_trades]
    avg_profit_pct = np.mean(profits) if profits else 0.0
    max_profit_pct = max(profits) if profits else 0.0
    max_loss_pct = min(profits) if profits else 0.0
    
    return {
        'total_return': total_return,
        'annual_return': annual_return,
        'sharpe_ratio': sharpe_ratio,
        'max_drawdown': max_drawdown,
        'calmar_ratio': calmar_ratio,
        'volatility': volatility,
        'total_trades': total_trades,
        'win_trades': win_trades,
        'lose_trades': lose_trades,
        'win_rate': win_rate,
        'profit_factor': profit_factor,
        'avg_hold_days': avg_hold_days,
        'avg_profit_pct': avg_profit_pct,
        'max_profit_pct': max_profit_pct,
        'max_loss_pct': max_loss_pct,
        'initial_capital': initial_capital,
        'final_capital': final_capital,
    }


def calculate_max_drawdown(equity_values: List[float]) -> float:
    """计算最大回撤"""
    if not equity_values:
        return 0.0
    
    peak = equity_values[0]
    max_dd = 0.0
    
    for value in equity_values:
        peak = max(peak, value)
        dd = (value - peak) / peak
        max_dd = min(max_dd, dd)
    
    return max_dd


def calculate_drawdown_series(equity_values: List[float]) -> List[float]:
    """计算回撤序列"""
    if not equity_values:
        return []
    
    peak = equity_values[0]
    drawdowns = []
    
    for value in equity_values:
        peak = max(peak, value)
        dd = (value - peak) / peak
        drawdowns.append(dd)
    
    return drawdowns


def log_metrics(metrics: Dict) -> None:
    """记录绩效指标到日志"""
    logger.info("=" * 70)
    logger.info("回测绩效报告")
    logger.info("=" * 70)
    
    logger.info("【收益指标】")
    logger.info(f"  总收益率: {metrics.get('total_return', 0)*100:.2f}%")
    logger.info(f"  年化收益率: {metrics.get('annual_return', 0)*100:.2f}%")
    logger.info(f"  夏普比率: {metrics.get('sharpe_ratio', 0):.3f}")
    logger.info(f"  最大回撤: {metrics.get('max_drawdown', 0)*100:.2f}%")
    logger.info(f"  卡尔玛比率: {metrics.get('calmar_ratio', 0):.3f}")
    logger.info(f"  波动率: {metrics.get('volatility', 0)*100:.2f}%")
    
    logger.info("【交易统计】")
    logger.info(f"  总交易次数: {metrics.get('total_trades', 0)}次")
    logger.info(f"  盈利次数: {metrics.get('win_trades', 0)}次")
    logger.info(f"  亏损次数: {metrics.get('lose_trades', 0)}次")
    logger.info(f"  胜率: {metrics.get('win_rate', 0)*100:.2f}%")
    logger.info(f"  盈亏比: {metrics.get('profit_factor', 0):.3f}")
    
    logger.info("【持仓分析】")
    logger.info(f"  平均持仓天数: {metrics.get('avg_hold_days', 0):.1f}天")
    logger.info(f"  平均盈亏: {metrics.get('avg_profit_pct', 0)*100:.2f}%")
    logger.info(f"  最大盈利: {metrics.get('max_profit_pct', 0)*100:.2f}%")
    logger.info(f"  最大亏损: {metrics.get('max_loss_pct', 0)*100:.2f}%")
    
    logger.info("【资金信息】")
    logger.info(f"  初始资金: {metrics.get('initial_capital', 0):,.2f}")
    logger.info(f"  最终资金: {metrics.get('final_capital', 0):,.2f}")
    
    logger.info("=" * 70)


def print_metrics(metrics: Dict) -> None:
    """打印绩效指标（保留用于命令行输出）"""
    log_metrics(metrics)


def format_metrics_report(metrics: Dict) -> str:
    """格式化绩效指标为字符串"""
    lines = [
        "=" * 70,
        "回测绩效报告",
        "=" * 70,
        "",
        "【收益指标】",
        f"  总收益率: {metrics.get('total_return', 0)*100:.2f}%",
        f"  年化收益率: {metrics.get('annual_return', 0)*100:.2f}%",
        f"  夏普比率: {metrics.get('sharpe_ratio', 0):.3f}",
        f"  最大回撤: {metrics.get('max_drawdown', 0)*100:.2f}%",
        f"  卡尔玛比率: {metrics.get('calmar_ratio', 0):.3f}",
        f"  波动率: {metrics.get('volatility', 0)*100:.2f}%",
        "",
        "【交易统计】",
        f"  总交易次数: {metrics.get('total_trades', 0)}次",
        f"  盈利次数: {metrics.get('win_trades', 0)}次",
        f"  亏损次数: {metrics.get('lose_trades', 0)}次",
        f"  胜率: {metrics.get('win_rate', 0)*100:.2f}%",
        f"  盈亏比: {metrics.get('profit_factor', 0):.3f}",
        "",
        "【持仓分析】",
        f"  平均持仓天数: {metrics.get('avg_hold_days', 0):.1f}天",
        f"  平均盈亏: {metrics.get('avg_profit_pct', 0)*100:.2f}%",
        f"  最大盈利: {metrics.get('max_profit_pct', 0)*100:.2f}%",
        f"  最大亏损: {metrics.get('max_loss_pct', 0)*100:.2f}%",
        "",
        "【资金信息】",
        f"  初始资金: {metrics.get('initial_capital', 0):,.2f}",
        f"  最终资金: {metrics.get('final_capital', 0):,.2f}",
        "=" * 70,
    ]
    return "\n".join(lines)
