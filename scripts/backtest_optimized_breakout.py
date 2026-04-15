# -*- coding: utf-8 -*-
"""
优化后突破策略回测：对比不同选股预设 + 盘中买点信号确认

对比组：
  1. baseline选股 + 无条件买入（原版基线）
  2. baseline选股 + 突破确认（原版选股+买点）
  3. baseline选股 + 突破+放量确认（原版选股+严买点）
  4. optuna_optimized_v1选股 + 无条件买入（优化选股）
  5. optuna_optimized_v1选股 + 突破确认（优化选股+买点）
  6. optuna_optimized_v1选股 + 突破+放量确认（优化选股+严买点）
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    sys.stdout.reconfigure(line_buffering=True)
except Exception:
    pass

import json
import numpy as np
import pandas as pd
from datetime import datetime
from src.core.config import ConfigManager
from src.core.database import DatabaseManager
from src.modules.breakout_strategy import (
    BreakoutStrategy, BreakoutParams,
    get_breakout_params_for_backtest
)


def run_backtest(strategy, params, price_map, signal_dates, use_ma120,
                 need_breakout=False, need_volume=False,
                 breakout_buffer=0.002, breakout_max_chase=0.008,
                 volume_confirm_ratio=1.3, max_intraday_gain=0.05):
    """运行单组回测"""
    trades = {1: [], 2: [], 3: []}
    signal_count = 0
    skipped_breakout = 0
    skipped_volume = 0

    for td in signal_dates:
        snapshot = strategy._build_snapshot(strategy._features, td)
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

        cond4 = filtered["box_range"].notna() & (filtered["box_range"] <= params.box_max_range)
        if filtered["atr_ratio_q60"].notna().mean() > 0.3:
            cond4 = cond4 & (filtered["atr_ratio_q60"].fillna(0.5) <= params.atr_quantile_max)
        filtered = filtered.loc[cond4].copy()
        if filtered.empty:
            continue

        scored = strategy._compute_scores(filtered)
        min_score, top_k = strategy._market_gate(strategy._features, td)
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

            # T+1日数据
            t1_row = sub.loc[idx + 1]
            t1_high = float(t1_row["high"])
            t1_open = float(t1_row["open"])
            t1_vol = float(t1_row["vol"])
            t1_vol_ma20 = float(t1_row["vol_ma20"]) if pd.notna(t1_row.get("vol_ma20")) else 0

            if t1_open <= 0:
                continue

            # ── 买点信号确认 ──
            if need_breakout:
                # 条件1: 最高价突破触发价
                trigger = pivot * (1 + breakout_buffer)
                if t1_high < trigger:
                    skipped_breakout += 1
                    continue
                # 条件2: 入场价 = 触发价
                entry_price = trigger
                # 条件3: 不追高
                if entry_price > pivot * (1 + breakout_max_chase):
                    skipped_breakout += 1
                    continue
                # 条件4: 当日涨幅限制
                if t1_open > 0 and (t1_high / t1_open - 1) > max_intraday_gain:
                    skipped_breakout += 1
                    continue
            else:
                entry_price = t1_open  # 无条件开盘价买入

            if need_volume:
                # 条件5: 放量确认
                if t1_vol_ma20 > 0 and t1_vol / t1_vol_ma20 < volume_confirm_ratio:
                    skipped_volume += 1
                    continue

            signal_count += 1
            for n in [1, 2, 3]:
                t_idx = idx + 1 + n
                if t_idx < len(sub):
                    exit_close = float(sub.loc[t_idx, "close"])
                    trades[n].append(exit_close / entry_price - 1.0)

    return {
        "signal_count": signal_count,
        "skipped_breakout": skipped_breakout,
        "skipped_volume": skipped_volume,
        "trades": trades,
    }


def print_results(name, data):
    """打印单组结果"""
    print(f"\n  --- {name} ---", flush=True)
    print(f"  入场信号数: {data['signal_count']}", flush=True)
    if data["skipped_breakout"] > 0:
        print(f"  被突破过滤: {data['skipped_breakout']}", flush=True)
    if data["skipped_volume"] > 0:
        print(f"  被放量过滤: {data['skipped_volume']}", flush=True)

    print(f"  {'持有':>6}  {'笔数':>5}  {'胜率':>8}  {'均收益':>10}  {'中位数':>10}  "
          f"{'均盈利':>10}  {'均亏损':>10}  {'盈亏比':>7}  {'PF':>7}", flush=True)
    print("  " + "-" * 88, flush=True)

    for n in [1, 2, 3]:
        rets = np.array(data["trades"][n]) if data["trades"][n] else np.array([])
        if len(rets) == 0:
            print(f"  T+{n}     无数据", flush=True)
            continue
        cnt = len(rets)
        wr = (rets > 0).mean()
        avg = rets.mean()
        med = np.median(rets)
        avg_w = rets[rets > 0].mean() if (rets > 0).any() else 0
        avg_l = rets[rets < 0].mean() if (rets < 0).any() else 0
        payoff = -avg_w / avg_l if avg_l < 0 else 0
        gw = rets[rets > 0].sum()
        gl = -rets[rets < 0].sum()
        pf = gw / gl if gl > 1e-10 else 0
        print(f"  T+{n}    {cnt:>5}  {wr:>8.2%}  {avg:>10.4%}  {med:>10.4%}  "
              f"{avg_w:>10.4%}  {avg_l:>10.4%}  {payoff:>7.2f}  {pf:>7.2f}", flush=True)


def main():
    print("=" * 72, flush=True)
    print("  优化后突破策略回测：选股预设 x 买点信号确认", flush=True)
    print("=" * 72, flush=True)

    config = ConfigManager()
    db = DatabaseManager(config)

    all_dates = [r["trade_date"] for r in db.query(
        "SELECT DISTINCT trade_date FROM stock_daily ORDER BY trade_date ASC"
    )]
    # 确保日期为字符串格式
    all_dates = [d.strftime("%Y%m%d") if hasattr(d, "strftime") else str(d) for d in all_dates]
    warmup_skip = 65
    use_ma120 = len(all_dates) >= 180
    backtest_dates = all_dates[warmup_skip:]

    # 划分样本内/样本外
    total = len(backtest_dates)
    split_idx = int(total * 0.7)
    in_sample_dates = backtest_dates[:split_idx]
    out_sample_dates = backtest_dates[split_idx:-4]

    print(f"  总交易日: {total}", flush=True)
    is_start = in_sample_dates[0] if isinstance(in_sample_dates[0], str) else in_sample_dates[0].strftime('%Y%m%d')
    is_end = in_sample_dates[-1] if isinstance(in_sample_dates[-1], str) else in_sample_dates[-1].strftime('%Y%m%d')
    os_start = out_sample_dates[0] if isinstance(out_sample_dates[0], str) else out_sample_dates[0].strftime('%Y%m%d')
    os_end = out_sample_dates[-1] if isinstance(out_sample_dates[-1], str) else out_sample_dates[-1].strftime('%Y%m%d')
    print(f"  样本内: {is_start} ~ {is_end} ({len(in_sample_dates)}天)", flush=True)
    print(f"  样本外: {os_start} ~ {os_end} ({len(out_sample_dates)}天)", flush=True)

    # ── 定义对比组 ──
    test_groups = [
        # (组名, 选股预设, 突破确认, 放量确认)
        ("1.基线+无条件",     "baseline",             False, False),
        ("2.基线+突破确认",   "baseline",             True,  False),
        ("3.基线+突破+放量",  "baseline",             True,  True),
        ("4.优化+无条件",     "optuna_optimized_v1",  False, False),
        ("5.优化+突破确认",   "optuna_optimized_v1",  True,  False),
        ("6.优化+突破+放量",  "optuna_optimized_v1",  True,  True),
    ]

    all_results = {}

    # ── 预计算因子和价格表（只算一次）──
    print(f"\n  预计算因子...", flush=True)
    base_params = BreakoutParams()
    base_params.min_amt_ma20 = 8e4
    base_params.rs_quantile_max = 0.97
    base_strategy = BreakoutStrategy(db=db, params=base_params)
    raw_daily, raw_basic = base_strategy._load_data(all_dates[-1])
    features = base_strategy._compute_features(raw_daily, raw_basic, all_dates[-1])
    print(f"  因子行数: {len(features)}", flush=True)

    # 构建价格查找表
    price_df = features[["ts_code", "trade_date", "open", "high", "low", "close",
                         "vol", "vol_ma20", "pivot"]].copy()
    price_df = price_df.sort_values(["ts_code", "trade_date"]).reset_index(drop=True)
    price_map = {}
    for code, sub in price_df.groupby("ts_code"):
        s = sub.sort_values("trade_date").reset_index(drop=True)
        s["date_str"] = s["trade_date"].dt.strftime("%Y%m%d")
        price_map[code] = s

    for group_name, preset, need_breakout, need_volume in test_groups:
        print(f"  计算 {group_name} ...", flush=True)

        # 获取参数
        params = get_breakout_params_for_backtest(preset, use_ma120)
        strategy = BreakoutStrategy(db=db, params=params)
        strategy._features = features  # 复用因子

        # 买点参数
        breakout_buffer = params.breakout_buffer
        breakout_max_chase = params.breakout_max_chase
        volume_confirm_ratio = params.volume_confirm_ratio
        max_intraday_gain = params.max_intraday_gain

        # 样本内回测
        is_result = run_backtest(
            strategy, params, price_map, in_sample_dates, use_ma120,
            need_breakout=need_breakout, need_volume=need_volume,
            breakout_buffer=breakout_buffer, breakout_max_chase=breakout_max_chase,
            volume_confirm_ratio=volume_confirm_ratio, max_intraday_gain=max_intraday_gain,
        )

        # 样本外回测
        os_result = run_backtest(
            strategy, params, price_map, out_sample_dates, use_ma120,
            need_breakout=need_breakout, need_volume=need_volume,
            breakout_buffer=breakout_buffer, breakout_max_chase=breakout_max_chase,
            volume_confirm_ratio=volume_confirm_ratio, max_intraday_gain=max_intraday_gain,
        )

        all_results[group_name] = {
            "in_sample": is_result,
            "out_sample": os_result,
            "preset": preset,
            "need_breakout": need_breakout,
            "need_volume": need_volume,
        }

    # ── 输出结果 ──
    print(f"\n{'=' * 72}", flush=True)
    print("  样本内结果", flush=True)
    print(f"{'=' * 72}", flush=True)
    for name, data in all_results.items():
        print_results(name, data["in_sample"])

    print(f"\n{'=' * 72}", flush=True)
    print("  样本外结果", flush=True)
    print(f"{'=' * 72}", flush=True)
    for name, data in all_results.items():
        print_results(name, data["out_sample"])

    # ── 汇总对比表 ──
    print(f"\n{'=' * 72}", flush=True)
    print("  T+1 汇总对比（样本外）", flush=True)
    print(f"{'=' * 72}", flush=True)
    print(f"  {'组名':>22}  {'信号数':>6}  {'胜率':>8}  {'均收益':>10}  {'PF':>7}  {'中位数':>10}", flush=True)
    print("  " + "-" * 75, flush=True)

    for name, data in all_results.items():
        rets = np.array(data["out_sample"]["trades"][1])
        if len(rets) == 0:
            continue
        cnt = len(rets)
        wr = (rets > 0).mean()
        avg = rets.mean()
        med = np.median(rets)
        gw = rets[rets > 0].sum()
        gl = -rets[rets < 0].sum()
        pf = gw / gl if gl > 1e-10 else 0
        print(f"  {name:>22}  {cnt:>6}  {wr:>8.2%}  {avg:>10.4%}  {pf:>7.2f}  {med:>10.4%}", flush=True)

    # ── 保存结果 ──
    output = {}
    for name, data in all_results.items():
        output[name] = {
            "preset": data["preset"],
            "need_breakout": data["need_breakout"],
            "need_volume": data["need_volume"],
            "in_sample": {
                "signal_count": data["in_sample"]["signal_count"],
                "t1_win_rate": float((np.array(data["in_sample"]["trades"][1]) > 0).mean()) if data["in_sample"]["trades"][1] else 0,
                "t1_avg_ret": float(np.array(data["in_sample"]["trades"][1]).mean()) if data["in_sample"]["trades"][1] else 0,
            },
            "out_sample": {
                "signal_count": data["out_sample"]["signal_count"],
                "t1_win_rate": float((np.array(data["out_sample"]["trades"][1]) > 0).mean()) if data["out_sample"]["trades"][1] else 0,
                "t1_avg_ret": float(np.array(data["out_sample"]["trades"][1]).mean()) if data["out_sample"]["trades"][1] else 0,
            },
        }

    out_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "output", "breakout_optimized_backtest.json")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"\n  结果已保存: {out_path}", flush=True)

    print(f"\n{'=' * 72}", flush=True)
    print("  完成", flush=True)
    print(f"{'=' * 72}", flush=True)


if __name__ == "__main__":
    main()
