# -*- coding: utf-8 -*-
"""
Qlib 策略优化脚本
分步骤优化你的选股策略
"""

import sys
import os
from datetime import datetime, timedelta
import pandas as pd
import numpy as np

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.core.logger import get_logger
from src.core.database import DatabaseManager
from src.core.config import ConfigManager
from src.modules.factor_analysis import FactorAnalyzer

logger = get_logger("qlib_optimization")


class QlibStrategyOptimizer:
    """Qlib 策略优化器"""
    
    def __init__(self):
        self.config = ConfigManager()
        self.db = DatabaseManager(self.config)
        self.factor_analyzer = FactorAnalyzer(self.config, self.db)
        
        # 检查 Qlib 是否可用
        try:
            from src.modules.qlib_factor_adapter import QlibFactorAdapter
            self.qlib_adapter = QlibFactorAdapter(self.config, self.db)
            self.qlib_available = True
            logger.info("Qlib 可用，开始优化流程")
        except ImportError as e:
            self.qlib_available = False
            logger.warning(f"Qlib 不可用: {e}")
            logger.warning("请先激活 qlib_env 环境: conda activate qlib_env")
    
    def step1_analyze_existing_factors(self):
        """
        步骤 1：分析现有因子的 IC 表现
        """
        print("\n" + "=" * 60)
        print("步骤 1：分析现有因子 IC 表现")
        print("=" * 60)
        
        # 你的现有因子
        existing_factors = [
            'trend_score',
            'momentum_score', 
            'volume_score',
            'pullback_score',
            'quality_score',
            'fundamental_score'
        ]
        
        results = []
        
        for factor_name in existing_factors:
            print(f"\n分析因子: {factor_name}")
            
            try:
                # 计算 IC
                ic_df = self.factor_analyzer.calculate_stock_factor_ic(
                    factor_name=factor_name,
                    period=5,
                    start_date='20230101',
                    end_date='20231231'
                )
                
                if not ic_df.empty:
                    stats = self.factor_analyzer.calculate_ic_statistics(ic_df)
                    
                    results.append({
                        'factor': factor_name,
                        'ic_mean': stats.get('ic_mean', 0),
                        'ic_ir': stats.get('ic_ir', 0),
                        'ic_positive_ratio': stats.get('ic_positive_ratio', 0),
                        'sample_count': stats.get('sample_count', 0)
                    })
                    
                    print(f"  IC 均值: {stats.get('ic_mean', 0):.4f}")
                    print(f"  ICIR: {stats.get('ic_ir', 0):.4f}")
                    print(f"  IC 正比例: {stats.get('ic_positive_ratio', 0):.2%}")
                else:
                    print(f"  无数据")
                    
            except Exception as e:
                logger.error(f"分析因子 {factor_name} 失败: {e}")
        
        # 保存结果
        if results:
            df = pd.DataFrame(results)
            df = df.sort_values('ic_mean', ascending=False)
            
            output_file = 'output/existing_factor_ic_analysis.csv'
            os.makedirs('output', exist_ok=True)
            df.to_csv(output_file, index=False, encoding='utf-8-sig')
            
            print(f"\n结果已保存到: {output_file}")
            print("\n因子 IC 排名：")
            print(df.to_string(index=False))
        
        return results
    
    def step2_calculate_qlib_factors(self, stock_codes=None, top_n=50):
        """
        步骤 2：计算 Qlib Alpha158 因子
        
        Args:
            stock_codes: 股票代码列表，None 则自动选择
            top_n: 选择前 N 只股票
        """
        print("\n" + "=" * 60)
        print("步骤 2：计算 Qlib Alpha158 因子")
        print("=" * 60)
        
        if not self.qlib_available:
            print("Qlib 不可用，跳过此步骤")
            return
        
        # 获取股票列表
        if stock_codes is None:
            print("\n从数据库获取股票列表...")
            conn = self.db._get_connection()
            
            # 获取成交额前 50 的主板股票
            sql = """
                SELECT ts_code
                FROM stock_daily
                WHERE trade_date >= '20230101'
                AND ts_code LIKE '%.SH' OR ts_code LIKE '%.SZ'
                GROUP BY ts_code
                ORDER BY AVG(amount) DESC
                LIMIT ?
            """
            
            df = pd.read_sql(sql, conn, params=(top_n,))
            conn.close()
            
            stock_codes = df['ts_code'].tolist()
            print(f"选择了 {len(stock_codes)} 只股票")
        
        # 计算因子
        print(f"\n开始计算 Alpha158 因子...")
        print(f"时间范围: 2023-01-01 ~ 2023-12-31")
        
        try:
            results = self.qlib_adapter.batch_calculate_factors(
                stock_codes=stock_codes,
                start_date='2023-01-01',
                end_date='2023-12-31',
                factor_type='alpha158'
            )
            
            print(f"\n成功计算 {len(results)} 只股票的因子")
            
            # 统计
            total_factors = 0
            for stock_code, factor_data in results.items():
                if not factor_data.empty:
                    total_factors += len(factor_data.columns)
            
            print(f"总共计算了 {total_factors} 个因子值")
            
        except Exception as e:
            logger.error(f"计算 Qlib 因子失败: {e}")
    
    def step3_filter_effective_factors(self, ic_threshold=0.03, icir_threshold=0.5):
        """
        步骤 3：筛选有效的 Qlib 因子
        
        Args:
            ic_threshold: IC 阈值
            icir_threshold: ICIR 阈值
        """
        print("\n" + "=" * 60)
        print("步骤 3：筛选有效 Qlib 因子")
        print("=" * 60)
        
        print(f"\n筛选标准：")
        print(f"  IC 均值 > {ic_threshold}")
        print(f"  ICIR > {icir_threshold}")
        
        # 获取 Qlib 因子列表
        if not self.qlib_available:
            print("Qlib 不可用，跳过此步骤")
            return []
        
        factor_list = self.qlib_adapter.get_factor_list('qlib_alpha158_')
        
        if not factor_list:
            print("未找到 Qlib 因子，请先执行步骤 2")
            return []
        
        print(f"\n找到 {len(factor_list)} 个 Qlib 因子，开始分析...")
        
        effective_factors = []
        results = []
        
        # 分析每个因子
        for i, factor_name in enumerate(factor_list[:50]):  # 先分析前 50 个
            if (i + 1) % 10 == 0:
                print(f"  进度: {i+1}/{min(50, len(factor_list))}")
            
            try:
                ic_df = self.factor_analyzer.calculate_stock_factor_ic(
                    factor_name=factor_name,
                    period=5,
                    start_date='20230101',
                    end_date='20231231'
                )
                
                if not ic_df.empty:
                    stats = self.factor_analyzer.calculate_ic_statistics(ic_df)
                    
                    ic_mean = stats.get('ic_mean', 0)
                    ic_ir = stats.get('ic_ir', 0)
                    
                    results.append({
                        'factor': factor_name,
                        'ic_mean': ic_mean,
                        'ic_ir': ic_ir,
                        'ic_positive_ratio': stats.get('ic_positive_ratio', 0)
                    })
                    
                    # 筛选有效因子
                    if ic_mean > ic_threshold and ic_ir > icir_threshold:
                        effective_factors.append(factor_name)
                        print(f"  [有效] {factor_name}: IC={ic_mean:.4f}, ICIR={ic_ir:.4f}")
                    
            except Exception as e:
                logger.debug(f"分析因子 {factor_name} 失败: {e}")
        
        # 保存结果
        if results:
            df = pd.DataFrame(results)
            df = df.sort_values('ic_mean', ascending=False)
            
            output_file = 'output/qlib_factor_ic_analysis.csv'
            df.to_csv(output_file, index=False, encoding='utf-8-sig')
            
            print(f"\n结果已保存到: {output_file}")
        
        print(f"\n筛选出 {len(effective_factors)} 个有效因子")
        
        return effective_factors
    
    def step4_factor_orthogonalization(self, factor_names):
        """
        步骤 4：因子正交化处理
        
        Args:
            factor_names: 需要正交化的因子列表
        """
        print("\n" + "=" * 60)
        print("步骤 4：因子正交化处理")
        print("=" * 60)
        
        if not factor_names:
            print("未提供因子列表，跳过此步骤")
            return
        
        print(f"\n对 {len(factor_names)} 个因子进行正交化...")
        
        # 计算因子相关性矩阵
        print("\n计算因子相关性矩阵...")
        
        conn = self.db._get_connection()
        
        # 获取因子数据
        placeholders = ','.join(['?' for _ in factor_names])
        sql = f"""
            SELECT ts_code, trade_date, factor_name, factor_value
            FROM factor_values
            WHERE factor_name IN ({placeholders})
            AND trade_date >= '20230101'
            AND trade_date <= '20231231'
        """
        
        df = pd.read_sql(sql, conn, params=factor_names)
        conn.close()
        
        if df.empty:
            print("无因子数据")
            return
        
        # 透视表
        factor_pivot = df.pivot_table(
            index=['ts_code', 'trade_date'],
            columns='factor_name',
            values='factor_value'
        )
        
        # 计算相关性矩阵
        corr_matrix = factor_pivot.corr()
        
        print("\n因子相关性矩阵：")
        print(corr_matrix.round(3))
        
        # 保存相关性矩阵
        output_file = 'output/factor_correlation_matrix.csv'
        corr_matrix.to_csv(output_file, encoding='utf-8-sig')
        print(f"\n相关性矩阵已保存到: {output_file}")
        
        # 分析高相关性因子对
        print("\n高相关性因子对（|相关性| > 0.7）：")
        
        high_corr_pairs = []
        for i in range(len(corr_matrix.columns)):
            for j in range(i+1, len(corr_matrix.columns)):
                corr = corr_matrix.iloc[i, j]
                if abs(corr) > 0.7:
                    factor1 = corr_matrix.columns[i]
                    factor2 = corr_matrix.columns[j]
                    high_corr_pairs.append((factor1, factor2, corr))
                    print(f"  {factor1} <-> {factor2}: {corr:.3f}")
        
        if not high_corr_pairs:
            print("  无高相关性因子对")
        
        # 建议
        print("\n建议：")
        if high_corr_pairs:
            print("  1. 考虑去除高相关性因子中的一个")
            print("  2. 或使用施密特正交化处理")
            print("  3. Qlib 提供了正交化工具，可进一步处理")
        else:
            print("  因子独立性良好，无需正交化")
    
    def step5_update_strategy_weights(self, effective_factors):
        """
        步骤 5：更新选股策略权重
        
        Args:
            effective_factors: 有效因子列表
        """
        print("\n" + "=" * 60)
        print("步骤 5：更新选股策略权重")
        print("=" * 60)
        
        if not effective_factors:
            print("未提供有效因子，跳过此步骤")
            return
        
        print(f"\n基于 {len(effective_factors)} 个有效因子更新权重...")
        
        # 计算每个有效因子的 IC
        factor_ics = {}
        
        for factor_name in effective_factors:
            try:
                ic_df = self.factor_analyzer.calculate_stock_factor_ic(
                    factor_name=factor_name,
                    period=5,
                    start_date='20230101',
                    end_date='20231231'
                )
                
                if not ic_df.empty:
                    stats = self.factor_analyzer.calculate_ic_statistics(ic_df)
                    factor_ics[factor_name] = stats.get('ic_mean', 0)
                    
            except Exception as e:
                logger.debug(f"获取因子 {factor_name} IC 失败: {e}")
        
        if not factor_ics:
            print("无法计算因子 IC")
            return
        
        # 基于 IC 计算权重（IC 越高权重越大）
        total_ic = sum(abs(ic) for ic in factor_ics.values())
        
        weights = {}
        for factor_name, ic in factor_ics.items():
            weights[factor_name] = abs(ic) / total_ic if total_ic > 0 else 0
        
        # 打印权重
        print("\n因子权重分配：")
        for factor_name, weight in sorted(weights.items(), key=lambda x: x[1], reverse=True):
            print(f"  {factor_name}: {weight:.4f} (IC={factor_ics[factor_name]:.4f})")
        
        # 生成配置建议
        print("\n配置建议：")
        print("在 config.yaml 中添加以下配置：")
        print("\nqlib_factors:")
        for factor_name, weight in sorted(weights.items(), key=lambda x: x[1], reverse=True)[:10]:
            print(f"  {factor_name}: {weight:.4f}")
        
        # 保存权重
        output_file = 'output/qlib_factor_weights.csv'
        weight_df = pd.DataFrame([
            {'factor': k, 'ic': factor_ics[k], 'weight': v}
            for k, v in weights.items()
        ])
        weight_df = weight_df.sort_values('weight', ascending=False)
        weight_df.to_csv(output_file, index=False, encoding='utf-8-sig')
        
        print(f"\n权重已保存到: {output_file}")
    
    def step6_backtest_validation(self):
        """
        步骤 6：回测验证优化效果
        """
        print("\n" + "=" * 60)
        print("步骤 6：回测验证优化效果")
        print("=" * 60)
        
        print("\n建议使用你的回测框架进行验证：")
        print("\n1. 基准回测（现有策略）：")
        print("   通过 main.py 回测菜单或 scripts/run_*_backtest.py 中对应脚本执行")
        
        print("\n2. 优化回测（加入 Qlib 因子）：")
        print("   - 在选股策略中添加 Qlib 因子")
        print("   - 使用新的权重配置")
        print("   - 运行回测对比")
        
        print("\n3. 对比指标：")
        print("   - 收益率")
        print("   - 夏普比率")
        print("   - 最大回撤")
        print("   - IC 均值")
        print("   - 胜率")
        
        print("\n4. 回测时间范围建议：")
        print("   - 训练期：2022-01-01 ~ 2022-12-31")
        print("   - 验证期：2023-01-01 ~ 2023-06-30")
        print("   - 测试期：2023-07-01 ~ 2023-12-31")
    
    def run_full_optimization(self):
        """运行完整优化流程"""
        print("\n" + "=" * 60)
        print("Qlib 策略优化流程")
        print("=" * 60)
        
        if not self.qlib_available:
            print("\n错误：Qlib 不可用")
            print("请先激活 qlib_env 环境：")
            print("  conda activate qlib_env")
            return
        
        # 步骤 1：分析现有因子
        existing_results = self.step1_analyze_existing_factors()
        
        # 步骤 2：计算 Qlib 因子
        self.step2_calculate_qlib_factors(top_n=50)
        
        # 步骤 3：筛选有效因子
        effective_factors = self.step3_filter_effective_factors()
        
        # 步骤 4：因子正交化
        if effective_factors:
            self.step4_factor_orthogonalization(effective_factors)
        
        # 步骤 5：更新策略权重
        self.step5_update_strategy_weights(effective_factors)
        
        # 步骤 6：回测验证
        self.step6_backtest_validation()
        
        print("\n" + "=" * 60)
        print("优化流程完成")
        print("=" * 60)
        print("\n下一步：")
        print("1. 查看输出文件：output/*.csv")
        print("2. 根据权重建议更新配置")
        print("3. 运行回测验证效果")


def main():
    """主函数"""
    import argparse
    
    parser = argparse.ArgumentParser(description='Qlib 策略优化')
    parser.add_argument('--step', type=int, choices=range(1, 7),
                       help='执行指定步骤（1-6）')
    parser.add_argument('--all', action='store_true',
                       help='执行所有步骤')
    
    args = parser.parse_args()
    
    optimizer = QlibStrategyOptimizer()
    
    if args.all:
        optimizer.run_full_optimization()
    elif args.step:
        if args.step == 1:
            optimizer.step1_analyze_existing_factors()
        elif args.step == 2:
            optimizer.step2_calculate_qlib_factors()
        elif args.step == 3:
            optimizer.step3_filter_effective_factors()
        elif args.step == 4:
            optimizer.step4_factor_orthogonalization([])
        elif args.step == 5:
            optimizer.step5_update_strategy_weights([])
        elif args.step == 6:
            optimizer.step6_backtest_validation()
    else:
        # 默认显示帮助
        print("\n使用方法：")
        print("  执行所有步骤：python scripts/optimize_strategy_with_qlib.py --all")
        print("  执行单步：python scripts/optimize_strategy_with_qlib.py --step 1")
        print("\n步骤说明：")
        print("  1. 分析现有因子 IC 表现")
        print("  2. 计算 Qlib Alpha158 因子")
        print("  3. 筛选有效 Qlib 因子")
        print("  4. 因子正交化处理")
        print("  5. 更新选股策略权重")
        print("  6. 回测验证优化效果")


if __name__ == '__main__':
    main()
