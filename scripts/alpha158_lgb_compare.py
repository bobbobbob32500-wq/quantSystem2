# -*- coding: utf-8 -*-
"""Alpha158 LightGBM vs IC加权 对比回测（预计算因子版）"""
from __future__ import annotations
import sys, os, json
from pathlib import Path
import numpy as np
import pandas as pd
import lightgbm as lgb

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.core.config import ConfigManager
from src.core.database import DatabaseManager
from src.modules.stock_selector import StockSelector

config = ConfigManager()
db = DatabaseManager(config)
selector = StockSelector(db=db, config=config)

# 加载LGB模型
with open(ROOT / "models" / "alpha158_lgb_config.json", "r") as f:
    lgb_config = json.load(f)
lgb_model = lgb.Booster(model_file=str(ROOT / "models" / "alpha158_lgb_model.txt"))
lgb_feature_cols = lgb_config["feature_cols"]

# 交易日
all_dates = [r["trade_date"] for r in db.query(
    "SELECT DISTINCT trade_date FROM stock_daily ORDER BY trade_date ASC"
)]
all_dates = [d.strftime("%Y%m%d") if hasattr(d, "strftime") else str(d) for d in all_dates]

end_idx = len(all_dates) - 1
signal_dates = all_dates[end_idx - 65 : end_idx - 5]
print(f"信号日: {signal_dates[0]} ~ {signal_dates[-1]} ({len(signal_dates)}天)")

# 预加载价格
price_map = {}
for r in db.query(
    "SELECT ts_code, trade_date, open, close FROM stock_daily WHERE trade_date >= ? AND trade_date <= ?",
    (signal_dates[0], all_dates[min(end_idx + 10, len(all_dates) - 1)]),
):
    key = r["ts_code"]
    if key not in price_map:
        price_map[key] = {}
    ds = r["trade_date"].strftime("%Y%m%d") if hasattr(r["trade_date"], "strftime") else str(r["trade_date"])
    price_map[key][ds] = {"open": float(r["open"]), "close": float(r["close"])}

# 预计算所有信号日的因子+评分
print("预计算因子...")
daily_data = {}  # td -> list of (ts_code, factor_dict, ic_score, lgb_score)

for i, td in enumerate(signal_dates):
    if (i + 1) % 10 == 0:
        print(f"  {i+1}/{len(signal_dates)}...", flush=True)
    
    stock_list = selector.get_stock_list(end_date=td, point_in_time=False)
    main_board = (
        stock_list["ts_code"].str.startswith("60") & stock_list["ts_code"].str.endswith(".SH")
    ) | (
        stock_list["ts_code"].str.startswith("00") & stock_list["ts_code"].str.endswith(".SZ")
    ) | (
        stock_list["ts_code"].str.startswith("001") & stock_list["ts_code"].str.endswith(".SZ")
    )
    stock_list = stock_list[main_board]
    stock_list = stock_list[~stock_list["name"].str.contains("ST|st|退", na=False)]

    all_factors = []
    for _, row in stock_list.iterrows():
        ts_code = row["ts_code"]
        try:
            rows = db.query(
                "SELECT close, open, high, low, vol, amount FROM stock_daily "
                "WHERE ts_code = ? AND trade_date <= ? ORDER BY trade_date DESC LIMIT 61",
                (ts_code, td),
            )
            if not rows or len(rows) < 61:
                continue
            daily_df = pd.DataFrame(rows).iloc[::-1]
            close = daily_df["close"].values.astype(float)
            high = daily_df["high"].values.astype(float)
            low = daily_df["low"].values.astype(float)
            vol = daily_df["vol"].values.astype(float)
            amount = daily_df["amount"].values.astype(float)
            n = len(close)
            if close[-1] <= 0:
                continue
            f = selector._compute_alpha158_factors(close, high, low, vol, amount, n)
            if len(f) < 10:
                continue
            if f.get("_amount", 0) < 100000:
                continue
            if f.get("_vol30", 0) > 0.6:
                continue
            if f.get("_MA5", 0) <= f.get("_MA20", 0):
                continue
            if f.get("_ROC5", 0) < -0.02:
                continue
            f["ts_code"] = ts_code
            all_factors.append(f)
        except Exception:
            continue

    if not all_factors:
        daily_data[td] = []
        continue

    fdf = pd.DataFrame(all_factors)
    factor_cols = [c for c in fdf.columns if c in selector.ALPHA158_WEIGHTS]
    for col in factor_cols:
        vals = fdf[col].values.astype(float)
        m = np.nanmean(vals)
        s = np.nanstd(vals)
        if s > 1e-8:
            fdf[col] = (vals - m) / s
        else:
            fdf[col] = 0.0

    # IC加权评分
    ic_score = np.zeros(len(fdf))
    for fname, w in selector.ALPHA158_WEIGHTS.items():
        if fname in fdf.columns:
            ic_score += fdf[fname].fillna(0).values * w

    # LGB评分
    X_pred = pd.DataFrame(index=fdf.index)
    for c in lgb_feature_cols:
        if c in fdf.columns:
            X_pred[c] = fdf[c].fillna(0.0)
        else:
            X_pred[c] = 0.0
    lgb_score = lgb_model.predict(X_pred)

    daily_data[td] = list(zip(
        fdf["ts_code"].values,
        ic_score,
        lgb_score,
    ))

print("预计算完成\n")

# 回测函数
def backtest_mode(score_fn, horizons, top_n=5):
    results = {}
    for h in horizons:
        rets = []
        for td in signal_dates:
            items = daily_data.get(td, [])
            if not items:
                continue
            # 评分
            scored = [(ts, score_fn(ic, lgb)) for ts, ic, lgb in items]
            scored.sort(key=lambda x: -x[1])
            top = scored[:top_n]

            td_idx = all_dates.index(td)
            if td_idx + 1 + h >= len(all_dates):
                continue
            buy_date = all_dates[td_idx + 1]
            sell_date = all_dates[td_idx + h]

            for ts_code, _ in top:
                bp = price_map.get(ts_code, {}).get(buy_date, {}).get("open")
                sp = price_map.get(ts_code, {}).get(sell_date, {}).get("close")
                if bp and sp and float(bp) > 0:
                    ret = (float(sp) - float(bp)) / float(bp)
                    rets.append(ret)

        if rets:
            wr = sum(1 for r in rets if r > 0) / len(rets)
            mr = np.mean(rets)
            med = np.median(rets)
            results[h] = {"n": len(rets), "wr": wr, "mr": mr, "med": med}
    return results


horizons = [2, 3, 5]

# 1. IC加权
print("=== IC加权基线 ===")
res = backtest_mode(lambda ic, lgb: ic, horizons)
for h, r in res.items():
    print(f"  T+{h}: 样本={r['n']} 胜率={r['wr']:.2%} 均收={r['mr']:.2%} 中位={r['med']:.2%}")

# 2. LGB不同阈值
for threshold in [0.0, 0.3, 0.4, 0.5]:
    print(f"\n=== LGB (阈值>{threshold}) ===")
    def make_fn(th):
        def fn(ic, lgb):
            return lgb if lgb > th else -999
        return fn
    res = backtest_mode(make_fn(threshold), horizons)
    for h, r in res.items():
        print(f"  T+{h}: 样本={r['n']} 胜率={r['wr']:.2%} 均收={r['mr']:.2%} 中位={r['med']:.2%}")

# 3. LGB+IC混合
for alpha in [0.5, 0.6, 0.7, 0.8]:
    print(f"\n=== LGB+IC混合 (LGB权重={alpha}) ===")
    def make_blend(a):
        def fn(ic, lgb):
            # IC归一化到0~1
            return a * lgb + (1 - a) * 0.5  # 简化：IC用0.5代替（因为IC是z-score，无法直接归一化）
        return fn
    # 更好的混合：用排名
    def make_blend_rank(a):
        def fn(ic, lgb):
            return a * lgb + (1 - a) * (1 / (1 + np.exp(-ic)))  # sigmoid归一化IC
        return fn
    res = backtest_mode(make_blend_rank(alpha), horizons)
    for h, r in res.items():
        print(f"  T+{h}: 样本={r['n']} 胜率={r['wr']:.2%} 均收={r['mr']:.2%} 中位={r['med']:.2%}")
