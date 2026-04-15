#!/usr/bin/env python
# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse, json, sqlite3, statistics, sys
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / 'tools') not in sys.path:
    sys.path.insert(0, str(ROOT / 'tools'))

from scripts.analyze_secondary_launch_intraday import _load_session
from tools.analyze_secondary_launch_unified_truth import _fetch_daily_features
from src.modules.backtest.history_recommendation_db import HistoryRecommendationDB
from src.modules.secondary_launch_intraday import (
    _build_breakout_signal, _build_layered_execution_signal, _build_pullback_signal,
    _prepare_minute_frame, _resolve_breakout_threshold, _resolve_market_gate,
)


def _to_day(v: Any) -> str:
    s = str(v).strip()
    return s.replace('-', '')[:8] if s else ''


def _metric(vals):
    x = [float(v) for v in vals if v is not None]
    if not x:
        return dict(count=0, win_rate=0.0, avg_return_pct=0.0, median_return_pct=0.0, best_return_pct=0.0, worst_return_pct=0.0, profit_factor=0.0)
    pos = sum(v for v in x if v > 0)
    neg = -sum(v for v in x if v < 0)
    return dict(
        count=len(x),
        win_rate=round(sum(v > 0 for v in x) / len(x) * 100, 2),
        avg_return_pct=round(sum(x) / len(x) * 100, 2),
        median_return_pct=round(statistics.median(x) * 100, 2),
        best_return_pct=round(max(x) * 100, 2),
        worst_return_pct=round(min(x) * 100, 2),
        profit_factor=round((pos / neg) if neg > 1e-12 else 0.0, 2),
    )


def _bucket(t: str) -> str:
    return '上午' if t and t < '11:30:00' else '午后'


def _candidate(row, feat):
    d = {
        'symbol': row['ts_code'], 'name': row.get('name', ''),
        'score': float(row.get('signal_score', 0.0) or 0.0),
        'signal_score': float(row.get('signal_score', 0.0) or 0.0),
        'rank': int(row.get('rank', 0) or 0),
        'pool_type': 'core' if int(row.get('rank', 0) or 0) == 1 else 'reserve',
        'industry': str(row.get('industry', '') or ''), 'strategy_profile': 'secondary_launch',
    }
    d.update(feat or {})
    return d


def _exit_map(conn, symbol, signal_date, entry_price):
    rows = list(conn.execute("SELECT trade_date, close FROM stock_daily WHERE ts_code=? AND trade_date>=? ORDER BY trade_date ASC", (symbol, signal_date)))
    future = [r for r in rows if str(r['trade_date']) > signal_date]
    out = {}
    for i, lab in enumerate(['T+1', 'T+2', 'T+3'], start=1):
        out[f'{lab}_close_ret'] = (float(future[i-1]['close']) / entry_price - 1.0) if len(future) >= i and future[i-1]['close'] is not None else None
    return out


def _resolve_full(row, frame, feat):
    cand = _candidate(row, feat)
    market_confirm = {'market_score': 50.0, 'trend': 'neutral', 'index_below_vwap': False}
    for idx in range(len(frame)):
        now = pd.Timestamp(frame.iloc[idx]['trade_time']).to_pydatetime()
        window = frame.iloc[: idx + 1].copy()
        prepared = _prepare_minute_frame(window)
        if prepared.empty:
            continue
        quote = {'price': float(prepared.iloc[-1]['close'])}
        p = _build_pullback_signal(prepared, cand, quote, now)
        if p.signal and float(p.confidence or 0.0) >= 0.60:
            return dict(entry_time=now.strftime('%H:%M:%S'), entry_price=float(window.iloc[-1]['close']), signal_type=str(p.signal_type or ''), confidence=float(p.confidence or 0.0), execution_tier='full_confirm')
        b = _build_breakout_signal(prepared, cand, quote, now, market_confirm=market_confirm)
        th = _resolve_breakout_threshold(now, _resolve_market_gate(market_confirm))
        if b.signal and float(b.confidence or 0.0) >= th:
            return dict(entry_time=now.strftime('%H:%M:%S'), entry_price=float(window.iloc[-1]['close']), signal_type=str(b.signal_type or ''), confidence=float(b.confidence or 0.0), execution_tier='full_confirm')
    return None


def _resolve_layered(row, frame, feat):
    cand = _candidate(row, feat)
    market_confirm = {'market_score': 50.0, 'trend': 'neutral', 'index_below_vwap': False}
    industry_confirm = {'score': 50.0, 'level': 'neutral', 'industry': cand.get('industry') or '未知'}
    for idx in range(len(frame)):
        now = pd.Timestamp(frame.iloc[idx]['trade_time']).to_pydatetime()
        window = frame.iloc[: idx + 1].copy()
        prepared = _prepare_minute_frame(window)
        if prepared.empty:
            continue
        sig = _build_layered_execution_signal(prepared, cand, {'price': float(prepared.iloc[-1]['close'])}, now, industry_confirm, market_confirm)
        if sig.signal:
            det = dict(sig.details or {})
            return dict(entry_time=now.strftime('%H:%M:%S'), entry_price=float(window.iloc[-1]['close']), signal_type=str(sig.signal_type or ''), confidence=float(sig.confidence or 0.0), execution_tier=str(det.get('execution_tier', '')), execution_note=str(det.get('execution_note', '')))
    return None


def _sum_group(rows, key):
    out = []
    for k in sorted({r.get(key) for r in rows}):
        sub = [r for r in rows if r.get(key) == k]
        out.append({key: k, 'sample_count': len(sub), 'T+2_close': _metric([r.get('T+2_close_ret') for r in sub])})
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--signals-csv', default='results/secondary_launch_v3_signals_FINAL.csv')
    ap.add_argument('--trades-csv', default='results/secondary_launch_v3_trades_20260402_135420.csv')
    ap.add_argument('--minute-db', default='data/history_recommendation.db')
    ap.add_argument('--daily-db', default='data/database/quant_system.db')
    args = ap.parse_args()

    sig = pd.read_csv(ROOT / args.signals_csv)
    tr = pd.read_csv(ROOT / args.trades_csv)
    minute_db = HistoryRecommendationDB(str(ROOT / args.minute_db))
    conn = sqlite3.connect(str(ROOT / args.daily_db)); conn.row_factory = sqlite3.Row

    rows = [dict(signal_date=_to_day(r.get('signal_date')), ts_code=str(r.get('ts_code', '') or '').strip().upper(), name=str(r.get('name', '') or ''), rank=int(r.get('rank') or 0), signal_score=float(r.get('signal_score', 0.0) or 0.0), rs20=float(r.get('rs20', 0.0) or 0.0)) for _, r in sig.iterrows()]
    no_confirm = [float(x) for x in pd.to_numeric(tr['net_ret'], errors='coerce').dropna().tolist()]
    full_entries, layered_entries = [], []

    for row in rows:
        frame = _load_session(minute_db, row['ts_code'], row['signal_date'])
        if frame.empty:
            continue
        feat = _fetch_daily_features(conn, row['ts_code'], row['signal_date'])
        x = _resolve_full(row, frame, feat)
        if x:
            full_entries.append({**row, **x, 'time_bucket': _bucket(x['entry_time']), **_exit_map(conn, row['ts_code'], row['signal_date'], x['entry_price'])})
        y = _resolve_layered(row, frame, feat)
        if y:
            layered_entries.append({**row, **y, 'time_bucket': _bucket(y['entry_time']), **_exit_map(conn, row['ts_code'], row['signal_date'], y['entry_price'])})

    conn.close()
    sample_count = len(rows)
    payload = {
        'generated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'sample_count': sample_count,
        'hold_reference': 'T+2_close',
        'modes': {
            'no_confirm': {'description': '无确认', 'trade_count': len(no_confirm), 'entry_rate_pct': round(len(no_confirm) / sample_count * 100, 2), 'metrics': _metric(no_confirm)},
            'full_confirm': {'description': '全确认', 'trade_count': len(full_entries), 'entry_rate_pct': round(len(full_entries) / sample_count * 100, 2), 'metrics': _metric([r.get('T+2_close_ret') for r in full_entries]), 'by_rank': _sum_group(full_entries, 'rank'), 'by_time_bucket': _sum_group(full_entries, 'time_bucket')},
            'layered_confirm': {'description': '分层确认', 'trade_count': len(layered_entries), 'entry_rate_pct': round(len(layered_entries) / sample_count * 100, 2), 'metrics': _metric([r.get('T+2_close_ret') for r in layered_entries]), 'by_rank': _sum_group(layered_entries, 'rank'), 'by_time_bucket': _sum_group(layered_entries, 'time_bucket'), 'by_execution_tier': _sum_group(layered_entries, 'execution_tier')},
        },
        'full_confirm_entries': full_entries,
        'layered_confirm_entries': layered_entries,
    }

    a, b, c = payload['modes']['no_confirm'], payload['modes']['full_confirm'], payload['modes']['layered_confirm']
    lines = [
        '# 二次启动策略：无确认 vs 全确认 vs 分层确认 回测对比', '',
        f"- 生成时间：{payload['generated_at']}", f"- 信号样本数：{sample_count}", f"- 收益比较口径：`T+2_close`（无确认沿用日线机械回测 `net_ret`）", '',
        '## 总览对比', '',
        '| 方案 | 交易数 | 触发率 | 胜率 | 平均收益 | 中位收益 | 盈亏比 |',
        '| --- | ---: | ---: | ---: | ---: | ---: | ---: |',
        f"| 无确认 | {a['trade_count']} | {a['entry_rate_pct']:.2f}% | {a['metrics']['win_rate']:.2f}% | {a['metrics']['avg_return_pct']:.2f}% | {a['metrics']['median_return_pct']:.2f}% | {a['metrics']['profit_factor']:.2f} |",
        f"| 全确认 | {b['trade_count']} | {b['entry_rate_pct']:.2f}% | {b['metrics']['win_rate']:.2f}% | {b['metrics']['avg_return_pct']:.2f}% | {b['metrics']['median_return_pct']:.2f}% | {b['metrics']['profit_factor']:.2f} |",
        f"| 分层确认 | {c['trade_count']} | {c['entry_rate_pct']:.2f}% | {c['metrics']['win_rate']:.2f}% | {c['metrics']['avg_return_pct']:.2f}% | {c['metrics']['median_return_pct']:.2f}% | {c['metrics']['profit_factor']:.2f} |",
        '', '## 分层确认：按执行层拆分', '',
        '| 执行层 | 样本数 | 胜率 | 平均收益 | 中位收益 | 盈亏比 |',
        '| --- | ---: | ---: | ---: | ---: | ---: |',
    ]
    for r in c['by_execution_tier']:
        m = r['T+2_close']
        lines.append(f"| {r['execution_tier']} | {r['sample_count']} | {m['win_rate']:.2f}% | {m['avg_return_pct']:.2f}% | {m['median_return_pct']:.2f}% | {m['profit_factor']:.2f} |")

    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    out_json = ROOT / 'data' / 'reports' / f'secondary_launch_execution_modes_{ts}.json'
    out_md = ROOT / 'data' / 'reports' / f'secondary_launch_execution_modes_{ts}.md'
    out_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    out_md.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print('\n'.join(lines))
    print(f'\nJSON: {out_json}')
    print(f'MD: {out_md}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
