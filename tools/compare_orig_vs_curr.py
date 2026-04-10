# -*- coding: utf-8 -*-
"""
同池对比回测：优化后权重 vs 原始权重
"""

import sqlite3
from pathlib import Path
from datetime import datetime, timedelta
import pandas as pd
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
DB = str(ROOT / 'data' / 'database' / 'quant_system.db')

FACTORS = ['trend_score','momentum_score','volume_score','fundamental_score','pullback_score']

W_ORIG = {'trend_score':0.45,'momentum_score':0.50,'volume_score':0.00,'fundamental_score':0.00,'pullback_score':0.05}
W_CURR = {'trend_score':0.40,'momentum_score':0.40,'volume_score':0.10,'fundamental_score':0.05,'pullback_score':0.05}


def load_data(start='20251117', end='20260327', future_days=5):
    conn = sqlite3.connect(DB)
    ph = ','.join('?'*len(FACTORS))
    fv = pd.read_sql(
        f"SELECT ts_code, trade_date, factor_name, factor_value FROM factor_values WHERE factor_name IN ({ph}) AND trade_date>=? AND trade_date<=?",
        conn, params=FACTORS+[start,end]
    )
    px_end = (datetime.strptime(end,'%Y%m%d') + timedelta(days=future_days*3+30)).strftime('%Y%m%d')
    px = pd.read_sql(
        "SELECT ts_code, trade_date, close FROM stock_daily WHERE trade_date>=? AND trade_date<=?",
        conn, params=[start, px_end]
    )
    conn.close()

    fv_w = fv.pivot_table(index=['ts_code','trade_date'], columns='factor_name', values='factor_value', aggfunc='last').reset_index()
    fv_w.columns.name = None

    px['trade_date'] = px['trade_date'].astype(str)
    px = px.sort_values(['ts_code','trade_date'])
    px['future_ret'] = px.groupby('ts_code')['close'].transform(lambda x: x.shift(-future_days)/x - 1)
    px = px[['ts_code','trade_date','future_ret']].dropna()

    fv_w['trade_date'] = fv_w['trade_date'].astype(str)
    return pd.merge(fv_w, px, on=['ts_code','trade_date'], how='inner')


def score(df, w):
    s = np.zeros(len(df))
    for f, wt in w.items():
        s += df[f].fillna(0).values * wt
    return s


def run(df, top_n=30):
    rows = []
    for d, g in df.groupby('trade_date'):
        g = g.dropna(subset=FACTORS+['future_ret'])
        if len(g) < max(50, top_n):
            continue
        g = g.copy()
        g['s_orig'] = score(g, W_ORIG)
        g['s_curr'] = score(g, W_CURR)
        rows.append({
            'trade_date': d,
            'ret_orig': g.nlargest(top_n, 's_orig')['future_ret'].mean(),
            'ret_curr': g.nlargest(top_n, 's_curr')['future_ret'].mean(),
        })
    return pd.DataFrame(rows).sort_values('trade_date')


def stats(s):
    m = s.mean(); sd = s.std(); win = (s>0).mean()
    sharpe = (m/sd*np.sqrt(252/5)) if sd>0 else 0
    cum = (1+s).prod()-1
    return m, sd, win, sharpe, cum


if __name__ == '__main__':
    df = load_data()
    bt = run(df, top_n=30)
    if bt.empty:
        print('无有效样本')
        raise SystemExit

    mo, sdo, wino, sho, cumo = stats(bt['ret_orig'])
    mc, sdc, winc, shc, cumc = stats(bt['ret_curr'])

    print('\n=== 同池对比回测（Top30, 持有5日）===')
    print(f"样本天数: {len(bt)}")
    print(f"原策略 平均收益: {mo*100:+.3f}%  胜率:{wino*100:.1f}%  夏普:{sho:+.2f}  累计:{cumo*100:+.2f}%")
    print(f"新策略 平均收益: {mc*100:+.3f}%  胜率:{winc*100:.1f}%  夏普:{shc:+.2f}  累计:{cumc*100:+.2f}%")
    print(f"平均收益差(新-原): {(mc-mo)*100:+.3f}%")

    out = ROOT / 'results'
    out.mkdir(exist_ok=True)
    fp = out / f"compare_orig_vs_curr_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    bt.to_csv(fp, index=False, encoding='utf-8-sig')
    print(f"明细已保存: {fp}")
