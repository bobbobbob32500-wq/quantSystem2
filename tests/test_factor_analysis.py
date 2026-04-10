# -*- coding: utf-8 -*-
"""
因子分析测试脚本
测试因子IC分析和验证功能
"""

import sys
import os

# 添加项目根目录到路径
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.core.config import ConfigManager
from src.core.database import DatabaseManager
from src.modules.factor_analysis import (
    FactorAnalyzer,
    FactorICValidator,
    FactorCorrelationAnalyzer,
    FactorWeightOptimizer,
    generate_factor_analysis_report
)
from src.modules.stock_selector import StockSelector
from src.core.logger import get_logger

logger = get_logger("test_factor_analysis")


def test_factor_analysis():
    """测试因子分析功能"""
    logger.info("=" * 80)
    logger.info("开始测试因子分析功能")
    logger.info("=" * 80)
    
    # 1. 初始化
    config = ConfigManager()
    db = DatabaseManager(config)
    
    # 2. 创建因子分析器
    analyzer = FactorAnalyzer(config, db)
    validator = FactorICValidator(analyzer)
    
    # 3. 定义因子列表
    factor_names = [
        'trend_score',
        'momentum_score',
        'volume_score',
        'pullback_score'
    ]
    
    # 4. 生成分析报告
    logger.info("生成因子分析报告...")
    report = generate_factor_analysis_report(
        analyzer, validator, factor_names,
        output_path='data/reports/factor_analysis_report.txt'
    )
    
    print(report)
    
    # 5. 保存报告
    report_dir = 'data/reports'
    os.makedirs(report_dir, exist_ok=True)
    report_path = os.path.join(report_dir, 'factor_analysis_report.txt')
    
    with open(report_path, 'w', encoding='utf-8') as f:
        f.write(report)
    
    logger.info(f"报告已保存到: {report_path}")
    
    # 6. 分析结果
    validation_results = validator.validate_all_factors(factor_names)
    
    if not validation_results.empty:
        logger.info("\n" + "=" * 80)
        logger.info("因子有效性验证结果")
        logger.info("=" * 80)
        
        effective_factors = validation_results[validation_results['is_effective']]
        ineffective_factors = validation_results[~validation_results['is_effective']]
        
        logger.info(f"\n有效因子 ({len(effective_factors)}个):")
        if not effective_factors.empty:
            for _, row in effective_factors.iterrows():
                logger.info(f"  - {row['factor_name']}: IC均值={row['ic_mean']:.3f}, IC_IR={row['ic_ir']:.3f}")
        
        logger.info(f"\n无效因子 ({len(ineffective_factors)}个):")
        if not ineffective_factors.empty:
            for _, row in ineffective_factors.iterrows():
                logger.info(f"  - {row['factor_name']}: {row['recommendation']}")
        
        # 7. 相关性分析
        logger.info("\n" + "=" * 80)
        logger.info("因子相关性分析")
        logger.info("=" * 80)
        
        correlation_analyzer = FactorCorrelationAnalyzer(db)
        correlation_matrix = correlation_analyzer.calculate_factor_correlation_matrix(factor_names)
        
        if not correlation_matrix.empty:
            print("\n因子相关性矩阵:")
            print(correlation_matrix)
            
            redundant_pairs = correlation_analyzer.identify_redundant_factors(correlation_matrix, threshold=0.7)
            if redundant_pairs:
                logger.warning(f"\n发现 {len(redundant_pairs)} 对冗余因子:")
                for f1, f2, corr in redundant_pairs:
                    logger.warning(f"  {f1} <-> {f2}: {corr:.3f}")
        
        # 8. 权重优化建议
        logger.info("\n" + "=" * 80)
        logger.info("权重优化建议")
        logger.info("=" * 80)
        
        optimizer = FactorWeightOptimizer()
        
        # 收集有效因子的IC统计
        effective_ic_stats = {}
        for _, row in effective_factors.iterrows():
            effective_ic_stats[row['factor_name']] = {
                'ic_mean': row['ic_mean'],
                'ic_ir': row['ic_ir']
            }
        
        if effective_ic_stats:
            logger.info("\n基于IC均值的权重:")
            weights_by_ic = optimizer.calculate_weights_by_ic(effective_ic_stats)
            for name, weight in sorted(weights_by_ic.items(), key=lambda x: -x[1]):
                logger.info(f"  {name}: {weight:.2%}")
            
            logger.info("\n基于IC_IR的权重:")
            weights_by_ic_ir = optimizer.calculate_weights_by_ic_ir(effective_ic_stats)
            for name, weight in sorted(weights_by_ic_ir.items(), key=lambda x: -x[1]):
                logger.info(f"  {name}: {weight:.2%}")
        else:
            logger.warning("无有效因子，无法优化权重")
    
    logger.info("\n" + "=" * 80)
    logger.info("测试完成")
    logger.info("=" * 80)


if __name__ == "__main__":
    test_factor_analysis()
