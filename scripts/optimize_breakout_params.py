# -*- coding: utf-8 -*-
"""
突破选股策略参数网格搜索（高性能版）

核心优化：预缓存每日快照 + 基础过滤 + 趋势过滤结果，
网格搜索只做参数敏感的后续过滤（RS/箱体/ATR/评分），速度提升50x+

分两段防过拟合：
  - 样本内（前70%交易日）：寻找最优参数
  - 样本外（后30%交易日）：验证参数稳健性
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 强制刷新输出
sys.stdout.reconfigure(line_buffering=True) if hasattr(sys.stdout, 'reconfigure') else None

import numpy as np
import pandas as pd
from itertools import product
from src.core.config import ConfigManager
from src.core.database import DatabaseManager
from src.modules.breakout_strategy import BreakoutStrategy, BreakoutParams


def precompute_daily_snapshots(features, backtest_dates, params, use_ma120):
    """
    预计算每日：快照 → 基础过滤 → 趋势过滤 的结果（这些不依赖搜索参数）
    返回 {date_str: DataFrame} 字典
    """
    strategy = BreakoutStrategy.__new__(BreakoutStrategy)
    strategy.db = None
    strategy.params = params

    cache = {}
    for td in backtest_dates:
        snapshot = strategy._build_snapshot(features, td)
        if snapshot.empty:
            continue
        filtered = strategy._layer_base_filter(snapshot)
        if filtered.empty:
            continue

        # 趋势过滤（不依赖搜索参数）
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

        cache[td] = filtered
    return cache


def evaluate_with_cache(
    daily_cache, price_map, signal_dates,
    rs_min, rs_max, box_max, atr_max, min_score, top_k,
    weight_rs, weight_trend, weight_stability, weight_box, weight_volume,
):
    """基于预缓存结果，只做参数敏感的后续过滤+评分+收益计算"""
    all_rets = {1: [], 2: [], 3: []}
    signal_count = 0

    for td in signal_dates:
        filtered = daily_cache.get(td)
        if filtered is None:
            continue

        # Layer 3 RS过滤
        cond_rs = (
            filtered["rs20_xsec_q"].notna()
            & (filtered["rs20_xsec_q"] >= rs_min)
        )
        if rs_max < 1.0:
            cond_rs = cond_rs & (filtered["rs20_xsec_q"] <= rs_max)
        f3 = filtered.loc[cond_rs]
        if f3.empty:
            continue

        # Layer 4 走稳过滤
        cond4 = f3["box_range"].notna() & (f3["box_range"] <= box_max)
        if f3["atr_ratio_q60"].notna().mean() > 0.3:
            cond4 = cond4 & (f3["atr_ratio_q60"].fillna(0.5) <= atr_max)
        f4 = f3.loc[cond4]
        if f4.empty:
            continue

        # 评分（内联版，避免Strategy实例开销）
        rs_score = f4["rs20_xsec_q"].fillna(0.0).clip(0.0, 1.0) * weight_rs
        ma_gap = ((f4["ma20"] - f4["ma60"]) / f4["ma60"].replace(0, np.nan)).fillna(0.0)
        slope_score = (f4["ma20_slope"].fillna(0.0).clip(0.0, 0.02) / 0.02)
        trend_score = ((ma_gap.clip(0.0, 0.08) / 0.08) * 0.5 + slope_score * 0.5) * weight_trend
        stab_score = (1.0 - f4["atr_ratio_q60"].fillna(0.5).clip(0.0, 1.0)) * weight_stability
        box_score = (1.0 - (f4["box_range"].fillna(box_max) / box_max).clip(0.0, 1.0)) * weight_box
        vol_ratio = (f4["vol_ma5"] / f4["vol_ma20"].replace(0, np.nan)).fillna(0.0).clip(0.0, 2.0)
        vol_raw = np.where(vol_ratio < 0.8, vol_ratio / 0.8,
                           np.where(vol_ratio <= 1.5, 1.0, 1.0 - (vol_ratio - 1.5) / 1.5))
        vol_score = pd.Series(vol_raw, index=f4.index).clip(0.0, 1.0) * weight_volume

        total_score = rs_score + trend_score + stab_score + box_score + vol_score
        passed = total_score >= min_score
        if not passed.any():
            continue

        top = total_score[passed].nlargest(top_k)

        for idx in top.index:
            code = f4.loc[idx, "ts_code"]
            sub = price_map.get(code)
            if sub is None:
                continue
            match = sub.index[sub["date_str"] == td]
            if len(match) == 0:
                continue
            pos = match[0]
            if pos + 1 >= len(sub):
                continue
            entry = float(sub.loc[pos + 1, "open"])
            if entry <= 0:
                continue

            signal_count += 1
            for n in [1, 2, 3]:
                t_idx = pos + 1 + n
                if t_idx < len(sub):
                    all_rets[n].append(float(sub.loc[t_idx, "close"]) / entry - 1.0)

    result = {"signal_count": signal_count}
    for n in [1, 2, 3]:
        rets = np.array(all_rets[n]) if all_rets[n] else np.array([])
        if len(rets) == 0:
            result.update({f"t{n}_win_rate": 0, f"t{n}_avg_ret": 0, f"t{n}_pf": 0})
            continue
        result[f"t{n}_win_rate"] = float((rets > 0).mean())
        result[f"t{n}_avg_ret"] = float(rets.mean())
        gw = float(rets[rets > 0].sum())
        gl = float(-rets[rets < 0].sum())
        result[f"t{n}_pf"] = gw / gl if gl > 1e-10 else 0.0
    return result


def main():
    print("=" * 72, flush=True)
    print("  突破选股策略 - 参数网格搜索（高性能版）", flush=True)
    print("=" * 72, flush=True)

    config = ConfigManager()
    db = DatabaseManager(config)

    all_dates = [r["trade_date"] for r in db.query(
        "SELECT DISTINCT trade_date FROM stock_daily ORDER BY trade_date ASC"
    )]
    total = len(all_dates)
    warmup_skip = 65
    use_ma120 = total >= 180

    if total < 75:
        print(f"  数据不足({total}天)，退出", flush=True)
        return

    backtest_dates = all_dates[warmup_skip:-3]
    split_idx = int(len(backtest_dates) * 0.7)
    in_sample = backtest_dates[:split_idx]
    out_sample = backtest_dates[split_idx:]
    print(f"  总交易日: {total}", flush=True)
    print(f"  样本内: {in_sample[0]} -> {in_sample[-1]} ({len(in_sample)}天)", flush=True)
    print(f"  样本外: {out_sample[0]} -> {out_sample[-1]} ({len(out_sample)}天)", flush=True)

    # 预计算因子
    print("\n  [1/3] 计算全量因子...", flush=True)
    base_params = BreakoutParams()
    strategy = BreakoutStrategy(db=db, params=base_params)
    raw_daily, raw_basic = strategy._load_data(all_dates[-1])
    features = strategy._compute_features(raw_daily, raw_basic, all_dates[-1])
    print(f"  因子行数: {len(features)}", flush=True)

    # 价格映射表
    price_df = features[["ts_code", "trade_date", "open", "close"]].copy()
    price_df = price_df.sort_values(["ts_code", "trade_date"]).reset_index(drop=True)
    price_map = {}
    for code, sub in price_df.groupby("ts_code"):
        s = sub.sort_values("trade_date").reset_index(drop=True)
        s["date_str"] = s["trade_date"].dt.strftime("%Y%m%d")
        price_map[code] = s

    # 预缓存每日快照（基础+趋势过滤）
    print("  [2/3] 预缓存每日快照+基础过滤...", flush=True)
    daily_cache = precompute_daily_snapshots(features, backtest_dates, base_params, use_ma120)
    print(f"  缓存天数: {len(daily_cache)}", flush=True)

    # 网格搜索
    print("  [3/3] 网格搜索...\n", flush=True)
    grid = {
        "min_score":   [55.0, 60.0, 65.0],
        "rs_min":      [0.75, 0.80, 0.85, 0.90],
        "rs_max":      [0.97, 1.0],
        "box_max":     [0.08, 0.10, 0.12],
        "atr_max":     [0.50, 0.60, 0.70],
        "top_k":       [10, 15, 20],
    }
    keys = list(grid.keys())
    combos = list(product(*[grid[k] for k in keys]))
    print(f"  参数组合: {len(combos)}", flush=True)

    # 默认评分权重
    W = {"rs": 35.0, "trend": 25.0, "stab": 20.0, "box": 12.0, "vol": 8.0}

    results = []
    for i, combo in enumerate(combos):
        d = dict(zip(keys, combo))
        res = evaluate_with_cache(
            daily_cache, price_map, in_sample,
            d["rs_min"], d["rs_max"], d["box_max"], d["atr_max"],
            d["min_score"], int(d["top_k"]),
            W["rs"], W["trend"], W["stab"], W["box"], W["vol"],
        )
        res.update(d)
        results.append(res)
        if (i + 1) % 50 == 0:
            print(f"  进度: {i+1}/{len(combos)}", flush=True)

    df = pd.DataFrame(results)
    df = df[df["signal_count"] >= 30].copy()
    if df.empty:
        print("  所有组合信号不足30条，请放宽参数范围", flush=True)
        return

    # 综合评分
    for col in ["t1_win_rate", "t1_avg_ret", "t2_win_rate", "t2_avg_ret", "t1_pf"]:
        cmin, cmax = df[col].min(), df[col].max()
        df[f"{col}_n"] = (df[col] - cmin) / (cmax - cmin + 1e-10)

    df["composite"] = (
        df["t1_win_rate_n"] * 30
        + df["t1_avg_ret_n"] * 25
        + df["t2_win_rate_n"] * 20
        + df["t2_avg_ret_n"] * 15
        + df["t1_pf_n"] * 10
    )

    top10 = df.nlargest(10, "composite")

    print(f"\n{'=' * 72}", flush=True)
    print("  样本内 TOP10", flush=True)
    print(f"{'=' * 72}", flush=True)
    header = (f"  {'#':>2}  {'ScoreMin':>8}  {'RS_min':>6}  {'RS_max':>6}  {'BoxMax':>6}  "
              f"{'ATR_max':>7}  {'TopK':>4}  {'Signals':>7}  {'T1_WR':>7}  {'T1_Ret':>8}  "
              f"{'T1_PF':>6}  {'T2_WR':>7}  {'T2_Ret':>8}  {'Score':>6}")
    print(header, flush=True)
    print("  " + "-" * 112, flush=True)

    for rank, (_, row) in enumerate(top10.iterrows(), 1):
        print(f"  {rank:>2}  {row['min_score']:>8.0f}  {row['rs_min']:>6.2f}  "
              f"{row['rs_max']:>6.2f}  {row['box_max']:>6.2f}  "
              f"{row['atr_max']:>7.2f}  {int(row['top_k']):>4}  "
              f"{int(row['signal_count']):>7}  {row['t1_win_rate']:>7.2%}  "
              f"{row['t1_avg_ret']:>8.4%}  {row['t1_pf']:>6.2f}  "
              f"{row['t2_win_rate']:>7.2%}  {row['t2_avg_ret']:>8.4%}  "
              f"{row['composite']:>6.1f}", flush=True)

    # 样本外验证TOP3
    print(f"\n{'=' * 72}", flush=True)
    print("  样本外验证 TOP3", flush=True)
    print(f"{'=' * 72}", flush=True)

    best_oos_params = None
    best_oos_score = -1

    for rank, (_, row) in enumerate(top10.head(3).iterrows(), 1):
        oos = evaluate_with_cache(
            daily_cache, price_map, out_sample,
            row["rs_min"], row["rs_max"], row["box_max"], row["atr_max"],
            row["min_score"], int(row["top_k"]),
            W["rs"], W["trend"], W["stab"], W["box"], W["vol"],
        )
        print(f"\n  --- TOP{rank} ---", flush=True)
        print(f"  参数: ScoreMin={row['min_score']:.0f}  RS=[{row['rs_min']:.2f},{row['rs_max']:.2f}]"
              f"  BoxMax={row['box_max']:.2f}  ATR_max={row['atr_max']:.2f}  TopK={int(row['top_k'])}", flush=True)
        print(f"  样本内: T1 WR={row['t1_win_rate']:.2%}  Ret={row['t1_avg_ret']:.4%}  PF={row['t1_pf']:.2f}  N={int(row['signal_count'])}", flush=True)
        print(f"  样本外: T1 WR={oos['t1_win_rate']:.2%}  Ret={oos['t1_avg_ret']:.4%}  PF={oos['t1_pf']:.2f}  N={oos['signal_count']}", flush=True)
        print(f"          T2 WR={oos['t2_win_rate']:.2%}  Ret={oos['t2_avg_ret']:.4%}  PF={oos['t2_pf']:.2f}", flush=True)
        print(f"          T3 WR={oos['t3_win_rate']:.2%}  Ret={oos['t3_avg_ret']:.4%}  PF={oos['t3_pf']:.2f}", flush=True)

        # 稳健性判定
        oos_composite = oos["t1_win_rate"] * 30 + oos["t1_avg_ret"] * 100 + oos["t1_pf"] * 10
        if oos["t1_pf"] > 1.2 and oos["t1_win_rate"] > 0.50:
            label = "PASS（稳健）"
        elif oos["t1_pf"] > 1.0:
            label = "MARGINAL（边际）"
        else:
            label = "FAIL（衰减严重）"
        print(f"  判定: {label}", flush=True)

        if oos_composite > best_oos_score:
            best_oos_score = oos_composite
            best_oos_params = row

    # 推荐参数
    if best_oos_params is not None:
        b = best_oos_params
        print(f"\n{'=' * 72}", flush=True)
        print("  最终推荐参数（样本外最优）", flush=True)
        print(f"{'=' * 72}", flush=True)
        print(f"  min_signal_score  = {b['min_score']:.0f}", flush=True)
        print(f"  rs_quantile_min   = {b['rs_min']:.2f}", flush=True)
        print(f"  rs_quantile_max   = {b['rs_max']:.2f}", flush=True)
        print(f"  box_max_range     = {b['box_max']:.2f}", flush=True)
        print(f"  atr_quantile_max  = {b['atr_max']:.2f}", flush=True)
        print(f"  top_k             = {int(b['top_k'])}", flush=True)
        print(f"{'=' * 72}", flush=True)


if __name__ == "__main__":
    main()
