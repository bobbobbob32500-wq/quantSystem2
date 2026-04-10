# -*- coding: utf-8 -*-
"""
Pattern Mining统一接口
整合组合枚举、决策树、LightGBM三种方法
"""

import pandas as pd
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass

from src.core.logger import get_logger
from src.modules.pattern_mining import PatternMiningEngine
from src.modules.ml_pattern_mining import MLPatternMiningEngine

logger = get_logger("unified_pattern_mining")


@dataclass
class UnifiedPatternResult:
    """统一Pattern结果"""
    method: str              # 方法名称
    patterns: List           # Pattern列表
    profit_count: int        # 赚钱Pattern数量
    loss_count: int          # 亏钱Pattern数量
    best_pattern: Dict       # 最佳Pattern


class UnifiedPatternMining:
    """统一Pattern Mining接口"""
    
    def __init__(self):
        """初始化统一接口"""
        self.combination_engine = PatternMiningEngine()
        self.ml_engine = MLPatternMiningEngine()
        
        logger.info("统一Pattern Mining接口初始化完成")
    
    def run_all_methods(self, trades: List[Dict],
                       max_depth: int = 3,
                       top_n: int = 20) -> Dict:
        """
        运行所有Pattern Mining方法
        
        Args:
            trades: 交易记录列表
            max_depth: 最大组合深度
            top_n: 返回Top N个Pattern
        
        Returns:
            结果字典
        """
        logger.info("=" * 80)
        logger.info("开始统一Pattern Mining...")
        logger.info("=" * 80)
        
        results = {}
        
        # 方法1: 组合枚举
        logger.info("\n[方法1] 组合枚举Pattern Mining...")
        try:
            profit_patterns, loss_patterns = self.combination_engine.run(
                trades, max_depth=max_depth, top_n=top_n
            )
            
            results['combination'] = {
                'method': '组合枚举',
                'profit_patterns': profit_patterns,
                'loss_patterns': loss_patterns,
                'profit_count': len(profit_patterns),
                'loss_count': len(loss_patterns),
                'best_pattern': profit_patterns.iloc[0].to_dict() if not profit_patterns.empty else None,
            }
        except Exception as e:
            logger.error(f"组合枚举失败: {e}")
            results['combination'] = None
        
        # 方法2: 决策树
        logger.info("\n[方法2] 决策树Pattern Mining...")
        try:
            ml_results = self.ml_engine.run(trades, use_decision_tree=True, use_lightgbm=False)
            
            if 'decision_tree' in ml_results:
                dt_results = ml_results['decision_tree']
                results['decision_tree'] = {
                    'method': '决策树',
                    'rules': dt_results['rules'],
                    'profit_rules': dt_results['profit_rules'],
                    'loss_rules': dt_results['loss_rules'],
                    'profit_count': len(dt_results['profit_rules']),
                    'loss_count': len(dt_results['loss_rules']),
                    'best_pattern': dt_results['profit_rules'][0].__dict__ if dt_results['profit_rules'] else None,
                }
            else:
                results['decision_tree'] = None
        except Exception as e:
            logger.error(f"决策树失败: {e}")
            results['decision_tree'] = None
        
        # 方法3: LightGBM
        logger.info("\n[方法3] LightGBM Pattern Mining...")
        try:
            ml_results = self.ml_engine.run(trades, use_decision_tree=False, use_lightgbm=True)
            
            if 'lightgbm' in ml_results:
                lgb_results = ml_results['lightgbm']
                results['lightgbm'] = {
                    'method': 'LightGBM',
                    'importance': lgb_results['importance'],
                    'rules': lgb_results['rules'],
                    'profit_rules': lgb_results['profit_rules'],
                    'loss_rules': lgb_results['loss_rules'],
                    'profit_count': len(lgb_results['profit_rules']),
                    'loss_count': len(lgb_results['loss_rules']),
                    'best_pattern': lgb_results['profit_rules'][0].__dict__ if lgb_results['profit_rules'] else None,
                }
            else:
                results['lightgbm'] = None
        except Exception as e:
            logger.error(f"LightGBM失败: {e}")
            results['lightgbm'] = None
        
        return results
    
    def generate_unified_report(self, results: Dict) -> str:
        """
        生成统一报告
        
        Args:
            results: 结果字典
        
        Returns:
            报告文本
        """
        lines = [
            "=" * 120,
            "统一Pattern Mining报告",
            f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "=" * 120,
            "",
        ]
        
        # 方法对比
        lines.extend([
            "【方法对比】",
            "-" * 120,
            f"{'方法':<15} {'赚钱Pattern数':>15} {'亏钱Pattern数':>15} {'最佳期望收益':>15}",
            "-" * 120,
        ])
        
        for method_name in ['combination', 'decision_tree', 'lightgbm']:
            if results.get(method_name):
                r = results[method_name]
                best_return = r['best_pattern']['expected_return'] if r['best_pattern'] else 0
                lines.append(
                    f"{r['method']:<15} {r['profit_count']:>15} {r['loss_count']:>15} {best_return:>14.3f}%"
                )
        
        lines.extend(["-" * 120, ""])
        
        # 组合枚举结果
        if results.get('combination'):
            comb = results['combination']
            lines.extend([
                "",
                "【组合枚举结果】",
                "-" * 120,
            ])
            
            if not comb['profit_patterns'].empty:
                lines.append("\n赚钱Pattern (Top 10):")
                for i, row in comb['profit_patterns'].head(10).iterrows():
                    conditions = row['conditions']
                    cond_str = " + ".join([f"{k}={v}" for k, v in conditions.items()])
                    lines.extend([
                        f"  {i+1}. {cond_str}",
                        f"     胜率: {row['win_rate']*100:.1f}%, 期望收益: {row['expected_return']:.3f}%, 样本: {int(row['sample_size'])}, 评分: {row['score']:.3f}",
                    ])
            
            if not comb['loss_patterns'].empty:
                lines.append("\n禁止交易Pattern:")
                for i, row in comb['loss_patterns'].head(5).iterrows():
                    conditions = row['conditions']
                    cond_str = " + ".join([f"{k}={v}" for k, v in conditions.items()])
                    lines.extend([
                        f"  ❌ {cond_str}",
                        f"     胜率: {row['win_rate']*100:.1f}%, 期望收益: {row['expected_return']:.3f}%, 样本: {int(row['sample_size'])}",
                    ])
        
        # 决策树结果
        if results.get('decision_tree'):
            dt = results['decision_tree']
            lines.extend([
                "",
                "【决策树结果】",
                "-" * 120,
            ])
            
            if dt['profit_rules']:
                lines.append("\n赚钱规则 (Top 10):")
                for rule in sorted(dt['profit_rules'], key=lambda x: x.expected_return, reverse=True)[:10]:
                    lines.extend([
                        f"  规则{rule.rule_id}: {rule.conditions_str}",
                        f"     胜率: {rule.win_rate*100:.1f}%, 期望收益: {rule.expected_return:.3f}%, 样本: {rule.sample_size}",
                    ])
            
            if dt['loss_rules']:
                lines.append("\n禁止交易规则:")
                for rule in sorted(dt['loss_rules'], key=lambda x: x.expected_return)[:5]:
                    lines.extend([
                        f"  ❌ 规则{rule.rule_id}: {rule.conditions_str}",
                        f"     胜率: {rule.win_rate*100:.1f}%, 期望收益: {rule.expected_return:.3f}%, 样本: {rule.sample_size}",
                    ])
        
        # LightGBM结果
        if results.get('lightgbm'):
            lgb = results['lightgbm']
            lines.extend([
                "",
                "【LightGBM结果】",
                "-" * 120,
            ])
            
            if not lgb['importance'].empty:
                lines.append("\n特征重要性:")
                for _, row in lgb['importance'].iterrows():
                    lines.append(f"  {row['feature']}: {row['importance']:.2f}")
            
            if lgb['profit_rules']:
                lines.append("\n赚钱规则 (Top 10):")
                for rule in sorted(lgb['profit_rules'], key=lambda x: x.expected_return, reverse=True)[:10]:
                    lines.extend([
                        f"  规则{rule.rule_id}: {rule.conditions_str}",
                        f"     胜率: {rule.win_rate*100:.1f}%, 期望收益: {rule.expected_return:.3f}%, 样本: {rule.sample_size}",
                    ])
        
        # 综合建议
        lines.extend([
            "",
            "【综合建议】",
            "-" * 120,
        ])
        
        # 找出最佳方法
        best_method = None
        best_return = -999
        
        for method_name in ['combination', 'decision_tree', 'lightgbm']:
            if results.get(method_name) and results[method_name]['best_pattern']:
                ret = results[method_name]['best_pattern']['expected_return']
                if ret > best_return:
                    best_return = ret
                    best_method = method_name
        
        if best_method:
            lines.extend([
                f"推荐方法: {results[best_method]['method']}",
                f"最佳期望收益: {best_return:.3f}%",
                "",
                "建议:",
                "1. 使用组合枚举方法发现明确的条件组合",
                "2. 使用决策树方法发现分层规则",
                "3. 使用LightGBM方法发现特征重要性",
                "4. 综合三种方法的结果，制定交易策略",
            ])
        else:
            lines.append("未发现有效的赚钱Pattern，建议:")
            lines.append("1. 检查数据质量")
            lines.append("2. 增加样本数量")
            lines.append("3. 调整参数设置")
        
        lines.append("=" * 120)
        
        return "\n".join(lines)
    
    def export_best_patterns(self, results: Dict, top_n: int = 10) -> List[Dict]:
        """
        导出最佳Pattern
        
        Args:
            results: 结果字典
            top_n: 导出Top N个Pattern
        
        Returns:
            最佳Pattern列表
        """
        all_patterns = []
        
        # 收集所有赚钱Pattern
        for method_name in ['combination', 'decision_tree', 'lightgbm']:
            if not results.get(method_name):
                continue
            
            r = results[method_name]
            
            if method_name == 'combination':
                if not r['profit_patterns'].empty:
                    for _, row in r['profit_patterns'].head(top_n).iterrows():
                        all_patterns.append({
                            'method': r['method'],
                            'conditions': row['conditions'],
                            'win_rate': row['win_rate'],
                            'expected_return': row['expected_return'],
                            'sample_size': int(row['sample_size']),
                            'score': row['score'],
                        })
            
            elif method_name in ['decision_tree', 'lightgbm']:
                for rule in sorted(r['profit_rules'], key=lambda x: x.expected_return, reverse=True)[:top_n]:
                    all_patterns.append({
                        'method': r['method'],
                        'conditions': rule.conditions_str,
                        'win_rate': rule.win_rate,
                        'expected_return': rule.expected_return,
                        'sample_size': rule.sample_size,
                        'score': rule.importance,
                    })
        
        # 按期望收益排序
        all_patterns = sorted(all_patterns, key=lambda x: x['expected_return'], reverse=True)
        
        return all_patterns[:top_n]


def run_unified_pattern_mining(trades: List[Dict], top_n: int = 20) -> str:
    """
    运行统一Pattern Mining（便捷函数）
    
    Args:
        trades: 交易记录列表
        top_n: 返回Top N个Pattern
    
    Returns:
        报告文本
    """
    engine = UnifiedPatternMining()
    results = engine.run_all_methods(trades, top_n=top_n)
    return engine.generate_unified_report(results)
