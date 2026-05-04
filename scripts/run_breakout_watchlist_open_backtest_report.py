# -*- coding: utf-8 -*-
"""
突破策略 — 选股 + 买点 日线回测（同一报告内对比）

1）原选股：T 日选股 → **T+1 开盘价全量买入**（凡入池即买）→ T+1/T+2/T+3 收盘收益
2）买点策略：T 日选股 → T+1 仅当 **突破 pivot×(1+缓冲) 且量能达标** 时视为成交
   - 主口径：触发价 `entry_price` 买入（与 `confirm_breakout_daily` 一致）
   - 对比口径：T+1 开盘价买入（列 ret_t*_open）

输出：
  data/reports/breakout_watchlist_open_backtest_report.md（及带时间戳副本）
  data/reports/breakout_watchlist_open_trades_latest.csv
  data/reports/breakout_buy_point_trades_latest.csv
  data/reports/breakout_buy_point_funnel.csv

用法：
  python scripts/run_breakout_watchlist_open_backtest_report.py
  python scripts/run_breakout_watchlist_open_backtest_report.py --preset selection_relaxed_v1
  python scripts/run_breakout_watchlist_open_backtest_report.py --preset win_rate_priority
  python scripts/run_breakout_watchlist_open_backtest_report.py --preset wide_pool_strict_entry_v1
  python scripts/run_breakout_watchlist_open_backtest_report.py --preset wide_pool_strict_entry_v2
  python scripts/run_breakout_watchlist_open_backtest_report.py --compare
  python scripts/run_breakout_watchlist_open_backtest_report.py --compare-winrate
  python scripts/run_breakout_watchlist_open_backtest_report.py --compare --signal-start-date 20260105 --signal-end-date 20260410
  python scripts/run_breakout_watchlist_open_backtest_report.py --compare-buy-optimize --signal-start-date 20260105 --signal-end-date 20260410
  python scripts/run_breakout_watchlist_open_backtest_report.py --compare-full --signal-start-date 20260105 --signal-end-date 20260410
  # 含：baseline、放宽选股、买点三档、wide_pool_strict_entry_v1/v2（宽池+严买点一体）
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    sys.stdout.reconfigure(line_buffering=True)
except Exception:
    pass

from datetime import datetime
from typing import Any, Dict

import numpy as np
import pandas as pd

from src.core.config import ConfigManager
from src.core.database import DatabaseManager
from src.modules.breakout_backtest_runner import (
    run_breakout_backtest_loop,
    run_watchlist_open_backtest_loop,
    summarize_ret_column,
)
from src.modules.breakout_strategy import (
    BreakoutParams,
    BreakoutStrategy,
    get_breakout_params_for_backtest,
)


def _filter_signal_dates(signal_dates: list, start_s: str, end_s: str) -> list:
    """按起止日过滤信号日列表（字符串 YYYYMMDD 比较）。"""
    out = list(signal_dates)
    start_s = str(start_s or "").strip()
    end_s = str(end_s or "").strip()
    if start_s:
        out = [d for d in out if str(d) >= start_s]
    if end_s:
        out = [d for d in out if str(d) <= end_s]
    return out


def _fmt_pct(x: float | None) -> str:
    if x is None or (isinstance(x, float) and (np.isnan(x))):
        return "—"
    return f"{x:.2%}"


def _stats_row(v: pd.Series) -> tuple[int, float, float, float, float]:
    v = v.dropna()
    if v.empty:
        return 0, float("nan"), float("nan"), float("nan"), float("nan")
    n = len(v)
    wr = float((v > 0).mean())
    m = float(v.mean())
    med = float(v.median())
    gw = float(v[v > 0].sum())
    gl = float(-v[v < 0].sum())
    pf = gw / gl if gl > 1e-12 else 0.0
    return n, wr, m, med, pf


def _md_row(label: str, n: int, wr: float, m: float, med: float, pf: float) -> str:
    if n == 0:
        return f"| {label} | — | — | — | — | — |\n"
    return f"| {label} | {n} | {_fmt_pct(wr)} | {_fmt_pct(m)} | {_fmt_pct(med)} | {pf:.2f} |\n"


def run_preset_loops(
    db: DatabaseManager,
    features: pd.DataFrame,
    all_dates: list,
    signal_dates: list,
    use_ma120: bool,
    preset_name: str,
    progress_every: int = 20,
) -> Dict[str, Any]:
    """同一套因子表下，按预设跑「选股 T+1 开盘」+「买点确认」两套循环。"""
    params = get_breakout_params_for_backtest(preset_name, use_ma120)
    strategy = BreakoutStrategy(db=db, params=params)
    df, funnel_df, gate_stats = run_watchlist_open_backtest_loop(
        strategy, features, all_dates, signal_dates, use_ma120, progress_every=progress_every
    )
    df_buy, funnel_buy, _gate_buy = run_breakout_backtest_loop(
        strategy, features, all_dates, signal_dates, use_ma120, progress_every=progress_every
    )
    return {
        "params": params,
        "df": df,
        "funnel_df": funnel_df,
        "gate_stats": gate_stats,
        "df_buy": df_buy,
        "funnel_buy": funnel_buy,
    }


def _save_preset_outputs(rep_dir: str, prefix: str, res: Dict[str, Any]) -> None:
    """写出单套预设的漏斗与成交 CSV。"""
    funnel_df = res["funnel_df"]
    df = res["df"]
    df_buy = res["df_buy"]
    funnel_buy = res["funnel_buy"]
    funnel_df.to_csv(
        os.path.join(rep_dir, f"breakout_watchlist_open_funnel_{prefix}.csv"),
        index=False,
        encoding="utf-8-sig",
    )
    if not df.empty:
        df.sort_values(["signal_date", "ts_code"]).reset_index(drop=True).to_csv(
            os.path.join(rep_dir, f"breakout_watchlist_open_trades_{prefix}.csv"),
            index=False,
            encoding="utf-8-sig",
        )
    funnel_buy.to_csv(
        os.path.join(rep_dir, f"breakout_buy_point_funnel_{prefix}.csv"),
        index=False,
        encoding="utf-8-sig",
    )
    if df_buy is not None and not df_buy.empty:
        df_buy.sort_values(["signal_date", "confirm_date", "ts_code"]).reset_index(drop=True).to_csv(
            os.path.join(rep_dir, f"breakout_buy_point_trades_{prefix}.csv"),
            index=False,
            encoding="utf-8-sig",
        )


def _write_compare_outputs(
    rep_dir: str,
    stamp: str,
    min_d: str,
    max_d: str,
    total_days: int,
    signal_dates: list,
    warmup_skip: int,
    use_ma120: bool,
    res_b: Dict[str, Any],
    res_r: Dict[str, Any],
) -> None:
    """写出 baseline vs selection_relaxed_v1 的 CSV 与对比 Markdown。"""

    _save_preset_outputs(rep_dir, "baseline", res_b)
    _save_preset_outputs(rep_dir, "selection_relaxed_v1", res_r)

    pb, pr = res_b["params"], res_r["params"]
    n_sig = len(signal_dates)

    def _pool_buy_metrics(res: Dict[str, Any]) -> tuple:
        fu = res["funnel_df"]
        fb = res["funnel_buy"]
        dfb = res["df_buy"]
        days_pool = int((fu["watchlist_n"] > 0).sum())
        total_wl = int(fu["watchlist_n"].sum())
        # 买点确认笔数在 `run_breakout_backtest_loop` 的 funnel 中
        if not fb.empty and "confirmed_n" in fb.columns:
            days_confirm = int((fb["confirmed_n"] > 0).sum())
        else:
            days_confirm = 0
        n_buy = len(dfb) if dfb is not None else 0
        return days_pool, total_wl, days_confirm, n_buy

    dbp, twb, dcb, nbb = _pool_buy_metrics(res_b)
    drp, twr, dcr, nbr = _pool_buy_metrics(res_r)

    def _t1_stats(res: Dict[str, Any]) -> tuple:
        d = res["df_buy"]
        if d is None or d.empty or "ret_t1" not in d.columns:
            return (0, float("nan"), float("nan"), float("nan"), float("nan"))
        return _stats_row(d["ret_t1"])

    t1b = _t1_stats(res_b)
    t1r = _t1_stats(res_r)

    def _fmt_pf_tuple(t: tuple) -> str:
        if len(t) < 5 or t[0] == 0:
            return "—"
        v = t[4]
        if v is None or (isinstance(v, float) and np.isnan(v)):
            return "—"
        return f"{v:.2f}"

    lines = [
        "# 突破策略 — 选股预设对比（baseline vs selection_relaxed_v1）\n\n",
        f"- **生成时间**：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n",
        f"- **数据库日线**：{min_d} → {max_d}（共 {total_days} 个交易日）\n",
        f"- **信号日**：{signal_dates[0]} → {signal_dates[-1]}（共 **{n_sig}** 天）\n",
        f"- **趋势过滤**：{'MA120' if use_ma120 else 'MA20>MA60 降级'}\n",
        "- **说明**：两档 **买点参数完全相同**（仅放宽选股）。\n\n",
        "## 一、选股参数差异\n\n",
        "| 参数 | baseline | selection_relaxed_v1 |\n| --- | ---: | ---: |\n",
        f"| rs_quantile_min | {pb.rs_quantile_min} | {pr.rs_quantile_min} |\n",
        f"| min_signal_score | {pb.min_signal_score} | {pr.min_signal_score} |\n",
        f"| top_k | {pb.top_k} | {pr.top_k} |\n",
        f"| atr_quantile_max | {pb.atr_quantile_max} | {pr.atr_quantile_max} |\n",
        f"| box_max_range | {pb.box_max_range} | {pr.box_max_range} |\n",
        f"| breakout_buffer（未改） | {pb.breakout_buffer} | {pr.breakout_buffer} |\n",
        f"| volume_confirm_ratio（未改） | {pb.volume_confirm_ratio} | {pr.volume_confirm_ratio} |\n\n",
        "## 二、频率对比\n\n",
        "| 指标 | baseline | selection_relaxed_v1 |\n| --- | ---: | ---: |\n",
        f"| 有池日数 | {dbp} | {drp} |\n",
        f"| 有池日占比 | {dbp / n_sig:.2%} | {drp / n_sig:.2%} |\n",
        f"| 观察池累计条数 | {twb} | {twr} |\n",
        f"| 有买点日数（confirmed>0） | {dcb} | {dcr} |\n",
        f"| 买点成交笔数 | {nbb} | {nbr} |\n",
    ]
    conv_b = f"{nbb / twb:.2%}" if twb > 0 else "—"
    conv_r = f"{nbr / twr:.2%}" if twr > 0 else "—"
    lines.append(f"| 池条→买点转化 | {conv_b} | {conv_r} |\n")

    lines.extend(
        [
            "\n## 三、买点胜率（触发价 ret_t1，主口径）\n\n",
            "| 预设 | 样本数 | 胜率 | 均收益 | PF |\n| --- | ---: | ---: | ---: | ---: |\n",
            f"| baseline | {t1b[0]} | {_fmt_pct(t1b[1])} | {_fmt_pct(t1b[2])} | {_fmt_pf_tuple(t1b)} |\n",
            f"| selection_relaxed_v1 | {t1r[0]} | {_fmt_pct(t1r[1])} | {_fmt_pct(t1r[2])} | {_fmt_pf_tuple(t1r)} |\n\n",
            "## 四、输出文件\n\n",
            f"- `breakout_watchlist_open_funnel_baseline.csv` / `_selection_relaxed_v1.csv`\n",
            f"- `breakout_buy_point_trades_baseline.csv` / `_selection_relaxed_v1.csv`\n",
            f"- 时间戳副本：`breakout_selection_compare_{stamp}.md`\n",
        ]
    )

    cmp_path = os.path.join(rep_dir, "breakout_selection_compare.md")
    cmp_stamp = os.path.join(rep_dir, f"breakout_selection_compare_{stamp}.md")
    text = "".join(lines)
    with open(cmp_path, "w", encoding="utf-8") as f:
        f.write(text)
    with open(cmp_stamp, "w", encoding="utf-8") as f:
        f.write(text)


def _write_compare_winrate_outputs(
    rep_dir: str,
    stamp: str,
    min_d: str,
    max_d: str,
    total_days: int,
    signal_dates: list,
    use_ma120: bool,
    res_base: Dict[str, Any],
    res_win: Dict[str, Any],
) -> None:
    """baseline vs win_rate_priority：选股相同，仅买点收紧；CSV + 对比 MD。"""
    _save_preset_outputs(rep_dir, "baseline", res_base)
    _save_preset_outputs(rep_dir, "win_rate_priority", res_win)

    pb, pw = res_base["params"], res_win["params"]
    n_sig = len(signal_dates)

    def _pool_buy_metrics(res: Dict[str, Any]) -> tuple:
        fu = res["funnel_df"]
        fb = res["funnel_buy"]
        dfb = res["df_buy"]
        days_pool = int((fu["watchlist_n"] > 0).sum())
        total_wl = int(fu["watchlist_n"].sum())
        if not fb.empty and "confirmed_n" in fb.columns:
            days_confirm = int((fb["confirmed_n"] > 0).sum())
        else:
            days_confirm = 0
        n_buy = len(dfb) if dfb is not None else 0
        return days_pool, total_wl, days_confirm, n_buy

    dbp, twb, dcb, nbb = _pool_buy_metrics(res_base)
    dwp, tww, dcw, nbw = _pool_buy_metrics(res_win)

    def _t1_stats(res: Dict[str, Any]) -> tuple:
        d = res["df_buy"]
        if d is None or d.empty or "ret_t1" not in d.columns:
            return (0, float("nan"), float("nan"), float("nan"), float("nan"))
        return _stats_row(d["ret_t1"])

    t1b = _t1_stats(res_base)
    t1w = _t1_stats(res_win)

    def _fmt_pf_tuple(t: tuple) -> str:
        if len(t) < 5 or t[0] == 0:
            return "—"
        v = t[4]
        if v is None or (isinstance(v, float) and np.isnan(v)):
            return "—"
        return f"{v:.2f}"

    lines = [
        "# 突破策略 — 胜率优先：买点收紧对比（baseline vs win_rate_priority）\n\n",
        f"- **生成时间**：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n",
        f"- **数据库日线**：{min_d} → {max_d}（共 {total_days} 个交易日）\n",
        f"- **信号日**：{signal_dates[0]} → {signal_dates[-1]}（共 **{n_sig}** 天）\n",
        f"- **趋势过滤**：{'MA120' if use_ma120 else 'MA20>MA60 降级'}\n",
        "- **说明**：两档 **选股参数相同**；`win_rate_priority` 仅收紧 **突破缓冲、量能、追高与日内涨幅**。\n\n",
        "## 一、参数差异（仅买点）\n\n",
        "| 参数 | baseline | win_rate_priority |\n| --- | ---: | ---: |\n",
        f"| rs_quantile_min（选股） | {pb.rs_quantile_min} | {pw.rs_quantile_min} |\n",
        f"| min_signal_score | {pb.min_signal_score} | {pw.min_signal_score} |\n",
        f"| top_k | {pb.top_k} | {pw.top_k} |\n",
        f"| breakout_buffer | {pb.breakout_buffer} | {pw.breakout_buffer} |\n",
        f"| breakout_max_chase | {pb.breakout_max_chase} | {pw.breakout_max_chase} |\n",
        f"| volume_confirm_ratio（A） | {pb.volume_confirm_ratio} | {pw.volume_confirm_ratio} |\n",
        f"| volume_normal_ratio（B 下限） | {pb.volume_normal_ratio} | {pw.volume_normal_ratio} |\n",
        f"| max_intraday_gain | {pb.max_intraday_gain} | {pw.max_intraday_gain} |\n\n",
        "## 二、频率对比（选股应一致；买点笔数因确认规则变化）\n\n",
        "| 指标 | baseline | win_rate_priority |\n| --- | ---: | ---: |\n",
        f"| 有池日数 | {dbp} | {dwp} |\n",
        f"| 观察池累计条数 | {twb} | {tww} |\n",
        f"| 有买点日数 | {dcb} | {dcw} |\n",
        f"| 买点成交笔数 | {nbb} | {nbw} |\n",
    ]
    conv_b = f"{nbb / twb:.2%}" if twb > 0 else "—"
    conv_w = f"{nbw / tww:.2%}" if tww > 0 else "—"
    lines.append(f"| 池条→买点转化 | {conv_b} | {conv_w} |\n")

    lines.extend(
        [
            "\n## 三、买点胜率（触发价 ret_t1）\n\n",
            "| 预设 | 样本数 | 胜率 | 均收益 | PF |\n| --- | ---: | ---: | ---: | ---: |\n",
            f"| baseline | {t1b[0]} | {_fmt_pct(t1b[1])} | {_fmt_pct(t1b[2])} | {_fmt_pf_tuple(t1b)} |\n",
            f"| win_rate_priority | {t1w[0]} | {_fmt_pct(t1w[1])} | {_fmt_pct(t1w[2])} | {_fmt_pf_tuple(t1w)} |\n\n",
            "## 四、输出文件\n\n",
            "- `breakout_watchlist_open_funnel_baseline.csv` / `breakout_watchlist_open_funnel_win_rate_priority.csv`\n",
            "- `breakout_buy_point_trades_baseline.csv` / `breakout_buy_point_trades_win_rate_priority.csv`\n",
            f"- 时间戳副本：`breakout_buy_winrate_compare_{stamp}.md`\n",
        ]
    )

    cmp_path = os.path.join(rep_dir, "breakout_buy_winrate_compare.md")
    cmp_stamp = os.path.join(rep_dir, f"breakout_buy_winrate_compare_{stamp}.md")
    text = "".join(lines)
    with open(cmp_path, "w", encoding="utf-8") as f:
        f.write(text)
    with open(cmp_stamp, "w", encoding="utf-8") as f:
        f.write(text)


def _write_compare_buy_optimize_outputs(
    rep_dir: str,
    stamp: str,
    min_d: str,
    max_d: str,
    total_days: int,
    signal_dates: list,
    use_ma120: bool,
    res_base: Dict[str, Any],
    res_win: Dict[str, Any],
    res_tune: Dict[str, Any],
) -> None:
    """baseline vs win_rate_priority vs buy_tuning_v1：选股均为 baseline，仅买点阶梯收紧。"""
    _save_preset_outputs(rep_dir, "baseline", res_base)
    _save_preset_outputs(rep_dir, "win_rate_priority", res_win)
    _save_preset_outputs(rep_dir, "buy_tuning_v1", res_tune)

    pb, pw, pt = res_base["params"], res_win["params"], res_tune["params"]
    n_sig = len(signal_dates)

    def _pool_buy_metrics(res: Dict[str, Any]) -> tuple:
        fu = res["funnel_df"]
        fb = res["funnel_buy"]
        dfb = res["df_buy"]
        days_pool = int((fu["watchlist_n"] > 0).sum())
        total_wl = int(fu["watchlist_n"].sum())
        if not fb.empty and "confirmed_n" in fb.columns:
            days_confirm = int((fb["confirmed_n"] > 0).sum())
        else:
            days_confirm = 0
        n_buy = len(dfb) if dfb is not None else 0
        return days_pool, total_wl, days_confirm, n_buy

    dbp, twb, dcb, nbb = _pool_buy_metrics(res_base)
    dwp, tww, dcw, nbw = _pool_buy_metrics(res_win)
    dtp, twt, dct, nbt = _pool_buy_metrics(res_tune)

    def _t1_stats(res: Dict[str, Any]) -> tuple:
        d = res["df_buy"]
        if d is None or d.empty or "ret_t1" not in d.columns:
            return (0, float("nan"), float("nan"), float("nan"), float("nan"))
        return _stats_row(d["ret_t1"])

    t1b = _t1_stats(res_base)
    t1w = _t1_stats(res_win)
    t1t = _t1_stats(res_tune)

    def _fmt_pf_tuple(t: tuple) -> str:
        if len(t) < 5 or t[0] == 0:
            return "—"
        v = t[4]
        if v is None or (isinstance(v, float) and np.isnan(v)):
            return "—"
        return f"{v:.2f}"

    lines = [
        "# 突破策略 — 买点优化对比（baseline vs win_rate_priority vs buy_tuning_v1）\n\n",
        f"- **生成时间**：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n",
        f"- **数据库日线**：{min_d} → {max_d}（共 {total_days} 个交易日）\n",
        f"- **信号日**：{signal_dates[0]} → {signal_dates[-1]}（共 **{n_sig}** 天）\n",
        f"- **趋势过滤**：{'MA120' if use_ma120 else 'MA20>MA60 降级'}\n",
        "- **说明**：三档 **选股参数与 baseline 一致**；买点为阶梯收紧："
        "默认 → 胜率优先 → **buy_tuning_v1**（更严缓冲/量能/日内涨幅）。\n\n",
        "## 一、买点参数对比\n\n",
        "| 参数 | baseline | win_rate_priority | buy_tuning_v1 |\n| --- | ---: | ---: | ---: |\n",
        f"| breakout_buffer | {pb.breakout_buffer} | {pw.breakout_buffer} | {pt.breakout_buffer} |\n",
        f"| breakout_max_chase | {pb.breakout_max_chase} | {pw.breakout_max_chase} | {pt.breakout_max_chase} |\n",
        f"| volume_confirm_ratio（A） | {pb.volume_confirm_ratio} | {pw.volume_confirm_ratio} | {pt.volume_confirm_ratio} |\n",
        f"| volume_normal_ratio | {pb.volume_normal_ratio} | {pw.volume_normal_ratio} | {pt.volume_normal_ratio} |\n",
        f"| max_intraday_gain | {pb.max_intraday_gain} | {pw.max_intraday_gain} | {pt.max_intraday_gain} |\n\n",
        "## 二、频率对比\n\n",
        "| 指标 | baseline | win_rate_priority | buy_tuning_v1 |\n| --- | ---: | ---: | ---: |\n",
        f"| 有池日数 | {dbp} | {dwp} | {dtp} |\n",
        f"| 观察池累计条数 | {twb} | {tww} | {twt} |\n",
        f"| 有买点日数 | {dcb} | {dcw} | {dct} |\n",
        f"| 买点成交笔数 | {nbb} | {nbw} | {nbt} |\n",
    ]
    conv_b = f"{nbb / twb:.2%}" if twb > 0 else "—"
    conv_w = f"{nbw / tww:.2%}" if tww > 0 else "—"
    conv_t = f"{nbt / twt:.2%}" if twt > 0 else "—"
    lines.append(f"| 池条→买点转化 | {conv_b} | {conv_w} | {conv_t} |\n")

    lines.extend(
        [
            "\n## 三、买点胜率（触发价 ret_t1）\n\n",
            "| 预设 | 样本数 | 胜率 | 均收益 | PF |\n| --- | ---: | ---: | ---: | ---: |\n",
            f"| baseline | {t1b[0]} | {_fmt_pct(t1b[1])} | {_fmt_pct(t1b[2])} | {_fmt_pf_tuple(t1b)} |\n",
            f"| win_rate_priority | {t1w[0]} | {_fmt_pct(t1w[1])} | {_fmt_pct(t1w[2])} | {_fmt_pf_tuple(t1w)} |\n",
            f"| buy_tuning_v1 | {t1t[0]} | {_fmt_pct(t1t[1])} | {_fmt_pct(t1t[2])} | {_fmt_pf_tuple(t1t)} |\n\n",
            "## 四、输出文件\n\n",
            "- `breakout_watchlist_open_funnel_baseline.csv` / `_win_rate_priority.csv` / `_buy_tuning_v1.csv`\n",
            "- `breakout_buy_point_trades_*.csv` 同上三档前缀\n",
            f"- 时间戳副本：`breakout_buy_optimize_compare_{stamp}.md`\n",
        ]
    )

    cmp_path = os.path.join(rep_dir, "breakout_buy_optimize_compare.md")
    cmp_stamp_path = os.path.join(rep_dir, f"breakout_buy_optimize_compare_{stamp}.md")
    text = "".join(lines)
    with open(cmp_path, "w", encoding="utf-8") as f:
        f.write(text)
    with open(cmp_stamp_path, "w", encoding="utf-8") as f:
        f.write(text)


def _write_compare_full_outputs(
    rep_dir: str,
    stamp: str,
    min_d: str,
    max_d: str,
    total_days: int,
    signal_dates: list,
    warmup_skip: int,
    use_ma120: bool,
    res_base: Dict[str, Any],
    res_relaxed: Dict[str, Any],
    res_win: Dict[str, Any],
    res_tune: Dict[str, Any],
    res_wide: Dict[str, Any],
    res_wide_v2: Dict[str, Any],
) -> None:
    """
    单份 MD：表一放宽选股、表二买点三档、表三宽池+严买点（v1/v2）；
    写出六档预设的全部 CSV。
    """
    _save_preset_outputs(rep_dir, "baseline", res_base)
    _save_preset_outputs(rep_dir, "selection_relaxed_v1", res_relaxed)
    _save_preset_outputs(rep_dir, "win_rate_priority", res_win)
    _save_preset_outputs(rep_dir, "buy_tuning_v1", res_tune)
    _save_preset_outputs(rep_dir, "wide_pool_strict_entry_v1", res_wide)
    _save_preset_outputs(rep_dir, "wide_pool_strict_entry_v2", res_wide_v2)

    pb = res_base["params"]
    pr = res_relaxed["params"]
    pw = res_win["params"]
    pt = res_tune["params"]
    pwide = res_wide["params"]
    pwide2 = res_wide_v2["params"]
    n_sig = len(signal_dates)

    def _pool_buy_metrics(res: Dict[str, Any]) -> tuple:
        fu = res["funnel_df"]
        fb = res["funnel_buy"]
        dfb = res["df_buy"]
        days_pool = int((fu["watchlist_n"] > 0).sum())
        total_wl = int(fu["watchlist_n"].sum())
        if not fb.empty and "confirmed_n" in fb.columns:
            days_confirm = int((fb["confirmed_n"] > 0).sum())
        else:
            days_confirm = 0
        n_buy = len(dfb) if dfb is not None else 0
        return days_pool, total_wl, days_confirm, n_buy

    def _t1_stats(res: Dict[str, Any]) -> tuple:
        d = res["df_buy"]
        if d is None or d.empty or "ret_t1" not in d.columns:
            return (0, float("nan"), float("nan"), float("nan"), float("nan"))
        return _stats_row(d["ret_t1"])

    def _fmt_pf_tuple(t: tuple) -> str:
        if len(t) < 5 or t[0] == 0:
            return "—"
        v = t[4]
        if v is None or (isinstance(v, float) and np.isnan(v)):
            return "—"
        return f"{v:.2f}"

    dbp, twb, dcb, nbb = _pool_buy_metrics(res_base)
    drp, twr, dcr, nbr = _pool_buy_metrics(res_relaxed)
    dwp, tww, dcw, nbw = _pool_buy_metrics(res_win)
    dtp, twt, dct, nbt = _pool_buy_metrics(res_tune)
    dwide, twwide, dcwide, nbwide = _pool_buy_metrics(res_wide)
    dwide2, twwide2, dcwide2, nbwide2 = _pool_buy_metrics(res_wide_v2)

    t1b_sel = _t1_stats(res_base)
    t1r_sel = _t1_stats(res_relaxed)
    t1b_buy = _t1_stats(res_base)
    t1w = _t1_stats(res_win)
    t1t = _t1_stats(res_tune)
    t1wide = _t1_stats(res_wide)
    t1wide2 = _t1_stats(res_wide_v2)

    lines: list[str] = [
        "# 突破策略 — 综合对比（放宽选股 + 买点三档 + 宽池严买点 v1/v2，均以 baseline 为参照）\n\n",
        f"- **生成时间**：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n",
        f"- **数据库日线**：{min_d} → {max_d}（共 {total_days} 个交易日）\n",
        f"- **信号日**：{signal_dates[0]} → {signal_dates[-1]}（共 **{n_sig}** 天）\n",
        f"- **Warmup 跳过**：前 {warmup_skip} 个交易日；末尾保留 3 个交易日\n",
        f"- **趋势过滤**：{'MA120' if use_ma120 else 'MA20>MA60 降级'}\n\n",
        "## 说明\n\n",
        "- **baseline**：选股 + 买点均为默认主口径。\n",
        "- **表一**：仅改变**选股**（`selection_relaxed_v1`），**买点参数与 baseline 相同**。\n",
        "- **表二**：三档 **选股均与 baseline 相同**，仅改变**买点**（`win_rate_priority` / `buy_tuning_v1`）。\n",
        "- **表三**：**放宽选股 + 收紧买点** 一体化：`wide_pool_strict_entry_v1`（买点同 `win_rate_priority`）、"
        "`wide_pool_strict_entry_v2`（买点同 `buy_tuning_v1`，更严）。选股均同表一之 relaxed。\n\n",
        "---\n\n",
        "## 一、放宽选股 vs baseline（买点相同）\n\n",
        "### 1.1 选股参数差异\n\n",
        "| 参数 | baseline | selection_relaxed_v1 |\n| --- | ---: | ---: |\n",
        f"| rs_quantile_min | {pb.rs_quantile_min} | {pr.rs_quantile_min} |\n",
        f"| min_signal_score | {pb.min_signal_score} | {pr.min_signal_score} |\n",
        f"| top_k | {pb.top_k} | {pr.top_k} |\n",
        f"| atr_quantile_max | {pb.atr_quantile_max} | {pr.atr_quantile_max} |\n",
        f"| box_max_range | {pb.box_max_range} | {pr.box_max_range} |\n",
        f"| breakout_buffer（相同） | {pb.breakout_buffer} | {pr.breakout_buffer} |\n",
        f"| volume_confirm_ratio（相同） | {pb.volume_confirm_ratio} | {pr.volume_confirm_ratio} |\n\n",
        "### 1.2 频率与买点转化\n\n",
        "| 指标 | baseline | selection_relaxed_v1 |\n| --- | ---: | ---: |\n",
        f"| 有池日数 | {dbp} | {drp} |\n",
        f"| 有池日占比 | {dbp / n_sig:.2%} | {drp / n_sig:.2%} |\n",
        f"| 观察池累计条数 | {twb} | {twr} |\n",
        f"| 有买点日数 | {dcb} | {dcr} |\n",
        f"| 买点成交笔数 | {nbb} | {nbr} |\n",
    ]
    c0 = f"{nbb / twb:.2%}" if twb > 0 else "—"
    c1 = f"{nbr / twr:.2%}" if twr > 0 else "—"
    lines.append(f"| 池条→买点转化 | {c0} | {c1} |\n\n")
    lines.extend(
        [
            "### 1.3 买点 T+1（触发价 ret_t1，买点规则相同）\n\n",
            "| 预设 | 样本数 | 胜率 | 均收益 | PF |\n| --- | ---: | ---: | ---: | ---: |\n",
            f"| baseline | {t1b_sel[0]} | {_fmt_pct(t1b_sel[1])} | {_fmt_pct(t1b_sel[2])} | {_fmt_pf_tuple(t1b_sel)} |\n",
            f"| selection_relaxed_v1 | {t1r_sel[0]} | {_fmt_pct(t1r_sel[1])} | {_fmt_pct(t1r_sel[2])} | {_fmt_pf_tuple(t1r_sel)} |\n\n",
            "---\n\n",
            "## 二、买点三档 vs baseline（选股均为 baseline）\n\n",
            "### 2.1 买点参数\n\n",
            "| 参数 | baseline | win_rate_priority | buy_tuning_v1 |\n| --- | ---: | ---: | ---: |\n",
            f"| breakout_buffer | {pb.breakout_buffer} | {pw.breakout_buffer} | {pt.breakout_buffer} |\n",
            f"| breakout_max_chase | {pb.breakout_max_chase} | {pw.breakout_max_chase} | {pt.breakout_max_chase} |\n",
            f"| volume_confirm_ratio（A） | {pb.volume_confirm_ratio} | {pw.volume_confirm_ratio} | {pt.volume_confirm_ratio} |\n",
            f"| volume_normal_ratio | {pb.volume_normal_ratio} | {pw.volume_normal_ratio} | {pt.volume_normal_ratio} |\n",
            f"| max_intraday_gain | {pb.max_intraday_gain} | {pw.max_intraday_gain} | {pt.max_intraday_gain} |\n\n",
            "### 2.2 频率（选股应一致：观察池条数三档相同）\n\n",
            "| 指标 | baseline | win_rate_priority | buy_tuning_v1 |\n| --- | ---: | ---: | ---: |\n",
            f"| 有池日数 | {dbp} | {dwp} | {dtp} |\n",
            f"| 观察池累计条数 | {twb} | {tww} | {twt} |\n",
            f"| 有买点日数 | {dcb} | {dcw} | {dct} |\n",
            f"| 买点成交笔数 | {nbb} | {nbw} | {nbt} |\n",
        ]
    )
    conv_b = f"{nbb / twb:.2%}" if twb > 0 else "—"
    conv_w = f"{nbw / tww:.2%}" if tww > 0 else "—"
    conv_t = f"{nbt / twt:.2%}" if twt > 0 else "—"
    lines.append(f"| 池条→买点转化 | {conv_b} | {conv_w} | {conv_t} |\n\n")
    lines.extend(
        [
            "### 2.3 买点 T+1（触发价 ret_t1）\n\n",
            "| 预设 | 样本数 | 胜率 | 均收益 | PF |\n| --- | ---: | ---: | ---: | ---: |\n",
            f"| baseline | {t1b_buy[0]} | {_fmt_pct(t1b_buy[1])} | {_fmt_pct(t1b_buy[2])} | {_fmt_pf_tuple(t1b_buy)} |\n",
            f"| win_rate_priority | {t1w[0]} | {_fmt_pct(t1w[1])} | {_fmt_pct(t1w[2])} | {_fmt_pf_tuple(t1w)} |\n",
            f"| buy_tuning_v1 | {t1t[0]} | {_fmt_pct(t1t[1])} | {_fmt_pct(t1t[2])} | {_fmt_pf_tuple(t1t)} |\n\n",
            "---\n\n",
            "## 三、放宽选股 + 收紧买点 vs baseline（`wide_pool_strict_entry_v1` / `v2`）\n\n",
            "### 3.1 `wide_pool_strict_entry_v1`（选股同 relaxed，买点同 win_rate_priority）\n\n",
            "#### 参数摘要\n\n",
            "| 参数 | baseline | wide_pool_strict_entry_v1 |\n| --- | ---: | ---: |\n",
            f"| rs_quantile_min | {pb.rs_quantile_min} | {pwide.rs_quantile_min} |\n",
            f"| min_signal_score | {pb.min_signal_score} | {pwide.min_signal_score} |\n",
            f"| top_k | {pb.top_k} | {pwide.top_k} |\n",
            f"| breakout_buffer | {pb.breakout_buffer} | {pwide.breakout_buffer} |\n",
            f"| volume_confirm_ratio | {pb.volume_confirm_ratio} | {pwide.volume_confirm_ratio} |\n",
            f"| volume_normal_ratio | {pb.volume_normal_ratio} | {pwide.volume_normal_ratio} |\n",
            f"| max_intraday_gain | {pb.max_intraday_gain} | {pwide.max_intraday_gain} |\n\n",
            "#### 频率与买点转化\n\n",
            "| 指标 | baseline | wide_pool_strict_entry_v1 |\n| --- | ---: | ---: |\n",
            f"| 有池日数 | {dbp} | {dwide} |\n",
            f"| 有池日占比 | {dbp / n_sig:.2%} | {dwide / n_sig:.2%} |\n",
            f"| 观察池累计条数 | {twb} | {twwide} |\n",
            f"| 有买点日数 | {dcb} | {dcwide} |\n",
            f"| 买点成交笔数 | {nbb} | {nbwide} |\n",
        ]
    )
    cw0 = f"{nbwide / twwide:.2%}" if twwide > 0 else "—"
    lines.append(f"| 池条→买点转化 | {conv_b} | {cw0} |\n\n")
    lines.extend(
        [
            "#### 买点 T+1（触发价 ret_t1）\n\n",
            "| 预设 | 样本数 | 胜率 | 均收益 | PF |\n| --- | ---: | ---: | ---: | ---: |\n",
            f"| baseline | {t1b_buy[0]} | {_fmt_pct(t1b_buy[1])} | {_fmt_pct(t1b_buy[2])} | {_fmt_pf_tuple(t1b_buy)} |\n",
            f"| wide_pool_strict_entry_v1 | {t1wide[0]} | {_fmt_pct(t1wide[1])} | {_fmt_pct(t1wide[2])} | {_fmt_pf_tuple(t1wide)} |\n\n",
            "### 3.2 `wide_pool_strict_entry_v2`（选股同 relaxed，买点同 buy_tuning_v1）\n\n",
            "#### 参数摘要\n\n",
            "| 参数 | baseline | wide_pool_strict_entry_v2 |\n| --- | ---: | ---: |\n",
            f"| rs_quantile_min | {pb.rs_quantile_min} | {pwide2.rs_quantile_min} |\n",
            f"| min_signal_score | {pb.min_signal_score} | {pwide2.min_signal_score} |\n",
            f"| top_k | {pb.top_k} | {pwide2.top_k} |\n",
            f"| breakout_buffer | {pb.breakout_buffer} | {pwide2.breakout_buffer} |\n",
            f"| volume_confirm_ratio | {pb.volume_confirm_ratio} | {pwide2.volume_confirm_ratio} |\n",
            f"| volume_normal_ratio | {pb.volume_normal_ratio} | {pwide2.volume_normal_ratio} |\n",
            f"| max_intraday_gain | {pb.max_intraday_gain} | {pwide2.max_intraday_gain} |\n\n",
            "#### 频率与买点转化\n\n",
            "| 指标 | baseline | wide_pool_strict_entry_v2 |\n| --- | ---: | ---: |\n",
            f"| 有池日数 | {dbp} | {dwide2} |\n",
            f"| 有池日占比 | {dbp / n_sig:.2%} | {dwide2 / n_sig:.2%} |\n",
            f"| 观察池累计条数 | {twb} | {twwide2} |\n",
            f"| 有买点日数 | {dcb} | {dcwide2} |\n",
            f"| 买点成交笔数 | {nbb} | {nbwide2} |\n",
        ]
    )
    cw0 = f"{nbwide2 / twwide2:.2%}" if twwide2 > 0 else "—"
    lines.append(f"| 池条→买点转化 | {conv_b} | {cw0} |\n\n")
    lines.extend(
        [
            "#### 买点 T+1（触发价 ret_t1）\n\n",
            "| 预设 | 样本数 | 胜率 | 均收益 | PF |\n| --- | ---: | ---: | ---: | ---: |\n",
            f"| baseline | {t1b_buy[0]} | {_fmt_pct(t1b_buy[1])} | {_fmt_pct(t1b_buy[2])} | {_fmt_pf_tuple(t1b_buy)} |\n",
            f"| wide_pool_strict_entry_v2 | {t1wide2[0]} | {_fmt_pct(t1wide2[1])} | {_fmt_pct(t1wide2[2])} | {_fmt_pf_tuple(t1wide2)} |\n\n",
            "## 四、输出文件\n\n",
            "- `breakout_watchlist_open_funnel_*.csv`：`baseline` / `selection_relaxed_v1` / `win_rate_priority` / "
            "`buy_tuning_v1` / `wide_pool_strict_entry_v1` / `wide_pool_strict_entry_v2`\n",
            "- `breakout_buy_point_trades_*.csv` 同上六档前缀\n",
            f"- 本报告时间戳副本：`breakout_full_compare_{stamp}.md`\n",
        ]
    )

    cmp_path = os.path.join(rep_dir, "breakout_full_compare.md")
    cmp_stamp_path = os.path.join(rep_dir, f"breakout_full_compare_{stamp}.md")
    text = "".join(lines)
    with open(cmp_path, "w", encoding="utf-8") as f:
        f.write(text)
    with open(cmp_stamp_path, "w", encoding="utf-8") as f:
        f.write(text)


def main() -> None:
    parser = argparse.ArgumentParser(description="突破策略：选股+买点 日线回测")
    parser.add_argument(
        "--preset",
        choices=[
            "baseline",
            "selection_relaxed_v1",
            "win_rate_priority",
            "wide_pool_strict_entry_v1",
            "wide_pool_strict_entry_v2",
            "buy_tuning_v1",
        ],
        default="baseline",
        help="baseline=主报告默认；selection_relaxed_v1=放宽选股；win_rate_priority=选股同 baseline、收紧买点",
    )
    parser.add_argument(
        "--compare",
        action="store_true",
        help="同时跑 baseline 与 selection_relaxed_v1",
    )
    parser.add_argument(
        "--compare-winrate",
        action="store_true",
        help="同时跑 baseline 与 win_rate_priority（胜率优先买点），写出 breakout_buy_winrate_compare.md",
    )
    parser.add_argument(
        "--compare-buy-optimize",
        action="store_true",
        help="同时跑 baseline / win_rate_priority / buy_tuning_v1（选股均为 baseline，买点阶梯收紧），写出 breakout_buy_optimize_compare.md",
    )
    parser.add_argument(
        "--compare-full",
        action="store_true",
        help="合并选股/买点/宽池严买点对比到 breakout_full_compare.md，并写出六档 CSV（含 wide_pool_strict_entry_v1/v2）",
    )
    parser.add_argument(
        "--signal-start-date",
        type=str,
        default="",
        help="信号日下限 YYYYMMDD（含）；空则使用 warmup 后至倒数第 4 日的全区间",
    )
    parser.add_argument(
        "--signal-end-date",
        type=str,
        default="",
        help="信号日上限 YYYYMMDD（含）；空则同上",
    )
    args = parser.parse_args()

    print("=" * 70, flush=True)
    print("  突破策略 — 选股（T+1开盘）+ 买点（突破确认）日线回测", flush=True)
    print("=" * 70, flush=True)

    config = ConfigManager()
    db = DatabaseManager(config)

    info = db.query(
        "SELECT MIN(trade_date) as min_d, MAX(trade_date) as max_d, "
        "COUNT(DISTINCT trade_date) as days FROM stock_daily"
    )
    min_d, max_d, total_days = info[0]["min_d"], info[0]["max_d"], info[0]["days"]
    print(f"\n  数据库日线: {min_d} -> {max_d}, 共 {total_days} 个交易日", flush=True)

    all_dates_rows = db.query(
        "SELECT DISTINCT trade_date FROM stock_daily ORDER BY trade_date ASC"
    )
    all_dates = [r["trade_date"] for r in all_dates_rows]

    if len(all_dates) >= 180:
        warmup_skip = 125
        use_ma120 = True
    elif len(all_dates) >= 75:
        warmup_skip = 65
        use_ma120 = False
        print(f"  注意: 仅{len(all_dates)}个交易日, 降级 MA20>MA60 趋势过滤", flush=True)
    else:
        print("  数据不足，退出")
        return

    if len(all_dates) <= warmup_skip + 10:
        print("  warmup 后数据不足，退出")
        return

    backtest_dates = all_dates[warmup_skip:]
    signal_dates = backtest_dates[:-3]
    signal_dates = _filter_signal_dates(signal_dates, args.signal_start_date, args.signal_end_date)
    if not signal_dates:
        print("  过滤后信号日为空，请调整 --signal-start-date / --signal-end-date", flush=True)
        return
    print(
        f"  信号日窗口: {signal_dates[0]} -> {signal_dates[-1]}（共 {len(signal_dates)} 个交易日）",
        flush=True,
    )

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    rep_dir = os.path.join(root, "data", "reports")
    os.makedirs(rep_dir, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    print(
        "\n  [1/10] 计算全量因子（与选股预设无关，全市场因子只算一次）..."
        if args.compare_full
        else "\n  [1/4] 计算全量因子（与选股预设无关，全市场因子只算一次）...",
        flush=True,
    )
    params_feat = get_breakout_params_for_backtest("baseline", use_ma120)
    strategy_feat = BreakoutStrategy(db=db, params=params_feat)
    raw_daily, raw_basic = strategy_feat._load_data(max_d)
    if raw_daily.empty:
        print("  日线为空，退出")
        return
    features = strategy_feat._compute_features(raw_daily, raw_basic, max_d)
    print(f"  因子行数: {len(features)}", flush=True)

    if args.compare_full:
        n = len(signal_dates)
        print(f"\n  [2/10] baseline 回测（{n} 个信号日）...", flush=True)
        res_base = run_preset_loops(db, features, all_dates, signal_dates, use_ma120, "baseline")
        print("\n  [3/10] selection_relaxed_v1 回测（放宽选股、买点同 baseline）...", flush=True)
        res_relaxed = run_preset_loops(db, features, all_dates, signal_dates, use_ma120, "selection_relaxed_v1")
        print("\n  [4/10] win_rate_priority 回测（选股同 baseline）...", flush=True)
        res_win = run_preset_loops(db, features, all_dates, signal_dates, use_ma120, "win_rate_priority")
        print("\n  [5/10] buy_tuning_v1 回测...", flush=True)
        res_tune = run_preset_loops(db, features, all_dates, signal_dates, use_ma120, "buy_tuning_v1")
        print("\n  [6/10] wide_pool_strict_entry_v1 回测（宽池 + 买点同 win_rate_priority）...", flush=True)
        res_wide = run_preset_loops(db, features, all_dates, signal_dates, use_ma120, "wide_pool_strict_entry_v1")
        print("\n  [7/10] wide_pool_strict_entry_v2 回测（宽池 + 买点同 buy_tuning_v1）...", flush=True)
        res_wide_v2 = run_preset_loops(db, features, all_dates, signal_dates, use_ma120, "wide_pool_strict_entry_v2")
        print("\n  [8/10] 汇总写入 breakout_full_compare.md ...", flush=True)
        _write_compare_full_outputs(
            rep_dir,
            stamp,
            min_d,
            max_d,
            total_days,
            signal_dates,
            warmup_skip,
            use_ma120,
            res_base,
            res_relaxed,
            res_win,
            res_tune,
            res_wide,
            res_wide_v2,
        )
        print("\n  [9/10] 综合对比报告已生成", flush=True)
        print(f"    {os.path.join(rep_dir, 'breakout_full_compare.md')}", flush=True)
        print(f"    {os.path.join(rep_dir, f'breakout_full_compare_{stamp}.md')}", flush=True)
        print("\n" + "=" * 70, flush=True)
        print("  [10/10] 完成", flush=True)
        print("=" * 70, flush=True)
        return

    if args.compare_buy_optimize:
        print(f"\n  [2/5] baseline 回测（{len(signal_dates)} 个信号日）...", flush=True)
        res_base = run_preset_loops(db, features, all_dates, signal_dates, use_ma120, "baseline")
        print("\n  [3/5] win_rate_priority 回测...", flush=True)
        res_win = run_preset_loops(db, features, all_dates, signal_dates, use_ma120, "win_rate_priority")
        print("\n  [4/5] buy_tuning_v1 回测...", flush=True)
        res_tune = run_preset_loops(db, features, all_dates, signal_dates, use_ma120, "buy_tuning_v1")
        _write_compare_buy_optimize_outputs(
            rep_dir, stamp, min_d, max_d, total_days, signal_dates, use_ma120, res_base, res_win, res_tune
        )
        print("\n  [5/5] 买点优化三档对比报告已生成", flush=True)
        print(f"    {os.path.join(rep_dir, 'breakout_buy_optimize_compare.md')}", flush=True)
        print(f"    {os.path.join(rep_dir, f'breakout_buy_optimize_compare_{stamp}.md')}", flush=True)
        print("\n" + "=" * 70, flush=True)
        print("  完成", flush=True)
        print("=" * 70, flush=True)
        return

    if args.compare_winrate:
        print(f"\n  [2/4] baseline 回测（{len(signal_dates)} 个信号日）...", flush=True)
        res_base = run_preset_loops(db, features, all_dates, signal_dates, use_ma120, "baseline")
        print("\n  [3/4] win_rate_priority 回测（选股同 baseline、收紧买点）...", flush=True)
        res_win = run_preset_loops(db, features, all_dates, signal_dates, use_ma120, "win_rate_priority")
        _write_compare_winrate_outputs(
            rep_dir, stamp, min_d, max_d, total_days, signal_dates, use_ma120, res_base, res_win
        )
        print("\n  [4/4] 胜率优先对比报告已生成", flush=True)
        print(f"    {os.path.join(rep_dir, 'breakout_buy_winrate_compare.md')}", flush=True)
        print(f"    {os.path.join(rep_dir, f'breakout_buy_winrate_compare_{stamp}.md')}", flush=True)
        print("\n" + "=" * 70, flush=True)
        print("  完成", flush=True)
        print("=" * 70, flush=True)
        return

    if args.compare:
        print(f"\n  [2/4] baseline 回测（{len(signal_dates)} 个信号日）...", flush=True)
        res_b = run_preset_loops(db, features, all_dates, signal_dates, use_ma120, "baseline")
        print("\n  [3/4] selection_relaxed_v1 回测...", flush=True)
        res_r = run_preset_loops(db, features, all_dates, signal_dates, use_ma120, "selection_relaxed_v1")
        _write_compare_outputs(
            rep_dir, stamp, min_d, max_d, total_days, signal_dates, warmup_skip, use_ma120, res_b, res_r
        )
        print("\n  [4/4] 对比报告已生成", flush=True)
        print(f"    {os.path.join(rep_dir, 'breakout_selection_compare.md')}", flush=True)
        print(f"    {os.path.join(rep_dir, f'breakout_selection_compare_{stamp}.md')}", flush=True)
        print("\n" + "=" * 70, flush=True)
        print("  完成", flush=True)
        print("=" * 70, flush=True)
        return

    preset = args.preset
    print(f"\n  [2/4] 逐日回测 — 预设={preset}（观察池 + 买点）...", flush=True)
    res = run_preset_loops(db, features, all_dates, signal_dates, use_ma120, preset)
    df = res["df"]
    funnel_df = res["funnel_df"]
    gate_stats = res["gate_stats"]
    df_buy = res["df_buy"]
    funnel_buy = res["funnel_buy"]
    params = res["params"]

    funnel_path = os.path.join(
        rep_dir,
        "breakout_watchlist_open_funnel.csv"
        if preset == "baseline"
        else f"breakout_watchlist_open_funnel_{preset}.csv",
    )
    funnel_df.to_csv(funnel_path, index=False, encoding="utf-8-sig")

    trades_path = os.path.join(
        rep_dir,
        "breakout_watchlist_open_trades_latest.csv"
        if preset == "baseline"
        else f"breakout_watchlist_open_trades_{preset}.csv",
    )
    if not df.empty:
        df = df.sort_values(["signal_date", "ts_code"]).reset_index(drop=True)
        df.to_csv(trades_path, index=False, encoding="utf-8-sig")
        df.to_csv(
            os.path.join(rep_dir, f"breakout_watchlist_open_trades_{stamp}.csv"),
            index=False,
            encoding="utf-8-sig",
        )

    buy_funnel_path = os.path.join(
        rep_dir,
        "breakout_buy_point_funnel.csv"
        if preset == "baseline"
        else f"breakout_buy_point_funnel_{preset}.csv",
    )
    funnel_buy.to_csv(buy_funnel_path, index=False, encoding="utf-8-sig")

    buy_trades_path = os.path.join(
        rep_dir,
        "breakout_buy_point_trades_latest.csv"
        if preset == "baseline"
        else f"breakout_buy_point_trades_{preset}.csv",
    )
    if not df_buy.empty:
        df_buy = df_buy.sort_values(["signal_date", "confirm_date", "ts_code"]).reset_index(drop=True)
        df_buy.to_csv(buy_trades_path, index=False, encoding="utf-8-sig")
        df_buy.to_csv(
            os.path.join(rep_dir, f"breakout_buy_point_trades_{stamp}.csv"),
            index=False,
            encoding="utf-8-sig",
        )

    n_sig_days = len(signal_dates)
    days_pool = int((funnel_df["watchlist_n"] > 0).sum())
    total_wl = int(funnel_df["watchlist_n"].sum())
    n_trades = len(df)

    days_confirm = int((funnel_buy["confirmed_n"] > 0).sum()) if not funnel_buy.empty else 0
    n_buy = len(df_buy) if df_buy is not None else 0

    lines = []
    title = "# 突破策略 — 选股 + 买点 日线回测\n\n"
    if preset != "baseline":
        title = f"# 突破策略 — 选股 + 买点 日线回测（预设：`{preset}`）\n\n"
    lines.append(title)
    lines.append(f"- **生成时间**：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
    lines.append(f"- **数据库日线范围**：{min_d} → {max_d}（共 {total_days} 个交易日）\n")
    lines.append(
        f"- **回测信号日窗口**：{signal_dates[0]} → {signal_dates[-1]}（共 **{n_sig_days}** 个交易日）\n"
    )
    lines.append(f"- **Warmup 跳过**：前 {warmup_skip} 个交易日；末尾保留 3 个交易日\n")
    lines.append(f"- **趋势过滤**：{'MA120 版本' if use_ma120 else '降级 MA20>MA60'}\n\n")

    lines.append("## 一、回测参数（与日线报告脚本一致）\n\n")
    lines.append("| 参数 | 取值 |\n| --- | --- |\n")
    lines.append(f"| min_amt_ma20 | {params.min_amt_ma20} |\n")
    lines.append(f"| rs_quantile_min | {params.rs_quantile_min} |\n")
    lines.append(f"| rs_quantile_max | {params.rs_quantile_max} |\n")
    lines.append(f"| min_signal_score | {params.min_signal_score} |\n")
    lines.append(f"| top_k | {params.top_k} |\n")
    lines.append(f"| breakout_buffer | {params.breakout_buffer} |\n")
    lines.append(f"| volume_confirm_ratio（A） | {params.volume_confirm_ratio} |\n")
    lines.append(f"| volume_normal_ratio（B） | {params.volume_normal_ratio} |\n")
    lines.append("\n")

    lines.append("## 二、触发频率（选股）\n\n")
    lines.append("| 指标 | 数值 |\n| --- | ---: |\n")
    lines.append(f"| 信号日总数 | {n_sig_days} |\n")
    lines.append(f"| 有观察池的交易日数（watchlist_n>0） | {days_pool} |\n")
    if n_sig_days > 0:
        lines.append(f"| **有池日占比** | {days_pool / n_sig_days:.2%} |\n")
    lines.append(f"| 观察池累计条数（可交易样本） | {total_wl} |\n")
    if n_sig_days > 0:
        lines.append(f"| 全信号日平均每日条数 | {total_wl / n_sig_days:.3f} |\n")
    if days_pool > 0:
        lines.append(f"| 仅有池日平均每日条数 | {total_wl / days_pool:.3f} |\n")
    lines.append(
        f"| 市场闸门 | 正常 {gate_stats['normal']} 天 / 谨慎 {gate_stats['caution']} 天 / 禁止 {gate_stats['stop']} 天 |\n"
    )
    lines.append("\n")

    lines.append("## 三、触发频率（买点：次日突破+量能确认）\n\n")
    lines.append("| 指标 | 数值 |\n| --- | ---: |\n")
    lines.append(f"| 有突破确认的交易日数（confirmed_n>0） | {days_confirm} |\n")
    if n_sig_days > 0:
        lines.append(f"| **有买点日占信号日比例** | {days_confirm / n_sig_days:.2%} |\n")
    lines.append(f"| 确认成交总笔数 | {n_buy} |\n")
    if n_sig_days > 0:
        lines.append(f"| 全信号日平均买点笔数/日 | {n_buy / n_sig_days:.3f} |\n")
    if days_confirm > 0:
        lines.append(f"| 仅有买点日平均笔数/日 | {n_buy / days_confirm:.3f} |\n")
    if total_wl > 0 and n_buy > 0:
        lines.append(f"| 观察池条数 → 买点笔数 转化 | {n_buy / total_wl:.2%} |\n")
    lines.append("\n")

    lines.append("## 四、选股口径 — T+1 开盘全买 — 持有至各收盘\n\n")
    lines.append(
        "> **ret_t1** = 当日（T+1）收盘 / T+1 开盘 − 1；"
        "**ret_t2** = T+2 收盘 / T+1 开盘 − 1；**ret_t3** = T+3 收盘 / T+1 开盘 − 1。"
        "不含手续费与滑点。\n\n"
    )
    lines.append("| 持有至 | 样本数 | 胜率 | 平均收益 | 中位数收益 | PF |\n| --- | ---: | ---: | ---: | ---: | ---: |\n")
    for hn in [1, 2, 3]:
        col = f"ret_t{hn}"
        if df.empty:
            lines.append(_md_row(f"T+{hn} 收盘", 0, float("nan"), float("nan"), float("nan"), float("nan")))
            continue
        n, wr, m, med, pf = _stats_row(df[col])
        lines.append(_md_row(f"T+{hn} 收盘", n, wr, m, med, pf))

    lines.append("\n## 五、选股口径 — 等权组合（按信号日对池内 ret 取均值再复利）\n\n")
    for hn in [1, 2, 3]:
        col = f"ret_t{hn}"
        m = summarize_ret_column(df, col) if not df.empty else {}
        lines.append(f"### {col}\n\n")
        lines.append(
            f"- 单笔样本数：{m.get('n_trades', 0):.0f}\n"
            f"- 区间总收益：{_fmt_pct(m.get('port_total_ret'))}\n"
            f"- 最大回撤：{_fmt_pct(m.get('port_mdd'))}\n"
            f"- 日夏普（年化近似）：{m.get('port_sharpe', 0):.2f}\n\n"
        )

    lines.append("## 六、买点口径 — 触发价买入（`confirm_breakout_daily`）\n\n")
    lines.append(
        "> 自确认日 **触发价** 至其后第 N 个交易日 **收盘**；与 `run_breakout_daily_backtest_report` 主口径一致。"
        "不含手续费与滑点。\n\n"
    )
    lines.append("| 持有至 | 样本数 | 胜率 | 平均收益 | 中位数收益 | PF |\n| --- | ---: | ---: | ---: | ---: | ---: |\n")
    for hn in [1, 2, 3]:
        col = f"ret_t{hn}"
        if df_buy is None or df_buy.empty:
            lines.append(_md_row(f"T+{hn} 收盘", 0, float("nan"), float("nan"), float("nan"), float("nan")))
            continue
        n, wr, m, med, pf = _stats_row(df_buy[col])
        lines.append(_md_row(f"T+{hn} 收盘", n, wr, m, med, pf))

    lines.append("\n### 6.1 等权组合（按信号日对触发价 ret_t1~t3 分别聚合）\n\n")
    for hn in [1, 2, 3]:
        col = f"ret_t{hn}"
        m = summarize_ret_column(df_buy, col) if df_buy is not None and not df_buy.empty else {}
        lines.append(f"#### {col}\n\n")
        lines.append(
            f"- 单笔样本数：{m.get('n_trades', 0):.0f}\n"
            f"- 区间总收益：{_fmt_pct(m.get('port_total_ret'))}\n"
            f"- 最大回撤：{_fmt_pct(m.get('port_mdd'))}\n"
            f"- 日夏普（年化近似）：{m.get('port_sharpe', 0):.2f}\n\n"
        )

    lines.append("## 七、买点口径 — T+1 开盘价买入（敏感性）\n\n")
    lines.append(
        "> 假设确认日以 **开盘价** 成交，再持有至各收盘；列名为 `ret_t1_open` ~ `ret_t3_open`。\n\n"
    )
    lines.append("| 持有至 | 样本数 | 胜率 | 平均收益 | 中位数收益 | PF |\n| --- | ---: | ---: | ---: | ---: | ---: |\n")
    for hn in [1, 2, 3]:
        col = f"ret_t{hn}_open"
        if df_buy is None or df_buy.empty or col not in df_buy.columns:
            lines.append(_md_row(f"T+{hn} 收盘", 0, float("nan"), float("nan"), float("nan"), float("nan")))
            continue
        n, wr, m, med, pf = _stats_row(df_buy[col])
        lines.append(_md_row(f"T+{hn} 收盘", n, wr, m, med, pf))

    if df_buy is not None and not df_buy.empty and "signal_grade" in df_buy.columns:
        lines.append("\n## 八、买点 — 按信号分级（触发价 ret_t1）\n\n")
        lines.append("| 分级 | 笔数 | 胜率 | 均收益 |\n| --- | ---: | ---: | ---: |\n")
        for g in sorted(df_buy["signal_grade"].dropna().unique()):
            v = df_buy.loc[df_buy["signal_grade"] == g, "ret_t1"].dropna()
            if v.empty:
                continue
            lines.append(f"| {g} | {len(v)} | {_fmt_pct((v > 0).mean())} | {_fmt_pct(v.mean())} |\n")

    if not df.empty:
        lines.append("\n## 九、选股 — 按评分分层（ret_t1）\n\n")
        df2 = df.copy()
        df2["score_bin"] = pd.cut(
            df2["signal_score"],
            bins=[0, 55, 60, 65, 70, 75, 80, 100],
            labels=["<55", "55-60", "60-65", "65-70", "70-75", "75-80", ">80"],
        )
        lines.append("| 评分区间 | 笔数 | 胜率 | 均收益 |\n| --- | ---: | ---: | ---: |\n")
        for label, grp in df2.groupby("score_bin", observed=True):
            v = grp["ret_t1"].dropna()
            if v.empty:
                continue
            lines.append(
                f"| {label} | {len(v)} | {_fmt_pct((v > 0).mean())} | {_fmt_pct(v.mean())} |\n"
            )

        lines.append("\n## 十、选股 — 按月（ret_t1）\n\n")
        df2["month"] = df2["signal_date"].astype(str).str[:6]
        lines.append("| 月份 | 笔数 | 胜率 | 均收益 |\n| --- | ---: | ---: | ---: |\n")
        for month, grp in df2.groupby("month"):
            v = grp["ret_t1"].dropna()
            if v.empty:
                continue
            lines.append(
                f"| {month} | {len(v)} | {_fmt_pct((v > 0).mean())} | {_fmt_pct(v.mean())} |\n"
            )

    lines.append("\n## 十一、输出文件\n\n")
    lines.append(f"- 选股漏斗：`{funnel_path}`\n")
    lines.append(f"- 选股成交明细（T+1 开盘）：`{trades_path}`\n")
    lines.append(f"- 买点逐日漏斗：`{buy_funnel_path}`\n")
    lines.append(f"- 买点成交明细：`{buy_trades_path}`\n")

    report_md = os.path.join(
        rep_dir,
        "breakout_watchlist_open_backtest_report.md"
        if preset == "baseline"
        else f"breakout_watchlist_open_backtest_report_{preset}.md",
    )
    report_stamp = (
        os.path.join(rep_dir, f"breakout_watchlist_open_backtest_report_{stamp}.md")
        if preset == "baseline"
        else os.path.join(rep_dir, f"breakout_watchlist_open_backtest_report_{preset}_{stamp}.md")
    )
    text = "".join(lines)
    with open(report_md, "w", encoding="utf-8") as f:
        f.write(text)
    with open(report_stamp, "w", encoding="utf-8") as f:
        f.write(text)

    print("\n  [4/4] 报告已生成", flush=True)
    print(f"    {report_md}", flush=True)
    print(f"    {report_stamp}", flush=True)
    print(f"    {funnel_path}", flush=True)
    print(f"    {buy_funnel_path}", flush=True)
    print(f"    {buy_trades_path}", flush=True)
    print("\n" + "=" * 70, flush=True)
    print("  完成", flush=True)
    print("=" * 70, flush=True)


if __name__ == "__main__":
    main()
