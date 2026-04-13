# -*- coding: utf-8 -*-
"""
Qlib 优化全流程：基线回测 -> Qlib优化 -> 优化后回测 -> 对比

使用方式：
  conda activate qlib_env
  python scripts/qlib_full_optimize_pipeline.py
"""

import sys
import os
import json
import time
import sqlite3
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, asdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.core.logger import get_logger
from src.core.database import DatabaseManager
from src.core.config import ConfigManager
from src.modules.stock_selector import StockSelector

logger = get_logger("qlib_pipeline")

# ============================================================
# 回测参数
# ============================================================
BACKTEST_START = "20251001"   # 3个月回测起点
BACKTEST_END   = "20251231"   # 3个月回测终点
TOP_N = 5                     # 每日推荐股票数
HORIZONS = [2, 3, 5]         # 持有期 T+2, T+3, T+5
MAIN_HORIZON = 5              # 主持有期


@dataclass
class BacktestResult:
    """回测结果"""
    label: str
    sample_count: int = 0
    trade_days: int = 0
    mean_return: float = 0.0
    median_return: float = 0.0
    win_rate: float = 0.0
    sharpe_ratio: float = 0.0
    max_drawdown: float = 0.0
    total_return: float = 0.0
    day_mean_return: float = 0.0
    day_win_rate: float = 0.0
    avg_mfe: float = 0.0
    avg_mae: float = 0.0


def load_trade_dates(db: DatabaseManager) -> List[str]:
    """加载交易日列表"""
    conn = db._get_connection()
    sql = "SELECT DISTINCT trade_date FROM stock_daily ORDER BY trade_date"
    dates = [str(row[0]) for row in conn.execute(sql).fetchall()]
    conn.close()
    return dates


def get_signal_dates(trade_dates: List[str], start: str, end: str, horizon_max: int) -> List[str]:
    """获取信号日期列表"""
    selected = [d for d in trade_dates if start <= d <= end]
    # 预留 horizon_max 天用于计算卖出收益
    if len(selected) > horizon_max:
        selected = selected[:len(selected) - horizon_max]
    return selected


def run_selection_for_dates(
    signal_dates: List[str],
    db: DatabaseManager,
    config_overrides: Dict = None,
    top_n: int = TOP_N,
) -> pd.DataFrame:
    """在指定日期范围内运行选股"""
    config = ConfigManager()
    config.set("stock_selection.save_factor_values", False, save=False)
    config.set("stock_selection.min_score", 0.0, save=False)
    
    if config_overrides:
        for key, value in config_overrides.items():
            config.set(key, value, save=False)
    
    selector = StockSelector(config=config, db=db)
    
    records = []
    for idx, trade_date in enumerate(signal_dates, start=1):
        try:
            results = selector.run_selection(end_date=trade_date)
            if top_n > 0:
                results = results[:top_n]
            for rank, item in enumerate(results, start=1):
                records.append({
                    "rec_date": trade_date,
                    "ts_code": str(item.get("ts_code", "")),
                    "name": str(item.get("name", "")),
                    "rank": rank,
                    "score": float(item.get("total_score", 0.0) or 0.0),
                })
        except Exception as e:
            logger.debug(f"Selection failed on {trade_date}: {e}")
        
        if idx % 10 == 0 or idx == len(signal_dates):
            print(f"  Progress: {idx}/{len(signal_dates)} days, {len(records)} recommendations")
    
    return pd.DataFrame(records)


def evaluate_recommendations(
    rec_df: pd.DataFrame,
    db: DatabaseManager,
    trade_dates: List[str],
    horizon: int,
) -> BacktestResult:
    """评估推荐结果"""
    if rec_df.empty:
        return BacktestResult(label="empty")
    
    date_to_idx = {d: i for i, d in enumerate(trade_dates)}
    
    rec = rec_df.copy()
    rec["rec_idx"] = rec["rec_date"].map(date_to_idx)
    rec = rec.dropna(subset=["rec_idx"])
    rec["rec_idx"] = rec["rec_idx"].astype(int)
    rec = rec[rec["rec_idx"] + horizon < len(trade_dates)].copy()
    
    if rec.empty:
        return BacktestResult(label="no_valid_trades")
    
    # Load price data
    symbols = sorted(rec["ts_code"].unique().tolist())
    min_idx = int(rec["rec_idx"].min() + 1)
    max_idx = int(rec["rec_idx"].max() + horizon)
    date_min = trade_dates[min_idx]
    date_max = trade_dates[max_idx]
    
    conn = db._get_connection()
    placeholders = ",".join(["?"] * len(symbols))
    sql = f"""
        SELECT ts_code, trade_date, open, close, high, low
        FROM stock_daily
        WHERE ts_code IN ({placeholders})
          AND trade_date >= ? AND trade_date <= ?
    """
    price_df = pd.read_sql(sql, conn, params=symbols + [date_min, date_max])
    conn.close()
    
    if price_df.empty:
        return BacktestResult(label="no_price_data")
    
    for col in ("open", "close", "high", "low"):
        price_df[col] = pd.to_numeric(price_df[col], errors="coerce")
    
    # Build price map
    price_map = {}
    for _, row in price_df.iterrows():
        price_map[(str(row["ts_code"]), str(row["trade_date"]))] = {
            "open": row["open"], "close": row["close"],
            "high": row["high"], "low": row["low"],
        }
    
    # Calculate returns
    returns = []
    mfe_list = []
    mae_list = []
    daily_returns = {}
    
    for _, row in rec.iterrows():
        symbol = row["ts_code"]
        rec_idx = int(row["rec_idx"])
        
        buy_date = trade_dates[rec_idx + 1]   # T+1 open
        sell_date = trade_dates[rec_idx + horizon]  # T+horizon close
        
        buy_price = price_map.get((symbol, buy_date), {}).get("open")
        sell_price = price_map.get((symbol, sell_date), {}).get("close")
        
        if buy_price and sell_price and buy_price > 0:
            ret = (sell_price - buy_price) / buy_price
            returns.append(ret)
            
            # MFE/MAE
            max_favorable = 0.0
            max_adverse = 0.0
            for h in range(1, horizon + 1):
                check_date = trade_dates[rec_idx + h]
                prices = price_map.get((symbol, check_date), {})
                if prices:
                    high_ret = (prices.get("high", buy_price) - buy_price) / buy_price
                    low_ret = (prices.get("low", buy_price) - buy_price) / buy_price
                    max_favorable = max(max_favorable, high_ret)
                    max_adverse = min(max_adverse, low_ret)
            
            mfe_list.append(max_favorable)
            mae_list.append(max_adverse)
            
            # Daily returns
            rec_date = row["rec_date"]
            if rec_date not in daily_returns:
                daily_returns[rec_date] = []
            daily_returns[rec_date].append(ret)
    
    if not returns:
        return BacktestResult(label="no_valid_returns")
    
    returns_arr = np.array(returns)
    
    # Daily stats
    day_mean_rets = []
    day_win_rates = []
    for date, rets in daily_returns.items():
        day_mean_rets.append(np.mean(rets))
        day_win_rates.append(np.mean([1 if r > 0 else 0 for r in rets]))
    
    # Sharpe ratio (annualized)
    if len(day_mean_rets) > 1:
        mean_daily = np.mean(day_mean_rets)
        std_daily = np.std(day_mean_rets)
        sharpe = (mean_daily / std_daily) * np.sqrt(252) if std_daily > 0 else 0.0
    else:
        sharpe = 0.0
    
    # Max drawdown
    cumulative = np.cumprod(1 + returns_arr)
    running_max = np.maximum.accumulate(cumulative)
    drawdowns = (cumulative - running_max) / running_max
    max_dd = float(np.min(drawdowns)) if len(drawdowns) > 0 else 0.0
    
    return BacktestResult(
        label="",
        sample_count=len(returns),
        trade_days=len(daily_returns),
        mean_return=float(np.mean(returns_arr)),
        median_return=float(np.median(returns_arr)),
        win_rate=float(np.mean(returns_arr > 0)),
        sharpe_ratio=float(sharpe),
        max_drawdown=float(max_dd),
        total_return=float(np.prod(1 + returns_arr) - 1),
        day_mean_return=float(np.mean(day_mean_rets)) if day_mean_rets else 0.0,
        day_win_rate=float(np.mean(day_win_rates)) if day_win_rates else 0.0,
        avg_mfe=float(np.mean(mfe_list)) if mfe_list else 0.0,
        avg_mae=float(np.mean(mae_list)) if mae_list else 0.0,
    )


def print_backtest_result(label: str, result: BacktestResult, horizon: int):
    """打印回测结果"""
    print(f"\n  [{label}] T+{horizon} Backtest Result:")
    print(f"    Trades:        {result.sample_count}")
    print(f"    Trade days:    {result.trade_days}")
    print(f"    Mean return:   {result.mean_return:.4f} ({result.mean_return*100:.2f}%)")
    print(f"    Median return: {result.median_return:.4f} ({result.median_return*100:.2f}%)")
    print(f"    Win rate:      {result.win_rate:.2%}")
    print(f"    Sharpe ratio:  {result.sharpe_ratio:.4f}")
    print(f"    Max drawdown:  {result.max_drawdown:.4f} ({result.max_drawdown*100:.2f}%)")
    print(f"    Total return:  {result.total_return:.4f} ({result.total_return*100:.2f}%)")
    print(f"    Day mean ret:  {result.day_mean_return:.4f} ({result.day_mean_return*100:.2f}%)")
    print(f"    Day win rate:  {result.day_win_rate:.2%}")
    print(f"    Avg MFE:       {result.avg_mfe:.4f} ({result.avg_mfe*100:.2f}%)")
    print(f"    Avg MAE:       {result.avg_mae:.4f} ({result.avg_mae*100:.2f}%)")


def run_qlib_optimization() -> Dict:
    """运行 Qlib 优化，返回优化后的因子权重"""
    print("\n" + "=" * 60)
    print("Phase 2: Qlib Optimization")
    print("=" * 60)
    
    import qlib
    from qlib.data.dataset import DatasetH
    from qlib.contrib.model.gbdt import LGBModel
    from qlib.data import D
    from scipy.stats import spearmanr
    
    qlib.init(provider_uri='C:/Users/32519/.qlib/qlib_data/cn_data')
    
    # Step 2a: Compute Alpha158 factors and IC
    print("\n  Computing Alpha158 factor IC...")
    
    dataset = DatasetH(
        handler={
            'class': 'Alpha158',
            'module_path': 'qlib.contrib.data.handler',
            'kwargs': {
                'start_time': '2015-01-01',
                'end_time': '2020-09-25',
                'fit_start_time': '2015-01-01',
                'fit_end_time': '2018-12-31',
                'instruments': 'csi300',
            },
        },
        segments={
            'train': ('2015-01-01', '2018-12-31'),
            'valid': ('2019-01-01', '2019-12-31'),
            'test':  ('2020-01-01', '2020-09-25'),
        },
    )
    
    train_features = dataset.prepare('train', col_set='feature')
    train_labels = dataset.prepare('train', col_set='label')
    valid_features = dataset.prepare('valid', col_set='feature')
    valid_labels = dataset.prepare('valid', col_set='label')
    
    print(f"  Train: {train_features.shape}, Valid: {valid_features.shape}")
    
    # Calculate IC for each factor
    all_features = pd.concat([train_features, valid_features])
    all_labels = pd.concat([train_labels, valid_labels])
    
    factor_ics = {}
    for i, factor_name in enumerate(all_features.columns):
        if (i + 1) % 30 == 0:
            print(f"    IC progress: {i+1}/{len(all_features.columns)}")
        
        try:
            fv = all_features[factor_name].dropna()
            lv = all_labels.iloc[:, 0] if len(all_labels.columns) > 0 else all_labels
            lv = lv.dropna()
            
            common_idx = fv.index.intersection(lv.index)
            if len(common_idx) < 100:
                continue
            
            ic_values = []
            for date in fv.loc[common_idx].index.get_level_values('datetime').unique():
                f_group = fv.xs(date, level='datetime')
                l_group = lv.xs(date, level='datetime') if date in lv.index.get_level_values('datetime') else None
                if l_group is not None and len(f_group) > 20:
                    try:
                        ic, _ = spearmanr(f_group, l_group)
                        if not np.isnan(ic):
                            ic_values.append(ic)
                    except:
                        pass
            
            if ic_values:
                factor_ics[factor_name] = {
                    'ic_mean': np.mean(ic_values),
                    'ic_ir': np.mean(ic_values) / np.std(ic_values) if np.std(ic_values) > 0 else 0,
                }
        except:
            pass
    
    # Select effective factors
    effective = {k: v for k, v in factor_ics.items() 
                 if abs(v['ic_mean']) > 0.02 and abs(v['ic_ir']) > 0.3}
    
    print(f"\n  Total factors analyzed: {len(factor_ics)}")
    print(f"  Effective factors (|IC|>0.02, |ICIR|>0.3): {len(effective)}")
    
    # Step 2b: Train LightGBM model
    print("\n  Training LightGBM model...")
    
    model = LGBModel(
        loss='mse',
        colsample_bytree=0.8879,
        learning_rate=0.0421,
        subsample=0.8789,
        lambda_l1=205.6999,
        lambda_l2=580.5258,
        max_depth=8,
        num_leaves=210,
        num_threads=4,
    )
    
    model.fit(dataset)
    print("  Model training complete!")
    
    # Step 2c: Calculate model IC on test set
    pred = model.predict(dataset)
    test_label = dataset.prepare('test', col_set='label')
    
    pred_valid = pred.dropna()
    model_ic_values = []
    
    if not test_label.empty and not pred_valid.empty:
        common_idx = pred_valid.index.intersection(test_label.index)
        if len(common_idx) > 0:
            for date in pred_valid.loc[common_idx].index.get_level_values('datetime').unique():
                p_date = pred_valid.loc[common_idx].xs(date, level='datetime')
                l_date = test_label.loc[common_idx].xs(date, level='datetime')
                if len(p_date) > 10:
                    try:
                        ic, _ = spearmanr(p_date, l_date)
                        if not np.isnan(ic):
                            model_ic_values.append(ic)
                    except:
                        pass
    
    model_ic = np.mean(model_ic_values) if model_ic_values else 0
    model_icir = (np.mean(model_ic_values) / np.std(model_ic_values)) if model_ic_values and np.std(model_ic_values) > 0 else 0
    
    print(f"\n  Model IC on test set: {model_ic:.4f}")
    print(f"  Model ICIR on test set: {model_icir:.4f}")
    
    # Step 2d: Map effective factors to existing 6 categories and compute optimized weights
    factor_categories = {
        'trend': ['MA', 'MACD', 'KUP', 'KLOW', 'KSFT', 'OPEN', 'CLOSE', 'HIGH', 'LOW', 'MID'],
        'momentum': ['ROC', 'RSI', 'MOM', 'RET', 'CHANGE', 'KLEN', 'KMID', 'BETA'],
        'volume': ['VOL', 'VWAP', 'TURN', 'AMOUNT', 'VSTD', 'CNTP', 'CNTN', 'CNT0'],
        'pullback': ['ATR', 'BOLL', 'SKEW', 'KURT', 'MAX', 'MIN', 'QTLU', 'QTLD', 'RANGE'],
        'quality': ['STD', 'CV', 'RANK', 'RSQR', 'RESI', 'IMAX', 'IMIN', 'IMXD'],
        'fundamental': ['PE', 'PB', 'PS', 'ROE', 'ROA', 'EPS', 'DCF', 'MEAN'],
    }
    
    category_ic = {cat: [] for cat in factor_categories}
    for factor_name, ic_info in effective.items():
        for cat, keywords in factor_categories.items():
            if any(kw in factor_name.upper() for kw in keywords):
                category_ic[cat].append(abs(ic_info['ic_mean']))
                break
    
    # Compute weights
    category_weights = {}
    total_ic = 0
    for cat, ics in category_ic.items():
        mean_ic = np.mean(ics) if ics else 0
        category_weights[cat] = mean_ic
        total_ic += mean_ic
    
    if total_ic > 0:
        for cat in category_weights:
            category_weights[cat] /= total_ic
    
    # Ensure all categories have non-zero weight
    for cat in factor_categories:
        if cat not in category_weights or category_weights[cat] == 0:
            category_weights[cat] = 0.01
    
    # Re-normalize
    total = sum(category_weights.values())
    for cat in category_weights:
        category_weights[cat] /= total
    
    print(f"\n  Qlib-optimized factor weights:")
    for cat in ['trend', 'momentum', 'pullback', 'quality', 'fundamental', 'volume']:
        print(f"    {cat:15s}: {category_weights.get(cat, 0):.4f}")
    
    return {
        'weights': category_weights,
        'effective_factors': len(effective),
        'model_ic': model_ic,
        'model_icir': model_icir,
        'factor_ics': {k: v for k, v in sorted(factor_ics.items(), key=lambda x: abs(x[1]['ic_mean']), reverse=True)[:20]},
    }


def main():
    """Main pipeline"""
    print("=" * 60)
    print("Qlib Full Optimization Pipeline")
    print(f"Backtest window: {BACKTEST_START} ~ {BACKTEST_END} (3 months)")
    print("=" * 60)
    
    # Initialize
    config = ConfigManager()
    db = DatabaseManager(config)
    
    trade_dates = load_trade_dates(db)
    print(f"Total trade dates in DB: {len(trade_dates)}")
    print(f"Date range: {trade_dates[0]} ~ {trade_dates[-1]}")
    
    signal_dates = get_signal_dates(trade_dates, BACKTEST_START, BACKTEST_END, max(HORIZONS))
    print(f"Signal dates: {len(signal_dates)} ({signal_dates[0]} ~ {signal_dates[-1]})")
    
    # ============================================================
    # Phase 1: Baseline backtest (current enhanced strategy)
    # ============================================================
    print("\n" + "=" * 60)
    print("Phase 1: Baseline Backtest (current enhanced strategy)")
    print("=" * 60)
    
    baseline_config = {
        "stock_selection.strategy_profile": "enhanced",
        "stock_selection.enhanced_weight_profile": "active",
    }
    
    print(f"\n  Running baseline selection ({len(signal_dates)} days)...")
    baseline_rec = run_selection_for_dates(signal_dates, db, baseline_config)
    print(f"  Baseline recommendations: {len(baseline_rec)}")
    
    baseline_results = {}
    for h in HORIZONS:
        result = evaluate_recommendations(baseline_rec, db, trade_dates, h)
        result.label = "baseline"
        baseline_results[h] = result
        print_backtest_result("Baseline", result, h)
    
    # ============================================================
    # Phase 2: Qlib optimization
    # ============================================================
    qlib_result = run_qlib_optimization()
    optimized_weights = qlib_result['weights']
    
    # ============================================================
    # Phase 3: Optimized backtest
    # ============================================================
    print("\n" + "=" * 60)
    print("Phase 3: Optimized Backtest (Qlib-optimized weights)")
    print("=" * 60)
    
    # Apply optimized weights
    optimized_config = {
        "stock_selection.strategy_profile": "enhanced",
        "stock_selection.enhanced_weight_profile": "active",
        "stock_selection.trend_factor_weight": optimized_weights.get('trend', 0.2613),
        "stock_selection.momentum_factor_weight": optimized_weights.get('momentum', 0.3324),
        "stock_selection.pullback_factor_weight": optimized_weights.get('pullback', 0.2164),
        "stock_selection.quality_factor_weight": optimized_weights.get('quality', 0.1122),
        "stock_selection.fundamental_factor_weight": optimized_weights.get('fundamental', 0.0651),
        "stock_selection.volume_factor_weight": optimized_weights.get('volume', 0.0125),
    }
    
    print(f"\n  Running optimized selection ({len(signal_dates)} days)...")
    optimized_rec = run_selection_for_dates(signal_dates, db, optimized_config)
    print(f"  Optimized recommendations: {len(optimized_rec)}")
    
    optimized_results = {}
    for h in HORIZONS:
        result = evaluate_recommendations(optimized_rec, db, trade_dates, h)
        result.label = "optimized"
        optimized_results[h] = result
        print_backtest_result("Optimized", result, h)
    
    # ============================================================
    # Phase 4: Comparison report
    # ============================================================
    print("\n" + "=" * 60)
    print("Phase 4: Comparison Report")
    print("=" * 60)
    
    current_weights = {
        'trend': 0.2613, 'momentum': 0.3324, 'pullback': 0.2164,
        'quality': 0.1122, 'fundamental': 0.0651, 'volume': 0.0125,
    }
    
    print(f"\n  Weight Changes:")
    print(f"  {'Factor':15s}  {'Current':>8s}  {'Optimized':>8s}  {'Change':>8s}")
    print("  " + "-" * 45)
    for cat in ['trend', 'momentum', 'pullback', 'quality', 'fundamental', 'volume']:
        cur = current_weights.get(cat, 0)
        opt = optimized_weights.get(cat, 0)
        print(f"  {cat:15s}  {cur:8.4f}  {opt:8.4f}  {opt-cur:+8.4f}")
    
    print(f"\n  Performance Comparison (main horizon T+{MAIN_HORIZON}):")
    print(f"  {'Metric':20s}  {'Baseline':>10s}  {'Optimized':>10s}  {'Change':>10s}")
    print("  " + "-" * 55)
    
    bl = baseline_results[MAIN_HORIZON]
    op = optimized_results[MAIN_HORIZON]
    
    metrics = [
        ('Trades',        bl.sample_count, op.sample_count, False),
        ('Mean return',   bl.mean_return, op.mean_return, True),
        ('Median return', bl.median_return, op.median_return, True),
        ('Win rate',      bl.win_rate, op.win_rate, True),
        ('Sharpe ratio',  bl.sharpe_ratio, op.sharpe_ratio, True),
        ('Max drawdown',  bl.max_drawdown, op.max_drawdown, True),
        ('Total return',  bl.total_return, op.total_return, True),
        ('Day mean ret',  bl.day_mean_return, op.day_mean_return, True),
        ('Day win rate',  bl.day_win_rate, op.day_win_rate, True),
        ('Avg MFE',       bl.avg_mfe, op.avg_mfe, True),
        ('Avg MAE',       bl.avg_mae, op.avg_mae, True),
    ]
    
    for name, bl_val, op_val, is_pct in metrics:
        change = op_val - bl_val
        if is_pct:
            print(f"  {name:20s}  {bl_val:10.4f}  {op_val:10.4f}  {change:+10.4f}")
        else:
            print(f"  {name:20s}  {bl_val:10d}  {op_val:10d}  {change:+10d}")
    
    # All horizons comparison
    print(f"\n  All Horizons Comparison:")
    for h in HORIZONS:
        bl_h = baseline_results[h]
        op_h = optimized_results[h]
        print(f"\n  T+{h}:")
        print(f"    Mean return: {bl_h.mean_return:.4f} -> {op_h.mean_return:.4f} ({op_h.mean_return-bl_h.mean_return:+.4f})")
        print(f"    Win rate:    {bl_h.win_rate:.2%} -> {op_h.win_rate:.2%} ({op_h.win_rate-bl_h.win_rate:+.2%})")
        print(f"    Sharpe:      {bl_h.sharpe_ratio:.4f} -> {op_h.sharpe_ratio:.4f} ({op_h.sharpe_ratio-bl_h.sharpe_ratio:+.4f})")
    
    # Save results
    os.makedirs('output', exist_ok=True)
    
    report = {
        'backtest_window': f'{BACKTEST_START}~{BACKTEST_END}',
        'signal_days': len(signal_dates),
        'current_weights': current_weights,
        'optimized_weights': optimized_weights,
        'qlib_info': {
            'effective_factors': qlib_result['effective_factors'],
            'model_ic': qlib_result['model_ic'],
            'model_icir': qlib_result['model_icir'],
        },
        'baseline': {f'T+{h}': asdict(r) for h, r in baseline_results.items()},
        'optimized': {f'T+{h}': asdict(r) for h, r in optimized_results.items()},
    }
    
    with open('output/qlib_optimization_report.json', 'w', encoding='utf-8') as f:
        json.dump(report, f, indent=2, ensure_ascii=False, default=str)
    
    print(f"\n  Report saved to: output/qlib_optimization_report.json")
    
    print("\n" + "=" * 60)
    print("Pipeline Complete!")
    print("=" * 60)


if __name__ == '__main__':
    main()
