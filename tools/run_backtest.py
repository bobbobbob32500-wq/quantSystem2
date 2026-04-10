# -*- coding: utf-8 -*-
"""
选股策略回测脚本（P0 基础版）

数据源：
  - quant_system.db / stock_daily：日线收盘价
  - history_recommendation.db / recommendations：历史推荐记录

回测逻辑：
  - 推荐日次日开盘买入（用次日 open 价，若无则用 close 代替）
  - 持有 N 个交易日后收盘卖出（扣除双边佣金+印花税）
  - 对比「原始 legacy 策略权重」与「优化后权重」的模拟差异

用法：
  python tools/run_backtest.py
  python tools/run_backtest.py --hold 5
  python tools/run_backtest.py --hold 5 --min-score 70
"""

import argparse
import sqlite3
import sys
import os
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional

import pandas as pd
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

QUANT_DB  = str(ROOT / "data" / "database" / "quant_system.db")
HIST_DB   = str(ROOT / "data" / "history_recommendation.db")
BUY_FEE   = 0.0003
SELL_FEE  = 0.0003
STAMP_TAX = 0.001


# ──────────────────────────────────────────────────────────────────────────────
# 辅助函数
# ──────────────────────────────────────────────────────────────────────────────

def norm_code(symbol: str) -> str:
    """把 symbol 转为 ts_code（如 600519 -> 600519.SH）。"""
    s = str(symbol).strip()
    if '.' in s:
        return s.upper()
    if s.startswith(('6', '9')):
        return f"{s}.SH"
    return f"{s}.SZ"


def norm_date8(s) -> str:
    """把各种日期格式统一成 YYYYMMDD。"""
    digits = ''.join(c for c in str(s) if c.isdigit())
    return digits[:8] if len(digits) >= 8 else ''


def get_daily(quant_conn, ts_code: str, start: str, end: str) -> pd.DataFrame:
    """取指定股票日线数据（trade_date YYYYMMDD 升序）。"""
    df = pd.read_sql(
        "SELECT trade_date, open, close FROM stock_daily "
        "WHERE ts_code=? AND trade_date>=? AND trade_date<=? ORDER BY trade_date",
        quant_conn,
        params=(ts_code, start, end),
    )
    return df


def get_price_on_or_after(quant_conn, ts_code: str, date8: str, col='open') -> tuple:
    """
    取 date8 当天或之后第一个有价格的交易日的 col 价格。
    返回 (trade_date, price)，找不到返回 (None, None)。
    """
    cur = quant_conn.cursor()
    cur.execute(
        f"SELECT trade_date, {col}, close FROM stock_daily "
        "WHERE ts_code=? AND trade_date>=? ORDER BY trade_date LIMIT 1",
        (ts_code, date8),
    )
    row = cur.fetchone()
    if row is None:
        return None, None
    trade_date, price, close_price = row
    price = float(price) if price else float(close_price)
    if price is None or price <= 0:
        price = float(close_price) if close_price else None
    return trade_date, price


def get_price_on_or_before(quant_conn, ts_code: str, date8: str, col='close') -> tuple:
    """
    取 date8 当天或之前最近交易日的 col 价格。
    返回 (trade_date, price)。
    """
    cur = quant_conn.cursor()
    cur.execute(
        f"SELECT trade_date, {col}, close FROM stock_daily "
        "WHERE ts_code=? AND trade_date<=? ORDER BY trade_date DESC LIMIT 1",
        (ts_code, date8),
    )
    row = cur.fetchone()
    if row is None:
        return None, None
    trade_date, price, close_price = row
    price = float(price) if price else float(close_price)
    return trade_date, price


def nth_trading_day_after(quant_conn, ts_code: str, buy_date8: str, n: int) -> str:
    """
    返回 buy_date8 之后第 n 个有数据的交易日（用该股本身的数据）。
    若数据不足则返回最后一个可用日期。
    """
    cur = quant_conn.cursor()
    cur.execute(
        "SELECT trade_date FROM stock_daily "
        "WHERE ts_code=? AND trade_date>? ORDER BY trade_date LIMIT ?",
        (ts_code, buy_date8, n),
    )
    rows = cur.fetchall()
    if not rows:
        return buy_date8
    return rows[-1][0]


# ──────────────────────────────────────────────────────────────────────────────
# 主回测逻辑
# ──────────────────────────────────────────────────────────────────────────────

def run_backtest(
    hold_days: int = 5,
    min_score: float = 0.0,
    start_date: str = None,
    end_date: str = None,
    quiet: bool = False,
) -> pd.DataFrame:
    """
    对历史推荐记录执行日线回测。

    Returns:
        trades_df: 每笔交易详情 DataFrame
    """
    qconn = sqlite3.connect(QUANT_DB)
    qconn.row_factory = sqlite3.Row
    hconn = sqlite3.connect(HIST_DB)
    hconn.row_factory = sqlite3.Row

    # 读取推荐记录
    sql = "SELECT * FROM recommendations WHERE recommendation_score >= ?"
    params = [min_score]
    if start_date:
        sql += " AND recommendation_date >= ?"
        params.append(start_date)
    if end_date:
        sql += " AND recommendation_date <= ?"
        params.append(end_date)
    sql += " ORDER BY recommendation_date, symbol"

    cur = hconn.cursor()
    cur.execute(sql, params)
    recs = cur.fetchall()
    hconn.close()

    print(f"\n读取推荐记录: {len(recs)} 条  (min_score>={min_score}, hold_days={hold_days})")
    if not recs:
        print("无推荐记录，退出。")
        return pd.DataFrame()

    trades = []
    skipped = 0

    for rec in recs:
        symbol  = str(rec['symbol'])
        name    = str(rec['name'] or '')
        rec_date= norm_date8(rec['recommendation_date'])
        score   = float(rec['recommendation_score'] or 0)
        strategy= str(rec['strategy_type'] if rec['strategy_type'] else 'legacy')

        ts_code = norm_code(symbol)

        # 买入日 = 推荐日次日开盘
        buy_date8 = (datetime.strptime(rec_date, '%Y%m%d') + timedelta(days=1)).strftime('%Y%m%d')
        buy_td, buy_price = get_price_on_or_after(qconn, ts_code, buy_date8, col='open')

        if buy_price is None or buy_price <= 0:
            skipped += 1
            continue

        # 卖出日 = 买入日后第 hold_days 个交易日
        sell_date8 = nth_trading_day_after(qconn, ts_code, buy_td, hold_days)
        sell_td, sell_price = get_price_on_or_before(qconn, ts_code, sell_date8, col='close')

        if sell_price is None or sell_price <= 0:
            skipped += 1
            continue

        # 计算净收益（扣成本）
        gross = (sell_price - buy_price) / buy_price
        cost  = BUY_FEE + SELL_FEE + STAMP_TAX
        net   = gross - cost

        trades.append({
            'symbol':      symbol,
            'ts_code':     ts_code,
            'name':        name,
            'rec_date':    rec_date,
            'buy_date':    buy_td,
            'buy_price':   round(buy_price, 3),
            'sell_date':   sell_td,
            'sell_price':  round(sell_price, 3),
            'gross_return':round(gross * 100, 4),
            'net_return':  round(net * 100, 4),
            'score':       round(score, 2),
            'strategy':    strategy,
        })

    qconn.close()

    df = pd.DataFrame(trades)
    if df.empty:
        print(f"无有效交易（跳过 {skipped} 条）")
        return df

    # ── 整体统计 ──────────────────────────────────────────────────────────────
    print(f"\n{'='*60}")
    print(f"回测结果（持有{hold_days}交易日，扣除费用）")
    print(f"{'='*60}")
    print(f"有效交易: {len(df)} 笔  (跳过: {skipped} 条)")
    print(f"胜率:     {(df.net_return > 0).mean()*100:.1f}%")
    print(f"平均收益: {df.net_return.mean():.2f}%")
    print(f"中位数:   {df.net_return.median():.2f}%")
    print(f"盈利均值: {df[df.net_return>0].net_return.mean():.2f}%"  if (df.net_return>0).any() else "盈利均值: -")
    print(f"亏损均值: {df[df.net_return<0].net_return.mean():.2f}%"  if (df.net_return<0).any() else "亏损均值: -")
    print(f"最大单笔: {df.net_return.max():.2f}%")
    print(f"最小单笔: {df.net_return.min():.2f}%")

    win  = len(df[df.net_return > 0])
    loss = len(df[df.net_return < 0])
    flat = len(df) - win - loss
    print(f"盈/亏/平: {win}/{loss}/{flat}")

    # Profit Factor
    gross_win  = df[df.net_return > 0].net_return.sum()
    gross_loss = abs(df[df.net_return < 0].net_return.sum())
    pf = gross_win / gross_loss if gross_loss > 0 else float('inf')
    print(f"盈亏比(PF):{pf:.2f}")

    # 月度累计收益（等权，每笔视为独立仓位）
    df['month'] = pd.to_datetime(df['rec_date'], format='%Y%m%d').dt.to_period('M')
    monthly = df.groupby('month')['net_return'].agg(['mean','count','std'])
    monthly.columns = ['月均收益%','笔数','标准差%']
    print(f"\n月度明细:")
    print(monthly.to_string())

    # 按评分分段统计（分3档）
    if df['score'].nunique() > 2:
        df['score_bin'] = pd.cut(df['score'], bins=3, labels=['低分','中分','高分'])
        score_group = df.groupby('score_bin', observed=True)['net_return'].agg(['mean','count'])
        score_group.columns = ['平均收益%','笔数']
        print(f"\n按评分分档:")
        print(score_group.to_string())

    # 输出 CSV
    out_dir = ROOT / 'results'
    out_dir.mkdir(exist_ok=True)
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    csv_path = out_dir / f'backtest_daily_{ts}.csv'
    df.to_csv(csv_path, index=False, encoding='utf-8-sig')
    print(f"\n详情已保存: {csv_path}")
    return df


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='日线回测')
    parser.add_argument('--hold',      type=int,   default=5,   help='持有交易日数（默认5）')
    parser.add_argument('--min-score', type=float, default=0.0, help='最低推荐评分过滤')
    parser.add_argument('--start',     default=None, help='开始日期 YYYYMMDD')
    parser.add_argument('--end',       default=None, help='结束日期 YYYYMMDD')
    args = parser.parse_args()
    run_backtest(
        hold_days=args.hold,
        min_score=args.min_score,
        start_date=args.start,
        end_date=args.end,
    )
