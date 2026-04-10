# -*- coding: utf-8 -*-
"""
突破策略确认成交分布可视化

输入：
  data/reports/strategy_comparison_breakout_trades_latest.csv

输出：
  data/reports/breakout_confirm_daily_count.png
  data/reports/breakout_confirm_weekly_count.png
  data/reports/breakout_confirm_weekly_quality.png
"""

from __future__ import annotations

import os
from datetime import datetime

import matplotlib.pyplot as plt
import pandas as pd

plt.rcParams["font.sans-serif"] = [
    "Microsoft YaHei",
    "SimHei",
    "Noto Sans CJK SC",
    "Arial Unicode MS",
    "DejaVu Sans",
]
plt.rcParams["axes.unicode_minus"] = False


def _load_trades(path: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    if df.empty:
        return df
    df["confirm_date"] = pd.to_datetime(
        df["confirm_date"].astype(str), format="%Y%m%d", errors="coerce"
    )
    df = df.dropna(subset=["confirm_date"]).copy()
    return df


def _plot_daily_count(df: pd.DataFrame, out_path: str) -> None:
    daily_cnt = df.groupby("confirm_date").size().rename("count").reset_index()
    fig, ax = plt.subplots(figsize=(12, 4))
    ax.bar(daily_cnt["confirm_date"], daily_cnt["count"], color="#4C78A8")
    ax.set_title("突破策略：按日确认成交笔数")
    ax.set_xlabel("确认日期")
    ax.set_ylabel("成交笔数")
    ax.grid(axis="y", linestyle="--", alpha=0.3)
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)


def _plot_weekly_count(df: pd.DataFrame, out_path: str) -> None:
    wk = df.copy()
    wk["week_start"] = wk["confirm_date"].dt.to_period("W-MON").dt.start_time
    weekly_cnt = wk.groupby("week_start").size().rename("count").reset_index()

    fig, ax = plt.subplots(figsize=(12, 4))
    ax.bar(weekly_cnt["week_start"], weekly_cnt["count"], color="#59A14F")
    ax.set_title("突破策略：按周确认成交笔数")
    ax.set_xlabel("周起始日")
    ax.set_ylabel("成交笔数")
    ax.grid(axis="y", linestyle="--", alpha=0.3)
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)


def _plot_weekly_quality(df: pd.DataFrame, out_path: str) -> None:
    wk = df.copy()
    wk["week_start"] = wk["confirm_date"].dt.to_period("W-MON").dt.start_time
    weekly_q = (
        wk.groupby("week_start")
        .agg(
            trades=("ret_t1", "count"),
            win_rate=("ret_t1", lambda s: (s > 0).mean()),
            mean_ret=("ret_t1", "mean"),
        )
        .reset_index()
    )

    fig, ax1 = plt.subplots(figsize=(12, 4))
    ax1.plot(
        weekly_q["week_start"],
        weekly_q["win_rate"] * 100,
        marker="o",
        color="#E15759",
        label="T+1胜率(%)",
    )
    ax1.set_ylabel("T+1胜率(%)", color="#E15759")
    ax1.tick_params(axis="y", labelcolor="#E15759")
    ax1.set_xlabel("周起始日")
    ax1.grid(axis="y", linestyle="--", alpha=0.25)

    ax2 = ax1.twinx()
    ax2.plot(
        weekly_q["week_start"],
        weekly_q["mean_ret"] * 100,
        marker="s",
        linestyle="--",
        color="#F28E2B",
        label="T+1均收益(%)",
    )
    ax2.set_ylabel("T+1均收益(%)", color="#F28E2B")
    ax2.tick_params(axis="y", labelcolor="#F28E2B")

    plt.title("突破策略：周度质量（T+1胜率 + T+1均收益）")
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)


def main() -> None:
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    report_dir = os.path.join(root, "data", "reports")
    src_path = os.path.join(report_dir, "strategy_comparison_breakout_trades_latest.csv")
    if not os.path.exists(src_path):
        raise FileNotFoundError(
            f"未找到输入文件：{src_path}。请先运行策略对比报告脚本生成成交明细。"
        )

    df = _load_trades(src_path)
    if df.empty:
        raise RuntimeError("输入成交文件为空，无法绘图。")

    daily_png = os.path.join(report_dir, "breakout_confirm_daily_count.png")
    weekly_png = os.path.join(report_dir, "breakout_confirm_weekly_count.png")
    quality_png = os.path.join(report_dir, "breakout_confirm_weekly_quality.png")

    _plot_daily_count(df, daily_png)
    _plot_weekly_count(df, weekly_png)
    _plot_weekly_quality(df, quality_png)

    print("图表已生成：")
    print(" ", daily_png)
    print(" ", weekly_png)
    print(" ", quality_png)
    print(f"样本区间：{df['confirm_date'].min().date()} -> {df['confirm_date'].max().date()}")
    print(f"确认成交总笔数：{len(df)}")
    print(f"确认成交交易日数：{df['confirm_date'].nunique()}")
    print(f"生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")


if __name__ == "__main__":
    main()
