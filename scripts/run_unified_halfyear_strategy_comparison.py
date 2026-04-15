# -*- coding: utf-8 -*-
"""
四策略统一口径半年（约 126 个交易日）对比回测。

统一约定（可自行改脚本顶部常量）：
1. 窗口：数据库最新有效数据区间内，取「可回测信号日」的最后 TRADING_DAYS 个交易日（默认 126 ≈ 半年）。
2. Alpha158：信号日 T 日盘后选股 → T+1 开盘价买入 → T+h 日收盘价卖出（h=3、5），与菜单短时回测一致。
3. 突破 / 宽进突破：信号日 T 收盘后观察池 → 仅当 T+1 日突破+量能确认后以触发价买入 → 持有至确认日后第 h 日收盘（ret_t3 / ret_t5）。
4. 二次启动：signal_date 当日开盘价买入（与 MainboardSecondaryLaunchBacktester 一致），持有 hold_days 日后收盘价卖出；含手续费与滑点（CostConfig）。

说明：突破类为「毛收益率（触发价，不含手续费）」；Alpha158 为「毛收益率」；二次启动报表同时给出净收益。可对前两者用 ROUND_TRIP_COST_APPROX 做近似净收益列。

输出：
  data/reports/unified_strategy_comparison_<stamp>.md
  data/reports/unified_strategy_comparison_<stamp>.json
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Tuple

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    sys.stdout.reconfigure(line_buffering=True)
except Exception:
    pass

# 约半年交易日数量（可改）
TRADING_DAYS_DEFAULT = 126
# 向前预留交易日数（保证 T+5 收益可算）
FORWARD_RESERVE = 6
# Alpha158 每日最多推荐只数（与主流程默认一致）
ALPHA158_TOP_N = 5
# 二次启动持有天数（与 config 常见值一致）
SECONDARY_HOLD_DAYS = 5
# 近似单边总成本：佣金双边 + 印花税 + 过户费 + 双边滑点（与 CostConfig 同量级，仅用于对比表「近似净」）
ROUND_TRIP_COST_APPROX = (
    0.0003 + 0.0003 + 0.0005 + 0.00002 + 0.002
)


def _load_qfp():
    path = ROOT / "scripts" / "qlib_full_optimize_pipeline.py"
    spec = importlib.util.spec_from_file_location("qfp_unified", path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def _stats_series(s: pd.Series) -> Dict[str, float]:
    v = pd.to_numeric(s, errors="coerce").dropna()
    if v.empty:
        return {
            "n": 0,
            "win_rate": float("nan"),
            "mean": float("nan"),
            "median": float("nan"),
            "pf": float("nan"),
        }
    n = int(len(v))
    win_rate = float((v > 0).mean())
    mean = float(v.mean())
    median = float(v.median())
    gw = float(v[v > 0].sum())
    gl = float(-v[v < 0].sum())
    pf = gw / gl if gl > 1e-12 else 0.0
    return {"n": n, "win_rate": win_rate, "mean": mean, "median": median, "pf": pf}


def _portfolio_metrics(trades_df: pd.DataFrame, ret_col: str) -> Dict[str, float]:
    from src.modules.breakout_backtest_runner import summarize_ret_column

    return summarize_ret_column(trades_df, ret_col)


def _resolve_signal_window(
    all_dates: List[str], warmup_skip: int, trading_days: int, forward_reserve: int
) -> Tuple[List[str], str, str]:
    """返回 signal_dates 列表及人类可读说明。"""
    if len(all_dates) <= warmup_skip + forward_reserve + 10:
        return [], "", ""
    capable = all_dates[warmup_skip : -forward_reserve]
    if len(capable) < trading_days:
        trading_days = len(capable)
    if trading_days <= 0:
        return [], "", ""
    signal_dates = capable[-trading_days:]
    note = (
        f"取可回测段最后 {len(signal_dates)} 个交易日；"
        f"全库日线自 {all_dates[0]} 至 {all_dates[-1]}"
    )
    return signal_dates, note, f"{signal_dates[0]}_{signal_dates[-1]}"


def main() -> None:
    parser = argparse.ArgumentParser(description="四策略统一口径半年对比回测")
    parser.add_argument(
        "--trading-days",
        type=int,
        default=TRADING_DAYS_DEFAULT,
        help=f"交易日窗口长度，默认 {TRADING_DAYS_DEFAULT}（约半年）",
    )
    args = parser.parse_args()

    from src.core.config import ConfigManager
    from src.core.database import DatabaseManager
    from src.modules.breakout_backtest_runner import run_breakout_backtest_loop
    from src.modules.breakout_strategy import (
        BreakoutStrategy,
        build_breakout_strategy_from_config,
        get_breakout_params_for_backtest,
        resolve_breakout_preset_from_config,
    )
    from src.modules.mainboard_secondary_launch_backtester import (
        CostConfig,
        MainboardSecondaryLaunchBacktester,
    )
    from src.modules.mainboard_secondary_launch_strategy import (
        MainboardSecondaryLaunchStrategy,
        StrategyParams,
    )

    qfp = _load_qfp()

    config = ConfigManager()
    db = DatabaseManager(config)
    all_dates = qfp.load_trade_dates(db)

    if len(all_dates) >= 180:
        warmup_skip = 125
        use_ma120 = True
    elif len(all_dates) >= 75:
        warmup_skip = 65
        use_ma120 = False
    else:
        print("数据库交易日不足，无法回测", flush=True)
        sys.exit(1)

    signal_dates, window_note, window_tag = _resolve_signal_window(
        all_dates, warmup_skip, args.trading_days, FORWARD_RESERVE
    )
    if not signal_dates:
        print("无法构造信号窗口（数据或 warmup 不足）", flush=True)
        sys.exit(1)

    w0, w1 = signal_dates[0], signal_dates[-1]
    print("=" * 72, flush=True)
    print("  四策略统一口径对比回测", flush=True)
    print("=" * 72, flush=True)
    print(f"  信号日窗口: {w0} ~ {w1} （共 {len(signal_dates)} 日）", flush=True)
    print(f"  {window_note}", flush=True)
    print(f"  MA120: {'开启' if use_ma120 else '降级'}", flush=True)

    rep_dir = ROOT / "data" / "reports"
    rep_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    results: Dict[str, Any] = {
        "meta": {
            "generated_at": stamp,
            "signal_start": w0,
            "signal_end": w1,
            "signal_days": len(signal_dates),
            "warmup_skip": warmup_skip,
            "forward_reserve": FORWARD_RESERVE,
            "alpha158_top_n": ALPHA158_TOP_N,
            "secondary_hold_days": SECONDARY_HOLD_DAYS,
            "round_trip_cost_approx": ROUND_TRIP_COST_APPROX,
        },
        "strategies": {},
    }

    # ---------- 1. Alpha158 ----------
    alpha_cfg: Dict[str, Any] = {
        "stock_selection.strategy_profile": "alpha158",
        "stock_selection.save_factor_values": False,
        "stock_selection.min_score": 0.0,
    }
    # 保证 T+5 可定价：截掉窗口末尾
    alpha_signal_dates = qfp.get_signal_dates(all_dates, w0, w1, 5)
    print(f"\n  [1/4] Alpha158：有效信号日 {len(alpha_signal_dates)} 日（含定价预留）...", flush=True)
    rec_df = qfp.run_selection_for_dates(
        alpha_signal_dates,
        db,
        config_overrides=alpha_cfg,
        top_n=ALPHA158_TOP_N,
    )
    alpha_h3 = qfp.evaluate_recommendations(rec_df, db, all_dates, 3)
    alpha_h5 = qfp.evaluate_recommendations(rec_df, db, all_dates, 5)
    results["strategies"]["alpha158"] = {
        "label": "Alpha158 IC加权（本地手算因子）",
        "rec_count": int(len(rec_df)),
        "horizon_3": asdict(alpha_h3) if alpha_h3 else {},
        "horizon_5": asdict(alpha_h5) if alpha_h5 else {},
    }

    # ---------- 2. 突破（config 预设）----------
    preset = resolve_breakout_preset_from_config(config)
    strategy_std = build_breakout_strategy_from_config(db, config)
    max_d = all_dates[-1]
    print(f"\n  [2/4] 突破策略（预设 {preset}）...", flush=True)
    raw_daily, raw_basic = strategy_std._load_data(max_d)
    features_std = strategy_std._compute_features(raw_daily, raw_basic, max_d)
    df_br, funnel_br, gate_br = run_breakout_backtest_loop(
        strategy_std, features_std, all_dates, signal_dates, use_ma120, progress_every=0
    )
    br_t3 = _stats_series(df_br["ret_t3"]) if not df_br.empty and "ret_t3" in df_br else _stats_series(pd.Series(dtype=float))
    br_t5 = _stats_series(df_br["ret_t5"]) if not df_br.empty and "ret_t5" in df_br else _stats_series(pd.Series(dtype=float))
    br_port3 = _portfolio_metrics(df_br, "ret_t3")
    br_port5 = _portfolio_metrics(df_br, "ret_t5")
    results["strategies"]["breakout"] = {
        "label": f"突破策略（{preset}）",
        "preset": preset,
        "trades": int(len(df_br)),
        "gate": gate_br,
        "ret_t3": br_t3,
        "ret_t5": br_t5,
        "portfolio_ret_t3": br_port3,
        "portfolio_ret_t5": br_port5,
    }

    # ---------- 3. 宽进突破 ----------
    print(f"\n  [3/4] 宽进突破（wide_pool_strict_entry_v2）...", flush=True)
    params_wide = get_breakout_params_for_backtest("wide_pool_strict_entry_v2", use_ma120)
    strategy_wide = BreakoutStrategy(db=db, params=params_wide)
    raw_w, basic_w = strategy_wide._load_data(max_d)
    features_wide = strategy_wide._compute_features(raw_w, basic_w, max_d)
    df_wb, funnel_wb, gate_wb = run_breakout_backtest_loop(
        strategy_wide, features_wide, all_dates, signal_dates, use_ma120, progress_every=0
    )
    wb_t3 = _stats_series(df_wb["ret_t3"]) if not df_wb.empty and "ret_t3" in df_wb else _stats_series(pd.Series(dtype=float))
    wb_t5 = _stats_series(df_wb["ret_t5"]) if not df_wb.empty and "ret_t5" in df_wb else _stats_series(pd.Series(dtype=float))
    wb_port3 = _portfolio_metrics(df_wb, "ret_t3")
    wb_port5 = _portfolio_metrics(df_wb, "ret_t5")
    results["strategies"]["wide_breakout"] = {
        "label": "宽进突破（wide_pool_strict_entry_v2）",
        "trades": int(len(df_wb)),
        "gate": gate_wb,
        "ret_t3": wb_t3,
        "ret_t5": wb_t5,
        "portfolio_ret_t3": wb_port3,
        "portfolio_ret_t5": wb_port5,
    }

    # ---------- 4. 二次启动 ----------
    print(f"\n  [4/4] 二次启动（持有 {SECONDARY_HOLD_DAYS} 日，含成本）...", flush=True)
    sec_params = StrategyParams()
    sec_strat = MainboardSecondaryLaunchStrategy(sec_params)
    sec_bt = MainboardSecondaryLaunchBacktester(db, sec_strat, cost=CostConfig())
    sec_out = sec_bt.run_backtest(w0, w1, hold_days=SECONDARY_HOLD_DAYS)
    trades_sec = sec_out.get("trades") if isinstance(sec_out, dict) else pd.DataFrame()
    metrics_sec = sec_out.get("metrics", {}) if isinstance(sec_out, dict) else {}
    if isinstance(trades_sec, pd.DataFrame) and not trades_sec.empty and "gross_ret" in trades_sec.columns:
        g = _stats_series(trades_sec["gross_ret"])
    else:
        g = _stats_series(pd.Series(dtype=float))
    results["strategies"]["secondary_launch"] = {
        "label": "主板二次启动（日线，净收益为主）",
        "metrics": metrics_sec,
        "gross_stats": g,
        "trade_rows": int(len(trades_sec)) if hasattr(trades_sec, "__len__") else 0,
    }

    # ---------- 写 JSON ----------
    json_path = rep_dir / f"unified_strategy_comparison_{stamp}.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2, default=str)

    # ---------- 写 Markdown ----------
    lines: List[str] = []
    lines.append("# 四策略统一口径对比回测\n\n")
    lines.append(f"- **生成时间**：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
    lines.append(f"- **信号日窗口**：`{w0}` ~ `{w1}`（共 **{len(signal_dates)}** 个交易日）\n")
    lines.append(f"- **说明**：{window_note}\n")
    lines.append(
        f"- **对比持有期**：Alpha158 / 突破类 使用 **T+3、T+5**（定义见脚本头注释）；"
        f"二次启动为信号日开盘入、持有 **{SECONDARY_HOLD_DAYS}** 日收盘出（含费）。\n"
    )
    lines.append(
        f"- **近似综合成本**（用于毛→净粗算）：全回合（买+卖含费与滑点）约 `{ROUND_TRIP_COST_APPROX:.4f}`\n\n"
    )

    lines.append("## 汇总表（毛收益，除二次启动净收益列外）\n\n")
    lines.append("| 策略 | 样本数/笔数 | T+3 胜率 | T+3 均值 | T+5 胜率 | T+5 均值 | 备注 |\n")
    lines.append("| --- | ---: | ---: | ---: | ---: | ---: | --- |\n")

    a3n = results["strategies"]["alpha158"]["horizon_3"].get("sample_count", 0)
    a3w = results["strategies"]["alpha158"]["horizon_3"].get("win_rate", float("nan"))
    a3m = results["strategies"]["alpha158"]["horizon_3"].get("mean_return", float("nan"))
    a5n = results["strategies"]["alpha158"]["horizon_5"].get("sample_count", 0)
    a5w = results["strategies"]["alpha158"]["horizon_5"].get("win_rate", float("nan"))
    a5m = results["strategies"]["alpha158"]["horizon_5"].get("mean_return", float("nan"))
    lines.append(
        f"| Alpha158 | {a3n} | {a3w:.2%} | {a3m:.4%} | {a5w:.2%} | {a5m:.4%} | T+1开→T+h收；样本 h3={a3n} / h5={a5n} |\n"
    )

    b3 = results["strategies"]["breakout"]["ret_t3"]
    b5 = results["strategies"]["breakout"]["ret_t5"]
    lines.append(
        f"| 突破 | {b3['n']} | {b3['win_rate']:.2%} | {b3['mean']:.4%} | {b5['win_rate']:.2%} | {b5['mean']:.4%} | 触发价；预设 {preset} |\n"
    )

    w3 = results["strategies"]["wide_breakout"]["ret_t3"]
    w5 = results["strategies"]["wide_breakout"]["ret_t5"]
    lines.append(
        f"| 宽进突破 | {w3['n']} | {w3['win_rate']:.2%} | {w3['mean']:.4%} | {w5['win_rate']:.2%} | {w5['mean']:.4%} | 触发价；wide_pool_strict_entry_v2 |\n"
    )

    net_wr = metrics_sec.get("win_rate", float("nan"))
    smean = float(metrics_sec.get("avg_return", float("nan")))
    if trades_sec is not None and hasattr(trades_sec, "__len__") and len(trades_sec) > 0:
        nr = pd.to_numeric(trades_sec["net_ret"], errors="coerce").dropna()
        if not nr.empty:
            smean = float(nr.mean())
    lines.append(
        f"| 二次启动 | {results['strategies']['secondary_launch']['trade_rows']} | — | — | — | {smean:.4%} | **净**单笔收益均值；胜率 {net_wr:.2%} |\n"
    )

    lines.append("\n## 等权组合（按 signal_date 日均收益复利，仅突破类）\n\n")
    lines.append("| 策略 | 组合 T+3 累计 | T+3 最大回撤 | T+3 日夏普 | 组合 T+5 累计 | T+5 最大回撤 | T+5 日夏普 |\n")
    lines.append("| --- | ---: | ---: | ---: | ---: | ---: | ---: |\n")
    p3 = results["strategies"]["breakout"]["portfolio_ret_t3"]
    p5 = results["strategies"]["breakout"]["portfolio_ret_t5"]
    lines.append(
        f"| 突破 | {p3.get('port_total_ret', float('nan')):.4%} | {p3.get('port_mdd', float('nan')):.4%} | {p3.get('port_sharpe', float('nan')):.2f} | "
        f"{p5.get('port_total_ret', float('nan')):.4%} | {p5.get('port_mdd', float('nan')):.4%} | {p5.get('port_sharpe', float('nan')):.2f} |\n"
    )
    q3 = results["strategies"]["wide_breakout"]["portfolio_ret_t3"]
    q5 = results["strategies"]["wide_breakout"]["portfolio_ret_t5"]
    lines.append(
        f"| 宽进突破 | {q3.get('port_total_ret', float('nan')):.4%} | {q3.get('port_mdd', float('nan')):.4%} | {q3.get('port_sharpe', float('nan')):.2f} | "
        f"{q5.get('port_total_ret', float('nan')):.4%} | {q5.get('port_mdd', float('nan')):.4%} | {q5.get('port_sharpe', float('nan')):.2f} |\n"
    )

    lines.append("\n## JSON\n\n")
    lines.append(f"- `{json_path.name}`\n")

    md_path = rep_dir / f"unified_strategy_comparison_{stamp}.md"
    with open(md_path, "w", encoding="utf-8") as f:
        f.write("".join(lines))

    print("\n" + "=" * 72, flush=True)
    print(f"  完成。报告：\n    {md_path}\n    {json_path}", flush=True)
    print("=" * 72, flush=True)


if __name__ == "__main__":
    main()
