# -*- coding: utf-8 -*-
"""
交易效果评测模块
统计历史交易数据，生成交易效果分析报告
"""

import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from src.core.logger import get_logger
from src.core.config import ConfigManager
from src.core.database import DatabaseManager

logger = get_logger("trade_evaluator")


class TradeEvaluator:
    """交易效果评测器"""
    
    def __init__(self, config: ConfigManager = None, db: DatabaseManager = None):
        """
        初始化交易效果评测器
        
        Args:
            config: 配置管理器
            db: 数据库管理器
        """
        if config is None:
            config = ConfigManager()
        if db is None:
            db = DatabaseManager(config)
        
        self.config = config
        self.db = db
        
        logger.info("交易效果评测器初始化完成")
    
    def get_trade_history(self, start_date: str = None, end_date: str = None) -> List[Dict]:
        """
        获取交易历史
        
        Args:
            start_date: 开始日期
            end_date: 结束日期
        
        Returns:
            交易记录列表
        """
        if start_date is None:
            start_date = (datetime.now() - timedelta(days=365)).strftime("%Y-%m-%d")
        if end_date is None:
            end_date = datetime.now().strftime("%Y-%m-%d")
        
        sql = """
            SELECT id, ts_code, name, trade_type, trade_price, trade_num, 
                   trade_time, profit, remark
            FROM trade_log
            WHERE trade_time >= ? AND trade_time <= ?
            ORDER BY trade_time
        """
        
        results = self.db.query(sql, (start_date, end_date))
        return results if results else []
    
    def calculate_metrics(self, trades: List[Dict]) -> Dict:
        """
        计算交易指标
        
        Args:
            trades: 交易记录列表
        
        Returns:
            指标字典
        """
        if not trades:
            return {
                "total_trades": 0,
                "win_rate": 0,
                "avg_profit": 0,
                "avg_loss": 0,
                "profit_ratio": 0,
                "total_profit": 0,
                "max_profit": 0,
                "max_loss": 0
            }
        
        # 统计盈亏
        profits = [t['profit'] for t in trades if t.get('profit') is not None]
        
        if not profits:
            return {
                "total_trades": len(trades),
                "win_rate": 0,
                "avg_profit": 0,
                "avg_loss": 0,
                "profit_ratio": 0,
                "total_profit": 0,
                "max_profit": 0,
                "max_loss": 0
            }
        
        win_trades = [p for p in profits if p > 0]
        loss_trades = [p for p in profits if p < 0]
        
        total_profit = sum(profits)
        win_count = len(win_trades)
        loss_count = len(loss_trades)
        total_count = len(profits)
        
        win_rate = win_count / total_count * 100 if total_count > 0 else 0
        avg_profit = np.mean(win_trades) if win_trades else 0
        avg_loss = np.mean(loss_trades) if loss_trades else 0
        profit_ratio = abs(avg_profit / avg_loss) if avg_loss != 0 else 0
        
        return {
            "total_trades": total_count,
            "win_trades": win_count,
            "loss_trades": loss_count,
            "win_rate": round(win_rate, 2),
            "avg_profit": round(avg_profit, 2),
            "avg_loss": round(avg_loss, 2),
            "profit_ratio": round(profit_ratio, 2),
            "total_profit": round(total_profit, 2),
            "max_profit": round(max(profits), 2),
            "max_loss": round(min(profits), 2)
        }
    
    def calculate_monthly_returns(self, trades: List[Dict]) -> List[Dict]:
        """
        计算月度收益
        
        Args:
            trades: 交易记录列表
        
        Returns:
            月度收益列表
        """
        if not trades:
            return []
        
        df = pd.DataFrame(trades)
        df['trade_time'] = pd.to_datetime(df['trade_time'])
        df['month'] = df['trade_time'].dt.to_period('M')
        
        monthly = df.groupby('month').agg({
            'profit': 'sum',
            'ts_code': 'count'
        }).reset_index()
        
        monthly.columns = ['month', 'profit', 'trades']
        monthly['month'] = monthly['month'].astype(str)
        
        return monthly.to_dict('records')
    
    def calculate_stock_performance(self, trades: List[Dict]) -> List[Dict]:
        """
        计算各股票表现
        
        Args:
            trades: 交易记录列表
        
        Returns:
            股票表现列表
        """
        if not trades:
            return []
        
        df = pd.DataFrame(trades)
        
        stock_stats = df.groupby('ts_code').agg({
            'profit': ['sum', 'count', 'mean'],
            'name': 'first'
        }).reset_index()
        
        stock_stats.columns = ['ts_code', 'total_profit', 'trade_count', 'avg_profit', 'name']
        
        # 计算胜率
        result = []
        for _, row in stock_stats.iterrows():
            ts_code = row['ts_code']
            stock_trades = [t for t in trades if t['ts_code'] == ts_code]
            profits = [t['profit'] for t in stock_trades if t.get('profit') is not None]
            win_count = len([p for p in profits if p > 0])
            win_rate = win_count / len(profits) * 100 if profits else 0
            
            result.append({
                "ts_code": ts_code,
                "name": row['name'],
                "total_profit": round(row['total_profit'], 2),
                "trade_count": int(row['trade_count']),
                "avg_profit": round(row['avg_profit'], 2),
                "win_rate": round(win_rate, 2)
            })
        
        # 按总盈亏排序
        result.sort(key=lambda x: x['total_profit'], reverse=True)
        return result
    
    def run_evaluation(self, start_date: str = None, end_date: str = None) -> Dict:
        """
        执行交易效果评测
        
        Args:
            start_date: 开始日期
            end_date: 结束日期
        
        Returns:
            评测结果
        """
        logger.info("=" * 60)
        logger.info("开始执行交易效果评测...")
        logger.info("=" * 60)
        
        if start_date is None:
            start_date = (datetime.now() - timedelta(days=365)).strftime("%Y-%m-%d")
        if end_date is None:
            end_date = datetime.now().strftime("%Y-%m-%d")
        
        result = {
            "start_date": start_date,
            "end_date": end_date,
            "evaluate_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "metrics": None,
            "monthly_returns": None,
            "stock_performance": None
        }
        
        try:
            # 获取交易历史
            trades = self.get_trade_history(start_date, end_date)
            
            if not trades:
                logger.warning("无交易记录")
                result["metrics"] = self.calculate_metrics([])
                return result
            
            logger.info(f"获取到{len(trades)}条交易记录")
            
            # 计算指标
            result["metrics"] = self.calculate_metrics(trades)
            
            # 计算月度收益
            result["monthly_returns"] = self.calculate_monthly_returns(trades)
            
            # 计算股票表现
            result["stock_performance"] = self.calculate_stock_performance(trades)
            
            logger.info("=" * 60)
            logger.info(f"交易效果评测完成")
            logger.info(f"总交易: {result['metrics']['total_trades']}次")
            logger.info(f"胜率: {result['metrics']['win_rate']}%")
            logger.info(f"总盈亏: {result['metrics']['total_profit']}元")
            logger.info("=" * 60)
            
        except Exception as e:
            logger.error(f"交易效果评测失败: {e}")
            result["error"] = str(e)
        
        return result
    
    def generate_report(self, result: Dict) -> str:
        """
        生成评测报告
        
        Args:
            result: 评测结果
        
        Returns:
            报告文本
        """
        lines = []
        
        lines.extend([
            "=" * 70,
            "                    交易效果评测报告",
            "=" * 70,
            f"评测区间: {result['start_date']} ~ {result['end_date']}",
            f"评测时间: {result['evaluate_time']}",
            ""
        ])
        
        metrics = result.get("metrics", {})
        
        lines.extend([
            "-" * 70,
            "【总体指标】",
            f"  总交易次数: {metrics.get('total_trades', 0)}次",
            f"  盈利次数: {metrics.get('win_trades', 0)}次",
            f"  亏损次数: {metrics.get('loss_trades', 0)}次",
            f"  胜率: {metrics.get('win_rate', 0)}%",
            "",
            "-" * 70,
            "【盈亏分析】",
            f"  总盈亏: {metrics.get('total_profit', 0)}元",
            f"  平均盈利: {metrics.get('avg_profit', 0)}元",
            f"  平均亏损: {metrics.get('avg_loss', 0)}元",
            f"  盈亏比: {metrics.get('profit_ratio', 0)}",
            f"  最大单笔盈利: {metrics.get('max_profit', 0)}元",
            f"  最大单笔亏损: {metrics.get('max_loss', 0)}元",
            ""
        ])
        
        # 月度收益
        if result.get("monthly_returns"):
            lines.extend([
                "-" * 70,
                "【月度收益】",
                ""
            ])
            
            for m in result["monthly_returns"]:
                profit_str = f"+{m['profit']}" if m['profit'] > 0 else str(m['profit'])
                lines.append(f"  {m['month']}: {profit_str}元 ({m['trades']}笔)")
            
            lines.append("")
        
        # 股票表现
        if result.get("stock_performance"):
            lines.extend([
                "-" * 70,
                "【股票表现TOP10】",
                ""
            ])
            
            for i, s in enumerate(result["stock_performance"][:10], 1):
                profit_str = f"+{s['total_profit']}" if s['total_profit'] > 0 else str(s['total_profit'])
                lines.append(f"  {i}. {s['ts_code']} {s['name']}")
                lines.append(f"     盈亏: {profit_str}元, 胜率: {s['win_rate']}%")
            
            lines.append("")
        
        lines.append("=" * 70)
        
        return "\n".join(lines)
    
    def get_optimization_suggestions(self, result: Dict) -> List[str]:
        """
        生成优化建议
        
        Args:
            result: 评测结果
        
        Returns:
            建议列表
        """
        suggestions = []
        metrics = result.get("metrics", {})
        
        win_rate = metrics.get("win_rate", 0)
        profit_ratio = metrics.get("profit_ratio", 0)
        total_profit = metrics.get("total_profit", 0)
        
        # 胜率建议
        if win_rate < 40:
            suggestions.append("胜率偏低，建议优化选股策略，提高选股准确性")
        elif win_rate > 60:
            suggestions.append("胜率良好，可考虑适当增加仓位")
        
        # 盈亏比建议
        if profit_ratio < 1.5:
            suggestions.append("盈亏比偏低，建议加强止损止盈管理，让盈利奔跑")
        elif profit_ratio > 3:
            suggestions.append("盈亏比优秀，当前风控策略有效")
        
        # 总体盈亏建议
        if total_profit < 0:
            suggestions.append("整体亏损，建议暂停交易，复盘策略问题")
        elif total_profit > 0:
            suggestions.append("整体盈利，可继续执行当前策略")
        
        return suggestions
