# -*- coding: utf-8 -*-
"""
快速日线回测（批量查询版，避免逐条查库超时）
"""
import sqlite3, sys, argparse
from pathlib import Path
from datetime import datetime, timedelta
import pandas as pd
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

QUANT_DB = str(ROOT / "data" / "database" / "quant_system.db")
HIST_DB  = str(ROOT / "data" / "history_recommendation.db")
BUY_FEE, SELL_FEE, STAMP = 0.0003, 0.0003, 0.001


def norm_code(s):
    s = str(s).strip()
    if '.' in s: return s.upper()
    return f"{s}.SH" if s.startswith(('6','9')) else f"{s}.SZ"

def norm8(s):
    d = ''.join(c for c in str(s) if c.isdigit())
    return d[:8] if len(d)>=8 else ''


def run(hold_days=5, min_score=0.0, start=None, end=None):
    # 1. 读推荐记录
    hconn = sqlite3.connect(HIST_DB)
    df_rec = pd.read_sql(
        "SELECT symbol, name, recommendation_date, recommendation_score, strategy_type "
        "FROM recommendations WHERE recommendation_score>=?",
        hconn, params=[min_score]
    )
    hconn.close()
    print(f"推荐记录: {len(df_rec)} 条")

    df_rec['rec_date8'] = df_rec['recommendation_date'].apply(norm8)
    if start: df_rec = df_rec[df_rec['rec_date8']>=start]
    if end:   df_rec = df_rec[df_rec['rec_date8']<=end]
    df_rec['ts_code'] = df_rec['symbol'].apply(norm_code)
    df_rec['strategy_type'] = df_rec['strategy_type'].fillna('legacy')
    print(f"过滤后: {len(df_rec)} 条")

    if df_rec.empty:
        print("无记录")
        return

    # 2. 批量读日线数据
    qconn = sqlite3.connect(QUANT_DB)
    codes = df_rec['ts_code'].unique().tolist()
    placeholders = ','.join('?'*len(codes))

    # 计算日期范围（留足够余量）
    dates = df_rec['rec_date8'].dropna()
    d_min = dates.min()
    d_max = dates.max()
    d_start = (datetime.strptime(d_min,'%Y%m%d') - timedelta(days=3)).strftime('%Y%m%d')
    d_end   = (datetime.strptime(d_max,'%Y%m%d') + timedelta(days=hold_days*3+30)).strftime('%Y%m%d')

    print(f"批量读取日线: {len(codes)} 只股票, {d_start}~{d_end} ...")
    daily = pd.read_sql(
        f"SELECT ts_code, trade_date, open, close FROM stock_daily "
        f"WHERE ts_code IN ({placeholders}) AND trade_date>=? AND trade_date<=? "
        f"ORDER BY ts_code, trade_date",
        qconn, params=codes + [d_start, d_end]
    )
    qconn.close()
    print(f"日线数据: {len(daily)} 行")

    if daily.empty:
        print("无日线数据")
        return

    daily['trade_date'] = daily['trade_date'].astype(str)
    daily = daily.sort_values(['ts_code','trade_date'])

    # 3. 为每只股票建索引：trade_date -> (open, close)
    def make_date_idx(grp):
        return grp.set_index('trade_date')[['open','close']]

    stock_idx = {code: make_date_idx(g) for code, g in daily.groupby('ts_code')}

    def get_price_on_or_after(ts_code, date8, col='open'):
        idx = stock_idx.get(ts_code)
        if idx is None: return None, None
        avail = idx[idx.index >= date8]
        if avail.empty: return None, None
        td = avail.index[0]
        p = float(avail.loc[td, col])
        if p <= 0: p = float(avail.loc[td, 'close'])
        return td, p

    def nth_day_after(ts_code, buy_td, n):
        idx = stock_idx.get(ts_code)
        if idx is None: return buy_td
        avail = idx[idx.index > buy_td]
        if len(avail) < n: return avail.index[-1] if not avail.empty else buy_td
        return avail.index[n-1]

    def get_price_on_or_before(ts_code, date8, col='close'):
        idx = stock_idx.get(ts_code)
        if idx is None: return None, None
        avail = idx[idx.index <= date8]
        if avail.empty: return None, None
        td = avail.index[-1]
        return td, float(avail.loc[td, col])

    # 4. 逐条撮合（已无DB查询，速度快）
    trades, skipped = [], 0
    for _, row in df_rec.iterrows():
        ts   = row['ts_code']
        rec8 = row['rec_date8']
        if not rec8: skipped+=1; continue

        buy_d8 = (datetime.strptime(rec8,'%Y%m%d')+timedelta(days=1)).strftime('%Y%m%d')
        buy_td, buy_p = get_price_on_or_after(ts, buy_d8, 'open')
        if buy_p is None: skipped+=1; continue

        sell_d8 = nth_day_after(ts, buy_td, hold_days)
        sell_td, sell_p = get_price_on_or_before(ts, sell_d8, 'close')
        if sell_p is None: skipped+=1; continue

        gross = (sell_p - buy_p) / buy_p
        net   = gross - (BUY_FEE + SELL_FEE + STAMP)
        trades.append({
            'symbol': row['symbol'], 'ts_code': ts, 'name': str(row['name'] or ''),
            'rec_date': rec8, 'buy_date': buy_td, 'buy_price': round(buy_p,3),
            'sell_date': sell_td, 'sell_price': round(sell_p,3),
            'gross_pct': round(gross*100,4), 'net_pct': round(net*100,4),
            'score': round(float(row['recommendation_score'] or 0),2),
            'strategy': str(row['strategy_type']),
        })

    df = pd.DataFrame(trades)
    if df.empty:
        print(f"无有效交易（跳过 {skipped} 条）")
        return

    print(f"\n{'='*60}")
    print(f"回测结果（持有{hold_days}交易日，扣双边佣金+印花税）")
    print(f"{'='*60}")
    print(f"有效交易: {len(df)} 笔  跳过: {skipped}")
    win  = (df.net_pct>0).sum()
    loss = (df.net_pct<0).sum()
    flat = len(df)-win-loss
    print(f"胜率:     {win/len(df)*100:.1f}%  ({win}胜/{loss}负/{flat}平)")
    print(f"平均收益: {df.net_pct.mean():.2f}%")
    print(f"中位数:   {df.net_pct.median():.2f}%")
    print(f"最大盈利: {df.net_pct.max():.2f}%")
    print(f"最大亏损: {df.net_pct.min():.2f}%")
    gw = df[df.net_pct>0].net_pct.sum()
    gl = abs(df[df.net_pct<0].net_pct.sum())
    print(f"盈亏比PF: {gw/gl:.2f}" if gl>0 else "盈亏比PF: inf")
    print(f"累计收益(等权): {df.net_pct.sum():.2f}%")

    # 月度
    df['month'] = pd.to_datetime(df.rec_date, format='%Y%m%d').dt.to_period('M')
    m = df.groupby('month').agg(月均收益=('net_pct','mean'), 笔数=('net_pct','count'))
    print(f"\n月度明细:")
    print(m.to_string())

    # 评分分档
    if df['score'].nunique()>2:
        df['score_bin'] = pd.cut(df['score'], bins=3, labels=['低','中','高'])
        sg = df.groupby('score_bin', observed=True).agg(平均收益=('net_pct','mean'), 笔数=('net_pct','count'))
        print(f"\n评分分档:")
        print(sg.to_string())

    # 策略对比（若有多种）
    if df['strategy'].nunique()>1:
        st = df.groupby('strategy').agg(平均收益=('net_pct','mean'), 笔数=('net_pct','count'),
                                        胜率=('net_pct', lambda x:(x>0).mean()))
        print(f"\n策略对比:")
        print(st.to_string())

    # 保存
    out = ROOT/'results'
    out.mkdir(exist_ok=True)
    ts_now = datetime.now().strftime('%Y%m%d_%H%M%S')
    path = out/f'backtest_fast_{ts_now}.csv'
    df.to_csv(path, index=False, encoding='utf-8-sig')
    print(f"\n已保存: {path}")
    return df


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--hold',      type=int,   default=5)
    ap.add_argument('--min-score', type=float, default=0.0)
    ap.add_argument('--start',     default=None)
    ap.add_argument('--end',       default=None)
    a = ap.parse_args()
    run(hold_days=a.hold, min_score=a.min_score, start=a.start, end=a.end)
