# -*- coding: utf-8 -*-
"""
Alpha158 LightGBM V3 训练脚本
- 扩展训练数据到180天
- 时序交叉验证（避免未来信息泄露）
- Optuna超参优化
- 批量预加载日线数据，加速因子计算
"""
import sys, os, json, time
import numpy as np, pandas as pd
from datetime import datetime
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.core.config import ConfigManager
from src.core.database import DatabaseManager
from src.modules.stock_selector import StockSelector
from src.modules.alpha158_regime_router import Alpha158RegimeRouter

import lightgbm as lgb
from sklearn.metrics import roc_auc_score
import optuna

optuna.logging.set_verbosity(optuna.logging.WARNING)


def batch_load_daily(db, date_min, date_max):
    """批量加载日线数据到内存"""
    print("批量加载日线数据...")
    rows = db.query(
        "SELECT ts_code, trade_date, close, open, high, low, vol, amount "
        "FROM stock_daily WHERE trade_date >= ? AND trade_date <= ? AND close > 0",
        (date_min, date_max),
    )
    # 按ts_code分组
    stock_daily = defaultdict(list)
    for r in rows:
        stock_daily[r["ts_code"]].append(r)
    # 排序
    for ts in stock_daily:
        stock_daily[ts].sort(key=lambda x: str(x["trade_date"]))
    print(f"  加载完成: {len(stock_daily)}只股票, {len(rows)}条记录")
    return stock_daily


def compute_factors_from_cache(selector, ts_code, end_date_str, stock_daily_cache):
    """从缓存数据计算因子"""
    records = stock_daily_cache.get(ts_code, [])
    if not records:
        return None
    # 找到end_date及之前的61条
    result = []
    for r in reversed(records):
        ds = r["trade_date"].strftime("%Y%m%d") if hasattr(r["trade_date"], "strftime") else str(r["trade_date"])
        if ds <= end_date_str:
            result.append(r)
        if len(result) >= 61:
            break
    if len(result) < 61:
        return None
    result = result[::-1]  # 按时间正序

    close = np.array([float(r["close"]) for r in result])
    high = np.array([float(r["high"]) for r in result])
    low = np.array([float(r["low"]) for r in result])
    vol = np.array([float(r["vol"]) for r in result])
    amount = np.array([float(r["amount"]) for r in result])
    n = len(close)
    if close[-1] <= 0:
        return None

    f = selector._compute_alpha158_factors(close, high, low, vol, amount, n)
    if len(f) < 10:
        return None
    return f


def build_dataset(selector, db, all_dates, signal_dates, stock_daily_cache, regime_router, top_n=5):
    """构建训练数据集"""
    print(f"构建数据集: {len(signal_dates)}天, top{top_n}")

    # 获取股票列表
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
    print(f"候选股票: {len(ts_codes)}只")

    # 预加载价格（用于标注）
    price_map = {}
    date_min = signal_dates[0]
    date_max_idx = min(all_dates.index(signal_dates[-1]) + 5, len(all_dates) - 1)
    date_max = all_dates[date_max_idx]
    for r in db.query(
        "SELECT ts_code, trade_date, open, close FROM stock_daily "
        "WHERE trade_date >= ? AND trade_date <= ?",
        (date_min, date_max),
    ):
        key = r["ts_code"]
        if key not in price_map:
            price_map[key] = {}
        ds = r["trade_date"].strftime("%Y%m%d") if hasattr(r["trade_date"], "strftime") else str(r["trade_date"])
        price_map[key][ds] = {"open": float(r["open"]), "close": float(r["close"])}

    # 逐日选股+标注
    all_records = []
    for i, td in enumerate(signal_dates):
        if (i + 1) % 20 == 0:
            print(f"  处理 {i+1}/{len(signal_dates)} ({td})", flush=True)

        td_idx = all_dates.index(td)
        buy_date = all_dates[td_idx + 1] if td_idx + 1 < len(all_dates) else None
        sell_date = all_dates[td_idx + 2] if td_idx + 2 < len(all_dates) else None
        if not buy_date or not sell_date:
            continue
        regime_decision = regime_router.decide(end_date=td)
        regime = regime_decision.regime

        day_factors = []
        for ts_code in ts_codes:
            f = compute_factors_from_cache(selector, ts_code, td, stock_daily_cache)
            if f is None:
                continue
            # 回调过滤
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

            # 标注
            t1_open = price_map.get(ts_code, {}).get(buy_date, {}).get("open")
            t2_close = price_map.get(ts_code, {}).get(sell_date, {}).get("close")
            if not t1_open or not t2_close or float(t1_open) <= 0:
                continue
            ret = (float(t2_close) - float(t1_open)) / float(t1_open)
            f["_label"] = 1 if ret > 0 else 0
            f["_ret"] = ret
            f["_date"] = td
            f["_ts_code"] = ts_code
            f["_regime"] = regime
            f["REGIME_TREND"] = 1.0 if regime == "trend" else 0.0
            f["REGIME_SIDEWAYS"] = 1.0 if regime == "sideways" else 0.0
            f["REGIME_WEAK"] = 1.0 if regime == "weak" else 0.0
            day_factors.append(f)

        if not day_factors:
            continue

        # IC排序采样
        day_df = pd.DataFrame(day_factors)
        factor_cols = [c for c in day_df.columns if c in selector.ALPHA158_WEIGHTS]
        for col in factor_cols:
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

        # 采样策略：只取IC评分极端的股票，增强信号
        # top10（IC最强正信号）+ bottom10（IC最强负信号）
        n_sample = min(10, len(day_df) // 4)
        if n_sample < 3:
            n_sample = 3
        top = day_df.head(n_sample)
        bottom = day_df.tail(n_sample)
        sampled = pd.concat([top, bottom])
        all_records.extend(sampled.to_dict("records"))

    print(f"数据集构建完成: {len(all_records)}条")
    return pd.DataFrame(all_records)


def time_series_cv(df, n_splits=4):
    """时序交叉验证分割"""
    dates = sorted(df["_date"].unique())
    n = len(dates)
    fold_size = n // (n_splits + 1)
    folds = []
    for i in range(n_splits):
        train_end = fold_size * (i + 1)
        val_start = train_end
        val_end = fold_size * (i + 2)
        train_dates = set(dates[:train_end])
        val_dates = set(dates[val_start:val_end])
        train_idx = df[df["_date"].isin(train_dates)].index
        val_idx = df[df["_date"].isin(val_dates)].index
        folds.append((train_idx, val_idx))
    return folds


def objective(trial, X, y, df, feature_cols):
    """Optuna目标函数"""
    params = {
        "objective": "binary",
        "metric": "auc",
        "verbosity": -1,
        "learning_rate": trial.suggest_float("learning_rate", 0.01, 0.15),
        "num_leaves": trial.suggest_int("num_leaves", 20, 80),
        "max_depth": trial.suggest_int("max_depth", 4, 10),
        "subsample": trial.suggest_float("subsample", 0.6, 1.0),
        "colsample_bytree": trial.suggest_float("colsample_bytree", 0.5, 1.0),
        "lambda_l2": trial.suggest_float("lambda_l2", 1, 50),
        "min_child_samples": trial.suggest_int("min_child_samples", 20, 80),
    }

    folds = time_series_cv(df, n_splits=4)
    aucs = []
    for train_idx, val_idx in folds:
        X_train = X.loc[train_idx, feature_cols]
        y_train = y.loc[train_idx]
        X_val = X.loc[val_idx, feature_cols]
        y_val = y.loc[val_idx]
        if len(y_train) < 100 or len(y_val) < 50:
            continue
        train_data = lgb.Dataset(X_train, label=y_train)
        val_data = lgb.Dataset(X_val, label=y_val, reference=train_data)
        model = lgb.train(
            params, train_data, num_boost_round=300,
            valid_sets=[val_data], callbacks=[
                lgb.early_stopping(stopping_rounds=30, verbose=False),
            ],
        )
        pred = model.predict(X_val)
        auc = roc_auc_score(y_val, pred)
        aucs.append(auc)

    return np.mean(aucs) if aucs else 0.5


def main():
    config = ConfigManager()
    db = DatabaseManager(config)
    selector = StockSelector(db=db, config=config)
    regime_router = Alpha158RegimeRouter(
        db=db,
        lookback=int(config.get("stock_selection.alpha158_regime_lookback", 30)),
        trend_ret5_threshold=float(
            config.get("stock_selection.alpha158_regime_trend_ret5_threshold", 0.015)
        ),
        weak_ret5_threshold=float(
            config.get("stock_selection.alpha158_regime_weak_ret5_threshold", -0.02)
        ),
        ma_deviation_threshold=float(
            config.get("stock_selection.alpha158_regime_ma_deviation_threshold", 0.01)
        ),
        enable=bool(config.get("stock_selection.alpha158_regime_router_enabled", True)),
    )

    all_dates = [r["trade_date"] for r in db.query("SELECT DISTINCT trade_date FROM stock_daily ORDER BY trade_date ASC")]
    all_dates = [d.strftime("%Y%m%d") if hasattr(d, "strftime") else str(d) for d in all_dates]
    end_idx = len(all_dates) - 1

    # 扩展到180天（需要额外61天回看）
    n_days = 180
    lookback = 61
    signal_start_idx = end_idx - n_days - 5 - lookback
    signal_end_idx = end_idx - 5
    date_min = all_dates[signal_start_idx]
    date_max = all_dates[min(signal_end_idx + 5, end_idx)]
    signal_dates = all_dates[end_idx - n_days - 5 : end_idx - 5]
    print(f"训练区间: {signal_dates[0]} ~ {signal_dates[-1]} ({len(signal_dates)}天)")

    # 批量加载日线
    stock_daily_cache = batch_load_daily(db, date_min, date_max)

    # 构建数据集
    df = build_dataset(
        selector, db, all_dates, signal_dates, stock_daily_cache, regime_router, top_n=5
    )

    # 特征列
    feature_cols = [
        "MA30", "MA60", "MA5", "MA10", "ROC30", "ROC60", "ROC5", "ROC10",
        "QTLU60", "QTLD60", "QTLU20", "SUMN30", "CNTN30", "SUMN60", "VSTD30",
        "RSV60", "RANK60", "VOL_RATIO5", "VOL_RATIO20", "VWAP_DEV",
        "AMP20", "AMP5", "TURN20", "BOLL_POS", "MACD_NORM", "RSI14",
        "KDJ_K", "OBV_NORM", "HIGH_LOW_RATIO", "MA_CROSS", "VOL_PRICE_CORR",
        "REGIME_TREND", "REGIME_SIDEWAYS", "REGIME_WEAK",
    ]
    feature_cols = [c for c in feature_cols if c in df.columns]
    print(f"特征数: {len(feature_cols)}")

    # 准备X, y
    X = df.copy()
    for c in feature_cols:
        X[c] = X[c].fillna(0.0).astype(float)
    y = df["_label"]

    print(f"\n数据集统计:")
    print(f"  总样本: {len(df)}")
    print(f"  正样本: {int(y.sum())} ({y.mean():.1%})")
    print(f"  负样本: {int((1-y).sum())} ({(1-y).mean():.1%})")
    print(f"  日期数: {df['_date'].nunique()}")
    if "_regime" in df.columns:
        print("  状态分布:")
        for regime_name, cnt in df["_regime"].value_counts().items():
            sub = df[df["_regime"] == regime_name]
            win_rate = float(sub["_label"].mean()) if not sub.empty else 0.0
            mean_ret = float(sub["_ret"].mean()) if not sub.empty else 0.0
            print(
                f"    {regime_name:<9} 样本={len(sub):>5} 胜率={win_rate:>6.1%} 均收={mean_ret:>7.2%}"
            )

    # Optuna优化
    print("\n开始Optuna超参优化 (40 trials)...")
    t0 = time.time()
    study = optuna.create_study(direction="maximize")
    study.optimize(lambda trial: objective(trial, X, y, df, feature_cols), n_trials=40, show_progress_bar=True)
    print(f"优化耗时: {time.time()-t0:.0f}s")

    best_params = study.best_params
    best_auc = study.best_value
    print(f"\n最优AUC: {best_auc:.4f}")
    print(f"最优参数: {best_params}")

    # 用最优参数训练最终模型
    lgb_params = {
        "objective": "binary",
        "metric": "auc",
        "verbosity": -1,
        **best_params,
    }

    folds = time_series_cv(df, n_splits=4)
    models = []
    fold_aucs = []
    for fold_i, (train_idx, val_idx) in enumerate(folds):
        X_train = X.loc[train_idx, feature_cols]
        y_train = y.loc[train_idx]
        X_val = X.loc[val_idx, feature_cols]
        y_val = y.loc[val_idx]
        if len(y_train) < 100 or len(y_val) < 50:
            continue
        train_data = lgb.Dataset(X_train, label=y_train)
        val_data = lgb.Dataset(X_val, label=y_val, reference=train_data)
        model = lgb.train(
            lgb_params, train_data, num_boost_round=500,
            valid_sets=[val_data], callbacks=[
                lgb.early_stopping(stopping_rounds=30, verbose=False),
            ],
        )
        pred = model.predict(X_val)
        auc = roc_auc_score(y_val, pred)
        models.append(model)
        fold_aucs.append(auc)
        print(f"  Fold {fold_i+1}: AUC={auc:.4f} (train={len(y_train)}, val={len(y_val)})")

    print(f"\n各折AUC: {[f'{a:.4f}' for a in fold_aucs]}")
    print(f"平均AUC: {np.mean(fold_aucs):.4f} +/- {np.std(fold_aucs):.4f}")

    # 保存最后一折模型
    best_model = models[-1]
    os.makedirs("models", exist_ok=True)

    # 备份旧模型
    for fname in ["alpha158_lgb_model.txt", "alpha158_lgb_config.json"]:
        src = os.path.join("models", fname)
        if os.path.exists(src):
            dst = src + ".v2_pullback"
            if not os.path.exists(dst):
                os.rename(src, dst)
                print(f"备份: {fname} -> {fname}.v2_pullback")

    model_path = os.path.join("models", "alpha158_lgb_model.txt")
    best_model.save_model(model_path)

    importance = best_model.feature_importance(importance_type="gain")
    feat_imp = dict(zip(feature_cols, importance.tolist()))
    sorted_imp = sorted(feat_imp.items(), key=lambda x: -x[1])
    print("\n特征重要性 Top10:")
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
        "regime_distribution": (
            df["_regime"].value_counts().to_dict() if "_regime" in df.columns else {}
        ),
        "filter_mode": "pullback_v3",
        "note": f"trained with 180d data, time-series CV, AUC={np.mean(fold_aucs):.4f}+/-{np.std(fold_aucs):.4f}",
    }
    config_path = os.path.join("models", "alpha158_lgb_config.json")
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(config_data, f, ensure_ascii=False, indent=2)

    print(f"\n模型已保存: {model_path}")
    print(f"配置已保存: {config_path}")
    print(f"最终AUC: {np.mean(fold_aucs):.4f} +/- {np.std(fold_aucs):.4f}")


if __name__ == "__main__":
    main()
