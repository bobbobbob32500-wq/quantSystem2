# -*- coding: utf-8 -*-
"""
突破策略：累计净值、滚动胜率 与 上证指数 同图对比

上图：上证指数收盘（左轴，归一化）与策略等权 T+1 净值（右轴，归一化）
下图：按成交时间顺序的滚动胜率（默认近 20 笔交易）
上下两图均叠加：上证 **5 个交易日累计涨跌幅** 分档底色（便于观察策略台阶与大盘环境）

输入：data/reports/breakout_backtest_trades_latest.csv
输出：data/reports/breakout_equity_winrate_vs_sh_index.png
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

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
        return pd.DataFrame(columns=["date", "close"])
    idx["date"] = pd.to_datetime(idx["trade_date"].astype(str), format="%Y%m%d", errors="coerce")
    idx = idx.dropna(subset=["date"]).sort_values("date").copy()
    idx["close"] = idx["close"].astype(float)
    return idx[["date", "close"]]


def _ret5_regime_style(ret5: float) -> tuple[str, float]:
    """上证近 5 个交易日累计涨跌幅分档 → (底色, alpha)。"""
    if pd.isna(ret5):
        return "#E8E8E8", 0.22
    if ret5 >= 0.02:
        return "#FFCCCC", 0.38
    if ret5 >= 0.0:
        return "#FFE9CC", 0.36
    if ret5 > -0.02:
        return "#E8F5E9", 0.34
    return "#C5D9F0", 0.38


def paint_sh_ret5_background(
    ax,
    idx_full: pd.DataFrame,
    x_min: pd.Timestamp,
    x_max: pd.Timestamp,
    zorder: float = 0,
) -> None:
    """
    按交易日绘制竖条底色：每个 [t_i, t_{i+1}) 使用 t_i 当日收盘可算的 ret5。
    """
    ic = idx_full.sort_values("date").reset_index(drop=True)
    if len(ic) < 2:
        return
    ic["ret5"] = ic["close"] / ic["close"].shift(5) - 1.0
    dates = ic["date"].values
    for i in range(len(ic) - 1):
        d0 = pd.Timestamp(dates[i])
        d1 = pd.Timestamp(dates[i + 1])
        if d1 <= x_min or d0 >= x_max:
            continue
        r = float(ic.iloc[i]["ret5"]) if pd.notna(ic.iloc[i]["ret5"]) else float("nan")
        face, alpha = _ret5_regime_style(r)
        ax.axvspan(d0, d1, facecolor=face, alpha=alpha, linewidth=0, zorder=zorder)


def main() -> None:
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    rep_dir = os.path.join(root, "data", "reports")
    trades_path = os.path.join(rep_dir, "breakout_backtest_trades_latest.csv")
    if not os.path.exists(trades_path):
        raise FileNotFoundError(f"请先运行日线回测报告生成：{trades_path}")

    df = pd.read_csv(trades_path)
    if df.empty or "ret_t1" not in df.columns:
        raise RuntimeError("成交明细为空或缺少 ret_t1")

    df["signal_date"] = pd.to_datetime(df["signal_date"].astype(str), format="%Y%m%d", errors="coerce")
    df["confirm_date"] = pd.to_datetime(df["confirm_date"].astype(str), format="%Y%m%d", errors="coerce")
    df = df.dropna(subset=["signal_date", "ret_t1"]).copy()

    # 与报告一致：按信号日等权 T+1，无交易日收益记 0（净值走平）
    daily_ret = df.groupby("signal_date")["ret_t1"].mean().sort_index()

    start_s = daily_ret.index.min().strftime("%Y%m%d")
    end_s = daily_ret.index.max().strftime("%Y%m%d")
    # 向前多取若干自然日，保证首段也有 ret5
    pad_start = (pd.Timestamp(start_s) - pd.Timedelta(days=45)).strftime("%Y%m%d")

    config = ConfigManager()
    db = DatabaseManager(config)
    idx_full = load_sh_index(db, pad_start, end_s)
    if idx_full.empty:
        raise RuntimeError("未查询到上证指数 000001.SH，请先回填指数日线。")

    ts_start = pd.Timestamp(start_s)
    ts_end = pd.Timestamp(end_s)
    idx = idx_full[(idx_full["date"] >= ts_start) & (idx_full["date"] <= ts_end)].copy()
    if idx.empty:
        raise RuntimeError("指数在回测窗口内无数据。")

    all_days = idx.set_index("date")["close"].copy()
    port = pd.Series(0.0, index=all_days.index)
    for d, r in daily_ret.items():
        ts = pd.Timestamp(d)
        if ts in port.index:
            port.loc[ts] = float(r)
    equity = (1.0 + port).cumprod()

    idx_norm = all_days / float(all_days.iloc[0])
    eq_norm = equity / float(equity.iloc[0])

    # 滚动胜率：按确认日序，每笔 T+1 是否盈利
    tr = df.sort_values(["confirm_date", "ts_code"]).reset_index(drop=True)
    win_roll = []
    roll_n = 20
    for i in range(len(tr)):
        lo = max(0, i - roll_n + 1)
        chunk = tr.loc[lo : i + 1, "ret_t1"]
        win_roll.append(float((chunk > 0).mean()))
    tr["_roll_win_rate"] = win_roll

    fig, (ax_top, ax_bot) = plt.subplots(
        2,
        1,
        sharex=True,
        figsize=(14, 8),
        gridspec_kw={"height_ratios": [2.0, 1.0], "hspace": 0.12},
        layout="constrained",
    )

    x_min = all_days.index.min()
    x_max = all_days.index.max()
    paint_sh_ret5_background(ax_top, idx_full, x_min, x_max, zorder=0)
    paint_sh_ret5_background(ax_bot, idx_full, x_min, x_max, zorder=0)

    color_idx = "#E15759"
    color_eq = "#4C78A8"
    ax_top.plot(
        all_days.index,
        idx_norm.values,
        color=color_idx,
        linewidth=1.6,
        label="上证收盘(归一化)",
        zorder=3,
    )
    ax_top.set_ylabel("上证（起点=1）", color=color_idx)
    ax_top.tick_params(axis="y", labelcolor=color_idx)
    ax_top.grid(axis="y", linestyle="--", alpha=0.3, zorder=2)

    ax2 = ax_top.twinx()
    ax2.plot(
        eq_norm.index,
        eq_norm.values,
        color=color_eq,
        linewidth=1.8,
        label="策略等权T+1净值(归一化)",
        zorder=3,
    )
    ax2.set_ylabel("策略净值（起点=1）", color=color_eq)
    ax2.tick_params(axis="y", labelcolor=color_eq)
    ax_top.set_title("突破策略 vs 上证指数：归一化走势对比（底色=上证5日涨跌幅分档）")
    lines1, lab1 = ax_top.get_legend_handles_labels()
    lines2, lab2 = ax2.get_legend_handles_labels()
    patch_leg = [
        mpatches.Patch(facecolor=c, edgecolor="none", alpha=0.45, label=lab)
        for lab, c in [
            ("5日≥+2%", "#FFCCCC"),
            ("5日[0,+2%)", "#FFE9CC"),
            ("5日(-2%,0)", "#E8F5E9"),
            ("5日≤-2%", "#C5D9F0"),
            ("不足5日", "#E8E8E8"),
        ]
    ]
    ax_top.legend(
        lines1 + lines2 + patch_leg,
        lab1 + lab2 + [p.get_label() for p in patch_leg],
        loc="upper left",
        fontsize=8,
        ncol=2,
    )

    ax_bot.axhline(0.5, color="#999", linestyle=":", linewidth=1)
    ax_bot.plot(
        tr["confirm_date"],
        tr["_roll_win_rate"],
        color="#59A14F",
        linewidth=1.4,
        drawstyle="steps-post",
        label=f"滚动胜率（近{roll_n}笔，按确认日序）",
        zorder=3,
    )
    ax_bot.set_ylabel("胜率")
    ax_bot.set_ylim(0, 1.02)
    ax_bot.set_xlabel("日期")
    ax_bot.legend(loc="upper left", fontsize=9)
    ax_bot.grid(axis="y", linestyle="--", alpha=0.25)
    ax_bot.set_title("单票 T+1 滚动胜率（每笔对应一笔确认成交；底色同上）")

    out_path = os.path.join(rep_dir, "breakout_equity_winrate_vs_sh_index.png")
    fig.savefig(out_path, dpi=150)
    plt.close(fig)

    print("已生成:", out_path)
    print(
        f"区间: {start_s} -> {end_s} | 上证涨跌: {idx_norm.iloc[-1] - 1:.2%} | 策略净值涨跌: {eq_norm.iloc[-1] - 1:.2%}"
    )
    print(f"全样本 T+1 胜率: {(df['ret_t1'] > 0).mean():.2%} | 成交笔数: {len(df)}")


if __name__ == "__main__":
    main()
