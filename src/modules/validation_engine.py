# -*- coding: utf-8 -*-
"""
Pattern验证引擎（Validation Engine）
防止数据泄露、评估稳定性、加入交易成本、组合优化
"""

import pandas as pd
import numpy as np
from datetime import datetime
from typing import Dict, List, Optional, Tuple, Callable
from dataclasses import dataclass

from src.core.logger import get_logger

logger = get_logger("validation_engine")


@dataclass
class ValidatedPattern:
    """验证后的Pattern数据结构"""
    pattern_id: int
    conditions: Dict
    method: str
    
    # 训练集表现
    train_win_rate: float
    train_expected_return: float
    train_sample_size: int
    
    # 测试集表现（关键）
    test_win_rate: float
    test_expected_return: float
    test_sample_size: int
    
    # 稳定性指标
    std_return: float
    stability_score: float
    
    # 真实表现（考虑交易成本）
    real_expected_return: float
    
    # 综合评分
    composite_score: float
    
    # 是否通过验证
    is_valid: bool


class ValidationEngine:
    """Pattern验证引擎"""
    
    def __init__(self, 
                 train_ratio: float = 0.7,
                 min_test_samples: int = 20,
                 fee: float = 0.1,
                 slippage: float = 0.05):
        """
        初始化验证引擎
        
        Args:
            train_ratio: 训练集比例
            min_test_samples: 测试集最小样本数
            fee: 手续费（%）
            slippage: 滑点（%）
        """
        self.train_ratio = train_ratio
        self.min_test_samples = min_test_samples
        self.fee = fee
        self.slippage = slippage
        
        logger.info(f"Validation Engine初始化完成")
        logger.info(f"  训练集比例: {train_ratio}")
        logger.info(f"  最小测试样本: {min_test_samples}")
        logger.info(f"  手续费: {fee}%")
        logger.info(f"  滑点: {slippage}%")
    
    def split_data_by_time(self, trades: List[Dict]) -> Tuple[pd.DataFrame, pd.DataFrame]:
        """
        时间序列切分（防止数据泄露）
        
        Args:
            trades: 交易记录列表
        
        Returns:
            (训练集, 测试集)
        """
        if not trades:
            return pd.DataFrame(), pd.DataFrame()
        
        df = pd.DataFrame(trades)
        
        # 确保有entry_date列
        if 'entry_date' not in df.columns:
            logger.warning("缺少entry_date列，无法按时间切分")
            # 简单切分
            train_size = int(len(df) * self.train_ratio)
            return df.iloc[:train_size], df.iloc[train_size:]
        
        # 按时间排序
        df['entry_date'] = pd.to_datetime(df['entry_date'])
        df = df.sort_values('entry_date').reset_index(drop=True)
        
        # 时间切分
        train_size = int(len(df) * self.train_ratio)
        train_data = df.iloc[:train_size].copy()
        test_data = df.iloc[train_size:].copy()
        
        logger.info(f"数据切分完成:")
        logger.info(f"  训练集: {len(train_data)} 条 ({train_data['entry_date'].min()} ~ {train_data['entry_date'].max()})")
        logger.info(f"  测试集: {len(test_data)} 条 ({test_data['entry_date'].min()} ~ {test_data['entry_date'].max()})")
        
        return train_data, test_data
    
    def walk_forward_split(self, trades: List[Dict], 
                          n_folds: int = 5,
                          train_window: int = 100) -> List[Tuple[pd.DataFrame, pd.DataFrame]]:
        """
        Walk-forward验证（防止过拟合）
        
        Args:
            trades: 交易记录列表
            n_folds: 折数
            train_window: 训练窗口大小
        
        Returns:
            [(训练集1, 测试集1), (训练集2, 测试集2), ...]
        """
        if not trades:
            return []
        
        df = pd.DataFrame(trades)
        
        if 'entry_date' in df.columns:
            df['entry_date'] = pd.to_datetime(df['entry_date'])
            df = df.sort_values('entry_date').reset_index(drop=True)
        
        folds = []
        test_size = (len(df) - train_window) // n_folds
        
        for i in range(n_folds):
            train_start = i * test_size
            train_end = train_start + train_window
            test_end = train_end + test_size
            
            if test_end > len(df):
                break
            
            train_data = df.iloc[train_start:train_end].copy()
            test_data = df.iloc[train_end:test_end].copy()
            
            folds.append((train_data, test_data))
        
        logger.info(f"Walk-forward切分完成: {len(folds)} 折")
        
        return folds
    
    def validate_pattern(self, 
                        pattern: Dict,
                        train_data: pd.DataFrame,
                        test_data: pd.DataFrame,
                        strategy_func: Callable) -> Optional[ValidatedPattern]:
        """
        验证单个Pattern
        
        Args:
            pattern: Pattern字典
            train_data: 训练集
            test_data: 测试集
            strategy_func: 策略函数
        
        Returns:
            验证后的Pattern
        """
        # 训练集表现
        train_matched = train_data[train_data.apply(strategy_func, axis=1)]
        train_pnl = train_matched['pnl'] if 'pnl' in train_matched.columns else pd.Series()
        
        if len(train_pnl) == 0:
            return None
        
        train_win_rate = (train_pnl > 0).mean()
        train_expected_return = train_pnl.mean()
        train_sample_size = len(train_pnl)
        
        # 测试集表现（关键）
        test_matched = test_data[test_data.apply(strategy_func, axis=1)]
        test_pnl = test_matched['pnl'] if 'pnl' in test_matched.columns else pd.Series()
        
        if len(test_pnl) < self.min_test_samples:
            logger.debug(f"Pattern测试样本不足: {len(test_pnl)} < {self.min_test_samples}")
            return None
        
        test_win_rate = (test_pnl > 0).mean()
        test_expected_return = test_pnl.mean()
        test_sample_size = len(test_pnl)
        
        # 稳定性评分
        std_return = test_pnl.std()
        stability_score = self._calculate_stability_score(test_win_rate, std_return, test_sample_size)
        
        # 真实表现（考虑交易成本）
        real_pnl = test_pnl - self.fee - self.slippage
        real_expected_return = real_pnl.mean()
        
        # 综合评分
        composite_score = self._calculate_composite_score(
            test_expected_return,
            test_win_rate,
            std_return,
            test_sample_size,
            stability_score
        )
        
        # 是否通过验证
        is_valid = self._check_validation(
            test_win_rate,
            test_expected_return,
            real_expected_return,
            test_sample_size
        )
        
        return ValidatedPattern(
            pattern_id=pattern.get('pattern_id', 0),
            conditions=pattern.get('conditions', {}),
            method=pattern.get('method', 'unknown'),
            train_win_rate=train_win_rate,
            train_expected_return=train_expected_return,
            train_sample_size=train_sample_size,
            test_win_rate=test_win_rate,
            test_expected_return=test_expected_return,
            test_sample_size=test_sample_size,
            std_return=std_return,
            stability_score=stability_score,
            real_expected_return=real_expected_return,
            composite_score=composite_score,
            is_valid=is_valid
        )
    
    def _calculate_stability_score(self, 
                                  win_rate: float,
                                  std_return: float,
                                  sample_size: int) -> float:
        """
        计算稳定性评分
        
        Args:
            win_rate: 胜率
            std_return: 收益标准差
            sample_size: 样本数
        
        Returns:
            稳定性评分
        """
        if std_return == 0 or std_return is None:
            return 0
        
        # 高胜率 + 低波动 = 高稳定性
        stability = win_rate / (std_return + 1e-9)
        
        # 样本数惩罚
        if sample_size < 30:
            stability *= (sample_size / 30)
        
        return max(0, stability)
    
    def _calculate_composite_score(self,
                                  expected_return: float,
                                  win_rate: float,
                                  std_return: float,
                                  sample_size: int,
                                  stability_score: float) -> float:
        """
        计算综合评分
        
        Args:
            expected_return: 期望收益
            win_rate: 胜率
            std_return: 收益标准差
            sample_size: 样本数
            stability_score: 稳定性评分
        
        Returns:
            综合评分
        """
        # 标准化各指标
        score = (
            expected_return * 0.4 +           # 期望收益权重
            win_rate * 10 * 0.3 +             # 胜率权重
            stability_score * 0.2 +           # 稳定性权重
            (sample_size / 100) * 0.1         # 样本数权重
        )
        
        return score
    
    def _check_validation(self,
                         test_win_rate: float,
                         test_expected_return: float,
                         real_expected_return: float,
                         test_sample_size: int) -> bool:
        """
        检查是否通过验证
        
        Args:
            test_win_rate: 测试胜率
            test_expected_return: 测试期望收益
            real_expected_return: 真实期望收益
            test_sample_size: 测试样本数
        
        Returns:
            是否通过验证
        """
        # 条件1: 胜率 > 50%
        if test_win_rate <= 0.5:
            return False
        
        # 条件2: 期望收益 > 0
        if test_expected_return <= 0:
            return False
        
        # 条件3: 真实期望收益 > 0（考虑交易成本）
        if real_expected_return <= 0:
            return False
        
        # 条件4: 样本数足够
        if test_sample_size < self.min_test_samples:
            return False
        
        return True
    
    def validate_patterns(self,
                         patterns: List[Dict],
                         train_data: pd.DataFrame,
                         test_data: pd.DataFrame,
                         convert_func: Callable) -> List[ValidatedPattern]:
        """
        批量验证Pattern
        
        Args:
            patterns: Pattern列表
            train_data: 训练集
            test_data: 测试集
            convert_func: Pattern转策略函数
        
        Returns:
            验证后的Pattern列表
        """
        validated = []
        
        for i, pattern in enumerate(patterns):
            # 转换为策略函数
            strategy_func = convert_func(pattern.get('conditions', {}))
            
            # 验证
            validated_pattern = self.validate_pattern(
                pattern, train_data, test_data, strategy_func
            )
            
            if validated_pattern:
                validated_pattern.pattern_id = i
                validated.append(validated_pattern)
        
        logger.info(f"验证完成: {len(validated)}/{len(patterns)} 个Pattern通过验证")
        
        return validated
    
    def rank_patterns(self, validated_patterns: List[ValidatedPattern]) -> List[ValidatedPattern]:
        """
        排序Pattern
        
        Args:
            validated_patterns: 验证后的Pattern列表
        
        Returns:
            排序后的Pattern列表
        """
        # 按综合评分排序
        sorted_patterns = sorted(
            validated_patterns,
            key=lambda x: x.composite_score,
            reverse=True
        )
        
        return sorted_patterns
    
    def combine_patterns(self, 
                        top_patterns: List[ValidatedPattern],
                        convert_func: Callable) -> Callable:
        """
        组合多个Pattern（投票机制）
        
        Args:
            top_patterns: Top Pattern列表
            convert_func: Pattern转策略函数
        
        Returns:
            组合策略函数
        """
        def combined_strategy(row):
            """组合策略：任一Pattern满足即买入"""
            for pattern in top_patterns:
                strategy_func = convert_func(pattern.conditions)
                try:
                    if strategy_func(row):
                        return True
                except:
                    continue
            return False
        
        return combined_strategy
    
    def generate_validation_report(self, 
                                  validated_patterns: List[ValidatedPattern],
                                  top_n: int = 10) -> str:
        """
        生成验证报告
        
        Args:
            validated_patterns: 验证后的Pattern列表
            top_n: 显示Top N个Pattern
        
        Returns:
            报告文本
        """
        lines = [
            "=" * 120,
            "Pattern验证报告",
            f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "=" * 120,
            "",
            f"验证参数:",
            f"  训练集比例: {self.train_ratio}",
            f"  最小测试样本: {self.min_test_samples}",
            f"  手续费: {self.fee}%",
            f"  滑点: {self.slippage}%",
            "",
        ]
        
        # 统计信息
        valid_count = sum(1 for p in validated_patterns if p.is_valid)
        lines.extend([
            "【验证统计】",
            "-" * 120,
            f"总Pattern数: {len(validated_patterns)}",
            f"通过验证数: {valid_count}",
            f"通过率: {valid_count/len(validated_patterns)*100:.1f}%" if validated_patterns else "通过率: 0%",
            "",
        ])
        
        # Top Pattern
        sorted_patterns = self.rank_patterns(validated_patterns)
        
        lines.extend([
            "【Top Pattern】（按综合评分排序）",
            "-" * 120,
            f"{'ID':<5} {'方法':<12} {'训练胜率':>10} {'训练收益':>10} {'测试胜率':>10} {'测试收益':>10} {'真实收益':>10} {'稳定性':>10} {'综合评分':>10} {'通过':>6}",
            "-" * 120,
        ])
        
        for i, p in enumerate(sorted_patterns[:top_n]):
            lines.append(
                f"{p.pattern_id:<5} {p.method:<12} "
                f"{p.train_win_rate*100:>9.1f}% {p.train_expected_return:>9.3f}% "
                f"{p.test_win_rate*100:>9.1f}% {p.test_expected_return:>9.3f}% "
                f"{p.real_expected_return:>9.3f}% {p.stability_score:>10.3f} "
                f"{p.composite_score:>10.3f} {'✅' if p.is_valid else '❌':>6}"
            )
        
        lines.extend(["-" * 120, ""])
        
        # 过拟合警告
        overfitting_patterns = [
            p for p in validated_patterns
            if p.train_expected_return > 0 and p.test_expected_return < 0
        ]
        
        if overfitting_patterns:
            lines.extend([
                "【过拟合警告】",
                "-" * 120,
                f"发现 {len(overfitting_patterns)} 个Pattern在训练集赚钱但测试集亏损:",
            ])
            
            for p in overfitting_patterns[:5]:
                cond_str = str(p.conditions)[:80]
                lines.append(
                    f"  ❌ {cond_str}... "
                    f"训练: {p.train_expected_return:.3f}% → 测试: {p.test_expected_return:.3f}%"
                )
            
            lines.append("")
        
        # 建议
        lines.extend([
            "【行动建议】",
            "-" * 120,
        ])
        
        if valid_count > 0:
            best = sorted_patterns[0]
            lines.extend([
                f"1. 推荐使用Pattern #{best.pattern_id}",
                f"   条件: {best.conditions}",
                f"   测试胜率: {best.test_win_rate*100:.1f}%",
                f"   真实期望收益: {best.real_expected_return:.3f}%",
                "",
                "2. 应用交易成本过滤:",
                f"   手续费+滑点 = {self.fee + self.slippage}%",
                f"   确保期望收益 > {self.fee + self.slippage}%",
                "",
                "3. 使用组合策略提高稳定性:",
                f"   组合Top {min(3, valid_count)} 个Pattern进行投票",
            ])
        else:
            lines.extend([
                "❌ 没有Pattern通过验证",
                "",
                "建议:",
                "1. 检查数据质量",
                "2. 增加样本数量",
                "3. 放宽验证条件",
                "4. 调整Pattern Mining参数",
            ])
        
        lines.append("=" * 120)
        
        return "\n".join(lines)
