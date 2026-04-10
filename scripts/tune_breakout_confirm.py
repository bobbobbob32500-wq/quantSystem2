# -*- coding: utf-8 -*-
"""
突破确认参数调优脚本

遍历不同的放量阈值（volume_confirm_ratio）和突破缓冲（breakout_buffer）组合，
输出每种组合下的信号量、胜率、均收益、PF，帮助找到信号量与质量的最佳平衡点。

同时对比"仅突破"和"突破+放量"两种模式在每组参数下的表现。
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    sys.stdout.reconfigure(line_buffering=True)
except Exception:
    pass

import numpy as np
import pandas as pd
from itertools import product
from src.core.config import ConfigManager
from src.core.database import DatabaseManager
from src.modules.breakout_strategy import BreakoutStrategy, BreakoutParams


def build_features_and_price_map(db, strategy, all_dates, end_date):
    """预计算因子和价格查找表（只做一次，所有参数组合复用）"""
    raw_daily, raw_basic = strategy._load_data(end_date)
    features = strategy._compute_features(raw_daily, raw_basic, end_date)

    price_df = features[["ts_code", "trade_date", "open", "high", "low",
                          "close", "vol", "vol_ma20", "pivot"]].copy()
    price_df = price_df.sort_values(["ts_code", "trade_date"]).reset_index(drop=True)
    price_map = {}
    for code, sub in price_df.groupby("ts_code"):
        s = sub.sort_values("trade_date").reset_index(drop=True)
        s["date_str"] = s["trade_date"].dt.strftime("%Y%m%d")
        price_map[code] = s
    return features, price_map


def run_single_combo(strategy, features, price_map, signal_dates,
                     vol_ratio_threshold, buffer, max_chase, use_ma120):
    """对单组参数运行回测，返回统计结果"""
    p = strategy.params
    # 临时覆盖参数
    orig_buffer = p.breakout_buffer
    orig_chase = p.breakout_max_chase
    p.breakout_buffer = buffer
    p.breakout_max_chase = max_chase

    trades_breakout = []    # 仅突破
    trades_bv = []          # 突破+放量

    for td in signal_dates:
        snapshot = strategy._build_snapshot(features, td)
        if snapshot.empty:
            continue
        filtered = strategy._layer_base_filter(snapshot)
        if filtered.empty:
            continue

        if use_ma120:
            filtered = strategy._layer_trend_filter(filtered)
        else:
            cond = (
                filtered["ma20"].notna()
                & filtered["ma60"].notna()
                & (filtered["ma20"] > filtered["ma60"])
                & (filtered["ma20_slope"].fillna(-1) > 0)
            )
            filtered = filtered.loc[cond].copy()
        if filtered.empty:
            continue

        filtered = strategy._layer_strength_filter(filtered)
        if filtered.empty:
            continue

        cond4 = filtered["box_range"].notna() & (filtered["box_range"] <= p.box_max_range)
        if filtered["atr_ratio_q60"].notna().mean() > 0.3:
            cond4 = cond4 & (filtered["atr_ratio_q60"].fillna(0.5) <= p.atr_quantile_max)
        filtered = filtered.loc[cond4].copy()
        if filtered.empty:
            continue

        scored = strategy._compute_scores(filtered)
        min_score, top_k = strategy._market_gate(features, td)
        if min_score >= 999 or top_k <= 0:
            continue
        scored = scored[scored["signal_score"] >= min_score].copy()
        if scored.empty:
            continue
        scored = scored.sort_values("signal_score", ascending=False).head(top_k)

        for _, row in scored.iterrows():
            code = row["ts_code"]
            sub = price_map.get(code)
            if sub is None:
                continue
            match = sub.index[sub["date_str"] == td]
            if len(match) == 0:
                continue
            idx = match[0]
            if idx + 1 >= len(sub):
                continue

            pivot = float(row.get("pivot", 0))
            if pivot <= 0:
                continue

            t1 = sub.loc[idx + 1]
            t1_high = float(t1["high"])
            t1_open = float(t1["open"])
            t1_vol = float(t1["vol"])
            t1_vol_ma20 = float(t1["vol_ma20"]) if pd.notna(t1.get("vol_ma20")) else 0

            if t1_open <= 0:
                continue

            trigger = pivot * (1 + buffer)
            if t1_high < trigger:
                continue
            entry_price = trigger
            if entry_price > pivot * (1 + max_chase):
                continue
            if entry_price > t1_high:
                continue
            if t1_open > 0 and (t1_high / t1_open - 1) > 0.05:
                continue

            vol_ratio = t1_vol / t1_vol_ma20 if t1_vol_ma20 > 0 else 0.0

            # T+1收益（以T+2收盘为出场）
            if idx + 3 < len(sub):
                exit_close = float(sub.loc[idx + 3, "close"])
                ret = exit_close / entry_price - 1.0
                trades_breakout.append(ret)
                if vol_ratio >= vol_ratio_threshold:
                    trades_bv.append(ret)

    # 恢复参数
    p.breakout_buffer = orig_buffer
    p.breakout_max_chase = orig_chase

    return trades_breakout, trades_bv


def calc_stats(rets):
    """计算核心统计指标"""
    if len(rets) == 0:
        return {"cnt": 0, "wr": 0, "avg": 0, "pf": 0}
    arr = np.array(rets)
    cnt = len(arr)
    wr = float((arr > 0).mean())
    avg = float(arr.mean())
    gw = arr[arr > 0].sum()
    gl = -arr[arr < 0].sum()
    pf = gw / gl if gl > 1e-10 else 99.0
    return {"cnt": cnt, "wr": wr, "avg": avg, "pf": pf}


def main():
    print("=" * 72, flush=True)
    print("  突破确认参数调优", flush=True)
    print("=" * 72, flush=True)

    config = ConfigManager()
    db = DatabaseManager(config)

    all_dates = [r["trade_date"] for r in db.query(
        "SELECT DISTINCT trade_date FROM stock_daily ORDER BY trade_date ASC"
    )]
    warmup_skip = 65
    use_ma120 = len(all_dates) >= 180
    backtest_dates = all_dates[warmup_skip:]
    signal_dates = backtest_dates[:-4]

    params = BreakoutParams()
    params.min_amt_ma20 = 8e4
    params.rs_quantile_max = 0.97
    params.min_signal_score = 60.0
    params.top_k = 15
    strategy = BreakoutStrategy(db=db, params=params)

    print("  预计算因子（仅一次）...", flush=True)
    features, price_map = build_features_and_price_map(
        db, strategy, all_dates, all_dates[-1]
    )
    print(f"  因子行数: {len(features)}", flush=True)

    # ── 参数网格 ──
    vol_ratios = [1.0, 1.1, 1.2, 1.3, 1.5]
    buffers = [0.001, 0.002, 0.003]
    max_chases = [0.006, 0.008, 0.010]

    results = []

    total = len(buffers) * len(max_chases) * len(vol_ratios)
    done = 0

    print(f"\n  参数组合总数: {len(buffers)}×{len(max_chases)} = {len(buffers)*len(max_chases)} 个突破参数组合", flush=True)
    print(f"  × {len(vol_ratios)} 个放量阈值", flush=True)
    print(f"\n  {'buffer':>8}  {'chase':>8}  {'vol_min':>8}  │ "
          f"{'模式':>12}  {'信号数':>5}  {'胜率':>8}  {'均收益':>10}  {'PF':>7}", flush=True)
    print("  " + "─" * 85, flush=True)

    for buf, chase in product(buffers, max_chases):
        t_bo, t_bv_all = run_single_combo(
            strategy, features, price_map, signal_dates,
            vol_ratio_threshold=1.0, buffer=buf, max_chase=chase,
            use_ma120=use_ma120,
        )
        # 打印纯突破结果
        s_bo = calc_stats(t_bo)
        print(f"  {buf:>8.3f}  {chase:>8.3f}  {'--':>8}  │ "
              f"{'仅突破':>12}  {s_bo['cnt']:>5}  {s_bo['wr']:>8.2%}  "
              f"{s_bo['avg']:>10.4%}  {s_bo['pf']:>7.2f}", flush=True)

        for vr in vol_ratios:
            # 从已有的突破数据中按放量过滤（不用重跑）
            # 需要重跑一次获取放量筛选后的数据
            _, t_bv = run_single_combo(
                strategy, features, price_map, signal_dates,
                vol_ratio_threshold=vr, buffer=buf, max_chase=chase,
                use_ma120=use_ma120,
            )
            s_bv = calc_stats(t_bv)
            print(f"  {buf:>8.3f}  {chase:>8.3f}  {vr:>8.1f}  │ "
                  f"{'突破+放量':>12}  {s_bv['cnt']:>5}  {s_bv['wr']:>8.2%}  "
                  f"{s_bv['avg']:>10.4%}  {s_bv['pf']:>7.2f}", flush=True)

            results.append({
                "buffer": buf, "chase": chase, "vol_min": vr,
                **{f"bv_{k}": v for k, v in s_bv.items()},
                **{f"bo_{k}": v for k, v in s_bo.items()},
            })
            done += 1

        print("  " + "─" * 85, flush=True)

    # ── 综合排名（信号量≥30，按 PF*均收益 排序）──
    df = pd.DataFrame(results)
    df["composite"] = df["bv_pf"] * df["bv_avg"] * 10000  # 放大便于阅读
    qualified = df[df["bv_cnt"] >= 15].copy()
    if not qualified.empty:
        top5 = qualified.sort_values("composite", ascending=False).head(5)
        print(f"\n{'=' * 72}", flush=True)
        print("  Top 5 参数组合（突破+放量，信号≥15笔）", flush=True)
        print(f"{'=' * 72}", flush=True)
        for i, (_, r) in enumerate(top5.iterrows(), 1):
            print(f"  #{i}  buffer={r['buffer']:.3f}  chase={r['chase']:.3f}  "
                  f"vol≥{r['vol_min']:.1f}  │  "
                  f"信号={int(r['bv_cnt'])}  胜率={r['bv_wr']:.2%}  "
                  f"均收={r['bv_avg']:.4%}  PF={r['bv_pf']:.2f}", flush=True)

    # ── 最佳"仅突破"（不要求放量，信号更多）──
    bo_only = df.drop_duplicates(subset=["buffer", "chase"])
    bo_only["bo_composite"] = bo_only["bo_pf"] * bo_only["bo_avg"] * 10000
    bo_qual = bo_only[bo_only["bo_cnt"] >= 30].copy()
    if not bo_qual.empty:
        bo_top3 = bo_qual.sort_values("bo_composite", ascending=False).head(3)
        print(f"\n{'=' * 72}", flush=True)
        print("  Top 3 参数组合（仅突破，信号≥30笔）", flush=True)
        print(f"{'=' * 72}", flush=True)
        for i, (_, r) in enumerate(bo_top3.iterrows(), 1):
            print(f"  #{i}  buffer={r['buffer']:.3f}  chase={r['chase']:.3f}  │  "
                  f"信号={int(r['bo_cnt'])}  胜率={r['bo_wr']:.2%}  "
                  f"均收={r['bo_avg']:.4%}  PF={r['bo_pf']:.2f}", flush=True)

    print(f"\n  调优完成", flush=True)


if __name__ == "__main__":
    main()
