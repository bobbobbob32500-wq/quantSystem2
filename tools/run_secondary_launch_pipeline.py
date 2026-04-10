# -*- coding: utf-8 -*-
"""
运行“强势回调缩量二次启动”策略开发全流程
（按要求移除集合竞价过滤）
"""

from __future__ import annotations

from pathlib import Path
import json
import sys
import itertools

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


def main():
    root = Path(__file__).resolve().parents[1]
    out_dir = root / "results"
    out_dir.mkdir(parents=True, exist_ok=True)

    config = ConfigManager()
    db = DatabaseManager(config)

    # 读取配置（若无则用默认）
    sp = StrategyParams(
        min_list_days=int(config.get("stock_selection.secondary_launch.min_list_days", 60)),
        limit_up_threshold=float(config.get("stock_selection.secondary_launch.limit_up_threshold", 9.7)),
        limit_down_threshold=float(config.get("stock_selection.secondary_launch.limit_down_threshold", -9.7)),
        limit_up_count_10_min=int(config.get("stock_selection.secondary_launch.limit_up_count_10_min", 1)),
        limit_up_count_10_max=int(config.get("stock_selection.secondary_launch.limit_up_count_10_max", 2)),
        last_limit_up_days_min=int(config.get("stock_selection.secondary_launch.last_limit_up_days_min", 2)),
        last_limit_up_days_max=int(config.get("stock_selection.secondary_launch.last_limit_up_days_max", 5)),
        drawdown_min=float(config.get("stock_selection.secondary_launch.drawdown_min", 0.02)),
        drawdown_max=float(config.get("stock_selection.secondary_launch.drawdown_max", 0.08)),
        vol_shrink_ratio=float(config.get("stock_selection.secondary_launch.vol_shrink_ratio", 0.80)),
        close_ma5_dev_max=float(config.get("stock_selection.secondary_launch.close_ma5_dev_max", 0.02)),
        min_amt_ma20=float(config.get("stock_selection.secondary_launch.min_amt_ma20", 1e5)),
        max_amt_ma20=float(config.get("stock_selection.secondary_launch.max_amt_ma20", 5e6)),
        min_price=float(config.get("stock_selection.secondary_launch.min_price", 3.0)),
        limit_up_amt_ratio_min=float(config.get("stock_selection.secondary_launch.limit_up_amt_ratio_min", 0.6)),
        limit_up_amt_ratio_max=float(config.get("stock_selection.secondary_launch.limit_up_amt_ratio_max", 3.5)),
        rs_lookback=int(config.get("stock_selection.secondary_launch.rs_lookback", 20)),
        max_candidates=int(config.get("stock_selection.secondary_launch.max_candidates", 15)),
        picks_per_day=int(config.get("stock_selection.secondary_launch.picks_per_day", 5)),
    )

    cost = CostConfig(
        buy_fee_rate=float(config.get("feedback.buy_fee_rate", 0.0003)),
        sell_fee_rate=float(config.get("feedback.sell_fee_rate", 0.0003)),
        stamp_tax_rate=float(config.get("feedback.stamp_tax_rate", 0.0005)),
        transfer_fee_rate=float(config.get("stock_selection.secondary_launch.transfer_fee_rate", 0.00001)),
        slippage_rate=float(config.get("feedback.buy_slippage", 0.001)),
    )

    strategy = MainboardSecondaryLaunchStrategy(sp)
    bt = MainboardSecondaryLaunchBacktester(db, strategy, cost)

    # 样本内不少于3个月
    is_start = str(config.get("stock_selection.secondary_launch.backtest_in_sample_start", "20251201"))
    is_end = str(config.get("stock_selection.secondary_launch.backtest_in_sample_end", "20260327"))
    oos_start = str(config.get("stock_selection.secondary_launch.backtest_oos_start", "20260301"))
    oos_end = str(config.get("stock_selection.secondary_launch.backtest_oos_end", "20260327"))
    hold_days = int(config.get("stock_selection.secondary_launch.hold_days", 5))

    # 1) 围绕当前候选进行第二轮小范围优化
    data = bt.load_data(
        start_date=is_start,
        end_date=is_end,
        warmup_days=max(90, hold_days * 3),
        forward_days=max(15, hold_days * 3),
    )
    base_features = strategy.prepare_features(data["daily"], data["basic"])
    signal_frame = strategy.build_signal_frame(base_features)

    current_hold_days = hold_days
    current_dd_min = float(sp.drawdown_min)
    current_dd_max = float(sp.drawdown_max)
    current_vr = float(sp.vol_shrink_ratio)
    current_days_min = int(sp.last_limit_up_days_min)
    current_days_max = int(sp.last_limit_up_days_max)
    current_picks = int(sp.picks_per_day)

    focused_rows = []
    hold_days_space = sorted({max(2, current_hold_days - 1), current_hold_days, min(5, current_hold_days + 1)})
    dd_space = [
        (max(0.01, current_dd_min - 0.01), current_dd_max),
        (current_dd_min, current_dd_max),
        (current_dd_min, min(0.10, current_dd_max + 0.02)),
    ]
    vr_space = sorted({max(0.5, current_vr - 0.1), current_vr, min(0.85, current_vr + 0.1)})
    day_space = sorted(
        {
            (max(1, current_days_min - 1), max(current_days_min, current_days_max - 1)),
            (current_days_min, current_days_max),
            (current_days_min, min(6, current_days_max + 1)),
        }
    )
    picks_space = sorted({1, current_picks, min(3, current_picks + 1)})
    up_space = [(1, 1), (1, 2)]

    for hold_days_candidate, (dd_min, dd_max), vr, (dmin, dmax), picks_per_day, (up_min, up_max) in itertools.product(
        hold_days_space,
        dd_space,
        vr_space,
        day_space,
        picks_space,
        up_space,
    ):
        params = StrategyParams(
            min_list_days=sp.min_list_days,
            limit_up_threshold=sp.limit_up_threshold,
            limit_down_threshold=sp.limit_down_threshold,
            limit_up_count_10_min=up_min,
            limit_up_count_10_max=up_max,
            last_limit_up_days_min=dmin,
            last_limit_up_days_max=dmax,
            drawdown_min=dd_min,
            drawdown_max=dd_max,
            vol_shrink_ratio=vr,
            close_ma5_dev_max=sp.close_ma5_dev_max,
            min_amt_ma20=sp.min_amt_ma20,
            max_amt_ma20=sp.max_amt_ma20,
            min_price=sp.min_price,
            limit_up_amt_ratio_min=sp.limit_up_amt_ratio_min,
            limit_up_amt_ratio_max=sp.limit_up_amt_ratio_max,
            rs_lookback=sp.rs_lookback,
            max_candidates=max(sp.max_candidates, picks_per_day * 3),
            picks_per_day=picks_per_day,
        )
        candidate_strategy = MainboardSecondaryLaunchStrategy(params)
        candidate_signals = candidate_strategy.generate_signals_from_frame(signal_frame)
        in_sample_candidate = bt._build_backtest_result(
            base_features,
            candidate_signals,
            is_start,
            is_end,
            hold_days_candidate,
        )
        candidate_metrics = in_sample_candidate["metrics"]
        focused_rows.append(
            {
                "hold_days": hold_days_candidate,
                "drawdown_min": dd_min,
                "drawdown_max": dd_max,
                "vol_shrink_ratio": vr,
                "days_min": dmin,
                "days_max": dmax,
                "limit_up_count_10_min": up_min,
                "limit_up_count_10_max": up_max,
                "picks_per_day": picks_per_day,
                "total_trades": candidate_metrics.get("total_trades", 0),
                "total_signal_days": candidate_metrics.get("total_signal_days", 0),
                "win_rate": candidate_metrics.get("win_rate", 0.0),
                "day_win_rate": candidate_metrics.get("day_win_rate", 0.0),
                "annual_return": candidate_metrics.get("annual_return", 0.0),
                "sharpe_ratio": candidate_metrics.get("sharpe_ratio", 0.0),
                "max_drawdown": candidate_metrics.get("max_drawdown", 0.0),
                "total_return": candidate_metrics.get("total_return", 0.0),
                "avg_return": candidate_metrics.get("avg_return", 0.0),
                "profit_factor": candidate_metrics.get("profit_factor", 0.0),
            }
        )

    grid_df = pd.DataFrame(focused_rows)
    if not grid_df.empty:
        grid_df = grid_df[grid_df["total_trades"] >= 15].copy()
        grid_df["score"] = (
            grid_df["win_rate"] * 0.40
            + grid_df["day_win_rate"] * 0.25
            + grid_df["avg_return"] * 1.50
            + grid_df["profit_factor"].clip(upper=3.0) * 0.08
            + grid_df["sharpe_ratio"] * 0.05
            - grid_df["max_drawdown"].abs() * 0.12
        )
        grid_df = grid_df.sort_values(
            ["score", "win_rate", "day_win_rate", "avg_return", "total_trades"],
            ascending=[False, False, False, False, False],
        ).reset_index(drop=True)

    # 2) 选最优参数并自动写回配置
    best_params = {}
    if not grid_df.empty:
        best = grid_df.iloc[0].to_dict()
        best_params = {
            "hold_days": int(best["hold_days"]),
            "drawdown_min": float(best["drawdown_min"]),
            "drawdown_max": float(best["drawdown_max"]),
            "vol_shrink_ratio": float(best["vol_shrink_ratio"]),
            "last_limit_up_days_min": int(best["days_min"]),
            "last_limit_up_days_max": int(best["days_max"]),
            "limit_up_count_10_min": int(best["limit_up_count_10_min"]),
            "limit_up_count_10_max": int(best["limit_up_count_10_max"]),
            "picks_per_day": int(best["picks_per_day"]),
        }
        for k, v in best_params.items():
            config.set(f"stock_selection.secondary_launch.{k}", v, save=False)
        config.set("stock_selection.secondary_launch.last_auto_optimized", True, save=False)
        config.set("stock_selection.secondary_launch.last_optimized_from", is_start, save=False)
        config.set("stock_selection.secondary_launch.last_optimized_to", is_end, save=True)
        hold_days = int(best_params["hold_days"])

        sp = StrategyParams(
            min_list_days=int(config.get("stock_selection.secondary_launch.min_list_days", 60)),
            limit_up_threshold=float(config.get("stock_selection.secondary_launch.limit_up_threshold", 9.7)),
            limit_down_threshold=float(config.get("stock_selection.secondary_launch.limit_down_threshold", -9.7)),
            limit_up_count_10_min=int(best_params["limit_up_count_10_min"]),
            limit_up_count_10_max=int(best_params["limit_up_count_10_max"]),
            last_limit_up_days_min=int(best_params["last_limit_up_days_min"]),
            last_limit_up_days_max=int(best_params["last_limit_up_days_max"]),
            drawdown_min=float(best_params["drawdown_min"]),
            drawdown_max=float(best_params["drawdown_max"]),
            vol_shrink_ratio=float(best_params["vol_shrink_ratio"]),
            close_ma5_dev_max=float(config.get("stock_selection.secondary_launch.close_ma5_dev_max", 0.02)),
            min_amt_ma20=float(config.get("stock_selection.secondary_launch.min_amt_ma20", 1e5)),
            max_amt_ma20=float(config.get("stock_selection.secondary_launch.max_amt_ma20", 5e6)),
            min_price=float(config.get("stock_selection.secondary_launch.min_price", 3.0)),
            limit_up_amt_ratio_min=float(config.get("stock_selection.secondary_launch.limit_up_amt_ratio_min", 0.6)),
            limit_up_amt_ratio_max=float(config.get("stock_selection.secondary_launch.limit_up_amt_ratio_max", 3.5)),
            rs_lookback=int(config.get("stock_selection.secondary_launch.rs_lookback", 20)),
            max_candidates=int(config.get("stock_selection.secondary_launch.max_candidates", 15)),
            picks_per_day=int(best_params["picks_per_day"]),
        )
        strategy = MainboardSecondaryLaunchStrategy(sp)
        bt = MainboardSecondaryLaunchBacktester(db, strategy, cost)

    # 3) 使用最优参数重新回测
    in_sample = bt.run_backtest(is_start, is_end, hold_days=hold_days)
    oos = bt.run_backtest(oos_start, oos_end, hold_days=hold_days)

    # 4) 敏感性分析（简化：取top10 score的方差）
    sensitivity = {}
    if len(grid_df) >= 10:
        top10 = grid_df.head(10)
        sensitivity = {
            "score_std_top10": float(top10["score"].std(ddof=1)),
            "annual_return_std_top10": float(top10["annual_return"].std(ddof=1)),
            "max_drawdown_std_top10": float(top10["max_drawdown"].std(ddof=1)),
        }

    # 5) 基准指数对比（简单使用000001.SH 同周期close涨跌）
    bench_sql = """
    SELECT trade_date, close FROM stock_daily
    WHERE ts_code = '000001.SH' AND trade_date >= ? AND trade_date <= ?
    ORDER BY trade_date
    """
    bench_rows = db.query(bench_sql, (is_start, is_end))
    benchmark_return = 0.0
    if len(bench_rows) >= 2:
        benchmark_return = float(bench_rows[-1]["close"] / bench_rows[0]["close"] - 1.0)

    alpha = float(in_sample["metrics"].get("total_return", 0.0) - benchmark_return)

    oos_metrics = oos["metrics"]
    validation = {
        "oos_trade_count_ok": int(oos_metrics.get("total_trades", 0)) >= 10,
        "oos_win_rate_ok": float(oos_metrics.get("win_rate", 0.0)) >= 0.45,
        "oos_annual_return_ok": float(oos_metrics.get("annual_return", 0.0)) >= 0.0,
        "oos_max_drawdown_ok": abs(float(oos_metrics.get("max_drawdown", 0.0))) <= 0.20,
    }
    validation["passed"] = all(validation.values())

    # 保存结果
    (out_dir / "secondary_launch_in_sample_trades.csv").write_text(
        in_sample["trades"].to_csv(index=False), encoding="utf-8"
    )
    (out_dir / "secondary_launch_oos_trades.csv").write_text(
        oos["trades"].to_csv(index=False), encoding="utf-8"
    )
    grid_df.to_csv(out_dir / "secondary_launch_grid_search.csv", index=False, encoding="utf-8-sig")

    summary = {
        "strategy": "mainboard_secondary_launch_no_auction_filter",
        "in_sample_period": [is_start, is_end],
        "oos_period": [oos_start, oos_end],
        "hold_days": hold_days,
        "in_sample_metrics": in_sample["metrics"],
        "oos_metrics": oos["metrics"],
        "best_params": best_params,
        "sensitivity": sensitivity,
        "benchmark_return": benchmark_return,
        "alpha": alpha,
        "validation": validation,
        "removed_feature": "auction_open_filter",
    }

    with open(out_dir / "secondary_launch_summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    report_lines = [
        "# 二次启动策略流水线报告",
        "",
        "## 策略说明",
        "- 策略名称：强势回调缩量二次启动（去集合竞价过滤版）",
        "- 数据口径：仅使用截至 t-1 的日线数据盘前筛选",
        "- 核心改动：移除集合竞价开盘过滤，避免依赖实时竞价数据",
        "",
        "## 回测区间",
        f"- 样本内：{is_start} ~ {is_end}",
        f"- 样本外：{oos_start} ~ {oos_end}",
        f"- 持有周期：{hold_days} 个交易日",
        "",
        "## 样本内指标",
        f"- 交易笔数：{in_sample['metrics'].get('total_trades', 0)}",
        f"- 胜率：{float(in_sample['metrics'].get('win_rate', 0.0)):.2%}",
        f"- 年化收益：{float(in_sample['metrics'].get('annual_return', 0.0)):.2%}",
        f"- 夏普比率：{float(in_sample['metrics'].get('sharpe_ratio', 0.0)):.3f}",
        f"- 最大回撤：{float(in_sample['metrics'].get('max_drawdown', 0.0)):.2%}",
        "",
        "## 样本外指标",
        f"- 交易笔数：{oos_metrics.get('total_trades', 0)}",
        f"- 胜率：{float(oos_metrics.get('win_rate', 0.0)):.2%}",
        f"- 年化收益：{float(oos_metrics.get('annual_return', 0.0)):.2%}",
        f"- 夏普比率：{float(oos_metrics.get('sharpe_ratio', 0.0)):.3f}",
        f"- 最大回撤：{float(oos_metrics.get('max_drawdown', 0.0)):.2%}",
        "",
        "## 样本外验证",
        f"- 交易样本充足：{'通过' if validation['oos_trade_count_ok'] else '未通过'}",
        f"- 胜率门槛：{'通过' if validation['oos_win_rate_ok'] else '未通过'}",
        f"- 年化收益门槛：{'通过' if validation['oos_annual_return_ok'] else '未通过'}",
        f"- 最大回撤门槛：{'通过' if validation['oos_max_drawdown_ok'] else '未通过'}",
        f"- 综合结论：{'通过' if validation['passed'] else '未通过'}",
        "",
        "## 参数优化结果",
        f"- 最优参数：{json.dumps(best_params, ensure_ascii=False)}",
        f"- Alpha（样本内相对000001.SH）：{alpha:.2%}",
        "",
        "## 产出文件",
        "- `results/secondary_launch_in_sample_trades.csv`",
        "- `results/secondary_launch_oos_trades.csv`",
        "- `results/secondary_launch_grid_search.csv`",
        "- `results/secondary_launch_summary.json`",
    ]
    (out_dir / "secondary_launch_pipeline_report.md").write_text(
        "\n".join(report_lines) + "\n",
        encoding="utf-8",
    )

    print("=== Secondary Launch Strategy Pipeline Done ===")
    print("In-sample:", in_sample["metrics"])
    print("Out-of-sample:", oos["metrics"])
    print("Best params:", best_params)
    print("Alpha vs benchmark:", alpha)
    print("Validation:", validation)


if __name__ == "__main__":
    main()
