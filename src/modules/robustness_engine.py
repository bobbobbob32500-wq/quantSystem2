# -*- coding: utf-8 -*-
"""
鲁棒性引擎（Robustness Engine）
确保Pattern在未来还能活：Walk-Forward验证、市场状态分层、统计显著性、资金曲线验证
"""

import pandas as pd
import numpy as np
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
import warnings
warnings.filterwarnings('ignore')

from src.core.logger import get_logger

logger = get_logger("robustness_engine")

# 尝试导入统计库
try:
    from scipy import stats
    SCIPY_AVAILABLE = True
except ImportError:
    SCIPY_AVAILABLE = False
    logger.warning("scipy未安装，统计检验功能受限")


@dataclass
class RobustnessResult:
    """鲁棒性验证结果"""
    pattern_id: int
    conditions: Dict
    
    # Walk-Forward验证
    wf_windows: int              # 总窗口数
    wf_valid_windows: int        # 有效窗口数
    wf_consistency: float        # 一致性评分
    
    # 市场状态分层
    regime_performance: Dict     # 各市场状态表现
    
    # 统计显著性
    p_value: float               # p值
    confidence_interval: Tuple[float, float]  # 置信区间
    is_significant: bool         # 是否显著
    
    # 资金曲线
    max_drawdown: float          # 最大回撤
    sharpe_ratio: float          # 夏普比率
    equity_curve: np.ndarray     # 资金曲线
    
    # 综合鲁棒性评分
    robustness_score: float
    
    # 是否通过鲁棒性验证
    is_robust: bool


class RobustnessEngine:
    """鲁棒性引擎"""
    
    def __init__(self,
                 wf_window_size: int = 200,
                 wf_step: int = 50,
                 min_consistency: float = 0.6,
                 max_drawdown_threshold: float = 0.15,
                 significance_level: float = 0.05):
        """
        初始化鲁棒性引擎
        
        Args:
            wf_window_size: Walk-Forward窗口大小
            wf_step: Walk-Forward步长
            min_consistency: 最小一致性要求
            max_drawdown_threshold: 最大回撤阈值
            significance_level: 显著性水平
        """
        self.wf_window_size = wf_window_size
        self.wf_step = wf_step
        self.min_consistency = min_consistency
        self.max_drawdown_threshold = max_drawdown_threshold
        self.significance_level = significance_level
        
        logger.info("=" * 80)
        logger.info("鲁棒性引擎初始化完成")
        logger.info(f"  Walk-Forward窗口: {wf_window_size}")
        logger.info(f"  Walk-Forward步长: {wf_step}")
        logger.info(f"  最小一致性: {min_consistency}")
        logger.info(f"  最大回撤阈值: {max_drawdown_threshold}")
        logger.info(f"  显著性水平: {significance_level}")
        logger.info("=" * 80)
    
    def walk_forward_validate(self,
                             trades: pd.DataFrame,
                             pattern_func,
                             min_samples: int = 20) -> Dict:
        """
        Walk-Forward验证（滚动验证）
        
        Args:
            trades: 交易数据
            pattern_func: Pattern策略函数
            min_samples: 最小样本数
        
        Returns:
            Walk-Forward验证结果
        """
        if len(trades) < self.wf_window_size + self.wf_step:
            logger.warning("数据量不足，无法进行Walk-Forward验证")
            return {'windows': 0, 'valid_windows': 0, 'consistency': 0}
        
        results = []
        windows = 0
        valid_windows = 0
        
        # 滚动验证
        for i in range(0, len(trades) - self.wf_window_size - self.wf_step, self.wf_step):
            # 训练窗口
            train = trades.iloc[i:i+self.wf_window_size]
            
            # 测试窗口
            test = trades.iloc[i+self.wf_window_size:i+self.wf_window_size+self.wf_step]
            
            # 在测试窗口验证
            test_matched = test[test.apply(pattern_func, axis=1)]
            
            if 'pnl' in test_matched.columns and len(test_matched) >= min_samples:
                pnl = test_matched['pnl']
                win_rate = (pnl > 0).mean()
                expected_return = pnl.mean()
                
                windows += 1
                
                # 判断该窗口是否有效
                if win_rate > 0.5 and expected_return > 0:
                    valid_windows += 1
                
                results.append({
                    'window_id': windows,
                    'win_rate': win_rate,
                    'expected_return': expected_return,
                    'sample_size': len(pnl),
                    'is_valid': win_rate > 0.5 and expected_return > 0
                })
        
        # 计算一致性
        consistency = valid_windows / windows if windows > 0 else 0
        
        logger.info(f"Walk-Forward验证完成:")
        logger.info(f"  总窗口数: {windows}")
        logger.info(f"  有效窗口数: {valid_windows}")
        logger.info(f"  一致性: {consistency:.2%}")
        
        return {
            'windows': windows,
            'valid_windows': valid_windows,
            'consistency': consistency,
            'details': results
        }
    
    def detect_market_regime(self, 
                            df: pd.DataFrame,
                            volatility_col: str = 'volatility',
                            trend_col: str = 'trend_strength') -> pd.DataFrame:
        """
        检测市场状态
        
        Args:
            df: 数据DataFrame
            volatility_col: 波动率列名
            trend_col: 趋势强度列名
        
        Returns:
            带市场状态标签的DataFrame
        """
        df = df.copy()
        
        # 如果没有波动率列，使用pnl的滚动标准差
        if volatility_col not in df.columns:
            if 'pnl' in df.columns:
                df['volatility'] = df['pnl'].rolling(20).std().fillna(0)
            else:
                df['volatility'] = 0
        
        # 如果没有趋势列，使用pnl的滚动均值
        if trend_col not in df.columns:
            if 'pnl' in df.columns:
                df['trend_strength'] = abs(df['pnl'].rolling(20).mean().fillna(0))
            else:
                df['trend_strength'] = 0
        
        # 计算阈值
        vol_threshold = df['volatility'].quantile(0.7)
        trend_threshold = df['trend_strength'].quantile(0.5)
        
        # 市场状态分类
        def classify_regime(row):
            if row['volatility'] > vol_threshold:
                return 'volatile'
            elif row['trend_strength'] > trend_threshold:
                return 'trend'
            else:
                return 'range'
        
        df['market_regime'] = df.apply(classify_regime, axis=1)
        
        logger.info(f"市场状态分层完成:")
        logger.info(f"  趋势市场: {(df['market_regime'] == 'trend').sum()} 条")
        logger.info(f"  震荡市场: {(df['market_regime'] == 'range').sum()} 条")
        logger.info(f"  高波动市场: {(df['market_regime'] == 'volatile').sum()} 条")
        
        return df
    
    def validate_by_regime(self,
                          trades: pd.DataFrame,
                          pattern_func,
                          min_samples: int = 15) -> Dict:
        """
        按市场状态分层验证
        
        Args:
            trades: 交易数据（需包含market_regime列）
            pattern_func: Pattern策略函数
            min_samples: 最小样本数
        
        Returns:
            各市场状态表现
        """
        if 'market_regime' not in trades.columns:
            logger.warning("缺少market_regime列，先进行市场状态检测")
            trades = self.detect_market_regime(trades)
        
        regime_performance = {}
        
        for regime in ['trend', 'range', 'volatile']:
            regime_data = trades[trades['market_regime'] == regime]
            
            if len(regime_data) < min_samples:
                regime_performance[regime] = {
                    'sample_size': len(regime_data),
                    'is_valid': False,
                    'reason': '样本不足'
                }
                continue
            
            # 应用Pattern
            matched = regime_data[regime_data.apply(pattern_func, axis=1)]
            
            if 'pnl' not in matched.columns or len(matched) < min_samples:
                regime_performance[regime] = {
                    'sample_size': len(matched),
                    'is_valid': False,
                    'reason': '匹配样本不足'
                }
                continue
            
            pnl = matched['pnl']
            win_rate = (pnl > 0).mean()
            expected_return = pnl.mean()
            
            regime_performance[regime] = {
                'sample_size': len(pnl),
                'win_rate': win_rate,
                'expected_return': expected_return,
                'is_valid': win_rate > 0.5 and expected_return > 0
            }
        
        logger.info(f"市场状态分层验证完成:")
        for regime, perf in regime_performance.items():
            if perf.get('is_valid'):
                logger.info(f"  {regime}: 胜率{perf['win_rate']*100:.1f}%, 收益{perf['expected_return']:.3f}% ✅")
            else:
                logger.info(f"  {regime}: {perf.get('reason', '未通过')} ❌")
        
        return regime_performance
    
    def statistical_significance_test(self,
                                     pnl: pd.Series,
                                     n_bootstrap: int = 1000) -> Dict:
        """
        统计显著性检验
        
        Args:
            pnl: 收益序列
            n_bootstrap: Bootstrap次数
        
        Returns:
            显著性检验结果
        """
        if len(pnl) < 10:
            return {
                'p_value': 1.0,
                'confidence_interval': (0, 0),
                'is_significant': False
            }
        
        # 方法1: 二项检验（胜率是否显著>50%）
        wins = (pnl > 0).sum()
        n = len(pnl)
        
        if SCIPY_AVAILABLE:
            p_value = stats.binom_test(wins, n, 0.5, alternative='greater')
        else:
            # 简化计算
            p_value = 1.0
        
        # 方法2: Bootstrap置信区间
        bootstrap_means = []
        for _ in range(n_bootstrap):
            sample = np.random.choice(pnl, size=len(pnl), replace=True)
            bootstrap_means.append(sample.mean())
        
        confidence_interval = (
            np.percentile(bootstrap_means, 5),
            np.percentile(bootstrap_means, 95)
        )
        
        # 判断是否显著
        is_significant = (
            p_value < self.significance_level and
            confidence_interval[0] > 0  # 置信区间下界>0
        )
        
        logger.info(f"统计显著性检验完成:")
        logger.info(f"  p值: {p_value:.4f}")
        logger.info(f"  置信区间: [{confidence_interval[0]:.3f}, {confidence_interval[1]:.3f}]")
        logger.info(f"  是否显著: {'✅' if is_significant else '❌'}")
        
        return {
            'p_value': p_value,
            'confidence_interval': confidence_interval,
            'is_significant': is_significant
        }
    
    def simulate_equity_curve(self,
                             pnl: pd.Series,
                             initial_capital: float = 100000) -> Dict:
        """
        模拟资金曲线
        
        Args:
            pnl: 收益序列
            initial_capital: 初始资金
        
        Returns:
            资金曲线结果
        """
        if len(pnl) == 0:
            return {
                'equity_curve': np.array([initial_capital]),
                'max_drawdown': 0,
                'sharpe_ratio': 0
            }
        
        # 计算资金曲线
        equity = initial_capital
        equity_curve = [equity]
        
        for ret in pnl:
            equity *= (1 + ret / 100)
            equity_curve.append(equity)
        
        equity_curve = np.array(equity_curve)
        
        # 计算最大回撤
        peak = np.maximum.accumulate(equity_curve)
        drawdown = (peak - equity_curve) / peak
        max_drawdown = np.max(drawdown)
        
        # 计算夏普比率
        if len(pnl) > 1:
            sharpe_ratio = pnl.mean() / (pnl.std() + 1e-9) * np.sqrt(252)
        else:
            sharpe_ratio = 0
        
        logger.info(f"资金曲线模拟完成:")
        logger.info(f"  最大回撤: {max_drawdown:.2%}")
        logger.info(f"  夏普比率: {sharpe_ratio:.2f}")
        
        return {
            'equity_curve': equity_curve,
            'max_drawdown': max_drawdown,
            'sharpe_ratio': sharpe_ratio
        }
    
    def validate_robustness(self,
                           pattern: Dict,
                           trades: pd.DataFrame,
                           pattern_func,
                           min_samples: int = 20) -> RobustnessResult:
        """
        完整鲁棒性验证
        
        Args:
            pattern: Pattern字典
            trades: 交易数据
            pattern_func: Pattern策略函数
            min_samples: 最小样本数
        
        Returns:
            鲁棒性验证结果
        """
        logger.info(f"\n开始Pattern #{pattern.get('pattern_id', 0)} 鲁棒性验证...")
        
        # 1. Walk-Forward验证
        wf_result = self.walk_forward_validate(trades, pattern_func, min_samples)
        
        # 2. 市场状态分层验证
        trades_with_regime = self.detect_market_regime(trades)
        regime_performance = self.validate_by_regime(trades_with_regime, pattern_func, min_samples)
        
        # 3. 统计显著性检验
        matched = trades[trades.apply(pattern_func, axis=1)]
        pnl = matched['pnl'] if 'pnl' in matched.columns else pd.Series()
        
        sig_result = self.statistical_significance_test(pnl)
        
        # 4. 资金曲线验证
        equity_result = self.simulate_equity_curve(pnl)
        
        # 5. 计算综合鲁棒性评分
        robustness_score = self._calculate_robustness_score(
            wf_result,
            regime_performance,
            sig_result,
            equity_result
        )
        
        # 6. 判断是否通过鲁棒性验证
        is_robust = self._check_robustness(
            wf_result,
            regime_performance,
            sig_result,
            equity_result
        )
        
        return RobustnessResult(
            pattern_id=pattern.get('pattern_id', 0),
            conditions=pattern.get('conditions', {}),
            wf_windows=wf_result['windows'],
            wf_valid_windows=wf_result['valid_windows'],
            wf_consistency=wf_result['consistency'],
            regime_performance=regime_performance,
            p_value=sig_result['p_value'],
            confidence_interval=sig_result['confidence_interval'],
            is_significant=sig_result['is_significant'],
            max_drawdown=equity_result['max_drawdown'],
            sharpe_ratio=equity_result['sharpe_ratio'],
            equity_curve=equity_result['equity_curve'],
            robustness_score=robustness_score,
            is_robust=is_robust
        )
    
    def _calculate_robustness_score(self,
                                   wf_result: Dict,
                                   regime_performance: Dict,
                                   sig_result: Dict,
                                   equity_result: Dict) -> float:
        """计算综合鲁棒性评分"""
        # Walk-Forward一致性权重
        wf_score = wf_result['consistency']
        
        # 市场状态通过率权重
        regime_valid_count = sum(
            1 for perf in regime_performance.values()
            if perf.get('is_valid', False)
        )
        regime_score = regime_valid_count / 3
        
        # 统计显著性权重
        sig_score = 1.0 if sig_result['is_significant'] else 0.0
        
        # 资金曲线权重（回撤越小越好）
        dd_score = max(0, 1 - equity_result['max_drawdown'] / self.max_drawdown_threshold)
        
        # 综合评分
        robustness_score = (
            wf_score * 0.3 +
            regime_score * 0.3 +
            sig_score * 0.2 +
            dd_score * 0.2
        )
        
        return robustness_score
    
    def _check_robustness(self,
                         wf_result: Dict,
                         regime_performance: Dict,
                         sig_result: Dict,
                         equity_result: Dict) -> bool:
        """检查是否通过鲁棒性验证"""
        # 条件1: Walk-Forward一致性
        if wf_result['consistency'] < self.min_consistency:
            return False
        
        # 条件2: 至少在一种市场状态有效
        regime_valid = any(
            perf.get('is_valid', False)
            for perf in regime_performance.values()
        )
        if not regime_valid:
            return False
        
        # 条件3: 统计显著
        if not sig_result['is_significant']:
            return False
        
        # 条件4: 最大回撤可接受
        if equity_result['max_drawdown'] > self.max_drawdown_threshold:
            return False
        
        return True
    
    def generate_robustness_report(self,
                                  results: List[RobustnessResult],
                                  top_n: int = 10) -> str:
        """生成鲁棒性报告"""
        lines = [
            "=" * 120,
            "鲁棒性验证报告",
            f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "=" * 120,
            "",
        ]
        
        # 统计
        robust_count = sum(1 for r in results if r.is_robust)
        lines.extend([
            "【鲁棒性统计】",
            "-" * 120,
            f"总Pattern数: {len(results)}",
            f"通过鲁棒性验证: {robust_count}",
            f"通过率: {robust_count/len(results)*100:.1f}%" if results else "通过率: 0%",
            "",
        ])
        
        # 排序
        sorted_results = sorted(results, key=lambda x: x.robustness_score, reverse=True)
        
        # Top Pattern
        lines.extend([
            "【Top Pattern】（按鲁棒性评分排序）",
            "-" * 120,
            f"{'ID':<5} {'WF一致性':>10} {'市场状态':>10} {'p值':>10} {'置信区间':>20} {'最大回撤':>10} {'夏普':>8} {'鲁棒评分':>10} {'通过':>6}",
            "-" * 120,
        ])
        
        for r in sorted_results[:top_n]:
            regime_valid = sum(1 for p in r.regime_performance.values() if p.get('is_valid', False))
            ci_str = f"[{r.confidence_interval[0]:.3f}, {r.confidence_interval[1]:.3f}]"
            
            lines.append(
                f"{r.pattern_id:<5} {r.wf_consistency:>9.2%} "
                f"{regime_valid}/3{'':>6} {r.p_value:>10.4f} "
                f"{ci_str:>20} {r.max_drawdown:>9.2%} "
                f"{r.sharpe_ratio:>8.2f} {r.robustness_score:>10.3f} "
                f"{'✅' if r.is_robust else '❌':>6}"
            )
        
        lines.extend(["-" * 120, ""])
        
        # 建议
        lines.extend([
            "【行动建议】",
            "-" * 120,
        ])
        
        if robust_count > 0:
            best = sorted_results[0]
            lines.extend([
                f"✅ 推荐使用Pattern #{best.pattern_id}",
                f"   Walk-Forward一致性: {best.wf_consistency:.2%}",
                f"   统计显著: {'是' if best.is_significant else '否'}",
                f"   最大回撤: {best.max_drawdown:.2%}",
                f"   鲁棒性评分: {best.robustness_score:.3f}",
                "",
                "该Pattern已通过所有鲁棒性验证，可进入实盘测试。",
            ])
        else:
            lines.extend([
                "❌ 没有Pattern通过鲁棒性验证",
                "",
                "建议:",
                "1. 增加历史数据量",
                "2. 放宽验证条件",
                "3. 调整Pattern Mining参数",
            ])
        
        lines.append("=" * 120)
        
        return "\n".join(lines)
