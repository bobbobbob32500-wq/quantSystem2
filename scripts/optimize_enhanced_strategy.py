# -*- coding: utf-8 -*-
"""
增强型选股策略历史回测 + IC分析 + 权重寻优

目标:
1. 使用本地真实历史数据评估增强策略在短线(3/5个交易日)的表现
2. 计算各因子IC统计
3. 在训练集进行权重搜索, 在验证集评估泛化能力
4. 输出优化报告, 给出推荐权重
"""

from __future__ import annotations

import argparse
import json
import math
import sqlite3
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.core.config import ConfigManager


FACTOR_COLUMNS = [
    "trend_score",
    "momentum_score",
    "volume_score",
    "fundamental_score",
    "pullback_score",
    "quality_score",
]

EXTRA_COLUMNS = [
    "short_cycle_score",
    "tradeability_score",
]


@dataclass
class BacktestMetrics:
    sample_days: int
    mean_ret_3: float
    mean_ret_5: float
    win_rate_3: float
    win_rate_5: float
    sharpe_3: float
    sharpe_5: float
    score: float

    def to_dict(self) -> Dict[str, float]:
        return {
            "sample_days": int(self.sample_days),
            "mean_ret_3": float(self.mean_ret_3),
            "mean_ret_5": float(self.mean_ret_5),
            "win_rate_3": float(self.win_rate_3),
            "win_rate_5": float(self.win_rate_5),
            "sharpe_3": float(self.sharpe_3),
            "sharpe_5": float(self.sharpe_5),
            "score": float(self.score),
        }


def _safe_spearman(x: pd.Series, y: pd.Series) -> float:
    pair = pd.DataFrame({"x": x, "y": y}).dropna()
    if len(pair) < 30:
        return math.nan
    corr, _ = spearmanr(pair["x"], pair["y"])
    if pd.isna(corr):
        return math.nan
    return float(corr)


def _calc_sharpe(returns: pd.Series) -> float:
    if returns.empty:
        return 0.0
    std = float(returns.std(ddof=0))
    if std <= 1e-12:
        return 0.0
    return float(returns.mean() / std)


def _score_metrics(mean_ret_3: float, mean_ret_5: float, win_rate_5: float) -> float:
    # 优先5日收益, 同时兼顾3日收益与胜率
    return float(mean_ret_5 * 0.7 + mean_ret_3 * 0.3 + (win_rate_5 - 0.5) * 0.02)


def load_trade_dates(conn: sqlite3.Connection) -> List[str]:
    sql = "SELECT DISTINCT trade_date FROM stock_daily ORDER BY trade_date"
    return [row[0] for row in conn.execute(sql).fetchall()]


def choose_signal_dates(trade_dates: List[str], signal_days: int, horizon_max: int) -> List[str]:
    if len(trade_dates) <= horizon_max:
        return []
    max_idx = len(trade_dates) - 1 - horizon_max
    start_idx = max(0, max_idx - signal_days + 1)
    return trade_dates[start_idx : max_idx + 1]


def load_factor_panel(conn: sqlite3.Connection, signal_dates: List[str]) -> pd.DataFrame:
    placeholders = ",".join(["?"] * len(signal_dates))
    factor_names = FACTOR_COLUMNS + EXTRA_COLUMNS
    factor_placeholders = ",".join(["?"] * len(factor_names))
    sql = f"""
        SELECT trade_date, ts_code, factor_name, factor_value
        FROM factor_values
        WHERE trade_date IN ({placeholders})
          AND factor_name IN ({factor_placeholders})
    """
    params = list(signal_dates) + factor_names
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
    )

    needed = FACTOR_COLUMNS + EXTRA_COLUMNS
    panel = panel.dropna(subset=needed)

    industry = pd.read_sql("SELECT ts_code, industry FROM stock_basic", conn)
    panel = panel.merge(industry, on="ts_code", how="left")
    panel["industry"] = panel["industry"].fillna("未知")
    return panel


def attach_forward_returns(
    conn: sqlite3.Connection,
    panel: pd.DataFrame,
    trade_dates: List[str],
    horizon_3: int,
    horizon_5: int,
) -> pd.DataFrame:
    if panel.empty:
        return panel

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
    x["buy_date"] = x["trade_date"].map(lambda d: _nth(d, 1))
    x["sell_3_date"] = x["trade_date"].map(lambda d: _nth(d, horizon_3))
    x["sell_5_date"] = x["trade_date"].map(lambda d: _nth(d, horizon_5))
    x = x.dropna(subset=["buy_date", "sell_3_date", "sell_5_date"])
    if x.empty:
        return x

    symbols = x["ts_code"].drop_duplicates().tolist()
    all_dates = sorted(
        set(x["trade_date"]) | set(x["buy_date"]) | set(x["sell_3_date"]) | set(x["sell_5_date"])
    )
    sym_ph = ",".join(["?"] * len(symbols))
    dt_ph = ",".join(["?"] * len(all_dates))
    sql = f"""
        SELECT ts_code, trade_date, open, close
        FROM stock_daily
        WHERE ts_code IN ({sym_ph}) AND trade_date IN ({dt_ph})
    """
    prices = pd.read_sql(sql, conn, params=symbols + all_dates)
    if prices.empty:
        return pd.DataFrame()
    prices["open"] = pd.to_numeric(prices["open"], errors="coerce")
    prices["close"] = pd.to_numeric(prices["close"], errors="coerce")
    prices = prices.dropna(subset=["open", "close"])

    close_t = prices.rename(columns={"trade_date": "trade_date", "close": "close_t"})[
        ["ts_code", "trade_date", "close_t"]
    ]
    buy_open = prices.rename(columns={"trade_date": "buy_date", "open": "buy_open"})[
        ["ts_code", "buy_date", "buy_open"]
    ]
    sell3_close = prices.rename(columns={"trade_date": "sell_3_date", "close": "sell_3_close"})[
        ["ts_code", "sell_3_date", "sell_3_close"]
    ]
    sell5_close = prices.rename(columns={"trade_date": "sell_5_date", "close": "sell_5_close"})[
        ["ts_code", "sell_5_date", "sell_5_close"]
    ]

    x = x.merge(close_t, on=["ts_code", "trade_date"], how="left")
    x = x.merge(buy_open, on=["ts_code", "buy_date"], how="left")
    x = x.merge(sell3_close, on=["ts_code", "sell_3_date"], how="left")
    x = x.merge(sell5_close, on=["ts_code", "sell_5_date"], how="left")
    x = x.dropna(subset=["close_t", "buy_open", "sell_3_close", "sell_5_close"])
    if x.empty:
        return x

    x["ret_3_cc"] = x["sell_3_close"] / x["close_t"] - 1.0
    x["ret_5_cc"] = x["sell_5_close"] / x["close_t"] - 1.0
    x["ret_3_oc"] = x["sell_3_close"] / x["buy_open"] - 1.0
    x["ret_5_oc"] = x["sell_5_close"] / x["buy_open"] - 1.0
    return x


def calc_ic_stats(dataset: pd.DataFrame, factors: List[str], target: str) -> pd.DataFrame:
    rows: List[Dict] = []
    for factor in factors:
        daily = []
        for _, g in dataset.groupby("trade_date"):
            ic = _safe_spearman(g[factor], g[target])
            if not pd.isna(ic):
                daily.append(ic)
        if not daily:
            continue
        s = pd.Series(daily, dtype=float)
        rows.append(
            {
                "factor": factor,
                "target": target,
                "ic_mean": float(s.mean()),
                "ic_std": float(s.std(ddof=0)),
                "ic_ir": float(s.mean() / s.std(ddof=0)) if s.std(ddof=0) > 1e-12 else 0.0,
                "ic_positive_ratio": float((s > 0).mean()),
                "sample_days": int(len(s)),
            }
        )
    return pd.DataFrame(rows).sort_values("ic_mean", ascending=False)


def score_candidates(
    df: pd.DataFrame,
    weights: Dict[str, float],
    short_cycle_weight: float,
    tradeability_penalty_weight: float,
) -> pd.Series:
    base = sum(df[f] * weights.get(f, 0.0) for f in FACTOR_COLUMNS)
    short_adj = (df["short_cycle_score"] - 50.0) * short_cycle_weight
    risk_penalty = np.maximum(0.0, (65.0 - df["tradeability_score"]) * tradeability_penalty_weight)
    total = base + short_adj - risk_penalty
    return total.clip(0.0, 100.0)


def pick_top_with_industry_limit(
    day_df: pd.DataFrame,
    top_n: int,
    max_per_industry: int,
) -> pd.DataFrame:
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


def run_portfolio_backtest(
    dataset: pd.DataFrame,
    weights: Dict[str, float],
    short_cycle_weight: float,
    tradeability_penalty_weight: float,
    top_n: int,
    max_per_industry: int,
    eval_dates: List[str],
) -> BacktestMetrics:
    daily_ret3 = []
    daily_ret5 = []
    for d in eval_dates:
        g = dataset[dataset["trade_date"] == d].copy()
        if g.empty:
            continue
        g["score"] = score_candidates(g, weights, short_cycle_weight, tradeability_penalty_weight)
        chosen = pick_top_with_industry_limit(g, top_n=top_n, max_per_industry=max_per_industry)
        if chosen.empty:
            continue
        daily_ret3.append(float(chosen["ret_3_oc"].mean()))
        daily_ret5.append(float(chosen["ret_5_oc"].mean()))

    if not daily_ret3 or not daily_ret5:
        return BacktestMetrics(0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, -1.0)

    s3 = pd.Series(daily_ret3, dtype=float)
    s5 = pd.Series(daily_ret5, dtype=float)
    mean_ret_3 = float(s3.mean())
    mean_ret_5 = float(s5.mean())
    win_rate_3 = float((s3 > 0).mean())
    win_rate_5 = float((s5 > 0).mean())
    sharpe_3 = _calc_sharpe(s3)
    sharpe_5 = _calc_sharpe(s5)
    score = _score_metrics(mean_ret_3, mean_ret_5, win_rate_5)
    return BacktestMetrics(
        sample_days=len(s3),
        mean_ret_3=mean_ret_3,
        mean_ret_5=mean_ret_5,
        win_rate_3=win_rate_3,
        win_rate_5=win_rate_5,
        sharpe_3=sharpe_3,
        sharpe_5=sharpe_5,
        score=score,
    )


def sample_weight_vectors(
    base_weights: Dict[str, float],
    n_trials: int,
    seed: int,
) -> List[Dict[str, float]]:
    rng = np.random.default_rng(seed)
    base = np.array([max(base_weights.get(f, 0.0), 1e-4) for f in FACTOR_COLUMNS], dtype=float)
    base = base / base.sum()
    alpha = np.maximum(base * 30.0, 0.4)
    candidates: List[Dict[str, float]] = []
    for _ in range(n_trials):
        w = rng.dirichlet(alpha)
        candidates.append({f: float(v) for f, v in zip(FACTOR_COLUMNS, w)})
    candidates.append({f: float(base[i]) for i, f in enumerate(FACTOR_COLUMNS)})
    return candidates


def optimize_weights(
    dataset: pd.DataFrame,
    train_dates: List[str],
    val_dates: List[str],
    base_weights: Dict[str, float],
    short_cycle_weight: float,
    tradeability_penalty_weight: float,
    top_n: int,
    max_per_industry: int,
    n_trials: int,
    seed: int,
) -> Tuple[Dict[str, float], pd.DataFrame]:
    candidates = sample_weight_vectors(base_weights, n_trials=n_trials, seed=seed)
    rows = []
    for w in candidates:
        train_metrics = run_portfolio_backtest(
            dataset,
            weights=w,
            short_cycle_weight=short_cycle_weight,
            tradeability_penalty_weight=tradeability_penalty_weight,
            top_n=top_n,
            max_per_industry=max_per_industry,
            eval_dates=train_dates,
        )
        rows.append(
            {
                **{f"w_{k}": float(v) for k, v in w.items()},
                "train_score": train_metrics.score,
                "train_mean_ret_3": train_metrics.mean_ret_3,
                "train_mean_ret_5": train_metrics.mean_ret_5,
                "train_win_rate_5": train_metrics.win_rate_5,
                "train_days": train_metrics.sample_days,
            }
        )

    result_df = pd.DataFrame(rows).sort_values("train_score", ascending=False).reset_index(drop=True)
    top_train = result_df.head(min(30, len(result_df))).copy()
    val_scores = []
    for i in range(len(top_train)):
        w = {f: float(top_train.iloc[i][f"w_{f}"]) for f in FACTOR_COLUMNS}
        val_metrics = run_portfolio_backtest(
            dataset,
            weights=w,
            short_cycle_weight=short_cycle_weight,
            tradeability_penalty_weight=tradeability_penalty_weight,
            top_n=top_n,
            max_per_industry=max_per_industry,
            eval_dates=val_dates,
        )
        val_scores.append(
            {
                "val_score": val_metrics.score,
                "val_mean_ret_3": val_metrics.mean_ret_3,
                "val_mean_ret_5": val_metrics.mean_ret_5,
                "val_win_rate_5": val_metrics.win_rate_5,
                "val_days": val_metrics.sample_days,
            }
        )
    for k in val_scores[0].keys():
        top_train[k] = [d[k] for d in val_scores]

    # 选择验证集分数最高, 若并列则优先5日收益
    top_train = top_train.sort_values(
        ["val_score", "val_mean_ret_5", "train_score"], ascending=False
    ).reset_index(drop=True)
    best = top_train.iloc[0]
    best_weights = {f: float(best[f"w_{f}"]) for f in FACTOR_COLUMNS}
    return best_weights, top_train


def write_report(
    report_path: Path,
    run_meta: Dict,
    ic3: pd.DataFrame,
    ic5: pd.DataFrame,
    baseline_all: BacktestMetrics,
    baseline_train: BacktestMetrics,
    baseline_val: BacktestMetrics,
    best_all: BacktestMetrics,
    best_train: BacktestMetrics,
    best_val: BacktestMetrics,
    best_weights: Dict[str, float],
    candidate_table: pd.DataFrame,
):
    lines: List[str] = []
    lines.append("# 增强策略历史回测与IC优化报告")
    lines.append("")
    lines.append(f"- 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"- 信号样本交易日: {run_meta['signal_start']} ~ {run_meta['signal_end']} ({run_meta['signal_days']}天)")
    lines.append(f"- 当前增强权重档位: {run_meta['active_weight_profile']}")
    lines.append(f"- 训练/验证切分: {run_meta['train_days']} / {run_meta['val_days']}")
    lines.append("")

    lines.append("## 1. 因子IC统计 (未来3日/5日 close-to-close)")
    lines.append("")
    if not ic3.empty:
        lines.append("### IC@3D")
        lines.append(ic3.to_markdown(index=False))
        lines.append("")
    if not ic5.empty:
        lines.append("### IC@5D")
        lines.append(ic5.to_markdown(index=False))
        lines.append("")

    def _metric_md(title: str, m: BacktestMetrics):
        lines.append(f"### {title}")
        lines.append("")
        lines.append("| 指标 | 数值 |")
        lines.append("|---|---:|")
        lines.append(f"| 样本天数 | {m.sample_days} |")
        lines.append(f"| 平均收益(3日) | {m.mean_ret_3:.4%} |")
        lines.append(f"| 平均收益(5日) | {m.mean_ret_5:.4%} |")
        lines.append(f"| 胜率(3日) | {m.win_rate_3:.2%} |")
        lines.append(f"| 胜率(5日) | {m.win_rate_5:.2%} |")
        lines.append(f"| Sharpe(3日) | {m.sharpe_3:.4f} |")
        lines.append(f"| Sharpe(5日) | {m.sharpe_5:.4f} |")
        lines.append(f"| 综合评分 | {m.score:.6f} |")
        lines.append("")

    lines.append("## 2. 组合回测对比 (Top10 + 行业上限3)")
    lines.append("")
    _metric_md("基线权重-全样本", baseline_all)
    _metric_md("基线权重-训练集", baseline_train)
    _metric_md("基线权重-验证集", baseline_val)
    _metric_md("优化权重-全样本", best_all)
    _metric_md("优化权重-训练集", best_train)
    _metric_md("优化权重-验证集", best_val)

    lines.append("## 3. 推荐增强权重")
    lines.append("")
    lines.append("| 因子 | 权重 |")
    lines.append("|---|---:|")
    for f in FACTOR_COLUMNS:
        lines.append(f"| {f} | {best_weights[f]:.4f} |")
    lines.append("")

    lines.append("## 4. 候选解Top10 (按验证集评分)")
    lines.append("")
    view_cols = [
        "val_score",
        "val_mean_ret_3",
        "val_mean_ret_5",
        "val_win_rate_5",
        "train_score",
    ] + [f"w_{f}" for f in FACTOR_COLUMNS]
    lines.append(candidate_table[view_cols].head(10).to_markdown(index=False))
    lines.append("")

    report_path.write_text("\n".join(lines), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description="Optimize enhanced stock-selection strategy by backtest and IC.")
    parser.add_argument("--signal-days", type=int, default=30, help="number of signal dates used for analysis")
    parser.add_argument("--n-trials", type=int, default=600, help="random-search trials")
    parser.add_argument("--seed", type=int, default=42, help="random seed")
    parser.add_argument("--horizon-3", type=int, default=3, help="short horizon (trading days from signal day)")
    parser.add_argument("--horizon-5", type=int, default=5, help="mid horizon (trading days from signal day)")
    args = parser.parse_args()

    config = ConfigManager()
    db_path = Path(config.get("database.path", "data/database/quant_system.db"))
    conn = sqlite3.connect(str(db_path))
    try:
        trade_dates = load_trade_dates(conn)
        signal_dates = choose_signal_dates(
            trade_dates,
            signal_days=args.signal_days,
            horizon_max=max(args.horizon_3, args.horizon_5),
        )
        if not signal_dates:
            raise RuntimeError("not enough trade dates for analysis")

        panel = load_factor_panel(conn, signal_dates)
        dataset = attach_forward_returns(
            conn,
            panel,
            trade_dates=trade_dates,
            horizon_3=args.horizon_3,
            horizon_5=args.horizon_5,
        )
        if dataset.empty:
            raise RuntimeError("factor/price merged dataset is empty")

        signal_dates_final = sorted(dataset["trade_date"].drop_duplicates().tolist())
        split_idx = max(1, int(len(signal_dates_final) * 0.7))
        split_idx = min(split_idx, len(signal_dates_final) - 1)
        train_dates = signal_dates_final[:split_idx]
        val_dates = signal_dates_final[split_idx:]

        ic3 = calc_ic_stats(dataset, FACTOR_COLUMNS + ["short_cycle_score", "tradeability_score"], "ret_3_cc")
        ic5 = calc_ic_stats(dataset, FACTOR_COLUMNS + ["short_cycle_score", "tradeability_score"], "ret_5_cc")

        profile_name = str(config.get("stock_selection.enhanced_weight_profile", "active")).strip().lower() or "active"
        profiles = config.get("stock_selection.enhanced_weight_profiles", {}) or {}
        profile = profiles.get(profile_name) or profiles.get("active") or {}

        def _get_weight(key: str, flat_key: str, default: float) -> float:
            if isinstance(profile, dict):
                value = profile.get(key, profile.get(flat_key))
                if value is not None:
                    return float(value)
            return float(config.get(f"stock_selection.{flat_key}", default))

        base_weights = {
            "trend_score": _get_weight("trend", "trend_factor_weight", 0.35),
            "momentum_score": _get_weight("momentum", "momentum_factor_weight", 0.30),
            "volume_score": _get_weight("volume", "volume_factor_weight", 0.05),
            "fundamental_score": _get_weight("fundamental", "fundamental_factor_weight", 0.05),
            "pullback_score": _get_weight("pullback", "pullback_factor_weight", 0.15),
            "quality_score": _get_weight("quality", "quality_factor_weight", 0.10),
        }
        total_base = sum(base_weights.values())
        if total_base <= 0:
            base_weights = {k: 1.0 / len(base_weights) for k in base_weights}
        else:
            base_weights = {k: float(v / total_base) for k, v in base_weights.items()}

        short_cycle_weight = float(config.get("stock_selection.short_cycle_score_weight", 0.16))
        tradeability_penalty_weight = float(config.get("stock_selection.tradeability_penalty_weight", 0.18))
        top_n = int(config.get("stock_selection.top_n", 10))
        max_per_industry = int(config.get("stock_selection.max_per_industry", 3))

        baseline_train = run_portfolio_backtest(
            dataset,
            weights=base_weights,
            short_cycle_weight=short_cycle_weight,
            tradeability_penalty_weight=tradeability_penalty_weight,
            top_n=top_n,
            max_per_industry=max_per_industry,
            eval_dates=train_dates,
        )
        baseline_all = run_portfolio_backtest(
            dataset,
            weights=base_weights,
            short_cycle_weight=short_cycle_weight,
            tradeability_penalty_weight=tradeability_penalty_weight,
            top_n=top_n,
            max_per_industry=max_per_industry,
            eval_dates=signal_dates_final,
        )
        baseline_val = run_portfolio_backtest(
            dataset,
            weights=base_weights,
            short_cycle_weight=short_cycle_weight,
            tradeability_penalty_weight=tradeability_penalty_weight,
            top_n=top_n,
            max_per_industry=max_per_industry,
            eval_dates=val_dates,
        )

        best_weights, candidate_table = optimize_weights(
            dataset=dataset,
            train_dates=train_dates,
            val_dates=val_dates,
            base_weights=base_weights,
            short_cycle_weight=short_cycle_weight,
            tradeability_penalty_weight=tradeability_penalty_weight,
            top_n=top_n,
            max_per_industry=max_per_industry,
            n_trials=args.n_trials,
            seed=args.seed,
        )

        best_train = run_portfolio_backtest(
            dataset,
            weights=best_weights,
            short_cycle_weight=short_cycle_weight,
            tradeability_penalty_weight=tradeability_penalty_weight,
            top_n=top_n,
            max_per_industry=max_per_industry,
            eval_dates=train_dates,
        )
        best_all = run_portfolio_backtest(
            dataset,
            weights=best_weights,
            short_cycle_weight=short_cycle_weight,
            tradeability_penalty_weight=tradeability_penalty_weight,
            top_n=top_n,
            max_per_industry=max_per_industry,
            eval_dates=signal_dates_final,
        )
        best_val = run_portfolio_backtest(
            dataset,
            weights=best_weights,
            short_cycle_weight=short_cycle_weight,
            tradeability_penalty_weight=tradeability_penalty_weight,
            top_n=top_n,
            max_per_industry=max_per_industry,
            eval_dates=val_dates,
        )

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_dir = Path("reports")
        report_dir.mkdir(parents=True, exist_ok=True)
        report_path = report_dir / f"enhanced_strategy_optimization_{timestamp}.md"

        run_meta = {
            "signal_start": signal_dates_final[0],
            "signal_end": signal_dates_final[-1],
            "signal_days": len(signal_dates_final),
            "train_days": len(train_dates),
            "val_days": len(val_dates),
            "active_weight_profile": profile_name,
            "base_weights": base_weights,
            "best_weights": best_weights,
            "short_cycle_weight": short_cycle_weight,
            "tradeability_penalty_weight": tradeability_penalty_weight,
            "top_n": top_n,
            "max_per_industry": max_per_industry,
        }
        write_report(
            report_path=report_path,
            run_meta=run_meta,
            ic3=ic3,
            ic5=ic5,
            baseline_all=baseline_all,
            baseline_train=baseline_train,
            baseline_val=baseline_val,
            best_all=best_all,
            best_train=best_train,
            best_val=best_val,
            best_weights=best_weights,
            candidate_table=candidate_table,
        )

        json_path = report_dir / f"enhanced_strategy_optimization_{timestamp}.json"
        json_path.write_text(
            json.dumps(
                {
                    "run_meta": run_meta,
                    "baseline_all": baseline_all.to_dict(),
                    "baseline_train": baseline_train.to_dict(),
                    "baseline_val": baseline_val.to_dict(),
                    "best_all": best_all.to_dict(),
                    "best_train": best_train.to_dict(),
                    "best_val": best_val.to_dict(),
                    "top_candidates": candidate_table.head(20).to_dict(orient="records"),
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        print("report:", report_path.as_posix())
        print("json:", json_path.as_posix())
        print("best_weights:", best_weights)
        print("baseline_val:", baseline_val.to_dict())
        print("best_val:", best_val.to_dict())
    finally:
        conn.close()


if __name__ == "__main__":
    main()
