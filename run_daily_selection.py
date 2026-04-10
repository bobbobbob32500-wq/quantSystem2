"""
运行今日选股
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


def main():
    """主函数"""
    print("=" * 80)
    print("今日选股 - 强势回调二次启动策略")
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
        print("警告: 今日无符合条件的候选股票")
        print("\n可能原因:")
        print("1. 市场环境不适合(如大跌、恐慌)")
        print("2. 条件过于严格")
        print("3. 数据问题")
        print("\n建议:")
        print("1. 检查市场整体涨跌情况")
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
    print("🎯 选股完成!")
    print("=" * 80)
    
    print("\n📋 明日操作建议:")
    print("1. 观察候选股票开盘情况")
    print("2. 等待买点触发(回踩MA5/突破前高/缩量企稳)")
    print("3. 严格执行交易纪律")
    print("4. 单日最多买入1-2只")
    print("5. 设置止损(-5%)和止盈(+10%)")
    
    print("\n⚠️ 风险提示:")
    print("• 股市有风险,投资需谨慎")
    print("• 本策略仅供参考,不构成投资建议")
    print("• 请根据自身风险承受能力调整仓位")
    print("• 严格执行止损纪律")


if __name__ == "__main__":
    main()
