# -*- coding: utf-8 -*-
"""诊断过滤漏斗：查看每一层有多少股票通过"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd
from src.core.config import ConfigManager
from src.core.database import DatabaseManager
from src.modules.breakout_strategy import BreakoutStrategy, BreakoutParams

config = ConfigManager()
db = DatabaseManager(config)
params = BreakoutParams()
strategy = BreakoutStrategy(db=db, params=params)

# 用最新交易日的前一天做测试
test_date = "20260401"
print(f"诊断日期: {test_date}")

# 拉数据+因子
raw_daily, raw_basic = strategy._load_data("20260402")
features = strategy._compute_features(raw_daily, raw_basic, "20260402")
print(f"总因子行数: {len(features)}")

# 截面快照
snapshot = strategy._build_snapshot(features, test_date)
print(f"\n截面快照: {len(snapshot)} 只股票")

# 检查关键列的NaN占比
for col in ["ma20", "ma60", "ma120", "ma20_slope", "rs20", "rs20_xsec_q",
            "atr_ratio_q60", "box_range", "pivot", "amt_ma20", "list_days"]:
    if col in snapshot.columns:
        notna_pct = snapshot[col].notna().mean() * 100
        print(f"  {col:>18}: 非NaN {notna_pct:.1f}%  (非NaN数={snapshot[col].notna().sum()})")

# Layer 1
l1 = strategy._layer_base_filter(snapshot)
print(f"\nLayer1 基础过滤: {len(snapshot)} -> {len(l1)}")
if l1.empty:
    # 拆开看哪个条件过滤最多
    p = params
    checks = {
        "close区间": snapshot["close"].between(p.min_price, p.max_price).sum(),
        "amt_ma20": (snapshot["amt_ma20"].fillna(0) >= p.min_amt_ma20).sum(),
        "list_days": (snapshot["list_days"].fillna(0) >= p.min_list_days).sum(),
        "非涨停": (~snapshot["is_limit_up"].fillna(False)).sum(),
        "非跌停": (~snapshot["is_limit_down"].fillna(False)).sum(),
        "涨停次数<=3": (snapshot["limit_up_count_20"].fillna(0) <= p.max_limit_up_count_20d).sum(),
        "跌停次数<=1": (snapshot["limit_down_count_20"].fillna(0) <= p.max_limit_down_count_20d).sum(),
        "vol>0": (snapshot["vol"].fillna(0) > 0).sum(),
        "pivot非NaN": snapshot["pivot"].notna().sum(),
        "非ST": (~snapshot["name"].fillna("").str.upper().str.contains("ST|退")).sum() if "name" in snapshot.columns else "N/A",
    }
    for k, v in checks.items():
        print(f"  {k:>16}: {v} / {len(snapshot)}")

# Layer 2 趋势
if not l1.empty:
    # 降级趋势
    cond = (
        l1["ma20"].notna() & l1["ma60"].notna()
        & (l1["ma20"] > l1["ma60"])
        & (l1["ma20_slope"].fillna(-1) > 0)
    )
    l2 = l1.loc[cond].copy()
    print(f"Layer2 趋势过滤: {len(l1)} -> {len(l2)}")

    # 细看
    if len(l2) == 0:
        print(f"  ma20>ma60: {(l1['ma20'] > l1['ma60']).sum()}")
        print(f"  ma20_slope>0: {(l1['ma20_slope'].fillna(-1) > 0).sum()}")
        both = ((l1['ma20'] > l1['ma60']) & (l1['ma20_slope'].fillna(-1) > 0)).sum()
        print(f"  两者都满足: {both}")

    # Layer 3 强度
    if not l2.empty:
        l3 = strategy._layer_strength_filter(l2)
        print(f"Layer3 强度过滤: {len(l2)} -> {len(l3)}")
        if l3.empty:
            print(f"  rs20_xsec_q分布: {l2['rs20_xsec_q'].describe()}")

        # Layer 4 走稳
        if not l3.empty:
            p = params
            cond4 = (
                l3["box_range"].notna()
                & (l3["box_range"] <= p.box_max_range)
            )
            if l3["atr_ratio_q60"].notna().mean() > 0.3:
                cond4 = cond4 & (l3["atr_ratio_q60"].fillna(0.5) <= p.atr_quantile_max)
            l4 = l3.loc[cond4].copy()
            print(f"Layer4 走稳过滤: {len(l3)} -> {len(l4)}")
            if l4.empty:
                print(f"  box_range分布: {l3['box_range'].describe()}")
                print(f"  atr_ratio_q60分布: {l3['atr_ratio_q60'].describe()}")
