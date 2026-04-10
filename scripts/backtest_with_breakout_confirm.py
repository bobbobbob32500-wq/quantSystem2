# -*- coding: utf-8 -*-
"""
改进版回测：加入日线级别的"突破确认+放量确认"

对比三种入场模式：
  模式A（当前）: 观察池次日开盘无条件买入
  模式B（+突破）: 仅在次日最高价突破pivot时买入，入场价=pivot
  模式C（+突破+放量）: 次日突破pivot 且 成交量>20日均量1.3倍 才买入
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
    print("  改进版回测：对比三种入场模式", flush=True)
    print("=" * 72, flush=True)

    config = ConfigManager()
    db = DatabaseManager(config)

    all_dates = [r["trade_date"] for r in db.query(
        "SELECT DISTINCT trade_date FROM stock_daily ORDER BY trade_date ASC"
    )]
    warmup_skip = 65
    use_ma120 = len(all_dates) >= 180
    backtest_dates = all_dates[warmup_skip:]
    signal_dates = backtest_dates[:-4]  # 多留1天给持有期

    params = BreakoutParams()
    params.min_amt_ma20 = 8e4
    params.rs_quantile_max = 0.97
    params.min_signal_score = 60.0
    params.top_k = 15
    strategy = BreakoutStrategy(db=db, params=params)

    print("  计算因子...", flush=True)
    raw_daily, raw_basic = strategy._load_data(all_dates[-1])
    features = strategy._compute_features(raw_daily, raw_basic, all_dates[-1])
    print(f"  因子行数: {len(features)}", flush=True)

    # 构建完整价格+量能查找表
    price_df = features[["ts_code", "trade_date", "open", "high", "low", "close", "vol", "vol_ma20", "pivot"]].copy()
    price_df = price_df.sort_values(["ts_code", "trade_date"]).reset_index(drop=True)
    price_map = {}
    for code, sub in price_df.groupby("ts_code"):
        s = sub.sort_values("trade_date").reset_index(drop=True)
        s["date_str"] = s["trade_date"].dt.strftime("%Y%m%d")
        price_map[code] = s

    # 三种模式分别跑
    modes = {
        "A_无条件买入": {"need_breakout": False, "need_volume": False},
        "B_突破确认":   {"need_breakout": True,  "need_volume": False},
        "C_突破+放量":  {"need_breakout": True,  "need_volume": True},
    }

    all_results = {}

    for mode_name, mode_cfg in modes.items():
        trades = {1: [], 2: [], 3: []}
        signal_count = 0
        skipped_no_breakout = 0
        skipped_no_volume = 0

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

                # 信号日数据
                pivot = float(row.get("pivot", 0))
                if pivot <= 0:
                    continue

                # T+1 日数据
                t1_row = sub.loc[idx + 1]
                t1_high = float(t1_row["high"])
                t1_open = float(t1_row["open"])
                t1_vol = float(t1_row["vol"])
                t1_vol_ma20 = float(t1_row["vol_ma20"]) if pd.notna(t1_row.get("vol_ma20")) else 0

                if t1_open <= 0:
                    continue

                # ── 模式判断 ──
                if mode_cfg["need_breakout"]:
                    if t1_high < pivot * 1.002:  # 最高价未突破pivot+0.2%缓冲
                        skipped_no_breakout += 1
                        continue
                    entry_price = pivot * 1.002  # 以触发价入场
                    # 入场价不能高于当日最高价（实际不可能低买到）
                    if entry_price > t1_high:
                        skipped_no_breakout += 1
                        continue
                    # 不追高：入场价不能超过pivot的0.8%
                    if entry_price > pivot * 1.008:
                        skipped_no_breakout += 1
                        continue
                    # 当日涨幅不超过5%
                    if t1_open > 0 and (t1_high / t1_open - 1) > 0.05:
                        skipped_no_breakout += 1
                        continue
                else:
                    entry_price = t1_open  # 无条件开盘价买入

                if mode_cfg["need_volume"]:
                    if t1_vol_ma20 > 0 and t1_vol / t1_vol_ma20 < 1.3:
                        skipped_no_volume += 1
                        continue

                signal_count += 1
                for n in [1, 2, 3]:
                    t_idx = idx + 1 + n
                    if t_idx < len(sub):
                        exit_close = float(sub.loc[t_idx, "close"])
                        trades[n].append(exit_close / entry_price - 1.0)

        all_results[mode_name] = {
            "signal_count": signal_count,
            "skipped_breakout": skipped_no_breakout,
            "skipped_volume": skipped_no_volume,
            "trades": trades,
        }

    # ── 输出对比 ──
    print(f"\n{'=' * 72}", flush=True)
    print("  三种入场模式对比", flush=True)
    print(f"{'=' * 72}", flush=True)

    for mode_name, data in all_results.items():
        print(f"\n  --- {mode_name} ---", flush=True)
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

    # ── 提升幅度对比 ──
    print(f"\n{'=' * 72}", flush=True)
    print("  效果提升对比（T+1）", flush=True)
    print(f"{'=' * 72}", flush=True)
    base = all_results["A_无条件买入"]
    for mode_name, data in all_results.items():
        r_base = np.array(base["trades"][1])
        r_this = np.array(data["trades"][1])
        if len(r_base) == 0 or len(r_this) == 0:
            continue
        wr_base = (r_base > 0).mean()
        wr_this = (r_this > 0).mean()
        avg_base = r_base.mean()
        avg_this = r_this.mean()
        pf_base_gw = r_base[r_base > 0].sum()
        pf_base_gl = -r_base[r_base < 0].sum()
        pf_base = pf_base_gw / pf_base_gl if pf_base_gl > 0 else 0
        pf_this_gw = r_this[r_this > 0].sum()
        pf_this_gl = -r_this[r_this < 0].sum()
        pf_this = pf_this_gw / pf_this_gl if pf_this_gl > 0 else 0

        wr_delta = wr_this - wr_base
        avg_delta = avg_this - avg_base
        print(f"  {mode_name:20s}  "
              f"胜率={wr_this:.2%}({wr_delta:+.2%})  "
              f"均收={avg_this:.4%}({avg_delta:+.4%})  "
              f"PF={pf_this:.2f}  "
              f"信号数={len(r_this)}", flush=True)

    print(f"\n{'=' * 72}", flush=True)
    print("  完成", flush=True)
    print(f"{'=' * 72}", flush=True)


if __name__ == "__main__":
    main()
