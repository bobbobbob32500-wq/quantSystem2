#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
分析V2回踩策略触发后T+2负收益样本的共性。

对每条负收益触发样本，提取：
1. 日线特征：信号日涨跌、量比、振幅、近5日涨跌、近5日最大回撤、均线位置
2. 盘中特征：触发时间、触发价位/VWAP偏离、触发时置信度层级、触发后走势
3. 对比正收益触发样本的同维度特征，找到区分度最大的维度
"""

from __future__ import annotations

import json
import sqlite3
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _flush(*args):
    print(*args, flush=True)


def get_daily_features(conn: sqlite3.Connection, symbol: str, signal_date: str) -> Dict[str, Any]:
    """取信号日及前后日线特征。"""
    rows = list(conn.execute(
        """SELECT trade_date, open, close, high, low, vol, amount, pct_chg
           FROM stock_daily
           WHERE ts_code = ? AND trade_date <= ?
           ORDER BY trade_date DESC LIMIT 20""",
        (symbol, signal_date),
    ))
    if not rows:
        return {}

    today = rows[0]
    today_close = float(today["close"]) if today["close"] else None
    today_open = float(today["open"]) if today["open"] else None

    pct_chg = float(today["pct_chg"]) if today["pct_chg"] is not None else None

    vols = [float(r["vol"]) for r in rows[:5] if r["vol"] is not None]
    avg_vol_5 = sum(vols) / len(vols) if vols else None
    today_vol = float(today["vol"]) if today["vol"] else None
    vol_ratio_5 = (today_vol / avg_vol_5) if today_vol and avg_vol_5 and avg_vol_5 > 0 else None

    amplitude = None
    if today["high"] and today["low"] and today["close"]:
        amplitude = (float(today["high"]) - float(today["low"])) / float(today["close"]) * 100

    # 近5日涨跌
    ret_5d = None
    if len(rows) >= 5 and rows[4]["close"] and today_close:
        ret_5d = (today_close / float(rows[4]["close"]) - 1.0) * 100

    # 近10日涨跌
    ret_10d = None
    if len(rows) >= 10 and rows[9]["close"] and today_close:
        ret_10d = (today_close / float(rows[9]["close"]) - 1.0) * 100

    # 信号日是涨是跌
    signal_day_up = pct_chg is not None and pct_chg > 0

    # 信号日上影线比例 (上影线长度 / 实体+上下影)
    upper_shadow_pct = None
    if today["high"] and today["close"] and today["open"] and today["low"]:
        h, c, o, l = float(today["high"]), float(today["close"]), float(today["open"]), float(today["low"])
        total_range = h - l
        if total_range > 0:
            upper_shadow = h - max(c, o)
            upper_shadow_pct = upper_shadow / total_range * 100

    # 近3日连续下跌天数
    down_days = 0
    for r in rows[:5]:
        if r["pct_chg"] is not None and float(r["pct_chg"]) < 0:
            down_days += 1
        else:
            break

    # 信号日是否大阴线 (跌幅 > 3%)
    big_down = pct_chg is not None and pct_chg < -3.0

    # 信号日是否涨停 (涨幅 > 9.5%)
    limit_up = pct_chg is not None and pct_chg > 9.5

    # 近5日最大单日跌幅
    max_single_drop = None
    drops = [float(r["pct_chg"]) for r in rows[:5] if r["pct_chg"] is not None]
    if drops:
        max_single_drop = min(drops)

    # 开盘跳空幅度
    gap = None
    if len(rows) >= 2 and today_open and rows[1]["close"]:
        prev_close = float(rows[1]["close"])
        gap = (today_open / prev_close - 1.0) * 100

    return {
        "pct_chg": pct_chg,
        "vol_ratio_5": round(vol_ratio_5, 3) if vol_ratio_5 else None,
        "amplitude": round(amplitude, 2) if amplitude else None,
        "ret_5d": round(ret_5d, 2) if ret_5d else None,
        "ret_10d": round(ret_10d, 2) if ret_10d else None,
        "signal_day_up": signal_day_up,
        "upper_shadow_pct": round(upper_shadow_pct, 1) if upper_shadow_pct is not None else None,
        "down_days": down_days,
        "big_down": big_down,
        "limit_up": limit_up,
        "max_single_drop_5d": round(max_single_drop, 2) if max_single_drop is not None else None,
        "gap_pct": round(gap, 2) if gap is not None else None,
    }


def main() -> int:
    truth_path = ROOT / "results" / "secondary_launch_unified_truth_20260402_114221.json"
    truth = json.loads(truth_path.read_text(encoding="utf-8"))

    daily_conn = sqlite3.connect(str(ROOT / "data/database/quant_system.db"))
    daily_conn.row_factory = sqlite3.Row

    entries = truth.get("entries", [])
    _flush(f"总触发样本: {len(entries)}")

    records = []
    for e in entries:
        symbol = e["symbol"]
        signal_date = e["signal_date"]
        t2_ret = e.get("T+2_close_ret")

        daily_feat = get_daily_features(daily_conn, symbol, signal_date)

        entry_time = e.get("entry_time", "")
        entry_hour = int(entry_time.split(":")[0]) if entry_time else 0
        entry_minute = int(entry_time.split(":")[1]) if entry_time else 0
        is_early = entry_hour < 10 or (entry_hour == 10 and entry_minute <= 15)
        is_afternoon = entry_hour >= 13

        records.append({
            "symbol": symbol,
            "signal_date": signal_date,
            "name": e.get("name", ""),
            "rank": e.get("rank"),
            "entry_time": entry_time,
            "time_bucket": e.get("time_bucket", ""),
            "entry_price": e.get("entry_price"),
            "T+2_ret": round(t2_ret * 100, 2) if t2_ret is not None else None,
            "T+2_positive": t2_ret is not None and t2_ret > 0,
            "is_early": is_early,
            "is_afternoon": is_afternoon,
            **daily_feat,
        })

    daily_conn.close()

    has_t2 = [r for r in records if r.get("T+2_ret") is not None]
    positive = [r for r in has_t2 if r["T+2_positive"]]
    negative = [r for r in has_t2 if not r["T+2_positive"]]

    _flush(f"\n有T+2数据: {len(has_t2)}")
    _flush(f"T+2正收益: {len(positive)} ({len(positive)/len(has_t2)*100:.1f}%)")
    _flush(f"T+2负收益: {len(negative)} ({len(negative)/len(has_t2)*100:.1f}%)")

    # ========== 多维度对比 ==========
    _flush(f"\n{'='*70}")
    _flush(f"正收益 vs 负收益 多维度对比")
    _flush(f"{'='*70}")

    def stats(group, key):
        vals = [r[key] for r in group if r.get(key) is not None]
        if not vals:
            return "-", "-", "-"
        return f"{sum(vals)/len(vals):.2f}", f"{min(vals):.2f}", f"{max(vals):.2f}"

    def pct(group, key, val_fn):
        matched = sum(1 for r in group if val_fn(r.get(key)))
        return f"{matched}/{len(group)} ({matched/len(group)*100:.1f}%)" if group else "-"

    _flush(f"\n  {'维度':<25} {'正收益均值':>12} {'负收益均值':>12} {'差异':>10}")
    _flush(f"  {'-'*60}")

    for feat in ["pct_chg", "vol_ratio_5", "amplitude", "ret_5d", "ret_10d",
                  "upper_shadow_pct", "gap_pct", "max_single_drop_5d"]:
        p_avg, _, _ = stats(positive, feat)
        n_avg, _, _ = stats(negative, feat)
        try:
            diff = f"{float(n_avg) - float(p_avg):+.2f}"
        except (ValueError, TypeError):
            diff = "-"
        _flush(f"  {feat:<25} {p_avg:>12} {n_avg:>12} {diff:>10}")

    # 分类特征
    _flush(f"\n  分类特征对比:")
    _flush(f"  {'维度':<25} {'正收益':>20} {'负收益':>20}")
    _flush(f"  {'-'*65}")

    _flush(f"  {'信号日上涨':<25} {pct(positive, 'signal_day_up', lambda x: x):>20} {pct(negative, 'signal_day_up', lambda x: x):>20}")
    _flush(f"  {'信号日大阴线':<25} {pct(positive, 'big_down', lambda x: x):>20} {pct(negative, 'big_down', lambda x: x):>20}")
    _flush(f"  {'信号日涨停':<25} {pct(positive, 'limit_up', lambda x: x):>20} {pct(negative, 'limit_up', lambda x: x):>20}")
    _flush(f"  {'早盘触发(<=10:15)':<25} {pct(positive, 'is_early', lambda x: x):>20} {pct(negative, 'is_early', lambda x: x):>20}")
    _flush(f"  {'午后触发':<25} {pct(positive, 'is_afternoon', lambda x: x):>20} {pct(negative, 'is_afternoon', lambda x: x):>20}")

    # rank 分布
    _flush(f"\n  rank分布:")
    for rk in [1, 2, 3]:
        p_cnt = sum(1 for r in positive if r["rank"] == rk)
        n_cnt = sum(1 for r in negative if r["rank"] == rk)
        p_total = len(positive)
        n_total = len(negative)
        _flush(f"    rank {rk}: 正收益 {p_cnt}/{p_total} ({p_cnt/p_total*100:.1f}%)  "
               f"负收益 {n_cnt}/{n_total} ({n_cnt/n_total*100:.1f}%)")

    # 信号日涨跌分段
    _flush(f"\n  信号日涨跌幅分段:")
    bins = [(-999, -5), (-5, -3), (-3, 0), (0, 3), (3, 5), (5, 10), (10, 999)]
    for lo, hi in bins:
        label = f"  [{lo}%, {hi}%)" if lo > -999 else f"  (<{hi}%)"
        if hi >= 999:
            label = f"  (>={lo}%)"
        p_cnt = sum(1 for r in positive if r.get("pct_chg") is not None and lo <= r["pct_chg"] < hi)
        n_cnt = sum(1 for r in negative if r.get("pct_chg") is not None and lo <= r["pct_chg"] < hi)
        if p_cnt + n_cnt > 0:
            wr = p_cnt / (p_cnt + n_cnt) * 100
            _flush(f"  {label:<20} 正={p_cnt} 负={n_cnt} 胜率={wr:.1f}%")

    # 近5日涨跌分段
    _flush(f"\n  近5日涨跌幅分段:")
    for lo, hi in [(-999, -10), (-10, -5), (-5, 0), (0, 5), (5, 10), (10, 999)]:
        label = f"  [{lo}%, {hi}%)" if lo > -999 else f"  (<{hi}%)"
        if hi >= 999:
            label = f"  (>={lo}%)"
        p_cnt = sum(1 for r in positive if r.get("ret_5d") is not None and lo <= r["ret_5d"] < hi)
        n_cnt = sum(1 for r in negative if r.get("ret_5d") is not None and lo <= r["ret_5d"] < hi)
        if p_cnt + n_cnt > 0:
            wr = p_cnt / (p_cnt + n_cnt) * 100
            _flush(f"  {label:<20} 正={p_cnt} 负={n_cnt} 胜率={wr:.1f}%")

    # 量比分段
    _flush(f"\n  量比(5日)分段:")
    for lo, hi in [(0, 0.5), (0.5, 0.7), (0.7, 0.9), (0.9, 1.1), (1.1, 1.5), (1.5, 999)]:
        label = f"  [{lo}, {hi})" if hi < 999 else f"  (>={lo})"
        p_cnt = sum(1 for r in positive if r.get("vol_ratio_5") is not None and lo <= r["vol_ratio_5"] < hi)
        n_cnt = sum(1 for r in negative if r.get("vol_ratio_5") is not None and lo <= r["vol_ratio_5"] < hi)
        if p_cnt + n_cnt > 0:
            wr = p_cnt / (p_cnt + n_cnt) * 100
            _flush(f"  {label:<20} 正={p_cnt} 负={n_cnt} 胜率={wr:.1f}%")

    # 振幅分段
    _flush(f"\n  振幅分段:")
    for lo, hi in [(0, 3), (3, 5), (5, 7), (7, 10), (10, 15), (15, 999)]:
        label = f"  [{lo}%, {hi}%)" if hi < 999 else f"  (>={lo}%)"
        p_cnt = sum(1 for r in positive if r.get("amplitude") is not None and lo <= r["amplitude"] < hi)
        n_cnt = sum(1 for r in negative if r.get("amplitude") is not None and lo <= r["amplitude"] < hi)
        if p_cnt + n_cnt > 0:
            wr = p_cnt / (p_cnt + n_cnt) * 100
            _flush(f"  {label:<20} 正={p_cnt} 负={n_cnt} 胜率={wr:.1f}%")

    # 上影线分段
    _flush(f"\n  上影线比例分段:")
    for lo, hi in [(0, 10), (10, 25), (25, 40), (40, 60), (60, 999)]:
        label = f"  [{lo}%, {hi}%)" if hi < 999 else f"  (>={lo}%)"
        p_cnt = sum(1 for r in positive if r.get("upper_shadow_pct") is not None and lo <= r["upper_shadow_pct"] < hi)
        n_cnt = sum(1 for r in negative if r.get("upper_shadow_pct") is not None and lo <= r["upper_shadow_pct"] < hi)
        if p_cnt + n_cnt > 0:
            wr = p_cnt / (p_cnt + n_cnt) * 100
            _flush(f"  {label:<20} 正={p_cnt} 负={n_cnt} 胜率={wr:.1f}%")

    # 连续下跌天数
    _flush(f"\n  信号日前连续下跌天数:")
    for d in range(6):
        p_cnt = sum(1 for r in positive if r.get("down_days") == d)
        n_cnt = sum(1 for r in negative if r.get("down_days") == d)
        if p_cnt + n_cnt > 0:
            wr = p_cnt / (p_cnt + n_cnt) * 100
            _flush(f"    {d}天: 正={p_cnt} 负={n_cnt} 胜率={wr:.1f}%")

    # ========== 负收益样本详情（T+2 < -5%） ==========
    _flush(f"\n{'='*70}")
    _flush(f"T+2 < -5% 的大亏样本详情")
    _flush(f"{'='*70}")
    big_loss = sorted([r for r in negative if r["T+2_ret"] < -5], key=lambda x: x["T+2_ret"])
    for r in big_loss:
        _flush(f"\n  {r['signal_date']} {r['symbol']} {r.get('name','')} rank={r['rank']}")
        _flush(f"    T+2: {r['T+2_ret']:.2f}%  触发时间: {r['entry_time']}  时段: {r['time_bucket']}")
        _flush(f"    信号日涨跌: {r.get('pct_chg','?')}%  振幅: {r.get('amplitude','?')}%  量比: {r.get('vol_ratio_5','?')}")
        _flush(f"    近5日: {r.get('ret_5d','?')}%  近10日: {r.get('ret_10d','?')}%")
        _flush(f"    上影线: {r.get('upper_shadow_pct','?')}%  跳空: {r.get('gap_pct','?')}%")
        _flush(f"    连跌天数: {r.get('down_days','?')}  大阴线: {r.get('big_down','?')}  涨停: {r.get('limit_up','?')}")

    # ========== 候选过滤规则回测 ==========
    _flush(f"\n{'='*70}")
    _flush(f"候选过滤规则回测")
    _flush(f"{'='*70}")

    rules = [
        ("信号日跌幅>5%", lambda r: r.get("pct_chg") is not None and r["pct_chg"] < -5),
        ("信号日跌幅>3%", lambda r: r.get("pct_chg") is not None and r["pct_chg"] < -3),
        ("近5日跌幅>10%", lambda r: r.get("ret_5d") is not None and r["ret_5d"] < -10),
        ("近5日跌幅>8%", lambda r: r.get("ret_5d") is not None and r["ret_5d"] < -8),
        ("振幅>10%", lambda r: r.get("amplitude") is not None and r["amplitude"] > 10),
        ("振幅>8%", lambda r: r.get("amplitude") is not None and r["amplitude"] > 8),
        ("上影线>50%", lambda r: r.get("upper_shadow_pct") is not None and r["upper_shadow_pct"] > 50),
        ("上影线>40%", lambda r: r.get("upper_shadow_pct") is not None and r["upper_shadow_pct"] > 40),
        ("量比>1.3", lambda r: r.get("vol_ratio_5") is not None and r["vol_ratio_5"] > 1.3),
        ("量比>1.2", lambda r: r.get("vol_ratio_5") is not None and r["vol_ratio_5"] > 1.2),
        ("连跌>=3天", lambda r: r.get("down_days") is not None and r["down_days"] >= 3),
        ("信号日涨停", lambda r: r.get("limit_up") is True),
        ("信号日大阴线(跌>3%)+量比>0.9", lambda r: (r.get("pct_chg") is not None and r["pct_chg"] < -3) and (r.get("vol_ratio_5") is not None and r["vol_ratio_5"] > 0.9)),
        ("信号日跌+振幅>7%", lambda r: (r.get("pct_chg") is not None and r["pct_chg"] < 0) and (r.get("amplitude") is not None and r["amplitude"] > 7)),
        ("近5日跌>5% + 信号日跌", lambda r: (r.get("ret_5d") is not None and r["ret_5d"] < -5) and (r.get("pct_chg") is not None and r["pct_chg"] < 0)),
        ("信号日跌幅>3% + 上影线>30%", lambda r: (r.get("pct_chg") is not None and r["pct_chg"] < -3) and (r.get("upper_shadow_pct") is not None and r["upper_shadow_pct"] > 30)),
        ("振幅>8% + 量比>1.0", lambda r: (r.get("amplitude") is not None and r["amplitude"] > 8) and (r.get("vol_ratio_5") is not None and r["vol_ratio_5"] > 1.0)),
        ("振幅>10% 或 信号日跌>5%", lambda r: (r.get("amplitude") is not None and r["amplitude"] > 10) or (r.get("pct_chg") is not None and r["pct_chg"] < -5)),
    ]

    _flush(f"\n  {'规则':<35} {'拦截正':>6} {'拦截负':>6} {'净收益':>8} {'精确度':>8}")
    _flush(f"  {'-'*70}")

    for name, fn in rules:
        blocked_pos = sum(1 for r in positive if fn(r))
        blocked_neg = sum(1 for r in negative if fn(r))
        blocked_total = blocked_pos + blocked_neg
        precision = blocked_neg / blocked_total * 100 if blocked_total > 0 else 0
        # 计算被拦截的正收益样本的损失 vs 被拦截的负收益样本的避免
        lost_profit = sum(r["T+2_ret"] for r in positive if fn(r))
        avoided_loss = sum(abs(r["T+2_ret"]) for r in negative if fn(r))
        net_benefit = avoided_loss - lost_profit
        _flush(f"  {name:<35} {blocked_pos:>6} {blocked_neg:>6} {net_benefit:>+8.1f}% {precision:>7.1f}%")

    # 组合规则
    _flush(f"\n  组合规则测试:")
    combo_rules = [
        ("combo1: 振幅>10% 或 跌>5%",
         lambda r: (r.get("amplitude") is not None and r["amplitude"] > 10) or (r.get("pct_chg") is not None and r["pct_chg"] < -5)),
        ("combo2: 振幅>8%+量比>1.0 或 跌>5%",
         lambda r: ((r.get("amplitude") is not None and r["amplitude"] > 8) and (r.get("vol_ratio_5") is not None and r["vol_ratio_5"] > 1.0)) or (r.get("pct_chg") is not None and r["pct_chg"] < -5)),
        ("combo3: 跌>3%+上影>30% 或 振幅>10%",
         lambda r: ((r.get("pct_chg") is not None and r["pct_chg"] < -3) and (r.get("upper_shadow_pct") is not None and r["upper_shadow_pct"] > 30)) or (r.get("amplitude") is not None and r["amplitude"] > 10)),
        ("combo4: 跌>5% 或 近5日跌>10% 或 振幅>10%",
         lambda r: (r.get("pct_chg") is not None and r["pct_chg"] < -5) or (r.get("ret_5d") is not None and r["ret_5d"] < -10) or (r.get("amplitude") is not None and r["amplitude"] > 10)),
        ("combo5: (跌>3%+放量>0.9) 或 振幅>10%",
         lambda r: ((r.get("pct_chg") is not None and r["pct_chg"] < -3) and (r.get("vol_ratio_5") is not None and r["vol_ratio_5"] > 0.9)) or (r.get("amplitude") is not None and r["amplitude"] > 10)),
    ]

    for name, fn in combo_rules:
        blocked_pos = [r for r in positive if fn(r)]
        blocked_neg = [r for r in negative if fn(r)]
        remain_pos = [r for r in positive if not fn(r)]
        remain_neg = [r for r in negative if not fn(r)]
        new_total = len(remain_pos) + len(remain_neg)
        new_wr = len(remain_pos) / new_total * 100 if new_total > 0 else 0
        new_avg_ret = sum(r["T+2_ret"] for r in remain_pos + remain_neg) / new_total if new_total > 0 else 0
        lost_profit = sum(r["T+2_ret"] for r in blocked_pos)
        avoided_loss = sum(abs(r["T+2_ret"]) for r in blocked_neg)
        _flush(f"\n  {name}:")
        _flush(f"    拦截: 正{len(blocked_pos)} 负{len(blocked_neg)}  精确度: {len(blocked_neg)/(len(blocked_pos)+len(blocked_neg))*100:.1f}%")
        _flush(f"    剩余: {new_total}条  新胜率: {new_wr:.1f}%  新T+2均收: {new_avg_ret:.2f}%")
        _flush(f"    避免亏损: {avoided_loss:.1f}%  损失利润: {lost_profit:.1f}%  净收益: {avoided_loss - lost_profit:+.1f}%")

    # 保存
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = ROOT / "results" / f"negative_entry_analysis_{ts}.json"
    out.write_text(json.dumps(records, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    _flush(f"\n详细数据已保存: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
