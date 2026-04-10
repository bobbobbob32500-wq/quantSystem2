# -*- coding: utf-8 -*-
"""
增强策略因子归因 + 去重诊断

目标：
1. 基于真实 factor_values + stock_daily 数据，计算多周期 IC / RankIC
2. 输出因子相关性矩阵，识别高相关（重复）因子对
3. 输出分层收益（Top-Bottom）检验，判断因子单调性
4. 结合当前配置权重，给出“去重后”的建议权重
"""

from __future__ import annotations

import argparse
import json
import math
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.core.config import ConfigManager


BASE_FACTORS = [
    "trend_score",
    "momentum_score",
    "volume_score",
    "fundamental_score",
    "pullback_score",
    "quality_score",
]

AUX_FACTORS = [
    "short_cycle_score",
    "tradeability_score",
]

ALL_FACTORS = BASE_FACTORS + AUX_FACTORS


def _safe_pearson(x: pd.Series, y: pd.Series, min_samples: int) -> float:
    pair = pd.DataFrame({"x": x, "y": y}).dropna()
    if len(pair) < min_samples:
        return math.nan
    corr = pair["x"].corr(pair["y"], method="pearson")
    if pd.isna(corr):
        return math.nan
    return float(corr)


def _safe_spearman(x: pd.Series, y: pd.Series, min_samples: int) -> float:
    pair = pd.DataFrame({"x": x, "y": y}).dropna()
    if len(pair) < min_samples:
        return math.nan
    corr, _ = spearmanr(pair["x"], pair["y"])
    if pd.isna(corr):
        return math.nan
    return float(corr)


def _records(df: pd.DataFrame) -> List[Dict]:
    if df is None or df.empty:
        return []
    return json.loads(df.to_json(orient="records", force_ascii=False))


def _normalize_weights(weights: Dict[str, float]) -> Dict[str, float]:
    clean = {k: max(0.0, float(v)) for k, v in weights.items()}
    s = float(sum(clean.values()))
    if s <= 1e-12:
        n = len(clean) or 1
        return {k: 1.0 / n for k in clean}
    return {k: float(v / s) for k, v in clean.items()}


def load_trade_dates(conn: sqlite3.Connection) -> List[str]:
    sql = "SELECT DISTINCT trade_date FROM stock_daily ORDER BY trade_date"
    return [str(row[0]) for row in conn.execute(sql).fetchall()]


def choose_signal_dates(trade_dates: List[str], signal_days: int, horizon_max: int) -> List[str]:
    if len(trade_dates) <= horizon_max:
        return []
    max_idx = len(trade_dates) - 1 - horizon_max
    start_idx = max(0, max_idx - signal_days + 1)
    return trade_dates[start_idx : max_idx + 1]


def load_factor_panel(conn: sqlite3.Connection, signal_dates: List[str]) -> pd.DataFrame:
    if not signal_dates:
        return pd.DataFrame()

    date_placeholder = ",".join(["?"] * len(signal_dates))
    factor_placeholder = ",".join(["?"] * len(ALL_FACTORS))
    sql = f"""
        SELECT trade_date, ts_code, factor_name, factor_value
        FROM factor_values
        WHERE trade_date IN ({date_placeholder})
          AND factor_name IN ({factor_placeholder})
    """
    params = list(signal_dates) + ALL_FACTORS
    raw = pd.read_sql(sql, conn, params=params)
    if raw.empty:
        return pd.DataFrame()

    panel = (
        raw.pivot_table(
            index=["trade_date", "ts_code"],
            columns="factor_name",
            values="factor_value",
            aggfunc="last",
        )
        .reset_index()
        .copy()
    )
    panel = panel.dropna(subset=ALL_FACTORS)
    if panel.empty:
        return panel

    industry_df = pd.read_sql("SELECT ts_code, industry FROM stock_basic", conn)
    panel = panel.merge(industry_df, on="ts_code", how="left")
    panel["industry"] = panel["industry"].fillna("未知")
    return panel


def attach_forward_returns(
    conn: sqlite3.Connection,
    panel: pd.DataFrame,
    trade_dates: List[str],
    horizons: List[int],
) -> pd.DataFrame:
    if panel.empty:
        return panel
    if not horizons:
        return pd.DataFrame()

    date_to_idx = {d: i for i, d in enumerate(trade_dates)}

    def _nth(d: str, n: int) -> str | None:
        idx = date_to_idx.get(d)
        if idx is None:
            return None
        target = idx + n
        if 0 <= target < len(trade_dates):
            return trade_dates[target]
        return None

    x = panel.copy()
    x["buy_date"] = x["trade_date"].map(lambda d: _nth(str(d), 1))
    sell_cols = []
    for h in horizons:
        col = f"sell_{h}_date"
        x[col] = x["trade_date"].map(lambda d, hh=h: _nth(str(d), hh))
        sell_cols.append(col)

    x = x.dropna(subset=["buy_date"] + sell_cols)
    if x.empty:
        return x

    all_dates = set(x["trade_date"].astype(str).tolist())
    all_dates.update(x["buy_date"].astype(str).tolist())
    for col in sell_cols:
        all_dates.update(x[col].astype(str).tolist())
    min_date = min(all_dates)
    max_date = max(all_dates)

    prices = pd.read_sql(
        """
        SELECT ts_code, trade_date, open, close
        FROM stock_daily
        WHERE trade_date >= ? AND trade_date <= ?
        """,
        conn,
        params=(min_date, max_date),
    )
    if prices.empty:
        return pd.DataFrame()

    prices["trade_date"] = prices["trade_date"].astype(str)
    symbols = set(x["ts_code"].astype(str).tolist())
    dates = set(str(d) for d in all_dates)
    prices = prices[prices["ts_code"].isin(symbols) & prices["trade_date"].isin(dates)].copy()
    if prices.empty:
        return pd.DataFrame()

    prices["open"] = pd.to_numeric(prices["open"], errors="coerce")
    prices["close"] = pd.to_numeric(prices["close"], errors="coerce")
    prices = prices.dropna(subset=["open", "close"])
    if prices.empty:
        return pd.DataFrame()

    close_t = prices.rename(columns={"trade_date": "trade_date", "close": "close_t"})[
        ["ts_code", "trade_date", "close_t"]
    ]
    buy_open = prices.rename(columns={"trade_date": "buy_date", "open": "buy_open"})[
        ["ts_code", "buy_date", "buy_open"]
    ]
    x = x.merge(close_t, on=["ts_code", "trade_date"], how="left")
    x = x.merge(buy_open, on=["ts_code", "buy_date"], how="left")

    for h in horizons:
        sell_col = f"sell_{h}_date"
        close_col = f"sell_{h}_close"
        sell_df = prices.rename(columns={"trade_date": sell_col, "close": close_col})[
            ["ts_code", sell_col, close_col]
        ]
        x = x.merge(sell_df, on=["ts_code", sell_col], how="left")
        x[f"ret_{h}_cc"] = x[close_col] / x["close_t"] - 1.0
        x[f"ret_{h}_oc"] = x[close_col] / x["buy_open"] - 1.0

    needed = ["close_t", "buy_open"] + [f"sell_{h}_close" for h in horizons]
    x = x.dropna(subset=needed)
    return x


def calc_daily_ic_summary(
    dataset: pd.DataFrame,
    factors: Iterable[str],
    target: str,
    min_cross_section: int,
) -> pd.DataFrame:
    rows: List[Dict] = []
    groups = [g for _, g in dataset.groupby("trade_date", sort=True)]

    for factor in factors:
        rank_ics: List[float] = []
        pearson_ics: List[float] = []
        samples: List[int] = []

        for g in groups:
            pair = g[[factor, target]].dropna()
            if len(pair) < min_cross_section:
                continue
            rank_ic = _safe_spearman(pair[factor], pair[target], min_cross_section)
            pearson_ic = _safe_pearson(pair[factor], pair[target], min_cross_section)
            if pd.isna(rank_ic) or pd.isna(pearson_ic):
                continue
            rank_ics.append(float(rank_ic))
            pearson_ics.append(float(pearson_ic))
            samples.append(int(len(pair)))

        if not rank_ics:
            continue

        s_rank = pd.Series(rank_ics, dtype=float)
        s_pearson = pd.Series(pearson_ics, dtype=float)
        rank_std = float(s_rank.std(ddof=0))
        rows.append(
            {
                "factor": factor,
                "target": target,
                "rank_ic_mean": float(s_rank.mean()),
                "rank_ic_std": rank_std,
                "rank_ic_ir": float(s_rank.mean() / rank_std) if rank_std > 1e-12 else 0.0,
                "rank_ic_positive_ratio": float((s_rank > 0).mean()),
                "pearson_ic_mean": float(s_pearson.mean()),
                "pearson_ic_std": float(s_pearson.std(ddof=0)),
                "sample_days": int(len(s_rank)),
                "avg_cross_section": float(np.mean(samples)) if samples else 0.0,
            }
        )

    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).sort_values("rank_ic_mean", ascending=False).reset_index(drop=True)


def calc_factor_correlation(dataset: pd.DataFrame, factors: List[str]) -> pd.DataFrame:
    part = dataset[factors].copy()
    part = part.dropna()
    if part.empty:
        return pd.DataFrame()
    return part.corr(method="spearman")


def identify_redundant_pairs(corr_matrix: pd.DataFrame, threshold: float) -> pd.DataFrame:
    if corr_matrix.empty:
        return pd.DataFrame()

    rows: List[Dict] = []
    cols = list(corr_matrix.columns)
    for i in range(len(cols)):
        for j in range(i + 1, len(cols)):
            f1 = cols[i]
            f2 = cols[j]
            corr = float(corr_matrix.iloc[i, j])
            if abs(corr) >= threshold:
                rows.append(
                    {
                        "factor_a": f1,
                        "factor_b": f2,
                        "corr": corr,
                        "abs_corr": abs(corr),
                    }
                )

    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).sort_values("abs_corr", ascending=False).reset_index(drop=True)


def calc_layer_profile(
    dataset: pd.DataFrame,
    factor: str,
    target: str,
    layers: int,
    min_samples: int,
) -> Dict:
    rows: List[Dict] = []
    tb_daily: List[float] = []
    monotonic_daily: List[float] = []

    for date, g in dataset.groupby("trade_date", sort=True):
        pair = g[[factor, target]].dropna()
        if len(pair) < min_samples:
            continue

        try:
            pair = pair.copy()
            pair["layer"] = pd.qcut(pair[factor], layers, labels=False, duplicates="drop")
        except Exception:
            continue

        if pair["layer"].nunique() < 2:
            continue

        pair["layer"] = pair["layer"].astype(int)
        grouped = pair.groupby("layer")[target].agg(["mean", "count"]).sort_index()
        if grouped.empty or len(grouped) < 2:
            continue

        for layer_idx, row in grouped.iterrows():
            rows.append(
                {
                    "trade_date": str(date),
                    "layer": int(layer_idx),
                    "mean_return": float(row["mean"]),
                    "count": int(row["count"]),
                }
            )

        tb_daily.append(float(grouped["mean"].iloc[-1] - grouped["mean"].iloc[0]))
        mono = _safe_spearman(
            pd.Series(grouped.index.to_numpy(dtype=float)),
            grouped["mean"].reset_index(drop=True),
            min_samples=2,
        )
        if not pd.isna(mono):
            monotonic_daily.append(float(mono))

    if not rows:
        return {
            "factor": factor,
            "target": target,
            "sample_days": 0,
            "top_bottom_mean": math.nan,
            "top_bottom_positive_ratio": math.nan,
            "daily_monotonic_mean": math.nan,
            "layer_table": pd.DataFrame(),
        }

    detail = pd.DataFrame(rows)
    layer_table = (
        detail.groupby("layer")
        .agg(
            mean_return=("mean_return", "mean"),
            avg_count=("count", "mean"),
            sample_days=("trade_date", "nunique"),
        )
        .reset_index()
        .sort_values("layer")
        .reset_index(drop=True)
    )
    layer_table["layer"] = layer_table["layer"].apply(lambda x: f"Q{int(x) + 1}")

    tb_series = pd.Series(tb_daily, dtype=float)
    mono_series = pd.Series(monotonic_daily, dtype=float) if monotonic_daily else pd.Series([], dtype=float)
    return {
        "factor": factor,
        "target": target,
        "sample_days": int(detail["trade_date"].nunique()),
        "top_bottom_mean": float(tb_series.mean()) if not tb_series.empty else math.nan,
        "top_bottom_positive_ratio": float((tb_series > 0).mean()) if not tb_series.empty else math.nan,
        "daily_monotonic_mean": float(mono_series.mean()) if not mono_series.empty else math.nan,
        "layer_table": layer_table,
    }


def load_current_base_weights(config: ConfigManager) -> Dict[str, float]:
    profile_name = str(config.get("stock_selection.enhanced_weight_profile", "active")).strip().lower() or "active"
    profiles = config.get("stock_selection.enhanced_weight_profiles", {}) or {}
    profile = profiles.get(profile_name) or profiles.get("active") or {}

    def _get_weight(key: str, flat_key: str, default: float) -> float:
        if isinstance(profile, dict):
            value = profile.get(key, profile.get(flat_key))
            if value is not None:
                return float(value)
        return float(config.get(f"stock_selection.{flat_key}", default))

    raw = {
        "trend_score": _get_weight("trend", "trend_factor_weight", 0.35),
        "momentum_score": _get_weight("momentum", "momentum_factor_weight", 0.30),
        "volume_score": _get_weight("volume", "volume_factor_weight", 0.05),
        "fundamental_score": _get_weight("fundamental", "fundamental_factor_weight", 0.05),
        "pullback_score": _get_weight("pullback", "pullback_factor_weight", 0.15),
        "quality_score": _get_weight("quality", "quality_factor_weight", 0.10),
    }
    return _normalize_weights(raw)


def build_weight_suggestions(
    current_weights: Dict[str, float],
    ic_primary: pd.DataFrame,
    redundant_pairs: pd.DataFrame,
    corr_threshold: float,
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    ic_map = {
        str(row["factor"]): float(row["rank_ic_mean"])
        for row in _records(ic_primary[["factor", "rank_ic_mean"]])
    }

    strength = {f: max(0.0, ic_map.get(f, 0.0)) for f in BASE_FACTORS}
    if sum(strength.values()) <= 1e-12:
        strength = {f: abs(ic_map.get(f, 0.0)) for f in BASE_FACTORS}
    if sum(strength.values()) <= 1e-12:
        strength = current_weights.copy()

    penalty_map = {f: 1.0 for f in BASE_FACTORS}
    pair_actions: List[Dict] = []
    if not redundant_pairs.empty:
        for _, row in redundant_pairs.iterrows():
            a = str(row["factor_a"])
            b = str(row["factor_b"])
            corr = float(row["corr"])

            sa = abs(float(ic_map.get(a, 0.0)))
            sb = abs(float(ic_map.get(b, 0.0)))
            if sa >= sb:
                keep, reduce = a, b
            else:
                keep, reduce = b, a

            gap = max(0.0, abs(corr) - corr_threshold)
            penalty_factor = max(0.35, 1.0 - gap * 1.5)

            if reduce in BASE_FACTORS:
                penalty_map[reduce] = min(penalty_map[reduce], penalty_factor)

            if a in BASE_FACTORS and b in BASE_FACTORS:
                action_type = "base_base"
            elif (a in BASE_FACTORS) ^ (b in BASE_FACTORS):
                action_type = "base_aux"
            else:
                action_type = "aux_aux"

            pair_actions.append(
                {
                    "factor_a": a,
                    "factor_b": b,
                    "corr": corr,
                    "action_type": action_type,
                    "keep_factor": keep,
                    "reduce_factor": reduce,
                    "keep_rank_ic": float(ic_map.get(keep, 0.0)),
                    "reduce_rank_ic": float(ic_map.get(reduce, 0.0)),
                    "penalty_factor": float(penalty_factor),
                }
            )

    adjusted_strength = {
        f: max(1e-9, float(strength.get(f, 0.0)) * float(penalty_map.get(f, 1.0)))
        for f in BASE_FACTORS
    }
    dedup_weights = _normalize_weights(adjusted_strength)

    # 适度保守：70% 使用归因结果 + 30% 保留当前配置
    mixed_weights = {
        f: dedup_weights[f] * 0.70 + current_weights.get(f, 0.0) * 0.30
        for f in BASE_FACTORS
    }
    mixed_weights = _normalize_weights(mixed_weights)

    rows = []
    for f in BASE_FACTORS:
        current = float(current_weights.get(f, 0.0))
        rec = float(mixed_weights.get(f, 0.0))
        rows.append(
            {
                "factor": f,
                "current_weight": current,
                "recommended_weight": rec,
                "delta": rec - current,
                "rank_ic_mean_primary": float(ic_map.get(f, 0.0)),
                "redundancy_penalty": float(penalty_map.get(f, 1.0)),
            }
        )

    weight_df = pd.DataFrame(rows).sort_values("recommended_weight", ascending=False).reset_index(drop=True)
    action_df = (
        pd.DataFrame(pair_actions)
        .sort_values("corr", key=lambda s: s.abs(), ascending=False)
        .reset_index(drop=True)
        if pair_actions
        else pd.DataFrame()
    )
    return weight_df, action_df


def build_aux_param_suggestions(
    config: ConfigManager,
    ic_primary: pd.DataFrame,
    action_df: pd.DataFrame,
) -> pd.DataFrame:
    ic_map = {
        str(row["factor"]): float(row["rank_ic_mean"])
        for row in _records(ic_primary[["factor", "rank_ic_mean"]])
    }

    current_short_cycle = float(config.get("stock_selection.short_cycle_score_weight", 0.16))
    current_tradeability = float(config.get("stock_selection.tradeability_penalty_weight", 0.18))

    aux_penalty = {
        "short_cycle_score": 1.0,
        "tradeability_score": 1.0,
    }
    if not action_df.empty:
        for _, row in action_df.iterrows():
            reduce_factor = str(row["reduce_factor"])
            if reduce_factor in aux_penalty:
                aux_penalty[reduce_factor] = min(
                    aux_penalty[reduce_factor],
                    float(row["penalty_factor"]),
                )

    # short_cycle 与趋势/动量常相关，冲突时优先下调短周期修正项
    rec_short_cycle = current_short_cycle * aux_penalty["short_cycle_score"]
    if float(ic_map.get("short_cycle_score", 0.0)) <= 0:
        rec_short_cycle *= 0.9
    rec_short_cycle = max(0.05, rec_short_cycle)

    # tradeability 是惩罚项：若自身为负相关，适当降低惩罚强度；否则维持
    rec_tradeability = current_tradeability * aux_penalty["tradeability_score"]
    if float(ic_map.get("tradeability_score", 0.0)) < 0:
        rec_tradeability *= 0.9
    rec_tradeability = max(0.05, rec_tradeability)

    rows = [
        {
            "parameter": "stock_selection.short_cycle_score_weight",
            "factor_proxy": "short_cycle_score",
            "current_value": current_short_cycle,
            "recommended_value": rec_short_cycle,
            "delta": rec_short_cycle - current_short_cycle,
            "rank_ic_mean_primary": float(ic_map.get("short_cycle_score", 0.0)),
            "note": "与主因子高相关时降低重复加分风险",
        },
        {
            "parameter": "stock_selection.tradeability_penalty_weight",
            "factor_proxy": "tradeability_score",
            "current_value": current_tradeability,
            "recommended_value": rec_tradeability,
            "delta": rec_tradeability - current_tradeability,
            "rank_ic_mean_primary": float(ic_map.get("tradeability_score", 0.0)),
            "note": "保持惩罚力度与交易性因子有效性一致",
        },
    ]
    return pd.DataFrame(rows)


def _calc_sharpe(returns: pd.Series) -> float:
    if returns.empty:
        return 0.0
    std = float(returns.std(ddof=0))
    if std <= 1e-12:
        return 0.0
    return float(returns.mean() / std)


def _score_metrics(mean_ret_short: float, mean_ret_main: float, win_rate_main: float) -> float:
    return float(mean_ret_main * 0.7 + mean_ret_short * 0.3 + (win_rate_main - 0.5) * 0.02)


def score_candidates(
    df: pd.DataFrame,
    weights: Dict[str, float],
    short_cycle_weight: float,
    tradeability_penalty_weight: float,
) -> pd.Series:
    base = sum(df[f] * weights.get(f, 0.0) for f in BASE_FACTORS)
    short_adj = (df["short_cycle_score"] - 50.0) * short_cycle_weight
    risk_penalty = np.maximum(0.0, (65.0 - df["tradeability_score"]) * tradeability_penalty_weight)
    total = base + short_adj - risk_penalty
    return total.clip(0.0, 100.0)


def pick_top_with_industry_limit(day_df: pd.DataFrame, top_n: int, max_per_industry: int) -> pd.DataFrame:
    selected_rows = []
    industry_count: Dict[str, int] = {}
    for row in day_df.sort_values("score", ascending=False).itertuples(index=False):
        ind = getattr(row, "industry", "未知")
        if industry_count.get(ind, 0) >= max_per_industry:
            continue
        selected_rows.append(row)
        industry_count[ind] = industry_count.get(ind, 0) + 1
        if len(selected_rows) >= top_n:
            break
    if not selected_rows:
        return pd.DataFrame(columns=day_df.columns)
    return pd.DataFrame(selected_rows, columns=day_df.columns)


def run_weight_profile_backtest(
    dataset: pd.DataFrame,
    weights: Dict[str, float],
    short_cycle_weight: float,
    tradeability_penalty_weight: float,
    top_n: int,
    max_per_industry: int,
    eval_dates: List[str],
    short_horizon: int,
    main_horizon: int,
) -> Dict[str, float]:
    short_col = f"ret_{short_horizon}_oc"
    main_col = f"ret_{main_horizon}_oc"
    if short_col not in dataset.columns or main_col not in dataset.columns:
        return {
            "sample_days": 0,
            "mean_ret_short": 0.0,
            "mean_ret_main": 0.0,
            "win_rate_short": 0.0,
            "win_rate_main": 0.0,
            "sharpe_short": 0.0,
            "sharpe_main": 0.0,
            "score": -1.0,
            "short_horizon": short_horizon,
            "main_horizon": main_horizon,
        }

    daily_short: List[float] = []
    daily_main: List[float] = []
    for d in eval_dates:
        g = dataset[dataset["trade_date"] == d].copy()
        if g.empty:
            continue
        g["score"] = score_candidates(
            g,
            weights=weights,
            short_cycle_weight=short_cycle_weight,
            tradeability_penalty_weight=tradeability_penalty_weight,
        )
        chosen = pick_top_with_industry_limit(g, top_n=top_n, max_per_industry=max_per_industry)
        if chosen.empty:
            continue

        short_ret = float(chosen[short_col].mean())
        main_ret = float(chosen[main_col].mean())
        if not np.isfinite(short_ret) or not np.isfinite(main_ret):
            continue
        daily_short.append(short_ret)
        daily_main.append(main_ret)

    if not daily_short or not daily_main:
        return {
            "sample_days": 0,
            "mean_ret_short": 0.0,
            "mean_ret_main": 0.0,
            "win_rate_short": 0.0,
            "win_rate_main": 0.0,
            "sharpe_short": 0.0,
            "sharpe_main": 0.0,
            "score": -1.0,
            "short_horizon": short_horizon,
            "main_horizon": main_horizon,
        }

    s_short = pd.Series(daily_short, dtype=float)
    s_main = pd.Series(daily_main, dtype=float)
    mean_ret_short = float(s_short.mean())
    mean_ret_main = float(s_main.mean())
    win_rate_short = float((s_short > 0).mean())
    win_rate_main = float((s_main > 0).mean())
    sharpe_short = _calc_sharpe(s_short)
    sharpe_main = _calc_sharpe(s_main)
    score = _score_metrics(mean_ret_short, mean_ret_main, win_rate_main)
    return {
        "sample_days": int(len(s_main)),
        "mean_ret_short": mean_ret_short,
        "mean_ret_main": mean_ret_main,
        "win_rate_short": win_rate_short,
        "win_rate_main": win_rate_main,
        "sharpe_short": sharpe_short,
        "sharpe_main": sharpe_main,
        "score": score,
        "short_horizon": short_horizon,
        "main_horizon": main_horizon,
    }


def build_backtest_comparison(
    dataset: pd.DataFrame,
    all_dates: List[str],
    current_weights: Dict[str, float],
    recommended_weights: Dict[str, float],
    short_cycle_weight: float,
    tradeability_penalty_weight: float,
    top_n: int,
    max_per_industry: int,
    short_horizon: int,
    main_horizon: int,
) -> pd.DataFrame:
    split_idx = max(1, int(len(all_dates) * 0.7))
    split_idx = min(split_idx, len(all_dates) - 1) if len(all_dates) > 1 else 1
    train_dates = all_dates[:split_idx]
    val_dates = all_dates[split_idx:] if len(all_dates) > 1 else all_dates

    rows: List[Dict] = []
    windows = [
        ("all", all_dates),
        ("train", train_dates),
        ("validation", val_dates),
    ]
    profiles = [
        ("current", current_weights),
        ("recommended", recommended_weights),
    ]
    for window_name, dates in windows:
        for profile_name, weights in profiles:
            m = run_weight_profile_backtest(
                dataset=dataset,
                weights=weights,
                short_cycle_weight=short_cycle_weight,
                tradeability_penalty_weight=tradeability_penalty_weight,
                top_n=top_n,
                max_per_industry=max_per_industry,
                eval_dates=dates,
                short_horizon=short_horizon,
                main_horizon=main_horizon,
            )
            rows.append(
                {
                    "window": window_name,
                    "profile": profile_name,
                    "sample_days": int(m["sample_days"]),
                    "mean_ret_short": float(m["mean_ret_short"]),
                    "mean_ret_main": float(m["mean_ret_main"]),
                    "win_rate_short": float(m["win_rate_short"]),
                    "win_rate_main": float(m["win_rate_main"]),
                    "sharpe_short": float(m["sharpe_short"]),
                    "sharpe_main": float(m["sharpe_main"]),
                    "score": float(m["score"]),
                }
            )

    result = pd.DataFrame(rows)
    if result.empty:
        return result

    diff_rows: List[Dict] = []
    for window_name in result["window"].drop_duplicates().tolist():
        cur = result[(result["window"] == window_name) & (result["profile"] == "current")]
        rec = result[(result["window"] == window_name) & (result["profile"] == "recommended")]
        if cur.empty or rec.empty:
            continue
        c = cur.iloc[0]
        r = rec.iloc[0]
        diff_rows.append(
            {
                "window": window_name,
                "profile": "delta(recommended-current)",
                "sample_days": int(r["sample_days"] - c["sample_days"]),
                "mean_ret_short": float(r["mean_ret_short"] - c["mean_ret_short"]),
                "mean_ret_main": float(r["mean_ret_main"] - c["mean_ret_main"]),
                "win_rate_short": float(r["win_rate_short"] - c["win_rate_short"]),
                "win_rate_main": float(r["win_rate_main"] - c["win_rate_main"]),
                "sharpe_short": float(r["sharpe_short"] - c["sharpe_short"]),
                "sharpe_main": float(r["sharpe_main"] - c["sharpe_main"]),
                "score": float(r["score"] - c["score"]),
            }
        )
    if diff_rows:
        result = pd.concat([result, pd.DataFrame(diff_rows)], ignore_index=True)
    return result


def write_report(
    report_path: Path,
    run_meta: Dict,
    ic_tables: Dict[int, pd.DataFrame],
    corr_matrix: pd.DataFrame,
    redundant_pairs: pd.DataFrame,
    layer_summary: pd.DataFrame,
    layer_detail: Dict[str, pd.DataFrame],
    weight_df: pd.DataFrame,
    action_df: pd.DataFrame,
    aux_param_df: pd.DataFrame,
    backtest_compare_df: pd.DataFrame,
):
    lines: List[str] = []
    lines.append("# 增强策略因子归因与去重诊断报告")
    lines.append("")
    lines.append(f"- 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"- 样本交易日: {run_meta['signal_start']} ~ {run_meta['signal_end']} ({run_meta['signal_days']} 天)")
    lines.append(f"- 因子样本行数: {run_meta['dataset_rows']}")
    lines.append(f"- 覆盖股票数: {run_meta['symbol_count']}")
    lines.append(f"- 当前增强权重档位: {run_meta['active_weight_profile']}")
    lines.append(f"- 分析周期: {run_meta['horizons']}, 主周期: T+{run_meta['primary_horizon']}")
    lines.append("")

    lines.append("## 1. 多周期 IC / RankIC")
    lines.append("")
    for horizon, table in ic_tables.items():
        lines.append(f"### T+{horizon}（开盘买入 -> 收盘卖出）")
        if table.empty:
            lines.append("无可用结果")
            lines.append("")
            continue
        show = table[
            [
                "factor",
                "rank_ic_mean",
                "rank_ic_ir",
                "rank_ic_positive_ratio",
                "pearson_ic_mean",
                "sample_days",
            ]
        ].copy()
        lines.append(show.to_markdown(index=False))
        lines.append("")

    lines.append("## 2. 因子相关性与去重")
    lines.append("")
    if corr_matrix.empty:
        lines.append("相关性矩阵为空")
    else:
        lines.append("### Spearman 相关性矩阵")
        lines.append(corr_matrix.round(3).to_markdown())
    lines.append("")

    lines.append(f"### 高相关因子对（|corr| >= {run_meta['corr_threshold']:.2f}）")
    if redundant_pairs.empty:
        lines.append("未识别到高相关因子对")
    else:
        lines.append(
            redundant_pairs[["factor_a", "factor_b", "corr", "abs_corr"]]
            .round(4)
            .to_markdown(index=False)
        )
    lines.append("")

    if not action_df.empty:
        lines.append("### 去重动作建议（保留/降权）")
        lines.append(
            action_df[
                [
                    "factor_a",
                    "factor_b",
                    "corr",
                    "action_type",
                    "keep_factor",
                    "reduce_factor",
                    "keep_rank_ic",
                    "reduce_rank_ic",
                    "penalty_factor",
                ]
            ]
            .round(4)
            .to_markdown(index=False)
        )
        lines.append("")

    lines.append(f"## 3. 分层收益（主周期 T+{run_meta['primary_horizon']}）")
    lines.append("")
    if layer_summary.empty:
        lines.append("无分层结果")
        lines.append("")
    else:
        lines.append(layer_summary.round(4).to_markdown(index=False))
        lines.append("")
        for factor in layer_summary["factor"].tolist():
            detail = layer_detail.get(factor)
            if detail is None or detail.empty:
                continue
            lines.append(f"### {factor} 分层明细")
            lines.append(detail.round(5).to_markdown(index=False))
            lines.append("")

    lines.append("## 4. 建议权重（去重后）")
    lines.append("")
    lines.append(weight_df.round(4).to_markdown(index=False))
    lines.append("")

    lines.append("## 5. 权重回测对比（旧 vs 新）")
    lines.append("")
    if backtest_compare_df is None or backtest_compare_df.empty:
        lines.append("无回测对比结果")
    else:
        bt = backtest_compare_df.copy()
        for col in ["mean_ret_short", "mean_ret_main", "win_rate_short", "win_rate_main"]:
            bt[col] = bt[col].astype(float)
        lines.append(
            bt[
                [
                    "window",
                    "profile",
                    "sample_days",
                    "mean_ret_short",
                    "mean_ret_main",
                    "win_rate_short",
                    "win_rate_main",
                    "sharpe_short",
                    "sharpe_main",
                    "score",
                ]
            ]
            .round(4)
            .to_markdown(index=False)
        )
        lines.append(
            f"- 其中 `mean_ret_short` 对应 T+{run_meta['short_horizon']}，`mean_ret_main` 对应 T+{run_meta['main_horizon']}"
        )
    lines.append("")

    lines.append("## 6. 辅助参数建议")
    lines.append("")
    if aux_param_df is None or aux_param_df.empty:
        lines.append("无辅助参数建议")
    else:
        lines.append(aux_param_df.round(4).to_markdown(index=False))
    lines.append("")

    lines.append("## 7. 结论")
    lines.append("")
    top_raise = weight_df.sort_values("delta", ascending=False).head(2)
    top_cut = weight_df.sort_values("delta", ascending=True).head(2)
    lines.append(
        "- 建议优先提升权重: "
        + ", ".join(f"{r['factor']}({r['delta']:+.2%})" for _, r in top_raise.iterrows())
    )
    lines.append(
        "- 建议优先降权: "
        + ", ".join(f"{r['factor']}({r['delta']:+.2%})" for _, r in top_cut.iterrows())
    )
    if redundant_pairs.empty:
        lines.append("- 本轮未检测到明显重复因子冲突")
    else:
        lines.append(f"- 检测到 {len(redundant_pairs)} 组高相关因子对，建议按去重动作表执行")
    if not action_df.empty:
        base_aux_cnt = int((action_df["action_type"] == "base_aux").sum())
        if base_aux_cnt > 0:
            lines.append(f"- 其中 {base_aux_cnt} 组属于主因子与辅助因子重叠，需同时关注短周期/交易性参数")
    lines.append("")

    report_path.write_text("\n".join(lines), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description="Factor attribution and de-dup analysis for enhanced strategy.")
    parser.add_argument("--signal-days", type=int, default=120, help="number of signal dates")
    parser.add_argument("--horizons", type=str, default="2,3,4,5", help="future horizons, comma-separated")
    parser.add_argument("--primary-horizon", type=int, default=5, help="primary horizon for layer/de-dup")
    parser.add_argument("--corr-threshold", type=float, default=0.65, help="redundancy threshold")
    parser.add_argument("--layers", type=int, default=5, help="layer count for qcut")
    parser.add_argument("--min-cross-section", type=int, default=80, help="min samples per day for IC")
    parser.add_argument("--min-layer-samples", type=int, default=120, help="min samples per day for layer analysis")
    args = parser.parse_args()

    horizons = []
    for part in args.horizons.split(","):
        part = part.strip()
        if not part:
            continue
        h = int(part)
        if h >= 2:
            horizons.append(h)
    horizons = sorted(set(horizons))
    if not horizons:
        raise RuntimeError("horizons is empty")
    if args.primary_horizon not in horizons:
        horizons = sorted(set(horizons + [int(args.primary_horizon)]))

    config = ConfigManager()
    db_path = Path(config.get("database.path", "data/database/quant_system.db"))
    conn = sqlite3.connect(str(db_path))

    try:
        trade_dates = load_trade_dates(conn)
        signal_dates = choose_signal_dates(trade_dates, signal_days=args.signal_days, horizon_max=max(horizons))
        if not signal_dates:
            raise RuntimeError("not enough trade dates for analysis window")

        panel = load_factor_panel(conn, signal_dates)
        if panel.empty:
            raise RuntimeError("factor panel is empty")

        dataset = attach_forward_returns(conn, panel=panel, trade_dates=trade_dates, horizons=horizons)
        if dataset.empty:
            raise RuntimeError("dataset with forward returns is empty")

        final_dates = sorted(dataset["trade_date"].astype(str).unique().tolist())
        ic_tables: Dict[int, pd.DataFrame] = {}
        for h in horizons:
            target = f"ret_{h}_oc"
            ic_tables[h] = calc_daily_ic_summary(
                dataset=dataset,
                factors=ALL_FACTORS,
                target=target,
                min_cross_section=args.min_cross_section,
            )

        corr_matrix = calc_factor_correlation(dataset, ALL_FACTORS)
        redundant_pairs = identify_redundant_pairs(corr_matrix, threshold=float(args.corr_threshold))

        primary_ic = ic_tables.get(args.primary_horizon, pd.DataFrame())
        current_weights = load_current_base_weights(config)
        weight_df, action_df = build_weight_suggestions(
            current_weights=current_weights,
            ic_primary=primary_ic,
            redundant_pairs=redundant_pairs,
            corr_threshold=float(args.corr_threshold),
        )
        aux_param_df = build_aux_param_suggestions(
            config=config,
            ic_primary=primary_ic,
            action_df=action_df,
        )
        recommended_weights = {
            str(row["factor"]): float(row["recommended_weight"])
            for _, row in weight_df.iterrows()
        }

        short_horizon = 3 if 3 in horizons else int(min(horizons))
        main_horizon = int(args.primary_horizon)
        short_cycle_weight = float(config.get("stock_selection.short_cycle_score_weight", 0.16))
        tradeability_penalty_weight = float(config.get("stock_selection.tradeability_penalty_weight", 0.18))
        top_n = int(config.get("stock_selection.top_n", 10))
        max_per_industry = int(config.get("stock_selection.max_per_industry", 3))
        backtest_compare_df = build_backtest_comparison(
            dataset=dataset,
            all_dates=final_dates,
            current_weights=current_weights,
            recommended_weights=recommended_weights,
            short_cycle_weight=short_cycle_weight,
            tradeability_penalty_weight=tradeability_penalty_weight,
            top_n=top_n,
            max_per_industry=max_per_industry,
            short_horizon=short_horizon,
            main_horizon=main_horizon,
        )

        layer_rows: List[Dict] = []
        layer_detail: Dict[str, pd.DataFrame] = {}
        primary_target = f"ret_{args.primary_horizon}_oc"
        for factor in ALL_FACTORS:
            prof = calc_layer_profile(
                dataset=dataset,
                factor=factor,
                target=primary_target,
                layers=int(args.layers),
                min_samples=int(args.min_layer_samples),
            )
            layer_rows.append(
                {
                    "factor": factor,
                    "sample_days": prof["sample_days"],
                    "top_bottom_mean": prof["top_bottom_mean"],
                    "top_bottom_positive_ratio": prof["top_bottom_positive_ratio"],
                    "daily_monotonic_mean": prof["daily_monotonic_mean"],
                }
            )
            layer_detail[factor] = prof["layer_table"]

        layer_summary = pd.DataFrame(layer_rows).sort_values("top_bottom_mean", ascending=False).reset_index(drop=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_dir = Path("reports")
        report_dir.mkdir(parents=True, exist_ok=True)
        report_path = report_dir / f"factor_attribution_dedup_{timestamp}.md"
        json_path = report_dir / f"factor_attribution_dedup_{timestamp}.json"

        run_meta = {
            "signal_start": final_dates[0],
            "signal_end": final_dates[-1],
            "signal_days": len(final_dates),
            "dataset_rows": int(len(dataset)),
            "symbol_count": int(dataset["ts_code"].nunique()),
            "active_weight_profile": str(config.get("stock_selection.enhanced_weight_profile", "active")),
            "horizons": horizons,
            "primary_horizon": int(args.primary_horizon),
            "corr_threshold": float(args.corr_threshold),
            "layers": int(args.layers),
            "min_cross_section": int(args.min_cross_section),
            "min_layer_samples": int(args.min_layer_samples),
            "short_horizon": short_horizon,
            "main_horizon": main_horizon,
            "top_n": top_n,
            "max_per_industry": max_per_industry,
        }

        write_report(
            report_path=report_path,
            run_meta=run_meta,
            ic_tables=ic_tables,
            corr_matrix=corr_matrix,
            redundant_pairs=redundant_pairs,
            layer_summary=layer_summary,
            layer_detail=layer_detail,
            weight_df=weight_df,
            action_df=action_df,
            aux_param_df=aux_param_df,
            backtest_compare_df=backtest_compare_df,
        )

        payload = {
            "run_meta": run_meta,
            "ic_tables": {str(k): _records(v) for k, v in ic_tables.items()},
            "correlation_matrix": corr_matrix.round(6).to_dict() if not corr_matrix.empty else {},
            "redundant_pairs": _records(redundant_pairs),
            "weight_suggestions": _records(weight_df),
            "dedup_actions": _records(action_df),
            "aux_param_suggestions": _records(aux_param_df),
            "backtest_compare": _records(backtest_compare_df),
            "layer_summary": _records(layer_summary),
            "layer_detail": {k: _records(v) for k, v in layer_detail.items()},
        }
        json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

        print("report:", report_path.as_posix())
        print("json:", json_path.as_posix())
        print("recommended_weights:", {r["factor"]: r["recommended_weight"] for r in _records(weight_df)})
        print("recommended_aux_params:", {r["parameter"]: r["recommended_value"] for r in _records(aux_param_df)})
    finally:
        conn.close()


if __name__ == "__main__":
    main()
