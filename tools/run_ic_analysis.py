# -*- coding: utf-8 -*-
"""
IC 分析脚本（基于 factor_values + stock_daily 实际数据）

用法:
  python tools/run_ic_analysis.py
  python tools/run_ic_analysis.py --period 5 --start 20251101
"""

import argparse
import sqlite3
import sys
from pathlib import Path
from datetime import datetime, timedelta

import pandas as pd
import numpy as np
from scipy.stats import spearmanr

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

QUANT_DB = str(ROOT / "data" / "database" / "quant_system.db")

CURRENT_WEIGHTS = {
    'trend_score': 0.40, 'momentum_score': 0.40, 'volume_score': 0.10,
    'fundamental_score': 0.05, 'pullback_score': 0.05,
}
ORIG_WEIGHTS = {
    'trend_score': 0.45, 'momentum_score': 0.50, 'volume_score': 0.00,
    'fundamental_score': 0.00, 'pullback_score': 0.05,
}
ALL_FACTORS = list(CURRENT_WEIGHTS.keys())


def load_factor_returns(conn, factor_names, start, end, future_days):
    placeholders = ','.join('?' * len(factor_names))
    fv = pd.read_sql(
        f"SELECT ts_code, trade_date, factor_name, factor_value FROM factor_values "
        f"WHERE factor_name IN ({placeholders}) AND trade_date>=? AND trade_date<=?",
        conn, params=factor_names + [start, end],
    )
    if fv.empty:
        return pd.DataFrame()
    fv_wide = fv.pivot_table(index=['ts_code','trade_date'], columns='factor_name',
                              values='factor_value', aggfunc='last').reset_index()
    fv_wide.columns.name = None

    price_end = (datetime.strptime(end,'%Y%m%d') + timedelta(days=future_days*2+30)).strftime('%Y%m%d')
    prices = pd.read_sql(
        "SELECT ts_code, trade_date, close FROM stock_daily "
        "WHERE trade_date>=? AND trade_date<=? ORDER BY ts_code, trade_date",
        conn, params=[start, price_end],
    )
    if prices.empty:
        return pd.DataFrame()
    prices['trade_date'] = prices['trade_date'].astype(str)
    prices['future_return'] = prices.groupby('ts_code')['close'].transform(
        lambda x: x.shift(-future_days) / x - 1
    )
    prices = prices[['ts_code','trade_date','future_return']].dropna()
    fv_wide['trade_date'] = fv_wide['trade_date'].astype(str)
    return pd.merge(fv_wide, prices, on=['ts_code','trade_date'], how='inner')


def calc_ic_series(df, factor_col):
    records = []
    for date, grp in df.groupby('trade_date'):
        sub = grp[['future_return', factor_col]].dropna()
        if len(sub) < 30:
            continue
        ic, _ = spearmanr(sub[factor_col], sub['future_return'])
        if not np.isnan(ic):
            records.append({'trade_date': date, 'ic': ic, 'n': len(sub)})
    if not records:
        return pd.Series(dtype=float, name='ic')
    return pd.DataFrame(records).set_index('trade_date')['ic']


def ic_stats(ic_series):
    if ic_series.empty:
        return dict(ic_mean=None, ic_std=None, ic_ir=None, t_stat=None,
                    ic_positive_ratio=None, ic_gt5_ratio=None, n_dates=0)
    m, s, n = ic_series.mean(), ic_series.std(), len(ic_series)
    ir = m/s if s > 0 else 0
    t  = m/(s/np.sqrt(n)) if s > 0 else 0
    return dict(
        ic_mean=round(m,5), ic_std=round(s,5), ic_ir=round(ir,4),
        t_stat=round(t,4), ic_positive_ratio=round((ic_series>0).mean(),3),
        ic_gt5_ratio=round((ic_series.abs()>0.05).mean(),3), n_dates=n,
    )


def layer_return(df, factor_col, n_layers=5):
    records = []
    for date, grp in df.groupby('trade_date'):
        sub = grp[['future_return', factor_col]].dropna()
        if len(sub) < n_layers * 5:
            continue
        sub = sub.copy()
        try:
            bins = pd.qcut(sub[factor_col], q=n_layers, duplicates='drop')
            if bins.nunique() < 2:
                continue
            sub['layer'] = bins
            layer_ret = sub.groupby('layer', observed=True)['future_return'].mean().sort_index()
            layer_ret.index = [f"L{i+1}" for i in range(len(layer_ret))]
            records.append(layer_ret)
        except Exception:
            continue
    if not records:
        return pd.DataFrame()
    return pd.DataFrame(records).mean().to_frame(name='avg_return')


def run_ic_analysis(periods=None, start=None, end=None, n_layers=5):
    if periods is None:
        periods = [3, 5, 10, 20]
    conn = sqlite3.connect(QUANT_DB)
    if end is None:
        end = '20260327'
    if start is None:
        start = (datetime.strptime(end,'%Y%m%d') - timedelta(days=180)).strftime('%Y%m%d')

    print(f"\n{'='*70}")
    print(f"IC 分析   时间: {start}~{end}   周期: {periods}日")
    print(f"{'='*70}")

    summary_rows = []
    for period in periods:
        print(f"\n--- 预测周期 {period} 日 ---")
        df = load_factor_returns(conn, ALL_FACTORS, start, end, period)
        if df.empty:
            print("  无数据，跳过")
            continue
        print(f"  样本: {len(df)} 行  截面日期: {df['trade_date'].nunique()}")
        for fac in ALL_FACTORS:
            if fac not in df.columns:
                continue
            stats = ic_stats(calc_ic_series(df, fac))
            row = {'factor': fac, 'period': period}
            row.update(stats)
            summary_rows.append(row)
            print(f"  {fac:<25} IC={stats['ic_mean']:+.4f}  IR={stats['ic_ir']:+.3f}  "
                  f"t={stats['t_stat']:+.2f}  IC+%={stats['ic_positive_ratio']:.0%}  "
                  f"N={stats['n_dates']}")

    if not summary_rows:
        print("\n无有效 IC 数据。")
        conn.close()
        return

    summary = pd.DataFrame(summary_rows)
    BASE = 5 if 5 in periods else periods[0]

    # 分层收益
    print(f"\n{'='*70}")
    print(f"分层收益（基准={BASE}日，{n_layers}层）")
    print(f"{'='*70}")
    df_base = load_factor_returns(conn, ALL_FACTORS, start, end, BASE)
    if not df_base.empty:
        for fac in ALL_FACTORS:
            if fac not in df_base.columns:
                continue
            lr = layer_return(df_base, fac, n_layers)
            if not lr.empty:
                spread = float(lr['avg_return'].iloc[-1]) - float(lr['avg_return'].iloc[0])
                print(f"  {fac:<25}  L1={lr['avg_return'].iloc[0]*100:+.3f}%  "
                      f"L{n_layers}={lr['avg_return'].iloc[-1]*100:+.3f}%  "
                      f"Spread={spread*100:+.3f}%")

    # 权重建议
    print(f"\n{'='*70}")
    print(f"权重优化建议（IC_IR 加权，周期={BASE}日）")
    print(f"{'='*70}")
    base_ic = summary[summary['period']==BASE].copy()
    base_ic = base_ic[base_ic['factor'].isin(ALL_FACTORS)].set_index('factor')
    base_ic['abs_ir'] = base_ic['ic_ir'].abs()
    total_ir = base_ic['abs_ir'].sum()
    base_ic['suggested_weight'] = (base_ic['abs_ir']/total_ir).round(4) if total_ir>0 else 1/len(base_ic)

    print(f"\n  {'因子':<23} {'当前权重':^8} {'原始权重':^8} {'建议权重':^8} {'IC均值':^9} {'IC_IR':^7} 变化")
    print("  " + "-"*68)
    for fac in ALL_FACTORS:
        if fac not in base_ic.index:
            continue
        r = base_ic.loc[fac]
        cw, ow, sw = CURRENT_WEIGHTS.get(fac,0), ORIG_WEIGHTS.get(fac,0), r['suggested_weight']
        flag = '▲' if sw-cw>0.02 else ('▼' if sw-cw<-0.02 else '─')
        print(f"  {fac:<23} {cw:^8.0%} {ow:^8.0%} {sw:^8.0%} {r['ic_mean']:^+9.4f} {r['ic_ir']:^+7.3f} {flag}")

    # 加权IC对比
    sug = base_ic['suggested_weight'].to_dict()
    w_cur = sum(CURRENT_WEIGHTS.get(f,0)*base_ic.loc[f,'ic_mean'] for f in ALL_FACTORS if f in base_ic.index)
    w_sug = sum(sug.get(f,0)*base_ic.loc[f,'ic_mean'] for f in ALL_FACTORS if f in base_ic.index)
    print(f"\n  当前权重加权IC: {w_cur:+.5f}")
    print(f"  建议权重加权IC: {w_sug:+.5f}")
    if abs(w_cur)>1e-6:
        print(f"  预期提升:      {(w_sug-w_cur)/abs(w_cur)*100:+.1f}%")

    # 保存
    out = ROOT / 'results'
    out.mkdir(exist_ok=True)
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    csv_path = out / f'ic_analysis_{ts}.csv'
    summary.to_csv(csv_path, index=False, encoding='utf-8-sig')
    print(f"\n详情已保存: {csv_path}")
    conn.close()


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--periods', nargs='+', type=int, default=[3,5,10,20])
    ap.add_argument('--start', default=None)
    ap.add_argument('--end',   default=None)
    ap.add_argument('--layers',type=int, default=5)
    a = ap.parse_args()
    run_ic_analysis(periods=a.periods, start=a.start, end=a.end, n_layers=a.layers)
