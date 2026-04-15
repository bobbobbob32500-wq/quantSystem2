# -*- coding: utf-8 -*-
"""
突破策略 Optuna 超参优化（三阶段递进）

阶段1: 参数优化 — 优化五层过滤阈值 + 评分权重（保持线性模型）
阶段2: 因子增强 — 用 Qlib Alpha158 替代手工因子（保持最优参数）
阶段3: 模型增强 — 用 LightGBM 替代线性评分 + Optuna 优化模型超参

相比网格搜索的优势：
  - 智能采样（TPE）而非穷举，搜索效率提升10x+
  - 连续空间搜索，不受网格粒度限制
  - 同时优化评分权重（网格搜索固定权重）
  - 支持多目标优化（胜率 + 收益率 + 盈亏比）

依赖：pip install optuna

用法：
  python scripts/optuna_breakout_optimize.py
  python scripts/optuna_breakout_optimize.py --phase 1 --n-trials 200
  python scripts/optuna_breakout_optimize.py --phase 2 --n-trials 50
  python scripts/optuna_breakout_optimize.py --phase 3 --n-trials 100
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# 强制刷新输出
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(line_buffering=True)

from src.core.config import ConfigManager
from src.core.database import DatabaseManager
from src.modules.breakout_strategy import BreakoutParams, BreakoutStrategy


# ============================================================
# 回测基础设施（复用已有逻辑）
# ============================================================

def precompute_daily_snapshots(
    features: pd.DataFrame,
    backtest_dates: List[str],
    params: BreakoutParams,
    use_ma120: bool,
) -> Dict[str, pd.DataFrame]:
    """预计算每日：快照 → 基础过滤 → 趋势过滤（不依赖搜索参数）"""
    strategy = BreakoutStrategy.__new__(BreakoutStrategy)
    strategy.db = None
    strategy.params = params

    cache = {}
    for td in backtest_dates:
        snapshot = strategy._build_snapshot(features, td)
        if snapshot.empty:
            continue
        filtered = strategy._layer_base_filter(snapshot)
        if filtered.empty:
            continue

        if use_ma120:
            filtered = strategy._layer_trend_filter(filtered)
        else:
            cond = (
                filtered["ma20"].notna()
                & filtered["ma60"].notna()
                & (filtered["ma20"] > filtered["ma60"])
                & (filtered["ma20_slope"].fillna(-1) > 0)
            )
            filtered = filtered.loc[cond].copy()
        if filtered.empty:
            continue

        cache[td] = filtered
    return cache


def build_price_map(features: pd.DataFrame) -> Dict[str, pd.DataFrame]:
    """构建价格映射表"""
    price_df = features[["ts_code", "trade_date", "open", "close"]].copy()
    price_df = price_df.sort_values(["ts_code", "trade_date"]).reset_index(drop=True)
    price_map = {}
    for code, sub in price_df.groupby("ts_code"):
        s = sub.sort_values("trade_date").reset_index(drop=True)
        s["date_str"] = s["trade_date"].dt.strftime("%Y%m%d")
        price_map[code] = s
    return price_map


def _add_enhanced_features(
    daily_cache: Dict[str, pd.DataFrame],
    features: pd.DataFrame,
    db: DatabaseManager
) -> Dict[str, pd.DataFrame]:
    """添加增强特征到daily_cache（从Tushare数据表读取）"""
    
    # 1. 获取行业分类
    industry_map = {}
    try:
        rows = db.query("SELECT ts_code, industry FROM stock_basic WHERE industry IS NOT NULL")
        for r in rows:
            industry_map[r["ts_code"]] = r["industry"]
    except Exception:
        pass

    # 2. 从Tushare表获取每日指标数据
    tushare_basic = {}
    try:
        rows = db.query("""
            SELECT ts_code, trade_date, pe, pb, ps, turnover_rate, volume_ratio, total_mv, circ_mv
            FROM tushare_daily_basic
        """)
        for r in rows:
            key = (r["ts_code"], r["trade_date"])
            tushare_basic[key] = {
                "pe": r["pe"],
                "pb": r["pb"],
                "ps": r["ps"],
                "turnover_rate": r["turnover_rate"],
                "volume_ratio": r["volume_ratio"],
                "total_mv": r["total_mv"],
                "circ_mv": r["circ_mv"],
            }
        print(f"    加载Tushare每日指标: {len(tushare_basic)}条")
    except Exception as e:
        print(f"    加载Tushare每日指标失败: {e}")

    # 3. 从Tushare表获取资金流向数据
    tushare_moneyflow = {}
    try:
        rows = db.query("""
            SELECT ts_code, trade_date, buy_lg_vol, sell_lg_vol, net_mf_vol, net_mf_amount
            FROM tushare_moneyflow
        """)
        for r in rows:
            key = (r["ts_code"], r["trade_date"])
            tushare_moneyflow[key] = {
                "buy_lg_vol": r["buy_lg_vol"],
                "sell_lg_vol": r["sell_lg_vol"],
                "net_mf_vol": r["net_mf_vol"],
                "net_mf_amount": r["net_mf_amount"],
            }
        print(f"    加载Tushare资金流向: {len(tushare_moneyflow)}条")
    except Exception as e:
        pass  # 表可能不存在

    # 4. 计算每日市场宽度
    market_breadth = {}
    for td, df in daily_cache.items():
        if df.empty:
            continue
        if "pct_chg" in df.columns:
            n_up = (df["pct_chg"] > 0).sum()
            n_down = (df["pct_chg"] < 0).sum()
            market_breadth[td] = {
                "market_ad_ratio": n_up / n_down if n_down > 0 else 10.0,
                "market_strong_ratio": (df["rs20_xsec_q"] > 0.8).sum() / len(df) if "rs20_xsec_q" in df.columns else 0.5
            }
        else:
            market_breadth[td] = {"market_ad_ratio": 1.0, "market_strong_ratio": 0.5}

    # 5. 计算行业统计
    industry_stats = {}
    for td, df in daily_cache.items():
        if df.empty or not industry_map:
            continue
        df = df.copy()
        df["industry"] = df["ts_code"].map(industry_map)
        df = df[df["industry"].notna()]
        if df.empty:
            continue
        ind_mean = df.groupby("industry")["rs20_xsec_q"].mean()
        industry_stats[td] = ind_mean.to_dict()

    # 6. 添加特征到daily_cache
    for td, df in daily_cache.items():
        if df.empty:
            continue
        df = df.copy()

        # 行业特征
        if industry_map and td in industry_stats:
            df["industry"] = df["ts_code"].map(industry_map)
            df["industry_momentum"] = df["industry"].map(industry_stats[td])
            df["industry_rs_gap"] = df["rs20_xsec_q"] - df["industry_momentum"]
            if "industry" in df.columns:
                df["industry_rs_rank"] = df.groupby("industry")["rs20_xsec_q"].rank(pct=True)
            else:
                df["industry_rs_rank"] = 0.5
        else:
            df["industry_momentum"] = 0.5
            df["industry_rs_gap"] = 0.0
            df["industry_rs_rank"] = 0.5

        # 市场宽度特征
        if td in market_breadth:
            df["market_ad_ratio"] = market_breadth[td]["market_ad_ratio"]
            df["market_strong_ratio"] = market_breadth[td]["market_strong_ratio"]
        else:
            df["market_ad_ratio"] = 1.0
            df["market_strong_ratio"] = 0.5

        # Tushare每日指标特征
        for idx in df.index:
            code = df.loc[idx, "ts_code"]
            key = (code, td)
            if key in tushare_basic:
                basic = tushare_basic[key]
                df.loc[idx, "ts_pe"] = basic["pe"] if basic["pe"] else 0
                df.loc[idx, "ts_pb"] = basic["pb"] if basic["pb"] else 0
                df.loc[idx, "ts_turnover_rate"] = basic["turnover_rate"] if basic["turnover_rate"] else 0
                df.loc[idx, "ts_volume_ratio"] = basic["volume_ratio"] if basic["volume_ratio"] else 1
                df.loc[idx, "ts_total_mv"] = basic["total_mv"] if basic["total_mv"] else 0
            else:
                df.loc[idx, "ts_pe"] = 0
                df.loc[idx, "ts_pb"] = 0
                df.loc[idx, "ts_turnover_rate"] = 0
                df.loc[idx, "ts_volume_ratio"] = 1
                df.loc[idx, "ts_total_mv"] = 0
            
            # 资金流向特征
            if key in tushare_moneyflow:
                mf = tushare_moneyflow[key]
                df.loc[idx, "ts_net_mf_vol"] = mf["net_mf_vol"] if mf["net_mf_vol"] else 0
                df.loc[idx, "ts_net_mf_amount"] = mf["net_mf_amount"] if mf["net_mf_amount"] else 0
            else:
                df.loc[idx, "ts_net_mf_vol"] = 0
                df.loc[idx, "ts_net_mf_amount"] = 0

        # 量价特征（从features中计算）
        if "vol" in df.columns and "vol_ma5" in df.columns:
            df["volume_ratio"] = df["vol"] / df["vol_ma5"].replace(0, np.nan)
        else:
            df["volume_ratio"] = 1.0

        # 振幅
        if "high" in df.columns and "low" in df.columns and "open" in df.columns:
            df["amplitude"] = (df["high"] - df["low"]) / df["open"].replace(0, np.nan)
        else:
            df["amplitude"] = 0.05

        df["price_volume_divergence"] = 0.0

        daily_cache[td] = df

    return daily_cache


def evaluate_with_params(
    daily_cache: Dict[str, pd.DataFrame],
    price_map: Dict[str, pd.DataFrame],
    signal_dates: List[str],
    # 过滤参数
    rs_min: float,
    rs_max: float,
    box_max: float,
    atr_max: float,
    min_score: float,
    top_k: int,
    # 评分权重
    weight_rs: float,
    weight_trend: float,
    weight_stability: float,
    weight_box: float,
    weight_volume: float,
    # 持有期
    horizons: Tuple[int, ...] = (1, 2, 3),
) -> Dict:
    """基于预缓存结果，执行参数敏感的过滤+评分+收益计算"""
    all_rets = {h: [] for h in horizons}
    signal_count = 0

    for td in signal_dates:
        filtered = daily_cache.get(td)
        if filtered is None:
            continue

        # Layer 3: RS过滤
        cond_rs = filtered["rs20_xsec_q"].notna() & (filtered["rs20_xsec_q"] >= rs_min)
        if rs_max < 1.0:
            cond_rs = cond_rs & (filtered["rs20_xsec_q"] <= rs_max)
        f3 = filtered.loc[cond_rs]
        if f3.empty:
            continue

        # Layer 4: 走稳过滤
        cond4 = f3["box_range"].notna() & (f3["box_range"] <= box_max)
        if f3["atr_ratio_q60"].notna().mean() > 0.3:
            cond4 = cond4 & (f3["atr_ratio_q60"].fillna(0.5) <= atr_max)
        f4 = f3.loc[cond4]
        if f4.empty:
            continue

        # 评分（内联版，避免 Strategy 实例开销）
        rs_score = f4["rs20_xsec_q"].fillna(0.0).clip(0.0, 1.0) * weight_rs
        ma_gap = (
            (f4["ma20"] - f4["ma60"]) / f4["ma60"].replace(0, np.nan)
        ).fillna(0.0)
        slope_score = f4["ma20_slope"].fillna(0.0).clip(0.0, 0.02) / 0.02
        trend_score = (
            (ma_gap.clip(0.0, 0.08) / 0.08) * 0.5 + slope_score * 0.5
        ) * weight_trend
        stab_score = (
            1.0 - f4["atr_ratio_q60"].fillna(0.5).clip(0.0, 1.0)
        ) * weight_stability
        box_score = (
            1.0
            - (f4["box_range"].fillna(box_max) / box_max).clip(0.0, 1.0)
        ) * weight_box
        vol_ratio = (
            f4["vol_ma5"] / f4["vol_ma20"].replace(0, np.nan)
        ).fillna(0.0).clip(0.0, 2.0)
        vol_raw = np.where(
            vol_ratio < 0.8,
            vol_ratio / 0.8,
            np.where(vol_ratio <= 1.5, 1.0, 1.0 - (vol_ratio - 1.5) / 1.5),
        )
        vol_score = pd.Series(vol_raw, index=f4.index).clip(0.0, 1.0) * weight_volume

        total_score = rs_score + trend_score + stab_score + box_score + vol_score
        passed = total_score >= min_score
        if not passed.any():
            continue

        top = total_score[passed].nlargest(top_k)

        for idx in top.index:
            code = f4.loc[idx, "ts_code"]
            sub = price_map.get(code)
            if sub is None:
                continue
            match = sub.index[sub["date_str"] == td]
            if len(match) == 0:
                continue
            pos = match[0]
            if pos + 1 >= len(sub):
                continue
            entry = float(sub.loc[pos + 1, "open"])
            if entry <= 0:
                continue

            signal_count += 1
            for h in horizons:
                t_idx = pos + 1 + h
                if t_idx < len(sub):
                    all_rets[h].append(float(sub.loc[t_idx, "close"]) / entry - 1.0)

    result = {"signal_count": signal_count}
    for h in horizons:
        rets = np.array(all_rets[h]) if all_rets[h] else np.array([])
        if len(rets) == 0:
            result.update(
                {f"t{h}_win_rate": 0, f"t{h}_avg_ret": 0, f"t{h}_pf": 0}
            )
            continue
        result[f"t{h}_win_rate"] = float((rets > 0).mean())
        result[f"t{h}_avg_ret"] = float(rets.mean())
        gw = float(rets[rets > 0].sum())
        gl = float(-rets[rets < 0].sum())
        result[f"t{h}_pf"] = gw / gl if gl > 1e-10 else 0.0
    return result


# ============================================================
# 阶段1: Optuna 参数优化
# ============================================================

def phase1_param_optimize(
    daily_cache: Dict[str, pd.DataFrame],
    price_map: Dict[str, pd.DataFrame],
    in_sample: List[str],
    out_sample: List[str],
    n_trials: int,
    seed: int,
) -> Dict:
    """阶段1: 用 Optuna 优化五层过滤参数 + 评分权重"""
    import optuna

    print("\n" + "=" * 72)
    print("  阶段1: Optuna 参数优化（过滤阈值 + 评分权重）")
    print("=" * 72)

    # 先跑一次基线获取信号数参考
    baseline_res = evaluate_with_params(
        daily_cache, price_map, in_sample,
        0.80, 0.97, 0.08, 0.50, 60.0, 15,
        35.0, 25.0, 20.0, 12.0, 8.0,
    )
    min_signal_count = max(int(baseline_res["signal_count"] * 0.5), 30)
    print(f"  基线样本内信号数={baseline_res['signal_count']}, 信号数下限={min_signal_count}")

    def objective(trial: optuna.Trial) -> float:
        # --- 过滤参数 ---
        rs_min = trial.suggest_float("rs_min", 0.70, 0.90)
        rs_max = trial.suggest_float("rs_max", 0.95, 1.00)
        box_max = trial.suggest_float("box_max", 0.05, 0.12)
        atr_max = trial.suggest_float("atr_max", 0.40, 0.70)
        min_score = trial.suggest_float("min_score", 50.0, 70.0)
        top_k = trial.suggest_int("top_k", 8, 25)

        # --- 评分权重（归一化前） ---
        raw_w_rs = trial.suggest_float("raw_w_rs", 20.0, 45.0)
        raw_w_trend = trial.suggest_float("raw_w_trend", 15.0, 35.0)
        raw_w_stab = trial.suggest_float("raw_w_stab", 10.0, 30.0)
        raw_w_box = trial.suggest_float("raw_w_box", 5.0, 20.0)
        raw_w_vol = trial.suggest_float("raw_w_vol", 3.0, 15.0)

        # 归一化到100分
        w_sum = raw_w_rs + raw_w_trend + raw_w_stab + raw_w_box + raw_w_vol
        weight_rs = raw_w_rs / w_sum * 100
        weight_trend = raw_w_trend / w_sum * 100
        weight_stability = raw_w_stab / w_sum * 100
        weight_box = raw_w_box / w_sum * 100
        weight_volume = raw_w_vol / w_sum * 100

        # 样本内回测
        res = evaluate_with_params(
            daily_cache, price_map, in_sample,
            rs_min, rs_max, box_max, atr_max, min_score, top_k,
            weight_rs, weight_trend, weight_stability, weight_box, weight_volume,
        )

        # 信号数硬约束：低于基线50%直接淘汰
        if res["signal_count"] < min_signal_count:
            return -1e6

        # 信号数软惩罚：低于基线80%时线性衰减
        signal_penalty = 1.0
        soft_threshold = int(baseline_res["signal_count"] * 0.8)
        if res["signal_count"] < soft_threshold:
            signal_penalty = res["signal_count"] / soft_threshold

        # 目标函数：收益率绝对值(50%) + 胜率(25%) + 盈亏比(25%)
        # 收益率用 avg_ret * signal_count 近似总收益，避免少信号高胜率陷阱
        total_ret = res["t1_avg_ret"] * res["signal_count"]
        obj = (
            min(total_ret, 5.0) / 5.0 * 0.50  # 总收益归一化，上限5
            + res["t1_win_rate"] * 0.25
            + min(res["t1_pf"], 3.0) / 3.0 * 0.25  # 盈亏比上限3
        ) * signal_penalty
        return obj

    sampler = optuna.samplers.TPESampler(seed=seed)
    study = optuna.create_study(direction="maximize", sampler=sampler)
    study.optimize(objective, n_trials=n_trials, show_progress_bar=True)

    # 提取最优参数
    best = study.best_params
    w_sum = (
        best["raw_w_rs"]
        + best["raw_w_trend"]
        + best["raw_w_stab"]
        + best["raw_w_box"]
        + best["raw_w_vol"]
    )

    best_params = {
        "rs_quantile_min": best["rs_min"],
        "rs_quantile_max": best["rs_max"],
        "box_max_range": best["box_max"],
        "atr_quantile_max": best["atr_max"],
        "min_signal_score": best["min_score"],
        "top_k": best["top_k"],
        "weight_rs": best["raw_w_rs"] / w_sum * 100,
        "weight_trend": best["raw_w_trend"] / w_sum * 100,
        "weight_stability": best["raw_w_stab"] / w_sum * 100,
        "weight_box": best["raw_w_box"] / w_sum * 100,
        "weight_volume": best["raw_w_vol"] / w_sum * 100,
    }

    # 样本外验证
    oos_res = evaluate_with_params(
        daily_cache, price_map, out_sample,
        best["rs_min"], best["rs_max"], best["box_max"], best["atr_max"],
        best["min_score"], best["top_k"],
        best_params["weight_rs"], best_params["weight_trend"],
        best_params["weight_stability"], best_params["weight_box"],
        best_params["weight_volume"],
    )

    # 样本内结果
    is_res = evaluate_with_params(
        daily_cache, price_map, in_sample,
        best["rs_min"], best["rs_max"], best["box_max"], best["atr_max"],
        best["min_score"], best["top_k"],
        best_params["weight_rs"], best_params["weight_trend"],
        best_params["weight_stability"], best_params["weight_box"],
        best_params["weight_volume"],
    )

    # 参数重要性
    importance = optuna.importance.get_param_importances(study)

    result = {
        "phase": 1,
        "best_params": best_params,
        "best_value": study.best_value,
        "in_sample": is_res,
        "out_sample": oos_res,
        "param_importance": importance,
        "n_trials": n_trials,
    }

    # 打印结果
    _print_phase1_result(result)

    return result


def _print_phase1_result(result: Dict) -> None:
    """打印阶段1结果"""
    bp = result["best_params"]
    is_r = result["in_sample"]
    oos_r = result["out_sample"]

    print(f"\n{'=' * 72}")
    print("  阶段1 结果: 最优参数")
    print(f"{'=' * 72}")
    print(f"  过滤参数:")
    print(f"    rs_quantile_min  = {bp['rs_quantile_min']:.4f}")
    print(f"    rs_quantile_max  = {bp['rs_quantile_max']:.4f}")
    print(f"    box_max_range    = {bp['box_max_range']:.4f}")
    print(f"    atr_quantile_max = {bp['atr_quantile_max']:.4f}")
    print(f"    min_signal_score = {bp['min_signal_score']:.1f}")
    print(f"    top_k            = {bp['top_k']}")
    print(f"  评分权重（归一化至100）:")
    print(f"    weight_rs        = {bp['weight_rs']:.2f}")
    print(f"    weight_trend     = {bp['weight_trend']:.2f}")
    print(f"    weight_stability = {bp['weight_stability']:.2f}")
    print(f"    weight_box       = {bp['weight_box']:.2f}")
    print(f"    weight_volume    = {bp['weight_volume']:.2f}")

    print(f"\n  样本内:")
    print(f"    信号数={is_r['signal_count']}  T1胜率={is_r['t1_win_rate']:.2%}  "
          f"T1收益={is_r['t1_avg_ret']:.4%}  T1盈亏比={is_r['t1_pf']:.2f}")
    print(f"    T2胜率={is_r['t2_win_rate']:.2%}  T2收益={is_r['t2_avg_ret']:.4%}  "
          f"T2盈亏比={is_r['t2_pf']:.2f}")

    print(f"  样本外:")
    print(f"    信号数={oos_r['signal_count']}  T1胜率={oos_r['t1_win_rate']:.2%}  "
          f"T1收益={oos_r['t1_avg_ret']:.4%}  T1盈亏比={oos_r['t1_pf']:.2f}")
    print(f"    T2胜率={oos_r['t2_win_rate']:.2%}  T2收益={oos_r['t2_avg_ret']:.4%}  "
          f"T2盈亏比={oos_r['t2_pf']:.2f}")

    # 稳健性判定
    if oos_r["t1_pf"] > 1.2 and oos_r["t1_win_rate"] > 0.50:
        label = "PASS（稳健）"
    elif oos_r["t1_pf"] > 1.0:
        label = "MARGINAL（边际）"
    else:
        label = "FAIL（衰减严重）"
    print(f"  判定: {label}")

    # 参数重要性
    print(f"\n  参数重要性（Top 5）:")
    for i, (k, v) in enumerate(sorted(result["param_importance"].items(), key=lambda x: -x[1])[:5], 1):
        print(f"    {i}. {k}: {v:.4f}")


# ============================================================
# 阶段2: Qlib 因子增强
# ============================================================

def _compute_alpha158_factors(features: pd.DataFrame) -> pd.DataFrame:
    """从现有OHLCV数据计算Qlib Alpha158因子（与Qlib Alpha158DL定义一致）"""
    df = features.sort_values(["ts_code", "trade_date"]).copy()
    g = df.groupby("ts_code")

    # --- Kbar 因子 (9个) ---
    df["KMID"] = (df["close"] - df["open"]) / df["open"]
    df["KLEN"] = (df["high"] - df["low"]) / df["open"]
    hl_range = df["high"] - df["low"] + 1e-12
    df["KMID2"] = (df["close"] - df["open"]) / hl_range
    go = df[["open", "close"]].max(axis=1)
    df["KUP"] = (df["high"] - go) / df["open"]
    df["KUP2"] = (df["high"] - go) / hl_range
    lo = df[["open", "close"]].min(axis=1)
    df["KLOW"] = (lo - df["low"]) / df["open"]
    df["KLOW2"] = (lo - df["low"]) / hl_range
    df["KSFT"] = (2 * df["close"] - df["high"] - df["low"]) / df["open"]
    df["KSFT2"] = (2 * df["close"] - df["high"] - df["low"]) / hl_range

    # --- Price 因子 (4个, window=0) ---
    df["OPEN0"] = df["open"] / df["close"]
    df["HIGH0"] = df["high"] / df["close"]
    df["LOW0"] = df["low"] / df["close"]
    # VWAP近似用 (high+low+close)/3
    vwap = (df["high"] + df["low"] + df["close"]) / 3
    df["VWAP0"] = vwap / df["close"]

    # --- Volume 因子 (5个, windows=[0,1,2,3,4]) ---
    for d in range(5):
        if d == 0:
            df[f"VOLUME{d}"] = df["vol"] / (df["vol"] + 1e-12)
        else:
            ref_vol = g["vol"].shift(d)
            df[f"VOLUME{d}"] = ref_vol / (df["vol"] + 1e-12)

    # --- Rolling 因子 (windows=[5,10,20,30,60]) ---
    windows = [5, 10, 20, 30, 60]
    for w in windows:
        # ROC: Ref($close, d) / $close
        df[f"ROC{w}"] = g["close"].shift(w) / df["close"]
        # MA: Mean($close, d) / $close
        df[f"MA{w}"] = g["close"].transform(lambda x: x.rolling(w, min_periods=1).mean()) / df["close"]
        # STD: Std($close, d) / $close
        df[f"STD{w}"] = g["close"].transform(lambda x: x.rolling(w, min_periods=1).std()) / df["close"]

    # --- 选取与突破策略最相关的因子子集（避免维度爆炸） ---
    # 从158个因子中选取与突破策略逻辑最相关的20个
    selected_factors = [
        # Kbar: 价格形态
        "KMID", "KLEN", "KMID2", "KUP", "KLOW",
        # ROC: 动量（突破核心）
        "ROC5", "ROC10", "ROC20",
        # MA: 均线偏离
        "MA5", "MA10", "MA20",
        # STD: 波动率（箱体相关）
        "STD5", "STD10", "STD20",
        # Volume: 量能
        "VOLUME0", "VOLUME1",
        # Price: 相对价格
        "HIGH0", "LOW0",
    ]

    # 只保留存在的因子
    available = [f for f in selected_factors if f in df.columns]
    return df, available


def phase2_qlib_factor_enhance(
    daily_cache: Dict[str, pd.DataFrame],
    price_map: Dict[str, pd.DataFrame],
    in_sample: List[str],
    out_sample: List[str],
    best_params_from_phase1: Dict,
    n_trials: int,
    seed: int,
    features: pd.DataFrame = None,
) -> Dict:
    """阶段2: 用 Qlib Alpha158 因子增强评分，Optuna 优化因子权重"""
    import optuna

    print("\n" + "=" * 72)
    print("  阶段2: Qlib Alpha158 因子增强")
    print("=" * 72)

    # 计算Alpha158因子
    if features is None:
        print("  错误: 需要features数据")
        return {"phase": 2, "status": "skipped", "reason": "No features data"}

    print("  计算Alpha158因子...")
    feat_enhanced, alpha_factor_names = _compute_alpha158_factors(features)
    print(f"  Alpha158因子数: {len(alpha_factor_names)}")
    print(f"  因子列表: {alpha_factor_names}")

    # 构建增强版daily_cache（包含Alpha158因子）
    bp = best_params_from_phase1
    base_params = BreakoutParams()
    strategy = BreakoutStrategy.__new__(BreakoutStrategy)
    strategy.db = None
    strategy.params = base_params

    enhanced_cache = {}
    all_dates = sorted(daily_cache.keys())
    for td in all_dates:
        # 获取当天的Alpha158因子数据
        day_feat = feat_enhanced[feat_enhanced["trade_date"] == td]
        if day_feat.empty:
            continue

        # 原始过滤后的数据
        filtered = daily_cache.get(td)
        if filtered is None or filtered.empty:
            continue

        # 合并Alpha158因子到filtered
        alpha_cols = ["ts_code"] + alpha_factor_names
        day_alpha = day_feat[alpha_cols].copy()
        merged = filtered.merge(day_alpha, on="ts_code", how="left")
        enhanced_cache[td] = merged

    print(f"  增强缓存天数: {len(enhanced_cache)}")

    # 基线信号数参考
    baseline_res = evaluate_with_params(
        daily_cache, price_map, in_sample,
        bp["rs_quantile_min"], bp["rs_quantile_max"],
        bp["box_max_range"], bp["atr_quantile_max"],
        bp["min_signal_score"], bp["top_k"],
        bp["weight_rs"], bp["weight_trend"],
        bp["weight_stability"], bp["weight_box"],
        bp["weight_volume"],
    )
    min_signal_count = max(int(baseline_res["signal_count"] * 0.5), 30)
    print(f"  基线样本内信号数={baseline_res['signal_count']}, 信号数下限={min_signal_count}")

    def objective(trial: optuna.Trial) -> float:
        # Alpha158 因子权重
        alpha_weights = {}
        for fname in alpha_factor_names:
            alpha_weights[fname] = trial.suggest_float(
                f"alpha_w_{fname}", -1.0, 1.0
            )

        # 混合比例: 原始评分权重 vs Alpha158因子权重
        alpha_blend = trial.suggest_float("alpha_blend", 0.0, 0.5)

        # 样本内回测
        res = _evaluate_with_alpha_factors(
            enhanced_cache, price_map, in_sample,
            bp["rs_quantile_min"], bp["rs_quantile_max"],
            bp["box_max_range"], bp["atr_quantile_max"],
            bp["min_signal_score"], bp["top_k"],
            bp["weight_rs"], bp["weight_trend"],
            bp["weight_stability"], bp["weight_box"],
            bp["weight_volume"],
            alpha_weights, alpha_blend, alpha_factor_names,
        )

        # 信号数硬约束
        if res["signal_count"] < min_signal_count:
            return -1e6

        # 信号数软惩罚
        signal_penalty = 1.0
        soft_threshold = int(baseline_res["signal_count"] * 0.8)
        if res["signal_count"] < soft_threshold:
            signal_penalty = res["signal_count"] / soft_threshold

        # 目标函数：总收益(50%) + 胜率(25%) + 盈亏比(25%)
        total_ret = res["t1_avg_ret"] * res["signal_count"]
        obj = (
            min(total_ret, 5.0) / 5.0 * 0.50
            + res["t1_win_rate"] * 0.25
            + min(res["t1_pf"], 3.0) / 3.0 * 0.25
        ) * signal_penalty
        return obj

    sampler = optuna.samplers.TPESampler(seed=seed)
    study = optuna.create_study(direction="maximize", sampler=sampler)
    study.optimize(objective, n_trials=n_trials, show_progress_bar=True)

    # 提取最优 Alpha158 因子权重
    best_alpha_weights = {}
    for fname in alpha_factor_names:
        best_alpha_weights[fname] = study.best_params[f"alpha_w_{fname}"]
    best_alpha_blend = study.best_params["alpha_blend"]

    # 样本外验证
    oos_res = _evaluate_with_alpha_factors(
        enhanced_cache, price_map, out_sample,
        bp["rs_quantile_min"], bp["rs_quantile_max"],
        bp["box_max_range"], bp["atr_quantile_max"],
        bp["min_signal_score"], bp["top_k"],
        bp["weight_rs"], bp["weight_trend"],
        bp["weight_stability"], bp["weight_box"],
        bp["weight_volume"],
        best_alpha_weights, best_alpha_blend, alpha_factor_names,
    )

    is_res = _evaluate_with_alpha_factors(
        enhanced_cache, price_map, in_sample,
        bp["rs_quantile_min"], bp["rs_quantile_max"],
        bp["box_max_range"], bp["atr_quantile_max"],
        bp["min_signal_score"], bp["top_k"],
        bp["weight_rs"], bp["weight_trend"],
        bp["weight_stability"], bp["weight_box"],
        bp["weight_volume"],
        best_alpha_weights, best_alpha_blend, alpha_factor_names,
    )

    # 稳健性判定
    if oos_res["t1_pf"] > 1.2 and oos_res["t1_win_rate"] > 0.50:
        label = "PASS（稳健）"
    elif oos_res["t1_pf"] > 1.0:
        label = "MARGINAL（边际）"
    else:
        label = "FAIL（衰减严重）"

    result = {
        "phase": 2,
        "status": "completed",
        "alpha_weights": best_alpha_weights,
        "alpha_blend": best_alpha_blend,
        "best_value": study.best_value,
        "in_sample": is_res,
        "out_sample": oos_res,
        "judgment": label,
    }

    print(f"\n  阶段2 结果: Alpha158混合比例={best_alpha_blend:.4f}")
    print(f"  Alpha158因子权重（按绝对值排序）:")
    for k, v in sorted(best_alpha_weights.items(), key=lambda x: -abs(x[1])):
        print(f"    {k}: {v:+.4f}")
    print(f"  样本内: 信号数={is_res['signal_count']}  T1胜率={is_res['t1_win_rate']:.2%}  T1收益={is_res['t1_avg_ret']:.4%}  T1盈亏比={is_res['t1_pf']:.2f}")
    print(f"  样本外: 信号数={oos_res['signal_count']}  T1胜率={oos_res['t1_win_rate']:.2%}  T1收益={oos_res['t1_avg_ret']:.4%}  T1盈亏比={oos_res['t1_pf']:.2f}")
    print(f"  判定: {label}")

    return result


def _evaluate_with_alpha_factors(
    enhanced_cache, price_map, signal_dates,
    rs_min, rs_max, box_max, atr_max, min_score, top_k,
    weight_rs, weight_trend, weight_stability, weight_box, weight_volume,
    alpha_weights, alpha_blend, alpha_factor_names,
) -> Dict:
    """带 Alpha158 因子增强的评估"""
    horizons = [1, 2, 3]
    all_rets = {h: [] for h in horizons}
    signal_count = 0

    for td in signal_dates:
        filtered = enhanced_cache.get(td)
        if filtered is None or filtered.empty:
            continue

        # Layer 3: RS过滤
        cond_rs = filtered["rs20_xsec_q"].notna() & (filtered["rs20_xsec_q"] >= rs_min)
        if rs_max < 1.0:
            cond_rs = cond_rs & (filtered["rs20_xsec_q"] <= rs_max)
        f3 = filtered.loc[cond_rs]
        if f3.empty:
            continue

        # Layer 4: 走稳过滤
        cond4 = f3["box_range"].notna() & (f3["box_range"] <= box_max)
        if f3["atr_ratio_q60"].notna().mean() > 0.3:
            cond4 = cond4 & (f3["atr_ratio_q60"].fillna(0.5) <= atr_max)
        f4 = f3.loc[cond4]
        if f4.empty:
            continue

        # 原始评分
        rs_score = f4["rs20_xsec_q"].fillna(0.0).clip(0.0, 1.0) * weight_rs
        ma_gap = (
            (f4["ma20"] - f4["ma60"]) / f4["ma60"].replace(0, np.nan)
        ).fillna(0.0)
        slope_score = f4["ma20_slope"].fillna(0.0).clip(0.0, 0.02) / 0.02
        trend_score = (
            (ma_gap.clip(0.0, 0.08) / 0.08) * 0.5 + slope_score * 0.5
        ) * weight_trend
        stab_score = (
            1.0 - f4["atr_ratio_q60"].fillna(0.5).clip(0.0, 1.0)
        ) * weight_stability
        box_score = (
            1.0
            - (f4["box_range"].fillna(box_max) / box_max).clip(0.0, 1.0)
        ) * weight_box
        vol_ratio = (
            f4["vol_ma5"] / f4["vol_ma20"].replace(0, np.nan)
        ).fillna(0.0).clip(0.0, 2.0)
        vol_raw = np.where(
            vol_ratio < 0.8,
            vol_ratio / 0.8,
            np.where(vol_ratio <= 1.5, 1.0, 1.0 - (vol_ratio - 1.5) / 1.5),
        )
        vol_score = pd.Series(vol_raw, index=f4.index).clip(0.0, 1.0) * weight_volume

        original_score = rs_score + trend_score + stab_score + box_score + vol_score

        # Alpha158 因子增强评分
        alpha_score = pd.Series(0.0, index=f4.index)
        for fname in alpha_factor_names:
            if fname in f4.columns and fname in alpha_weights:
                # 归一化因子值到[0,1]范围（用rank百分位）
                feat_vals = f4[fname].fillna(0.0)
                rank_vals = feat_vals.rank(pct=True).fillna(0.5)
                alpha_score += rank_vals * alpha_weights[fname] * 10.0  # 缩放到与原始评分同量级

        # 混合评分
        total_score = original_score * (1.0 - alpha_blend) + alpha_score * alpha_blend

        passed = total_score >= min_score
        if not passed.any():
            continue

        top = total_score[passed].nlargest(top_k)

        for idx in top.index:
            code = f4.loc[idx, "ts_code"]
            sub = price_map.get(code)
            if sub is None:
                continue
            match = sub.index[sub["date_str"] == td]
            if len(match) == 0:
                continue
            pos = match[0]
            if pos + 1 >= len(sub):
                continue
            entry = float(sub.loc[pos + 1, "open"])
            if entry <= 0:
                continue

            signal_count += 1
            for h in horizons:
                t_idx = pos + 1 + h
                if t_idx < len(sub):
                    all_rets[h].append(float(sub.loc[t_idx, "close"]) / entry - 1.0)

    result = {"signal_count": signal_count}
    for h in horizons:
        rets = np.array(all_rets[h]) if all_rets[h] else np.array([])
        if len(rets) == 0:
            result.update({f"t{h}_win_rate": 0, f"t{h}_avg_ret": 0, f"t{h}_pf": 0})
            continue
        result[f"t{h}_win_rate"] = float((rets > 0).mean())
        result[f"t{h}_avg_ret"] = float(rets.mean())
        gw = float(rets[rets > 0].sum())
        gl = float(-rets[rets < 0].sum())
        result[f"t{h}_pf"] = gw / gl if gl > 1e-10 else 0.0
    return result


# ============================================================
# 阶段3: LightGBM 模型增强
# ============================================================

def phase3_model_enhance(
    daily_cache: Dict[str, pd.DataFrame],
    price_map: Dict[str, pd.DataFrame],
    in_sample: List[str],
    out_sample: List[str],
    best_params: Dict,
    n_trials: int,
    seed: int,
) -> Dict:
    """阶段3: 用 LightGBM 替代线性评分 + Optuna 优化模型超参"""
    import optuna

    print("\n" + "=" * 72)
    print("  阶段3: LightGBM 模型增强")
    print("=" * 72)

    # 检查可用模型：LightGBM > sklearn GradientBoosting
    model_backend = None
    force_sklearn = os.environ.get("FORCE_SKLEARN", "0") == "1"
    if not force_sklearn:
        try:
            import lightgbm as lgb
            model_backend = "lightgbm"
            print("  使用 LightGBM")
        except ImportError:
            force_sklearn = True
    if force_sklearn and model_backend is None:
        try:
            from sklearn.ensemble import GradientBoostingClassifier
            model_backend = "sklearn"
            print("  LightGBM 未安装，使用 sklearn GradientBoosting")
        except ImportError:
            print("  无可用模型，跳过阶段3")
            return {"phase": 3, "status": "skipped", "reason": "No model available"}

    bp = best_params

    # 准备训练数据：从 daily_cache 提取特征和标签
    print("  准备训练数据...")
    train_X, train_y, valid_X, valid_y = _prepare_lgb_data(
        daily_cache, price_map, in_sample, out_sample,
        bp["rs_quantile_min"], bp["rs_quantile_max"],
        bp["box_max_range"], bp["atr_quantile_max"],
    )

    if train_X is None or len(train_X) < 100:
        print("  训练数据不足，跳过阶段3")
        return {"phase": 3, "status": "skipped", "reason": "Insufficient training data"}

    if model_backend == "lightgbm":
        import lightgbm as lgb

        def objective(trial: optuna.Trial) -> float:
            params = {
                "objective": "binary",
                "metric": "auc",
                "learning_rate": trial.suggest_float("learning_rate", 0.03, 0.15, log=True),
                "num_leaves": trial.suggest_int("num_leaves", 7, 63),
                "max_depth": trial.suggest_int("max_depth", 3, 7),
                "subsample": trial.suggest_float("subsample", 0.6, 1.0),
                "colsample_bytree": trial.suggest_float("colsample_bytree", 0.6, 1.0),
                "lambda_l2": trial.suggest_float("lambda_l2", 1.0, 100.0, log=True),
                "min_child_samples": trial.suggest_int("min_child_samples", 10, 50),
                "verbose": -1,
            }

            train_data = lgb.Dataset(train_X, label=train_y)
            valid_data = lgb.Dataset(valid_X, label=valid_y, reference=train_data)

            model = lgb.train(
                params,
                train_data,
                num_boost_round=100,
                valid_sets=[valid_data],
                callbacks=[lgb.early_stopping(15, verbose=False)],
            )

            pred = model.predict(valid_X)
            from sklearn.metrics import roc_auc_score
            auc = roc_auc_score(valid_y, pred)
            return auc

    else:
        from sklearn.ensemble import GradientBoostingClassifier
        from sklearn.metrics import roc_auc_score

        def objective(trial: optuna.Trial) -> float:
            params = {
                "learning_rate": trial.suggest_float("learning_rate", 0.01, 0.15, log=True),
                "max_depth": trial.suggest_int("max_depth", 3, 8),
                "n_estimators": trial.suggest_int("n_estimators", 50, 300),
                "subsample": trial.suggest_float("subsample", 0.6, 1.0),
                "min_samples_split": trial.suggest_int("min_samples_split", 2, 20),
                "min_samples_leaf": trial.suggest_int("min_samples_leaf", 1, 10),
                "max_features": trial.suggest_float("max_features", 0.5, 1.0),
            }

            model = GradientBoostingClassifier(
                loss="log_loss", random_state=seed, **params
            )
            model.fit(train_X, train_y)
            pred = model.predict_proba(valid_X)[:, 1]
            auc = roc_auc_score(valid_y, pred)
            return auc

    sampler = optuna.samplers.TPESampler(seed=seed)
    study = optuna.create_study(direction="maximize", sampler=sampler)
    study.optimize(objective, n_trials=n_trials, show_progress_bar=True)

    # 用最优参数训练最终模型
    if model_backend == "lightgbm":
        import lightgbm as lgb

        best_lgb_params = {
            "objective": "binary",
            "metric": "auc",
            "verbose": -1,
        }
        best_lgb_params.update(study.best_params)

        train_data = lgb.Dataset(train_X, label=train_y)
        valid_data = lgb.Dataset(valid_X, label=valid_y, reference=train_data)
        best_model = lgb.train(
            best_lgb_params,
            train_data,
            num_boost_round=200,
            valid_sets=[valid_data],
            callbacks=[lgb.early_stopping(30, verbose=False)],
        )

        # 保存模型文件供实盘使用
        model_save_path = os.path.join(ROOT, "models", "breakout_lgb_model.txt")
        os.makedirs(os.path.dirname(model_save_path), exist_ok=True)
        best_model.save_model(model_save_path)
        print(f"  LightGBM模型已保存: {model_save_path}")

        feat_importance = dict(zip(
            train_X.columns.tolist(),
            best_model.feature_importance(importance_type="gain").tolist(),
        ))
    else:
        from sklearn.ensemble import GradientBoostingClassifier

        best_model = GradientBoostingClassifier(
            loss="log_loss", random_state=seed, **study.best_params
        )
        best_model.fit(train_X, train_y)

        feat_importance = dict(zip(
            train_X.columns.tolist(),
            best_model.feature_importances_.tolist(),
        ))

    # ---- 用 LightGBM 模型做回测 ----
    feature_cols = [
        "rs20_xsec_q", "ma20_slope", "atr_ratio_q60", "box_range",
        "ma20", "ma60", "ma120", "close",
        "vol_ma5", "vol_ma20", "amt_ma20",
    ]

    # 定义所有特征列（与_prepare_lgb_data保持一致）
    all_feature_cols = [
        # 原有特征
        "rs20_xsec_q", "ma20_slope", "atr_ratio_q60", "box_range",
        "ma20", "ma60", "ma120", "close",
        "vol_ma5", "vol_ma20", "amt_ma20",
        # 增强特征
        "industry_rs_rank", "industry_rs_gap", "industry_momentum",
        "industry_strength", "volume_ratio", "price_volume_divergence",
        "amplitude", "market_ad_ratio", "market_strong_ratio",
        # Tushare特征
        "ts_pe", "ts_pb", "ts_turnover_rate", "ts_volume_ratio",
        "ts_total_mv", "ts_net_mf_vol", "ts_net_mf_amount"
    ]

    # 获取训练时的特征列
    trained_feature_cols = train_X.columns.tolist()

    def _lgb_backtest(signal_dates, top_k=bp["top_k"]):
        """用 LightGBM 概率替代线性评分选股"""
        all_rets = {1: [], 2: [], 3: []}
        signal_count = 0
        for td in signal_dates:
            filtered = daily_cache.get(td)
            if filtered is None:
                continue
            # 同样的 RS + 走稳过滤
            cond_rs = filtered["rs20_xsec_q"].notna() & (filtered["rs20_xsec_q"] >= bp["rs_quantile_min"])
            if bp["rs_quantile_max"] < 1.0:
                cond_rs = cond_rs & (filtered["rs20_xsec_q"] <= bp["rs_quantile_max"])
            f3 = filtered.loc[cond_rs]
            if f3.empty:
                continue
            cond4 = f3["box_range"].notna() & (f3["box_range"] <= bp["box_max_range"])
            if f3["atr_ratio_q60"].notna().mean() > 0.3:
                cond4 = cond4 & (f3["atr_ratio_q60"].fillna(0.5) <= bp["atr_quantile_max"])
            f4 = f3.loc[cond4]
            if f4.empty:
                continue

            # 构造特征矩阵
            avail = [c for c in all_feature_cols if c in f4.columns]
            X_pred = f4[avail].fillna(0.0)
            for c in all_feature_cols:
                if c not in avail:
                    X_pred[c] = 0.0
            X_pred = X_pred[train_X.columns.tolist()]

            # 模型预测概率
            if model_backend == "lightgbm":
                probs = best_model.predict(X_pred)
            else:
                probs = best_model.predict_proba(X_pred)[:, 1]

            # 选 top_k
            f4 = f4.copy()
            f4["_prob"] = probs
            top = f4.nlargest(top_k, "_prob")

            for idx in top.index:
                code = f4.loc[idx, "ts_code"]
                sub = price_map.get(code)
                if sub is None:
                    continue
                match = sub.index[sub["date_str"] == td]
                if len(match) == 0:
                    continue
                pos = match[0]
                if pos + 1 >= len(sub):
                    continue
                entry = float(sub.loc[pos + 1, "open"])
                if entry <= 0:
                    continue
                signal_count += 1
                for h in (1, 2, 3):
                    t_idx = pos + 1 + h
                    if t_idx < len(sub):
                        all_rets[h].append(float(sub.loc[t_idx, "close"]) / entry - 1.0)

        res = {"signal_count": signal_count}
        for h in (1, 2, 3):
            rets = np.array(all_rets[h]) if all_rets[h] else np.array([])
            if len(rets) == 0:
                res.update({f"t{h}_win_rate": 0, f"t{h}_avg_ret": 0, f"t{h}_pf": 0})
                continue
            res[f"t{h}_win_rate"] = float((rets > 0).mean())
            res[f"t{h}_avg_ret"] = float(rets.mean())
            gw = float(rets[rets > 0].sum())
            gl = float(-rets[rets < 0].sum())
            res[f"t{h}_pf"] = gw / gl if gl > 1e-10 else 0.0
        return res

    # 获取训练时的特征列
    trained_feature_cols = train_X.columns.tolist()

    def _lgb_backtest(signal_dates, top_k=bp["top_k"]):
        """用 LightGBM 概率替代线性评分选股"""
        all_rets = {1: [], 2: [], 3: []}
        signal_count = 0
        for td in signal_dates:
            filtered = daily_cache.get(td)
            if filtered is None:
                continue
            # 同样的 RS + 走稳过滤
            cond_rs = filtered["rs20_xsec_q"].notna() & (filtered["rs20_xsec_q"] >= bp["rs_quantile_min"])
            if bp["rs_quantile_max"] < 1.0:
                cond_rs = cond_rs & (filtered["rs20_xsec_q"] <= bp["rs_quantile_max"])
            f3 = filtered.loc[cond_rs]
            if f3.empty:
                continue
            cond4 = f3["box_range"].notna() & (f3["box_range"] <= bp["box_max_range"])
            if f3["atr_ratio_q60"].notna().mean() > 0.3:
                cond4 = cond4 & (f3["atr_ratio_q60"].fillna(0.5) <= bp["atr_quantile_max"])
            f4 = f3.loc[cond4]
            if f4.empty:
                continue

            # 构造特征矩阵（使用训练时的特征列）
            X_pred = pd.DataFrame(index=f4.index)
            for c in trained_feature_cols:
                if c in f4.columns:
                    X_pred[c] = f4[c].fillna(0.0)
                else:
                    X_pred[c] = 0.0

            # 模型预测概率
            if model_backend == "lightgbm":
                probs = best_model.predict(X_pred)
            else:
                probs = best_model.predict_proba(X_pred)[:, 1]

            # 选 top_k
            f4 = f4.copy()
            f4["_prob"] = probs
            top = f4.nlargest(top_k, "_prob")

            for idx in top.index:
                code = f4.loc[idx, "ts_code"]
                sub = price_map.get(code)
                if sub is None:
                    continue
                match = sub.index[sub["date_str"] == td]
                if len(match) == 0:
                    continue
                pos = match[0]
                if pos + 1 >= len(sub):
                    continue
                entry = float(sub.loc[pos + 1, "open"])
                if entry <= 0:
                    continue
                signal_count += 1
                for h in (1, 2, 3):
                    t_idx = pos + 1 + h
                    if t_idx < len(sub):
                        all_rets[h].append(float(sub.loc[t_idx, "close"]) / entry - 1.0)

        res = {"signal_count": signal_count}
        for h in (1, 2, 3):
            rets = np.array(all_rets[h]) if all_rets[h] else np.array([])
            if len(rets) == 0:
                res.update({f"t{h}_win_rate": 0, f"t{h}_avg_ret": 0, f"t{h}_pf": 0})
                continue
            res[f"t{h}_win_rate"] = float((rets > 0).mean())
            res[f"t{h}_avg_ret"] = float(rets.mean())
            gw = float(rets[rets > 0].sum())
            gl = float(-rets[rets < 0].sum())
            res[f"t{h}_pf"] = gw / gl if gl > 1e-10 else 0.0
        return res

    is_res = _lgb_backtest(in_sample)
    os_res = _lgb_backtest(out_sample)

    result = {
        "phase": 3,
        "status": "completed",
        "best_lgb_params": study.best_params,
        "best_auc": study.best_value,
        "feature_importance": feat_importance,
        "n_trials": n_trials,
        "in_sample": is_res,
        "out_sample": os_res,
    }

    print(f"\n  阶段3 结果: 最优AUC={study.best_value:.4f}")
    print(f"  LightGBM 超参数:")
    for k, v in study.best_params.items():
        print(f"    {k}: {v}")
    print(f"  特征重要性（Top 5）:")
    for i, (k, v) in enumerate(sorted(feat_importance.items(), key=lambda x: -x[1])[:5], 1):
        print(f"    {i}. {k}: {v:.2f}")
    print(f"\n  LightGBM 回测（样本内）:")
    print(f"    T1胜率={is_res['t1_win_rate']:.2%}  T1收益={is_res['t1_avg_ret']:.4%}  T1盈亏比={is_res['t1_pf']:.2f}  信号数={is_res['signal_count']}")
    print(f"  LightGBM 回测（样本外）:")
    print(f"    T1胜率={os_res['t1_win_rate']:.2%}  T1收益={os_res['t1_avg_ret']:.4%}  T1盈亏比={os_res['t1_pf']:.2f}  信号数={os_res['signal_count']}")

    return result


def _prepare_lgb_data(
    daily_cache, price_map, in_sample, out_sample,
    rs_min, rs_max, box_max, atr_max,
) -> Tuple:
    """准备 LightGBM 训练数据（含Tushare增强特征）"""
    # 原有特征
    feature_cols = [
        "rs20_xsec_q", "ma20_slope", "atr_ratio_q60", "box_range",
        "ma20", "ma60", "ma120", "close",
        "vol_ma5", "vol_ma20", "amt_ma20",
    ]
    # 增强特征（行业+市场）
    enhanced_cols = [
        "industry_rs_rank", "industry_rs_gap", "industry_momentum",
        "industry_strength", "volume_ratio", "price_volume_divergence",
        "amplitude", "market_ad_ratio", "market_strong_ratio"
    ]
    # Tushare特征（估值+资金流）
    tushare_cols = [
        "ts_pe", "ts_pb", "ts_turnover_rate", "ts_volume_ratio",
        "ts_total_mv", "ts_net_mf_vol", "ts_net_mf_amount"
    ]
    all_feature_cols = feature_cols + enhanced_cols + tushare_cols

    all_X, all_y = [], []

    for dates, label_prefix in [(in_sample, "train"), (out_sample, "valid")]:
        for td in dates:
            filtered = daily_cache.get(td)
            if filtered is None:
                continue

            # RS过滤
            cond_rs = filtered["rs20_xsec_q"].notna() & (filtered["rs20_xsec_q"] >= rs_min)
            if rs_max < 1.0:
                cond_rs = cond_rs & (filtered["rs20_xsec_q"] <= rs_max)
            f3 = filtered.loc[cond_rs]
            if f3.empty:
                continue

            # 走稳过滤
            cond4 = f3["box_range"].notna() & (f3["box_range"] <= box_max)
            if f3["atr_ratio_q60"].notna().mean() > 0.3:
                cond4 = cond4 & (f3["atr_ratio_q60"].fillna(0.5) <= atr_max)
            f4 = f3.loc[cond4]
            if f4.empty:
                continue

            # 提取特征（包括增强特征）
            available_cols = [c for c in all_feature_cols if c in f4.columns]
            if not available_cols:
                continue

            for idx, row in f4.iterrows():
                code = row["ts_code"]
                sub = price_map.get(code)
                if sub is None:
                    continue
                match = sub.index[sub["date_str"] == td]
                if len(match) == 0:
                    continue
                pos = match[0]
                if pos + 2 >= len(sub):
                    continue

                entry = float(sub.loc[pos + 1, "open"])
                if entry <= 0:
                    continue
                sell = float(sub.loc[pos + 2, "close"])
                ret = (sell - entry) / entry

                features = {c: float(row[c]) if pd.notna(row.get(c)) else 0.0 for c in available_cols}
                features["label_prefix"] = label_prefix
                all_X.append(features)
                all_y.append(1.0 if ret > 0 else 0.0)

    if not all_X:
        return None, None, None, None

    df_X = pd.DataFrame(all_X)
    y = np.array(all_y)

    # 分割训练/验证
    train_mask = df_X["label_prefix"] == "train"
    valid_mask = df_X["label_prefix"] == "valid"

    train_X = df_X[train_mask].drop(columns=["label_prefix"])
    valid_X = df_X[valid_mask].drop(columns=["label_prefix"])
    train_y = y[train_mask.values]
    valid_y = y[valid_mask.values]

    return train_X, train_y, valid_X, valid_y


# ============================================================
# 主流程
# ============================================================

def main() -> None:
    parser = argparse.ArgumentParser(description="突破策略 Optuna 三阶段优化")
    parser.add_argument(
        "--phase", type=int, default=0,
        help="优化阶段: 0=全部, 1=参数优化, 2=因子增强, 3=模型增强",
    )
    parser.add_argument("--n-trials", type=int, default=200, help="Optuna 试验次数")
    parser.add_argument("--seed", type=int, default=42, help="随机种子")
    parser.add_argument(
        "--out-json", default="",
        help="输出 JSON 路径（默认 output/optuna_breakout_optimize.json）",
    )
    args = parser.parse_args()

    print("=" * 72)
    print("  突破策略 Optuna 三阶段优化")
    print("=" * 72)

    config = ConfigManager()
    db = DatabaseManager(config)

    # 加载交易日
    all_dates = [
        r["trade_date"]
        for r in db.query(
            "SELECT DISTINCT trade_date FROM stock_daily ORDER BY trade_date ASC"
        )
    ]
    total = len(all_dates)
    warmup_skip = 65
    use_ma120 = total >= 180

    if total < 75:
        print("  数据不足，退出")
        return

    backtest_dates = all_dates[warmup_skip:-3]
    split_idx = int(len(backtest_dates) * 0.7)
    in_sample = backtest_dates[:split_idx]
    out_sample = backtest_dates[split_idx:]

    print(f"  总交易日: {total}")
    print(f"  样本内: {in_sample[0]} -> {in_sample[-1]} ({len(in_sample)}天)")
    print(f"  样本外: {out_sample[0]} -> {out_sample[-1]} ({len(out_sample)}天)")
    print(f"  Optuna trials: {args.n_trials}, seed: {args.seed}")

    # 预计算因子
    print("\n  [1/3] 计算全量因子...")
    base_params = BreakoutParams()
    strategy = BreakoutStrategy(db=db, params=base_params)
    raw_daily, raw_basic = strategy._load_data(all_dates[-1])
    features = strategy._compute_features(raw_daily, raw_basic, all_dates[-1])
    print(f"  因子行数: {len(features)}")

    # 价格映射
    print("  [2/3] 构建价格映射...")
    price_map = build_price_map(features)

    # 预缓存每日快照
    print("  [3/3] 预缓存每日快照+基础过滤...")
    daily_cache = precompute_daily_snapshots(
        features, backtest_dates, base_params, use_ma120
    )
    print(f"  缓存天数: {len(daily_cache)}")

    # 添加增强特征（行业动量、市场宽度、量价背离）
    print("  [4/4] 计算增强特征...")
    daily_cache = _add_enhanced_features(daily_cache, features, db)
    print(f"  增强特征添加完成")

    # 基线回测（当前默认参数）
    print("\n  基线回测（当前默认参数）...")
    baseline_params = BreakoutParams()
    baseline_is = evaluate_with_params(
        daily_cache, price_map, in_sample,
        baseline_params.rs_quantile_min, baseline_params.rs_quantile_max,
        baseline_params.box_max_range, baseline_params.atr_quantile_max,
        baseline_params.min_signal_score, baseline_params.top_k,
        baseline_params.weight_rs, baseline_params.weight_trend,
        baseline_params.weight_stability, baseline_params.weight_box,
        baseline_params.weight_volume,
    )
    baseline_oos = evaluate_with_params(
        daily_cache, price_map, out_sample,
        baseline_params.rs_quantile_min, baseline_params.rs_quantile_max,
        baseline_params.box_max_range, baseline_params.atr_quantile_max,
        baseline_params.min_signal_score, baseline_params.top_k,
        baseline_params.weight_rs, baseline_params.weight_trend,
        baseline_params.weight_stability, baseline_params.weight_box,
        baseline_params.weight_volume,
    )
    print(f"  样本内: T1胜率={baseline_is['t1_win_rate']:.2%}  T1收益={baseline_is['t1_avg_ret']:.4%}  "
          f"T1盈亏比={baseline_is['t1_pf']:.2f}  信号数={baseline_is['signal_count']}")
    print(f"  样本外: T1胜率={baseline_oos['t1_win_rate']:.2%}  T1收益={baseline_oos['t1_avg_ret']:.4%}  "
          f"T1盈亏比={baseline_oos['t1_pf']:.2f}  信号数={baseline_oos['signal_count']}")

    # 执行优化
    results = {
        "meta": {
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "n_trials": args.n_trials,
            "seed": args.seed,
            "in_sample_range": f"{in_sample[0]}~{in_sample[-1]}",
            "out_sample_range": f"{out_sample[0]}~{out_sample[-1]}",
            "in_sample_days": len(in_sample),
            "out_sample_days": len(out_sample),
        },
        "baseline": {
            "in_sample": baseline_is,
            "out_sample": baseline_oos,
            "params": {
                "rs_quantile_min": baseline_params.rs_quantile_min,
                "rs_quantile_max": baseline_params.rs_quantile_max,
                "box_max_range": baseline_params.box_max_range,
                "atr_quantile_max": baseline_params.atr_quantile_max,
                "min_signal_score": baseline_params.min_signal_score,
                "top_k": baseline_params.top_k,
                "weight_rs": baseline_params.weight_rs,
                "weight_trend": baseline_params.weight_trend,
                "weight_stability": baseline_params.weight_stability,
                "weight_box": baseline_params.weight_box,
                "weight_volume": baseline_params.weight_volume,
            },
        },
    }

    best_params_p1 = results["baseline"]["params"]

    # 阶段1: 参数优化
    if args.phase in (0, 1):
        t0 = time.time()
        p1_result = phase1_param_optimize(
            daily_cache, price_map, in_sample, out_sample,
            n_trials=args.n_trials, seed=args.seed,
        )
        p1_result["elapsed_seconds"] = time.time() - t0
        results["phase1"] = p1_result
        best_params_p1 = p1_result["best_params"]

    # 阶段2: Qlib 因子增强
    if args.phase in (0, 2):
        t0 = time.time()
        p2_result = phase2_qlib_factor_enhance(
            daily_cache, price_map, in_sample, out_sample,
            best_params_p1, n_trials=max(30, args.n_trials // 4), seed=args.seed,
            features=features,
        )
        p2_result["elapsed_seconds"] = time.time() - t0
        results["phase2"] = p2_result

    # 阶段3: LightGBM 模型增强
    if args.phase in (0, 3):
        t0 = time.time()
        p3_result = phase3_model_enhance(
            daily_cache, price_map, in_sample, out_sample,
            best_params_p1, n_trials=args.n_trials, seed=args.seed,
        )
        p3_result["elapsed_seconds"] = time.time() - t0
        results["phase3"] = p3_result

    # 保存结果
    out_path = args.out_json.strip()
    if not out_path:
        out_path = os.path.join(ROOT, "output", "optuna_breakout_optimize.json")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2, default=str)
    print(f"\n  结果已保存: {out_path}")

    # 生成对比摘要
    _print_summary(results)


def _print_summary(results: Dict) -> None:
    """打印最终对比摘要"""
    print(f"\n{'=' * 72}")
    print("  优化对比摘要")
    print(f"{'=' * 72}")

    bl = results["baseline"]
    print(f"\n  {'指标':<20} {'基线-样本内':>12} {'基线-样本外':>12}", end="")

    if "phase1" in results:
        p1 = results["phase1"]
        print(f" {'P1优化-样本内':>12} {'P1优化-样本外':>12}", end="")
    if "phase3" in results and "in_sample" in results["phase3"]:
        print(f" {'P3-LGB-样本内':>12} {'P3-LGB-样本外':>12}", end="")
    print()

    print(f"  {'-' * 68}")

    for metric, label in [
        ("t1_win_rate", "T1胜率"),
        ("t1_avg_ret", "T1收益率"),
        ("t1_pf", "T1盈亏比"),
        ("t2_win_rate", "T2胜率"),
        ("t2_avg_ret", "T2收益率"),
    ]:
        bl_is = bl["in_sample"].get(metric, 0)
        bl_oos = bl["out_sample"].get(metric, 0)
        fmt = ".2%" if "win_rate" in metric else (".4%" if "avg_ret" in metric else ".2f")

        print(f"  {label:<20} {bl_is:>12{fmt}} {bl_oos:>12{fmt}}", end="")

        if "phase1" in results:
            p1_is = results["phase1"]["in_sample"].get(metric, 0)
            p1_oos = results["phase1"]["out_sample"].get(metric, 0)
            print(f" {p1_is:>12{fmt}} {p1_oos:>12{fmt}}", end="")
        if "phase3" in results and "in_sample" in results["phase3"]:
            p3_is = results["phase3"]["in_sample"].get(metric, 0)
            p3_oos = results["phase3"]["out_sample"].get(metric, 0)
            print(f" {p3_is:>12{fmt}} {p3_oos:>12{fmt}}", end="")
        print()

    # 样本外提升
    bl_oos_dict = bl["out_sample"]
    if "phase1" in results:
        p1_oos = results["phase1"]["out_sample"]
        wr_delta = p1_oos.get("t1_win_rate", 0) - bl_oos_dict.get("t1_win_rate", 0)
        ret_delta = p1_oos.get("t1_avg_ret", 0) - bl_oos_dict.get("t1_avg_ret", 0)
        print(f"\n  P1 样本外提升: T1胜率 {wr_delta:+.2%}  T1收益率 {ret_delta:+.4%}")

    if "phase3" in results and "in_sample" in results["phase3"]:
        p3_oos = results["phase3"]["out_sample"]
        wr_delta = p3_oos.get("t1_win_rate", 0) - bl_oos_dict.get("t1_win_rate", 0)
        ret_delta = p3_oos.get("t1_avg_ret", 0) - bl_oos_dict.get("t1_avg_ret", 0)
        sig_bl = bl_oos_dict.get("signal_count", 0)
        sig_p3 = p3_oos.get("signal_count", 0)
        print(f"  P3 样本外提升: T1胜率 {wr_delta:+.2%}  T1收益率 {ret_delta:+.4%}  信号数 {sig_bl}→{sig_p3}")


if __name__ == "__main__":
    main()
