# -*- coding: utf-8 -*-
"""
事件驱动回测入口脚本
基于已有选股结果进行历史交易模拟
"""

import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import argparse
from datetime import datetime, timedelta

from src.core.logger import get_logger
from src.modules.backtest.history_recommendation_db import HistoryRecommendationDB
from src.modules.backtest.event_backtest_engine import EventDrivenBacktest, BacktestConfig

logger = get_logger("run_backtest")


def main():
    parser = argparse.ArgumentParser(description='事件驱动回测')
    parser.add_argument('--start', type=str, default=None, help='开始日期 (YYYY-MM-DD)')
    parser.add_argument('--end', type=str, default=None, help='结束日期 (YYYY-MM-DD)')
    parser.add_argument('--capital', type=float, default=100000, help='初始资金')
    parser.add_argument('--position-size', type=float, default=0.2, help='单只仓位比例')
    parser.add_argument('--max-positions', type=int, default=5, help='最大持仓数量')
    parser.add_argument('--stop-loss', type=float, default=-0.03, help='止损比例')
    parser.add_argument('--take-profit', type=float, default=0.05, help='止盈比例')
    parser.add_argument('--output', type=str, default='backtest_results.csv', help='输出文件')
    
    args = parser.parse_args()
    
    print("\n" + "=" * 70)
    print("事件驱动回测系统")
    print("=" * 70)
    
    db = HistoryRecommendationDB()
    
    stats = db.get_statistics()
    print(f"\n【数据库统计】")
    print(f"  推荐记录: {stats.get('total_recommendations', 0)}条")
    print(f"  分时数据: {stats.get('total_intraday_records', 0):,}条")
    print(f"  股票数量: {stats.get('symbols_with_data', 0)}只")
    
    if args.start is None or args.end is None:
        recommendations = db.get_recommendations()
        
        if not recommendations:
            print("\n[ERROR] 无推荐记录，请先运行选股并下载分时数据")
            return
        
        dates = [r['recommendation_date'] for r in recommendations if r.get('recommendation_date')]
        
        if not dates:
            print("\n[ERROR] 推荐记录无日期信息")
            return
        
        dates.sort()
        
        if args.start is None:
            args.start = dates[0]
        if args.end is None:
            args.end = dates[-1]
    
    print(f"\n【回测参数】")
    print(f"  回测区间: {args.start} ~ {args.end}")
    print(f"  初始资金: {args.capital:,.0f}")
    print(f"  单只仓位: {args.position_size*100:.0f}%")
    print(f"  最大持仓: {args.max_positions}只")
    print(f"  止损比例: {args.stop_loss*100:.0f}%")
    print(f"  止盈比例: {args.take_profit*100:.0f}%")
    
    config = BacktestConfig(
        initial_capital=args.capital,
        position_size=args.position_size,
        max_positions=args.max_positions,
        stop_loss_pct=args.stop_loss,
        take_profit_pct=args.take_profit,
    )
    
    backtest = EventDrivenBacktest(db=db, config=config)
    
    results = backtest.run(
        start_date=args.start,
        end_date=args.end,
        show_progress=True
    )
    
    backtest.print_results()
    
    backtest.save_results(args.output)
    
    print(f"\n[OK] 回测完成，结果已保存到 {args.output}")


if __name__ == "__main__":
    main()
