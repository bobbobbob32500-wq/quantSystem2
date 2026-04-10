# -*- coding: utf-8 -*-
"""
权重A/B对比回测 + IC分析 + 自动参数调整

权重方案：
  A (保守): trend=0.48, momentum=0.42, volume=0.02, fundamental=0.00, pullback=0.08
  B (折中): trend=0.45, momentum=0.40, volume=0.03, fundamental=0.02, pullback=0.10
  原始:    trend=0.45, momentum=0.50, volume=0.00, fundamental=0.00, pullback=0.05
  当前:    trend=0.40, momentum=0.40, volume=0.10, fundamental=0.05, pullback=0.05
"""

import sqlite3
from pathlib import Path
from datetime import datetime, timedelta
import pandas as pd
import numpy as np
from scipy.stats import spearmanr

ROOT = Path(__file__).resolve().parents[1]
DB = str(ROOT / 'data' / 'database' / 'quant_system.db')

FACTORS = ['trend_score','momentum_score','volume_score','fundamental_score','pullback_score']

WEIGHTS = {
    'orig': {'trend_score':0.45,'momentum_score':0.50,'volume_score':0.00,'fundamental_score':0.00,'pullback_score':0.05},
    'curr': {'trend_score':0.40,'momentum_score':0.40,'volume_score':0.10,'fundamental_score':0.05,'pullback_score':0.05},
    'A':    {'trend_score':0.48,'momentum_score':0.42,'volume_score':0.02,'fundamental_score':0.00,'pullback_score':0.08},
    'B':    {'trend_score':0.45,'momentum_score':0.40,'volume_score':0.03,'fundamental_score':0.02,'pullback_score':0.10},
}


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


def backtest(df, weights_dict, top_n=30):
    """对所有权重方案做回测"""
    results = {}
    for name, w in weights_dict.items():
        rows = []
        for d, g in df.groupby('trade_date'):
            g = g.dropna(subset=FACTORS+['future_ret'])
            if len(g) < max(50, top_n):
                continue
            g = g.copy()
            g['score'] = score(g, w)
            ret = g.nlargest(top_n, 'score')['future_ret'].mean()
            rows.append({'trade_date': d, 'ret': ret})
        if rows:
            results[name] = pd.DataFrame(rows).sort_values('trade_date')
    return results


def ic_analysis(df, weights_dict, future_days=5):
    """计算各权重方案的IC"""
    ic_results = {}
    for name, w in weights_dict.items():
        ics = []
        for d, g in df.groupby('trade_date'):
            g = g.dropna(subset=FACTORS+['future_ret'])
            if len(g) < 30:
                continue
            g = g.copy()
            g['score'] = score(g, w)
            ic, _ = spearmanr(g['score'], g['future_ret'])
            if not np.isnan(ic):
                ics.append(ic)
        if ics:
            ic_s = pd.Series(ics)
            ic_results[name] = {
                'ic_mean': ic_s.mean(),
                'ic_std': ic_s.std(),
                'ic_ir': ic_s.mean() / ic_s.std() if ic_s.std() > 0 else 0,
                'ic_positive_ratio': (ic_s > 0).mean(),
                'n_dates': len(ics),
            }
    return ic_results


def stats(s):
    m = s.mean()
    sd = s.std()
    win = (s > 0).mean()
    sharpe = (m / sd * np.sqrt(252/5)) if sd > 0 else 0
    cum = (1 + s).prod() - 1
    dd = (s.cumsum().expanding().max() - s.cumsum()).max()
    return m, sd, win, sharpe, cum, dd


def find_best(bt_results, ic_results):
    """综合评分找最优方案"""
    scores = {}
    for name in bt_results.keys():
        bt = bt_results[name]
        ic = ic_results.get(name, {})
        
        m, sd, win, sharpe, cum, dd = stats(bt['ret'])
        
        # 综合评分（权重：收益30% + 胜率20% + 夏普20% + IC_IR 20% + 回撤10%）
        ret_score = (m + 0.01) / 0.01 * 30 if m > -0.01 else max(0, 30 + m*1000)
        win_score = win * 100 * 0.2
        sharpe_score = max(0, (sharpe + 1) * 10) * 0.2
        ic_score = max(0, ic.get('ic_ir', 0) * 50) * 0.2
        dd_score = max(0, (0.1 - dd) / 0.1 * 10) * 0.1
        
        total = ret_score + win_score + sharpe_score + ic_score + dd_score
        scores[name] = {
            'avg_ret': m, 'std': sd, 'win': win, 'sharpe': sharpe, 'cum': cum, 'dd': dd,
            'ic_mean': ic.get('ic_mean', 0), 'ic_ir': ic.get('ic_ir', 0),
            'score': total,
        }
    
    best = max(scores.items(), key=lambda x: x[1]['score'])
    return best[0], scores


if __name__ == '__main__':
    print("\n" + "="*70)
    print("权重A/B对比回测 + IC分析")
    print("="*70)
    
    df = load_data(start='20251117', end='20260327', future_days=5)
    print(f"样本数据: {len(df)} 行")
    
    # 回测
    print("\n执行回测...")
    bt_results = backtest(df, WEIGHTS, top_n=30)
    
    # IC分析
    print("执行IC分析...")
    ic_results = ic_analysis(df, WEIGHTS, future_days=5)
    
    # 输出对比表
    print("\n" + "="*70)
    print("对比结果")
    print("="*70)
    print(f"{'方案':<8} {'平均收益':>10} {'胜率':>8} {'夏普':>8} {'累计':>10} {'最大回撤':>10} {'IC均值':>10} {'IC_IR':>8}")
    print("-"*70)
    
    best_name, scores = find_best(bt_results, ic_results)
    
    for name in ['orig', 'curr', 'A', 'B']:
        if name not in scores:
            continue
        s = scores[name]
        print(f"{name:<8} {s['avg_ret']*100:>+9.3f}% {s['win']*100:>7.1f}% {s['sharpe']:>+7.2f} {s['cum']*100:>+9.2f}% {s['dd']*100:>9.2f}% {s['ic_mean']:>+9.4f} {s['ic_ir']:>+7.3f}")
    
    print("\n" + "="*70)
    print(f"最优方案: {best_name.upper()}")
    print("="*70)
    s = scores[best_name]
    print(f"平均收益: {s['avg_ret']*100:+.3f}%")
    print(f"胜率: {s['win']*100:.1f}%")
    print(f"夏普: {s['sharpe']:+.2f}")
    print(f"累计: {s['cum']*100:+.2f}%")
    print(f"最大回撤: {s['dd']*100:.2f}%")
    print(f"IC均值: {s['ic_mean']:+.4f}")
    print(f"IC_IR: {s['ic_ir']:+.3f}")
    
    # 自动调整参数
    print("\n" + "="*70)
    print("自动调整参数")
    print("="*70)
    
    best_weights = WEIGHTS[best_name]
    print(f"将参数调整为方案 {best_name.upper()}:")
    for f, w in best_weights.items():
        print(f"  {f}: {w:.2f}")
    
    # 更新配置文件
    config_path = ROOT / 'config' / 'signal_config.yaml'
    if config_path.exists():
        import yaml
        with open(config_path, 'r', encoding='utf-8') as f:
            cfg = yaml.safe_load(f) or {}
        
        if 'stock_selection' not in cfg:
            cfg['stock_selection'] = {}
        
        cfg['stock_selection']['legacy_trend_factor_weight'] = best_weights['trend_score']
        cfg['stock_selection']['legacy_momentum_factor_weight'] = best_weights['momentum_score']
        cfg['stock_selection']['legacy_volume_factor_weight'] = best_weights['volume_score']
        cfg['stock_selection']['legacy_fundamental_factor_weight'] = best_weights['fundamental_score']
        cfg['stock_selection']['legacy_pullback_factor_weight'] = best_weights['pullback_score']
        
        with open(config_path, 'w', encoding='utf-8') as f:
            yaml.dump(cfg, f, allow_unicode=True, default_flow_style=False)
        print(f"\n[OK] 已更新配置文件: {config_path}")
    
    print("\n" + "="*70)
    print("参数调整完成！")
    print("="*70)
