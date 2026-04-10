# -*- coding: utf-8 -*-
"""
排查「扩容后成交笔数不变」：对照数据库日历、回测信号日公式、漏斗 CSV。

用法:
  python scripts/diagnose_breakout_trade_count.py
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd

from src.core.config import ConfigManager
from src.core.database import DatabaseManager


def main() -> None:
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    funnel_path = os.path.join(root, "data", "reports", "breakout_backtest_daily_funnel.csv")

    config = ConfigManager()
    db = DatabaseManager(config)
    rows = db.query(
        "SELECT MIN(trade_date) as a, MAX(trade_date) as b, "
        "COUNT(DISTINCT trade_date) as n FROM stock_daily"
    )
    min_d, max_d, n_cal = rows[0]["a"], rows[0]["b"], rows[0]["n"]
    n_rows = db.query("SELECT COUNT(*) as c FROM stock_daily")[0]["c"]
    n_sym = db.query("SELECT COUNT(DISTINCT ts_code) as c FROM stock_daily")[0]["c"]

    all_dates = [
        r["trade_date"]
        for r in db.query(
            "SELECT DISTINCT trade_date FROM stock_daily ORDER BY trade_date ASC"
        )
    ]
    if len(all_dates) >= 180:
        warmup = 125
        use_ma120 = True
    elif len(all_dates) >= 75:
        warmup = 65
        use_ma120 = False
    else:
        warmup = 0
        use_ma120 = False

    # 与 run_breakout_daily_backtest_report.py 一致
    n_signal_report = max(0, len(all_dates) - warmup - 3)
    # 与 export_breakout_watchlist_history.py 一致（末尾少丢 1 天，与回测不同）
    n_signal_export = max(0, len(all_dates) - warmup - 1)

    print("=" * 70)
    print("一、数据库 stock_daily")
    print("=" * 70)
    print(f"  MIN/MAX 交易日: {min_d} -> {max_d}")
    print(f"   distinct 交易日数: {n_cal}")
    print(f"  表总行数（日历×股票）: {n_rows}")
    print(f"  股票只数: {n_sym}")
    print()
    print("  说明: 若「扩容」只增加行数/股票数，但 distinct 交易日数未变，")
    print("        则回测信号日条数不变，成交笔数可以完全不变。")
    print()

    print("=" * 70)
    print("二、回测脚本信号日数量（run_breakout_daily_backtest_report.py）")
    print("=" * 70)
    print(f"  warmup_skip = {warmup}，MA120 = {use_ma120}")
    print(f"  公式: len(all_dates) - warmup - 3  →  {n_signal_report} 个信号日")
    print()
    print("  观察池导出脚本（export_breakout_watchlist_history.py）末尾切片为 [warmup:-1]，")
    print(f"  与回测差 2 个交易日: 导出侧约 {n_signal_export} 个信号日（勿与回测成交混谈）。")
    print()

    if os.path.isfile(funnel_path):
        df = pd.read_csv(funnel_path)
        print("=" * 70)
        print("三、最新漏斗文件（若存在）")
        print("=" * 70)
        print(f"  路径: {funnel_path}")
        print(f"  行数(应≈信号日数): {len(df)}")
        print(f"  confirmed_n 合计(成交笔数): {int(df['confirmed_n'].sum())}")
        print(f"  watchlist_n>0 的天数: {int((df['watchlist_n'] > 0).sum())}")
        print(f"  confirmed_n>0 的天数: {int((df['confirmed_n'] > 0).sum())}")
        print()
        print("  stage 分布:")
        for k, v in df["stage"].value_counts().items():
            print(f"    {k}: {v}")
        print()
        print("  说明: 成交笔数 = 各日 confirmed_n 之和；瓶颈多在「趋势/走稳/无突破确认」。")
    else:
        print("=" * 70)
        print("三、未找到漏斗 CSV，请先运行 run_breakout_daily_backtest_report.py")
        print("=" * 70)

    print()
    print("四、扩容后成交仍不变的常见原因")
    print("  - 只扩了分钟线、观察池 CSV、或其它表，未改 stock_daily 的交易日集合")
    print("  - stock_daily 只补了已有交易日的更多股票，distinct 交易日未增加")
    print("  - 参数未改时，新增股票未必进入当日 top_k，或 T+1 仍达不到确认条件")
    print("=" * 70)


if __name__ == "__main__":
    main()
