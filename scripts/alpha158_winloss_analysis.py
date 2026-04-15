# -*- coding: utf-8 -*-
"""Alpha158 盈亏股票特征分析"""
from __future__ import annotations
import sys, os, json
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.core.config import ConfigManager
from src.core.database import DatabaseManager
from src.modules.stock_selector import StockSelector

config = ConfigManager()
db = DatabaseManager(config)
selector = StockSelector(db=db, config=config)

# 交易日
all_dates = [r["trade_date"] for r in db.query(
    "SELECT DISTINCT trade_date FROM stock_daily ORDER BY trade_date ASC"
)]
all_dates = [d.strftime("%Y%m%d") if hasattr(d, "strftime") else str(d) for d in all_dates]

end_idx = len(all_dates) - 1
signal_dates = all_dates[end_idx - 130 : end_idx - 5]  # 更长区间
print(f"信号区间: {signal_dates[0]} ~ {signal_dates[-1]} ({len(signal_dates)}天)")

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

# 收集所有选股结果+因子+收益
all_records = []
horizon = 2  # T+2

for i, td in enumerate(signal_dates):
    if (i + 1) % 20 == 0:
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

    td_idx = all_dates.index(td)
    if td_idx + 1 + horizon >= len(all_dates):
        continue
    buy_date = all_dates[td_idx + 1]
    sell_date = all_dates[td_idx + horizon]

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
            f["name"] = row.get("name", "")
            f["industry"] = row.get("industry", "")
            all_factors.append(f)
        except Exception:
            continue

    if not all_factors:
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
    score = np.zeros(len(fdf))
    for fname, w in selector.ALPHA158_WEIGHTS.items():
        if fname in fdf.columns:
            score += fdf[fname].fillna(0).values * w
    fdf["ic_score"] = score

    # 取top5
    fdf = fdf.sort_values("ic_score", ascending=False).head(5)

    for _, row in fdf.iterrows():
        ts_code = row["ts_code"]
        bp = price_map.get(ts_code, {}).get(buy_date, {}).get("open")
        sp = price_map.get(ts_code, {}).get(sell_date, {}).get("close")
        if bp and sp and float(bp) > 0:
            ret = (float(sp) - float(bp)) / float(bp)
            rec = {
                "ts_code": ts_code,
                "name": row.get("name", ""),
                "industry": row.get("industry", ""),
                "rec_date": td,
                "ic_score": row["ic_score"],
                "ret": ret,
                "win": 1 if ret > 0 else 0,
            }
            # 保存因子值
            for c in factor_cols:
                rec[f"f_{c}"] = row[c]
            all_records.append(rec)

df = pd.DataFrame(all_records)
print(f"\n总样本: {len(df)}, 胜率: {df['win'].mean():.2%}, 均收: {df['ret'].mean():.2%}")

# ===== 分析1: 盈亏股票因子差异 =====
print("\n" + "=" * 60)
print("盈亏股票因子均值差异")
print("=" * 60)

win_df = df[df["win"] == 1]
lose_df = df[df["win"] == 0]

factor_names = [c for c in df.columns if c.startswith("f_")]
diff_data = []
for fn in factor_names:
    w_mean = win_df[fn].mean()
    l_mean = lose_df[fn].mean()
    diff = w_mean - l_mean
    # t-test
    from scipy import stats
    t_stat, p_val = stats.ttest_ind(win_df[fn].dropna(), lose_df[fn].dropna())
    diff_data.append({
        "factor": fn.replace("f_", ""),
        "win_mean": w_mean,
        "lose_mean": l_mean,
        "diff": diff,
        "t_stat": t_stat,
        "p_val": p_val,
        "sig": "***" if p_val < 0.001 else ("**" if p_val < 0.01 else ("*" if p_val < 0.05 else ""))
    })

diff_df = pd.DataFrame(diff_data).sort_values("p_val")
print(f"{'因子':<15} {'盈利均值':>8} {'亏损均值':>8} {'差异':>8} {'t值':>8} {'p值':>8} {'显著':>4}")
print("-" * 60)
for _, row in diff_df.iterrows():
    print(f"{row['factor']:<15} {row['win_mean']:>8.3f} {row['lose_mean']:>8.3f} {row['diff']:>8.3f} {row['t_stat']:>8.2f} {row['p_val']:>8.4f} {row['sig']:>4}")

# ===== 分析2: 行业盈亏分布 =====
print("\n" + "=" * 60)
print("行业盈亏分布（样本>=5）")
print("=" * 60)

ind_stats = df.groupby("industry").agg(
    count=("win", "count"),
    win_rate=("win", "mean"),
    mean_ret=("ret", "mean"),
).query("count >= 5").sort_values("win_rate", ascending=False)

print(f"{'行业':<12} {'样本':>5} {'胜率':>7} {'均收':>7}")
print("-" * 40)
for ind, row in ind_stats.iterrows():
    print(f"{ind:<12} {int(row['count']):>5} {row['win_rate']:>7.1%} {row['mean_ret']:>7.2%}")

# ===== 分析3: IC评分分位 vs 胜率 =====
print("\n" + "=" * 60)
print("IC评分分位 vs 胜率")
print("=" * 60)

df["ic_q"] = pd.qcut(df["ic_score"], 5, labels=["Q1(low)", "Q2", "Q3", "Q4", "Q5(high)"])
q_stats = df.groupby("ic_q").agg(
    count=("win", "count"),
    win_rate=("win", "mean"),
    mean_ret=("ret", "mean"),
)
print(f"{'分位':<10} {'样本':>5} {'胜率':>7} {'均收':>7}")
print("-" * 35)
for q, row in q_stats.iterrows():
    print(f"{q:<10} {int(row['count']):>5} {row['win_rate']:>7.1%} {row['mean_ret']:>7.2%}")

# ===== 分析4: 重复出现的股票 =====
print("\n" + "=" * 60)
print("高频出现股票盈亏")
print("=" * 60)

stock_stats = df.groupby("ts_code").agg(
    name=("name", "first"),
    count=("win", "count"),
    win_rate=("win", "mean"),
    mean_ret=("ret", "mean"),
).query("count >= 3").sort_values("count", ascending=False)

print(f"{'代码':<12} {'名称':<8} {'次数':>4} {'胜率':>7} {'均收':>7}")
print("-" * 45)
for code, row in stock_stats.head(20).iterrows():
    print(f"{code:<12} {row['name']:<8} {int(row['count']):>4} {row['win_rate']:>7.1%} {row['mean_ret']:>7.2%}")

# ===== 分析5: 不同top_n的胜率 =====
print("\n" + "=" * 60)
print("选股数量 vs 胜率（同日top1~5分别统计）")
print("=" * 60)

# 重新计算：每天按ic_score排序，分别取top1, top2, ...
rank_rets = {k: [] for k in range(1, 6)}
for td in signal_dates:
    td_df = df[df["rec_date"] == td].sort_values("ic_score", ascending=False)
    for k in range(1, 6):
        if len(td_df) >= k:
            rank_rets[k].append(td_df.iloc[k - 1]["ret"])

print(f"{'排名':<6} {'样本':>5} {'胜率':>7} {'均收':>7} {'中位':>7}")
print("-" * 35)
for k, rets in rank_rets.items():
    if rets:
        wr = sum(1 for r in rets if r > 0) / len(rets)
        print(f"Top{k:<4} {len(rets):>5} {wr:>7.1%} {np.mean(rets):>7.2%} {np.median(rets):>7.2%}")

# ===== 分析6: 亏损股票共性特征 =====
print("\n" + "=" * 60)
print("亏损股票共性特征（vs 盈利股票）")
print("=" * 60)

# 找出显著区分盈亏的因子
sig_factors = diff_df[diff_df["p_val"] < 0.1]["factor"].tolist()
if sig_factors:
    print(f"显著区分因子(p<0.1): {sig_factors}")
    for fn in sig_factors:
        col = f"f_{fn}"
        # 亏损股的该因子分布
        l_vals = lose_df[col].dropna()
        w_vals = win_df[col].dropna()
        # 找出亏损股的因子阈值
        l_75 = l_vals.quantile(0.75) if diff_df[diff_df["factor"]==fn]["diff"].values[0] > 0 else l_vals.quantile(0.25)
        print(f"  {fn}: 盈利均值={w_vals.mean():.3f}, 亏损均值={l_vals.mean():.3f}")

# 保存分析结果
out = {
    "total": len(df),
    "win_rate": float(df["win"].mean()),
    "mean_ret": float(df["ret"].mean()),
    "significant_factors": sig_factors,
    "factor_diffs": [{k: v for k, v in row.items()} for _, row in diff_df.iterrows()],
}
os.makedirs(ROOT / "output", exist_ok=True)
with open(ROOT / "output" / "alpha158_winloss_analysis.json", "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False, indent=2, default=str)
print(f"\n分析结果已保存到 output/alpha158_winloss_analysis.json")
