# -*- coding: utf-8 -*-
"""
验证改造后的突破策略完整流程：
  1. 盘前选股 → 观察池
  2. 日线突破确认 → 分级信号
  3. 对比改造前后效果
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    sys.stdout.reconfigure(line_buffering=True)
except Exception:
    pass

import numpy as np
import pandas as pd
from src.core.config import ConfigManager
from src.core.database import DatabaseManager
from src.modules.breakout_strategy import BreakoutStrategy, BreakoutParams


def main():
    print("=" * 72, flush=True)
    print("  突破策略改造验证", flush=True)
    print("=" * 72, flush=True)

    config = ConfigManager()
    db = DatabaseManager(config)

    all_dates = [r["trade_date"] for r in db.query(
        "SELECT DISTINCT trade_date FROM stock_daily ORDER BY trade_date ASC"
    )]

    params = BreakoutParams()  # 使用新默认参数
    strategy = BreakoutStrategy(db=db, params=params)

    print(f"\n  默认参数检查：", flush=True)
    print(f"    min_signal_score = {params.min_signal_score}", flush=True)
    print(f"    top_k = {params.top_k}", flush=True)
    print(f"    breakout_buffer = {params.breakout_buffer}", flush=True)
    print(f"    volume_confirm_ratio = {params.volume_confirm_ratio}", flush=True)
    print(f"    volume_normal_ratio = {params.volume_normal_ratio}", flush=True)
    print(f"    min_amt_ma20 = {params.min_amt_ma20}", flush=True)

    # 计算因子
    print(f"\n  计算因子...", flush=True)
    raw_daily, raw_basic = strategy._load_data(all_dates[-1])
    features = strategy._compute_features(raw_daily, raw_basic, all_dates[-1])
    print(f"  因子行数: {len(features)}", flush=True)

    # 构建价格查找表
    price_df = features[["ts_code", "trade_date", "open", "high", "low",
                          "close", "vol", "vol_ma20", "pivot"]].copy()
    price_df = price_df.sort_values(["ts_code", "trade_date"]).reset_index(drop=True)
    price_map = {}
    for code, sub in price_df.groupby("ts_code"):
        s = sub.sort_values("trade_date").reset_index(drop=True)
        s["date_str"] = s["trade_date"].dt.strftime("%Y%m%d")
        price_map[code] = s

    warmup_skip = 65
    use_ma120 = len(all_dates) >= 180
    signal_dates = all_dates[warmup_skip:-4]

    # 统计新旧对比
    old_trades = {1: [], 2: [], 3: []}  # 无条件买入
    new_a_trades = {1: [], 2: [], 3: []}  # A级信号
    new_b_trades = {1: [], 2: [], 3: []}  # B级信号
    new_all_trades = {1: [], 2: [], 3: []}  # 所有确认信号

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
                filtered["ma20"].notna() & filtered["ma60"].notna()
                & (filtered["ma20"] > filtered["ma60"])
                & (filtered["ma20_slope"].fillna(-1) > 0)
            )
            filtered = filtered.loc[cond].copy()
        if filtered.empty:
            continue

        filtered = strategy._layer_strength_filter(filtered)
        if filtered.empty:
            continue

        cond4 = filtered["box_range"].notna() & (filtered["box_range"] <= params.box_max_range)
        if filtered["atr_ratio_q60"].notna().mean() > 0.3:
            cond4 = cond4 & (filtered["atr_ratio_q60"].fillna(0.5) <= params.atr_quantile_max)
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

            # 旧模式：无条件开盘买入
            for n in [1, 2, 3]:
                t_idx = idx + 1 + n
                if t_idx < len(sub):
                    old_trades[n].append(float(sub.loc[t_idx, "close"]) / t1_open - 1.0)

            # 新模式：突破确认
            trigger = pivot * (1 + params.breakout_buffer)
            if t1_high < trigger:
                continue
            entry_price = trigger
            if entry_price > pivot * (1 + params.breakout_max_chase):
                continue
            if entry_price > t1_high:
                continue
            if t1_open > 0 and (t1_high / t1_open - 1) > params.max_intraday_gain:
                continue

            vol_ratio = t1_vol / t1_vol_ma20 if t1_vol_ma20 > 0 else 0.0
            if vol_ratio < params.volume_normal_ratio:
                continue

            is_a = vol_ratio >= params.volume_confirm_ratio

            for n in [1, 2, 3]:
                t_idx = idx + 1 + n
                if t_idx < len(sub):
                    ret = float(sub.loc[t_idx, "close"]) / entry_price - 1.0
                    new_all_trades[n].append(ret)
                    if is_a:
                        new_a_trades[n].append(ret)
                    else:
                        new_b_trades[n].append(ret)

    # 输出对比
    print(f"\n{'=' * 72}", flush=True)
    print(f"  改造前后效果对比", flush=True)
    print(f"{'=' * 72}", flush=True)

    for label, trades in [
        ("旧模式（无条件买入）", old_trades),
        ("新模式（全部确认信号）", new_all_trades),
        ("新模式 A级（突破+放量≥1.1x）", new_a_trades),
        ("新模式 B级（突破+正常量能）", new_b_trades),
    ]:
        print(f"\n  --- {label} ---", flush=True)
        for n in [1, 2, 3]:
            rets = np.array(trades[n]) if trades[n] else np.array([])
            if len(rets) == 0:
                print(f"  T+{n}  无数据", flush=True)
                continue
            wr = (rets > 0).mean()
            avg = rets.mean()
            gw = rets[rets > 0].sum()
            gl = -rets[rets < 0].sum()
            pf = gw / gl if gl > 1e-10 else 99.0
            print(f"  T+{n}  信号={len(rets):>4}  胜率={wr:>7.2%}  "
                  f"均收益={avg:>8.4%}  PF={pf:>6.2f}", flush=True)

    print(f"\n{'=' * 72}", flush=True)
    print(f"  验证完成", flush=True)
    print(f"{'=' * 72}", flush=True)


if __name__ == "__main__":
    main()
