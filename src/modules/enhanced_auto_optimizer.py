# -*- coding: utf-8 -*-
"""
增强的自动优化器
支持虚拟交易 + 回测数据的混合数据源
支持因子数据记录和市场环境数据
"""

import numpy as np
import pandas as pd
from typing import Any, Dict, List, Optional, Callable, Tuple
from datetime import datetime
import itertools
import logging
from dataclasses import dataclass

logger = logging.getLogger("EnhancedAutoOptimizer")


@dataclass
class TradeData:
    """交易数据（增强版）"""
    # 基本信息
    symbol: str
    name: str
    buy_time: datetime
    buy_price: float
    sell_time: Optional[datetime] = None
    sell_price: Optional[float] = None
    
    # 盈亏信息
    pnl: Optional[float] = None
    pnl_pct: Optional[float] = None
    peak_pnl_pct: Optional[float] = None
    lowest_pnl_pct: Optional[float] = None
    sell_reason: str = ''
    
    # 信号信息
    signal_type: str = ''
    signal_score: float = 0.0
    
    # 因子数据（新增）
    factors: Dict = None
    
    # 市场环境（新增）
    market_env: Dict = None
    
    # 数据来源（新增）
    data_source: str = 'virtual'  # 'virtual' 或 'backtest'
    
    def __post_init__(self):
        if self.factors is None:
            self.factors = {}
        if self.market_env is None:
            self.market_env = {}


class EnhancedAutoOptimizer:
    """
    增强的自动优化器
    支持混合数据源、因子优化、环境优化
    """
    
    def __init__(self,
                 param_optimizer,
                 effect_validator,
                 evaluate_func: Callable,
                 optimize_interval: int = 50,
                 min_trades_for_optimization: int = 20,
                 use_backtest_data: bool = True,
                 backtest_weight: float = 0.3,
                 min_robustness_score: float = 0.55,
                 min_deploy_score_delta: float = 0.001,
                 min_deploy_trade_count: int = 30):
        """
        初始化增强自动优化器
        
        Args:
            param_optimizer: 参数优化器
            effect_validator: 效果验证器
            evaluate_func: 策略评价函数
            optimize_interval: 优化间隔
            min_trades_for_optimization: 最小交易数
            use_backtest_data: 是否使用回测数据
            backtest_weight: 回测数据权重（0-1）
        """
        self.optimizer = param_optimizer
        self.validator = effect_validator
        self.evaluate_func = evaluate_func
        
        self.optimize_interval = optimize_interval
        self.min_trades_for_optimization = min_trades_for_optimization
        self.min_robustness_score = float(min_robustness_score)
        self.min_deploy_score_delta = float(min_deploy_score_delta)
        self.min_deploy_trade_count = int(min_deploy_trade_count)
        
        # 数据源
        self.use_backtest_data = use_backtest_data
        self.backtest_weight = backtest_weight
        
        # 虚拟交易数据
        self.virtual_trades = []
        
        # 回测数据（新增）
        self.backtest_trades = []
        
        # 当前参数
        self.current_params = {}
        
        # 因子权重
        self.factor_weights = {}
        
        # 优化历史
        self.optimization_history = []
        self.deployed_profile: Dict = {
            'params': {},
            'factor_weights': {},
            'timestamp': None,
            'score_delta': 0.0,
            'robustness_score': 0.0,
            'trade_count': 0,
            'source': 'init',
        }
        
        # 因子表现统计
        self.factor_performance = {}
        
        logger.info(f"增强自动优化器初始化完成")
        logger.info(f"  - 虚拟交易数据: 启用")
        logger.info(f"  - 回测数据: {'启用' if use_backtest_data else '禁用'}")
        logger.info(f"  - 回测权重: {backtest_weight:.1%}")
        logger.info(
            "  - 部署闸门: min_score_delta=%.4f, min_trade_count=%d, min_robustness=%.3f",
            self.min_deploy_score_delta,
            self.min_deploy_trade_count,
            self.min_robustness_score,
        )

    @staticmethod
    def _normalize_datetime(value: Any) -> datetime:
        if isinstance(value, datetime):
            return value
        text = str(value or "").strip()
        if not text:
            return datetime.now()
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y%m%d%H%M%S", "%Y-%m-%d", "%Y%m%d"):
            try:
                return datetime.strptime(text, fmt)
            except Exception:
                continue
        try:
            return datetime.fromisoformat(text)
        except Exception:
            return datetime.now()

    @staticmethod
    def _safe_float(value: Any, default: Optional[float] = 0.0) -> Optional[float]:
        if value is None:
            return default
        try:
            return float(value)
        except Exception:
            return default

    @staticmethod
    def _composite_score(metrics: Dict) -> float:
        win_rate = float(metrics.get('win_rate', 0) or 0)
        avg_pnl = float(metrics.get('avg_pnl', 0) or 0)
        sharpe = float(metrics.get('sharpe', metrics.get('sharpe_ratio', 0)) or 0)
        max_drawdown = abs(float(metrics.get('max_drawdown', metrics.get('drawdown', 0)) or 0))
        pnl_std = float(metrics.get('pnl_std', metrics.get('return_std', 0)) or 0)
        return float(
            win_rate * 0.55 +
            avg_pnl * 15.0 +
            sharpe * 0.15 -
            max_drawdown * 0.10 -
            pnl_std * 2.0
        )

    def _evaluate_deploy_gate(
        self,
        improved: bool,
        robustness_score: float,
        score_delta: float,
        trade_count: int,
    ) -> Tuple[bool, str]:
        if not improved:
            return False, 'validator_not_passed'
        if robustness_score < self.min_robustness_score:
            return False, f'robustness<{self.min_robustness_score:.3f}'
        if trade_count < self.min_deploy_trade_count:
            return False, f'trade_count<{self.min_deploy_trade_count}'
        if score_delta < self.min_deploy_score_delta:
            return False, f'score_delta<{self.min_deploy_score_delta:.4f}'
        return True, 'passed'
    
    def add_backtest_data(self, backtest_trades: List[Dict]):
        """
        添加回测数据
        
        Args:
            backtest_trades: 回测交易列表
        """
        for trade in backtest_trades:
            trade_data = TradeData(
                symbol=trade.get('symbol', ''),
                name=trade.get('name', ''),
                buy_time=self._normalize_datetime(trade.get('buy_time', datetime.now())),
                buy_price=self._safe_float(trade.get('buy_price', 0), 0.0) or 0.0,
                sell_time=trade.get('sell_time'),
                sell_price=trade.get('sell_price'),
                pnl=trade.get('pnl'),
                pnl_pct=trade.get('pnl_pct'),
                peak_pnl_pct=self._safe_float(trade.get('peak_pnl_pct'), None),
                lowest_pnl_pct=self._safe_float(trade.get('lowest_pnl_pct'), None),
                sell_reason=str(trade.get('sell_reason', '') or ''),
                signal_type=trade.get('signal_type', ''),
                signal_score=trade.get('signal_score', 0),
                factors=trade.get('factors', {}),
                market_env=trade.get('market_env', {}),
                data_source='backtest'
            )
            self.backtest_trades.append(trade_data)
        
        logger.info(f"添加回测数据: {len(backtest_trades)}笔")
        logger.info(f"当前回测数据总量: {len(self.backtest_trades)}笔")
    
    def on_virtual_trade_closed(self, trade: Dict):
        """
        虚拟交易平仓回调（增强版）
        
        Args:
            trade: 交易记录（包含因子和市场环境）
        """
        # 创建交易数据
        trade_data = TradeData(
            symbol=trade.get('symbol', ''),
            name=trade.get('name', ''),
            buy_time=self._normalize_datetime(trade.get('buy_time', datetime.now())),
            buy_price=self._safe_float(trade.get('buy_price', 0), 0.0) or 0.0,
            sell_time=self._normalize_datetime(trade.get('sell_time', datetime.now())),
            sell_price=self._safe_float(trade.get('sell_price', 0), 0.0) or 0.0,
            pnl=trade.get('pnl'),
            pnl_pct=trade.get('pnl_pct'),
            peak_pnl_pct=self._safe_float(trade.get('peak_pnl_pct'), None),
            lowest_pnl_pct=self._safe_float(trade.get('lowest_pnl_pct'), None),
            sell_reason=str(trade.get('sell_reason', '') or ''),
            signal_type=trade.get('signal_type', trade.get('buy_signal', '')),
            signal_score=trade.get('signal_score', trade.get('buy_score', 0)),
            factors=trade.get('factors', {}),  # 因子数据
            market_env=trade.get('market_env', {}),  # 市场环境
            data_source='virtual'
        )
        
        # 记录虚拟交易
        self.virtual_trades.append(trade_data)
        
        # 更新因子表现
        self._update_factor_performance(trade_data)
        
        # 检查是否触发优化
        total_trades = len(self._get_all_trades())
        if total_trades >= self.min_trades_for_optimization:
            if len(self.virtual_trades) % self.optimize_interval == 0:
                self._run_optimization()
    
    def _get_all_trades(self) -> List[TradeData]:
        """
        获取所有交易数据（混合数据源）
        
        Returns:
            虚拟交易 + 回测数据
        """
        if self.use_backtest_data:
            return self.virtual_trades + self.backtest_trades
        else:
            return self.virtual_trades
    
    def _get_weighted_trades(self) -> List[Dict]:
        """
        获取加权交易数据
        
        Returns:
            加权后的交易数据
        """
        all_trades = []
        
        # 虚拟交易（权重 = 1 - backtest_weight）
        virtual_weight = 1.0 if not self.use_backtest_data else max(0.0, 1 - self.backtest_weight)
        for trade in self.virtual_trades:
            raw_pnl = self._safe_float(trade.pnl, None)
            raw_pnl_pct = self._safe_float(trade.pnl_pct, None)
            weighted_trade = {
                'symbol': trade.symbol,
                'name': trade.name,
                'buy_time': trade.buy_time,
                'sell_time': trade.sell_time,
                'buy_price': trade.buy_price,
                'sell_price': trade.sell_price,
                'pnl': raw_pnl * virtual_weight if raw_pnl is not None else None,
                'pnl_pct': raw_pnl_pct * virtual_weight if raw_pnl_pct is not None else None,
                'raw_pnl': raw_pnl,
                'raw_pnl_pct': raw_pnl_pct,
                'weighted_pnl_pct': raw_pnl_pct * virtual_weight if raw_pnl_pct is not None else None,
                'peak_pnl_pct': self._safe_float(trade.peak_pnl_pct, None),
                'lowest_pnl_pct': self._safe_float(trade.lowest_pnl_pct, None),
                'sell_reason': trade.sell_reason,
                'signal_type': trade.signal_type,
                'signal_score': self._safe_float(trade.signal_score, 0.0) or 0.0,
                'factors': trade.factors,
                'market_env': trade.market_env,
                'data_source': 'virtual',
                'weight': virtual_weight
            }
            all_trades.append(weighted_trade)
        
        # 回测数据（权重 = backtest_weight）
        if self.use_backtest_data:
            for trade in self.backtest_trades:
                raw_pnl = self._safe_float(trade.pnl, None)
                raw_pnl_pct = self._safe_float(trade.pnl_pct, None)
                weighted_trade = {
                    'symbol': trade.symbol,
                    'name': trade.name,
                    'buy_time': trade.buy_time,
                    'sell_time': trade.sell_time,
                    'buy_price': trade.buy_price,
                    'sell_price': trade.sell_price,
                    'pnl': raw_pnl * self.backtest_weight if raw_pnl is not None else None,
                    'pnl_pct': raw_pnl_pct * self.backtest_weight if raw_pnl_pct is not None else None,
                    'raw_pnl': raw_pnl,
                    'raw_pnl_pct': raw_pnl_pct,
                    'weighted_pnl_pct': raw_pnl_pct * self.backtest_weight if raw_pnl_pct is not None else None,
                    'peak_pnl_pct': self._safe_float(trade.peak_pnl_pct, None),
                    'lowest_pnl_pct': self._safe_float(trade.lowest_pnl_pct, None),
                    'sell_reason': trade.sell_reason,
                    'signal_type': trade.signal_type,
                    'signal_score': self._safe_float(trade.signal_score, 0.0) or 0.0,
                    'factors': trade.factors,
                    'market_env': trade.market_env,
                    'data_source': 'backtest',
                    'weight': self.backtest_weight
                }
                all_trades.append(weighted_trade)
        
        return all_trades
    
    def _update_factor_performance(self, trade: TradeData):
        """
        更新因子表现统计
        
        Args:
            trade: 交易数据
        """
        if not trade.factors:
            return
        
        pnl_pct = trade.pnl_pct or 0
        is_win = pnl_pct > 0
        
        for factor_name, factor_value in trade.factors.items():
            if factor_name not in self.factor_performance:
                self.factor_performance[factor_name] = {
                    'total_trades': 0,
                    'win_trades': 0,
                    'total_pnl': 0,
                    'avg_factor_value': 0,
                    'factor_values': []
                }
            
            perf = self.factor_performance[factor_name]
            perf['total_trades'] += 1
            perf['total_pnl'] += pnl_pct
            perf['factor_values'].append(factor_value)
            
            if is_win:
                perf['win_trades'] += 1
            
            # 更新平均因子值
            perf['avg_factor_value'] = np.mean(perf['factor_values'])
    
    def optimize_factor_weights(self) -> Dict[str, float]:
        """
        优化因子权重（基于因子表现）
        
        Returns:
            新的因子权重
        """
        if not self.factor_performance:
            logger.warning("没有因子表现数据，无法优化权重")
            return {}
        
        new_weights = {}
        total_score = 0
        
        for factor_name, perf in self.factor_performance.items():
            if perf['total_trades'] == 0:
                continue
            
            # 计算因子得分
            win_rate = perf['win_trades'] / perf['total_trades']
            avg_pnl = perf['total_pnl'] / perf['total_trades']
            
            # 综合得分
            score = win_rate + avg_pnl
            total_score += score
            new_weights[factor_name] = score
        
        # 归一化
        if total_score > 0:
            for factor in new_weights:
                new_weights[factor] /= total_score
        
        self.factor_weights = new_weights
        
        logger.info(f"因子权重优化完成:")
        for factor, weight in sorted(new_weights.items(), key=lambda x: x[1], reverse=True):
            logger.info(f"  {factor}: {weight:.3f}")
        
        return new_weights
    
    def optimize_by_market_env(self) -> Dict[str, Dict]:
        """
        按市场环境优化
        
        Returns:
            不同环境下的最优参数
        """
        all_trades = self._get_all_trades()
        
        # 按环境分组
        env_groups = {}
        for trade in all_trades:
            if not trade.market_env:
                continue
            
            # 简化环境标识
            env_key = f"{trade.market_env.get('trend', 'unknown')}"
            
            if env_key not in env_groups:
                env_groups[env_key] = []
            env_groups[env_key].append(trade)
        
        # 对每个环境优化
        env_params = {}
        for env_key, trades in env_groups.items():
            if len(trades) < 10:  # 数据太少不优化
                continue
            
            logger.info(f"优化环境: {env_key}, 数据量: {len(trades)}")
            
            # 转换为字典格式
            trade_dicts = [
                {
                    'symbol': t.symbol,
                    'pnl': t.pnl,
                    'pnl_pct': t.pnl_pct,
                }
                for t in trades
            ]
            
            # 参数优化
            best_params, best_score = self.optimizer.grid_search(
                trade_dicts, 
                self.evaluate_func
            )
            sensitivity_report = self.optimizer.sensitivity_analysis(
                trade_dicts,
                self.evaluate_func,
                best_params
            )
            
            env_params[env_key] = {
                'params': best_params,
                'score': best_score,
                'sample_size': len(trades),
                'robustness_score': sensitivity_report.get('robustness_score', 0.0)
            }
        
        return env_params
    
    def _run_optimization(self):
        """执行优化流程（增强版）"""
        logger.info("="*80)
        logger.info(f"开始增强自动优化（第{len(self.optimization_history)+1}次）")
        logger.info("="*80)
        
        # 数据统计
        total_trades = len(self._get_all_trades())
        virtual_count = len(self.virtual_trades)
        backtest_count = len(self.backtest_trades)
        
        logger.info(f"数据统计:")
        logger.info(f"  - 虚拟交易: {virtual_count}笔")
        logger.info(f"  - 回测数据: {backtest_count}笔")
        logger.info(f"  - 总计: {total_trades}笔")
        
        try:
            # 1. 获取加权交易数据
            weighted_trades = self._get_weighted_trades()
            if not weighted_trades:
                logger.warning("无可用加权交易样本，跳过优化")
                return None
            
            # 2. 当前策略表现
            before_metrics = self.evaluate_func(weighted_trades, self.current_params)
            logger.info(f"当前策略表现: {before_metrics}")
            before_score = self._composite_score(before_metrics)
            
            # 3. 参数优化
            new_params, best_score = self.optimizer.grid_search(
                weighted_trades, 
                self.evaluate_func
            )
            logger.info(f"优化后参数: {new_params}, 得分: {best_score:.3f}")
            
            # 4. 新策略表现
            after_metrics = self.evaluate_func(weighted_trades, new_params)
            logger.info(f"新策略表现: {after_metrics}")
            after_score = self._composite_score(after_metrics)
            score_delta = float(after_score - before_score)
            logger.info(
                "综合评分: before=%.4f after=%.4f delta=%+.4f",
                before_score,
                after_score,
                score_delta,
            )

            sensitivity_report = self.optimizer.sensitivity_analysis(
                weighted_trades,
                self.evaluate_func,
                new_params
            )
            robustness_score = sensitivity_report.get('robustness_score', 0.0)
            logger.info(f"参数鲁棒性评分: {robustness_score:.3f}")
            
            # 5. 验证效果
            improved = self.validator.validate(before_metrics, after_metrics)
            deployable, deploy_reason = self._evaluate_deploy_gate(
                improved=improved,
                robustness_score=robustness_score,
                score_delta=score_delta,
                trade_count=total_trades,
            )
            if not deployable:
                logger.info(f"[SKIP] 上线闸门未通过: {deploy_reason}")
            
            # 6. 因子权重优化
            old_factor_weights = dict(self.factor_weights)
            new_factor_weights = self.optimize_factor_weights()
            
            # 7. 决定是否应用
            if deployable:
                self.current_params = new_params
                self.deployed_profile = {
                    'params': dict(new_params),
                    'factor_weights': dict(new_factor_weights),
                    'timestamp': datetime.now(),
                    'score_delta': float(score_delta),
                    'robustness_score': float(robustness_score),
                    'trade_count': int(total_trades),
                    'source': 'enhanced_auto_optimizer',
                }
                logger.info(f"[SUCCESS] 优化成功，应用新参数")
            else:
                self.factor_weights = old_factor_weights
                logger.info(f"[SKIP] 优化无效，保持现有参数")
            
            # 记录优化历史
            result = {
                'timestamp': datetime.now(),
                'best_params': new_params,
                'best_score': best_score,
                'before_metrics': before_metrics,
                'after_metrics': after_metrics,
                'before_score': float(before_score),
                'after_score': float(after_score),
                'score_delta': float(score_delta),
                'improved': improved,
                'robustness_score': robustness_score,
                'deployable': bool(deployable),
                'deploy_reason': str(deploy_reason),
                'sensitivity_report': sensitivity_report,
                'factor_weights': new_factor_weights,
                'data_stats': {
                    'virtual': virtual_count,
                    'backtest': backtest_count,
                    'total': total_trades
                }
            }
            self.optimization_history.append(result)
            
            logger.info("="*80)
            logger.info("增强自动优化完成")
            logger.info("="*80)
            
            return result
            
        except Exception as e:
            logger.error(f"优化流程失败: {e}")
            return None
    
    def get_optimization_summary(self) -> Dict:
        """获取优化总结（增强版）"""
        if not self.optimization_history:
            return {
                'total_optimizations': 0,
                'successful_optimizations': 0,
                'success_rate': 0,
                'deployed_profile': self.get_deployed_profile(),
            }
        
        successful = sum(1 for r in self.optimization_history if r.get('improved'))
        
        summary = {
            'total_optimizations': len(self.optimization_history),
            'successful_optimizations': successful,
            'success_rate': successful / len(self.optimization_history),
            'current_params': self.current_params,
            'factor_weights': self.factor_weights,
            'deployed_profile': self.get_deployed_profile(),
            'avg_robustness': float(np.mean([
                r.get('robustness_score', 0.0) for r in self.optimization_history
            ])),
            'data_stats': {
                'virtual_trades': len(self.virtual_trades),
                'backtest_trades': len(self.backtest_trades),
                'total_trades': len(self._get_all_trades())
            },
            'factor_performance': self.factor_performance
        }
        
        if self.optimization_history:
            last = self.optimization_history[-1]
            summary['last_optimization'] = last.get('timestamp')
            summary['last_robustness'] = last.get('robustness_score', 0.0)
            summary['last_score_delta'] = last.get('score_delta', 0.0)
            summary['last_deployable'] = bool(last.get('deployable', False))
            summary['last_deploy_reason'] = str(last.get('deploy_reason', ''))
        
        return summary

    def get_deployed_profile(self) -> Dict:
        profile = dict(self.deployed_profile or {})
        ts = profile.get('timestamp')
        if isinstance(ts, datetime):
            profile['timestamp'] = ts.isoformat()
        return profile

    def run_optimization_once(self) -> Optional[Dict]:
        """手动触发一次优化（满足最小样本才执行）。"""
        total_trades = len(self._get_all_trades())
        if total_trades < self.min_trades_for_optimization:
            logger.info(
                "跳过 run_optimization_once: trades=%d < min_trades_for_optimization=%d",
                total_trades,
                self.min_trades_for_optimization,
            )
            return None
        return self._run_optimization()
    
    def get_factor_report(self) -> str:
        """生成因子分析报告"""
        if not self.factor_performance:
            return "暂无因子数据"
        
        report = []
        report.append("="*80)
        report.append("因子表现分析报告")
        report.append("="*80)
        
        for factor_name, perf in sorted(
            self.factor_performance.items(),
            key=lambda x: x[1]['total_pnl'],
            reverse=True
        ):
            if perf['total_trades'] == 0:
                continue
            
            win_rate = perf['win_trades'] / perf['total_trades']
            avg_pnl = perf['total_pnl'] / perf['total_trades']
            
            report.append(f"\n{factor_name}:")
            report.append(f"  交易次数: {perf['total_trades']}")
            report.append(f"  胜率: {win_rate:.1%}")
            report.append(f"  平均盈亏: {avg_pnl:+.2%}")
            report.append(f"  平均因子值: {perf['avg_factor_value']:.3f}")
        
        report.append("\n" + "="*80)
        return "\n".join(report)
