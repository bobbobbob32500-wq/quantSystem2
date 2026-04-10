# -*- coding: utf-8 -*-
"""
完整量化策略系统（Complete Quantitative Strategy System）
Pattern Mining + Validation + Robustness 完整整合
"""

import pandas as pd
import numpy as np
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple, Callable
from dataclasses import dataclass

from src.core.logger import get_logger
from src.modules.pattern_mining import PatternMiningEngine
from src.modules.validation_engine import ValidationEngine, ValidatedPattern
from src.modules.robustness_engine import RobustnessEngine, RobustnessResult

logger = get_logger("complete_strategy_system")


@dataclass
class CompleteSystemResult:
    """完整系统结果"""
    # 数据
    train_data: pd.DataFrame
    test_data: pd.DataFrame
    
    # Pattern Mining
    profit_patterns: pd.DataFrame
    loss_patterns: pd.DataFrame
    
    # Validation
    validated_patterns: List[ValidatedPattern]
    valid_patterns: List[ValidatedPattern]
    
    # Robustness
    robust_patterns: List[RobustnessResult]
    final_patterns: List[RobustnessResult]
    
    # 最佳Pattern
    best_pattern: Optional[RobustnessResult]
    
    # 策略函数
    strategy_func: Optional[Callable]
    
    # 报告
    report: str
    composite_score: float = 0.0
    summary: Dict[str, Any] = None


class CompleteStrategySystem:
    """完整量化策略系统"""
    
    def __init__(self,
                 # Pattern Mining参数
                 min_sample_size: int = 20,
                 
                 # Validation参数
                 train_ratio: float = 0.7,
                 min_test_samples: int = 20,
                 fee: float = 0.1,
                 slippage: float = 0.05,
                 
                 # Robustness参数
                 wf_window_size: int = 200,
                 wf_step: int = 50,
                 min_consistency: float = 0.6,
                 max_drawdown_threshold: float = 0.15,
                 significance_level: float = 0.05):
        """
        初始化完整系统
        
        Args:
            min_sample_size: Pattern Mining最小样本数
            train_ratio: 训练集比例
            min_test_samples: 验证最小测试样本数
            fee: 手续费（%）
            slippage: 滑点（%）
            wf_window_size: Walk-Forward窗口大小
            wf_step: Walk-Forward步长
            min_consistency: 最小一致性要求
            max_drawdown_threshold: 最大回撤阈值
            significance_level: 显著性水平
        """
        # 初始化各引擎
        self.pattern_miner = PatternMiningEngine(min_sample_size=min_sample_size)
        
        self.validator = ValidationEngine(
            train_ratio=train_ratio,
            min_test_samples=min_test_samples,
            fee=fee,
            slippage=slippage
        )
        
        self.robustness_checker = RobustnessEngine(
            wf_window_size=wf_window_size,
            wf_step=wf_step,
            min_consistency=min_consistency,
            max_drawdown_threshold=max_drawdown_threshold,
            significance_level=significance_level
        )
        
        logger.info("=" * 80)
        logger.info("完整量化策略系统初始化完成")
        logger.info("=" * 80)
    
    def run_complete_pipeline(self,
                             trades: List[Dict],
                             max_depth: int = 3,
                             top_n: int = 20) -> CompleteSystemResult:
        """
        运行完整流程
        
        Args:
            trades: 交易记录列表
            max_depth: Pattern最大深度
            top_n: Top N个Pattern
        
        Returns:
            完整系统结果
        """
        logger.info("=" * 80)
        logger.info("开始完整策略系统流程...")
        logger.info("=" * 80)

        trades = self._normalize_trade_input(trades)
        if not trades:
            logger.warning("输入交易数据为空")
            return self._empty_result()
        
        # ==================== Level 1: Pattern Mining ====================
        logger.info("\n[Level 1] Pattern Mining...")
        
        # 数据切分
        train_data, test_data = self.validator.split_data_by_time(trades)
        
        if train_data.empty or test_data.empty:
            logger.error("数据切分失败")
            return self._empty_result()
        
        # Pattern Mining（只在训练集）
        profit_patterns, loss_patterns = self.pattern_miner.run(
            train_data.to_dict('records'),
            max_depth=max_depth,
            top_n=top_n
        )
        
        if profit_patterns.empty:
            logger.warning("未发现赚钱Pattern")
            return self._empty_result()
        
        logger.info(f"发现 {len(profit_patterns)} 个赚钱Pattern")
        
        # ==================== Level 2: Validation ====================
        logger.info("\n[Level 2] Validation Engine...")
        
        # 准备Pattern列表
        patterns_to_validate = []
        for i, row in profit_patterns.iterrows():
            patterns_to_validate.append({
                'pattern_id': i,
                'conditions': row.get('conditions', {}),
                'method': row.get('method', 'combination'),
            })
        
        # 验证Pattern
        validated_patterns = self.validator.validate_patterns(
            patterns_to_validate,
            train_data,
            test_data,
            self.pattern_miner.convert_pattern_to_strategy
        )
        
        # 筛选通过验证的Pattern
        valid_patterns = [p for p in validated_patterns if p.is_valid]
        
        logger.info(f"通过验证: {len(valid_patterns)}/{len(validated_patterns)}")
        
        if not valid_patterns:
            logger.warning("没有Pattern通过验证")
            return self._empty_result()
        
        # ==================== Level 3: Robustness ====================
        logger.info("\n[Level 3] Robustness Engine...")
        
        # 鲁棒性验证
        robust_patterns = []
        
        for pattern, validated in zip(patterns_to_validate, validated_patterns):
            if not validated.is_valid:
                continue
            
            pattern_func = self.pattern_miner.convert_pattern_to_strategy(
                pattern['conditions']
            )
            
            robustness_result = self.robustness_checker.validate_robustness(
                pattern,
                test_data,  # 在测试集上进行鲁棒性验证
                pattern_func,
                min_samples=15
            )
            
            robust_patterns.append(robustness_result)
        
        # 筛选通过鲁棒性验证的Pattern
        final_patterns = [p for p in robust_patterns if p.is_robust]
        
        logger.info(f"通过鲁棒性验证: {len(final_patterns)}/{len(robust_patterns)}")
        
        # ==================== 选择最佳Pattern ====================
        if final_patterns:
            best_pattern = max(final_patterns, key=lambda x: x.robustness_score)
            
            # 生成策略函数
            best_pattern_dict = next(
                (p for p in patterns_to_validate if p['pattern_id'] == best_pattern.pattern_id),
                None
            )
            
            if best_pattern_dict:
                strategy_func = self.pattern_miner.convert_pattern_to_strategy(
                    best_pattern_dict['conditions']
                )
            else:
                strategy_func = None
        else:
            best_pattern = None
            strategy_func = None
        
        # ==================== 生成报告 ====================
        report = self._generate_complete_report(
            train_data, test_data,
            profit_patterns, loss_patterns,
            validated_patterns, valid_patterns,
            robust_patterns, final_patterns,
            best_pattern
        )
        
        composite_score = self._compute_composite_score(valid_patterns, final_patterns, best_pattern)
        summary = self._build_result_summary(
            train_data=train_data,
            test_data=test_data,
            valid_patterns=valid_patterns,
            final_patterns=final_patterns,
            best_pattern=best_pattern,
            composite_score=composite_score,
        )

        return CompleteSystemResult(
            train_data=train_data,
            test_data=test_data,
            profit_patterns=profit_patterns,
            loss_patterns=loss_patterns,
            validated_patterns=validated_patterns,
            valid_patterns=valid_patterns,
            robust_patterns=robust_patterns,
            final_patterns=final_patterns,
            best_pattern=best_pattern,
            strategy_func=strategy_func,
            report=report,
            composite_score=composite_score,
            summary=summary,
        )
    
    def _empty_result(self) -> CompleteSystemResult:
        """返回空结果"""
        return CompleteSystemResult(
            train_data=pd.DataFrame(),
            test_data=pd.DataFrame(),
            profit_patterns=pd.DataFrame(),
            loss_patterns=pd.DataFrame(),
            validated_patterns=[],
            valid_patterns=[],
            robust_patterns=[],
            final_patterns=[],
            best_pattern=None,
            strategy_func=None,
            report="系统运行失败",
            composite_score=0.0,
            summary={"status": "empty", "composite_score": 0.0},
        )

    @staticmethod
    def _normalize_trade_input(trades: Any) -> List[Dict]:
        if trades is None:
            return []
        if isinstance(trades, pd.DataFrame):
            if trades.empty:
                return []
            return trades.to_dict("records")
        if isinstance(trades, list):
            return trades
        try:
            return list(trades)
        except Exception:
            return []

    @staticmethod
    def _compute_composite_score(
        valid_patterns: List[ValidatedPattern],
        final_patterns: List[RobustnessResult],
        best_pattern: Optional[RobustnessResult],
    ) -> float:
        if best_pattern is not None:
            return float(best_pattern.robustness_score)
        if final_patterns:
            return float(max(item.robustness_score for item in final_patterns))
        if valid_patterns:
            return float(max(item.composite_score for item in valid_patterns))
        return 0.0

    @staticmethod
    def _build_result_summary(
        train_data: pd.DataFrame,
        test_data: pd.DataFrame,
        valid_patterns: List[ValidatedPattern],
        final_patterns: List[RobustnessResult],
        best_pattern: Optional[RobustnessResult],
        composite_score: float,
    ) -> Dict[str, Any]:
        summary = {
            "status": "ok",
            "train_size": int(len(train_data)),
            "test_size": int(len(test_data)),
            "valid_pattern_count": int(len(valid_patterns)),
            "robust_pattern_count": int(len(final_patterns)),
            "composite_score": float(composite_score),
            "best_pattern_id": int(best_pattern.pattern_id) if best_pattern is not None else None,
        }
        if best_pattern is not None:
            summary.update(
                {
                    "best_pattern_score": float(best_pattern.robustness_score),
                    "best_pattern_drawdown": float(best_pattern.max_drawdown),
                    "best_pattern_sharpe": float(best_pattern.sharpe_ratio),
                }
            )
        return summary
    
    def _generate_complete_report(self,
                                 train_data: pd.DataFrame,
                                 test_data: pd.DataFrame,
                                 profit_patterns: pd.DataFrame,
                                 loss_patterns: pd.DataFrame,
                                 validated_patterns: List[ValidatedPattern],
                                 valid_patterns: List[ValidatedPattern],
                                 robust_patterns: List[RobustnessResult],
                                 final_patterns: List[RobustnessResult],
                                 best_pattern: Optional[RobustnessResult]) -> str:
        """生成完整报告"""
        lines = [
            "=" * 120,
            "完整量化策略系统报告",
            f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "=" * 120,
            "",
            "【系统流程】",
            "-" * 120,
            "Level 1: Pattern Mining → 发现模式",
            "Level 2: Validation Engine → 验证有效性",
            "Level 3: Robustness Engine → 确保未来可活",
            "",
            "【数据统计】",
            "-" * 120,
            f"训练集: {len(train_data)} 条",
            f"测试集: {len(test_data)} 条",
            "",
            "【Level 1: Pattern Mining】",
            "-" * 120,
            f"赚钱Pattern: {len(profit_patterns)} 个",
            f"亏钱Pattern: {len(loss_patterns)} 个",
            "",
            "【Level 2: Validation】",
            "-" * 120,
            f"验证Pattern: {len(validated_patterns)} 个",
            f"通过验证: {len(valid_patterns)} 个",
            f"通过率: {len(valid_patterns)/len(validated_patterns)*100:.1f}%" if validated_patterns else "通过率: 0%",
            "",
            "【Level 3: Robustness】",
            "-" * 120,
            f"鲁棒性验证: {len(robust_patterns)} 个",
            f"通过鲁棒性: {len(final_patterns)} 个",
            f"通过率: {len(final_patterns)/len(robust_patterns)*100:.1f}%" if robust_patterns else "通过率: 0%",
            "",
        ]
        
        # 最佳Pattern
        if best_pattern:
            lines.extend([
                "【最佳Pattern】",
                "-" * 120,
                f"Pattern ID: {best_pattern.pattern_id}",
                f"条件: {best_pattern.conditions}",
                "",
                "鲁棒性指标:",
                f"  Walk-Forward一致性: {best_pattern.wf_consistency:.2%}",
                f"  统计显著性: {'是' if best_pattern.is_significant else '否'} (p={best_pattern.p_value:.4f})",
                f"  置信区间: [{best_pattern.confidence_interval[0]:.3f}, {best_pattern.confidence_interval[1]:.3f}]",
                f"  最大回撤: {best_pattern.max_drawdown:.2%}",
                f"  夏普比率: {best_pattern.sharpe_ratio:.2f}",
                f"  鲁棒性评分: {best_pattern.robustness_score:.3f}",
                "",
                "市场状态表现:",
            ])
            
            for regime, perf in best_pattern.regime_performance.items():
                if perf.get('is_valid'):
                    lines.append(
                        f"  {regime}: 胜率{perf['win_rate']*100:.1f}%, 收益{perf['expected_return']:.3f}% ✅"
                    )
                else:
                    lines.append(f"  {regime}: 未通过 ❌")
        
        # 最终建议
        lines.extend([
            "",
            "【最终建议】",
            "-" * 120,
        ])
        
        if final_patterns:
            lines.extend([
                "✅ 系统验证完成，推荐进入实盘测试",
                "",
                "实盘部署步骤:",
                "1. 使用最佳Pattern进行模拟盘测试（1-2周）",
                "2. 监控实盘表现与测试集表现差异",
                "3. 如表现稳定，逐步增加仓位",
                "4. 定期重新训练和验证（建议每月）",
                "",
                "风险控制:",
                f"- 最大回撤限制: {self.robustness_checker.max_drawdown_threshold:.2%}",
                f"- 手续费+滑点: {self.validator.fee + self.validator.slippage:.2f}%",
                "- 建议仓位: 单Pattern不超过总资金10%",
            ])
        else:
            lines.extend([
                "❌ 没有Pattern通过完整验证",
                "",
                "可能原因:",
                "1. 数据量不足",
                "2. 市场环境变化",
                "3. Pattern过拟合",
                "4. 验证条件过严",
                "",
                "建议:",
                "1. 增加历史数据（至少1000条）",
                "2. 调整Pattern Mining参数",
                "3. 放宽验证条件",
                "4. 尝试不同的特征组合",
            ])
        
        lines.append("=" * 120)
        
        return "\n".join(lines)


def run_complete_strategy_system(trades: List[Dict],
                                top_n: int = 20) -> str:
    """
    运行完整策略系统（便捷函数）
    
    Args:
        trades: 交易记录列表
        top_n: Top N个Pattern
    
    Returns:
        报告文本
    """
    system = CompleteStrategySystem()
    result = system.run_complete_pipeline(trades, top_n=top_n)
    return result.report
