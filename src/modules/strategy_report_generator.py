# -*- coding: utf-8 -*-
"""
全自动策略分析报告生成器
回测完成后自动生成策略表现分析、问题识别和优化建议
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from collections import defaultdict

from src.core.logger import get_logger
from src.core.database import DatabaseManager

logger = get_logger("strategy_report")


@dataclass
class TradeRecord:
    """交易记录数据结构"""
    stock_code: str
    signal_type: str  # pullback/breakout/consolidation
    entry_time: datetime
    exit_time: datetime
    entry_price: float
    exit_price: float
    pnl: float  # 盈亏比例
    pnl_amount: float  # 盈亏金额
    hold_days: int
    max_drawdown: float
    rsi_at_entry: float
    pullback_at_entry: float
    volume_ratio: float


@dataclass
class Issue:
    """问题诊断数据结构"""
    issue_type: str
    description: str
    severity: str  # low/medium/high
    recommended_action: str
    affected_metric: str


@dataclass
class StrategyReport:
    """策略报告数据结构"""
    performance_metrics: Dict
    signal_statistics: Dict
    trade_distribution: Dict
    issues: List[Issue]
    optimization_suggestions: Dict
    generated_at: datetime


class StrategyReportGenerator:
    """策略分析报告生成器"""
    
    def __init__(self, db: DatabaseManager = None, config: Dict = None):
        """
        初始化报告生成器
        
        Args:
            db: 数据库管理器
            config: 配置参数
        """
        if db is None:
            db = DatabaseManager()
        
        self.db = db
        self.config = config or {}
        
        logger.info("策略分析报告生成器初始化完成")
    
    def run_full_analysis(self, days: int = 30) -> StrategyReport:
        """
        执行完整分析流程
        
        Args:
            days: 分析天数
        
        Returns:
            策略报告
        """
        logger.info(f"开始执行策略分析（最近{days}天）...")
        
        # 1. 计算性能指标
        performance_metrics = self.compute_performance_metrics(days)
        
        # 2. 计算信号统计
        signal_statistics = self.compute_signal_statistics(days)
        
        # 3. 计算交易分布
        trade_distribution = self.compute_trade_distribution(days)
        
        # 4. 问题诊断
        issues = self.detect_issues(performance_metrics, signal_statistics, trade_distribution)
        
        # 5. 生成优化建议
        optimization_suggestions = self.generate_optimization_suggestions(issues, performance_metrics)
        
        # 6. 生成报告
        report = StrategyReport(
            performance_metrics=performance_metrics,
            signal_statistics=signal_statistics,
            trade_distribution=trade_distribution,
            issues=issues,
            optimization_suggestions=optimization_suggestions,
            generated_at=datetime.now()
        )
        
        logger.info("策略分析完成")
        
        return report
    
    def compute_performance_metrics(self, days: int = 30) -> Dict:
        """
        计算性能指标
        
        包括：
        - 胜率
        - 盈亏比
        - 期望收益
        - 最大回撤
        - 最大连续亏损
        
        Args:
            days: 统计天数
        
        Returns:
            性能指标字典
        """
        try:
            start_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
            
            # 从数据库获取交易记录
            sql = """
                SELECT 
                    profit,
                    signal_type,
                    trigger_time
                FROM signal_statistics
                WHERE trigger_time >= ? AND profit IS NOT NULL
            """
            results = self.db.query(sql, (start_date,))
            
            if not results:
                return {
                    'total_trades': 0,
                    'win_rate': 0,
                    'profit_loss_ratio': 0,
                    'expected_return': 0,
                    'max_drawdown': 0,
                    'max_consecutive_losses': 0,
                }
            
            # 计算基础指标
            profits = [r['profit'] for r in results if r['profit'] > 0]
            losses = [abs(r['profit']) for r in results if r['profit'] < 0]
            
            total_trades = len(results)
            win_count = len(profits)
            loss_count = len(losses)
            
            # 胜率
            win_rate = win_count / total_trades * 100 if total_trades > 0 else 0
            
            # 平均盈利和平均亏损
            avg_profit = sum(profits) / len(profits) if profits else 0
            avg_loss = sum(losses) / len(losses) if losses else 0
            
            # 极端值分析（新增：判断是否依赖少数大单）
            if profits:
                sorted_profits = sorted(profits, reverse=True)
                max_profit_trade = sorted_profits[0]
                p90_profit = sorted_profits[int(len(sorted_profits) * 0.1)] if len(sorted_profits) > 10 else max_profit_trade
                top3_profit_sum = sum(sorted_profits[:3])
                total_profit_sum = sum(profits)
                profit_concentration = top3_profit_sum / total_profit_sum if total_profit_sum > 0 else 0
            else:
                max_profit_trade = 0
                p90_profit = 0
                profit_concentration = 0
            
            if losses:
                sorted_losses = sorted(losses, reverse=True)
                max_loss_trade = sorted_losses[0]
                p10_loss = sorted_losses[int(len(sorted_losses) * 0.1)] if len(sorted_losses) > 10 else max_loss_trade
            else:
                max_loss_trade = 0
                p10_loss = 0
            
            # 盈亏比
            profit_loss_ratio = avg_profit / avg_loss if avg_loss > 0 else 0
            
            # 期望收益（关键指标）
            expected_return = (win_rate / 100) * avg_profit - ((100 - win_rate) / 100) * avg_loss
            
            # 最大连续亏损（必须按时间排序）
            sorted_results = sorted(results, key=lambda x: x['trigger_time'])
            max_consecutive_losses = 0
            current_consecutive = 0
            for r in sorted_results:
                if r['profit'] < 0:
                    current_consecutive += 1
                    max_consecutive_losses = max(max_consecutive_losses, current_consecutive)
                else:
                    current_consecutive = 0
            
            # 最大回撤（正确计算：资金曲线）
            equity = 1.0  # 初始资金
            equity_curve = []
            
            for r in results:
                equity *= (1 + r['profit'] / 100)  # 复利计算
                equity_curve.append(equity)
            
            # 计算最大回撤
            peak = equity_curve[0] if equity_curve else 1.0
            max_drawdown = 0
            
            for v in equity_curve:
                peak = max(peak, v)
                dd = (peak - v) / peak * 100  # 转换为百分比
                max_drawdown = max(max_drawdown, dd)
            
            return {
                'total_trades': total_trades,
                'win_count': win_count,
                'loss_count': loss_count,
                'win_rate': round(win_rate, 2),
                'avg_profit': round(avg_profit, 2),
                'avg_loss': round(avg_loss, 2),
                'profit_loss_ratio': round(profit_loss_ratio, 2),
                'expected_return': round(expected_return, 3),
                'max_drawdown': round(max_drawdown, 2),
                'max_consecutive_losses': max_consecutive_losses,
                # 新增极端值指标
                'max_profit_trade': round(max_profit_trade, 2),
                'max_loss_trade': round(max_loss_trade, 2),
                'p90_profit': round(p90_profit, 2),
                'p10_loss': round(p10_loss, 2),
                'profit_concentration': round(profit_concentration, 2),
            }
            
        except Exception as e:
            logger.error(f"计算性能指标失败: {e}")
            return {}
    
    def compute_signal_statistics(self, days: int = 30) -> Dict:
        """
        计算信号统计
        
        包括：
        - 每日信号数
        - 零信号天数
        - 信号类型分布
        - 信号质量指数
        
        Args:
            days: 统计天数
        
        Returns:
            信号统计字典
        """
        try:
            start_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
            
            # 每日信号数
            sql_daily = """
                SELECT 
                    DATE(trigger_time) as date,
                    COUNT(*) as count
                FROM signal_statistics
                WHERE trigger_time >= ?
                GROUP BY DATE(trigger_time)
            """
            daily_results = self.db.query(sql_daily, (start_date,))
            
            daily_counts = {r['date']: r['count'] for r in daily_results}
            avg_daily_signals = sum(daily_counts.values()) / len(daily_counts) if daily_counts else 0
            
            # 零信号天数
            total_days = days
            zero_signal_days = total_days - len(daily_counts)
            
            # 信号类型分布
            sql_type = """
                SELECT 
                    signal_type,
                    COUNT(*) as count,
                    AVG(profit) as avg_profit,
                    SUM(CASE WHEN profit > 0 THEN 1 ELSE 0 END) as win_count
                FROM signal_statistics
                WHERE trigger_time >= ?
                GROUP BY signal_type
            """
            type_results = self.db.query(sql_type, (start_date,))
            
            signal_distribution = {}
            total_signals = sum(r['count'] for r in type_results)
            
            for r in type_results:
                signal_type = r['signal_type']
                count = r['count']
                win_count = r['win_count']
                avg_profit = r['avg_profit'] if r['avg_profit'] else 0
                
                win_rate = win_count / count * 100 if count > 0 else 0
                ratio = count / total_signals * 100 if total_signals > 0 else 0
                
                # 信号质量指数（正确版本：信号级期望收益）
                # quality_index = win_rate * avg_profit - (1 - win_rate) * avg_loss
                # 简化计算：直接使用期望收益
                loss_count = count - win_count
                avg_loss_for_signal = abs(avg_profit) * 0.5 if loss_count > 0 else 0  # 估算平均亏损
                quality_index = (win_rate / 100) * avg_profit - ((100 - win_rate) / 100) * avg_loss_for_signal
                
                signal_distribution[signal_type] = {
                    'count': count,
                    'ratio': round(ratio, 2),
                    'win_rate': round(win_rate, 2),
                    'avg_profit': round(avg_profit, 2),
                    'quality_index': round(quality_index, 3),
                }
            
            return {
                'avg_daily_signals': round(avg_daily_signals, 2),
                'total_signals': total_signals,
                'zero_signal_days': zero_signal_days,
                'signal_distribution': signal_distribution,
            }
            
        except Exception as e:
            logger.error(f"计算信号统计失败: {e}")
            return {}
    
    def compute_trade_distribution(self, days: int = 30) -> Dict:
        """
        计算交易分布
        
        包括：
        - 时间段分布
        - RSI区间分布
        - 回撤幅度分布
        
        Args:
            days: 统计天数
        
        Returns:
            交易分布字典
        """
        try:
            start_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
            
            # 时间段分布
            sql_time = """
                SELECT 
                    strftime('%H', trigger_time) as hour,
                    COUNT(*) as count,
                    AVG(profit) as avg_profit,
                    SUM(CASE WHEN profit > 0 THEN 1 ELSE 0 END) as win_count
                FROM signal_statistics
                WHERE trigger_time >= ?
                GROUP BY strftime('%H', trigger_time)
            """
            time_results = self.db.query(sql_time, (start_date,))
            
            time_distribution = {}
            for r in time_results:
                hour = r['hour']
                count = r['count']
                win_rate = r['win_count'] / count * 100 if count > 0 else 0
                avg_profit = r['avg_profit'] if r['avg_profit'] else 0
                
                time_distribution[hour] = {
                    'count': count,
                    'win_rate': round(win_rate, 2),
                    'avg_profit': round(avg_profit, 2),
                }
            
            # 区分上午和下午
            morning = [r for r in time_results if int(r['hour']) < 12]
            afternoon = [r for r in time_results if int(r['hour']) >= 12]
            
            morning_avg = sum(r['avg_profit'] for r in morning if r['avg_profit']) / len(morning) if morning else 0
            afternoon_avg = sum(r['avg_profit'] for r in afternoon if r['avg_profit']) / len(afternoon) if afternoon else 0
            
            time_comparison = {
                'morning_avg_profit': round(morning_avg, 2),
                'afternoon_avg_profit': round(afternoon_avg, 2),
            }
            
            return {
                'time_distribution': time_distribution,
                'time_comparison': time_comparison,
            }
            
        except Exception as e:
            logger.error(f"计算交易分布失败: {e}")
            return {}
    
    def detect_issues(self, performance_metrics: Dict, 
                     signal_statistics: Dict,
                     trade_distribution: Dict) -> List[Issue]:
        """
        问题诊断
        
        Args:
            performance_metrics: 性能指标
            signal_statistics: 信号统计
            trade_distribution: 交易分布
        
        Returns:
            问题列表
        """
        issues = []
        
        # 1. 信号频率检查
        avg_daily_signals = signal_statistics.get('avg_daily_signals', 0)
        if avg_daily_signals < 3:
            issues.append(Issue(
                issue_type="low_signal_frequency",
                description=f"信号过少：平均每日{avg_daily_signals}个",
                severity="high",
                recommended_action="放宽买点条件或减少防抖",
                affected_metric="signal_count"
            ))
        elif avg_daily_signals > 10:
            issues.append(Issue(
                issue_type="high_signal_frequency",
                description=f"信号过多：平均每日{avg_daily_signals}个",
                severity="medium",
                recommended_action="收紧条件或增加市场过滤",
                affected_metric="signal_count"
            ))
        
        # 2. 胜率检查
        win_rate = performance_metrics.get('win_rate', 0)
        if win_rate < 45:
            issues.append(Issue(
                issue_type="low_win_rate",
                description=f"胜率过低：{win_rate}%",
                severity="high",
                recommended_action="收紧买入条件，提高信号质量",
                affected_metric="win_rate"
            ))
        
        # 3. 期望收益检查
        expected_return = performance_metrics.get('expected_return', 0)
        if expected_return < 0:
            issues.append(Issue(
                issue_type="negative_expected_return",
                description=f"期望收益为负：{expected_return}%",
                severity="high",
                recommended_action="策略需要重大调整",
                affected_metric="expected_return"
            ))
        
        # 4. 最大连续亏损检查
        max_consecutive_losses = performance_metrics.get('max_consecutive_losses', 0)
        if max_consecutive_losses > 8:
            issues.append(Issue(
                issue_type="high_consecutive_losses",
                description=f"最大连续亏损过多：{max_consecutive_losses}次",
                severity="medium",
                recommended_action="增加止损机制或降低仓位",
                affected_metric="max_consecutive_losses"
            ))
        
        # 5. 信号类型表现差异检查
        signal_dist = signal_statistics.get('signal_distribution', {})
        if signal_dist:
            quality_indices = [v['quality_index'] for v in signal_dist.values()]
            if quality_indices:
                max_quality = max(quality_indices)
                min_quality = min(quality_indices)
                if max_quality > 0 and min_quality / max_quality < 0.5:
                    issues.append(Issue(
                        issue_type="signal_quality_conflict",
                        description="三种信号质量差异过大",
                        severity="medium",
                        recommended_action="调整信号权重，主策略优先",
                        affected_metric="quality_index"
                    ))
        
        return issues
    
    def generate_optimization_suggestions(self, issues: List[Issue],
                                         performance_metrics: Dict) -> Dict:
        """
        生成优化建议
        
        Args:
            issues: 问题列表
            performance_metrics: 性能指标
        
        Returns:
            优化建议字典
        """
        suggestions = {
            'factor_weights': [],
            'buy_signals': [],
            'sell_signals': [],
            'position_management': [],
            'time_filter': [],
        }
        
        # 根据问题生成建议
        for issue in issues:
            if issue.issue_type == "low_signal_frequency":
                suggestions['buy_signals'].append({
                    'action': '放宽回踩条件',
                    'detail': '止跌确认：单根放量阳线即可',
                    'priority': 'high',
                })
                suggestions['buy_signals'].append({
                    'action': '突破横盘约束改为软过滤',
                    'detail': '不强制要求横盘，改为置信度加分',
                    'priority': 'high',
                })
            
            elif issue.issue_type == "high_signal_frequency":
                suggestions['buy_signals'].append({
                    'action': '收紧买入条件',
                    'detail': '提高置信度阈值至0.8',
                    'priority': 'medium',
                })
            
            elif issue.issue_type == "low_win_rate":
                suggestions['factor_weights'].append({
                    'action': '降低动量权重',
                    'detail': '动量权重: 0.35 → 0.30',
                    'priority': 'high',
                })
                suggestions['factor_weights'].append({
                    'action': '提高回调保护权重',
                    'detail': '回调保护权重: 0.20 → 0.25',
                    'priority': 'high',
                })
            
            elif issue.issue_type == "signal_quality_conflict":
                suggestions['buy_signals'].append({
                    'action': '调整信号权重',
                    'detail': '主策略70% + 辅助策略30%',
                    'priority': 'medium',
                })
        
        # 基于性能指标的通用建议
        expected_return = performance_metrics.get('expected_return', 0)
        if expected_return > 0 and expected_return < 0.2:
            suggestions['position_management'].append({
                'action': '优化仓位控制',
                'detail': '使用连续仓位模型，降低回撤波动',
                'priority': 'low',
            })
        
        return suggestions
    
    def export_report(self, report: StrategyReport, 
                     format: str = "markdown",
                     output_path: str = None) -> str:
        """
        导出报告
        
        Args:
            report: 策略报告
            format: 输出格式（markdown/text）
            output_path: 输出路径
        
        Returns:
            报告文本
        """
        if format == "markdown":
            report_text = self._generate_markdown_report(report)
        else:
            report_text = self._generate_text_report(report)
        
        # 保存到文件
        if output_path:
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(report_text)
            logger.info(f"报告已保存至: {output_path}")
        
        return report_text
    
    def _generate_text_report(self, report: StrategyReport) -> str:
        """生成文本格式报告"""
        lines = [
            "=" * 80,
            "策略分析报告",
            "=" * 80,
            f"生成时间: {report.generated_at.strftime('%Y-%m-%d %H:%M:%S')}",
            "",
            "【一、总体指标】",
            "-" * 80,
        ]
        
        # 性能指标
        pm = report.performance_metrics
        lines.extend([
            f"总交易次数: {pm.get('total_trades', 0)}",
            f"胜率: {pm.get('win_rate', 0)}%",
            f"盈亏比: {pm.get('profit_loss_ratio', 0)}",
            f"期望收益: {pm.get('expected_return', 0)}%",
            f"最大回撤: {pm.get('max_drawdown', 0)}%",
            f"最大连续亏损: {pm.get('max_consecutive_losses', 0)}次",
            "",
            "【二、信号统计】",
            "-" * 80,
        ])
        
        # 信号统计
        ss = report.signal_statistics
        lines.extend([
            f"平均每日信号: {ss.get('avg_daily_signals', 0)}个",
            f"零信号天数: {ss.get('zero_signal_days', 0)}天",
            "",
            "信号类型分布:",
        ])
        
        signal_dist = ss.get('signal_distribution', {})
        for signal_type, data in signal_dist.items():
            lines.append(
                f"  {signal_type}: {data['ratio']}% "
                f"(胜率{data['win_rate']}%, 期望收益{data['avg_profit']}%)"
            )
        
        lines.extend([
            "",
            "【三、问题诊断】",
            "-" * 80,
        ])
        
        # 问题诊断
        if report.issues:
            for issue in report.issues:
                lines.append(
                    f"[{issue.severity.upper()}] {issue.description}"
                )
                lines.append(f"  建议: {issue.recommended_action}")
        else:
            lines.append("✅ 未发现明显问题")
        
        lines.extend([
            "",
            "【四、优化建议】",
            "-" * 80,
        ])
        
        # 优化建议
        suggestions = report.optimization_suggestions
        suggestion_count = 0
        
        for category, items in suggestions.items():
            if items:
                for item in items:
                    suggestion_count += 1
                    lines.append(f"{suggestion_count}. [{item['priority'].upper()}] {item['action']}")
                    lines.append(f"   {item['detail']}")
        
        if suggestion_count == 0:
            lines.append("✅ 当前策略表现良好，暂无优化建议")
        
        lines.append("=" * 80)
        
        return "\n".join(lines)
    
    def _generate_markdown_report(self, report: StrategyReport) -> str:
        """生成Markdown格式报告"""
        lines = [
            "# 策略分析报告",
            "",
            f"**生成时间**: {report.generated_at.strftime('%Y-%m-%d %H:%M:%S')}",
            "",
            "## 一、总体指标",
            "",
        ]
        
        # 性能指标
        pm = report.performance_metrics
        lines.extend([
            "| 指标 | 数值 |",
            "|------|------|",
            f"| 总交易次数 | {pm.get('total_trades', 0)} |",
            f"| 胜率 | {pm.get('win_rate', 0)}% |",
            f"| 盈亏比 | {pm.get('profit_loss_ratio', 0)} |",
            f"| 期望收益 | {pm.get('expected_return', 0)}% |",
            f"| 最大回撤 | {pm.get('max_drawdown', 0)}% |",
            f"| 最大连续亏损 | {pm.get('max_consecutive_losses', 0)}次 |",
            "",
            "## 二、信号统计",
            "",
        ])
        
        # 信号统计
        ss = report.signal_statistics
        lines.extend([
            f"- **平均每日信号**: {ss.get('avg_daily_signals', 0)}个",
            f"- **零信号天数**: {ss.get('zero_signal_days', 0)}天",
            "",
            "### 信号类型分布",
            "",
            "| 信号类型 | 占比 | 胜率 | 期望收益 |",
            "|---------|------|------|---------|",
        ])
        
        signal_dist = ss.get('signal_distribution', {})
        for signal_type, data in signal_dist.items():
            lines.append(
                f"| {signal_type} | {data['ratio']}% | "
                f"{data['win_rate']}% | {data['avg_profit']}% |"
            )
        
        lines.extend([
            "",
            "## 三、问题诊断",
            "",
        ])
        
        # 问题诊断
        if report.issues:
            for issue in report.issues:
                severity_emoji = {"high": "🔴", "medium": "🟡", "low": "🟢"}
                lines.append(
                    f"{severity_emoji.get(issue.severity, '⚪')} **{issue.description}**"
                )
                lines.append(f"  - 建议: {issue.recommended_action}")
                lines.append("")
        else:
            lines.append("✅ 未发现明显问题")
        
        lines.extend([
            "",
            "## 四、优化建议",
            "",
        ])
        
        # 优化建议
        suggestions = report.optimization_suggestions
        suggestion_count = 0
        
        for category, items in suggestions.items():
            if items:
                category_names = {
                    'factor_weights': '因子权重调整',
                    'buy_signals': '买入信号优化',
                    'sell_signals': '卖出信号优化',
                    'position_management': '仓位管理优化',
                    'time_filter': '时间过滤优化',
                }
                lines.append(f"### {category_names.get(category, category)}")
                lines.append("")
                
                for item in items:
                    suggestion_count += 1
                    priority_emoji = {"high": "🔥", "medium": "⚡", "low": "💡"}
                    lines.append(
                        f"{suggestion_count}. {priority_emoji.get(item['priority'], '•')} **{item['action']}**"
                    )
                    lines.append(f"   - {item['detail']}")
                lines.append("")
        
        if suggestion_count == 0:
            lines.append("✅ 当前策略表现良好，暂无优化建议")
        
        return "\n".join(lines)


def generate_strategy_report(days: int = 30, 
                           output_format: str = "text",
                           output_path: str = None) -> str:
    """
    生成策略分析报告（便捷函数）
    
    Args:
        days: 分析天数
        output_format: 输出格式
        output_path: 输出路径
    
    Returns:
        报告文本
    """
    generator = StrategyReportGenerator()
    report = generator.run_full_analysis(days)
    return generator.export_report(report, output_format, output_path)
