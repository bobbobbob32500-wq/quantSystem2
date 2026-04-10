# -*- coding: utf-8 -*-
"""
Pattern Mining系统
从交易数据中自动发现赚钱条件组合，生成子策略
"""

import pandas as pd
import numpy as np
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from itertools import combinations

from src.core.logger import get_logger

logger = get_logger("pattern_mining")


@dataclass
class Pattern:
    """Pattern数据结构"""
    conditions: Dict          # 条件组合
    sample_size: int          # 样本数量
    win_rate: float           # 胜率
    avg_profit: float         # 平均盈利
    avg_loss: float           # 平均亏损
    profit_loss_ratio: float  # 盈亏比
    expected_return: float    # 期望收益
    sharpe: float             # 夏普比率
    confidence: float         # 置信度
    score: float              # 综合评分
    is_profitable: bool       # 是否赚钱


class PatternMiningEngine:
    """Pattern Mining引擎"""
    
    def __init__(self, min_sample_size: int = 20):
        """
        初始化Pattern Mining引擎
        
        Args:
            min_sample_size: 最小样本数量
        """
        self.min_sample_size = min_sample_size
        
        logger.info(f"Pattern Mining引擎初始化完成，最小样本数: {min_sample_size}")
    
    def build_feature_matrix(self, trades: List[Dict]) -> pd.DataFrame:
        """
        构建特征矩阵
        
        Args:
            trades: 交易记录列表
        
        Returns:
            特征矩阵DataFrame
        """
        if not trades:
            return pd.DataFrame()
        
        df = pd.DataFrame(trades)
        
        # 确保必要列存在
        required_cols = ['pnl', 'signal_type', 'entry_date']
        for col in required_cols:
            if col not in df.columns:
                logger.warning(f"缺少必要列: {col}")
                return pd.DataFrame()
        
        # 提取时间特征
        df['entry_date'] = pd.to_datetime(df['entry_date'])
        df['hour'] = df['entry_date'].dt.hour
        
        # 添加默认特征（如果不存在）
        if 'rsi' not in df.columns:
            df['rsi'] = 55  # 默认RSI
        if 'pullback' not in df.columns:
            df['pullback'] = 8  # 默认回撤
        if 'volume_ratio' not in df.columns:
            df['volume_ratio'] = 1.5  # 默认量比
        
        return df
    
    def discretize_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        特征离散化（关键：否则无法组合）
        
        Args:
            df: 特征矩阵
        
        Returns:
            离散化后的DataFrame
        """
        df = df.copy()
        
        # RSI离散化
        df['rsi_bin'] = pd.cut(
            df['rsi'], 
            bins=[0, 50, 55, 60, 65, 100],
            labels=['<50', '50-55', '55-60', '60-65', '>65']
        )
        
        # 回撤离散化
        df['pullback_bin'] = pd.cut(
            df['pullback'],
            bins=[-100, 0, 5, 10, 15, 100],
            labels=['<0', '0-5', '5-10', '10-15', '>15']
        )
        
        # 量比离散化
        df['volume_bin'] = pd.cut(
            df['volume_ratio'],
            bins=[0, 1, 1.5, 2, 3, 100],
            labels=['<1', '1-1.5', '1.5-2', '2-3', '>3']
        )
        
        # 时间离散化
        df['time_bin'] = pd.cut(
            df['hour'],
            bins=[0, 10, 11, 13, 14, 24],
            labels=['9-10', '10-11', '11-13', '13-14', '14-15']
        )
        
        return df
    
    def generate_patterns(self, df: pd.DataFrame, max_depth: int = 3) -> List[Tuple[Dict, pd.DataFrame]]:
        """
        生成条件组合（核心）
        
        Args:
            df: 离散化后的DataFrame
            max_depth: 最大组合深度
        
        Returns:
            Pattern列表
        """
        features = ['rsi_bin', 'pullback_bin', 'volume_bin', 'time_bin', 'signal_type']
        
        patterns = []
        
        # 从单特征到多特征组合
        for depth in range(1, max_depth + 1):
            for cols in combinations(features, depth):
                try:
                    grouped = df.groupby(list(cols))
                    
                    for keys, group in grouped:
                        # 样本过滤
                        if len(group) < self.min_sample_size:
                            continue
                        
                        # 构建条件字典
                        if isinstance(keys, tuple):
                            pattern = {col: val for col, val in zip(cols, keys)}
                        else:
                            pattern = {cols[0]: keys}
                        
                        patterns.append((pattern, group))
                
                except Exception as e:
                    logger.debug(f"组合 {cols} 处理失败: {e}")
                    continue
        
        logger.info(f"生成 {len(patterns)} 个Pattern")
        
        return patterns
    
    def evaluate_pattern(self, group: pd.DataFrame) -> Dict:
        """
        评估单个Pattern
        
        Args:
            group: 符合该Pattern的交易记录
        
        Returns:
            评估结果字典
        """
        pnl = group['pnl']
        
        wins = pnl[pnl > 0]
        losses = pnl[pnl < 0]
        
        win_rate = len(wins) / len(pnl) if len(pnl) > 0 else 0
        avg_profit = wins.mean() if len(wins) > 0 else 0
        avg_loss = abs(losses.mean()) if len(losses) > 0 else 0
        
        profit_loss_ratio = avg_profit / avg_loss if avg_loss > 0 else 0
        
        expected_return = win_rate * avg_profit - (1 - win_rate) * avg_loss
        
        sharpe = pnl.mean() / (pnl.std() + 1e-9) if len(pnl) > 1 else 0
        
        return {
            'sample_size': len(pnl),
            'win_rate': win_rate,
            'avg_profit': avg_profit,
            'avg_loss': avg_loss,
            'profit_loss_ratio': profit_loss_ratio,
            'expected_return': expected_return,
            'sharpe': sharpe,
        }
    
    def score_patterns(self, patterns_df: pd.DataFrame) -> pd.DataFrame:
        """
        评分（标准化 + 置信度）
        
        Args:
            patterns_df: Pattern评估结果DataFrame
        
        Returns:
            带评分的DataFrame
        """
        df = patterns_df.copy()
        
        # 标准化函数
        def normalize(series):
            min_val = series.min()
            max_val = series.max()
            if max_val - min_val < 1e-9:
                return pd.Series([0.5] * len(series), index=series.index)
            return (series - min_val) / (max_val - min_val)
        
        # 标准化各指标
        df['expected_return_norm'] = normalize(df['expected_return'])
        df['sharpe_norm'] = normalize(df['sharpe'])
        df['sample_size_norm'] = normalize(df['sample_size'])
        
        # 置信度（样本数量）
        df['confidence'] = (df['sample_size'] / 100).clip(0, 1)
        
        # 综合评分
        df['score'] = (
            df['expected_return_norm'] * 0.5 +
            df['sharpe_norm'] * 0.3 +
            df['sample_size_norm'] * 0.2
        ) * df['confidence']
        
        return df
    
    def filter_patterns(self, df: pd.DataFrame, 
                       min_expected_return: float = 0,
                       min_win_rate: float = 0.5,
                       min_sample_size: int = 30) -> pd.DataFrame:
        """
        筛选优质Pattern
        
        Args:
            df: Pattern DataFrame
            min_expected_return: 最小期望收益
            min_win_rate: 最小胜率
            min_sample_size: 最小样本数
        
        Returns:
            筛选后的DataFrame
        """
        return df[
            (df['expected_return'] > min_expected_return) &
            (df['win_rate'] > min_win_rate) &
            (df['sample_size'] >= min_sample_size)
        ].copy()
    
    def run(self, trades: List[Dict], 
           max_depth: int = 3,
           top_n: int = 20) -> Tuple[pd.DataFrame, pd.DataFrame]:
        """
        运行Pattern Mining
        
        Args:
            trades: 交易记录列表
            max_depth: 最大组合深度
            top_n: 返回Top N个Pattern
        
        Returns:
            (赚钱Pattern, 亏钱Pattern)
        """
        logger.info("=" * 80)
        logger.info("开始Pattern Mining...")
        logger.info("=" * 80)
        
        # Step 1: 构建特征矩阵
        df = self.build_feature_matrix(trades)
        if df.empty:
            logger.warning("特征矩阵为空")
            return pd.DataFrame(), pd.DataFrame()
        
        # Step 2: 特征离散化
        df = self.discretize_features(df)
        
        # Step 3: 生成Pattern
        patterns = self.generate_patterns(df, max_depth)
        if not patterns:
            logger.warning("未生成任何Pattern")
            return pd.DataFrame(), pd.DataFrame()
        
        # Step 4: 评估Pattern
        pattern_results = []
        for pattern_dict, group in patterns:
            eval_result = self.evaluate_pattern(group)
            eval_result['conditions'] = pattern_dict
            pattern_results.append(eval_result)
        
        patterns_df = pd.DataFrame(pattern_results)
        
        # Step 5: 评分
        patterns_df = self.score_patterns(patterns_df)
        
        # Step 6: 分类
        profit_patterns = self.filter_patterns(patterns_df)
        loss_patterns = patterns_df[patterns_df['expected_return'] < 0].copy()
        
        # 排序
        profit_patterns = profit_patterns.sort_values('score', ascending=False).head(top_n)
        loss_patterns = loss_patterns.sort_values('expected_return', ascending=True).head(top_n)
        
        logger.info(f"发现 {len(profit_patterns)} 个赚钱Pattern")
        logger.info(f"发现 {len(loss_patterns)} 个亏钱Pattern")
        
        return profit_patterns, loss_patterns
    
    def generate_report(self, profit_patterns: pd.DataFrame, 
                       loss_patterns: pd.DataFrame) -> str:
        """
        生成Pattern Mining报告
        
        Args:
            profit_patterns: 赚钱Pattern
            loss_patterns: 亏钱Pattern
        
        Returns:
            报告文本
        """
        lines = [
            "=" * 100,
            "Pattern Mining报告",
            f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "=" * 100,
            "",
        ]
        
        # 赚钱Pattern
        if not profit_patterns.empty:
            lines.extend([
                "【赚钱模式】（按综合评分排序）",
                "-" * 100,
            ])
            
            for i, row in profit_patterns.iterrows():
                conditions = row['conditions']
                cond_str = " + ".join([f"{k}={v}" for k, v in conditions.items()])
                
                lines.extend([
                    f"{i+1}. {cond_str}",
                    f"   胜率: {row['win_rate']*100:.1f}%",
                    f"   期望收益: {row['expected_return']:.3f}%",
                    f"   样本数: {int(row['sample_size'])}",
                    f"   综合评分: {row['score']:.3f}",
                    f"   置信度: {row['confidence']:.2f}",
                    "",
                ])
        else:
            lines.extend([
                "【赚钱模式】",
                "未发现稳定赚钱的条件组合",
                "",
            ])
        
        # 亏钱Pattern
        if not loss_patterns.empty:
            lines.extend([
                "【禁止交易条件】（持续亏损）",
                "-" * 100,
            ])
            
            for i, row in loss_patterns.iterrows():
                conditions = row['conditions']
                cond_str = " + ".join([f"{k}={v}" for k, v in conditions.items()])
                
                lines.extend([
                    f"❌ {cond_str}",
                    f"   胜率: {row['win_rate']*100:.1f}%",
                    f"   期望收益: {row['expected_return']:.3f}%",
                    f"   样本数: {int(row['sample_size'])}",
                    "",
                ])
        
        lines.append("=" * 100)
        
        return "\n".join(lines)
    
    def convert_pattern_to_strategy(self, pattern_dict: Dict):
        """
        将Pattern转换为策略函数
        
        Args:
            pattern_dict: 条件字典
        
        Returns:
            策略函数
        """
        def strategy_check(row):
            """检查是否满足Pattern条件"""
            for key, val in pattern_dict.items():
                if key not in row:
                    return False
                if row[key] != val:
                    return False
            return True
        
        return strategy_check


def run_pattern_mining(trades: List[Dict], top_n: int = 20) -> str:
    """
    运行Pattern Mining（便捷函数）
    
    Args:
        trades: 交易记录列表
        top_n: 返回Top N个Pattern
    
    Returns:
        报告文本
    """
    engine = PatternMiningEngine()
    profit_patterns, loss_patterns = engine.run(trades, top_n=top_n)
    return engine.generate_report(profit_patterns, loss_patterns)
