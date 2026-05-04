# -*- coding: utf-8 -*-
"""
宽进突破策略（wide_pool_strict_entry_v2）日线回测 — 可指定信号日窗口。

与聚宽脚本、菜单「宽进突破」一致：选股层 selection_relaxed_v1 + 买点层 buy_tuning_v1。

用法:
  python scripts/run_wide_breakout_window_backtest.py --start-date 20260301 --end-date 20260410

输出:
  data/reports/wide_breakout_backtest_trades_<stamp>.csv
  data/reports/wide_breakout_backtest_summary_<stamp>.md
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    sys.stdout.reconfigure(line_buffering=True)
except Exception:
    pass

from datetime import datetime

import numpy as np
import pandas as pd

from src.core.config import ConfigManager
from src.core.database import DatabaseManager
from src.modules.breakout_backtest_runner import run_breakout_backtest_loop
from src.modules.breakout_strategy import (
    BreakoutStrategy,
    get_breakout_params_for_backtest,
)


def _fmt_pct(x: float | None) -> str:
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return "—"
    return f"{x:.2%}"


def _stats_row(v: pd.Series) -> tuple[int, float, float, float, float]:
    v = v.dropna()
    if v.empty:
        return 0, float("nan"), float("nan"), float("nan"), float("nan")
    n = len(v)
    wr = float((v > 0).mean())
    m = float(v.mean())
    med = float(v.median())
    gw = float(v[v > 0].sum())
    gl = float(-v[v < 0].sum())
    pf = gw / gl if gl > 1e-12 else 0.0
    return n, wr, m, med, pf


def main() -> None:
    parser = argparse.ArgumentParser(description="宽进突破策略指定窗口日线回测")
    parser.add_argument("--start-date", required=True, help="信号日起始 YYYYMMDD（含）")
    parser.add_argument("--end-date", required=True, help="信号日结束 YYYYMMDD（含）")
    args = parser.parse_args()
    d0, d1 = args.start_date.strip(), args.end_date.strip()
    if len(d0) != 8 or len(d1) != 8 or not d0.isdigit() or not d1.isdigit():
        print("日期格式须为 YYYYMMDD", flush=True)
        sys.exit(1)
    if d0 > d1:
        print("start-date 不能晚于 end-date", flush=True)
        sys.exit(1)

    print("=" * 70, flush=True)
    print("  宽进突破策略（wide_pool_strict_entry_v2）— 指定窗口回测", flush=True)
    print("=" * 70, flush=True)

    config = ConfigManager()
    db = DatabaseManager(config)

    info = db.query(
        "SELECT MIN(trade_date) as min_d, MAX(trade_date) as max_d, "
        "COUNT(DISTINCT trade_date) as days FROM stock_daily"
    )
    min_d, max_d, total_days = info[0]["min_d"], info[0]["max_d"], info[0]["days"]
    print(f"\n  数据库日线: {min_d} -> {max_d}, 共 {total_days} 个交易日", flush=True)

    all_dates_rows = db.query(
        "SELECT DISTINCT trade_date FROM stock_daily ORDER BY trade_date ASC"
    )
    all_dates = [r["trade_date"] for r in all_dates_rows]

    if len(all_dates) >= 180:
        warmup_skip = 125
        use_ma120 = True
    elif len(all_dates) >= 75:
        warmup_skip = 65
        use_ma120 = False
        print(f"  注意: 仅{len(all_dates)}个交易日, 降级 MA20>MA60 趋势过滤", flush=True)
    else:
        print("  数据不足，退出", flush=True)
        return

    if len(all_dates) <= warmup_skip + 10:
        print("  warmup 后数据不足，退出", flush=True)
        return

    backtest_dates = all_dates[warmup_skip:]
    signal_dates_full = backtest_dates[:-3]

    signal_dates = [d for d in signal_dates_full if d0 <= d <= d1]
    if not signal_dates:
        print(f"  窗口 [{d0},{d1}] 与可回测信号日无交集，退出", flush=True)
        print(f"  可回测信号日范围约: {signal_dates_full[0]} ~ {signal_dates_full[-1]}", flush=True)
        return

    params = get_breakout_params_for_backtest("wide_pool_strict_entry_v2", use_ma120)
    strategy = BreakoutStrategy(db=db, params=params)

    print(f"\n  参数预设: wide_pool_strict_entry_v2（宽进突破）", flush=True)
    print(f"  信号日窗口: {signal_dates[0]} ~ {signal_dates[-1]}（共 {len(signal_dates)} 个交易日）", flush=True)
    print(f"  Warmup 跳过前 {warmup_skip} 日；全量因子截至 max_d={max_d}", flush=True)

    print("\n  [1/2] 计算全量因子...", flush=True)
    raw_daily, raw_basic = strategy._load_data(max_d)
    if raw_daily.empty:
        print("  日线为空，退出", flush=True)
        return
    features = strategy._compute_features(raw_daily, raw_basic, max_d)
    print(f"  因子行数: {len(features)}", flush=True)

    print(f"\n  [2/2] 逐日回测（窗口内 {len(signal_dates)} 个信号日）...", flush=True)
    df, funnel_df, gate_stats = run_breakout_backtest_loop(
        strategy, features, all_dates, signal_dates, use_ma120, progress_every=5
    )

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    rep_dir = os.path.join(root, "data", "reports")
    os.makedirs(rep_dir, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    if not df.empty:
        df = df.sort_values(["signal_date", "confirm_date", "ts_code"]).reset_index(drop=True)

    path_csv = os.path.join(rep_dir, f"wide_breakout_backtest_trades_{stamp}.csv")
    path_funnel = os.path.join(rep_dir, f"wide_breakout_backtest_funnel_{stamp}.csv")
    path_md = os.path.join(rep_dir, f"wide_breakout_backtest_summary_{stamp}.md")

    if not funnel_df.empty:
        funnel_df.to_csv(path_funnel, index=False, encoding="utf-8-sig")
    if not df.empty:
        df.to_csv(path_csv, index=False, encoding="utf-8-sig")
    else:
        path_csv = ""

    n_trades = len(df)
    days_pool = int((funnel_df["watchlist_n"] > 0).sum()) if not funnel_df.empty else 0
    days_confirm = int((funnel_df["confirmed_n"] > 0).sum()) if not funnel_df.empty else 0

    lines: list[str] = []
    lines.append("# 宽进突破策略 — 指定窗口回测摘要\n\n")
    lines.append(f"- **生成时间**：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
    lines.append(f"- **预设**：`wide_pool_strict_entry_v2`（宽进突破）\n")
    lines.append(f"- **信号日窗口**：{d0} ~ {d1}（实际信号日 {signal_dates[0]} → {signal_dates[-1]}，共 **{len(signal_dates)}** 日）\n")
    lines.append(f"- **成交笔数**：{n_trades}\n")
    lines.append(f"- **观察池有票日数**：{days_pool} / **有确认成交日数**：{days_confirm}\n")
    lines.append(
        f"- **闸门**：正常 {gate_stats['normal']} / 谨慎 {gate_stats['caution']} / 禁止 {gate_stats['stop']}\n\n"
    )

    lines.append("## 收益（触发价入场，不含手续费）\n\n")
    lines.append("| 持有期 | 样本数 | 胜率 | 平均收益 | 中位数 | PF |\n| --- | ---: | ---: | ---: | ---: | ---: |\n")
    for hn in [1, 2, 3]:
        col = f"ret_t{hn}"
        if df.empty or col not in df.columns:
            lines.append(f"| T+{hn} | — | — | — | — | — |\n")
        else:
            n, wr, m, med, pf = _stats_row(df[col])
            lines.append(
                f"| T+{hn} | {n} | {_fmt_pct(wr)} | {_fmt_pct(m)} | {_fmt_pct(med)} | {pf:.2f} |\n"
            )
    lines.append("\n")

    md_text = "".join(lines)
    with open(path_md, "w", encoding="utf-8") as f:
        f.write(md_text)

    print("\n" + "=" * 70, flush=True)
    print(f"  成交笔数: {n_trades}", flush=True)
    if not df.empty and "ret_t1" in df.columns:
        n, wr, m, med, pf = _stats_row(df["ret_t1"])
        print(f"  T+1 收盘: 样本={n} 胜率={_fmt_pct(wr)} 均值={_fmt_pct(m)} 中位={_fmt_pct(med)} PF={pf:.2f}", flush=True)
    print(f"  报告: {path_md}", flush=True)
    if not funnel_df.empty:
        print(f"  漏斗: {path_funnel}", flush=True)
    if path_csv:
        print(f"  明细: {path_csv}", flush=True)
    print("=" * 70, flush=True)


if __name__ == "__main__":
    main()
