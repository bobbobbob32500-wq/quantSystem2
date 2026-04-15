import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try: sys.stdout.reconfigure(line_buffering=True)
except: pass

import glob, numpy as np, pandas as pd
from datetime import datetime, time as dt_time
from src.core.config import ConfigManager
from src.core.database import DatabaseManager
from src.modules.breakout_strategy import BreakoutStrategy, BreakoutParams

def load_intraday_cache(cache_dir="data/intraday_cache"):
    files = glob.glob(os.path.join(cache_dir, "*.parquet"))
    result = {}
    for f in files:
        try:
            df = pd.read_parquet(f)
            sym = str(df["symbol"].iloc[0])
            if sym not in result: result[sym] = df
            else: result[sym] = pd.concat([result[sym], df], ignore_index=True)
        except: continue
    for sym in result: result[sym] = result[sym].sort_values("trade_time").reset_index(drop=True)
    return result

def find_intraday_breakout(minute_df, trade_date_dash, pivot, buffer=0.002,
                           max_chase=0.008, max_intraday_gain=0.05,
                           volume_ma20=0, volume_confirm_ratio=1.2, hold_minutes=3):
    trigger = pivot * (1 + buffer)
    max_entry = pivot * (1 + max_chase)
    td_col = minute_df["trade_date"]
    if hasattr(td_col, "dt"): day_mask = td_col.dt.strftime("%Y-%m-%d") == trade_date_dash
    else: day_mask = td_col.astype(str).str[:10] == trade_date_dash
    day_bars = minute_df.loc[day_mask].sort_values("trade_time").reset_index(drop=True)
    if day_bars.empty: return False, None, None, None
    n = len(day_bars)
    open_price = float(day_bars.iloc[0].get("open", day_bars.iloc[0].get("close", 0)))
    if open_price <= 0: return False, None, None, None
    for i in range(n):
        bar = day_bars.iloc[i]
        bar_time = bar["trade_time"]
        if hasattr(bar_time, "time"): hm = bar_time.time()
        else: continue
        if hm < dt_time(9, 35) or hm > dt_time(14, 50): continue
        bar_high = float(bar.get("high", 0))
        bar_vol = float(bar.get("volume", bar.get("vol", 0)))
        if bar_high <= 0: continue
        if bar_high < trigger: continue
        entry_price = trigger
        if entry_price > max_entry or entry_price > bar_high: continue
        if (bar_high / open_price - 1) > max_intraday_gain: continue
        hold_ok = True
        if i + hold_minutes < n:
            for j in range(1, hold_minutes + 1):
                next_low = float(day_bars.iloc[i + j].get("low", 0))
                if next_low < trigger * 0.998: hold_ok = False; break
        else: hold_ok = False
        if not hold_ok: continue
        vol_ratio = 0.0
        if volume_ma20 > 0: vol_ratio = bar_vol / (volume_ma20 / 48.0)
        if vol_ratio < 1.0: continue
        return True, entry_price, bar_time, vol_ratio
    return False, None, None, None

def run_backtest(strategy, features, price_map, params, dates, use_ma120,
             intraday_data, need_breakout, need_volume, use_intraday):
    trades = {1: [], 2: [], 3: []}
    signal_count = 0; skipped_b = 0; skipped_v = 0
    iday_ok = 0; iday_no = 0; iday_miss = 0
    entry_times = []
    for td in dates:
        snapshot = strategy._build_snapshot(features, td)
        if snapshot.empty: continue
        filtered = strategy._layer_base_filter(snapshot)
        if filtered.empty: continue
        if use_ma120: filtered = strategy._layer_trend_filter(filtered)
        else:
            cond = filtered["ma20"].notna() & filtered["ma60"].notna() & (filtered["ma20"] > filtered["ma60"]) & (filtered["ma20_slope"].fillna(-1) > 0)
            filtered = filtered.loc[cond].copy()
        if filtered.empty: continue
        filtered = strategy._layer_strength_filter(filtered)
        if filtered.empty: continue
        cond4 = filtered["box_range"].notna() & (filtered["box_range"] <= params.box_max_range)
        if filtered["atr_ratio_q60"].notna().mean() > 0.3:
            cond4 = cond4 & (filtered["atr_ratio_q60"].fillna(0.5) <= params.atr_quantile_max)
        filtered = filtered.loc[cond4].copy()
        if filtered.empty: continue
        scored = strategy._compute_scores(filtered)
        min_score, top_k = strategy._market_gate(features, td)
        if min_score >= 999 or top_k <= 0: continue
        scored = scored[scored["signal_score"] >= min_score].copy()
        if scored.empty: continue
        scored = scored.sort_values("signal_score", ascending=False).head(top_k)
        for _, row in scored.iterrows():
            code = row["ts_code"]
            sub = price_map.get(code)
            if sub is None: continue
            match = sub.index[sub["date_str"] == td]
            if len(match) == 0: continue
            idx = match[0]
            if idx + 1 >= len(sub): continue
            pivot = float(row.get("pivot", 0))
            if pivot <= 0: continue
            t1 = sub.loc[idx + 1]
            t1_high = float(t1["high"]); t1_open = float(t1["open"])
            t1_vol = float(t1["vol"])
            t1_vma20 = float(t1["vol_ma20"]) if pd.notna(t1.get("vol_ma20")) else 0
            if t1_open <= 0: continue
            t1ds = sub.loc[idx+1, "date_str"]
            t1dd = t1ds[:4]+"-"+t1ds[4:6]+"-"+t1ds[6:8]
            if use_intraday:
                trigger = pivot * (1 + params.breakout_buffer)
                if t1_high < trigger: skipped_b += 1; continue
                sym6 = code.split(".")[0]
                mdf = intraday_data.get(sym6)
                if mdf is None or mdf.empty:
                    iday_miss += 1
                    ep = trigger
                    if ep > pivot*(1+params.breakout_max_chase): skipped_b += 1; continue
                    if t1_open>0 and (t1_high/t1_open-1)>params.max_intraday_gain: skipped_b += 1; continue
                    if t1_vma20>0 and t1_vol/t1_vma20<params.volume_confirm_ratio: skipped_v += 1; continue
                else:
                    ok, ep, et, vr = find_intraday_breakout(mdf, t1dd, pivot,
                        buffer=params.breakout_buffer, max_chase=params.breakout_max_chase,
                        max_intraday_gain=params.max_intraday_gain,
                        volume_ma20=t1_vma20, volume_confirm_ratio=params.volume_confirm_ratio, hold_minutes=3)
                    if not ok: iday_no += 1; continue
                    iday_ok += 1
                    if et is not None: entry_times.append(str(et))
            else:
                if need_breakout:
                    trigger = pivot * (1 + params.breakout_buffer)
                    if t1_high < trigger: skipped_b += 1; continue
                    ep = trigger
                    if ep > pivot*(1+params.breakout_max_chase): skipped_b += 1; continue
                    if t1_open>0 and (t1_high/t1_open-1)>params.max_intraday_gain: skipped_b += 1; continue
                else: ep = t1_open
                if need_volume:
                    if t1_vma20>0 and t1_vol/t1_vma20<params.volume_confirm_ratio: skipped_v += 1; continue
            signal_count += 1
            for n in [1,2,3]:
                ti = idx+1+n
                if ti < len(sub): trades[n].append(float(sub.loc[ti,"close"])/ep - 1.0)
    return {"n": signal_count, "sb": skipped_b, "sv": skipped_v,
            "iok": iday_ok, "ino": iday_no, "imiss": iday_miss,
            "trades": trades, "etimes": entry_times}
def main():
    print("=" * 80, flush=True)
    print("  INTRADAY CONFIRM BACKTEST", flush=True)
    print("=" * 80, flush=True)
    config = ConfigManager(); db = DatabaseManager(config)
    print("  Loading intraday cache...", flush=True)
    idata = load_intraday_cache()
    print(f"  Intraday: {len(idata)} stocks", flush=True)
    all_dates = [r["trade_date"] for r in db.query("SELECT DISTINCT trade_date FROM stock_daily ORDER BY trade_date ASC")]
    all_dates = [d.strftime("%Y%m%d") if hasattr(d, "strftime") else str(d) for d in all_dates]
    warmup_skip = 65; use_ma120 = len(all_dates) >= 180
    bd = all_dates[warmup_skip:]; total = len(bd); si = int(total * 0.7)
    ins = bd[:si]; outs = bd[si:-4]
    print(f"  In: {ins[0]}~{ins[-1]} ({len(ins)}d)", flush=True)
    print(f"  Out: {outs[0]}~{outs[-1]} ({len(outs)}d)", flush=True)
    params = BreakoutParams(); params.min_amt_ma20 = 8e4; params.rs_quantile_max = 0.97; params.min_signal_score = 60.0; params.top_k = 15
    strategy = BreakoutStrategy(db=db, params=params)
    print("  Computing features...", flush=True)
    raw_daily, raw_basic = strategy._load_data(all_dates[-1])
    features = strategy._compute_features(raw_daily, raw_basic, all_dates[-1])
    print(f"  Features: {len(features)} rows", flush=True)
    price_df = features[["ts_code","trade_date","open","high","low","close","vol","vol_ma20","pivot"]].copy()
    price_df = price_df.sort_values(["ts_code","trade_date"]).reset_index(drop=True)
    pm = {}
    for code, sub in price_df.groupby("ts_code"):
        s = sub.sort_values("trade_date").reset_index(drop=True)
        s["date_str"] = s["trade_date"].dt.strftime("%Y%m%d")
        pm[code] = s
    modes = [("A_daily_open",False,False,False), ("B_daily_breakout",True,False,False),
             ("C_daily_bk_vol",True,True,False), ("D_intraday_confirm",True,True,True)]
    ar = {}
    for sn, dates in [("IN",ins),("OUT",outs)]:
        sr = {}
        for mn,nb,nv,ui in modes:
            print(f"  Running {sn} {mn}...", flush=True)
            sr[mn] = run_backtest(strategy, features, pm, params, dates, use_ma120, idata, nb, nv, ui)
        ar[sn] = sr
    for sn in ["IN","OUT"]:
        print(f"
  == {sn} ==", flush=True)
        for mn,_,_,_ in modes:
            d = ar[sn][mn]
            print(f"  --- {mn} ---", flush=True)
            print(f"  Signals: {d["n"]}  SkipB: {d["sb"]}  SkipV: {d["sv"]}", flush=True)
            if d.get("iok",0)>0: print(f"  IntradayOK: {d["iok"]}  IntradayNO: {d["ino"]}  MissData: {d["imiss"]}", flush=True)
            for n in [1,2,3]:
                r = np.array(d["trades"][n]) if d["trades"][n] else np.array([])
                if len(r)==0: print(f"  T+{n}: no data", flush=True); continue
                wr=(r>0).mean(); avg=r.mean(); med=np.median(r)
                aw=r[r>0].mean() if (r>0).any() else 0
                al=r[r<0].mean() if (r<0).any() else 0
                pf=r[r>0].sum()/max(-r[r<0].sum(),1e-10)
                po=-aw/al if al<0 else 0
                print(f"  T+{n}: n={len(r)} WR={wr:.2%} Avg={avg:.4%} Med={med:.4%} PF={pf:.2f} Payoff={po:.2f}", flush=True)
    print("
  == T+1 SUMMARY (OUT) ==", flush=True)
    br = np.array(ar["OUT"]["A_daily_open"]["trades"][1])
    bwr = (br>0).mean() if len(br)>0 else 0
    bavg = br.mean() if len(br)>0 else 0
    for mn,_,_,_ in modes:
        r = np.array(ar["OUT"][mn]["trades"][1])
        if len(r)==0: continue
        wr=(r>0).mean(); avg=r.mean()
        pf=r[r>0].sum()/max(-r[r<0].sum(),1e-10)
        print(f"  {mn:>25}  n={len(r):>4}  WR={wr:.2%}({wr-bwr:+.2%})  Avg={avg:.4%}({avg-bavg:+.4%})  PF={pf:.2f}", flush=True)
    dd = ar["OUT"]["D_intraday_confirm"]
    if dd.get("etimes"):
        ts = dd["etimes"]
        print(f"
  Intraday entry time dist (OUT, {len(ts)} trades):", flush=True)
        hc = {}
        for t in ts:
            h = t[11:13] if len(t)>13 else "?"
            hc[h] = hc.get(h,0)+1
        for h in sorted(hc.keys()): print(f"    {h}:xx  {hc[h]:>3}", flush=True)
    print("
DONE", flush=True)

if __name__ == "__main__": main()