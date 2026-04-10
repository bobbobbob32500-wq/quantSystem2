# -*- coding: utf-8 -*-
"""快速诊断：确认数据可读性和回测基本结果"""
import sqlite3, sys
from pathlib import Path
import pandas as pd
import numpy as np
from datetime import timedelta, datetime

ROOT = Path(__file__).resolve().parents[1]
QUANT_DB = str(ROOT / 'data/database/quant_system.db')
HIST_DB  = str(ROOT / 'data/history_recommendation.db')

def norm_code(s):
    s = str(s).strip()
    if '.' in s: return s.upper()
    return f"{s}.SH" if s[:1] in ('6','9') else f"{s}.SZ"

def norm8(s):
    d = ''.join(c for c in str(s) if c.isdigit())
    return d[:8] if len(d)>=8 else ''

print("1. 读推荐记录...")
hconn = sqlite3.connect(HIST_DB)
rec = pd.read_sql("SELECT symbol,name,recommendation_date,recommendation_score,strategy_type FROM recommendations", hconn)
hconn.close()
print(f"   {len(rec)} 条，日期 {rec.recommendation_date.min()} ~ {rec.recommendation_date.max()}")

rec['rec8'] = rec['recommendation_date'].apply(norm8)
rec['ts_code'] = rec['symbol'].apply(norm_code)
rec['score'] = pd.to_numeric(rec['recommendation_score'], errors='coerce').fillna(0)

print("\n2. 读日线数据（仅推荐股票）...")
codes = rec['ts_code'].unique().tolist()
print(f"   涉及股票: {len(codes)} 只")

qconn = sqlite3.connect(QUANT_DB)
dates = rec['rec8'].dropna()
d_min = dates.min()
d_max = dates.max()
d_s = (datetime.strptime(d_min,'%Y%m%d')-timedelta(days=3)).strftime('%Y%m%d')
d_e = (datetime.strptime(d_max,'%Y%m%d')+timedelta(days=60)).strftime('%Y%m%d')

ph = ','.join('?'*len(codes))
daily = pd.read_sql(
    f"SELECT ts_code, trade_date, open, close FROM stock_daily WHERE ts_code IN ({ph}) AND trade_date>=? AND trade_date<=? ORDER BY ts_code, trade_date",
    qconn, params=codes+[d_s, d_e]
)
qconn.close()
print(f"   日线行数: {len(daily)}, 股票数: {daily.ts_code.nunique()}")

print("\n3. 批量回测撮合（5交易日持有）...")
daily['trade_date'] = daily['trade_date'].astype(str)
daily = daily.sort_values(['ts_code','trade_date'])
stock_idx = {c: g.set_index('trade_date')[['open','close']] for c,g in daily.groupby('ts_code')}

HOLD = 5
COST = 0.0003+0.0003+0.001
trades = []
skipped = 0

for _, row in rec.iterrows():
    ts = row['ts_code']
    rec8 = row['rec8']
    if not rec8 or ts not in stock_idx:
        skipped += 1; continue
    idx = stock_idx[ts]
    buy_d8 = (datetime.strptime(rec8,'%Y%m%d')+timedelta(days=1)).strftime('%Y%m%d')
    avail_buy = idx[idx.index >= buy_d8]
    if avail_buy.empty: skipped+=1; continue
    buy_td = avail_buy.index[0]
    buy_p  = float(avail_buy.iloc[0]['open'])
    if buy_p<=0: buy_p = float(avail_buy.iloc[0]['close'])
    if buy_p<=0: skipped+=1; continue
    avail_sell = idx[idx.index > buy_td]
    if avail_sell.empty: skipped+=1; continue
    sell_td = avail_sell.index[min(HOLD-1, len(avail_sell)-1)]
    sell_p  = float(avail_sell.iloc[min(HOLD-1, len(avail_sell)-1)]['close'])
    if sell_p<=0: skipped+=1; continue
    net = (sell_p-buy_p)/buy_p - COST
    trades.append({'ts_code':ts,'rec8':rec8,'score':row['score'],
                   'buy_td':buy_td,'buy_p':buy_p,'sell_td':sell_td,'sell_p':sell_p,
                   'net_pct':round(net*100,4)})

df = pd.DataFrame(trades)
print(f"   有效: {len(df)} 笔, 跳过: {skipped}")

if df.empty:
    print("无交易")
    sys.exit(0)

win  = (df.net_pct>0).sum()
loss = (df.net_pct<0).sum()
flat = len(df)-win-loss
gw = df[df.net_pct>0].net_pct.sum()
gl = abs(df[df.net_pct<0].net_pct.sum())

print(f"\n===== 回测结果（持有{HOLD}日）=====")
print(f"胜率:   {win/len(df)*100:.1f}%  ({win}胜/{loss}负/{flat}平)")
print(f"均值:   {df.net_pct.mean():.2f}%")
print(f"中位数: {df.net_pct.median():.2f}%")
print(f"最大:   {df.net_pct.max():.2f}%")
print(f"最小:   {df.net_pct.min():.2f}%")
print(f"PF盈亏比: {gw/gl:.2f}" if gl>0 else "PF: inf")

df['month'] = pd.to_datetime(df.rec8, format='%Y%m%d').dt.to_period('M')
m = df.groupby('month').agg(月均收益=('net_pct','mean'), 笔数=('net_pct','count'))
print(f"\n月度:"); print(m.to_string())

if df['score'].nunique()>2:
    df['bin'] = pd.cut(df.score, bins=3, labels=['低','中','高'])
    sg = df.groupby('bin',observed=True).agg(均值=('net_pct','mean'),笔数=('net_pct','count'))
    print(f"\n评分档位:"); print(sg.to_string())

out = ROOT/'results'
out.mkdir(exist_ok=True)
ts_now = datetime.now().strftime('%Y%m%d_%H%M%S')
path = out/f'bt_{ts_now}.csv'
df.to_csv(path, index=False, encoding='utf-8-sig')
print(f"\n已保存: {path}")
