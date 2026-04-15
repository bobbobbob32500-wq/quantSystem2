# -*- coding: utf-8 -*-
"""
训练二次启动策略日线二级过滤 LightGBM，并输出优化前后对比。

思路：
1. 先用现有二次启动规则生成全历史候选信号；
2. 以信号日开盘买入、持有 hold_days 日后的净收益是否大于 0 作为监督标签；
3. 使用最近窗口滚动切分训练/验证，避免前视偏差；
4. 模型仅作为二级过滤层，训练完成后写入 models/secondary_launch_lgb_model.txt。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.core.config import ConfigManager
from src.core.database import DatabaseManager
from src.modules.mainboard_secondary_launch_backtester import CostConfig, MainboardSecondaryLaunchBacktester
from src.modules.mainboard_secondary_launch_strategy import MainboardSecondaryLaunchStrategy, StrategyParams
from src.modules.secondary_launch_lgb_scorer import SecondaryLaunchLGBScorerConfig

MODEL_PATH = ROOT / "models" / "secondary_launch_lgb_model.txt"
CONFIG_PATH = ROOT / "models" / "secondary_launch_lgb_model.json"
REPORT_PATH = ROOT / "data" / "reports" / "secondary_launch_lgb_optimization_report.md"


def _metrics(ret: pd.Series) -> dict:
    s = pd.to_numeric(ret, errors="coerce").dropna()
    if s.empty:
        return {"count": 0, "win_rate": 0.0, "avg_return": 0.0, "median_return": 0.0, "profit_factor": 0.0}
    pos = float(s[s > 0].sum())
    neg = float(-s[s < 0].sum())
    return {
        "count": int(len(s)),
        "win_rate": float((s > 0).mean()),
        "avg_return": float(s.mean()),
        "median_return": float(s.median()),
        "profit_factor": float(pos / neg) if neg > 1e-12 else 0.0,
    }


def _fmt_pct(v: float) -> str:
    return f"{v:.2%}"


def _build_base_params(config: ConfigManager) -> StrategyParams:
    return StrategyParams(
        min_list_days=int(config.get("stock_selection.secondary_launch.min_list_days", 60)),
        limit_up_threshold=float(config.get("stock_selection.secondary_launch.limit_up_threshold", 9.7)),
        limit_down_threshold=float(config.get("stock_selection.secondary_launch.limit_down_threshold", -9.7)),
        limit_up_count_10_min=int(config.get("stock_selection.secondary_launch.limit_up_count_10_min", 1)),
        limit_up_count_10_max=int(config.get("stock_selection.secondary_launch.limit_up_count_10_max", 1)),
        last_limit_up_days_min=int(config.get("stock_selection.secondary_launch.last_limit_up_days_min", 1)),
        last_limit_up_days_max=int(config.get("stock_selection.secondary_launch.last_limit_up_days_max", 6)),
        drawdown_min=float(config.get("stock_selection.secondary_launch.drawdown_min", 0.02)),
        drawdown_max=float(config.get("stock_selection.secondary_launch.drawdown_max", 0.1)),
        vol_shrink_ratio=float(config.get("stock_selection.secondary_launch.vol_shrink_ratio", 0.85)),
        close_ma5_dev_max=float(config.get("stock_selection.secondary_launch.close_ma5_dev_max", 0.04)),
        close_ma10_min_ratio=float(config.get("stock_selection.secondary_launch.close_ma10_min_ratio", 0.99)),
        min_amt_ma20=float(config.get("stock_selection.secondary_launch.min_amt_ma20", 1e5)),
        max_amt_ma20=float(config.get("stock_selection.secondary_launch.max_amt_ma20", 5e6)),
        min_price=float(config.get("stock_selection.secondary_launch.min_price", 3.0)),
        limit_up_amt_ratio_min=float(config.get("stock_selection.secondary_launch.limit_up_amt_ratio_min", 0.6)),
        limit_up_amt_ratio_max=float(config.get("stock_selection.secondary_launch.limit_up_amt_ratio_max", 3.5)),
        rs_lookback=int(config.get("stock_selection.secondary_launch.rs_lookback", 20)),
        max_candidates=int(config.get("stock_selection.secondary_launch.max_candidates", 12)),
        picks_per_day=int(config.get("stock_selection.secondary_launch.picks_per_day", 2)),
        min_score=float(config.get("stock_selection.secondary_launch.min_score", 62.0)),
        cooldown_days=int(config.get("stock_selection.secondary_launch.cooldown_days", 2)),
        weak_market_ret5_threshold=float(config.get("stock_selection.secondary_launch.weak_market_ret5_threshold", -0.02)),
        weak_market_min_score_boost=float(config.get("stock_selection.secondary_launch.weak_market_min_score_boost", 6.0)),
        weak_market_max_picks=int(config.get("stock_selection.secondary_launch.weak_market_max_picks", 1)),
        second_pick_min_score=float(config.get("stock_selection.secondary_launch.second_pick_min_score", 72.0)),
        second_pick_score_gap=float(config.get("stock_selection.secondary_launch.second_pick_score_gap", 4.0)),
        lgb_enabled=False,
    )


def _prepare_dataset() -> tuple[pd.DataFrame, pd.DataFrame, StrategyParams, CostConfig]:
    config = ConfigManager()
    db = DatabaseManager(config)
    params = _build_base_params(config)
    cost = CostConfig(
        buy_fee_rate=float(config.get("feedback.buy_fee_rate", 0.0003)),
        sell_fee_rate=float(config.get("feedback.sell_fee_rate", 0.0003)),
        stamp_tax_rate=float(config.get("feedback.stamp_tax_rate", 0.0005)),
        transfer_fee_rate=float(config.get("stock_selection.secondary_launch.transfer_fee_rate", 0.00001)),
        slippage_rate=float(config.get("feedback.buy_slippage", 0.001)),
    )
    strategy = MainboardSecondaryLaunchStrategy(params)
    backtester = MainboardSecondaryLaunchBacktester(db, strategy, cost)

    start_date = str(config.get("stock_selection.secondary_launch.backtest_in_sample_start", "20251201"))
    end_date = str(config.get("stock_selection.secondary_launch.backtest_full_history_end", "")) or db.get_latest_trade_date("stock_daily")

    data = backtester.load_data(start_date, end_date, warmup_days=120, forward_days=15)
    features = strategy.prepare_features(data["daily"], data["basic"])
    signal_frame = strategy.build_signal_frame(features)
    signals = strategy.generate_signals_from_frame(signal_frame)
    bt = backtester._build_backtest_result(features, signals, start_date, end_date, hold_days=int(config.get("stock_selection.secondary_launch.hold_days", 2)))
    trades = bt["trades"].copy()
    trades["signal_date_key"] = pd.to_datetime(trades["signal_date"]).dt.strftime("%Y%m%d")
    signals["signal_date_key"] = pd.to_datetime(signals["signal_date"]).dt.strftime("%Y%m%d")

    feature_map = signal_frame.sort_values(["signal_date", "ts_code", "trade_date"]).drop_duplicates(["signal_date", "ts_code"], keep="last")
    feature_map["signal_date_key"] = pd.to_datetime(feature_map["signal_date"]).dt.strftime("%Y%m%d")

    merged = signals.merge(feature_map, on=["signal_date_key", "ts_code"], suffixes=("", "_feat"), how="left")
    merged = merged.merge(trades[["signal_date_key", "ts_code", "net_ret"]], on=["signal_date_key", "ts_code"], how="left")
    merged["label"] = (merged["net_ret"] > 0).astype(int)
    merged = merged.dropna(subset=["net_ret"]).copy()
    return merged, trades, params, cost


def _prepare_lgb_features(df: pd.DataFrame, feature_cols: list[str]) -> pd.DataFrame:
    feat = pd.DataFrame(index=df.index)
    feat["rs20"] = pd.to_numeric(df.get("rs20"), errors="coerce")
    feat["rs20_rank"] = feat["rs20"].rank(pct=True, method="average")
    feat["drawdown_from_peak"] = pd.to_numeric(df.get("drawdown_from_peak"), errors="coerce")
    feat["days_since_last_limit_up"] = pd.to_numeric(df.get("days_since_last_limit_up"), errors="coerce")
    feat["limit_up_count_10"] = pd.to_numeric(df.get("limit_up_count_10"), errors="coerce")
    close = pd.to_numeric(df.get("close"), errors="coerce")
    ma5 = pd.to_numeric(df.get("ma5"), errors="coerce")
    ma10 = pd.to_numeric(df.get("ma10"), errors="coerce")
    vol = pd.to_numeric(df.get("vol"), errors="coerce")
    vol_ma5 = pd.to_numeric(df.get("vol_ma5"), errors="coerce")
    vol_ma20 = pd.to_numeric(df.get("vol_ma20"), errors="coerce")
    feat["close_ma5_dev"] = (close / ma5 - 1.0).abs()
    feat["close_ma10_ratio"] = (close / ma10.replace(0, np.nan)).replace([np.inf, -np.inf], np.nan)
    feat["ma5_ma10_ratio"] = (ma5 / ma10.replace(0, np.nan)).replace([np.inf, -np.inf], np.nan)
    feat["volume_ratio_5"] = (vol / vol_ma5.replace(0, np.nan)).replace([np.inf, -np.inf], np.nan)
    feat["volume_trend_ratio"] = (vol_ma5 / vol_ma20.replace(0, np.nan)).replace([np.inf, -np.inf], np.nan)
    feat["amt_ma20_log"] = np.log1p(pd.to_numeric(df.get("amt_ma20"), errors="coerce").clip(lower=0))
    feat["limit_up_amt_ratio"] = pd.to_numeric(df.get("limit_up_amt_ratio"), errors="coerce")
    feat["next_ret_after_limit_up"] = pd.to_numeric(df.get("next_ret_after_limit_up"), errors="coerce")
    feat["ret5"] = pd.to_numeric(df.get("ret5"), errors="coerce")
    feat["is_above_ma10"] = (close >= ma10).astype(float)
    feat["is_ma5_above_ma10"] = (ma5 >= ma10).astype(float)

    X = pd.DataFrame(index=df.index)
    for col in feature_cols:
        X[col] = pd.to_numeric(feat.get(col), errors="coerce").fillna(0.0)
    return X


def _search_best_threshold(prob: pd.Series, ret: pd.Series, min_kept: int = 10) -> tuple[float, dict]:
    df = pd.DataFrame({"prob": pd.to_numeric(prob, errors="coerce"), "ret": pd.to_numeric(ret, errors="coerce")}).dropna()
    if df.empty:
        return 0.5, _metrics(pd.Series(dtype=float))
    candidates = sorted({round(float(x), 4) for x in np.linspace(df["prob"].min(), df["prob"].max(), 25)})
    best_threshold = float(candidates[0]) if candidates else 0.5
    best_metrics = _metrics(df["ret"])
    best_score = -1e18
    total_n = max(len(df), 1)
    for th in candidates:
        kept = df[df["prob"] >= th]["ret"]
        if len(kept) < min_kept:
            continue
        mt = _metrics(kept)
        score = (
            mt["win_rate"] * 0.50
            + mt["avg_return"] * 4.0
            + min(mt["profit_factor"], 3.0) * 0.10
            + (len(kept) / total_n) * 0.10
        )
        if score > best_score:
            best_score = score
            best_threshold = float(th)
            best_metrics = mt
    return best_threshold, best_metrics


def main() -> None:
    merged, _, _, _ = _prepare_dataset()
    cfg_seed = json.loads(CONFIG_PATH.read_text(encoding="utf-8")) if CONFIG_PATH.exists() else {}
    feature_cols = list(cfg_seed.get("feature_cols") or [])
    X = _prepare_lgb_features(merged, feature_cols)
    y = merged["label"].astype(int)
    dates = merged["signal_date_key"].astype(str)

    unique_dates = sorted(dates.unique().tolist())
    split_idx = max(int(len(unique_dates) * 0.7), 1)
    train_dates = set(unique_dates[:split_idx])
    valid_dates = set(unique_dates[split_idx:])
    train_mask = dates.isin(train_dates)
    valid_mask = dates.isin(valid_dates)

    X_train = X.loc[train_mask]
    y_train = y.loc[train_mask]
    X_valid = X.loc[valid_mask]
    y_valid = y.loc[valid_mask]

    train_data = lgb.Dataset(X_train, label=y_train)
    valid_data = lgb.Dataset(X_valid, label=y_valid, reference=train_data)
    params_lgb = {
        "objective": "binary",
        "metric": "auc",
        "learning_rate": 0.03,
        "num_leaves": 31,
        "max_depth": 4,
        "subsample": 0.85,
        "colsample_bytree": 0.8,
        "lambda_l2": 12.0,
        "min_child_samples": 24,
        "verbosity": -1,
        "seed": 42,
    }
    model = lgb.train(
        params_lgb,
        train_data,
        num_boost_round=300,
        valid_sets=[valid_data],
        callbacks=[lgb.early_stopping(stopping_rounds=30, verbose=False)],
    )
    MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    model.save_model(str(MODEL_PATH))

    prob = model.predict(X_valid)
    valid_df = merged.loc[valid_mask].copy()
    valid_df["lgb_prob"] = prob

    baseline_metrics = _metrics(valid_df["net_ret"])
    best_threshold, filtered_metrics = _search_best_threshold(valid_df["lgb_prob"], valid_df["net_ret"], min_kept=10)
    filtered_df = valid_df[valid_df["lgb_prob"] >= best_threshold].copy()

    cfg_payload = json.loads(CONFIG_PATH.read_text(encoding="utf-8")) if CONFIG_PATH.exists() else {}
    cfg_payload.update(
        {
            "trained_at": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S"),
            "train_rows": int(len(X_train)),
            "valid_rows": int(len(X_valid)),
            "best_iteration": int(model.best_iteration or 0),
            "best_auc": float(model.best_score.get("valid_0", {}).get("auc", 0.0)),
            "recommended_threshold": float(best_threshold),
            "lgb_params": params_lgb,
            "feature_importance": {
                col: float(val)
                for col, val in zip(X.columns.tolist(), model.feature_importance(importance_type="gain"))
            },
            "baseline_valid_metrics": baseline_metrics,
            "filtered_valid_metrics": filtered_metrics,
        }
    )
    CONFIG_PATH.write_text(json.dumps(cfg_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# 二次启动策略 LightGBM 二级过滤优化报告",
        "",
        f"- 训练时间：{cfg_payload['trained_at']}",
        f"- 训练样本：{cfg_payload['train_rows']}，验证样本：{cfg_payload['valid_rows']}",
        f"- 验证集 AUC：{cfg_payload['best_auc']:.4f}",
        f"- 推荐过滤阈值：{cfg_payload['recommended_threshold']:.4f}",
        "",
        "## 验证集前后对比",
        "",
        "| 方案 | 样本数 | 胜率 | 平均收益 | 中位收益 | 盈亏比 |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
        f"| 原始二次启动 | {baseline_metrics['count']} | {_fmt_pct(baseline_metrics['win_rate'])} | {_fmt_pct(baseline_metrics['avg_return'])} | {_fmt_pct(baseline_metrics['median_return'])} | {baseline_metrics['profit_factor']:.2f} |",
        f"| LGB过滤后二次启动 | {filtered_metrics['count']} | {_fmt_pct(filtered_metrics['win_rate'])} | {_fmt_pct(filtered_metrics['avg_return'])} | {_fmt_pct(filtered_metrics['median_return'])} | {filtered_metrics['profit_factor']:.2f} |",
        "",
        "## 结论",
        "",
        "- LGB 只做二级过滤，不替代原有日线规则；",
        "- 若过滤后胜率、均收益、盈亏比同步改善，则说明原策略主要问题是边缘信号过多；",
        "- 若样本收缩过度，应调低 `lgb_min_score` 或降低融合权重。",
        "",
    ]
    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
