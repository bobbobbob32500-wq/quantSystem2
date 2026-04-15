# -*- coding: utf-8 -*-
"""
盘中买点确认机制回测

对比四种入场模式：
  模式A: 日线无条件买入（T+1开盘价入场）
  模式B: 日线突破确认（T+1最高价突破pivot，以触发价入场）
  模式C: 日线突破+放量确认
  模式D: 盘中分钟线突破确认（在分时数据中找到首次突破pivot的时刻，
         检查突破后维持、放量等盘中条件，以突破时刻价格入场）

模式D是核心验证：用分钟线模拟盘中实时监控，验证盘中确认是否能进一步提升胜率。
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    sys.stdout.reconfigure(line_buffering=True)
except Exception:
    pass

import glob
import numpy as np
import pandas as pd
from datetime import datetime, time as dt_time
from src.core.config import ConfigManager
from src.core.database import DatabaseManager
from src.modules.breakout_strategy import BreakoutStrategy, BreakoutParams


def load_intraday_cache(cache_dir="data/intraday_cache"):
    """加载所有分时缓存，返回 {symbol: DataFrame}"""
    files = glob.glob(os.path.join(cache_dir, "*.parquet"))
    result = {}
    for f in files:
        try:
            df = pd.read_parquet(f)
            sym = str(df["symbol"].iloc[0]) if "symbol" in df.columns else None
            if sym is None:
                basename = os.path.basename(f)
                sym = basename.split("_")[0]
            if sym not in result:
                result[sym] = df
            else:
                result[sym] = pd.concat([result[sym], df], ignore_index=True)
        except Exception:
            continue
    # 排序
    for sym in result:
        result[sym] = result[sym].sort_values("trade_time").reset_index(drop=True)
    return result


def find_intraday_breakout(minute_df, trade_date_str, pivot, buffer=0.002,
                           max_chase=0.008, max_intraday_gain=0.05,
                           volume_ma20=0, volume_confirm_ratio=1.2,
                           hold_minutes=3):
    """
    在某交易日的分钟线中寻找盘中突破买点。

    模拟盘中实时监控：
    1. 逐根5分钟K线扫描
    2. 当high突破trigger = pivot*(1+buffer)时
    3. 检查后续hold_minutes根K线是否维持在前高之上
    4. 检查量能是否达标
    5. 时间过滤：9:35前/14:50后不确认

    Returns:
        (confirmed, entry_price, entry_time, vol_ratio, confirm_type)
        confirmed=False时其余为None
    """
    trigger = pivot * (1 + buffer)
    max_entry = pivot * (1 + max_chase)

    # 筛选当日分钟线
    if "trade_date" in minute_df.columns:
        td_col = minute_df["trade_date"]
        if hasattr(td_col.dt, "strftime"):
            day_mask = td_col.dt.strftime("%Y-%m-%d") == trade_date_str
        else:
            day_mask = td_col.astype(str).str[:10] == trade_date_str
    else:
        day_mask = minute_df["trade_time"].dt.strftime("%Y-%m-%d") == trade_date_str

    day_bars = minute_df.loc[day_mask].copy()
    if day_bars.empty:
        return False, None, None, None, None

    day_bars = day_bars.sort_values("trade_time").reset_index(drop=True)
    n = len(day_bars)

    # 开盘价（用于涨幅限制）
    open_price = float(day_bars.iloc[0].get("open", day_bars.iloc[0].get("close", 0)))
    if open_price <= 0:
        return False, None, None, None, None

    # 当日涨幅限制
    if (day_bars["high"].max() / open_price - 1) > max_intraday_gain:
        # 整日涨幅过大，不追
        pass  # 逐根检查更精确

    for i in range(n):
        bar = day_bars.iloc[i]
        bar_time = bar["trade_time"]
        if hasattr(bar_time, "time"):
            hm = bar_time.time()
        else:
            continue

        # 时间过滤
        if hm < dt_time(9, 35) or hm > dt_time(14, 50):
            continue

        bar_high = float(bar.get("high", 0))
        bar_close = float(bar.get("close", 0))
        bar_vol = float(bar.get("volume", bar.get("vol", 0)))

        if bar_high <= 0:
            continue

        # 条件1: 突破触发价
        if bar_high < trigger:
            continue

        # 条件2: 入场价不追高
        entry_price = trigger
        if entry_price > max_entry:
            continue
        if entry_price > bar_high:
            continue

        # 条件3: 当日涨幅限制（用当前bar的high/open）
        if (bar_high / open_price - 1) > max_intraday_gain:
            continue

        # 条件4: 突破后维持（检查后续hold_minutes根K线）
        hold_ok = True
        if i + hold_minutes < n:
            for j in range(1, hold_minutes + 1):
                next_low = float(day_bars.iloc[i + j].get("low", 0))
                if next_low < trigger * 0.998:  # 允许0.2%的回撤容忍
                    hold_ok = False
                    break
        else:
            hold_ok = False  # 数据不足，无法确认维持

        if not hold_ok:
            continue

        # 条件5: 量能确认
        vol_ratio = 0.0
        if volume_ma20 > 0:
            # 累计到当前bar的成交量
            cum_vol = float(day_bars.iloc[:i+1]["volume"].sum()) if "volume" in day_bars.columns else 0
            # 用当前bar的量比（简化：用单根bar量/均量）
            vol_ratio = bar_vol / (volume_ma20 / 48.0) if volume_ma20 > 0 else 0  # 48个5分钟bar/天

        # 量能分级
        if vol_ratio >= volume_confirm_ratio:
            confirm_type = "breakout+volume"
        elif vol_ratio >= 1.0:
            confirm_type = "breakout"
        else:
            confirm_type = "breakout_low_vol"  # 缩量突破，降级但不完全过滤

        entry_time = bar_time
        return True, entry_price, entry_time, vol_ratio, confirm_type

    return False, None, None, None, None


def main():
    print("=" * 80, flush=True)
    print("  盘中买点确认机制回测", flush=True)
    print("  对比: 日线无条件 / 日线突破 / 日线突破+放量 / 盘中分钟线确认", flush=True)
    print("=" * 80, flush=True)

    config = ConfigManager()
    db = DatabaseManager(config)

    # ── 加载分时缓存 ──
    print("\n  加载分时数据缓存...", flush=True)
    intraday_data = load_intraday_cache()
    print(f"  分时数据: {len(intraday_data)} 只股票", flush=True)

    # ── 日线数据与因子 ──
    all_dates = [r["trade_date"] for r in db.query(
        "SELECT DISTINCT trade_date FROM stock_daily ORDER BY trade_date ASC"
    )]
    all_dates = [d.strftime("%Y%m%d") if hasattr(d, "strftime") else str(d) for d in all_dates]
    warmup_skip = 65
    use_ma120 = len(all_dates) >= 180
    backtest_dates = all_dates[warmup_skip:]
    signal_dates = backtest_dates[:-4]

    # 样本内/外划分
    total = len(backtest_dates)
    split_idx = int(total * 0.7)
    in_sample_dates = backtest_dates[:split_idx]
    out_sample_dates = backtest_dates[split_idx:-4]

    is_start, is_end = in_sample_dates[0], in_sample_dates[-1]
    os_start, os_end = out_sample_dates[0], out_sample_dates[-1]
    print(f"  样本内: {is_start} ~ {is_end} ({len(in_sample_dates)}天)", flush=True)
    print(f"  样本外: {os_start} ~ {os_end} ({len(out_sample_dates)}天)", flush=True)

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

    # 构建价格查找表
    price_df = features[["ts_code", "trade_date", "open", "high", "low", "close",
                         "vol", "vol_ma20", "pivot"]].copy()
    price_df = price_df.sort_values(["ts_code", "trade_date"]).reset_index(drop=True)
    price_map = {}
    for code, sub in price_df.groupby("ts_code"):
        s = sub.sort_values("trade_date").reset_index(drop=True)
        s["date_str"] = s["trade_date"].dt.strftime("%Y%m%d")
        price_map[code] = s

    # ── 四种模式回测 ──
    modes = {
        "A_日线无条件": {"need_breakout": False, "need_volume": False, "use_intraday": False},
        "B_日线突破":   {"need_breakout": True,  "need_volume": False, "use_intraday": False},
        "C_日线突破+放量": {"need_breakout": True,  "need_volume": True,  "use_intraday": False},
        "D_盘中分钟确认": {"need_breakout": True,  "need_volume": True,  "use_intraday": True},
    }

    all_results = {}

    for sample_name, dates in [("样本内", in_sample_dates), ("样本外", out_sample_dates)]:
        sample_results = {}

        for mode_name, mode_cfg in modes.items():
            trades = {1: [], 2: [], 3: []}
            signal_count = 0
            skipped_breakout = 0
            skipped_volume = 0
            intraday_confirmed = 0
            intraday_miss_data = 0
            intraday_no_confirm = 0
            e
