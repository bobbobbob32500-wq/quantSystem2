# -*- coding: utf-8 -*-
"""
分策略回测框架
分别测试回踩、突破、横盘三种策略，找出主策略
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass

from src.core.logger import get_logger
from src.core.database import DatabaseManager
from src.modules.optimized_buy_signals import OptimizedBuySignals, IntradayData
from src.modules.risk_controller import RiskController

logger = get_logger("strategy_backtest")


@dataclass
class BacktestResult:
    """回测结果数据结构"""
    strategy_name: str
    total_trades: int
    win_rate: float
    profit_loss_ratio: float
    expected_return: float
    max_drawdown: float
    max_consecutive_losses: int
    avg_hold_days: float
    sharpe_ratio: float
    total_return: float
    # 新增：交易频率维度
    trades_per_month: float
    capital_utilization: float
    # 新增：收益稳定性
    std_return: float
    # 新增：综合评分
    composite_score: float


class StrategyBacktester:
    """分策略回测器"""
    
    def __init__(self, db: DatabaseManager = None, initial_capital: float = 100000):
        """
        初始化回测器
        
        Args:
            db: 数据库管理器
            initial_capital: 初始资金
        """
        if db is None:
            db = DatabaseManager()
        
        self.db = db
        self.initial_capital = initial_capital
        self.signal_detector = OptimizedBuySignals()
        self.risk_controller = RiskController(db=db)
        
        logger.info(f"分策略回测器初始化完成，初始资金: {initial_capital}")
    
    def get_stock_list(self) -> List[str]:
        """
        获取股票列表
        
        Returns:
            股票代码列表
        """
        sql = """
            SELECT DISTINCT ts_code 
            FROM stock_daily 
            WHERE trade_date >= ?
            ORDER BY ts_code
        """
        
        start_date = (datetime.now() - timedelta(days=120)).strftime("%Y%m%d")
        results = self.db.query(sql, (start_date,))
        
        return [r['ts_code'] for r in results]
    
    def get_stock_data(self, ts_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        """
        获取股票日线数据
        
        Args:
            ts_code: 股票代码
            start_date: 开始日期
            end_date: 结束日期
        
        Returns:
            日线数据DataFrame
        """
        sql = """
            SELECT trade_date, open, close, high, low, vol, amount, pct_chg
            FROM stock_daily
            WHERE ts_code = ? AND trade_date >= ? AND trade_date <= ?
            ORDER BY trade_date
        """
        
        results = self.db.query(sql, (ts_code, start_date, end_date))
        
        if not results:
            return pd.DataFrame()
        
        df = pd.DataFrame(results)
        df['trade_date'] = pd.to_datetime(df['trade_date'], format='%Y%m%d')
        
        return df
    
    def simulate_signal_only(self, df: pd.DataFrame, signal_type: str) -> List[Dict]:
        """
        模拟单一信号策略
        
        Args:
            df: 日线数据
            signal_type: 信号类型（pullback/breakout/consolidation）
        
        Returns:
            交易记录列表
        """
        if df.empty or len(df) < 30:
            return []
        
        trades = []
        position = None  # 当前持仓
        
        for i in range(30, len(df)):
            current_date = df.iloc[i]['trade_date']
            current_price = df.iloc[i]['close']
            
            # 构建分时数据（用日线模拟）
            window = 30
            price_data = df.iloc[i-window:i]['close'].values
            volume_data = df.iloc[i-window:i]['vol'].values
            high_data = df.iloc[i-window:i]['high'].values
            low_data = df.iloc[i-window:i]['low'].values
            
            intraday_data = IntradayData(
                price=price_data,
                volume=volume_data,
                high=high_data,
                low=low_data,
                timestamp=df.iloc[i-window:i]['trade_date'].values
            )
            
            # 检测指定类型的信号
            signal = None
            if signal_type == "pullback":
                signal = self.signal_detector.signal_pullback(intraday_data)
            elif signal_type == "breakout":
                signal = self.signal_detector.signal_breakout(intraday_data)
            elif signal_type == "consolidation":
                signal = self.signal_detector.signal_consolidation(intraday_data)
            
            # 买入逻辑
            if position is None and signal and signal.signal:
                position = {
                    'entry_date': current_date,
                    'entry_price': current_price,
                    'signal_type': signal_type,
                }
            
            # 卖出逻辑（策略特定退出逻辑，避免污染比较）
            elif position is not None:
                hold_days = (current_date - position['entry_date']).days
                pnl_pct = (current_price - position['entry_price']) / position['entry_price'] * 100
                
                # 根据策略类型使用不同的退出逻辑
                should_sell = False
                
                if signal_type == "breakout":
                    # 突破策略：趋势跟踪，需要长持
                    # 止损：-8%（给更多空间）
                    # 跟踪止盈：从最高点回撤5%
                    if pnl_pct < -8:
                        should_sell = True
                    elif position.get('highest_price', 0) == 0:
                        position['highest_price'] = current_price
                    else:
                        position['highest_price'] = max(position['highest_price'], current_price)
                        if current_price < position['highest_price'] * 0.95:
                            should_sell = True
                
                elif signal_type == "pullback":
                    # 回踩策略：短反弹，短持
                    # 止损：-5%
                    # 止盈：+3% 到 +5%
                    if pnl_pct < -5 or pnl_pct > 5:
                        should_sell = True
                    elif hold_days >= 3:  # 最多持有3天
                        should_sell = True
                
                elif signal_type == "consolidation":
                    # 横盘策略：中等持仓
                    # 止损：-6%
                    # 止盈：+8%
                    if pnl_pct < -6 or pnl_pct > 8:
                        should_sell = True
                    elif hold_days >= 7:  # 最多持有7天
                        should_sell = True
                
                if should_sell:
                    trades.append({
                        'entry_date': position['entry_date'],
                        'exit_date': current_date,
                        'entry_price': position['entry_price'],
                        'exit_price': current_price,
                        'pnl': pnl_pct,
                        'hold_days': hold_days,
                        'signal_type': signal_type,
                    })
                    position = None
        
        return trades
    
    def backtest_strategy(self, signal_type: str, 
                         start_date: str = None,
                         end_date: str = None,
                         stock_list: List[str] = None) -> BacktestResult:
        """
        回测单一策略
        
        Args:
            signal_type: 信号类型
            start_date: 开始日期
            end_date: 结束日期
            stock_list: 股票列表
        
        Returns:
            回测结果
        """
        logger.info(f"开始回测 {signal_type} 策略...")
        
        # 设置日期范围
        if end_date is None:
            end_date = datetime.now().strftime("%Y%m%d")
        if start_date is None:
            start_date = (datetime.now() - timedelta(days=90)).strftime("%Y%m%d")
        
        # 获取股票列表
        if stock_list is None:
            stock_list = self.get_stock_list()
        
        # 收集所有交易
        all_trades = []
        
        for i, ts_code in enumerate(stock_list):
            if i % 100 == 0:
                logger.info(f"已处理 {i}/{len(stock_list)} 只股票")
            
            try:
                df = self.get_stock_data(ts_code, start_date, end_date)
                trades = self.simulate_signal_only(df, signal_type)
                all_trades.extend(trades)
            except Exception as e:
                logger.debug(f"处理 {ts_code} 失败: {e}")
                continue
        
        # 计算回测指标
        result = self._calculate_backtest_metrics(all_trades, signal_type)
        
        logger.info(f"{signal_type} 策略回测完成: 胜率 {result.win_rate}%, 期望收益 {result.expected_return}%")
        
        return result
    
    def _calculate_backtest_metrics(self, trades: List[Dict], strategy_name: str) -> BacktestResult:
        """
        计算回测指标
        
        Args:
            trades: 交易列表
            strategy_name: 策略名称
        
        Returns:
            回测结果
        """
        if not trades:
            return BacktestResult(
                strategy_name=strategy_name,
                total_trades=0,
                win_rate=0,
                profit_loss_ratio=0,
                expected_return=0,
                max_drawdown=0,
                max_consecutive_losses=0,
                avg_hold_days=0,
                sharpe_ratio=0,
                total_return=0,
            )
        
        # 基础指标
        total_trades = len(trades)
        profits = [t['pnl'] for t in trades if t['pnl'] > 0]
        losses = [abs(t['pnl']) for t in trades if t['pnl'] < 0]
        
        win_count = len(profits)
        loss_count = len(losses)
        win_rate = win_count / total_trades * 100 if total_trades > 0 else 0
        
        avg_profit = sum(profits) / len(profits) if profits else 0
        avg_loss = sum(losses) / len(losses) if losses else 0
        
        profit_loss_ratio = avg_profit / avg_loss if avg_loss > 0 else 0
        
        # 期望收益
        expected_return = (win_rate / 100) * avg_profit - ((100 - win_rate) / 100) * avg_loss
        
        # 最大回撤（资金曲线）
        equity = 1.0
        equity_curve = [1.0]
        
        for t in sorted(trades, key=lambda x: x['entry_date']):
            equity *= (1 + t['pnl'] / 100)
            equity_curve.append(equity)
        
        peak = equity_curve[0]
        max_drawdown = 0
        for v in equity_curve:
            peak = max(peak, v)
            dd = (peak - v) / peak * 100
            max_drawdown = max(max_drawdown, dd)
        
        # 最大连续亏损
        sorted_trades = sorted(trades, key=lambda x: x['entry_date'])
        max_consecutive_losses = 0
        current_consecutive = 0
        for t in sorted_trades:
            if t['pnl'] < 0:
                current_consecutive += 1
                max_consecutive_losses = max(max_consecutive_losses, current_consecutive)
            else:
                current_consecutive = 0
        
        # 平均持仓天数
        avg_hold_days = sum(t['hold_days'] for t in trades) / len(trades) if trades else 0
        
        # 夏普比率（简化）
        returns = [t['pnl'] for t in trades]
        avg_return = sum(returns) / len(returns) if returns else 0
        std_return = np.std(returns) if len(returns) > 1 else 0
        sharpe_ratio = avg_return / std_return * np.sqrt(252) if std_return > 0 else 0
        
        # 总收益
        total_return = (equity_curve[-1] - 1) * 100 if equity_curve else 0
        
        # 新增：交易频率维度
        # 假设回测周期为90天
        backtest_days = 90
        trades_per_month = total_trades / (backtest_days / 30) if backtest_days > 0 else 0
        
        # 资金利用率（简化：交易次数越多，利用率越高）
        capital_utilization = min(1.0, trades_per_month / 10)  # 假设每月10次为满利用率
        
        # 新增：收益稳定性
        std_return = np.std(returns) if len(returns) > 1 else 0
        
        # 新增：综合评分（关键）
        # 评分 = 期望收益*0.4 + 夏普比率*0.3 - 最大回撤*0.2 + 交易频率*0.1
        composite_score = (
            expected_return * 0.4 +
            sharpe_ratio * 0.3 -
            max_drawdown * 0.002 +  # 回撤权重降低，因为已经是负数
            trades_per_month * 0.1
        )
        
        return BacktestResult(
            strategy_name=strategy_name,
            total_trades=total_trades,
            win_rate=round(win_rate, 2),
            profit_loss_ratio=round(profit_loss_ratio, 2),
            expected_return=round(expected_return, 3),
            max_drawdown=round(max_drawdown, 2),
            max_consecutive_losses=max_consecutive_losses,
            avg_hold_days=round(avg_hold_days, 1),
            sharpe_ratio=round(sharpe_ratio, 2),
            total_return=round(total_return, 2),
            trades_per_month=round(trades_per_month, 2),
            capital_utilization=round(capital_utilization, 2),
            std_return=round(std_return, 2),
            composite_score=round(composite_score, 3),
        )
    
    def backtest_all_strategies(self, start_date: str = None,
                               end_date: str = None) -> Dict[str, BacktestResult]:
        """
        回测所有策略并对比
        
        Args:
            start_date: 开始日期
            end_date: 结束日期
        
        Returns:
            各策略回测结果
        """
        logger.info("=" * 80)
        logger.info("开始分策略回测...")
        logger.info("=" * 80)
        
        results = {}
        
        # 回测回踩策略
        results['pullback'] = self.backtest_strategy("pullback", start_date, end_date)
        
        # 回测突破策略
        results['breakout'] = self.backtest_strategy("breakout", start_date, end_date)
        
        # 回测横盘策略
        results['consolidation'] = self.backtest_strategy("consolidation", start_date, end_date)
        
        return results
    
    def generate_comparison_report(self, results: Dict[str, BacktestResult]) -> str:
        """
        生成策略对比报告
        
        Args:
            results: 各策略回测结果
        
        Returns:
            报告文本
        """
        # 计算标准化评分（修复量纲污染）
        results_with_scores = self._calculate_normalized_scores(results)
        
        lines = [
            "=" * 120,
            "分策略回测对比报告",
            f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "=" * 120,
            "",
            "【策略对比表】（按标准化综合评分排序）",
            "-" * 120,
            f"{'策略':<15} {'交易次数':>8} {'月交易数':>8} {'胜率':>8} {'盈亏比':>8} {'期望收益':>10} {'总收益':>10} {'最大回撤':>10} {'夏普':>8} {'置信度':>8} {'综合评分':>10}",
            "-" * 120,
        ]
        
        # 按标准化评分排序
        sorted_results = sorted(results_with_scores.items(), key=lambda x: x[1]['normalized_score'], reverse=True)
        
        for strategy_name, result_dict in sorted_results:
            result = result_dict['result']
            confidence = result_dict['confidence']
            normalized_score = result_dict['normalized_score']
            
            # 标记最佳策略
            marker = " ✅" if normalized_score == sorted_results[0][1]['normalized_score'] else ""
            
            lines.append(
                f"{strategy_name:<15} {result.total_trades:>8} "
                f"{result.trades_per_month:>8.1f} {result.win_rate:>7.1f}% {result.profit_loss_ratio:>8.2f} "
                f"{result.expected_return:>9.3f}% {result.total_return:>9.2f}% "
                f"{result.max_drawdown:>9.2f}% {result.sharpe_ratio:>8.2f} "
                f"{confidence:>7.2f} {normalized_score:>10.3f}{marker}"
            )
        
        lines.extend([
            "-" * 120,
            "",
            "【评分说明】",
            "-" * 120,
            "1. 标准化处理：所有指标归一化到[0,1]区间，避免量纲污染",
            "2. 置信度约束：交易次数<30时降低评分，避免统计不可靠",
            "3. 综合评分 = 标准化(期望收益)×0.4 + 标准化(夏普)×0.3 + 标准化(-回撤)×0.2 + 标准化(频率)×0.1",
            "",
            "【详细分析】",
            "-" * 120,
        ])
        
        # 找出主策略
        best_strategy = sorted_results[0][0]
        best_result_dict = sorted_results[0][1]
        best_result = best_result_dict['result']
        
        lines.extend([
            f"主策略推荐: {best_strategy}（标准化综合评分最高）",
            f"  - 综合评分: {best_result_dict['normalized_score']:.3f}",
            f"  - 置信度: {best_result_dict['confidence']:.2f}（交易次数: {best_result.total_trades}）",
            f"  - 期望收益: {best_result.expected_return}%",
            f"  - 总收益: {best_result.total_return}%",
            f"  - 月交易数: {best_result.trades_per_month}",
            f"  - 胜率: {best_result.win_rate}%",
            f"  - 盈亏比: {best_result.profit_loss_ratio}",
            f"  - 最大回撤: {best_result.max_drawdown}%",
            f"  - 夏普比率: {best_result.sharpe_ratio}",
            "",
        ])
        
        # 策略权重建议
        lines.extend([
            "【策略权重建议】（基于标准化评分）",
            "-" * 120,
        ])
        
        total_score = sum(r['normalized_score'] for r in results_with_scores.values() if r['normalized_score'] > 0)
        
        if total_score > 0:
            for strategy_name, result_dict in sorted_results:
                if result_dict['normalized_score'] > 0:
                    weight = result_dict['normalized_score'] / total_score
                    lines.append(f"{strategy_name}: {weight*100:.1f}% （评分: {result_dict['normalized_score']:.3f}, 置信度: {result_dict['confidence']:.2f}）")
        else:
            lines.append("所有策略综合评分为负，建议暂停交易")
        
        lines.extend([
            "",
            "=" * 120,
        ])
        
        return "\n".join(lines)
    
    def _calculate_normalized_scores(self, results: Dict[str, BacktestResult]) -> Dict:
        """
        计算标准化评分（修复量纲污染）
        
        Args:
            results: 各策略回测结果
        
        Returns:
            包含标准化评分的结果字典
        """
        if not results:
            return {}
        
        # 提取所有指标值
        expected_returns = [r.expected_return for r in results.values()]
        sharpe_ratios = [r.sharpe_ratio for r in results.values()]
        max_drawdowns = [r.max_drawdown for r in results.values()]
        trades_per_months = [r.trades_per_month for r in results.values()]
        
        # 标准化函数
        def normalize(values):
            min_val = min(values)
            max_val = max(values)
            if max_val - min_val < 1e-9:
                return [0.5] * len(values)  # 所有值相同，返回0.5
            return [(v - min_val) / (max_val - min_val) for v in values]
        
        # 标准化各指标
        norm_expected_returns = normalize(expected_returns)
        norm_sharpe_ratios = normalize(sharpe_ratios)
        norm_drawdowns = normalize([-d for d in max_drawdowns])  # 回撤越小越好，取负
        norm_trades_per_months = normalize(trades_per_months)
        
        # 计算标准化评分
        results_with_scores = {}
        for i, (strategy_name, result) in enumerate(results.items()):
            # 置信度约束（关键：避免少量高收益的统计幻觉）
            if result.total_trades < 30:
                confidence = result.total_trades / 30  # 线性惩罚
            else:
                confidence = 1.0
            
            # 标准化综合评分
            normalized_score = (
                norm_expected_returns[i] * 0.4 +
                norm_sharpe_ratios[i] * 0.3 +
                norm_drawdowns[i] * 0.2 +
                norm_trades_per_months[i] * 0.1
            ) * confidence  # 应用置信度约束
            
            results_with_scores[strategy_name] = {
                'result': result,
                'normalized_score': normalized_score,
                'confidence': confidence,
            }
        
        return results_with_scores
        """
        生成策略对比报告
        
        Args:
            results: 各策略回测结果
        
        Returns:
            报告文本
        """
        lines = [
            "=" * 120,
            "分策略回测对比报告",
            f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "=" * 120,
            "",
            "【策略对比表】（按综合评分排序）",
            "-" * 120,
            f"{'策略':<15} {'交易次数':>8} {'月交易数':>8} {'胜率':>8} {'盈亏比':>8} {'期望收益':>10} {'总收益':>10} {'最大回撤':>10} {'夏普':>8} {'综合评分':>10}",
            "-" * 120,
        ]
        
        # 按综合评分排序（关键改进）
        sorted_results = sorted(results.items(), key=lambda x: x[1].composite_score, reverse=True)
        
        for strategy_name, result in sorted_results:
            # 标记最佳策略
            marker = " ✅" if result == sorted_results[0][1] else ""
            
            lines.append(
                f"{strategy_name:<15} {result.total_trades:>8} "
                f"{result.trades_per_month:>8.1f} {result.win_rate:>7.1f}% {result.profit_loss_ratio:>8.2f} "
                f"{result.expected_return:>9.3f}% {result.total_return:>9.2f}% "
                f"{result.max_drawdown:>9.2f}% {result.sharpe_ratio:>8.2f} "
                f"{result.composite_score:>10.3f}{marker}"
            )
        
        lines.extend([
            "-" * 120,
            "",
            "【详细分析】",
            "-" * 120,
        ])
        
        # 找出主策略（基于综合评分）
        best_strategy = sorted_results[0][0]
        best_result = sorted_results[0][1]
        
        lines.extend([
            f"主策略推荐: {best_strategy}（综合评分最高）",
            f"  - 综合评分: {best_result.composite_score}",
            f"  - 期望收益: {best_result.expected_return}%",
            f"  - 总收益: {best_result.total_return}%",
            f"  - 月交易数: {best_result.trades_per_month}",
            f"  - 胜率: {best_result.win_rate}%",
            f"  - 盈亏比: {best_result.profit_loss_ratio}",
            f"  - 最大回撤: {best_result.max_drawdown}%",
            f"  - 夏普比率: {best_result.sharpe_ratio}",
            "",
        ])
        
        # 策略权重建议（基于综合评分）
        lines.extend([
            "【策略权重建议】（基于综合评分）",
            "-" * 120,
        ])
        
        total_score = sum(r.composite_score for r in results.values() if r.composite_score > 0)
        
        if total_score > 0:
            for strategy_name, result in sorted_results:
                if result.composite_score > 0:
                    weight = result.composite_score / total_score
                    lines.append(f"{strategy_name}: {weight*100:.1f}% （评分: {result.composite_score}）")
        else:
            lines.append("所有策略综合评分为负，建议暂停交易")
        
        lines.extend([
            "",
            "【评分公式说明】",
            "-" * 120,
            "综合评分 = 期望收益×0.4 + 夏普比率×0.3 - 最大回撤×0.002 + 月交易数×0.1",
            "",
            "=" * 120,
        ])
        
        return "\n".join(lines)


def run_strategy_backtest(start_date: str = None, end_date: str = None) -> str:
    """
    运行分策略回测（便捷函数）
    
    Args:
        start_date: 开始日期
        end_date: 结束日期
    
    Returns:
        对比报告
    """
    backtester = StrategyBacktester()
    results = backtester.backtest_all_strategies(start_date, end_date)
    return backtester.generate_comparison_report(results)
