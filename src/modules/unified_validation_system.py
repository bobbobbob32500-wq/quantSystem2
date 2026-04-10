# -*- coding: utf-8 -*-
"""
统一验证系统（Unified Validation System）
Pattern Mining + Validation Engine完整整合
"""

import pandas as pd
import numpy as np
from datetime import datetime
from typing import Dict, List, Optional, Tuple, Callable
from dataclasses import dataclass

from src.core.logger import get_logger
from src.modules.pattern_mining import PatternMiningEngine
from src.modules.ml_pattern_mining import MLPatternMiningEngine
from src.modules.validation_engine import ValidationEngine, ValidatedPattern

logger = get_logger("unified_validation_system")


@dataclass
class SystemResult:
    """系统结果数据结构"""
    # 数据切分
    train_data: pd.DataFrame
    test_data: pd.DataFrame
    
    # Pattern Mining结果
    profit_patterns: pd.DataFrame
    loss_patterns: pd.DataFrame
    
    # 验证结果
    validated_patterns: List[ValidatedPattern]
    valid_patterns: List[ValidatedPattern]
    
    # 最佳Pattern
    best_pattern: Optional[ValidatedPattern]
    
    # 组合策略
    combined_strategy: Optional[Callable]
    
    # 报告
    report: str


class UnifiedValidationSystem:
    """统一验证系统"""
    
    def __init__(self,
                 train_ratio: float = 0.7,
                 min_sample_size: int = 20,
                 min_test_samples: int = 20,
                 fee: float = 0.1,
                 slippage: float = 0.05):
        """
        初始化统一验证系统
        
        Args:
            train_ratio: 训练集比例
            min_sample_size: Pattern Mining最小样本数
            min_test_samples: 验证最小测试样本数
            fee: 手续费（%）
            slippage: 滑点（%）
        """
        self.pattern_miner = PatternMiningEngine(min_sample_size=min_sample_size)
        self.ml_miner = MLPatternMiningEngine()
        self.validator = ValidationEngine(
            train_ratio=train_ratio,
            min_test_samples=min_test_samples,
            fee=fee,
            slippage=slippage
        )
        
        logger.info("=" * 80)
        logger.info("统一验证系统初始化完成")
        logger.info(f"  训练集比例: {train_ratio}")
        logger.info(f"  手续费: {fee}%")
        logger.info(f"  滑点: {slippage}%")
        logger.info("=" * 80)
    
    def run_full_pipeline(self,
                         trades: List[Dict],
                         max_depth: int = 3,
                         top_n: int = 20,
                         use_ml: bool = False) -> SystemResult:
        """
        运行完整流程
        
        Args:
            trades: 交易记录列表
            max_depth: Pattern最大深度
            top_n: Top N个Pattern
            use_ml: 是否使用机器学习方法
        
        Returns:
            系统结果
        """
        logger.info("=" * 80)
        logger.info("开始完整验证流程...")
        logger.info("=" * 80)
        
        # Step 1: 数据切分（防止数据泄露）
        logger.info("\n[Step 1] 数据切分...")
        train_data, test_data = self.validator.split_data_by_time(trades)
        
        if train_data.empty or test_data.empty:
            logger.error("数据切分失败")
            return self._empty_result()
        
        # Step 2: Pattern Mining（只在训练集）
        logger.info("\n[Step 2] Pattern Mining（训练集）...")
        
        if use_ml:
            # 使用机器学习方法
            ml_results = self.ml_miner.run(
                train_data.to_dict('records'),
                use_decision_tree=True,
                use_lightgbm=True
            )
            
            # 提取Pattern（简化）
            profit_patterns = pd.DataFrame()
            loss_patterns = pd.DataFrame()
            
            if 'decision_tree' in ml_results and ml_results['decision_tree']:
                dt_rules = ml_results['decision_tree']['profit_rules']
                if dt_rules:
                    profit_patterns = pd.DataFrame([
                        {
                            'conditions': r.conditions,
                            'method': 'decision_tree',
                            'win_rate': r.win_rate,
                            'expected_return': r.expected_return,
                            'sample_size': r.sample_size,
                        }
                        for r in dt_rules
                    ])
        else:
            # 使用组合枚举方法
            profit_patterns, loss_patterns = self.pattern_miner.run(
                train_data.to_dict('records'),
                max_depth=max_depth,
                top_n=top_n
            )
        
        if profit_patterns.empty:
            logger.warning("未发现赚钱Pattern")
            return self._empty_result()
        
        logger.info(f"发现 {len(profit_patterns)} 个赚钱Pattern")
        
        # Step 3: Pattern验证（在测试集）
        logger.info("\n[Step 3] Pattern验证（测试集）...")
        
        # 准备Pattern列表
        patterns_to_validate = []
        for i, row in profit_patterns.iterrows():
            patterns_to_validate.append({
                'pattern_id': i,
                'conditions': row.get('conditions', {}),
                'method': row.get('method', 'combination'),
            })
        
        # 验证
        validated_patterns = self.validator.validate_patterns(
            patterns_to_validate,
            train_data,
            test_data,
            self.pattern_miner.convert_pattern_to_strategy
        )
        
        # Step 4: 筛选通过验证的Pattern
        valid_patterns = [p for p in validated_patterns if p.is_valid]
        
        logger.info(f"通过验证: {len(valid_patterns)}/{len(validated_patterns)}")
        
        # Step 5: 排序
        sorted_patterns = self.validator.rank_patterns(validated_patterns)
        
        # Step 6: 选择最佳Pattern
        best_pattern = sorted_patterns[0] if sorted_patterns else None
        
        # Step 7: 生成组合策略
        combined_strategy = None
        if len(sorted_patterns) >= 3:
            combined_strategy = self.validator.combine_patterns(
                sorted_patterns[:3],
                self.pattern_miner.convert_pattern_to_strategy
            )
            logger.info("生成组合策略（Top 3 Pattern投票）")
        
        # Step 8: 生成报告
        report = self._generate_full_report(
            train_data, test_data,
            profit_patterns, loss_patterns,
            validated_patterns, valid_patterns,
            best_pattern
        )
        
        return SystemResult(
            train_data=train_data,
            test_data=test_data,
            profit_patterns=profit_patterns,
            loss_patterns=loss_patterns,
            validated_patterns=validated_patterns,
            valid_patterns=valid_patterns,
            best_pattern=best_pattern,
            combined_strategy=combined_strategy,
            report=report
        )
    
    def _empty_result(self) -> SystemResult:
        """返回空结果"""
        return SystemResult(
            train_data=pd.DataFrame(),
            test_data=pd.DataFrame(),
            profit_patterns=pd.DataFrame(),
            loss_patterns=pd.DataFrame(),
            validated_patterns=[],
            valid_patterns=[],
            best_pattern=None,
            combined_strategy=None,
            report="验证失败"
        )
    
    def _generate_full_report(self,
                             train_data: pd.DataFrame,
                             test_data: pd.DataFrame,
                             profit_patterns: pd.DataFrame,
                             loss_patterns: pd.DataFrame,
                             validated_patterns: List[ValidatedPattern],
                             valid_patterns: List[ValidatedPattern],
                             best_pattern: Optional[ValidatedPattern]) -> str:
        """生成完整报告"""
        lines = [
            "=" * 120,
            "统一验证系统报告",
            f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "=" * 120,
            "",
            "【数据切分】",
            "-" * 120,
            f"训练集: {len(train_data)} 条",
            f"测试集: {len(test_data)} 条",
            "",
            "【Pattern Mining结果】",
            "-" * 120,
            f"赚钱Pattern: {len(profit_patterns)} 个",
            f"亏钱Pattern: {len(loss_patterns)} 个",
            "",
            "【验证结果】",
            "-" * 120,
            f"验证Pattern: {len(validated_patterns)} 个",
            f"通过验证: {len(valid_patterns)} 个",
            f"通过率: {len(valid_patterns)/len(validated_patterns)*100:.1f}%" if validated_patterns else "通过率: 0%",
            "",
        ]
        
        # 最佳Pattern
        if best_pattern:
            lines.extend([
                "【最佳Pattern】",
                "-" * 120,
                f"Pattern ID: {best_pattern.pattern_id}",
                f"方法: {best_pattern.method}",
                f"条件: {best_pattern.conditions}",
                "",
                f"训练集表现:",
                f"  胜率: {best_pattern.train_win_rate*100:.1f}%",
                f"  期望收益: {best_pattern.train_expected_return:.3f}%",
                f"  样本数: {best_pattern.train_sample_size}",
                "",
                f"测试集表现:",
                f"  胜率: {best_pattern.test_win_rate*100:.1f}%",
                f"  期望收益: {best_pattern.test_expected_return:.3f}%",
                f"  样本数: {best_pattern.test_sample_size}",
                "",
                f"稳定性:",
                f"  收益波动: {best_pattern.std_return:.3f}",
                f"  稳定性评分: {best_pattern.stability_score:.3f}",
                "",
                f"真实表现（考虑交易成本）:",
                f"  期望收益: {best_pattern.real_expected_return:.3f}%",
                "",
                f"综合评分: {best_pattern.composite_score:.3f}",
                "",
            ])
        
        # 过拟合分析
        overfitting = [
            p for p in validated_patterns
            if p.train_expected_return > 0 and p.test_expected_return < 0
        ]
        
        if overfitting:
            lines.extend([
                "【过拟合警告】",
                "-" * 120,
                f"发现 {len(overfitting)} 个过拟合Pattern（训练赚钱，测试亏损）",
                "",
            ])
        
        # 建议
        lines.extend([
            "【行动建议】",
            "-" * 120,
        ])
        
        if valid_patterns:
            lines.extend([
                "✅ 系统验证通过，可以进入实盘测试",
                "",
                "建议步骤:",
                "1. 使用最佳Pattern进行模拟盘测试",
                "2. 监控实盘表现与测试集表现差异",
                "3. 定期重新训练和验证（建议每月）",
                "4. 使用组合策略提高稳定性",
                "",
                f"预期表现:",
                f"  胜率: {best_pattern.test_win_rate*100:.1f}%",
                f"  期望收益: {best_pattern.real_expected_return:.3f}%",
            ])
        else:
            lines.extend([
                "❌ 没有Pattern通过验证",
                "",
                "可能原因:",
                "1. 数据量不足",
                "2. 市场环境变化",
                "3. Pattern过拟合",
                "",
                "建议:",
                "1. 增加历史数据",
                "2. 调整Pattern Mining参数",
                "3. 放宽验证条件",
            ])
        
        lines.append("=" * 120)
        
        return "\n".join(lines)
    
    def export_strategy(self, result: SystemResult) -> Optional[Callable]:
        """
        导出策略函数
        
        Args:
            result: 系统结果
        
        Returns:
            策略函数
        """
        if result.combined_strategy:
            return result.combined_strategy
        
        if result.best_pattern:
            return self.pattern_miner.convert_pattern_to_strategy(
                result.best_pattern.conditions
            )
        
        return None


def run_unified_validation(trades: List[Dict],
                          top_n: int = 20,
                          use_ml: bool = False) -> str:
    """
    运行统一验证（便捷函数）
    
    Args:
        trades: 交易记录列表
        top_n: Top N个Pattern
        use_ml: 是否使用机器学习
    
    Returns:
        报告文本
    """
    system = UnifiedValidationSystem()
    result = system.run_full_pipeline(trades, top_n=top_n, use_ml=use_ml)
    return result.report
