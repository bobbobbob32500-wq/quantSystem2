# -*- coding: utf-8 -*-
import sys, os, glob, json
import numpy as np, pandas as pd
from datetime import time as dt_time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.core.config import ConfigManager
from src.core.database import DatabaseManager
from src.modules.breakout_strategy import BreakoutStrategy, BreakoutParams

def load_intraday_cache(cache_dir='data/intraday_cache'):
    files = glob.glob(os.path.join(cache_dir, '*.parquet'))
    result = {}
    for f in files:
        try:
            df = pd.read_parquet(f)
            sym = str(df['symbol'].iloc[0])
            if sym not in result: result[sym] = df
            else: result[sym] = pd.concat([result[sym], df], ignore_index=True)
        except: continue
    for sym in result: result[sym] = result[sym].sort_values('trade_time').reset_index(drop=True)
    return result

def find_intraday_breakout(minute_df, trade_date_dash, pivot, buffer=0.002,
                           max_chase=0.008, max_intraday_gain=0.05,
                           volume_ma20=0, volume_confirm_ratio=1.2, hold_minutes=3):
    trigger = pivot * (1 + buffer)
    max_entry = pivot * (1 + max_chase)
    td_col = minute_df['trade_date']
    if hasattr(td_col, 'dt'):
        day_mask = td_col.dt.strftime('%Y-%m-%d') == trade_date_dash
    else:
        day_mask = td_col.astype(str).str[:10] == trade_date_dash
    day_bars = minute_df.loc[day_mask].sort_values('trade_time').reset_index(drop=True)
    if day_bars.empty: return False, None, None, None
    n = len(day_bars)
    open_price = float(day_bars.iloc[0].get('open', day_bars.iloc[0].get('close', 0)))
    if open_price <= 0: return False, None, None, None
    for i in range(n):
        bar = day_bars.iloc[i]
        bar_time = bar['trade_time']
        if hasattr(bar_time, 'time'): hm = bar_time.time()
        else: continue
        if hm < dt_time(9, 35) or hm > dt_time(14, 50): continue
        bar_high = float(bar.get('high', 0))
        bar_vol = float(bar.get('volume', bar.get('vol', 0)))
        if bar_high <= 0: continue
        if bar_high < trigger: continue
        entry_price = trigger
        if entry_price > max_entry or entry_price > bar_high: continue
        if (bar_high / open_price - 1) > max_intraday_gain: continue
        hold_ok = True
        if i + hold_minutes < n:
            for j in range(1, hold_minutes + 1):
                next_low = float(day_bars.iloc[i + j].get('low', 0))
                if next_low < trigger * 0.998: hold_ok = False; break
        else: hold_ok = False
        if not hold_ok: continue
        vol_ratio = 0.0
        if volume_ma20 > 0: vol_ratio = bar_vol / (volume_ma20 / 48.0)
        if vol_ratio < 1.0: continue
        return True, entry_price, bar_time, vol_ratio
    return False, None, None, None
