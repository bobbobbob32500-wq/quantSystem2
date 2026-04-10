# -*- coding: utf-8 -*-
"""
多周期IC分析脚本
测试不同预测周期（3天、5天、10天）的IC表现
"""

import sys
import os

# 添加项目根目录到路径
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.core.config import ConfigManager
from src.core.database import DatabaseManager
from src.modules.factor_analysis import FactorAnalyzer
from src.core.logger import get_logger

logger = get_logger("multi_period_ic_analysis")


def analyze_multi_period_ic(factor_names: list, periods: list):
    """
    分析不同周期的IC

    Args:
        factor_names: 因子名称列表
        periods: 预测周期列表（如[3, 5, 10]）
    """
    logger.info("=" * 80)
    logger.info("多周期IC分析")
    logger.info("=" * 80)
    logger.info(f"测试因子: {', '.join(factor_names)}")
    logger.info(f"测试周期: {', '.join(map(str, periods))}天")
    logger.info("=" * 80)

    # 1. 初始化
    config = ConfigManager()
    db = DatabaseManager(config)
    analyzer = FactorAnalyzer(config, db)

    # 2. 分析每个因子在不同周期的IC
    all_results = []

    for factor_name in factor_names:
        print(f"\n{'='*80}")
        print(f"分析因子: {factor_name}")
        print(f"{'='*80}")

        factor_results = {
            'factor_name': factor_name,
            'periods': {}
        }

        for period in periods:
            print(f"\n周期: {period}天")
            print("-" * 80)

            try:
                # 计算IC
                ic_df = analyzer.calculate_stock_factor_ic(factor_name, period=period)

                if ic_df.empty:
                    print(f"  无IC数据")
                    continue

                # 计算统计指标
                ic_stats = analyzer.calculate_ic_statistics(ic_df)

                # 保存结果
                factor_results['periods'][period] = ic_stats

                # 输出结果
                print(f"  IC均值: {ic_stats['ic_mean']:.6f}")
                print(f"  IC标准差: {ic_stats['ic_std']:.6f}")
                print(f"  IC_IR: {ic_stats['ic_ir']:.6f}")
                print(f"  IC>0比例: {ic_stats['ic_positive_ratio']:.2%}")
                print(f"  t统计量: {ic_stats['t_stat']:.6f}")
                print(f"  样本数: {len(ic_df)}")

                logger.info(f"{factor_name} (周期{period}天): IC={ic_stats['ic_mean']:.6f}, IR={ic_stats['ic_ir']:.6f}")

            except Exception as e:
                print(f"  计算失败: {e}")
                logger.error(f"{factor_name} (周期{period}天) 计算失败: {e}")

        all_results.append(factor_results)

    # 3. 综合分析
    print(f"\n{'='*80}")
    print("多周期IC综合分析")
    print(f"{'='*80}\n")

    for factor_result in all_results:
        factor_name = factor_result['factor_name']
        periods_data = factor_result['periods']

        if not periods_data:
            continue

        print(f"\n因子: {factor_name}")
        print("-" * 80)

        # 找出IC均值最高的周期
        best_period_ic = max(periods_data.items(), key=lambda x: x[1]['ic_mean'])
        # 找出IC_IR最高的周期
        best_period_ir = max(periods_data.items(), key=lambda x: x[1]['ic_ir'])

        print(f"IC均值最高: 周期{best_period_ic[0]}天, IC={best_period_ic[1]['ic_mean']:.6f}")
        print(f"IC_IR最高: 周期{best_period_ir[0]}天, IR={best_period_ir[1]['ic_ir']:.6f}")

        # 分析周期稳定性
        ic_values = [data['ic_mean'] for data in periods_data.values()]
        ic_mean_avg = sum(ic_values) / len(ic_values)
        ic_mean_std = (sum((x - ic_mean_avg) ** 2 for x in ic_values) / len(ic_values)) ** 0.5

        print(f"平均IC均值: {ic_mean_avg:.6f}")
        print(f"IC均值标准差: {ic_mean_std:.6f}")
        print(f"稳定性评分: {ic_mean_avg / (ic_mean_std + 0.001):.6f}")

        # 建议
        if best_period_ic[0] == best_period_ir[0]:
            print(f"建议: 使用{best_period_ic[0]}天周期（IC和IR都最高）")
        else:
            print(f"建议: IC最高{best_period_ic[0]}天，IR最高{best_period_ir[0]}天，需要权衡")

    # 4. 生成对比表格
    print(f"\n{'='*80}")
    print("多周期IC对比表格")
    print(f"{'='*80}\n")

    # 表头
    header = f"{'因子':<20}"
    for period in periods:
        header += f"{period}天IC均值{'':<10}"
    print(header)
    print("-" * 80)

    # 数据行
    for factor_result in all_results:
        factor_name = factor_result['factor_name']
        periods_data = factor_result['periods']

        row = f"{factor_name:<20}"
        for period in periods:
            if period in periods_data:
                ic_mean = periods_data[period]['ic_mean']
                row += f"{ic_mean:.6f}{'':<10}"
            else:
                row += f"{'N/A':<6}{'':<10}"

        print(row)

    # 5. 生成建议
    print(f"\n{'='*80}")
    print("优化建议")
    print(f"{'='*80}\n")

    print("1. 单周期策略:")
    print("   - 为每个因子选择IC均值最高的周期")
    print("   - 简单直接，但可能错过多周期信号")

    print("\n2. 多周期融合策略:")
    print("   - 同时使用多个周期的IC值")
    print("   - 加权平均：IC均值高的周期权重更大")
    print("   - 更稳健，但计算复杂")

    print("\n3. 多周期一致性策略:")
    print("   - 只有多个周期IC都为正时才交易")
    print("   - 信号更强，但机会更少")

    print("\n4. 自适应周期策略:")
    print("   - 根据市场状态动态调整周期")
    print("   - 最复杂，但可能最优")


if __name__ == "__main__":
    print("\n" + "=" * 80)
    print("多周期IC分析")
    print("=" * 80)
    print("\n功能说明:")
    print("1. 测试不同预测周期（3天、5天、10天）的IC表现")
    print("2. 比较不同周期下因子的有效性")
    print("3. 找出每个因子的最佳预测周期")
    print("4. 提供多周期融合建议")
    print("\n测试周期:")
    print("  - 3天: 短期预测")
    print("  - 5天: 中短期预测（当前使用）")
    print("  - 10天: 中期预测")
    print("\n使用场景:")
    print("- 优化因子预测周期")
    print("- 多周期因子融合")
    print("- 提高策略稳定性")
    print("\n停止脚本: 按 Ctrl+C")
    print("=" * 80 + "\n")

    # 开始分析
    factor_names = ['trend_score', 'momentum_score', 'volume_score', 'pullback_score']
    periods = [3, 5, 10]

    analyze_multi_period_ic(factor_names, periods)

    print("\n" + "=" * 80)
    print("分析完成！")
    print("=" * 80)
