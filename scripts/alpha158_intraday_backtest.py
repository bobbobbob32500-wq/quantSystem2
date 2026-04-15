# -*- coding: utf-8 -*-
"""Alpha158 + 盘中买点确认 回测（优化版）"""
from __future__ import annotations
import sys, os, glob, json
from pathlib import Path
from datetime import time as dt_time
import numpy as np, pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.core.config import ConfigManager
from src.core.database import DatabaseManager
from src.modules.stock_selector import StockSelector
from src.modules.industry_cycle import IndustryCycleDetector


def load_intraday_cache(cache_dir="data/intraday_cache"):
    files = glob.glob(os.path.join(cache_dir, "*.parquet"))
    result = {}
    for f in files:
        try:
            df = pd.read_parquet(f)
            sym = str(df["symbol"].iloc[0])
            if sym not in result:
                result[sym] = df
            else:
                result[sym] = pd.concat([result[sym], df], ignore_index=True)
        except:
            continue
    for sym in result:
        result[sym] = result[sym].sort_values("trade_time").reset_index(drop=True)
    return result


def find_intraday_entry(minute_df, trade_date_dash, ref_price, buffer=0.001,
                        max_chase=0.015, max_intraday_gain=0.04,
                        volume_ma20=0, volume_confirm_ratio=1.0,
                        hold_minutes=3, require_volume=False):
    """
    Alpha158盘中买点确认
    
    与突破策略不同，Alpha158选出的股票不一定在突破前高。
    盘中确认逻辑：
    1. T+1开盘不追高（open <= ref_price * 1.01）
    2. 盘中价格从低点回升超过ref_price * (1+buffer)（确认止跌回升）
    3. 回升后维持3根K线
    4. 放量确认
    """
    trigger = ref_price * (1 + buffer)
    max_entry = ref_price * (1 + max_chase)
    td_col = minute_df["trade_date"]
    if hasattr(td_col, "dt"):
        day_mask = td_col.dt.strftime("%Y-%m-%d") == trade_date_dash
    else:
        day_mask = td_col.astype(str).str[:10] == trade_date_dash
    day_bars = minute_df.loc[day_mask].sort_values("trade_time").reset_index(drop=True)
    if day_bars.empty:
        return False, None
    n = len(day_bars)
    open_price = float(day_bars.iloc[0].get("open", day_bars.iloc[0].get("close", 0)))
    if open_price <= 0:
        return False, None
    # 开盘不追高：T+1开盘不超过ref_price的1%
    if open_price > ref_price * 1.01:
        return False, None
    
    # 找盘中最低点
    intra_low = float(day_bars["low"].min())
    # 要求盘中先跌后涨（V型或U型回升）
    # 找到最低点位置
    low_idx = int(day_bars["low"].values.argmin())
    
    # 从最低点之后寻找回升确认
    for i in range(max(0, low_idx), n):
        bar = day_bars.iloc[i]
        bar_time = bar["trade_time"]
        if hasattr(bar_time, "time"):
            hm = bar_time.time()
        else:
            continue
        if hm < dt_time(9, 35) or hm > dt_time(14, 50):
            continue
        bar_close = float(bar.get("close", 0))
        bar_high = float(bar.get("high", 0))
        bar_vol = float(bar.get("volume", bar.get("vol", 0)))
        if bar_close <= 0:
            continue
        
        # 回升确认：收盘价站上trigger
        if bar_close < trigger:
            continue
        
        entry_price = min(bar_close, max_entry)
        if entry_price > max_entry:
            continue
        if (entry_price / open_price - 1) > max_intraday_gain:
            continue
        
        # 维持确认：后续3根K线收盘价均 > trigger * 0.998
        hold_ok = True
        if i + hold_minutes < n:
            for j in range(1, hold_minutes + 1):
                next_close = float(day_bars.iloc[i + j].get("close", 0))
                if next_close < trigger * 0.998:
                    hold_ok = False
                    break
        else:
            hold_ok = False
        if not hold_ok:
            continue
        
        # 放量确认
        vol_ratio = 0.0
        if volume_ma20 > 0:
            vol_ratio = bar_vol / (volume_ma20 / 48.0)
        if require_volume and vol_ratio < volume_confirm_ratio:
            continue
        
        return True, entry_price
    return False, None


def main():
    config = ConfigManager()
    db = DatabaseManager(config)
    selector = StockSelector(db=db, config=config)

    all_dates = [r["trade_date"] for r in db.query(
        "SELECT DISTINCT trade_date FROM stock_daily ORDER BY trade_date ASC"
    )]
    all_dates = [d.strftime("%Y%m%d") if hasattr(d, "strftime") else str(d) for d in all_dates]

    print("加载盘中5分钟线...")
    intraday = load_intraday_cache()
    intra_dates = set()
    for sym, df in intraday.items():
        for d in df["trade_date"].unique():
            intra_dates.add(str(d)[:10].replace("-", ""))
    print(f"  {len(intraday)} 只股票, {len(intra_dates)} 天")

    end_idx = len(all_dates) - 1
    signal_dates = [d for d in all_dates[end_idx - 40 : end_idx - 5] if d in intra_dates]
    print(f"  可用信号日: {len(signal_dates)}天")

    # 预加载价格
    print("预加载价格...")
    price_map = {}
    for r in db.query(
        "SELECT ts_code, trade_date, open, close, high, vol FROM stock_daily WHERE trade_date >= ? AND trade_date <= ?",
        (signal_dates[0], all_dates[min(end_idx + 10, len(all_dates) - 1)]),
    ):
        key = r["ts_code"]
        if key not in price_map:
            price_map[key] = {}
        ds = r["trade_date"].strftime("%Y%m%d") if hasattr(r["trade_date"], "strftime") else str(r["trade_date"])
        price_map[key][ds] = {"open": float(r["open"]), "close": float(r["close"]), "high": float(r["high"]), "vol": float(r["vol"])}

    stock_industry = {}
    for r in db.query("SELECT ts_code, industry FROM stock_basic WHERE industry IS NOT NULL"):
        stock_industry[r["ts_code"]] = r["industry"]

    detector = IndustryCycleDetector(db, lookback=20, trend_window=5)

    # 预计算选股结果
    print("预计算Alpha158选股...")
    daily_picks = {}  # td -> [(ts_code, industry, td_high, buy_open, sell_close, vol_20, ind_weight)]
    horizon = 2

    for i, td in enumerate(signal_dates):
        if (i + 1) % 10 == 0:
            print(f"  {i+1}/{len(signal_dates)}...", flush=True)
        try:
            selected = selector._run_alpha158_selection(td)
        except:
            continue
        if not selected:
            continue
        top5 = selected[:5]

        td_idx = all_dates.index(td)
        if td_idx + 1 + horizon >= len(all_dates):
            continue
        buy_date = all_dates[td_idx + 1]
        sell_date = all_dates[td_idx + horizon]

        ind_weights = {}
        try:
            ind_weights = detector.get_industry_weights(td, all_dates)
        except:
            pass

        picks = []
        for rec in top5:
            ts_code = rec["ts_code"]
            industry = rec.get("industry", stock_industry.get(ts_code, ""))
            td_close = price_map.get(ts_code, {}).get(td, {}).get("close")
            td_high = price_map.get(ts_code, {}).get(td, {}).get("high")
            buy_open = price_map.get(ts_code, {}).get(buy_date, {}).get("open")
            sell_close = price_map.get(ts_code, {}).get(sell_date, {}).get("close")
            if not td_close or not buy_open or not sell_close or float(buy_open) <= 0:
                continue
            # 20日均量
            vols = []
            for offset in range(1, 21):
                d_idx = td_idx - offset
                if d_idx >= 0:
                    v = price_map.get(ts_code, {}).get(all_dates[d_idx], {}).get("vol", 0)
                    if v > 0:
                        vols.append(v)
            vol_20 = np.mean(vols) if vols else 0
            ind_w = ind_weights.get(industry, 1.0)
            picks.append((ts_code, industry, td_close, buy_open, sell_close, vol_20, ind_w))
        daily_picks[td] = picks

    print("预计算完成\n")

    # 回测各模式
    mode_rets = {"A_open": [], "B_breakout": [], "C_bk_vol": [], "D_bk_vol_ind": []}

    for td, picks in daily_picks.items():
        buy_date = all_dates[all_dates.index(td) + 1]
        buy_date_dash = f"{buy_date[:4]}-{buy_date[4:6]}-{buy_date[6:8]}"

        for ts_code, industry, td_close, buy_open, sell_close, vol_20, ind_w in picks:
            sell_close_f = float(sell_close)

            # A: 开盘买入
            ret_a = (sell_close_f - float(buy_open)) / float(buy_open)
            mode_rets["A_open"].append(ret_a)

            # 盘中数据
            sym_key = ts_code.replace(".SH", "").replace(".SZ", "")
            if sym_key not in intraday:
                continue

            # B: 盘中回升确认（不要求放量）
            ok, ep = find_intraday_entry(
                intraday[sym_key], buy_date_dash, ref_price=td_close,
                buffer=0.001, max_chase=0.015, max_intraday_gain=0.04,
                volume_ma20=vol_20, volume_confirm_ratio=1.0,
                hold_minutes=3, require_volume=False,
            )
            if ok:
                mode_rets["B_breakout"].append((sell_close_f - ep) / ep)

            # C: 盘中回升+放量
            ok, ep = find_intraday_entry(
                intraday[sym_key], buy_date_dash, ref_price=td_close,
                buffer=0.001, max_chase=0.015, max_intraday_gain=0.04,
                volume_ma20=vol_20, volume_confirm_ratio=1.0,
                hold_minutes=3, require_volume=True,
            )
            if ok:
                mode_rets["C_bk_vol"].append((sell_close_f - ep) / ep)
                # D: +行业周期
                if ind_w > 0.7:
                    mode_rets["D_bk_vol_ind"].append((sell_close_f - ep) / ep)

    # 输出
    print("=" * 70)
    print(f"Alpha158 + 盘中买点确认 回测 (T+{horizon}卖出)")
    print(f"信号区间: {signal_dates[0]} ~ {signal_dates[-1]} ({len(signal_dates)}天)")
    print("=" * 70)
    print(f"\n{'模式':<30} {'信号':>5} {'胜率':>7} {'均收':>7} {'中位':>7} {'PF':>6}")
    print("-" * 70)

    labels = {
        "A_open": "T+1开盘买入(基线)",
        "B_breakout": "盘中回升确认",
        "C_bk_vol": "盘中回升+放量",
        "D_bk_vol_ind": "盘中回升+放量+行业周期",
    }
    out = {}
    for k, rets in mode_rets.items():
        if not rets:
            continue
        n = len(rets)
        wr = sum(1 for r in rets if r > 0) / n
        mr = np.mean(rets)
        med = np.median(rets)
        gains = sum(r for r in rets if r > 0)
        losses = -sum(r for r in rets if r < 0)
        pf = gains / (losses + 1e-8)
        print(f"{labels[k]:<30} {n:>5} {wr:>7.1%} {mr:>7.2%} {med:>7.2%} {pf:>6.2f}")
        out[k] = {"n": n, "win_rate": float(wr), "mean_ret": float(mr), "pf": float(pf)}

    os.makedirs(ROOT / "output", exist_ok=True)
    with open(ROOT / "output" / "alpha158_intraday_backtest.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"\n结果已保存到 output/alpha158_intraday_backtest.json")


if __name__ == "__main__":
    main()
