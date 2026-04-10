# -*- coding: utf-8 -*-
"""
突破策略确认成交数量 vs 上证指数 环境对比图

输出：
  data/reports/breakout_confirm_vs_sh_index_daily.png
  data/reports/breakout_confirm_vs_sh_index_weekly.png
  data/reports/breakout_confirm_vs_sh_index_analysis.md
"""

from __future__ import annotations

import os
import sys
from datetime import datetime

import matplotlib.pyplot as plt
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.core.config import ConfigManager
from src.core.database import DatabaseManager

plt.rcParams["font.sans-serif"] = [
    "Microsoft YaHei",
    "SimHei",
    "Noto Sans CJK SC",
    "Arial Unicode MS",
    "DejaVu Sans",
]
plt.rcParams["axes.unicode_minus"] = False


def load_breakout_confirm_count(csv_path: str) -> pd.DataFrame:
    df = pd.read_csv(csv_path)
    if df.empty:
        return pd.DataFrame(columns=["date", "confirm_count"])
    df["confirm_date"] = pd.to_datetime(
        df["confirm_date"].astype(str), format="%Y%m%d", errors="coerce"
    )
    df = df.dropna(subset=["confirm_date"]).copy()
    cnt = (
        df.groupby("confirm_date")
        .size()
        .rename("confirm_count")
        .reset_index()
        .rename(columns={"confirm_date": "date"})
        .sort_values("date")
    )
    return cnt


def load_sh_index(db: DatabaseManager, start_date: str, end_date: str) -> pd.DataFrame:
    sql_stock = """
    SELECT trade_date, close
    FROM stock_daily
    WHERE ts_code = '000001.SH'
      AND trade_date >= ?
      AND trade_date <= ?
    ORDER BY trade_date
    """
    sql_index = """
    SELECT trade_date, close
    FROM index_daily
    WHERE ts_code = '000001.SH'
      AND trade_date >= ?
      AND trade_date <= ?
    ORDER BY trade_date
    """
    rows_stock = db.query(sql_stock, (start_date, end_date))
    table_rows = db.query(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='index_daily'"
    )
    if table_rows:
        rows_index = db.query(sql_index, (start_date, end_date))
    else:
        rows_index = []
    rows = rows_index if len(rows_index) >= len(rows_stock) else rows_stock
    idx = pd.DataFrame(rows)
    if idx.empty:
        return pd.DataFrame(columns=["date", "close", "ret1"])
    idx["date"] = pd.to_datetime(idx["trade_date"].astype(str), format="%Y%m%d", errors="coerce")
    idx = idx.dropna(subset=["date"]).sort_values("date").copy()
    idx["close"] = idx["close"].astype(float)
    idx["ret1"] = idx["close"].pct_change()
    return idx[["date", "close", "ret1"]]


def plot_daily_compare(merged: pd.DataFrame, out_path: str) -> None:
    fig, ax1 = plt.subplots(figsize=(13, 5))
    ax1.bar(
        merged["date"],
        merged["confirm_count"],
        color="#4C78A8",
        alpha=0.65,
        label="突破确认笔数(日)",
    )
    ax1.set_ylabel("确认笔数")
    ax1.set_xlabel("日期")
    ax1.grid(axis="y", linestyle="--", alpha=0.25)

    ax2 = ax1.twinx()
    ax2.plot(
        merged["date"],
        merged["close"],
        color="#E15759",
        linewidth=1.8,
        label="上证指数收盘",
    )
    ax2.set_ylabel("上证指数")
    plt.title("突破确认数量 vs 上证指数（日度）")
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)


def plot_weekly_compare(merged: pd.DataFrame, out_path: str) -> pd.DataFrame:
    wk = merged.copy()
    wk["week_start"] = wk["date"].dt.to_period("W-MON").dt.start_time
    weekly = (
        wk.groupby("week_start", as_index=False)
        .agg(
            confirm_count=("confirm_count", "sum"),
            sh_close=("close", "last"),
            sh_ret=("ret1", "sum"),
        )
        .sort_values("week_start")
    )
    weekly["confirm_count_ma3"] = weekly["confirm_count"].rolling(3).mean()
    weekly["sh_ret_ma3"] = weekly["sh_ret"].rolling(3).mean()

    fig, ax1 = plt.subplots(figsize=(13, 5))
    ax1.bar(
        weekly["week_start"],
        weekly["confirm_count"],
        color="#59A14F",
        alpha=0.70,
        label="突破确认笔数(周)",
    )
    ax1.plot(
        weekly["week_start"],
        weekly["confirm_count_ma3"],
        color="#2F855A",
        linewidth=1.8,
        label="确认笔数3周均线",
    )
    ax1.set_ylabel("周确认笔数")
    ax1.set_xlabel("周")
    ax1.grid(axis="y", linestyle="--", alpha=0.25)

    ax2 = ax1.twinx()
    ax2.plot(
        weekly["week_start"],
        weekly["sh_close"],
        color="#F28E2B",
        linewidth=1.8,
        label="上证指数周收盘",
    )
    ax2.set_ylabel("上证指数")
    plt.title("突破确认数量 vs 上证指数（周度）")
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)
    return weekly


def build_analysis(merged: pd.DataFrame, weekly: pd.DataFrame, out_path: str) -> str:
    day_corr = (
        merged["confirm_count"].corr(merged["ret1"])
        if len(merged.dropna(subset=["confirm_count", "ret1"])) > 1
        else float("nan")
    )
    weekly_corr = (
        weekly["confirm_count"].corr(weekly["sh_ret"])
        if len(weekly.dropna(subset=["confirm_count", "sh_ret"])) > 1
        else float("nan")
    )
    weekly_corr_ma = (
        weekly["confirm_count_ma3"].corr(weekly["sh_ret_ma3"])
        if len(weekly.dropna(subset=["confirm_count_ma3", "sh_ret_ma3"])) > 1
        else float("nan")
    )

    # 上涨日/下跌日分组
    up = merged[merged["ret1"] > 0]
    down = merged[merged["ret1"] < 0]
    flat = merged[merged["ret1"] == 0]
    up_avg = float(up["confirm_count"].mean()) if len(up) else 0.0
    down_avg = float(down["confirm_count"].mean()) if len(down) else 0.0
    flat_avg = float(flat["confirm_count"].mean()) if len(flat) else 0.0

    # 强/弱周分组
    strong_week = weekly[weekly["sh_ret"] > 0]
    weak_week = weekly[weekly["sh_ret"] <= 0]
    strong_avg = float(strong_week["confirm_count"].mean()) if len(strong_week) else 0.0
    weak_avg = float(weak_week["confirm_count"].mean()) if len(weak_week) else 0.0

    txt = []
    txt.append("# 突破确认数量与大盘环境关系分析\n\n")
    txt.append(f"- 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
    txt.append(
        f"- 样本区间：{merged['date'].min().date()} -> {merged['date'].max().date()}，"
        f"共 {len(merged)} 个交易日，{len(weekly)} 个自然周\n\n"
    )
    txt.append("## 定量关系\n\n")
    if len(merged) < 20:
        txt.append(
            "> 警告：当前数据库内可用的上证指数样本过少，以下统计仅供参考，建议补齐指数日线后再解读。\n\n"
        )
    txt.append(f"- 日度相关系数：`corr(确认笔数, 上证日收益) = {day_corr:.3f}`\n")
    txt.append(f"- 周度相关系数：`corr(周确认笔数, 上证周收益) = {weekly_corr:.3f}`\n")
    txt.append(f"- 3周平滑相关：`corr(确认笔数3周均线, 上证周收益3周均线) = {weekly_corr_ma:.3f}`\n\n")
    txt.append("## 分组观察\n\n")
    txt.append(f"- 上证上涨日：平均确认笔数 `{up_avg:.2f}`\n")
    txt.append(f"- 上证下跌日：平均确认笔数 `{down_avg:.2f}`\n")
    txt.append(f"- 上证平盘日：平均确认笔数 `{flat_avg:.2f}`\n")
    txt.append(f"- 上证上涨周：平均周确认笔数 `{strong_avg:.2f}`\n")
    txt.append(f"- 上证下跌/震荡周：平均周确认笔数 `{weak_avg:.2f}`\n\n")
    txt.append("## 结论解读\n\n")
    txt.append(
        "- 相关系数若为正，说明大盘走强时，突破确认数量通常会增加；"
        "若绝对值不大，说明关系存在但并非单一线性驱动（板块轮动、个股结构同样关键）。\n"
    )
    txt.append(
        "- 周度相关通常比日度更稳定，建议在实盘中以“周度确认热度 + 大盘周趋势”联合作为仓位调节依据。\n"
    )

    content = "".join(txt)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(content)
    return content


def main() -> None:
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    report_dir = os.path.join(root, "data", "reports")
    src_path = os.path.join(report_dir, "strategy_comparison_breakout_trades_latest.csv")
    if not os.path.exists(src_path):
        raise FileNotFoundError(
            f"未找到输入文件：{src_path}。请先运行策略对比报告脚本。"
        )

    raw = pd.read_csv(src_path)
    confirm_cnt = load_breakout_confirm_count(src_path)
    if confirm_cnt.empty:
        raise RuntimeError("突破确认成交文件为空，无法分析。")

    # 区间使用策略回测窗口（signal_date），避免只分析有确认成交的稀疏子区间
    if "signal_date" in raw.columns and not raw["signal_date"].dropna().empty:
        signal_dates = pd.to_datetime(
            raw["signal_date"].astype(str), format="%Y%m%d", errors="coerce"
        ).dropna()
        start_s = signal_dates.min().strftime("%Y%m%d")
        end_s = signal_dates.max().strftime("%Y%m%d")
    else:
        start_s = confirm_cnt["date"].min().strftime("%Y%m%d")
        end_s = confirm_cnt["date"].max().strftime("%Y%m%d")
    config = ConfigManager()
    db = DatabaseManager(config)
    idx = load_sh_index(db, start_s, end_s)
    if idx.empty:
        raise RuntimeError("未查询到上证指数数据（000001.SH）。")

    merged = idx.merge(confirm_cnt, on="date", how="left")
    merged["confirm_count"] = merged["confirm_count"].fillna(0.0)
    merged = merged.sort_values("date").reset_index(drop=True)

    daily_png = os.path.join(report_dir, "breakout_confirm_vs_sh_index_daily.png")
    weekly_png = os.path.join(report_dir, "breakout_confirm_vs_sh_index_weekly.png")
    analysis_md = os.path.join(report_dir, "breakout_confirm_vs_sh_index_analysis.md")

    plot_daily_compare(merged, daily_png)
    weekly = plot_weekly_compare(merged, weekly_png)
    content = build_analysis(merged, weekly, analysis_md)

    print("输出文件：")
    print(" ", daily_png)
    print(" ", weekly_png)
    print(" ", analysis_md)
    print("\n分析摘要：")
    print(content[:1200])


if __name__ == "__main__":
    main()
