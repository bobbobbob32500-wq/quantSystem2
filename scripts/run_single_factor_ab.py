# -*- coding: utf-8 -*-
"""
增强策略单因子幅度实验

目标：
1. 在当前增强权重档位基础上，只调整一个因子的权重
2. 其余因子按原相对比例缩放，保证总权重始终为 1
3. 输出 all / train / validation 三窗对比
4. 先支持 pullback / quality 两类单因子 AB
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from src.core.config import ConfigManager

from analyze_factor_attribution_dedup import (
    BASE_FACTORS,
    _normalize_weights,
    attach_forward_returns,
    choose_signal_dates,
    load_current_base_weights,
    load_factor_panel,
    load_trade_dates,
    run_weight_profile_backtest,
)


FACTOR_ALIASES = {
    "trend": "trend_score",
    "momentum": "momentum_score",
    "volume": "volume_score",
    "fundamental": "fundamental_score",
    "pullback": "pullback_score",
    "quality": "quality_score",
}


def resolve_factor_name(name: str) -> str:
    normalized = str(name).strip().lower()
    if not normalized:
        raise ValueError("factor name is empty")
    if normalized in FACTOR_ALIASES:
        return FACTOR_ALIASES[normalized]
    if normalized.endswith("_score") and normalized in BASE_FACTORS:
        return normalized
    raise ValueError(f"unsupported factor: {name}")


def load_named_profile_weights(config: ConfigManager, profile_name: str) -> Dict[str, float]:
    profiles = config.get("stock_selection.enhanced_weight_profiles", {}) or {}
    profile = profiles.get(profile_name, {}) if isinstance(profiles, dict) else {}

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


def build_candidate_grid(
    factor: str,
    current_weight: float,
    recommended_weight: float,
    grid_points: int,
) -> List[float]:
    diff = abs(current_weight - recommended_weight)
    pad = max(0.04, diff * 0.8)
    low = max(0.0, min(current_weight, recommended_weight) - pad)
    high = min(0.55, max(current_weight, recommended_weight) + pad)

    # pullback 更适合向下探索，quality 更适合向上探索
    if factor == "pullback_score":
        low = max(0.0, min(low, recommended_weight * 0.6))
    if factor == "quality_score":
        high = min(0.55, max(high, recommended_weight * 1.1))

    grid = np.linspace(low, high, max(5, int(grid_points)))
    anchors = [current_weight, recommended_weight, (current_weight + recommended_weight) / 2.0]
    values = sorted(
        {
            round(float(v), 4)
            for v in list(grid) + anchors
            if 0.0 <= float(v) < 1.0
        }
    )
    return values


def adjust_single_factor_weight(
    base_weights: Dict[str, float],
    factor: str,
    target_weight: float,
) -> Dict[str, float]:
    current = dict(base_weights)
    target_weight = float(min(max(target_weight, 0.0), 0.95))
    other_keys = [k for k in current if k != factor]
    other_sum = float(sum(current[k] for k in other_keys))
    residual = max(0.0, 1.0 - target_weight)

    if other_sum <= 1e-12:
        n = len(other_keys) or 1
        adjusted = {k: residual / n for k in other_keys}
    else:
        adjusted = {
            k: current[k] / other_sum * residual
            for k in other_keys
        }
    adjusted[factor] = target_weight
    return _normalize_weights(adjusted)


def evaluate_weight_profile(
    dataset: pd.DataFrame,
    all_dates: List[str],
    weights: Dict[str, float],
    short_cycle_weight: float,
    tradeability_penalty_weight: float,
    top_n: int,
    max_per_industry: int,
    short_horizon: int,
    main_horizon: int,
) -> Dict[str, Dict[str, float]]:
    split_idx = max(1, int(len(all_dates) * 0.7))
    split_idx = min(split_idx, len(all_dates) - 1) if len(all_dates) > 1 else 1
    windows = {
        "all": all_dates,
        "train": all_dates[:split_idx],
        "validation": all_dates[split_idx:] if len(all_dates) > 1 else all_dates,
    }

    result = {}
    for window_name, dates in windows.items():
        result[window_name] = run_weight_profile_backtest(
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
    return result


def summarize_single_factor_ab(
    factor: str,
    current_weights: Dict[str, float],
    recommended_weights: Dict[str, float],
    dataset: pd.DataFrame,
    all_dates: List[str],
    short_cycle_weight: float,
    tradeability_penalty_weight: float,
    top_n: int,
    max_per_industry: int,
    short_horizon: int,
    main_horizon: int,
    grid_points: int,
) -> Tuple[pd.DataFrame, Dict[str, float], Dict[str, float]]:
    baseline_eval = evaluate_weight_profile(
        dataset=dataset,
        all_dates=all_dates,
        weights=current_weights,
        short_cycle_weight=short_cycle_weight,
        tradeability_penalty_weight=tradeability_penalty_weight,
        top_n=top_n,
        max_per_industry=max_per_industry,
        short_horizon=short_horizon,
        main_horizon=main_horizon,
    )
    baseline = baseline_eval["validation"]

    current_weight = float(current_weights[factor])
    recommended_weight = float(recommended_weights.get(factor, current_weight))
    grid = build_candidate_grid(
        factor=factor,
        current_weight=current_weight,
        recommended_weight=recommended_weight,
        grid_points=grid_points,
    )

    rows: List[Dict] = []
    best_weights_by_validation = dict(current_weights)
    best_weights_balanced = dict(current_weights)
    best_validation_key = None
    best_balanced_key = None

    for target_weight in grid:
        candidate_weights = adjust_single_factor_weight(current_weights, factor, target_weight)
        eval_result = evaluate_weight_profile(
            dataset=dataset,
            all_dates=all_dates,
            weights=candidate_weights,
            short_cycle_weight=short_cycle_weight,
            tradeability_penalty_weight=tradeability_penalty_weight,
            top_n=top_n,
            max_per_industry=max_per_industry,
            short_horizon=short_horizon,
            main_horizon=main_horizon,
        )

        val = eval_result["validation"]
        all_window = eval_result["all"]
        train = eval_result["train"]
        delta_val_score = float(val["score"] - baseline["score"])
        delta_val_main = float(val["mean_ret_main"] - baseline["mean_ret_main"])
        delta_all_score = float(all_window["score"] - baseline_eval["all"]["score"])
        balanced_score = delta_val_score * 0.75 + delta_all_score * 0.25

        rows.append(
            {
                "factor": factor,
                "candidate_weight": float(target_weight),
                "delta_weight": float(target_weight - current_weight),
                "all_score": float(all_window["score"]),
                "all_mean_ret_main": float(all_window["mean_ret_main"]),
                "all_win_rate_main": float(all_window["win_rate_main"]),
                "train_score": float(train["score"]),
                "train_mean_ret_main": float(train["mean_ret_main"]),
                "validation_score": float(val["score"]),
                "validation_mean_ret_main": float(val["mean_ret_main"]),
                "validation_win_rate_main": float(val["win_rate_main"]),
                "delta_validation_score": delta_val_score,
                "delta_validation_mean_ret_main": delta_val_main,
                "delta_all_score": delta_all_score,
                "balanced_score": balanced_score,
                "weights": candidate_weights,
            }
        )

    table = pd.DataFrame(rows).sort_values(
        ["validation_score", "validation_mean_ret_main", "all_score"],
        ascending=False,
    ).reset_index(drop=True)

    if not table.empty:
        best_validation_key = int(table.index[0])
        best_weights_by_validation = dict(table.iloc[0]["weights"])

        balanced_table = table.sort_values(
            ["balanced_score", "validation_mean_ret_main", "all_score"],
            ascending=False,
        ).reset_index(drop=True)
        if not balanced_table.empty:
            best_balanced_key = int(balanced_table.index[0])
            best_weights_balanced = dict(balanced_table.iloc[0]["weights"])

        table["best_validation"] = False
        table.loc[table.index == best_validation_key, "best_validation"] = True
        table["best_balanced"] = False
        balanced_first_weight = balanced_table.iloc[0]["candidate_weight"]
        table.loc[table["candidate_weight"] == balanced_first_weight, "best_balanced"] = True

    meta = {
        "factor": factor,
        "current_weight": current_weight,
        "recommended_weight": recommended_weight,
        "grid": grid,
    }
    return table, best_weights_by_validation, {**meta, "best_balanced_weights": best_weights_balanced}


def write_report(
    report_path: Path,
    run_meta: Dict,
    baseline_weights: Dict[str, float],
    factor_tables: Dict[str, pd.DataFrame],
):
    lines: List[str] = []
    lines.append("# 单因子幅度实验报告")
    lines.append("")
    lines.append(f"- 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"- 基线增强权重档位: {run_meta['active_weight_profile']}")
    lines.append(f"- 推荐档位参考: {run_meta['recommended_profile']}")
    lines.append(f"- 样本交易日: {run_meta['signal_start']} ~ {run_meta['signal_end']} ({run_meta['signal_days']} 天)")
    lines.append(f"- 分析周期: T+{run_meta['short_horizon']} / T+{run_meta['main_horizon']}")
    lines.append("")

    lines.append("## 基线权重")
    lines.append("")
    baseline_df = pd.DataFrame(
        [{"factor": k, "weight": v} for k, v in baseline_weights.items()]
    ).sort_values("weight", ascending=False)
    lines.append(baseline_df.round(4).to_markdown(index=False))
    lines.append("")

    for factor, table in factor_tables.items():
        lines.append(f"## {factor} 单因子 AB")
        lines.append("")
        if table.empty:
            lines.append("无有效结果")
            lines.append("")
            continue

        top_view = table[
            [
                "candidate_weight",
                "delta_weight",
                "validation_score",
                "validation_mean_ret_main",
                "validation_win_rate_main",
                "delta_validation_score",
                "delta_validation_mean_ret_main",
                "all_score",
                "delta_all_score",
                "balanced_score",
                "best_validation",
                "best_balanced",
            ]
        ].copy()
        lines.append(top_view.round(4).to_markdown(index=False))
        lines.append("")

        best_val = table[table["best_validation"]].head(1)
        best_bal = table[table["best_balanced"]].head(1)
        if not best_val.empty:
            row = best_val.iloc[0]
            lines.append(
                f"- 最优验证窗权重: {row['candidate_weight']:.4f} "
                f"(validation_score={row['validation_score']:.4f}, "
                f"delta_validation_mean_ret_main={row['delta_validation_mean_ret_main']:.4f})"
            )
        if not best_bal.empty:
            row = best_bal.iloc[0]
            lines.append(
                f"- 最优平衡权重: {row['candidate_weight']:.4f} "
                f"(balanced_score={row['balanced_score']:.4f}, "
                f"delta_all_score={row['delta_all_score']:.4f})"
            )
        lines.append("")

    report_path.write_text("\n".join(lines), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description="Run single-factor AB tests for enhanced strategy.")
    parser.add_argument("--factors", type=str, default="pullback,quality", help="factor list, comma-separated")
    parser.add_argument("--signal-days", type=int, default=120, help="number of signal dates")
    parser.add_argument("--horizons", type=str, default="2,3,4,5", help="future horizons")
    parser.add_argument("--short-horizon", type=int, default=3, help="short evaluation horizon")
    parser.add_argument("--main-horizon", type=int, default=5, help="main evaluation horizon")
    parser.add_argument("--grid-points", type=int, default=11, help="grid points for one-factor scan")
    parser.add_argument("--recommended-profile", type=str, default="recommended", help="reference profile name")
    args = parser.parse_args()

    factors = [resolve_factor_name(item) for item in args.factors.split(",") if item.strip()]
    if not factors:
        raise RuntimeError("no factors specified")

    horizons = sorted({int(item.strip()) for item in args.horizons.split(",") if item.strip()})
    horizons = sorted(set(horizons + [int(args.short_horizon), int(args.main_horizon)]))

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

        all_dates = sorted(dataset["trade_date"].astype(str).unique().tolist())
        baseline_weights = load_current_base_weights(config)
        recommended_weights = load_named_profile_weights(config, args.recommended_profile)

        short_cycle_weight = float(config.get("stock_selection.short_cycle_score_weight", 0.16))
        tradeability_penalty_weight = float(config.get("stock_selection.tradeability_penalty_weight", 0.18))
        top_n = int(config.get("stock_selection.top_n", 10))
        max_per_industry = int(config.get("stock_selection.max_per_industry", 3))

        factor_tables: Dict[str, pd.DataFrame] = {}
        summary_rows: List[Dict] = []
        for factor in factors:
            table, _, meta = summarize_single_factor_ab(
                factor=factor,
                current_weights=baseline_weights,
                recommended_weights=recommended_weights,
                dataset=dataset,
                all_dates=all_dates,
                short_cycle_weight=short_cycle_weight,
                tradeability_penalty_weight=tradeability_penalty_weight,
                top_n=top_n,
                max_per_industry=max_per_industry,
                short_horizon=int(args.short_horizon),
                main_horizon=int(args.main_horizon),
                grid_points=int(args.grid_points),
            )
            factor_tables[factor] = table
            if not table.empty:
                best_val = table[table["best_validation"]].head(1).iloc[0]
                best_bal = table[table["best_balanced"]].head(1).iloc[0]
                summary_rows.append(
                    {
                        "factor": factor,
                        "current_weight": meta["current_weight"],
                        "recommended_weight": meta["recommended_weight"],
                        "best_validation_weight": float(best_val["candidate_weight"]),
                        "best_validation_score": float(best_val["validation_score"]),
                        "best_validation_delta_main": float(best_val["delta_validation_mean_ret_main"]),
                        "best_balanced_weight": float(best_bal["candidate_weight"]),
                        "best_balanced_score": float(best_bal["balanced_score"]),
                    }
                )

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_dir = Path("reports")
        report_dir.mkdir(parents=True, exist_ok=True)
        report_path = report_dir / f"single_factor_ab_{timestamp}.md"
        json_path = report_dir / f"single_factor_ab_{timestamp}.json"

        run_meta = {
            "active_weight_profile": str(config.get("stock_selection.enhanced_weight_profile", "active")),
            "recommended_profile": str(args.recommended_profile),
            "signal_start": all_dates[0],
            "signal_end": all_dates[-1],
            "signal_days": len(all_dates),
            "short_horizon": int(args.short_horizon),
            "main_horizon": int(args.main_horizon),
            "factors": factors,
        }
        write_report(
            report_path=report_path,
            run_meta=run_meta,
            baseline_weights=baseline_weights,
            factor_tables=factor_tables,
        )

        payload = {
            "run_meta": run_meta,
            "baseline_weights": baseline_weights,
            "summary": summary_rows,
            "factor_tables": {factor: json.loads(table.to_json(orient="records", force_ascii=False)) for factor, table in factor_tables.items()},
        }
        json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

        print("report:", report_path.as_posix())
        print("json:", json_path.as_posix())
        print("summary:", json.dumps(summary_rows, ensure_ascii=False))
    finally:
        conn.close()


if __name__ == "__main__":
    main()
