# -*- coding: utf-8 -*-
"""
完整的自动优化模块
实现参数优化 + 效果验证 + 完整反馈闭环
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Callable, Tuple
from datetime import datetime
import itertools
import logging
from dataclasses import dataclass, field

logger = logging.getLogger("AutoOptimizer")


@dataclass
class OptimizationResult:
    """优化结果"""
    best_params: Dict
    best_score: float
    before_metrics: Dict
    after_metrics: Dict
    improved: bool
    timestamp: datetime
    robustness_score: float = 0.0
    sensitivity_report: Dict = field(default_factory=dict)


class ParameterOptimizer:
    """
    参数优化器
    自动搜索参数空间，找到最优参数组合
    """
    
    def __init__(self, param_space: Dict[str, List]):
        """
        初始化参数优化器
        
        Args:
            param_space: 参数空间，例如
                {
                    'rsi_low': [45, 50, 55],
                    'rsi_high': [55, 60, 65],
                    'volume_ratio': [1.2, 1.5, 2.0],
                }
        """
        self.param_space = param_space
        self.optimization_history = []
        
        logger.info(f"参数优化器初始化完成，参数空间: {list(param_space.keys())}")

    def _score_metrics(self, metrics: Dict) -> float:
        """将多维表现指标压缩为一个优化分值。"""
        win_rate = float(metrics.get('win_rate', 0) or 0)
        avg_pnl = float(metrics.get('avg_pnl', 0) or 0)
        sharpe = float(metrics.get('sharpe', metrics.get('sharpe_ratio', 0)) or 0)
        max_drawdown = abs(float(metrics.get('max_drawdown', metrics.get('drawdown', 0)) or 0))
        pnl_std = float(metrics.get('pnl_std', metrics.get('return_std', 0)) or 0)

        # 胜率和平均收益是主信号，波动和回撤作为惩罚项。
        return (
            win_rate * 0.55 +
            avg_pnl * 15.0 +
            sharpe * 0.15 -
            max_drawdown * 0.10 -
            pnl_std * 2.0
        )

    def _get_neighbor_values(self, param_name: str, base_value) -> List:
        """获取参数空间里与当前值最接近的邻居值，用于灵敏度分析。"""
        values = list(self.param_space.get(param_name, []))
        if not values:
            return []

        if base_value in values:
            base_index = values.index(base_value)
        else:
            try:
                distances = [
                    abs(float(value) - float(base_value))
                    for value in values
                ]
                base_index = int(np.argmin(distances))
            except (TypeError, ValueError):
                return []

        neighbors = []
        if base_index > 0:
            neighbors.append(values[base_index - 1])
        if base_index < len(values) - 1:
            neighbors.append(values[base_index + 1])

        return [value for value in neighbors if value != base_value]
    
    def grid_search(self, 
                   trades: List[Dict], 
                   evaluate_func: Callable,
                   max_combinations: int = 100) -> Tuple[Dict, float]:
        """
        网格搜索找到最佳参数组合
        
        Args:
            trades: 交易历史
            evaluate_func: 评价函数，返回 {'win_rate':.., 'avg_pnl':..}
            max_combinations: 最大组合数（防止组合爆炸）
        
        Returns:
            (best_params, best_score)
        """
        keys = list(self.param_space.keys())
        all_combinations = list(itertools.product(*[self.param_space[k] for k in keys]))
        
        # 限制组合数量
        if len(all_combinations) > max_combinations:
            # 随机采样
            import random
            all_combinations = random.sample(all_combinations, max_combinations)
        
        best_score = -np.inf
        best_params = {}
        all_results = []
        
        logger.info(f"开始网格搜索，共{len(all_combinations)}个参数组合")
        
        for i, values in enumerate(all_combinations):
            params = dict(zip(keys, values))
            
            try:
                metrics = evaluate_func(trades, params)
                
                # 综合评分：收益能力 + 稳定性
                score = self._score_metrics(metrics)
                
                all_results.append({
                    'params': params,
                    'metrics': metrics,
                    'score': score
                })
                
                if score > best_score:
                    best_score = score
                    best_params = params
                    
            except Exception as e:
                logger.warning(f"参数组合{params}评价失败: {e}")
                continue
        
        logger.info(f"网格搜索完成，最佳参数: {best_params}, 得分: {best_score:.3f}")
        
        return best_params, best_score

    def sensitivity_analysis(self,
                             trades: List[Dict],
                             evaluate_func: Callable,
                             base_params: Dict) -> Dict:
        """
        对最佳参数做局部扰动，评估参数灵敏度。

        Returns:
            {
                'base_score': float,
                'robustness_score': float,
                'parameters': {
                    'param_name': {
                        'baseline_value': ...,
                        'baseline_score': ...,
                        'tested_values': [...],
                        'stability': ...,
                        'downside_penalty': ...,
                        'robustness': ...
                    }
                }
            }
        """
        if not base_params:
            return {
                'base_score': 0.0,
                'robustness_score': 0.0,
                'parameters': {}
            }

        try:
            base_metrics = evaluate_func(trades, base_params)
            base_score = self._score_metrics(base_metrics)
        except Exception as exc:
            logger.warning(f"灵敏度分析基线评估失败: {exc}")
            return {
                'base_score': 0.0,
                'robustness_score': 0.0,
                'parameters': {}
            }

        parameter_reports = {}
        robustness_scores = []

        for param_name, base_value in base_params.items():
            neighbors = self._get_neighbor_values(param_name, base_value)
            tested_values = []

            for neighbor in neighbors:
                trial_params = dict(base_params)
                trial_params[param_name] = neighbor

                try:
                    trial_metrics = evaluate_func(trades, trial_params)
                    trial_score = self._score_metrics(trial_metrics)
                    tested_values.append({
                        'value': neighbor,
                        'score': round(trial_score, 4),
                        'score_delta': round(trial_score - base_score, 4)
                    })
                except Exception as exc:
                    logger.warning(
                        f"灵敏度分析失败: 参数 {param_name}={neighbor} 评估异常: {exc}"
                    )

            if not tested_values:
                parameter_reports[param_name] = {
                    'baseline_value': base_value,
                    'baseline_score': round(base_score, 4),
                    'tested_values': [],
                    'stability': 1.0,
                    'downside_penalty': 1.0,
                    'robustness': 1.0
                }
                robustness_scores.append(1.0)
                continue

            scores = [base_score] + [item['score'] for item in tested_values]
            score_std = float(np.std(scores))
            worst_delta = min(item['score_delta'] for item in tested_values)
            tolerance = max(abs(base_score), 0.2)

            stability = max(0.0, 1.0 - score_std / tolerance)
            downside_penalty = max(0.0, 1.0 + min(0.0, worst_delta) / tolerance)
            robustness = min(1.0, max(0.0, stability * 0.6 + downside_penalty * 0.4))

            parameter_reports[param_name] = {
                'baseline_value': base_value,
                'baseline_score': round(base_score, 4),
                'tested_values': tested_values,
                'stability': round(stability, 4),
                'downside_penalty': round(downside_penalty, 4),
                'robustness': round(robustness, 4)
            }
            robustness_scores.append(robustness)

        robustness_score = float(np.mean(robustness_scores)) if robustness_scores else 0.0
        return {
            'base_score': round(base_score, 4),
            'robustness_score': round(robustness_score, 4),
            'parameters': parameter_reports
        }
    
    def optimize_factor_weights(self, 
                               factor_performance: Dict[str, Dict]) -> Dict[str, float]:
        """
        优化因子权重
        
        Args:
            factor_performance: 各因子表现，例如
                {
                    'momentum': {'win_rate': 0.65, 'avg_pnl': 0.05},
                    'value': {'win_rate': 0.55, 'avg_pnl': 0.02},
                }
        
        Returns:
            新的因子权重
        """
        new_weights = {}
        total_score = 0
        
        # 计算各因子得分
        for factor, perf in factor_performance.items():
            score = perf.get('win_rate', 0.5) + perf.get('avg_pnl', 0)
            total_score += score
            new_weights[factor] = score
        
        # 归一化
        if total_score > 0:
            for factor in new_weights:
                new_weights[factor] /= total_score
        
        logger.info(f"因子权重优化完成: {new_weights}")
        return new_weights


class EffectValidator:
    """
    效果验证器
    验证优化效果，确保策略确实提升
    """
    
    def __init__(self, 
                 min_win_rate_improvement: float = 0.01,
                 min_pnl_improvement: float = 0.01,
                 use_significance_test: bool = False):
        """
        初始化效果验证器
        
        Args:
            min_win_rate_improvement: 胜率最小提升阈值
            min_pnl_improvement: 盈亏最小提升阈值
            use_significance_test: 是否使用统计显著性检验
        """
        self.min_win_rate_improvement = min_win_rate_improvement
        self.min_pnl_improvement = min_pnl_improvement
        self.use_significance_test = use_significance_test
        
        logger.info(f"效果验证器初始化完成，最小提升: 胜率{min_win_rate_improvement:.1%}, "
                   f"盈亏{min_pnl_improvement:.1%}")

    def _composite_score(self, metrics: Dict) -> float:
        """与优化器保持一致的验证打分。"""
        win_rate = float(metrics.get('win_rate', 0) or 0)
        avg_pnl = float(metrics.get('avg_pnl', 0) or 0)
        sharpe = float(metrics.get('sharpe', metrics.get('sharpe_ratio', 0)) or 0)
        max_drawdown = abs(float(metrics.get('max_drawdown', metrics.get('drawdown', 0)) or 0))
        pnl_std = float(metrics.get('pnl_std', metrics.get('return_std', 0)) or 0)

        return (
            win_rate * 0.55 +
            avg_pnl * 15.0 +
            sharpe * 0.15 -
            max_drawdown * 0.10 -
            pnl_std * 2.0
        )

    def _passes_significance_gate(self,
                                  before_metrics: Dict,
                                  after_metrics: Dict) -> bool:
        """
        生产保守门槛。
        这里不用“伪显著性”冒充统计检验，而是要求足够样本量和足够大的综合提升。
        """
        trade_count = min(
            int(before_metrics.get('trade_count', before_metrics.get('total_trades', 0)) or 0),
            int(after_metrics.get('trade_count', after_metrics.get('total_trades', 0)) or 0)
        )
        score_diff = self._composite_score(after_metrics) - self._composite_score(before_metrics)
        pnl_std = max(
            float(before_metrics.get('pnl_std', 0) or 0),
            float(after_metrics.get('pnl_std', 0) or 0)
        )

        if trade_count < 20:
            logger.warning("显著性门槛未通过: 样本量不足 20 笔")
            return False

        threshold = max(0.01, pnl_std * 0.1)
        passed = score_diff >= threshold
        if not passed:
            logger.warning(
                f"显著性门槛未通过: 综合得分提升 {score_diff:.4f} 低于阈值 {threshold:.4f}"
            )
        return passed
    
    def validate(self, 
                before_metrics: Dict, 
                after_metrics: Dict) -> bool:
        """
        验证优化效果
        
        Args:
            before_metrics: 优化前指标
            after_metrics: 优化后指标
        
        Returns:
            是否通过验证
        """
        # 计算提升
        win_rate_diff = after_metrics.get('win_rate', 0) - before_metrics.get('win_rate', 0)
        pnl_diff = after_metrics.get('avg_pnl', 0) - before_metrics.get('avg_pnl', 0)
        
        # 判断是否提升
        win_rate_improved = win_rate_diff >= self.min_win_rate_improvement
        pnl_improved = pnl_diff >= self.min_pnl_improvement
        
        # 综合判断
        improved = win_rate_improved and pnl_improved
        
        # 统计显著性检验（可选）
        if self.use_significance_test and improved:
            improved = self._passes_significance_gate(before_metrics, after_metrics)

        score_diff = self._composite_score(after_metrics) - self._composite_score(before_metrics)
        
        logger.info(f"效果验证: 胜率提升{win_rate_diff:+.2%}, "
                   f"盈亏提升{pnl_diff:+.2%}, 综合提升{score_diff:+.4f}, 通过={improved}")
        
        return improved
    
    def compare_strategies(self,
                          strategy_a_metrics: Dict,
                          strategy_b_metrics: Dict) -> str:
        """
        对比两个策略
        
        Returns:
            'a' 或 'b' 或 'equal'
        """
        score_a = strategy_a_metrics.get('win_rate', 0) + strategy_a_metrics.get('avg_pnl', 0)
        score_b = strategy_b_metrics.get('win_rate', 0) + strategy_b_metrics.get('avg_pnl', 0)
        
        if score_a > score_b + 0.01:
            return 'a'
        elif score_b > score_a + 0.01:
            return 'b'
        else:
            return 'equal'


class CompleteAutoOptimizer:
    """
    完整的自动优化器
    实现完整的反馈闭环：记录 → 优化 → 验证 → 应用
    """
    
    def __init__(self,
                 param_optimizer: ParameterOptimizer,
                 effect_validator: EffectValidator,
                 evaluate_func: Callable,
                 optimize_interval: int = 50,
                 min_trades_for_optimization: int = 20,
                 min_robustness_score: float = 0.55):
        """
        初始化完整自动优化器
        
        Args:
            param_optimizer: 参数优化器
            effect_validator: 效果验证器
            evaluate_func: 策略评价函数
            optimize_interval: 优化间隔（每N笔交易优化一次）
            min_trades_for_optimization: 最小交易数（少于这个数不优化）
        """
        self.optimizer = param_optimizer
        self.validator = effect_validator
        self.evaluate_func = evaluate_func
        
        self.optimize_interval = optimize_interval
        self.min_trades_for_optimization = min_trades_for_optimization
        self.min_robustness_score = min_robustness_score
        
        # 交易记录
        self.virtual_trades = []
        
        # 当前参数
        self.current_params = {}
        
        # 优化历史
        self.optimization_history = []
        
        # 因子权重
        self.factor_weights = {}
        
        logger.info(f"完整自动优化器初始化完成，优化间隔: 每{optimize_interval}笔交易")
    
    def on_virtual_trade_closed(self, trade: Dict):
        """
        虚拟交易平仓回调
        
        Args:
            trade: 交易记录
        """
        # 记录交易
        self.virtual_trades.append(trade)
        
        # 检查是否触发优化
        if len(self.virtual_trades) >= self.min_trades_for_optimization:
            if len(self.virtual_trades) % self.optimize_interval == 0:
                self._run_optimization()
    
    def _run_optimization(self) -> Optional[OptimizationResult]:
        """
        执行优化流程
        
        Returns:
            优化结果
        """
        logger.info("="*80)
        logger.info(f"开始自动优化流程（第{len(self.optimization_history)+1}次）")
        logger.info(f"当前交易数: {len(self.virtual_trades)}")
        logger.info("="*80)
        
        try:
            # 1. 当前策略表现
            before_metrics = self.evaluate_func(self.virtual_trades, self.current_params)
            logger.info(f"当前策略表现: {before_metrics}")
            
            # 2. 参数优化
            new_params, best_score = self.optimizer.grid_search(
                self.virtual_trades, 
                self.evaluate_func
            )
            logger.info(f"优化后参数: {new_params}, 得分: {best_score:.3f}")
            
            # 3. 新参数策略表现
            after_metrics = self.evaluate_func(self.virtual_trades, new_params)
            logger.info(f"新策略表现: {after_metrics}")

            # 4. 灵敏度分析，避免把尖锐参数直接推到线上
            sensitivity_report = self.optimizer.sensitivity_analysis(
                self.virtual_trades,
                self.evaluate_func,
                new_params
            )
            robustness_score = sensitivity_report.get('robustness_score', 0.0)
            logger.info(f"参数鲁棒性评分: {robustness_score:.3f}")
            
            # 5. 验证效果
            improved = self.validator.validate(before_metrics, after_metrics)
            improved = improved and robustness_score >= self.min_robustness_score
            if not improved and robustness_score < self.min_robustness_score:
                logger.info(
                    f"[SKIP] 参数鲁棒性不足: {robustness_score:.3f} < {self.min_robustness_score:.3f}"
                )
            
            # 6. 决定是否应用
            if improved:
                old_params = self.current_params.copy()
                self.current_params = new_params
                logger.info(f"[SUCCESS] 优化成功，应用新参数")
                logger.info(f"  旧参数: {old_params}")
                logger.info(f"  新参数: {new_params}")
            else:
                logger.info(f"[SKIP] 优化无效，保持现有参数")
            
            # 记录优化历史
            result = OptimizationResult(
                best_params=new_params,
                best_score=best_score,
                before_metrics=before_metrics,
                after_metrics=after_metrics,
                improved=improved,
                timestamp=datetime.now(),
                robustness_score=robustness_score,
                sensitivity_report=sensitivity_report
            )
            self.optimization_history.append(result)
            
            logger.info("="*80)
            logger.info("自动优化流程完成")
            logger.info("="*80)
            
            return result
            
        except Exception as e:
            logger.error(f"优化流程失败: {e}")
            return None
    
    def optimize_factor_weights(self, factor_performance: Dict[str, Dict]) -> Dict[str, float]:
        """
        优化因子权重
        
        Args:
            factor_performance: 各因子表现
        
        Returns:
            新的因子权重
        """
        new_weights = self.optimizer.optimize_factor_weights(factor_performance)
        self.factor_weights = new_weights
        
        logger.info(f"因子权重已更新: {new_weights}")
        return new_weights
    
    def get_current_params(self) -> Dict:
        """获取当前参数"""
        return self.current_params
    
    def get_factor_weights(self) -> Dict[str, float]:
        """获取因子权重"""
        return self.factor_weights
    
    def get_optimization_summary(self) -> Dict:
        """获取优化总结"""
        if not self.optimization_history:
            return {
                'total_optimizations': 0,
                'successful_optimizations': 0,
                'success_rate': 0
            }
        
        successful = sum(1 for r in self.optimization_history if r.improved)
        
        return {
            'total_optimizations': len(self.optimization_history),
            'successful_optimizations': successful,
            'success_rate': successful / len(self.optimization_history),
            'last_optimization': self.optimization_history[-1].timestamp if self.optimization_history else None,
            'current_params': self.current_params,
            'factor_weights': self.factor_weights,
            'avg_robustness': float(np.mean([r.robustness_score for r in self.optimization_history])),
            'last_robustness': self.optimization_history[-1].robustness_score if self.optimization_history else 0.0
        }
    
    def force_optimize(self) -> Optional[OptimizationResult]:
        """强制执行优化（不等待间隔）"""
        if len(self.virtual_trades) < self.min_trades_for_optimization:
            logger.warning(f"交易数不足，无法优化（当前{len(self.virtual_trades)}，"
                          f"需要{self.min_trades_for_optimization}）")
            return None
        
        return self._run_optimization()
    
    def rollback_last_optimization(self) -> bool:
        """回滚上次优化"""
        if len(self.optimization_history) < 2:
            logger.warning("没有可回滚的优化")
            return False
        
        # 回滚到上上次的参数
        last_result = self.optimization_history[-2]
        self.current_params = last_result.best_params
        
        # 移除最后一次优化记录
        self.optimization_history.pop()
        
        logger.info(f"已回滚到参数: {self.current_params}")
        return True


# 示例评价函数
def example_evaluate_func(trades: List[Dict], params: Dict) -> Dict:
    """
    示例策略评价函数
    
    Args:
        trades: 交易历史
        params: 策略参数
    
    Returns:
        评价指标 {'win_rate':.., 'avg_pnl':..}
    """
    if not trades:
        return {'win_rate': 0, 'avg_pnl': 0}
    
    # 计算胜率
    win_trades = [t for t in trades if t.get('pnl', 0) > 0]
    win_rate = len(win_trades) / len(trades)
    
    # 计算平均盈亏
    pnls = [t.get('pnl_pct', 0) for t in trades]
    avg_pnl = np.mean(pnls) if pnls else 0
    
    # 这里可以根据params调整评价
    # 例如：如果params中有rsi_low，可以筛选符合条件的交易
    
    return {
        'win_rate': win_rate,
        'avg_pnl': avg_pnl,
        'total_trades': len(trades),
        'trade_count': len(trades),
        'win_count': len(win_trades),
        'pnl_std': float(np.std(pnls)) if pnls else 0.0
    }
