# -*- coding: utf-8 -*-
"""
突破策略日线级回测与选股效果报告

口径与 run_breakout_backtest.py 一致：
  信号日 T 收盘后选股 → T+1 突破+量能确认 → **主口径：触发价入场**；
  另输出 **确认日开盘价入场** 作敏感性对比（假设开盘即可成交，与「突破后挂单」不完全等价）。

输出：
  data/reports/breakout_daily_backtest_report.md（及带时间戳副本）
  data/reports/breakout_backtest_daily_funnel.csv
  data/reports/breakout_backtest_trades_latest.csv（与旧脚本同路径，便于下游复用）
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    sys.stdout.reconfigure(line_buffering=True)
except Exception:
    pass

from datetime import datetime

import numpy as np
import pandas as pd

from src.core.config import ConfigManager
from src.core.database import DatabaseManager
from src.modules.breakout_backtest_runner import run_breakout_backtest_loop
from src.modules.breakout_strategy import BreakoutStrategy, BreakoutParams


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


def _md_row_tn(label: str, n: int, wr: float, m: float, med: float, pf: float) -> str:
    if n == 0:
        return f"| {label} | — | — | — | — | — |\n"
    return f"| {label} | {n} | {_fmt_pct(wr)} | {_fmt_pct(m)} | {_fmt_pct(med)} | {pf:.2f} |\n"


def main() -> None:
    print("=" * 70, flush=True)
    print("  突破策略 — 日线回测与选股效果报告", flush=True)
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

    params = BreakoutParams()
    params.min_amt_ma20 = 8e4
    params.rs_quantile_max = 0.97
    # 与样本外粗网格 OOS 最优档一致（见 data/reports/breakout_oos_param_grid_summary.md）
    params.rs_quantile_min = 0.80
    params.min_signal_score = 60.0
    params.top_k = 20
    params.volume_confirm_ratio = 1.2
    params.volume_normal_ratio = 1.0
    if not use_ma120:
        params.atr_quantile_max = 0.50
        params.box_max_range = 0.08
    strategy = BreakoutStrategy(db=db, params=params)

    print("\n  [1/3] 计算全量因子...", flush=True)
    raw_daily, raw_basic = strategy._load_data(max_d)
    if raw_daily.empty:
        print("  日线为空，退出")
        return
    features = strategy._compute_features(raw_daily, raw_basic, max_d)
    print(f"  因子行数: {len(features)}", flush=True)

    print(f"\n  [2/3] 逐日回测 ({len(signal_dates)} 个信号日)...", flush=True)
    df, funnel_df, gate_stats = run_breakout_backtest_loop(
        strategy, features, all_dates, signal_dates, use_ma120, progress_every=15
    )

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    rep_dir = os.path.join(root, "data", "reports")
    os.makedirs(rep_dir, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    funnel_path = os.path.join(rep_dir, "breakout_backtest_daily_funnel.csv")
    funnel_df.to_csv(funnel_path, index=False, encoding="utf-8-sig")

    trades_path = os.path.join(rep_dir, "breakout_backtest_trades_latest.csv")
    if not df.empty:
        df = df.sort_values(["signal_date", "confirm_date", "ts_code"]).reset_index(drop=True)
        df.to_csv(trades_path, index=False, encoding="utf-8-sig")
        df.to_csv(os.path.join(rep_dir, f"breakout_backtest_trades_{stamp}.csv"), index=False, encoding="utf-8-sig")

    # 报告
    n_sig_days = len(signal_dates)
    days_pool = int((funnel_df["watchlist_n"] > 0).sum())
    total_wl = int(funnel_df["watchlist_n"].sum())
    days_confirm = int((funnel_df["confirmed_n"] > 0).sum())
    n_trades = len(df)

    lines = []
    lines.append("# 突破策略 — 日线回测与选股效果报告\n\n")
    lines.append(f"- **生成时间**：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
    lines.append(f"- **数据库日线范围**：{min_d} → {max_d}（共 {total_days} 个交易日）\n")
    lines.append(
        f"- **回测信号日窗口**：{signal_dates[0]} → {signal_dates[-1]}（共 **{n_sig_days}** 个交易日）\n"
    )
    lines.append(f"- **Warmup 跳过**：前 {warmup_skip} 个交易日；末尾保留 3 个交易日作为持有退出空间\n")
    lines.append(f"- **趋势过滤**：{'MA120 版本' if use_ma120 else '降级 MA20>MA60'}\n\n")

    lines.append("## 一、回测参数（与主回测脚本一致）\n\n")
    lines.append("| 参数 | 取值 |\n| --- | --- |\n")
    lines.append(f"| min_amt_ma20 | {params.min_amt_ma20} |\n")
    lines.append(f"| rs_quantile_min | {params.rs_quantile_min} |\n")
    lines.append(f"| rs_quantile_max | {params.rs_quantile_max} |\n")
    lines.append(f"| min_signal_score | {params.min_signal_score} |\n")
    lines.append(f"| top_k | {params.top_k} |\n")
    lines.append(f"| volume_confirm_ratio (A) | {params.volume_confirm_ratio} |\n")
    lines.append(f"| volume_normal_ratio (B) | {params.volume_normal_ratio} |\n")
    if not use_ma120:
        lines.append(f"| atr_quantile_max | {params.atr_quantile_max} |\n")
        lines.append(f"| box_max_range | {params.box_max_range} |\n")
    lines.append("\n")

    lines.append("## 二、选股漏斗（日线）\n\n")
    lines.append(
        "| 指标 | 数值 |\n| --- | ---: |\n"
        f"| 信号日总数 | {n_sig_days} |\n"
        f"| 进入观察池的交易日数（watchlist_n>0） | {days_pool} |\n"
        f"| 观察池累计条数 | {total_wl} |\n"
        f"| 出现突破+量能确认的交易日数 | {days_confirm} |\n"
        f"| 确认成交总笔数 | {n_trades} |\n"
    )
    if days_pool > 0:
        lines.append(
            f"| 观察池日 → 当日有确认笔数 占比 | {days_confirm / days_pool:.2%} 按天 |\n"
        )
    if total_wl > 0 and n_trades > 0:
        lines.append(f"| 观察池条数 → 确认笔数 条级转化 | {n_trades / total_wl:.2%} |\n")
    lines.append(
        f"| 市场闸门 | 正常 {gate_stats['normal']} 天 / 谨慎 {gate_stats['caution']} 天 / 禁止 {gate_stats['stop']} 天 |\n"
    )
    lines.append("\n")

    lines.append("## 三、确认成交收益（T+1 / T+2 / T+3）\n\n")
    lines.append("### 3.1 触发价入场（与 `confirm_breakout_daily` 一致，主口径）\n\n")
    lines.append("> 自确认日 **触发价** 至其后第 N 个交易日 **收盘**；**不含手续费与滑点**。\n\n")
    lines.append("| 持有期 | 样本数 | 胜率 | 平均收益 | 中位数收益 | PF |\n| --- | ---: | ---: | ---: | ---: | ---: |\n")
    for hn in [1, 2, 3]:
        col = f"ret_t{hn}"
        if df.empty:
            lines.append(f"| T+{hn} | — | — | — | — | — |\n")
            continue
        n, wr, m, med, pf = _stats_row(df[col])
        lines.append(_md_row_tn(f"T+{hn}", n, wr, m, med, pf))

    lines.append("\n### 3.2 开盘价入场（敏感性对比）\n\n")
    lines.append(
        "> 假设确认日 **以开盘价** 即可成交，再持有至第 N 日收盘。"
        "若开盘高于触发价，则等价于「更贵」买入；若低于触发价，则等价于「更便宜」买入。"
        "该口径**不替代**策略的真实挂单逻辑，仅用于与触发价对比。\n\n"
    )
    lines.append("| 持有期 | 样本数 | 胜率 | 平均收益 | 中位数收益 | PF |\n| --- | ---: | ---: | ---: | ---: | ---: |\n")
    for hn in [1, 2, 3]:
        col = f"ret_t{hn}_open"
        if df.empty:
            lines.append(f"| T+{hn} | — | — | — | — | — |\n")
            continue
        n, wr, m, med, pf = _stats_row(df[col])
        lines.append(_md_row_tn(f"T+{hn}", n, wr, m, med, pf))

    if not df.empty and "ret_t1" in df.columns and "ret_t1_open" in df.columns:
        both = df.dropna(subset=["ret_t1", "ret_t1_open"])
        if not both.empty:
            diff = both["ret_t1_open"] - both["ret_t1"]
            lines.append("\n### 3.3 T+1 差异（开盘价收益 − 触发价收益）\n\n")
            lines.append(f"- **可比样本数**：{len(diff)}\n")
            lines.append(f"- **差异均值**：{_fmt_pct(float(diff.mean()))}\n")
            lines.append(f"- **差异中位数**：{_fmt_pct(float(diff.median()))}\n")
            lines.append(
                f"- **开盘价更优（T+1）占比**：{float((diff > 0).mean()):.2%}（"
                "即开盘买入比触发价买入 T+1 收益更高的比例）\n\n"
            )

    if not df.empty:
        lines.append("\n## 四、等权组合（按信号日聚合，T+1）\n\n")
        dr = df.groupby("signal_date")["ret_t1"].mean().dropna().sort_index()
        dr_open = df.groupby("signal_date")["ret_t1_open"].mean().dropna().sort_index()
        if not dr.empty:
            eq = (1.0 + dr).cumprod()
            total_ret = float(eq.iloc[-1] - 1.0)
            mdd = float((eq / eq.cummax() - 1.0).min())
            sharpe = float(dr.mean() / dr.std() * np.sqrt(252)) if dr.std() > 0 else 0.0
            lines.append("### 触发价\n\n")
            lines.append(f"- **区间总收益**：{total_ret:.2%}\n")
            lines.append(f"- **最大回撤**：{mdd:.2%}\n")
            lines.append(f"- **日夏普（年化近似）**：{sharpe:.2f}\n")
            lines.append(f"- **有成交的信号日数**：{len(dr)}\n\n")
        if not dr_open.empty:
            eqo = (1.0 + dr_open).cumprod()
            total_ret_o = float(eqo.iloc[-1] - 1.0)
            mdd_o = float((eqo / eqo.cummax() - 1.0).min())
            sharpe_o = (
                float(dr_open.mean() / dr_open.std() * np.sqrt(252)) if dr_open.std() > 0 else 0.0
            )
            lines.append("### 开盘价（敏感性）\n\n")
            lines.append(f"- **区间总收益**：{total_ret_o:.2%}\n")
            lines.append(f"- **最大回撤**：{mdd_o:.2%}\n")
            lines.append(f"- **日夏普（年化近似）**：{sharpe_o:.2f}\n")
            lines.append(f"- **有成交的信号日数**：{len(dr_open)}\n\n")

        lines.append("## 五、按评分分层（T+1）\n\n")
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

        lines.append("\n## 六、按信号分级（T+1）\n\n")
        lines.append("| 分级 | 笔数 | 胜率 | 均收益 |\n| --- | ---: | ---: | ---: |\n")
        for g in sorted(df["signal_grade"].dropna().unique()):
            v = df.loc[df["signal_grade"] == g, "ret_t1"].dropna()
            if v.empty:
                continue
            lines.append(f"| {g} | {len(v)} | {_fmt_pct((v > 0).mean())} | {_fmt_pct(v.mean())} |\n")

        lines.append("\n## 七、按 RS 横截面分位（T+1）\n\n")
        df2["rs_bin"] = pd.cut(
            df2["rs20_xsec_q"],
            bins=[0, 0.80, 0.85, 0.90, 0.95, 1.01],
            labels=["80-85%", "85-90%", "90-95%", "95-100%", ">100%"],
            right=False,
        )
        lines.append("| RS 分位 | 笔数 | 胜率 | 均收益 |\n| --- | ---: | ---: | ---: |\n")
        for label, grp in df2.groupby("rs_bin", observed=True):
            v = grp["ret_t1"].dropna()
            if v.empty:
                continue
            lines.append(
                f"| {label} | {len(v)} | {_fmt_pct((v > 0).mean())} | {_fmt_pct(v.mean())} |\n"
            )

        lines.append("\n## 八、按行业（确认笔数 Top10，T+1）\n\n")
        ind_rows = []
        for ind_name, grp in df.groupby(df["industry"].fillna("未知")):
            v = grp["ret_t1"].dropna()
            if v.empty:
                continue
            ind_rows.append((ind_name, len(v), float((v > 0).mean()), float(v.mean())))
        ind_rows.sort(key=lambda x: -x[1])
        lines.append("| 行业 | 笔数 | 胜率 | 均收益 |\n| --- | ---: | ---: | ---: |\n")
        for ind_name, n, wr, m in ind_rows[:10]:
            lines.append(f"| {ind_name} | {n} | {_fmt_pct(wr)} | {_fmt_pct(m)} |\n")

        lines.append("\n## 九、按月（T+1）\n\n")
        df2["month"] = df2["signal_date"].astype(str).str[:6]
        lines.append("| 月份 | 笔数 | 胜率 | 均收益 |\n| --- | ---: | ---: | ---: |\n")
        for month, grp in df2.groupby("month"):
            v = grp["ret_t1"].dropna()
            if v.empty:
                continue
            lines.append(
                f"| {month} | {len(v)} | {_fmt_pct((v > 0).mean())} | {_fmt_pct(v.mean())} |\n"
            )

    lines.append("\n## 十、输出文件\n\n")
    lines.append(f"- 逐日漏斗：`{funnel_path}`\n")
    lines.append(
        f"- 成交明细：`{trades_path}`（含 `confirm_open`、`ret_t1_open`~`ret_t3_open` 与触发价口径 `ret_t1`~`ret_t3`）\n"
    )

    report_md = os.path.join(rep_dir, "breakout_daily_backtest_report.md")
    report_stamp = os.path.join(rep_dir, f"breakout_daily_backtest_report_{stamp}.md")
    text = "".join(lines)
    with open(report_md, "w", encoding="utf-8") as f:
        f.write(text)
    with open(report_stamp, "w", encoding="utf-8") as f:
        f.write(text)

    print("\n  [3/3] 报告已生成", flush=True)
    print(f"    {report_md}", flush=True)
    print(f"    {report_stamp}", flush=True)
    print(f"    {funnel_path}", flush=True)
    print("\n" + "=" * 70, flush=True)
    print("  完成", flush=True)
    print("=" * 70, flush=True)


if __name__ == "__main__":
    main()
