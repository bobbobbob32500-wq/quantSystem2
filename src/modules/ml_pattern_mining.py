# -*- coding: utf-8 -*-
"""
决策树/LightGBM Pattern Mining系统
使用机器学习自动发现赚钱条件，生成交易规则
"""

import pandas as pd
import numpy as np
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
import warnings
warnings.filterwarnings('ignore')

from src.core.logger import get_logger

logger = get_logger("ml_pattern_mining")

# 尝试导入机器学习库
try:
    from sklearn.tree import DecisionTreeClassifier, export_text
    from sklearn.ensemble import RandomForestClassifier
    SKLEARN_AVAILABLE = True
except ImportError:
    SKLEARN_AVAILABLE = False
    logger.warning("sklearn未安装，决策树功能不可用")

try:
    import lightgbm as lgb
    LIGHTGBM_AVAILABLE = True
except ImportError:
    LIGHTGBM_AVAILABLE = False
    logger.warning("lightgbm未安装，LightGBM功能不可用")


@dataclass
class TradingRule:
    """交易规则数据结构"""
    rule_id: int
    conditions: List[Dict]      # 条件列表
    conditions_str: str         # 条件字符串
    sample_size: int
    win_rate: float
    expected_return: float
    importance: float           # 特征重要性
    is_profitable: bool


class MLPatternMiningEngine:
    """机器学习Pattern Mining引擎"""
    
    def __init__(self):
        """初始化ML Pattern Mining引擎"""
        self.feature_names = []
        logger.info("ML Pattern Mining引擎初始化完成")
    
    def prepare_features(self, trades: List[Dict]) -> pd.DataFrame:
        """
        准备特征矩阵
        
        Args:
            trades: 交易记录列表
        
        Returns:
            特征矩阵DataFrame
        """
        if not trades:
            return pd.DataFrame()
        
        df = pd.DataFrame(trades)
        
        # 确保必要列存在
        if 'pnl' not in df.columns:
            logger.warning("缺少pnl列")
            return pd.DataFrame()
        
        # 提取时间特征
        if 'entry_date' in df.columns:
            df['entry_date'] = pd.to_datetime(df['entry_date'])
            df['hour'] = df['entry_date'].dt.hour
            df['minute'] = df['entry_date'].dt.minute
        
        # 添加默认特征
        if 'rsi' not in df.columns:
            df['rsi'] = 55
        if 'pullback' not in df.columns:
            df['pullback'] = 8
        if 'volume_ratio' not in df.columns:
            df['volume_ratio'] = 1.5
        
        # 信号类型编码
        if 'signal_type' in df.columns:
            signal_map = {'pullback': 0, 'breakout': 1, 'consolidation': 2}
            df['signal_code'] = df['signal_type'].map(signal_map).fillna(0)
        
        return df
    
    def create_target(self, df: pd.DataFrame, 
                     profit_threshold: float = 0) -> pd.Series:
        """
        创建目标变量
        
        Args:
            df: 特征矩阵
            profit_threshold: 盈利阈值
        
        Returns:
            目标变量Series
        """
        # 1表示盈利，0表示亏损
        return (df['pnl'] > profit_threshold).astype(int)
    
    def decision_tree_mining(self, df: pd.DataFrame,
                            max_depth: int = 4,
                            min_samples_leaf: int = 30) -> List[TradingRule]:
        """
        决策树Pattern Mining
        
        Args:
            df: 特征矩阵
            max_depth: 最大深度
            min_samples_leaf: 叶节点最小样本数
        
        Returns:
            交易规则列表
        """
        if not SKLEARN_AVAILABLE:
            logger.warning("sklearn未安装，跳过决策树挖掘")
            return []
        
        # 准备特征
        feature_cols = ['rsi', 'pullback', 'volume_ratio', 'hour', 'signal_code']
        feature_cols = [col for col in feature_cols if col in df.columns]
        
        if not feature_cols:
            logger.warning("没有可用特征")
            return []
        
        X = df[feature_cols].fillna(0)
        y = self.create_target(df)
        
        # 训练决策树
        clf = DecisionTreeClassifier(
            max_depth=max_depth,
            min_samples_leaf=min_samples_leaf,
            random_state=42
        )
        clf.fit(X, y)
        
        # 提取规则
        rules = self._extract_rules_from_tree(clf, X, y, df, feature_cols)
        
        logger.info(f"决策树挖掘发现 {len(rules)} 条规则")
        
        return rules
    
    def _extract_rules_from_tree(self, clf, X, y, df, feature_cols) -> List[TradingRule]:
        """
        从决策树提取规则
        
        Args:
            clf: 训练好的决策树
            X: 特征矩阵
            y: 目标变量
            df: 原始DataFrame
            feature_cols: 特征列名
        
        Returns:
            交易规则列表
        """
        rules = []
        tree = clf.tree_
        
        # 遍历所有叶节点
        leaf_indices = np.where(tree.children_left == -1)[0]
        
        for rule_id, leaf_idx in enumerate(leaf_indices):
            # 获取该叶节点的样本
            node_indicator = clf.decision_path(X)
            leaf_samples = node_indicator[:, leaf_idx].toarray().ravel().astype(bool)
            
            if leaf_samples.sum() < 10:  # 样本太少
                continue
            
            # 计算该规则的统计信息
            leaf_df = df[leaf_samples]
            pnl = leaf_df['pnl']
            
            wins = pnl[pnl > 0]
            losses = pnl[pnl < 0]
            
            win_rate = len(wins) / len(pnl) if len(pnl) > 0 else 0
            avg_profit = wins.mean() if len(wins) > 0 else 0
            avg_loss = abs(losses.mean()) if len(losses) > 0 else 0
            expected_return = win_rate * avg_profit - (1 - win_rate) * avg_loss
            
            # 提取条件（简化：使用特征统计）
            conditions = []
            for i, col in enumerate(feature_cols):
                col_values = leaf_df[col]
                conditions.append({
                    'feature': col,
                    'min': col_values.min(),
                    'max': col_values.max(),
                    'mean': col_values.mean(),
                })
            
            # 构建条件字符串
            cond_strs = []
            for cond in conditions:
                cond_strs.append(f"{cond['feature']}:[{cond['min']:.2f}, {cond['max']:.2f}]")
            conditions_str = " AND ".join(cond_strs)
            
            # 特征重要性（使用该叶节点的样本占比）
            importance = leaf_samples.sum() / len(df)
            
            rule = TradingRule(
                rule_id=rule_id,
                conditions=conditions,
                conditions_str=conditions_str,
                sample_size=int(leaf_samples.sum()),
                win_rate=win_rate,
                expected_return=expected_return,
                importance=importance,
                is_profitable=expected_return > 0
            )
            
            rules.append(rule)
        
        return rules
    
    def lightgbm_mining(self, df: pd.DataFrame,
                       num_leaves: int = 31,
                       min_data_in_leaf: int = 20) -> Tuple[pd.DataFrame, List[TradingRule]]:
        """
        LightGBM Pattern Mining
        
        Args:
            df: 特征矩阵
            num_leaves: 叶节点数
            min_data_in_leaf: 叶节点最小数据数
        
        Returns:
            (特征重要性DataFrame, 交易规则列表)
        """
        if not LIGHTGBM_AVAILABLE:
            logger.warning("lightgbm未安装，跳过LightGBM挖掘")
            return pd.DataFrame(), []
        
        # 准备特征
        feature_cols = ['rsi', 'pullback', 'volume_ratio', 'hour', 'signal_code']
        feature_cols = [col for col in feature_cols if col in df.columns]
        
        if not feature_cols:
            logger.warning("没有可用特征")
            return pd.DataFrame(), []
        
        X = df[feature_cols].fillna(0)
        y = self.create_target(df)
        
        # 创建数据集
        train_data = lgb.Dataset(X, label=y)
        
        # 训练参数
        params = {
            'objective': 'binary',
            'metric': 'auc',
            'num_leaves': num_leaves,
            'min_data_in_leaf': min_data_in_leaf,
            'learning_rate': 0.05,
            'feature_fraction': 0.8,
            'bagging_fraction': 0.8,
            'bagging_freq': 5,
            'verbose': -1,
        }
        
        # 训练模型
        model = lgb.train(params, train_data, num_boost_round=100)
        
        # 特征重要性
        importance_df = pd.DataFrame({
            'feature': feature_cols,
            'importance': model.feature_importance(importance_type='gain'),
        }).sort_values('importance', ascending=False)
        
        # 提取规则（简化：基于特征重要性）
        rules = self._extract_rules_from_lgb(model, X, y, df, feature_cols)
        
        logger.info(f"LightGBM挖掘发现 {len(rules)} 条规则")
        
        return importance_df, rules
    
    def _extract_rules_from_lgb(self, model, X, y, df, feature_cols) -> List[TradingRule]:
        """
        从LightGBM提取规则（简化版）
        
        Args:
            model: 训练好的LightGBM模型
            X: 特征矩阵
            y: 目标变量
            df: 原始DataFrame
            feature_cols: 特征列名
        
        Returns:
            交易规则列表
        """
        rules = []
        
        # 获取预测概率
        probs = model.predict(X)
        
        # 按概率分组
        prob_bins = [0, 0.3, 0.5, 0.7, 1.0]
        prob_labels = ['低概率', '中低概率', '中高概率', '高概率']
        
        df_with_prob = df.copy()
        df_with_prob['prob'] = probs
        df_with_prob['prob_bin'] = pd.cut(df_with_prob['prob'], bins=prob_bins, labels=prob_labels)
        
        # 对每个概率区间生成规则
        for rule_id, prob_label in enumerate(prob_labels):
            group_df = df_with_prob[df_with_prob['prob_bin'] == prob_label]
            
            if len(group_df) < 10:
                continue
            
            pnl = group_df['pnl']
            
            wins = pnl[pnl > 0]
            losses = pnl[pnl < 0]
            
            win_rate = len(wins) / len(pnl) if len(pnl) > 0 else 0
            avg_profit = wins.mean() if len(wins) > 0 else 0
            avg_loss = abs(losses.mean()) if len(losses) > 0 else 0
            expected_return = win_rate * avg_profit - (1 - win_rate) * avg_loss
            
            # 提取条件
            conditions = []
            for col in feature_cols:
                col_values = group_df[col]
                conditions.append({
                    'feature': col,
                    'min': col_values.min(),
                    'max': col_values.max(),
                    'mean': col_values.mean(),
                })
            
            cond_strs = [f"{cond['feature']}:[{cond['min']:.2f}, {cond['max']:.2f}]" for cond in conditions]
            conditions_str = f"预测概率={prob_label} AND " + " AND ".join(cond_strs)
            
            importance = len(group_df) / len(df)
            
            rule = TradingRule(
                rule_id=rule_id,
                conditions=conditions,
                conditions_str=conditions_str,
                sample_size=int(len(group_df)),
                win_rate=win_rate,
                expected_return=expected_return,
                importance=importance,
                is_profitable=expected_return > 0
            )
            
            rules.append(rule)
        
        return rules
    
    def run(self, trades: List[Dict],
           use_decision_tree: bool = True,
           use_lightgbm: bool = True) -> Dict:
        """
        运行ML Pattern Mining
        
        Args:
            trades: 交易记录列表
            use_decision_tree: 是否使用决策树
            use_lightgbm: 是否使用LightGBM
        
        Returns:
            结果字典
        """
        logger.info("=" * 80)
        logger.info("开始ML Pattern Mining...")
        logger.info("=" * 80)
        
        # 准备特征
        df = self.prepare_features(trades)
        if df.empty:
            logger.warning("特征矩阵为空")
            return {}
        
        results = {}
        
        # 决策树挖掘
        if use_decision_tree:
            logger.info("运行决策树挖掘...")
            dt_rules = self.decision_tree_mining(df)
            results['decision_tree'] = {
                'rules': dt_rules,
                'profit_rules': [r for r in dt_rules if r.is_profitable],
                'loss_rules': [r for r in dt_rules if not r.is_profitable],
            }
        
        # LightGBM挖掘
        if use_lightgbm:
            logger.info("运行LightGBM挖掘...")
            importance_df, lgb_rules = self.lightgbm_mining(df)
            results['lightgbm'] = {
                'importance': importance_df,
                'rules': lgb_rules,
                'profit_rules': [r for r in lgb_rules if r.is_profitable],
                'loss_rules': [r for r in lgb_rules if not r.is_profitable],
            }
        
        return results
    
    def generate_report(self, results: Dict) -> str:
        """
        生成ML Pattern Mining报告
        
        Args:
            results: 结果字典
        
        Returns:
            报告文本
        """
        lines = [
            "=" * 100,
            "ML Pattern Mining报告",
            f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "=" * 100,
            "",
        ]
        
        # 决策树结果
        if 'decision_tree' in results:
            dt_results = results['decision_tree']
            profit_rules = dt_results['profit_rules']
            loss_rules = dt_results['loss_rules']
            
            lines.extend([
                "【决策树挖掘结果】",
                "-" * 100,
            ])
            
            if profit_rules:
                lines.append("\n赚钱规则:")
                for rule in sorted(profit_rules, key=lambda x: x.expected_return, reverse=True)[:10]:
                    lines.extend([
                        f"  规则{rule.rule_id}: {rule.conditions_str}",
                        f"    胜率: {rule.win_rate*100:.1f}%, 期望收益: {rule.expected_return:.3f}%, 样本: {rule.sample_size}",
                        "",
                    ])
            
            if loss_rules:
                lines.append("\n禁止交易规则:")
                for rule in sorted(loss_rules, key=lambda x: x.expected_return)[:5]:
                    lines.extend([
                        f"  ❌ 规则{rule.rule_id}: {rule.conditions_str}",
                        f"     胜率: {rule.win_rate*100:.1f}%, 期望收益: {rule.expected_return:.3f}%, 样本: {rule.sample_size}",
                        "",
                    ])
        
        # LightGBM结果
        if 'lightgbm' in results:
            lgb_results = results['lightgbm']
            importance_df = lgb_results['importance']
            profit_rules = lgb_results['profit_rules']
            
            lines.extend([
                "",
                "【LightGBM挖掘结果】",
                "-" * 100,
            ])
            
            if not importance_df.empty:
                lines.append("\n特征重要性:")
                for _, row in importance_df.iterrows():
                    lines.append(f"  {row['feature']}: {row['importance']:.2f}")
            
            if profit_rules:
                lines.append("\n赚钱规则:")
                for rule in sorted(profit_rules, key=lambda x: x.expected_return, reverse=True)[:10]:
                    lines.extend([
                        f"  规则{rule.rule_id}: {rule.conditions_str}",
                        f"    胜率: {rule.win_rate*100:.1f}%, 期望收益: {rule.expected_return:.3f}%, 样本: {rule.sample_size}",
                        "",
                    ])
        
        lines.append("=" * 100)
        
        return "\n".join(lines)


def run_ml_pattern_mining(trades: List[Dict]) -> str:
    """
    运行ML Pattern Mining（便捷函数）
    
    Args:
        trades: 交易记录列表
    
    Returns:
        报告文本
    """
    engine = MLPatternMiningEngine()
    results = engine.run(trades)
    return engine.generate_report(results)
