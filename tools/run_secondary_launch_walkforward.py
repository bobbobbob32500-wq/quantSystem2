# -*- coding: utf-8 -*-
"""
二次启动策略 Walk-Forward 优化与验证
"""

from __future__ import annotations

from dataclasses import asdict
from itertools import product
import json
from pathlib import Path
import sys

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.core.config import ConfigManager
from src.core.database import DatabaseManager
from src.modules.mainboard_secondary_launch_strategy import (
    MainboardSecondaryLaunchStrategy,
    StrategyParams,
)
from src.modules.mainboard_secondary_launch_backtester import (
    MainboardSecondaryLaunchBacktester,
    CostConfig,
)


def build_base_objects():
    config = ConfigManager()
    db = DatabaseManager(config)
    params = StrategyParams(
        min_list_days=int(config.get("stock_selection.secondary_launch.min_list_days", 60)),
        limit_up_threshold=float(config.get("stock_selection.secondary_launch.limit_up_threshold", 9.7)),
        limit_down_threshold=float(config.get("stock_selection.secondary_launch.limit_down_threshold", -9.7)),
        limit_up_count_10_min=int(config.get("stock_selection.secondary_launch.limit_up_count_10_min", 1)),
        limit_up_count_10_max=int(config.get("stock_selection.secondary_launch.limit_up_count_10_max", 1)),
        last_limit_up_days_min=int(config.get("stock_selection.secondary_launch.last_limit_up_days_min", 2)),
        last_limit_up_days_max=int(config.get("stock_selection.secondary_launch.last_limit_up_days_max", 4)),
        drawdown_min=float(config.get("stock_selection.secondary_launch.drawdown_min", 0.03)),
        drawdown_max=float(config.get("stock_selection.secondary_launch.drawdown_max", 0.08)),
        vol_shrink_ratio=float(config.get("stock_selection.secondary_launch.vol_shrink_ratio", 0.6)),
        close_ma5_dev_max=float(config.get("stock_selection.secondary_launch.close_ma5_dev_max", 0.02)),
        min_amt_ma20=float(config.get("stock_selection.secondary_launch.min_amt_ma20", 1e5)),
        max_amt_ma20=float(config.get("stock_selection.secondary_launch.max_amt_ma20", 5e6)),
        min_price=float(config.get("stock_selection.secondary_launch.min_price", 3.0)),
        limit_up_amt_ratio_min=float(config.get("stock_selection.secondary_launch.limit_up_amt_ratio_min", 0.6)),
        limit_up_amt_ratio_max=float(config.get("stock_selection.secondary_launch.limit_up_amt_ratio_max", 3.5)),
        rs_lookback=int(config.get("stock_selection.secondary_launch.rs_lookback", 20)),
        max_candidates=int(config.get("stock_selection.secondary_launch.max_candidates", 15)),
        picks_per_day=int(config.get("stock_selection.secondary_launch.picks_per_day", 2)),
    )
    cost = CostConfig(
        buy_fee_rate=float(config.get("feedback.buy_fee_rate", 0.0003)),
        sell_fee_rate=float(config.get("feedback.sell_fee_rate", 0.0003)),
        stamp_tax_rate=float(config.get("feedback.stamp_tax_rate", 0.001)),
        transfer_fee_rate=float(config.get("stock_selection.secondary_launch.transfer_fee_rate", 0.00001)),
        slippage_rate=float(config.get("feedback.buy_slippage", 0.001)),
    )
    return config, db, params, cost


def get_folds():
    return [
        {"train_start": "20250901", "train_end": "20251130", "test_start": "20251201", "test_end": "20251231"},
        {"train_start": "20250901", "train_end": "20251231", "test_start": "20260101", "test_end": "20260131"},
        {"train_start": "20250901", "train_end": "20260131", "test_start": "20260201", "test_end": "20260228"},
        {"train_start": "20250901", "train_end": "20260228", "test_start": "20260301", "test_end": "20260331"},
    ]


def search_space(base: StrategyParams):
    return {
        "hold_days": [2, 3],
        "drawdown_min": sorted({0.02, 0.03}),
        "drawdown_max": sorted({0.06, 0.08}),
        "vol_shrink_ratio": sorted({0.60, 0.70}),
        "last_limit_up_days_min": [2],
        "last_limit_up_days_max": [4, 5],
        "limit_up_count_10_max": [1],
        "picks_per_day": [1, 2],
    }


def evaluate_candidate(base_features, signal_frame, backtester, base_params, candidate):
    params_dict = asdict(base_params)
    params_dict.update(
        {
            "drawdown_min": candidate["drawdown_min"],
            "drawdown_max": candidate["drawdown_max"],
            "vol_shrink_ratio": candidate["vol_shrink_ratio"],
            "last_limit_up_days_min": candidate["last_limit_up_days_min"],
            "last_limit_up_days_max": candidate["last_limit_up_days_max"],
            "limit_up_count_10_min": 1,
            "limit_up_count_10_max": candidate["limit_up_count_10_max"],
            "picks_per_day": candidate["picks_per_day"],
            "max_candidates": max(base_params.max_candidates, candidate["picks_per_day"] * 3),
        }
    )
    strategy = MainboardSecondaryLaunchStrategy(StrategyParams(**params_dict))
    signals = strategy.generate_signals_from_frame(signal_frame)

    fold_rows = []
    for idx, fold in enumerate(get_folds(), 1):
        train_result = backtester._build_backtest_result(
            base_features,
            signals,
            fold["train_start"],
            fold["train_end"],
            candidate["hold_days"],
        )
        test_result = backtester._build_backtest_result(
            base_features,
            signals,
            fold["test_start"],
            fold["test_end"],
            candidate["hold_days"],
        )
        train_metrics = train_result["metrics"]
        test_metrics = test_result["metrics"]
        fold_rows.append(
            {
                "fold": idx,
                "train_start": fold["train_start"],
                "train_end": fold["train_end"],
                "test_start": fold["test_start"],
                "test_end": fold["test_end"],
                "train_trades": train_metrics.get("total_trades", 0),
                "train_win_rate": train_metrics.get("win_rate", 0.0),
                "test_trades": test_metrics.get("total_trades", 0),
                "test_win_rate": test_metrics.get("win_rate", 0.0),
                "test_day_win_rate": test_metrics.get("day_win_rate", 0.0),
                "test_avg_return": test_metrics.get("avg_return", 0.0),
                "test_max_drawdown": test_metrics.get("max_drawdown", 0.0),
                "test_profit_factor": test_metrics.get("profit_factor", 0.0),
            }
        )

    fold_df = pd.DataFrame(fold_rows)
    valid_tests = fold_df[fold_df["test_trades"] >= 3].copy()
    if valid_tests.empty:
        return None, fold_df

    summary = {
        **candidate,
        "valid_folds": int(len(valid_tests)),
        "total_test_trades": int(valid_tests["test_trades"].sum()),
        "avg_test_win_rate": float(valid_tests["test_win_rate"].mean()),
        "median_test_win_rate": float(valid_tests["test_win_rate"].median()),
        "avg_test_day_win_rate": float(valid_tests["test_day_win_rate"].mean()),
        "avg_test_return": float(valid_tests["test_avg_return"].mean()),
        "avg_test_max_drawdown": float(valid_tests["test_max_drawdown"].mean()),
        "avg_test_profit_factor": float(valid_tests["test_profit_factor"].replace(0, pd.NA).dropna().mean() or 0.0),
        "win_rate_std": float(valid_tests["test_win_rate"].std(ddof=0)),
    }
    summary["score"] = (
        summary["avg_test_win_rate"] * 0.45
        + summary["avg_test_day_win_rate"] * 0.20
        + summary["avg_test_return"] * 1.20
        + min(summary["avg_test_profit_factor"], 3.0) * 0.08
        - abs(summary["avg_test_max_drawdown"]) * 0.12
        - summary["win_rate_std"] * 0.08
    )
    return summary, fold_df


def main():
    out_dir = ROOT / "results"
    out_dir.mkdir(parents=True, exist_ok=True)

    config, db, base_params, cost = build_base_objects()
    backtester = MainboardSecondaryLaunchBacktester(
        db=db,
        strategy=MainboardSecondaryLaunchStrategy(base_params),
        cost=cost,
    )

    data = backtester.load_data("20250901", "20260331", warmup_days=90, forward_days=15)
    base_features = backtester.strategy.prepare_features(data["daily"], data["basic"])
    signal_frame = backtester.strategy.build_signal_frame(base_features)

    space = search_space(base_params)
    all_candidates = []
    for values in product(
        space["hold_days"],
        space["drawdown_min"],
        space["drawdown_max"],
        space["vol_shrink_ratio"],
        space["last_limit_up_days_min"],
        space["last_limit_up_days_max"],
        space["limit_up_count_10_max"],
        space["picks_per_day"],
    ):
        hold_days, dd_min, dd_max, vr, dmin, dmax, up_max, ppd = values
        if dd_min >= dd_max:
            continue
        candidate = {
            "hold_days": hold_days,
            "drawdown_min": dd_min,
            "drawdown_max": dd_max,
            "vol_shrink_ratio": vr,
            "last_limit_up_days_min": dmin,
            "last_limit_up_days_max": dmax,
            "limit_up_count_10_max": up_max,
            "picks_per_day": ppd,
        }
        summary, fold_df = evaluate_candidate(
            base_features,
            signal_frame,
            backtester,
            base_params,
            candidate,
        )
        if summary is None:
            continue
        all_candidates.append(summary)

    candidate_df = pd.DataFrame(all_candidates)
    if candidate_df.empty:
        raise RuntimeError("walk-forward 搜索未找到有效参数组合")

    candidate_df = candidate_df.sort_values(
        ["score", "avg_test_win_rate", "avg_test_day_win_rate", "avg_test_return", "total_test_trades"],
        ascending=[False, False, False, False, False],
    ).reset_index(drop=True)
    candidate_df.to_csv(out_dir / "secondary_launch_walkforward_candidates.csv", index=False, encoding="utf-8-sig")

    best = candidate_df.iloc[0].to_dict()
    best_params = {
        "hold_days": int(best["hold_days"]),
        "drawdown_min": float(best["drawdown_min"]),
        "drawdown_max": float(best["drawdown_max"]),
        "vol_shrink_ratio": float(best["vol_shrink_ratio"]),
        "last_limit_up_days_min": int(best["last_limit_up_days_min"]),
        "last_limit_up_days_max": int(best["last_limit_up_days_max"]),
        "limit_up_count_10_min": 1,
        "limit_up_count_10_max": int(best["limit_up_count_10_max"]),
        "picks_per_day": int(best["picks_per_day"]),
    }
    for key, value in best_params.items():
        config.set(f"stock_selection.secondary_launch.{key}", value, save=False)
    config.set("stock_selection.secondary_launch.last_auto_optimized", True, save=False)
    config.set("stock_selection.secondary_launch.last_optimized_from", "20250901", save=False)
    config.set("stock_selection.secondary_launch.last_optimized_to", "20260331", save=True)

    final_param_dict = {**asdict(base_params), **best_params, "max_candidates": max(base_params.max_candidates, best_params["picks_per_day"] * 3)}
    final_param_dict.pop("hold_days", None)
    final_param_obj = StrategyParams(**final_param_dict)
    final_strategy = MainboardSecondaryLaunchStrategy(final_param_obj)
    final_backtester = MainboardSecondaryLaunchBacktester(db, final_strategy, cost)
    final_result = final_backtester.run_backtest("20250901", "20260331", hold_days=best_params["hold_days"])

    summary = {
        "strategy": "mainboard_secondary_launch_walkforward_optimized",
        "data_range": ["20250901", "20260331"],
        "walkforward_folds": get_folds(),
        "best_params": best_params,
        "best_candidate_summary": best,
        "final_full_range_metrics": final_result["metrics"],
    }
    (out_dir / "secondary_launch_walkforward_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    report_lines = [
        "# 二次启动策略 Walk-Forward 优化报告",
        "",
        "## 数据范围",
        "- 全样本：20250901 ~ 20260331",
        "- 验证方式：4 折滚动样本外验证",
        "",
        "## 最优参数",
        f"- hold_days: {best_params['hold_days']}",
        f"- drawdown: {best_params['drawdown_min']:.2%} ~ {best_params['drawdown_max']:.2%}",
        f"- vol_shrink_ratio: {best_params['vol_shrink_ratio']:.2f}",
        f"- last_limit_up_days: {best_params['last_limit_up_days_min']} ~ {best_params['last_limit_up_days_max']}",
        f"- limit_up_count_10: {best_params['limit_up_count_10_min']} ~ {best_params['limit_up_count_10_max']}",
        f"- picks_per_day: {best_params['picks_per_day']}",
        "",
        "## Walk-Forward 汇总",
        f"- 有效样本外折数: {int(best['valid_folds'])}",
        f"- 样本外总交易数: {int(best['total_test_trades'])}",
        f"- 平均样本外胜率: {float(best['avg_test_win_rate']):.2%}",
        f"- 平均样本外日胜率: {float(best['avg_test_day_win_rate']):.2%}",
        f"- 平均样本外单笔收益: {float(best['avg_test_return']):.2%}",
        f"- 平均样本外最大回撤: {float(best['avg_test_max_drawdown']):.2%}",
        "",
        "## 全样本结果",
        f"- 交易数: {final_result['metrics'].get('total_trades', 0)}",
        f"- 胜率: {float(final_result['metrics'].get('win_rate', 0.0)):.2%}",
        f"- 日胜率: {float(final_result['metrics'].get('day_win_rate', 0.0)):.2%}",
        f"- 平均单笔收益: {float(final_result['metrics'].get('avg_return', 0.0)):.2%}",
        f"- 最大回撤: {float(final_result['metrics'].get('max_drawdown', 0.0)):.2%}",
        "",
        "## 输出文件",
        "- `results/secondary_launch_walkforward_candidates.csv`",
        "- `results/secondary_launch_walkforward_summary.json`",
    ]
    (out_dir / "secondary_launch_walkforward_report.md").write_text(
        "\n".join(report_lines) + "\n",
        encoding="utf-8",
    )

    print("Walk-forward optimization done.")
    print("Best params:", best_params)
    print("Best avg OOS win rate:", best["avg_test_win_rate"])


if __name__ == "__main__":
    main()
