# -*- coding: utf-8 -*-
"""
Qlib 优化多因子选股策略 (StockSelector)

优化路径：
1. 用 Qlib Alpha158 因子补充现有 6 大类因子
2. 用 Qlib IC 分析筛选有效因子
3. 用 Qlib LightGBM 替代线性加权评分
4. 用 Qlib 因子正交化去除冗余

使用方式：
  conda activate qlib_env
  python scripts/qlib_optimize_stock_selector.py
"""

import sys
import os
import json
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.core.logger import get_logger
from src.core.database import DatabaseManager
from src.core.config import ConfigManager

logger = get_logger("qlib_optimize_stock_selector")


class QlibStockSelectorOptimizer:
    """Qlib 多因子选股策略优化器"""
    
    def __init__(self):
        self.config = ConfigManager()
        self.db = DatabaseManager(self.config)
        
        # Qlib 初始化
        try:
            import qlib
            qlib.init(provider_uri='C:/Users/32519/.qlib/qlib_data/cn_data')
            self.qlib = qlib
            self.qlib_available = True
            logger.info("Qlib initialized successfully")
        except Exception as e:
            self.qlib_available = False
            logger.error(f"Qlib init failed: {e}")
            raise
    
    # ================================================================
    # Step 1: 计算现有因子的 IC 表现
    # ================================================================
    def analyze_existing_factors(self) -> pd.DataFrame:
        """分析现有 6 大类因子的 IC 表现"""
        print("\n" + "=" * 60)
        print("Step 1: Analyze existing factor IC performance")
        print("=" * 60)
        
        from src.modules.factor_analysis import FactorAnalyzer
        analyzer = FactorAnalyzer(self.config, self.db)
        
        existing_factors = {
            'trend': 'Trend factor (MA alignment, price position, MACD)',
            'momentum': 'Momentum factor (20d return, RSI, consecutive up days)',
            'volume': 'Volume factor (volume expansion, price-volume coordination)',
            'pullback': 'Pullback factor (retracement position, support distance)',
            'quality': 'Quality factor (daily volatility, max drawdown, volume stability)',
            'fundamental': 'Fundamental factor (industry heat, ST flag, listing years)',
        }
        
        results = []
        
        for factor_key, factor_desc in existing_factors.items():
            # Try common factor name patterns in the database
            factor_names_to_try = [
                f'{factor_key}_score',
                f'{factor_key}_factor', 
                f'{factor_key}',
            ]
            
            for factor_name in factor_names_to_try:
                try:
                    ic_df = analyzer.calculate_stock_factor_ic(
                        factor_name=factor_name,
                        period=5,
                        start_date='20230101',
                        end_date='20231231'
                    )
                    
                    if not ic_df.empty:
                        stats = analyzer.calculate_ic_statistics(ic_df)
                        results.append({
                            'factor': factor_key,
                            'factor_name': factor_name,
                            'description': factor_desc,
                            'ic_mean': stats.get('ic_mean', 0),
                            'ic_std': stats.get('ic_std', 0),
                            'ic_ir': stats.get('ic_ir', 0),
                            'ic_positive_ratio': stats.get('ic_positive_ratio', 0),
                            'sample_count': stats.get('sample_count', 0),
                        })
                        print(f"  {factor_key}: IC={stats.get('ic_mean', 0):.4f}, ICIR={stats.get('ic_ir', 0):.4f}")
                        break
                except Exception as e:
                    logger.debug(f"Factor {factor_name} analysis failed: {e}")
        
        if results:
            df = pd.DataFrame(results).sort_values('ic_mean', ascending=False)
            os.makedirs('output', exist_ok=True)
            df.to_csv('output/existing_factor_ic.csv', index=False, encoding='utf-8-sig')
            print(f"\nResults saved to: output/existing_factor_ic.csv")
            return df
        else:
            print("No existing factor data found in database")
            return pd.DataFrame()
    
    # ================================================================
    # Step 2: 计算 Qlib Alpha158 因子并分析 IC
    # ================================================================
    def compute_qlib_alpha158_ic(self, 
                                  instruments: str = 'csi300',
                                  train_start: str = '2010-01-01',
                                  train_end: str = '2017-12-31',
                                  valid_start: str = '2018-01-01',
                                  valid_end: str = '2019-12-31',
                                  test_start: str = '2020-01-01',
                                  test_end: str = '2020-09-25') -> pd.DataFrame:
        """计算 Qlib Alpha158 因子并分析每个因子的 IC"""
        print("\n" + "=" * 60)
        print("Step 2: Compute Qlib Alpha158 factors and analyze IC")
        print("=" * 60)
        
        from qlib.data.dataset import DatasetH
        from qlib.data import D
        
        # Create dataset
        print(f"  Instruments: {instruments}")
        print(f"  Train: {train_start} ~ {train_end}")
        print(f"  Valid: {valid_start} ~ {valid_end}")
        print(f"  Test:  {test_start} ~ {test_end}")
        
        dataset = DatasetH(
            handler={
                'class': 'Alpha158',
                'module_path': 'qlib.contrib.data.handler',
                'kwargs': {
                    'start_time': train_start,
                    'end_time': test_end,
                    'fit_start_time': train_start,
                    'fit_end_time': train_end,
                    'instruments': instruments,
                },
            },
            segments={
                'train': (train_start, train_end),
                'valid': (valid_start, valid_end),
                'test': (test_start, test_end),
            },
        )
        
        # Get feature data
        print("\n  Loading Alpha158 features...")
        train_data = dataset.prepare('train', col_set='feature')
        valid_data = dataset.prepare('valid', col_set='feature')
        label_data = dataset.prepare('train', col_set='label')
        valid_label = dataset.prepare('valid', col_set='label')
        
        print(f"  Train shape: {train_data.shape}")
        print(f"  Valid shape: {valid_data.shape}")
        print(f"  Factor count: {len(train_data.columns)}")
        
        # Calculate IC for each factor
        print("\n  Calculating IC for each Alpha158 factor...")
        
        factor_ic_results = []
        
        # Combine train + valid for IC calculation
        all_features = pd.concat([train_data, valid_data])
        all_labels = pd.concat([label_data, valid_label])
        
        for i, factor_name in enumerate(train_data.columns):
            if (i + 1) % 20 == 0:
                print(f"    Progress: {i+1}/{len(train_data.columns)}")
            
            try:
                # Get factor values and labels
                factor_values = all_features[factor_name]
                labels = all_labels.iloc[:, 0] if len(all_labels.columns) > 0 else all_labels
                
                # Align indices
                common_idx = factor_values.dropna().index.intersection(labels.dropna().index)
                
                if len(common_idx) < 100:
                    continue
                
                fv = factor_values.loc[common_idx]
                lv = labels.loc[common_idx]
                
                # Calculate Spearman IC (cross-sectional)
                from scipy.stats import spearmanr
                
                # Group by date for cross-sectional IC
                ic_values = []
                for date, group_idx in fv.groupby(level='datetime').groups.items():
                    f_group = fv.loc[group_idx]
                    l_group = lv.loc[group_idx] if group_idx in lv.index.get_level_values('datetime') else None
                    
                    if l_group is not None and len(f_group) > 30:
                        try:
                            ic, _ = spearmanr(f_group, l_group)
                            if not np.isnan(ic):
                                ic_values.append(ic)
                        except:
                            pass
                
                if ic_values:
                    ic_mean = np.mean(ic_values)
                    ic_std = np.std(ic_values)
                    ic_ir = ic_mean / ic_std if ic_std > 0 else 0
                    
                    factor_ic_results.append({
                        'factor': factor_name,
                        'ic_mean': ic_mean,
                        'ic_std': ic_std,
                        'ic_ir': ic_ir,
                        'ic_positive_ratio': np.mean([1 if x > 0 else 0 for x in ic_values]),
                        'sample_days': len(ic_values),
                    })
                    
            except Exception as e:
                logger.debug(f"Factor {factor_name} IC calculation failed: {e}")
        
        if factor_ic_results:
            df = pd.DataFrame(factor_ic_results).sort_values('ic_mean', ascending=False)
            os.makedirs('output', exist_ok=True)
            df.to_csv('output/qlib_alpha158_ic.csv', index=False, encoding='utf-8-sig')
            
            # Print top factors
            print(f"\n  Top 20 Alpha158 factors by IC:")
            print(df.head(20).to_string(index=False))
            
            print(f"\n  Results saved to: output/qlib_alpha158_ic.csv")
            return df
        else:
            print("  No IC results computed")
            return pd.DataFrame()
    
    # ================================================================
    # Step 3: 筛选有效因子
    # ================================================================
    def select_effective_factors(self, 
                                  ic_threshold: float = 0.03,
                                  icir_threshold: float = 0.5,
                                  max_factors: int = 30) -> List[str]:
        """筛选有效的 Qlib 因子"""
        print("\n" + "=" * 60)
        print("Step 3: Select effective Qlib factors")
        print("=" * 60)
        
        ic_file = 'output/qlib_alpha158_ic.csv'
        if not os.path.exists(ic_file):
            print(f"  IC file not found: {ic_file}")
            print("  Please run Step 2 first")
            return []
        
        df = pd.read_csv(ic_file)
        
        # Filter by IC and ICIR
        effective = df[
            (df['ic_mean'].abs() > ic_threshold) & 
            (df['ic_ir'].abs() > icir_threshold)
        ].head(max_factors)
        
        print(f"  Selection criteria: |IC| > {ic_threshold}, |ICIR| > {icir_threshold}")
        print(f"  Effective factors: {len(effective)} / {len(df)}")
        print(f"\n  Selected factors:")
        for _, row in effective.iterrows():
            print(f"    {row['factor']:20s}  IC={row['ic_mean']:+.4f}  ICIR={row['ic_ir']:+.4f}")
        
        # Save
        effective.to_csv('output/effective_qlib_factors.csv', index=False, encoding='utf-8-sig')
        print(f"\n  Saved to: output/effective_qlib_factors.csv")
        
        return effective['factor'].tolist()
    
    # ================================================================
    # Step 4: 训练 Qlib LightGBM 模型
    # ================================================================
    def train_qlib_model(self,
                          instruments: str = 'csi300',
                          train_start: str = '2010-01-01',
                          train_end: str = '2017-12-31',
                          valid_start: str = '2018-01-01',
                          valid_end: str = '2019-12-31',
                          test_start: str = '2020-01-01',
                          test_end: str = '2020-09-25') -> Dict:
        """训练 Qlib LightGBM 模型"""
        print("\n" + "=" * 60)
        print("Step 4: Train Qlib LightGBM model")
        print("=" * 60)
        
        from qlib.data.dataset import DatasetH
        from qlib.contrib.model.gbdt import LGBModel
        from qlib.data import D
        
        # Create dataset
        dataset = DatasetH(
            handler={
                'class': 'Alpha158',
                'module_path': 'qlib.contrib.data.handler',
                'kwargs': {
                    'start_time': train_start,
                    'end_time': test_end,
                    'fit_start_time': train_start,
                    'fit_end_time': train_end,
                    'instruments': instruments,
                },
            },
            segments={
                'train': (train_start, train_end),
                'valid': (valid_start, valid_end),
                'test': (test_start, test_end),
            },
        )
        
        # Train LightGBM
        print("\n  Training LightGBM with Alpha158 features...")
        model = LGBModel(
            loss='mse',
            colsample_bytree=0.8879,
            learning_rate=0.0421,
            subsample=0.8789,
            lambda_l1=205.6999,
            lambda_l2=580.5258,
            max_depth=8,
            num_leaves=210,
            num_threads=4,
        )
        
        model.fit(dataset)
        print("  Model training complete!")
        
        # Predict on test set
        pred = model.predict(dataset)
        pred_valid = pred.dropna()
        
        print(f"\n  Prediction shape: {pred.shape}")
        print(f"  Valid predictions: {len(pred_valid)}")
        
        # Calculate prediction IC
        test_label = dataset.prepare('test', col_set='label')
        
        if not test_label.empty and not pred_valid.empty:
            # Align
            common_idx = pred_valid.index.intersection(test_label.index)
            if len(common_idx) > 0:
                from scipy.stats import spearmanr
                pred_aligned = pred_valid.loc[common_idx]
                label_aligned = test_label.loc[common_idx].iloc[:, 0] if len(test_label.columns) > 0 else test_label.loc[common_idx]
                
                # Cross-sectional IC
                ic_values = []
                for date in pred_aligned.index.get_level_values('datetime').unique():
                    p_date = pred_aligned.xs(date, level='datetime')
                    l_date = label_aligned.xs(date, level='datetime') if date in label_aligned.index.get_level_values('datetime') else None
                    
                    if l_date is not None and len(p_date) > 10:
                        try:
                            ic, _ = spearmanr(p_date, l_date)
                            if not np.isnan(ic):
                                ic_values.append(ic)
                        except:
                            pass
                
                if ic_values:
                    result = {
                        'model': 'LightGBM_Alpha158',
                        'instruments': instruments,
                        'train_period': f'{train_start}~{train_end}',
                        'test_period': f'{test_start}~{test_end}',
                        'ic_mean': np.mean(ic_values),
                        'ic_std': np.std(ic_values),
                        'ic_ir': np.mean(ic_values) / np.std(ic_values) if np.std(ic_values) > 0 else 0,
                        'ic_positive_ratio': np.mean([1 if x > 0 else 0 for x in ic_values]),
                        'num_factors': 158,
                        'num_test_days': len(ic_values),
                    }
                    
                    print(f"\n  Model performance on test set:")
                    print(f"    IC mean:  {result['ic_mean']:.4f}")
                    print(f"    IC std:   {result['ic_std']:.4f}")
                    print(f"    ICIR:     {result['ic_ir']:.4f}")
                    print(f"    IC>0 ratio: {result['ic_positive_ratio']:.2%}")
                    
                    # Save
                    os.makedirs('output', exist_ok=True)
                    with open('output/qlib_model_performance.json', 'w') as f:
                        json.dump(result, f, indent=2, ensure_ascii=False)
                    
                    return result
        
        return {}
    
    # ================================================================
    # Step 5: 生成优化后的权重配置
    # ================================================================
    def generate_optimized_weights(self) -> Dict:
        """基于 Qlib IC 分析生成优化后的因子权重"""
        print("\n" + "=" * 60)
        print("Step 5: Generate optimized factor weights")
        print("=" * 60)
        
        # Load effective Qlib factors
        ic_file = 'output/qlib_alpha158_ic.csv'
        if not os.path.exists(ic_file):
            print("  IC file not found, using default weights")
            return self._get_default_weights()
        
        df = pd.read_csv(ic_file)
        
        # Categorize Alpha158 factors into your 6 categories
        factor_categories = {
            'trend': ['MA', 'MACD', 'KUP', 'KLOW', 'KSFT', 'OPEN', 'CLOSE', 'HIGH', 'LOW'],
            'momentum': ['ROC', 'RSI', 'MOM', 'RET', 'CHANGE', 'KLEN', 'KMID'],
            'volume': ['VOL', 'VWAP', 'TURN', 'AMOUNT', 'BETA', 'VSTD'],
            'pullback': ['ATR', 'BOLL', 'SKEW', 'KURT', 'MAX', 'MIN', 'QTLU', 'QTLD'],
            'quality': ['STD', 'CV', 'RANK', 'RSQR', 'RESI', 'CNTP', 'CNTN'],
            'fundamental': ['PE', 'PB', 'PS', 'ROE', 'ROA', 'EPS', 'DCF'],
        }
        
        # Map each Alpha158 factor to a category
        category_ic = {cat: [] for cat in factor_categories}
        unmapped = []
        
        for _, row in df.iterrows():
            factor_name = row['factor']
            ic = abs(row['ic_mean'])
            
            mapped = False
            for cat, keywords in factor_categories.items():
                if any(kw in factor_name.upper() for kw in keywords):
                    category_ic[cat].append(ic)
                    mapped = True
                    break
            
            if not mapped:
                unmapped.append((factor_name, ic))
        
        # Calculate category weights based on IC
        category_weights = {}
        total_ic = 0
        
        for cat, ics in category_ic.items():
            if ics:
                mean_ic = np.mean(ics)
                category_weights[cat] = mean_ic
                total_ic += mean_ic
            else:
                category_weights[cat] = 0
        
        # Normalize
        if total_ic > 0:
            for cat in category_weights:
                category_weights[cat] /= total_ic
        
        # Compare with current weights
        current_weights = {
            'trend': 0.2613,
            'momentum': 0.3324,
            'pullback': 0.2164,
            'quality': 0.1122,
            'fundamental': 0.0651,
            'volume': 0.0125,
        }
        
        print("\n  Weight comparison (current vs Qlib-optimized):")
        print(f"  {'Factor':15s}  {'Current':>8s}  {'Qlib':>8s}  {'Change':>8s}")
        print("  " + "-" * 45)
        
        for cat in ['trend', 'momentum', 'pullback', 'quality', 'fundamental', 'volume']:
            cur = current_weights.get(cat, 0)
            opt = category_weights.get(cat, 0)
            change = opt - cur
            print(f"  {cat:15s}  {cur:8.4f}  {opt:8.4f}  {change:+8.4f}")
        
        # Save
        result = {
            'current_weights': current_weights,
            'qlib_optimized_weights': category_weights,
            'unmapped_factors': unmapped[:10],
        }
        
        os.makedirs('output', exist_ok=True)
        with open('output/optimized_weights.json', 'w') as f:
            json.dump(result, f, indent=2, ensure_ascii=False)
        
        print(f"\n  Saved to: output/optimized_weights.json")
        
        # Generate config snippet
        print("\n  Config snippet for config.yaml:")
        print("  stock_selection:")
        for cat in ['trend', 'momentum', 'pullback', 'quality', 'fundamental', 'volume']:
            print(f"    {cat}_factor_weight: {category_weights.get(cat, 0):.4f}")
        
        return category_weights
    
    def _get_default_weights(self) -> Dict:
        return {
            'trend': 0.2613,
            'momentum': 0.3324,
            'pullback': 0.2164,
            'quality': 0.1122,
            'fundamental': 0.0651,
            'volume': 0.0125,
        }
    
    # ================================================================
    # Run full optimization
    # ================================================================
    def run(self):
        """Run full optimization pipeline"""
        print("\n" + "=" * 60)
        print("Qlib StockSelector Optimization Pipeline")
        print("=" * 60)
        
        if not self.qlib_available:
            print("Qlib not available! Run: conda activate qlib_env")
            return
        
        # Step 1: Analyze existing factors
        self.analyze_existing_factors()
        
        # Step 2: Compute Qlib Alpha158 IC
        self.compute_qlib_alpha158_ic()
        
        # Step 3: Select effective factors
        effective_factors = self.select_effective_factors()
        
        # Step 4: Train Qlib model
        self.train_qlib_model()
        
        # Step 5: Generate optimized weights
        self.generate_optimized_weights()
        
        print("\n" + "=" * 60)
        print("Optimization complete!")
        print("=" * 60)
        print("\nOutput files:")
        print("  output/existing_factor_ic.csv       - Existing factor IC analysis")
        print("  output/qlib_alpha158_ic.csv         - Alpha158 factor IC analysis")
        print("  output/effective_qlib_factors.csv   - Selected effective factors")
        print("  output/qlib_model_performance.json  - Model performance metrics")
        print("  output/optimized_weights.json       - Optimized factor weights")


def main():
    import argparse
    parser = argparse.ArgumentParser(description='Qlib StockSelector Optimization')
    parser.add_argument('--step', type=int, choices=range(1, 6), help='Run specific step (1-5)')
    parser.add_argument('--all', action='store_true', help='Run all steps')
    args = parser.parse_args()
    
    optimizer = QlibStockSelectorOptimizer()
    
    if args.all:
        optimizer.run()
    elif args.step:
        if args.step == 1:
            optimizer.analyze_existing_factors()
        elif args.step == 2:
            optimizer.compute_qlib_alpha158_ic()
        elif args.step == 3:
            optimizer.select_effective_factors()
        elif args.step == 4:
            optimizer.train_qlib_model()
        elif args.step == 5:
            optimizer.generate_optimized_weights()
    else:
        print("\nUsage:")
        print("  Run all:  python scripts/qlib_optimize_stock_selector.py --all")
        print("  Run step: python scripts/qlib_optimize_stock_selector.py --step 1")
        print("\nSteps:")
        print("  1. Analyze existing factor IC")
        print("  2. Compute Qlib Alpha158 factor IC")
        print("  3. Select effective factors")
        print("  4. Train Qlib LightGBM model")
        print("  5. Generate optimized weights")


if __name__ == '__main__':
    main()
