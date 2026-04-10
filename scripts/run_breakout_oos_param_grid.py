# -*- coding: utf-8 -*-
"""
突破策略：样本内 / 样本外（时间切分）粗网格参数搜索。

思路（与此前讨论一致）：
  - 因子只算一遍；对每个参数组合仅重跑选股→确认循环。
  - 按时间将 signal_dates 切成训练段与 OOS 段，避免全样本过拟合。
  - 输出 CSV，便于按 OOS 指标人工筛选；默认按 OOS 盈亏比×样本惩罚 排序。

用法:
  python scripts/run_breakout_oos_param_grid.py
  python scripts/run_breakout_oos_param_grid.py --quick
  python scripts/run_breakout_oos_param_grid.py --train-ratio 0.65 --min-oos-trades 12
  python scripts/run_breakout_oos_param_grid.py --split-date 20260101
"""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import replace
from datetime import datetime
from itertools import product
from typing import Any, Dict, List, Sequence, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    sys.stdout.reconfigure(line_buffering=True)
except Exception:
    pass

import pandas as pd

from src.core.config import ConfigManager
from src.core.database import DatabaseManager
from src.modules.breakout_backtest_runner import run_breakout_backtest_loop, summarize_t1_metrics
from src.modules.breakout_strategy import BreakoutParams, BreakoutStrategy


def _base_params(use_ma120: bool) -> BreakoutParams:
    p = BreakoutParams()
    p.min_amt_ma20 = 8e4
    p.rs_quantile_max = 0.97
    p.min_signal_score = 60.0
    p.top_k = 15
    p.volume_confirm_ratio = 1.2
    p.volume_normal_ratio = 1.0
    if not use_ma120:
        p.atr_quantile_max = 0.50
        p.box_max_range = 0.08
    return p


def _split_dates(
    signal_dates: List[str],
    train_ratio: float | None,
    split_date: str | None,
) -> Tuple[List[str], List[str]]:
    if split_date:
        train = [d for d in signal_dates if str(d) < str(split_date)]
        oos = [d for d in signal_dates if str(d) >= str(split_date)]
        return train, oos
    n = len(signal_dates)
    k = int(n * float(train_ratio))
    k = max(20, min(n - 15, k))
    return signal_dates[:k], signal_dates[k:]


def _grid_specs(quick: bool, use_ma120: bool) -> Dict[str, Sequence[Any]]:
    if quick:
        d: Dict[str, Sequence[Any]] = {
            "rs_quantile_min": (0.78, 0.80),
            "volume_confirm_ratio": (1.05, 1.2),
            "min_signal_score": (56.0, 60.0),
            "top_k": (15, 20),
        }
    else:
        d = {
            "rs_quantile_min": (0.76, 0.78, 0.80),
            "volume_confirm_ratio": (1.1, 1.2),
            "min_signal_score": (56.0, 58.0, 60.0),
            "top_k": (15, 20),
            "atr_quantile_max": (0.50, 0.55),
            "box_max_range": (0.08, 0.095),
        }
    if not use_ma120:
        d.pop("atr_quantile_max", None)
        d.pop("box_max_range", None)
    return d


def _oos_score(m: Dict[str, float], min_trades: float) -> float:
    """OOS 排序用：盈亏比 × sqrt(笔数门槛)，笔数不足强惩罚。"""
    n = m.get("n_trades", 0.0)
    pf = m.get("pf", 0.0) or 0.0
    if n < min_trades:
        return pf * (n / max(min_trades, 1.0)) * 0.5
    return pf * (n**0.5)


def main() -> None:
    parser = argparse.ArgumentParser(description="突破策略 OOS 粗网格")
    parser.add_argument("--train-ratio", type=float, default=0.72, help="训练段占信号日比例（与 split-date 二选一）")
    parser.add_argument(
        "--split-date",
        type=str,
        default=None,
        help="训练段 signal_date < 该日(YYYYMMDD)，OOS 为之后",
    )
    parser.add_argument("--quick", action="store_true", help="缩小网格（约 16 组）")
    parser.add_argument("--min-oos-trades", type=float, default=10.0, help="排序时 OOS 最低期望笔数")
    args = parser.parse_args()

    print("=" * 70, flush=True)
    print("  突破策略 — 样本外参数粗网格", flush=True)
    print("=" * 70, flush=True)

    config = ConfigManager()
    db = DatabaseManager(config)
    all_dates = [
        r["trade_date"]
        for r in db.query("SELECT DISTINCT trade_date FROM stock_daily ORDER BY trade_date ASC")
    ]
    if len(all_dates) >= 180:
        warmup_skip = 125
        use_ma120 = True
    elif len(all_dates) >= 75:
        warmup_skip = 65
        use_ma120 = False
    else:
        print("数据不足")
        return
    if len(all_dates) <= warmup_skip + 10:
        print("warmup 后数据不足")
        return

    max_d = all_dates[-1]
    signal_dates = all_dates[warmup_skip : len(all_dates) - 3]
    train_dates, oos_dates = _split_dates(signal_dates, args.train_ratio, args.split_date)
    if len(train_dates) < 25 or len(oos_dates) < 10:
        print(f"切分过短: 训练 {len(train_dates)} / OOS {len(oos_dates)}，请调整比例或 split-date")
        return

    print(f"\n  信号日总数 {len(signal_dates)} | 训练 {len(train_dates)} | OOS {len(oos_dates)}", flush=True)
    print(f"  训练区间 {train_dates[0]} ~ {train_dates[-1]} | OOS {oos_dates[0]} ~ {oos_dates[-1]}", flush=True)

    base_p = _base_params(use_ma120)
    strat0 = BreakoutStrategy(db=db, params=base_p)
    print("\n  [1/2] 计算全量因子（仅一次）...", flush=True)
    raw_daily, raw_basic = strat0._load_data(max_d)
    if raw_daily.empty:
        print("日线为空")
        return
    features = strat0._compute_features(raw_daily, raw_basic, max_d)
    print(f"  因子行数: {len(features)}", flush=True)

    specs = _grid_specs(args.quick, use_ma120)
    keys = list(specs.keys())
    combos = list(product(*(specs[k] for k in keys)))
    print(f"\n  [2/2] 网格组合数: {len(combos)}（quick={args.quick}）", flush=True)

    rows: List[Dict[str, Any]] = []
    for idx, values in enumerate(combos):
        kw = dict(zip(keys, values))
        p = replace(base_p, **kw)
        strategy = BreakoutStrategy(db=db, params=p)

        df_tr, _, _ = run_breakout_backtest_loop(
            strategy, features, all_dates, train_dates, use_ma120, progress_every=0
        )
        df_os, _, _ = run_breakout_backtest_loop(
            strategy, features, all_dates, oos_dates, use_ma120, progress_every=0
        )
        mt = summarize_t1_metrics(df_tr)
        mo = summarize_t1_metrics(df_os)
        row = {**kw}
        row["train_n"] = mt["n_trades"]
        row["train_mean"] = mt["mean_ret"]
        row["train_pf"] = mt["pf"]
        row["train_port_ret"] = mt["port_total_ret"]
        row["train_mdd"] = mt["port_mdd"]
        row["train_sharpe"] = mt["port_sharpe"]
        row["oos_n"] = mo["n_trades"]
        row["oos_mean"] = mo["mean_ret"]
        row["oos_pf"] = mo["pf"]
        row["oos_port_ret"] = mo["port_total_ret"]
        row["oos_mdd"] = mo["port_mdd"]
        row["oos_sharpe"] = mo["port_sharpe"]
        row["rank_score"] = _oos_score(mo, args.min_oos_trades)
        rows.append(row)

        if (idx + 1) % max(1, len(combos) // 8) == 0 or idx == len(combos) - 1:
            print(f"  进度 {idx+1}/{len(combos)}", flush=True)

    out_df = pd.DataFrame(rows)
    out_df = out_df.sort_values("rank_score", ascending=False).reset_index(drop=True)

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    rep_dir = os.path.join(root, "data", "reports")
    os.makedirs(rep_dir, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_path = os.path.join(rep_dir, f"breakout_oos_param_grid_{stamp}.csv")
    out_df.to_csv(csv_path, index=False, encoding="utf-8-sig")
    latest = os.path.join(rep_dir, "breakout_oos_param_grid_latest.csv")
    out_df.to_csv(latest, index=False, encoding="utf-8-sig")

    md_path = os.path.join(rep_dir, "breakout_oos_param_grid_summary.md")
    best = out_df.iloc[0].to_dict() if not out_df.empty else {}
    lines = [
        "# 突破策略 — 样本外粗网格摘要\n\n",
        f"- 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n",
        f"- 训练段: {len(train_dates)} 信号日 | OOS: {len(oos_dates)} 信号日\n",
        f"- 组合数: {len(combos)} | quick={args.quick}\n",
        f"- 完整结果: `{csv_path}`\n\n",
        "## 排序说明\n\n",
        "按 `rank_score` 降序：OOS 盈亏比 × √笔数，笔数低于 `--min-oos-trades` 时惩罚。\n",
        "**勿直接实盘**：需结合经济含义与成本敏感性再定参。\n\n",
        "## 推荐检视（排名第一行）\n\n",
    ]
    if best:
        lines.append("```text\n")
        for k in out_df.columns:
            lines.append(f"  {k}: {best[k]}\n")
        lines.append("```\n\n")
    lines.append("## Top 5（表格）\n\n")
    if not out_df.empty:
        lines.append("```text\n")
        lines.append(out_df.head(5).to_string(index=False))
        lines.append("\n```\n")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write("".join(lines))

    print("\n  已写入:", flush=True)
    print(f"    {csv_path}", flush=True)
    print(f"    {latest}", flush=True)
    print(f"    {md_path}", flush=True)
    print("=" * 70, flush=True)


if __name__ == "__main__":
    main()
