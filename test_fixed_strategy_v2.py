"""
测试修正版策略 - 包含历史数据加载
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

from src.modules.strong_pullback_fixed_v2 import StrongPullbackStrategyFixed

# 设置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)


def load_historical_data(latest_date: str, lookback_days: int = 80):
    """加载历史数据（关键修复：加载足够的历史数据）"""
    db_path = 'data/database/quant_system.db'
    conn = sqlite3.connect(db_path)
    
    try:
        # 获取最近N个交易日
        date_query = f"""
        SELECT DISTINCT trade_date
        FROM stock_daily
        WHERE trade_date <= '{latest_date}'
        ORDER BY trade_date DESC
        LIMIT {lookback_days}
        """
        
        date_df = pd.read_sql_query(date_query, conn)
        if date_df.empty:
            print("没有找到交易日数据")
            return pd.DataFrame()
        
        date_list = date_df['trade_date'].tolist()
        date_condition = "', '".join(date_list)
        
        # 加载历史数据
        query = f"""
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
        WHERE d.trade_date IN ('{date_condition}')
        AND (d.ts_code LIKE '600%' OR d.ts_code LIKE '601%' OR 
             d.ts_code LIKE '603%' OR d.ts_code LIKE '605%' OR
             d.ts_code LIKE '000%' OR d.ts_code LIKE '001%' OR 
             d.ts_code LIKE '002%')
        ORDER BY d.ts_code, d.trade_date
        """
        
        df = pd.read_sql_query(query, conn)
        print(f"加载历史数据: {df.shape}")
        print(f"日期范围: {df['trade_date'].min()} 到 {df['trade_date'].max()}")
        print(f"交易日数量: {df['trade_date'].nunique()}")
        
        return df
        
    finally:
        conn.close()


def run_daily_selection():
    """运行每日选股（修正版：加载历史数据）"""
    print("=" * 80)
    print("强势回调二次启动策略 - 修正版每日选股")
    print("=" * 80)
    
    # 连接数据库
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
        
        # 加载历史数据（关键修复：加载80个交易日）
        df = load_historical_data(latest_date, lookback_days=80)
        
        if df.empty:
            print("无法加载历史数据")
            return
        
        # 创建策略实例
        strategy = StrongPullbackStrategyFixed()
        
        # 运行选股
        print(f"\n运行选股(日期: {latest_date})...")
        candidates = strategy.select_candidates(df, date=latest_date)
        
        if len(candidates) == 0:
            print("警告: 今日无符合条件的候选股票")
            print("\n可能原因:")
            print("1. 市场环境不适合(如大跌、恐慌)")
            print("2. 策略条件过于严格")
            print("3. 数据质量问题")
            print("\n建议:")
            print("1. 检查市场整体涨跌情况")
            print("2. 适当放宽条件(如回调天数、回撤幅度)")
            print("3. 等待下一个交易日")
            return
        
        # 生成观察建议
        print("\n生成观察建议...")
        watchlist = strategy.get_watchlist_notes(candidates)
        
        # 输出结果
        print(f"\n选股结果(共{len(candidates)}只):")
        print("-" * 80)
        print(f"日期: {latest_date}")
        print("-" * 80)
        
        for i, (_, row) in enumerate(watchlist.iterrows(), 1):
            print(f"\n{i}. {row['ts_code']} - {row['name']}")
            print(f"   综合评分: {row['total_score']:.1f}")
            print(f"   收盘价: {row['close']:.2f}")
            print(f"   强势类型: {row['strength_type']}")
            if pd.notna(row['strength_event_date']):
                print(f"   强势日: {row['strength_event_date'].strftime('%Y-%m-%d')}")
            print(f"   强势后天数: {row['days_since_strength']:.0f}")
            print(f"   回撤: {row['drawdown']:.2%}")
            print(f"   量比: {row['volume_ratio']:.2f}")
            print(f"   MA5: {row['ma5']:.2f}, MA10: {row['ma10']:.2f}")
            print(f"   观察重点: {row['watch_notes']}")
        
        # 保存结果
        print("\n保存结果...")
        output_dir = 'reports/real_trading'
        os.makedirs(output_dir, exist_ok=True)
        
        # 保存候选列表
        output_path = os.path.join(output_dir, f'candidates_fixed_{latest_date}.csv')
        candidates.to_csv(output_path, index=False, encoding='utf-8-sig')
        print(f"候选列表已保存到: {output_path}")
        
        # 保存观察建议
        watchlist_path = os.path.join(output_dir, f'watchlist_fixed_{latest_date}.csv')
        watchlist.to_csv(watchlist_path, index=False, encoding='utf-8-sig')
        print(f"观察建议已保存到: {watchlist_path}")
        
        # 保存交易日志
        log_path = os.path.join(output_dir, 'trading_log_fixed.txt')
        with open(log_path, 'a', encoding='utf-8') as f:
            f.write(f"\n{'='*60}\n")
            f.write(f"选股日期: {latest_date}\n")
            f.write(f"候选数量: {len(candidates)}\n")
            f.write(f"选股时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"{'='*60}\n")
            
            for _, row in watchlist.iterrows():
                f.write(f"\n{row['ts_code']} - {row['name']}")
                f.write(f" | 评分: {row['total_score']:.1f}")
                f.write(f" | 收盘: {row['close']:.2f}")
                f.write(f" | 强势日: {row['strength_event_date']}")
                f.write(f" | 观察: {row['watch_notes']}")
        
        print(f"交易日志已更新: {log_path}")
        
        print("\n" + "=" * 80)
        print("选股完成!")
        print("=" * 80)
        
        print("\n明日操作建议:")
        print("1. 观察候选股票开盘情况")
        print("2. 等待买点触发(回踩MA5/突破前高/缩量企稳)")
        print("3. 严格执行交易纪律")
        print("4. 单日最多买入1-2只")
        print("5. 设置止损(-5%)和止盈(+10%)")
        
    finally:
        conn.close()


def test_multiple_dates():
    """测试多个日期的选股效果"""
    print("\n" + "=" * 80)
    print("多日期策略测试")
    print("=" * 80)
    
    # 连接数据库
    db_path = 'data/database/quant_system.db'
    conn = sqlite3.connect(db_path)
    
    try:
        # 获取最近30个交易日
        query_dates = """
        SELECT DISTINCT trade_date
        FROM stock_daily
        WHERE trade_date >= '20260301' AND trade_date <= '20260327'
        ORDER BY trade_date DESC
        LIMIT 30
        """
        
        dates_df = pd.read_sql_query(query_dates, conn)
        dates = dates_df['trade_date'].tolist()
        
        print(f"测试日期范围: {dates[-1]} 到 {dates[0]}")
        print(f"测试天数: {len(dates)}")
        
        # 加载所有历史数据
        all_dates_query = f"""
        SELECT DISTINCT trade_date
        FROM stock_daily
        WHERE trade_date <= '{dates[0]}'
        ORDER BY trade_date DESC
        LIMIT 100
        """
        
        all_dates_df = pd.read_sql_query(all_dates_query, conn)
        all_dates = all_dates_df['trade_date'].tolist()
        date_condition = "', '".join(all_dates)
        
        # 加载历史数据
        query = f"""
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
        WHERE d.trade_date IN ('{date_condition}')
        AND (d.ts_code LIKE '600%' OR d.ts_code LIKE '601%' OR 
             d.ts_code LIKE '603%' OR d.ts_code LIKE '605%' OR
             d.ts_code LIKE '000%' OR d.ts_code LIKE '001%' OR 
             d.ts_code LIKE '002%')
        ORDER BY d.ts_code, d.trade_date
        """
        
        df = pd.read_sql_query(query, conn)
        print(f"加载历史数据: {df.shape}")
        
        # 创建策略实例
        strategy = StrongPullbackStrategyFixed()
        
        # 按日期测试
        results = []
        
        print("\n按日期测试策略:")
        print("-" * 80)
        
        for i, date in enumerate(dates, 1):
            print(f"测试第{i}/{len(dates)}个交易日: {date}", end='\r')
            
            # 选股
            candidates = strategy.select_candidates(df, date=date)
            
            results.append({
                'date': date,
                'candidates': len(candidates)
            })
        
        print("\n测试完成!")
        
        # 分析结果
        results_df = pd.DataFrame(results)
        
        print("\n测试结果统计:")
        print("-" * 80)
        print(f"测试天数: {len(results_df)}")
        print(f"平均每日候选数: {results_df['candidates'].mean():.1f}")
        print(f"最大候选数: {results_df['candidates'].max()}")
        print(f"最小候选数: {results_df['candidates'].min()}")
        print(f"有候选的天数: {(results_df['candidates'] > 0).sum()}")
        print(f"无候选的天数: {(results_df['candidates'] == 0).sum()}")
        
        # 保存结果
        output_dir = 'reports/real_trading'
        os.makedirs(output_dir, exist_ok=True)
        
        history_path = os.path.join(output_dir, 'history_test_results_fixed.csv')
        results_df.to_csv(history_path, index=False, encoding='utf-8-sig')
        print(f"\n历史测试结果已保存到: {history_path}")
        
        # 显示有候选的日期
        if (results_df['candidates'] > 0).any():
            print("\n有候选股票的日期:")
            for _, row in results_df[results_df['candidates'] > 0].iterrows():
                print(f"  {row['date']}: {row['candidates']}只")
        
    finally:
        conn.close()


def main():
    """主函数"""
    print("修正版策略测试")
    print("=" * 80)
    
    print("\n关键修复:")
    print("1. 历史数据加载: 加载80个交易日数据，避免单日数据问题")
    print("2. 强势事件锚点: 只标记当天发生的强势事件，避免滚动计数问题")
    print("3. 回调基准计算: 正确计算从强势日起的回撤和收益")
    print("4. 前高计算: 使用shift(1)避免包含当天")
    print("5. NaN值处理: 不再全局fillna(0)，使用notna()过滤")
    print("6. 趋势评分: 修复跨股票shift问题")
    print("7. 条件收紧: 跌停次数限制为1次，MA10斜率≥0")
    print("8. 观察建议: 替代买点建议，更符合T+1盘中交易逻辑")
    
    print("\n" + "=" * 80)
    print("开始测试...")
    print("=" * 80)
    
    # 运行每日选股
    run_daily_selection()
    
    # 测试多个日期
    test_multiple_dates()
    
    print("\n" + "=" * 80)
    print("测试完成!")
    print("=" * 80)
    
    print("\n使用说明:")
    print("1. 每日收盘后运行选股")
    print("2. 观察建议作为T+1日盘中参考")
    print("3. 严格执行交易纪律")
    print("4. 定期复盘优化参数")


if __name__ == "__main__":
    main()
