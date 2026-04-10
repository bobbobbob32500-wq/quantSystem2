"""
实盘使用指南 - 强势回调二次启动策略
"""

import sqlite3
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import logging
import sys
import os

# 添加项目路径
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, current_dir)

from src.modules.final_strategy import FinalStrategy

# 设置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)


def load_latest_data():
    """加载最新数据"""
    db_path = 'data/database/quant_system.db'
    conn = sqlite3.connect(db_path)
    
    try:
        # 获取最新日期
        query_date = """
        SELECT MAX(trade_date) as latest_date FROM stock_daily
        WHERE trade_date >= '20251201'
        """
        df_date = pd.read_sql_query(query_date, conn)
        latest_date = df_date['latest_date'].iloc[0]
        
        print(f"最新交易日: {latest_date}")
        
        # 加载最新数据
        query = """
        SELECT 
            d.ts_code,
            d.trade_date,
            d.open,
            d.high,
            d.low,
            d.close,
            d.vol,
            d.amount,
            d.pct_chg,
            b.name,
            b.list_date
        FROM stock_daily d
        LEFT JOIN stock_basic b ON d.ts_code = b.ts_code
        WHERE d.trade_date = ?
        AND (d.ts_code LIKE '600%' OR d.ts_code LIKE '601%' OR 
             d.ts_code LIKE '603%' OR d.ts_code LIKE '605%' OR
             d.ts_code LIKE '000%' OR d.ts_code LIKE '001%' OR 
             d.ts_code LIKE '002%')
        ORDER BY d.ts_code
        """
        
        df = pd.read_sql_query(query, conn, params=(latest_date,))
        print(f"加载数据: {df.shape}")
        
        return df, latest_date
        
    finally:
        conn.close()


def run_daily_selection():
    """运行每日选股"""
    print("=" * 80)
    print("实盘选股流程")
    print("=" * 80)
    
    # 1. 加载最新数据
    print("\n1. 加载最新数据...")
    df, latest_date = load_latest_data()
    
    if df is None or len(df) == 0:
        print("无法加载数据")
        return
    
    # 2. 创建策略实例
    print("\n2. 初始化策略...")
    strategy = FinalStrategy()
    
    # 3. 运行选股
    print(f"\n3. 运行选股(日期: {latest_date})...")
    candidates = strategy.select_candidates(df, date=latest_date)
    
    if len(candidates) == 0:
        print("⚠️  今日无符合条件的候选股票")
        print("\n建议:")
        print("1. 检查市场环境(是否处于极端行情)")
        print("2. 适当放宽条件(如回调天数、回撤幅度)")
        print("3. 等待下一个交易日")
        return
    
    # 4. 生成买点建议
    print("\n4. 生成买点建议...")
    buy_points = strategy.get_buy_points(candidates)
    
    # 5. 输出结果
    print("\n5. 选股结果:")
    print("-" * 80)
    print(f"日期: {latest_date}")
    print(f"候选股票数量: {len(candidates)}")
    print("-" * 80)
    
    for i, (_, row) in enumerate(buy_points.iterrows(), 1):
        print(f"\n{i}. {row['ts_code']} - {row['name']}")
        print(f"   综合评分: {row['total_score']:.1f}")
        print(f"   收盘价: {row['close']:.2f}")
        print(f"   强势类型: {row['strength_type']}")
        print(f"   强势后{row['days_since_strength']:.0f}天, 回撤: {row['drawdown']:.2%}")
        print(f"   量比: {row['volume_ratio']:.2f}")
        print(f"   MA5: {row['ma5']:.2f}, MA10: {row['ma10']:.2f}")
        print(f"   买点类型: {row['buy_type']}")
        print(f"   建议买入价: {row['buy_price']:.2f}")
        print(f"   买入理由: {row['buy_reason']}")
    
    # 6. 保存结果
    print("\n6. 保存结果...")
    output_dir = 'reports/real_trading'
    os.makedirs(output_dir, exist_ok=True)
    
    # 保存候选列表
    output_path = os.path.join(output_dir, f'candidates_{latest_date}.csv')
    candidates.to_csv(output_path, index=False, encoding='utf-8-sig')
    print(f"候选列表已保存到: {output_path}")
    
    # 保存买点建议
    buy_points_path = os.path.join(output_dir, f'buy_points_{latest_date}.csv')
    buy_points.to_csv(buy_points_path, index=False, encoding='utf-8-sig')
    print(f"买点建议已保存到: {buy_points_path}")
    
    # 保存交易日志
    log_path = os.path.join(output_dir, 'trading_log.txt')
    with open(log_path, 'a', encoding='utf-8') as f:
        f.write(f"\n{'='*60}\n")
        f.write(f"选股日期: {latest_date}\n")
        f.write(f"候选数量: {len(candidates)}\n")
        f.write(f"选股时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"{'='*60}\n")
        
        for _, row in buy_points.iterrows():
            f.write(f"\n{row['ts_code']} - {row['name']}")
            f.write(f" | 评分: {row['total_score']:.1f}")
            f.write(f" | 收盘: {row['close']:.2f}")
            f.write(f" | 买点: {row['buy_type']}")
            f.write(f" | 建议价: {row['buy_price']:.2f}")
            f.write(f" | 理由: {row['buy_reason']}")
    
    print(f"交易日志已更新: {log_path}")
    
    print("\n" + "=" * 80)
    print("选股完成!")
    print("=" * 80)


def backtest_strategy():
    """回测策略效果"""
    print("\n" + "=" * 80)
    print("策略回测")
    print("=" * 80)
    
    # 连接数据库
    db_path = 'data/database/quant_system.db'
    conn = sqlite3.connect(db_path)
    
    try:
        # 加载最近3个月数据
        query = """
        SELECT 
            d.ts_code,
            d.trade_date,
            d.open,
            d.high,
            d.low,
            d.close,
            d.vol,
            d.amount,
            d.pct_chg,
            b.name,
            b.list_date
        FROM stock_daily d
        LEFT JOIN stock_basic b ON d.ts_code = b.ts_code
        WHERE d.trade_date >= '20251201' AND d.trade_date <= '20260327'
        AND (d.ts_code LIKE '600%' OR d.ts_code LIKE '601%' OR 
             d.ts_code LIKE '603%' OR d.ts_code LIKE '605%' OR
             d.ts_code LIKE '000%' OR d.ts_code LIKE '001%' OR 
             d.ts_code LIKE '002%')
        ORDER BY d.trade_date, d.ts_code
        """
        
        df = pd.read_sql_query(query, conn)
        print(f"加载数据: {df.shape}")
        print(f"日期范围: {df['trade_date'].min()} 到 {df['trade_date'].max()}")
        
        # 创建策略实例
        strategy = FinalStrategy()
        
        # 按日期回测
        dates = sorted(df['trade_date'].unique())
        results = []
        
        print("\n开始回测...")
        for i, date in enumerate(dates[-30:], 1):  # 最近30个交易日
            print(f"处理第{i}/30个交易日: {date}", end='\r')
            
            # 选股
            candidates = strategy.select_candidates(df, date=date)
            
            if len(candidates) > 0:
                # 计算次日收益率
                next_date = dates[dates.index(date) + 1] if i < len(dates) else None
                if next_date:
                    # 获取候选股票次日数据
                    next_day_data = df[(df['trade_date'] == next_date) & 
                                      (df['ts_code'].isin(candidates['ts_code']))]
                    
                    if len(next_day_data) > 0:
                        # 计算平均收益率
                        avg_return = next_day_data['pct_chg'].mean()
                        results.append({
                            'date': date,
                            'candidates': len(candidates),
                            'avg_next_day_return': avg_return
                        })
        
        print("\n回测完成!")
        
        # 分析结果
        if results:
            results_df = pd.DataFrame(results)
            
            print("\n回测结果:")
            print("-" * 80)
            print(f"回测天数: {len(results_df)}")
            print(f"平均每日候选数: {results_df['candidates'].mean():.1f}")
            print(f"平均次日收益率: {results_df['avg_next_day_return'].mean():.2f}%")
            print(f"正收益天数比例: {(results_df['avg_next_day_return'] > 0).mean():.2%}")
            print(f"最大单日收益: {results_df['avg_next_day_return'].max():.2f}%")
            print(f"最大单日亏损: {results_df['avg_next_day_return'].min():.2f}%")
            
            # 保存回测结果
            output_dir = 'reports/real_trading'
            os.makedirs(output_dir, exist_ok=True)
            
            backtest_path = os.path.join(output_dir, 'backtest_results.csv')
            results_df.to_csv(backtest_path, index=False, encoding='utf-8-sig')
            print(f"\n回测结果已保存到: {backtest_path}")
        else:
            print("回测无结果")
            
    finally:
        conn.close()


def trading_discipline():
    """交易纪律说明"""
    print("\n" + "=" * 80)
    print("交易纪律")
    print("=" * 80)
    
    print("\n🚨 核心纪律:")
    print("1. T日收盘后选股,生成10-15只候选")
    print("2. T+1盘中等待买点触发")
    print("3. 没有买点就空仓,宁可错过不做预测单")
    print("4. 单日最多买1-2只,避免手续费侵蚀")
    print("5. 严格执行止损止盈规则")
    
    print("\n📊 仓位管理:")
    print("• 单只股票仓位: 10-20%")
    print("• 总仓位: 不超过50%")
    print("• 止损: -5%")
    print("• 止盈: +10% (可移动止盈)")
    
    print("\n⏰ 交易时间:")
    print("• 选股时间: T日收盘后(15:00-16:00)")
    print("• 买入时间: T+1日盘中(9:30-14:30)")
    print("• 卖出时间: 达到止损/止盈条件时")
    
    print("\n🔍 买点确认:")
    print("1. 回踩MA5: 价格回调到MA5附近")
    print("2. 突破前高: 价格突破近期高点")
    print("3. 缩量企稳: 成交量明显萎缩后企稳")
    print("4. 分时确认: 盘中分时图走强")
    
    print("\n⚠️ 风险控制:")
    print("• 连续3天无信号: 暂停交易,检查市场环境")
    print("• 单日亏损超过2%: 减半仓位")
    print("• 周亏损超过5%: 暂停一周")
    print("• 月亏损超过10%: 全面复盘策略")
    
    print("\n📈 绩效评估:")
    print("• 每日记录: 选股结果、实际交易、盈亏")
    print("• 每周复盘: 胜率、盈亏比、最大回撤")
    print("• 每月优化: 根据回测结果调整参数")
    
    print("\n" + "=" * 80)
    print("纪律是交易的生命线!")
    print("=" * 80)


def main():
    """主函数"""
    print("强势回调二次启动策略 - 实盘使用指南")
    print("=" * 80)
    
    while True:
        print("\n请选择操作:")
        print("1. 运行今日选股")
        print("2. 回测策略效果")
        print("3. 查看交易纪律")
        print("4. 退出")
        
        choice = input("\n请输入选择(1-4): ").strip()
        
        if choice == '1':
            run_daily_selection()
        elif choice == '2':
            backtest_strategy()
        elif choice == '3':
            trading_discipline()
        elif choice == '4':
            print("\n退出程序")
            break
        else:
            print("无效选择,请重新输入")
    
    print("\n" + "=" * 80)
    print("策略总结:")
    print("=" * 80)
    print("\n✅ 策略特点:")
    print("• 宽进严选: 扩大样本入口,严格质量过滤")
    print("• 结构清晰: 强势→回调→启动的逻辑链条")
    print("• 风险可控: 明确的止损止盈规则")
    print("• 易于执行: 自动选股+买点建议")
    
    print("\n📋 使用流程:")
    print("1. T日收盘后运行选股")
    print("2. 查看候选股票列表")
    print("3. T+1日盘中等待买点")
    print("4. 严格执行交易纪律")
    
    print("\n🎯 成功关键:")
    print("• 纪律: 严格执行交易规则")
    print("• 耐心: 等待最佳买点")
    print("• 风控: 及时止损")
    print("• 复盘: 持续优化改进")
    
    print("\n祝您交易顺利! 🚀")


if __name__ == "__main__":
    main()
