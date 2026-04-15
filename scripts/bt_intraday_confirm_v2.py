# -*- coding: utf-8 -*-
import sys, os, glob, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try: sys.stdout.reconfigure(line_buffering=True)
except: pass
import numpy as np, pandas as pd
from datetime import time as dt_time
from src.core.config import ConfigManager
from src.core.database import DatabaseManager
from src.modules.breakout_strategy import BreakoutStrategy, BreakoutParams
from scripts.bt_intraday_core import load_intraday_cache, find_intraday_breakout

def run_mode(st, feat, pm, params, dates, ma120, idata, need_breakout, need_volume, use_intraday):
    trades = {1: [], 2: [], 3: []}
    sc = 0; sb = 0; sv = 0; iok = 0; ino = 0; imiss = 0; etimes = []
    for td in dates:
        snap = st._build_snapshot(feat, td)
        if snap.empty: continue
        flt = st._layer_base_filter(snap)
        if flt.empty: continue
        if ma120: flt = st._layer_trend_filter(flt)
        else:
            c = flt["ma20"].notna() & flt["ma60"].notna() & (flt["ma20"] > flt["ma60"]) & (flt["ma20_slope"].fillna(-1) > 0)
            flt = flt.loc[c].copy()
        if flt.empty: continue
        flt = st._layer_strength_filter(flt)
        if flt.empty: continue
        c4 = flt["box_range"].notna() & (flt["box_range"] <= params.box_max_range)
        if flt["atr_ratio_q60"].notna().mean() > 0.3:
            c4 = c4 & (flt["atr_ratio_q60"].fillna(0.5) <= params.atr_quantile_max)
        flt = flt.loc[c4].copy()
        if flt.empty: continue
        sc2 = st._compute_scores(flt); ms, tk = st._market_gate(feat, td)
        if ms >= 999 or tk <= 0: continue
        sc2 = sc2[sc2["signal_score"] >= ms].copy()
        if sc2.empty: continue
        sc2 = sc2.sort_values("signal_score", ascending=False).head(tk)
        for _, row in sc2.iterrows():
            code = row["ts_code"]; sub = pm.get(code)
            if sub is None: continue
            m = sub.index[sub["date_str"] == td]
            if len(m) == 0: continue
            idx = m[0]
            if idx + 1 >= len(sub): continue
            pivot = float(row.get("pivot", 0))
            if pivot <= 0: continue
            t1 = sub.loc[idx + 1]
            t1h = float(t1["high"]); t1o = float(t1["open"])
            t1v = float(t1["vol"]); t1vm = float(t1["vol_ma20"]) if pd.notna(t1.get("vol_ma20")) else 0
            if t1o <= 0: continue
            t1ds = sub.loc[idx+1, "date_str"]; t1dd = t1ds[:4]+"-"+t1ds[4:6]+"-"+t1ds[6:8]
            if use_intraday:
                trig = pivot * (1 + params.breakout_buffer)
                if t1h < trig: sb += 1; continue
                s6 = code.split(".")[0]; mdf = idata.get(s6)
                if mdf is None or mdf.empty:
                    imiss += 1; ep = trig
                    if ep > pivot*(1+params.breakout_max_chase): sb += 1; continue
                    if t1o>0 and (t1h/t1o-1)>params.max_intraday_gain: sb += 1; continue
                    if t1vm>0 and t1v/t1vm<params.volume_confirm_ratio: sv += 1; continue
                else:
                    ok, ep, ett, vr = find_intraday_breakout(mdf, t1dd, pivot, buffer=params.breakout_buffer, max_chase=params.breakout_max_chase, max_intraday_gain=params.max_intraday_gain, volume_ma20=t1vm, volume_confirm_ratio=params.volume_confirm_ratio, hold_minutes=3)
                    if not ok: ino += 1; continue
                    iok += 1
                    if ett is not None: etimes.append(str(ett))
            else:
                if need_breakout:
                    trig = pivot * (1 + params.breakout_buffer)
                    if t1h < trig: sb += 1; continue
                    ep = trig
                    if ep > pivot*(1+params.breakout_max_chase): sb += 1; continue
                    if t1o>0 and (t1h/t1o-1)>params.max_intraday_gain: sb += 1; continue
                else: ep = t1o
                if need_volume:
                    if t1vm>0 and t1v/t1vm<params.volume_confirm_ratio: sv += 1; continue
            sc += 1
            for n in [1,2,3]:
                ti = idx+1+n
                if ti < len(sub): trades[n].append(float(sub.loc[ti,"close"])/ep - 1.0)
    return {"n": sc, "sb": sb, "sv": sv, "iok": iok, "ino": ino, "imiss": imiss, "trades": trades, "etimes": etimes}

def main():
    print("=" * 80, flush=True)
    print("  INTRADAY CONFIRM BACKTEST", flush=True)
    print("=" * 80, flush=True)
    config = ConfigManager(); db = DatabaseManager(config)
    params = BreakoutParams(); params.min_amt_ma20 = 8e4; params.rs_quantile_max = 0.97; params.min_signal_score = 60.0; params.top_k = 15
    st = BreakoutStrategy(db=db, params=params)
    ad = [r["trade_date"] for r in db.query("SELECT DISTINCT trade_date FROM stock_daily ORDER BY trade_date ASC")]
    ad = [d.strftime("%Y%m%d") if hasattr(d, "strftime") else str(d) for d in ad]
    ws = 65; ma120 = len(ad) >= 180; bd = ad[ws:]; tot = len(bd); si = int(tot * 0.7)
    ins = bd[:si]; outs = bd[si:-4]
    print(f"  In: {ins[0]}~{ins[-1]} ({len(ins)}d)", flush=True)
    print(f"  Out: {outs[0]}~{outs[-1]} ({len(outs)}d)", flush=True)
    print("  Computing features...", flush=True)
    rd, rb = st._load_data(ad[-1]); feat = st._compute_features(rd, rb, ad[-1])
    print(f"  Features: {len(feat)} rows", flush=True)
    pdf = feat[["ts_code","trade_date","open","high","low","close","vol","vol_ma20","pivot"]].copy()
    pdf = pdf.sort_values(["ts_code","trade_date"]).reset_index(drop=True)
    pm = {}
    for code, sub in pdf.groupby("ts_code"):
        s = sub.sort_values("trade_date").reset_index(drop=True)
        s["date_str"] = s["trade_date"].dt.strftime("%Y%m%d")
        pm[code] = s
    print("  Loading intraday cache...", flush=True)
    idata = load_intraday_cache()
    print(f"  Intraday: {len(idata)} stocks", flush=True)
    modes = [("A_daily_open",False,False,False), ("B_daily_breakout",True,False,False), ("C_daily_bk_vol",True,True,False), ("D_intraday_confirm",True,True,True)]
    ar = {}
    for sn, dates in [("IN",ins),("OUT",outs)]:
        sr = {}
        for mn,nb2,nv2,ui2 in modes:
            print(f"  Running {sn} {mn}...", flush=True)
            sr[mn] = run_mode(st, feat, pm, params, dates, ma120, idata, nb2, nv2, ui2)
        ar[sn] = sr
    # Save results
    out = {}
    for sn in ["IN","OUT"]:
        out[sn] = {}
        for mn,_,_,_ in modes:
            d = ar[sn][mn]
            out[sn][mn] = {"n": d["n"], "sb": d["sb"], "sv": d["sv"], "iok": d["iok"], "ino": d["ino"], "imiss": d["imiss"],
                           "t1": [float(x) for x in d["trades"][1]], "t2": [float(x) for x in d["trades"][2]], "t3": [float(x) for x in d["trades"][3]], "etimes": d["etimes"]}
    os.makedirs("output", exist_ok=True)
    with open("output/bt_ic_result.json", "w") as f2:
        json.dump(out, f2, indent=2)
    print("  Results saved to output/bt_ic_result.json", flush=True)
    # Print results
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
                aw=r[r>0].mean() if (r>0).any() else 0; al=r[r<0].mean() if (r<0).any() else 0
                pf=r[r>0].sum()/max(-r[r<0].sum(),1e-10); po=-aw/al if al<0 else 0
                print(f"  T+{n}: n={len(r)} WR={wr:.2%} Avg={avg:.4%} Med={med:.4%} PF={pf:.2f} Payoff={po:.2f}", flush=True)
    print("
  == T+1 SUMMARY (OUT) ==", flush=True)
    br = np.array(ar["OUT"]["A_daily_open"]["trades"][1])
    bwr = (br>0).mean() if len(br)>0 else 0; bavg = br.mean() if len(br)>0 else 0
    for mn,_,_,_ in modes:
        r = np.array(ar["OUT"][mn]["trades"][1])
        if len(r)==0: continue
        wr=(r>0).mean(); avg=r.mean(); pf=r[r>0].sum()/max(-r[r<0].sum(),1e-10)
        print(f"  {mn:>25}  n={len(r):>4}  WR={wr:.2%}({wr-bwr:+.2%})  Avg={avg:.4%}({avg-bavg:+.4%})  PF={pf:.2f}", flush=True)
    dd = ar["OUT"]["D_intraday_confirm"]
    if dd.get("etimes"):
        ts = dd["etimes"]; print(f"
  Intraday entry time dist (OUT, {len(ts)} trades):", flush=True)
        hc = {}
        for t in ts: h = t[11:13] if len(t)>13 else "?"; hc[h] = hc.get(h,0)+1
        for h in sorted(hc.keys()): print(f"    {h}:xx  {hc[h]:>3}", flush=True)
    print("
DONE", flush=True)

if __name__ == "__main__": main()
