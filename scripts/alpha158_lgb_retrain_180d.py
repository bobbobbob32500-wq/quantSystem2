# -*- coding: utf-8 -*-
"""用V2最优参数在180天数据上重训，时序CV评估"""
import sys, os, json, time
import numpy as np, pandas as pd
from collections import defaultdict
import shutil

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.core.config import ConfigManager
from src.core.database import DatabaseManager
from src.modules.stock_selector import StockSelector
import lightgbm as lgb
from sklearn.metrics import roc_auc_score

config = ConfigManager()
db = DatabaseManager(config)
selector = StockSelector(db=db, config=config)

# 加载V2参数
with open("models/alpha158_lgb_config.json", "r", encoding="utf-8") as f:
    v2_cfg = json.load(f)
v2_params = v2_cfg["lgb_params"]
feature_cols = v2_cfg["feature_cols"]
print(f"V2参数: {v2_params}")

all_dates = [r["trade_date"] for r in db.query("SELECT DISTINCT trade_date FROM stock_daily ORDER BY trade_date ASC")]
all_dates = [d.strftime("%Y%m%d") if hasattr(d, "strftime") else str(d) for d in all_dates]
end_idx = len(all_dates) - 1
n_days = 180
signal_dates = all_dates[end_idx - n_days - 5 : end_idx - 5]
print(f"训练区间: {signal_dates[0]}~{signal_dates[-1]} ({len(signal_dates)}天)")

# 批量加载
print("批量加载日线...")
rows = db.query(
    "SELECT ts_code, trade_date, close, open, high, low, vol, amount "
    "FROM stock_daily WHERE trade_date >= ? AND trade_date <= ? AND close > 0",
    (signal_dates[0], all_dates[min(end_idx + 5, len(all_dates) - 1)]),
)
stock_daily = defaultdict(list)
for r in rows:
    stock_daily[r["ts_code"]].append(r)
for ts in stock_daily:
    stock_daily[ts].sort(key=lambda x: str(x["trade_date"]))
print(f"加载: {len(stock_daily)}只, {len(rows)}条")

# 价格
price_map = {}
for r in db.query(
    "SELECT ts_code, trade_date, open, close FROM stock_daily WHERE trade_date >= ? AND trade_date <= ?",
    (signal_dates[0], all_dates[min(end_idx + 5, len(all_dates) - 1)]),
):
    key = r["ts_code"]
    if key not in price_map:
        price_map[key] = {}
    ds = r["trade_date"].strftime("%Y%m%d") if hasattr(r["trade_date"], "strftime") else str(r["trade_date"])
    price_map[key][ds] = {"open": float(r["open"]), "close": float(r["close"])}

stock_list = selector.get_stock_list(end_date=signal_dates[-1], point_in_time=False)
main_board_mask = (
    stock_list["ts_code"].str.startswith("60") & stock_list["ts_code"].str.endswith(".SH")
) | (
    stock_list["ts_code"].str.startswith("00") & stock_list["ts_code"].str.endswith(".SZ")
) | (
    stock_list["ts_code"].str.startswith("001") & stock_list["ts_code"].str.endswith(".SZ")
)
stock_list = stock_list[main_board_mask]
if selector.exclude_st:
    stock_list = stock_list[~stock_list["name"].str.contains("ST|st|退", na=False)]
ts_codes = stock_list["ts_code"].tolist()

# 构建数据集
print("构建数据集...")
all_records = []
for i, td in enumerate(signal_dates):
    if (i + 1) % 30 == 0:
        print(f"  {i+1}/{len(signal_dates)}", flush=True)
    td_idx = all_dates.index(td)
    buy_date = all_dates[td_idx + 1] if td_idx + 1 < len(all_dates) else None
    sell_date = all_dates[td_idx + 2] if td_idx + 2 < len(all_dates) else None
    if not buy_date or not sell_date:
        continue
    day_factors = []
    for ts_code in ts_codes:
        recs = stock_daily.get(ts_code, [])
        result = []
        for r in reversed(recs):
            ds = r["trade_date"].strftime("%Y%m%d") if hasattr(r["trade_date"], "strftime") else str(r["trade_date"])
            if ds <= td:
                result.append(r)
            if len(result) >= 61:
                break
        if len(result) < 61:
            continue
        result = result[::-1]
        close = np.array([float(r["close"]) for r in result])
        high = np.array([float(r["high"]) for r in result])
        low = np.array([float(r["low"]) for r in result])
        vol = np.array([float(r["vol"]) for r in result])
        amount = np.array([float(r["amount"]) for r in result])
        n = len(close)
        if close[-1] <= 0:
            continue
        f = selector._compute_alpha158_factors(close, high, low, vol, amount, n)
        if len(f) < 10:
            continue
        if f.get("_amount", 0) < selector.alpha158_min_amount:
            continue
        if f.get("_vol30", 0) > selector.alpha158_vol_max:
            continue
        ma5 = f.get("_MA5", 0)
        ma20 = f.get("_MA20", 1)
        if ma20 > 0 and ma5 / ma20 > 1.03:
            continue
        roc5 = f.get("_ROC5", 0)
        if roc5 < -0.08:
            continue
        t1_open = price_map.get(ts_code, {}).get(buy_date, {}).get("open")
        t2_close = price_map.get(ts_code, {}).get(sell_date, {}).get("close")
        if not t1_open or not t2_close or float(t1_open) <= 0:
            continue
        ret = (float(t2_close) - float(t1_open)) / float(t1_open)
        f["_label"] = 1 if ret > 0 else 0
        f["_ret"] = ret
        f["_date"] = td
        day_factors.append(f)
    if not day_factors:
        continue
    day_df = pd.DataFrame(day_factors)
    factor_cols_ic = [c for c in day_df.columns if c in selector.ALPHA158_WEIGHTS]
    for col in factor_cols_ic:
        vals = day_df[col].values.astype(float)
        m = np.nanmean(vals)
        s = np.nanstd(vals)
        if s > 1e-8:
            day_df[col] = (vals - m) / s
        else:
            day_df[col] = 0.0
    score = np.zeros(len(day_df))
    for fname, w in selector.ALPHA158_WEIGHTS.items():
        if fname in day_df.columns:
            score += day_df[fname].fillna(0).values * w
    day_df["_ic_score"] = score
    day_df = day_df.sort_values("_ic_score", ascending=False)
    n_sample = min(15, len(day_df) // 4)
    if n_sample < 5:
        n_sample = 5
    top = day_df.head(n_sample)
    bottom = day_df.tail(n_sample)
    sampled = pd.concat([top, bottom])
    all_records.extend(sampled.to_dict("records"))

df = pd.DataFrame(all_records)
print(f"数据集: {len(df)}条, 正样本: {df['_label'].sum():.0f} ({df['_label'].mean():.1%}), 日期: {df['_date'].nunique()}")

# 用V2参数训练
X = df[feature_cols].fillna(0.0).astype(float)
y = df["_label"]

# 时序CV
dates_sorted = sorted(df["_date"].unique())
n_dates = len(dates_sorted)
fold_size = n_dates // 5
folds = []
for i in range(4):
    train_end = fold_size * (i + 1)
    val_start = train_end
    val_end = fold_size * (i + 2)
    train_dates = set(dates_sorted[:train_end])
    val_dates = set(dates_sorted[val_start:val_end])
    folds.append((df[df["_date"].isin(train_dates)].index, df[df["_date"].isin(val_dates)].index))

lgb_params = {"objective": "binary", "metric": "auc", "verbosity": -1, **v2_params}
models = []
fold_aucs = []
for fi, (train_idx, val_idx) in enumerate(folds):
    X_train = X.loc[train_idx]
    y_train = y.loc[train_idx]
    X_val = X.loc[val_idx]
    y_val = y.loc[val_idx]
    if len(y_train) < 100 or len(y_val) < 50:
        continue
    train_data = lgb.Dataset(X_train, label=y_train)
    val_data = lgb.Dataset(X_val, label=y_val, reference=train_data)
    model = lgb.train(
        lgb_params, train_data, num_boost_round=500,
        valid_sets=[val_data],
        callbacks=[lgb.early_stopping(stopping_rounds=30, verbose=False)],
    )
    pred = model.predict(X_val)
    auc = roc_auc_score(y_val, pred)
    models.append(model)
    fold_aucs.append(auc)
    print(f"Fold {fi+1}: AUC={auc:.4f} (train={len(y_train)}, val={len(y_val)})")

print(f"各折AUC: {[f'{a:.4f}' for a in fold_aucs]}")
print(f"平均AUC: {np.mean(fold_aucs):.4f} +/- {np.std(fold_aucs):.4f}")

# 保存最后一折模型
best_model = models[-1]
os.makedirs("models", exist_ok=True)
for fname in ["alpha158_lgb_model.txt", "alpha158_lgb_config.json"]:
    src = os.path.join("models", fname)
    if os.path.exists(src):
        dst = src + ".v2_pullback"
        if not os.path.exists(dst):
            shutil.copy2(src, dst)

best_model.save_model("models/alpha158_lgb_model.txt")
importance = best_model.feature_importance(importance_type="gain")
feat_imp = dict(zip(feature_cols, importance.tolist()))
sorted_imp = sorted(feat_imp.items(), key=lambda x: -x[1])
print("特征Top10:")
for name, imp in sorted_imp[:10]:
    print(f"  {name:<20}: {imp:.1f}")

config_data = {
    "feature_cols": feature_cols,
    "lgb_params": lgb_params,
    "feature_importance": feat_imp,
    "best_auc": float(np.mean(fold_aucs)),
    "fold_aucs": [float(a) for a in fold_aucs],
    "auc_std": float(np.std(fold_aucs)),
    "n_features": len(feature_cols),
    "n_samples": len(df),
    "n_days": n_days,
    "filter_mode": "pullback_v3_fixed",
    "note": f"V2 params on 180d data, time-series CV, AUC={np.mean(fold_aucs):.4f}+/-{np.std(fold_aucs):.4f}",
}
with open("models/alpha158_lgb_config.json", "w", encoding="utf-8") as f:
    json.dump(config_data, f, ensure_ascii=False, indent=2)
print(f"模型已保存, AUC={np.mean(fold_aucs):.4f}+/-{np.std(fold_aucs):.4f}")
