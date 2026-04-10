# -*- coding: utf-8 -*-
"""
完整回测入口脚本
包含数据验证、下载、回测、绩效分析、可视化全流程
"""

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import argparse
import json
from datetime import datetime

from src.core.logger import get_logger
from src.modules.backtest.backtest_data_manager import BacktestDataManager
from src.modules.backtest.event_backtest_engine import EventDrivenBacktest, BacktestConfig
from src.modules.backtest.performance_analyzer import PerformanceAnalyzer
from src.modules.backtest.visualizer import BacktestVisualizer

logger = get_logger("run_complete_backtest")


def prepare_data(args):
    """准备数据阶段"""
    print("\n" + "=" * 70)
    print("阶段 1: 数据准备")
    print("=" * 70)
    
    manager = BacktestDataManager()
    
    # 检查数据完整性
    completeness = manager.check_data_completeness(
        month=args.month,
        follow_days=args.follow_days
    )
    
    if 'error' in completeness:
        print(f"[ERROR] {completeness['error']}")
        return None
    
    print(f"\n数据完整性检查:")
    print(f"  推荐记录: {completeness['total']}")
    print(f"  完整数据: {completeness['complete']}")
    print(f"  不完整: {completeness['incomplete']}")
    print(f"  完整率: {completeness['completeness_rate']*100:.1f}%")
    
    # 准备数据
    recommendations, stats = manager.prepare_backtest_data(
        month=args.month,
        follow_days=args.follow_days,
        force_download=args.force_download
    )
    
    print(f"\n数据准备统计:")
    print(f"  有效推荐: {stats['valid_recommendations']}")
    print(f"  缓存命中: {stats['download_stats']['cached']}")
    print(f"  新下载: {stats['download_stats']['downloaded']}")
    print(f"  下载失败: {stats['download_stats']['failed']}")
    
    return recommendations


def run_backtest(args, recommendations):
    """运行回测阶段"""
    print("\n" + "=" * 70)
    print("阶段 2: 运行回测")
    print("=" * 70)
    
    from src.modules.backtest.backtest_data_manager import BacktestDataManager
    
    manager = BacktestDataManager()
    
    config = BacktestConfig(
        initial_capital=args.capital,
        position_size=args.position_size,
        max_positions=args.max_positions,
        stop_loss_pct=args.stop_loss,
        take_profit_pct=args.take_profit,
    )
    
    backtest = EventDrivenBacktest(db=manager.db, config=config)
    
    # 计算回测日期范围
    start_date = f"{args.month}-01"
    end_date = f"{args.month}-28"
    
    results = backtest.run(
        start_date=start_date,
        end_date=end_date,
        show_progress=True
    )
    
    return backtest, results


def analyze_performance(args, backtest, results):
    """绩效分析阶段"""
    print("\n" + "=" * 70)
    print("阶段 3: 绩效分析")
    print("=" * 70)
    
    analyzer = PerformanceAnalyzer(risk_free_rate=args.risk_free_rate)
    
    metrics = analyzer.analyze(
        trades=backtest.trades,
        equity_curve=backtest.equity_curve,
        initial_capital=args.capital
    )
    
    # 打印报告
    analyzer.print_report(metrics)
    
    # 计算月度/周度收益
    monthly_returns = analyzer.calculate_monthly_returns(backtest.equity_curve)
    weekly_returns = analyzer.calculate_weekly_returns(backtest.equity_curve)
    
    if not monthly_returns.empty:
        print("\n【月度收益分布】")
        print("-" * 70)
        for _, row in monthly_returns.iterrows():
            print(f"  {row['month']}: {row['monthly_return']*100:+.2f}%")
    
    return metrics


def generate_visualization(args, metrics, backtest):
    """生成可视化报告"""
    print("\n" + "=" * 70)
    print("阶段 4: 生成可视化报告")
    print("=" * 70)
    
    visualizer = BacktestVisualizer(output_dir=args.output_dir)
    
    report_file = visualizer.generate_report(
        metrics=metrics,
        trades=backtest.trades,
        equity_curve=backtest.equity_curve,
        output_file=f"{args.output_dir}/backtest_report_{args.month.replace('-', '')}.html"
    )
    
    print(f"\n报告已生成: {report_file}")
    
    return report_file


def save_results(args, backtest, metrics, report_file):
    """保存结果"""
    print("\n" + "=" * 70)
    print("阶段 5: 保存结果")
    print("=" * 70)
    
    # 保存交易记录
    trades_file = f"{args.output_dir}/trades_{args.month.replace('-', '')}.csv"
    backtest.save_results(trades_file)
    print(f"交易记录: {trades_file}")
    
    # 保存汇总结果
    summary = {
        'month': args.month,
        'timestamp': datetime.now().isoformat(),
        'parameters': {
            'initial_capital': args.capital,
            'position_size': args.position_size,
            'max_positions': args.max_positions,
            'stop_loss': args.stop_loss,
            'take_profit': args.take_profit,
            'risk_free_rate': args.risk_free_rate,
        },
        'performance': {
            'total_return': metrics.total_return,
            'annualized_return': metrics.annualized_return,
            'max_drawdown': metrics.max_drawdown,
            'sharpe_ratio': metrics.sharpe_ratio,
            'win_rate': metrics.win_rate,
            'total_trades': metrics.total_trades,
        },
        'report_file': report_file,
    }
    
    summary_file = f"{args.output_dir}/summary_{args.month.replace('-', '')}.json"
    with open(summary_file, 'w', encoding='utf-8') as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    
    print(f"汇总结果: {summary_file}")


def main():
    parser = argparse.ArgumentParser(description='完整回测系统')
    
    # 数据参数
    parser.add_argument('--month', type=str, default='2026-02', help='回测月份 (YYYY-MM)')
    parser.add_argument('--follow-days', type=int, default=7, help='推荐后跟踪天数')
    parser.add_argument('--force-download', action='store_true', help='强制重新下载数据')
    
    # 回测参数
    parser.add_argument('--capital', type=float, default=100000, help='初始资金')
    parser.add_argument('--position-size', type=float, default=0.2, help='单只仓位比例')
    parser.add_argument('--max-positions', type=int, default=5, help='最大持仓数量')
    parser.add_argument('--stop-loss', type=float, default=-0.03, help='止损比例')
    parser.add_argument('--take-profit', type=float, default=0.05, help='止盈比例')
    parser.add_argument('--risk-free-rate', type=float, default=0.03, help='无风险收益率')
    
    # 输出参数
    parser.add_argument('--output-dir', type=str, default='reports', help='输出目录')
    parser.add_argument('--skip-data-prep', action='store_true', help='跳过数据准备')
    parser.add_argument('--skip-visualization', action='store_true', help='跳过可视化')
    
    args = parser.parse_args()
    
    print("\n" + "=" * 70)
    print("A股量化交易辅助系统 - 完整回测")
    print("=" * 70)
    print(f"回测月份: {args.month}")
    print(f"跟踪天数: {args.follow_days}天")
    print(f"初始资金: {args.capital:,.0f}")
    
    try:
        # 阶段1: 数据准备
        if not args.skip_data_prep:
            recommendations = prepare_data(args)
            if recommendations is None:
                return
        
        # 阶段2: 运行回测
        backtest, results = run_backtest(args, None)
        
        # 阶段3: 绩效分析
        metrics = analyze_performance(args, backtest, results)
        
        # 阶段4: 生成可视化
        report_file = None
        if not args.skip_visualization:
            report_file = generate_visualization(args, metrics, backtest)
        
        # 阶段5: 保存结果
        save_results(args, backtest, metrics, report_file)
        
        print("\n" + "=" * 70)
        print("✓ 回测完成")
        print("=" * 70)
        
    except Exception as e:
        print(f"\n[ERROR] 回测失败: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
