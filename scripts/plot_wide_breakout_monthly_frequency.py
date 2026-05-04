# -*- coding: utf-8 -*-
"""
宽进突破（wide_pool_strict_entry_v2）— 按月统计「成交笔数」与「有推荐信号日数」并出图。

默认合并已有回测 CSV（1–2 月 + 3–4 月漏斗）；可加 --refresh 先全窗重算再绘图。

输出：
  data/reports/wide_breakout_monthly_frequency.png（上图：成交按确认月 vs 按信号月；下图：有推荐日 / 有买点成交日）
  data/reports/wide_breakout_monthly_frequency.csv
"""

from __future__ import annotations

import argparse
import glob
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

plt.rcParams["font.sans-serif"] = [
    "Microsoft YaHei",
    "SimHei",
    "Noto Sans CJK SC",
    "Arial Unicode MS",
    "DejaVu Sans",
]
plt.rcParams["axes.unicode_minus"] = False


def _ym(s: str) -> str:
    x = str(s).strip()
    return x[:6] if len(x) >= 6 else x


def _month_label(ym: str) -> str:
    if len(ym) == 6 and ym.isdigit():
        return f"{ym[:4]}-{ym[4:6]}"
    return ym


def load_merged_data(
    root: str,
    trades_paths: list[str],
    funnel_paths: list[str],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    tframes = []
    for p in trades_paths:
        fp = os.path.join(root, p) if not os.path.isabs(p) else p
        if os.path.isfile(fp):
            tframes.append(pd.read_csv(fp, encoding="utf-8-sig"))
    trades = pd.concat(tframes, ignore_index=True) if tframes else pd.DataFrame()
    if not trades.empty and "confirm_date" in trades.columns:
        trades = trades.drop_duplicates(
            subset=["signal_date", "confirm_date", "ts_code"], keep="first"
        )

    fframes = []
    for p in funnel_paths:
        fp = os.path.join(root, p) if not os.path.isabs(p) else p
        if os.path.isfile(fp):
            fframes.append(pd.read_csv(fp, encoding="utf-8-sig"))
    funnel = pd.concat(fframes, ignore_index=True) if fframes else pd.DataFrame()
    if not funnel.empty and "signal_date" in funnel.columns:
        funnel = funnel.drop_duplicates(subset=["signal_date"], keep="first")
        funnel = funnel.sort_values("signal_date").reset_index(drop=True)

    return trades, funnel


def monthly_stats(trades: pd.DataFrame, funnel: pd.DataFrame) -> pd.DataFrame:
    months: list[str] = []
    if not funnel.empty and "signal_date" in funnel.columns:
        funnel = funnel.copy()
        funnel["_ym"] = funnel["signal_date"].map(_ym)
        months = sorted(funnel["_ym"].dropna().unique())
    if not trades.empty:
        if "confirm_date" in trades.columns:
            tym_c = trades["confirm_date"].map(_ym)
            months = sorted(set(months) | set(tym_c.dropna().unique()))
        if "signal_date" in trades.columns:
            tym_s = trades["signal_date"].map(_ym)
            months = sorted(set(months) | set(tym_s.dropna().unique()))

    rows = []
    for ym in months:
        n_trade_confirm = 0
        n_trade_signal = 0
        if not trades.empty and "confirm_date" in trades.columns:
            n_trade_confirm = int((trades["confirm_date"].map(_ym) == ym).sum())
        if not trades.empty and "signal_date" in trades.columns:
            n_trade_signal = int((trades["signal_date"].map(_ym) == ym).sum())
        n_rec = 0
        n_confirm_day = 0
        if not funnel.empty:
            sub = funnel[funnel["signal_date"].map(_ym) == ym]
            if "watchlist_n" in sub.columns:
                n_rec = int((sub["watchlist_n"].fillna(0) > 0).sum())
            if "confirmed_n" in sub.columns:
                n_confirm_day = int((sub["confirmed_n"].fillna(0) > 0).sum())
        rows.append(
            {
                "月份": _month_label(str(ym)),
                "YM": ym,
                "成交笔数_确认月": n_trade_confirm,
                "成交笔数_信号月": n_trade_signal,
                "有推荐信号日数": n_rec,
                "有买点成交日数": n_confirm_day,
            }
        )
    return pd.DataFrame(rows)


def _annotate_bars(ax, bars) -> None:
    for r in bars:
        h = r.get_height()
        if h > 0:
            ax.annotate(
                f"{int(h)}",
                xy=(r.get_x() + r.get_width() / 2, h),
                ha="center",
                va="bottom",
                fontsize=8,
            )


def plot_frequency(df: pd.DataFrame, out_png: str, title: str) -> None:
    if df.empty:
        raise RuntimeError("无月度数据，无法绘图")

    x = np.arange(len(df))
    labels = df["月份"].tolist()
    w = 0.35

    fig, (ax_a, ax_b) = plt.subplots(2, 1, figsize=(10, 8.5), sharex=True)

    b1 = ax_a.bar(x - w / 2, df["成交笔数_确认月"], width=w, label="成交笔数（按确认日月份）", color="#2E86AB")
    b1b = ax_a.bar(x + w / 2, df["成交笔数_信号月"], width=w, label="成交笔数（按信号日月份）", color="#44AF69", alpha=0.9)
    ax_a.set_ylabel("笔数")
    ax_a.set_title(title + " — 成交")
    ax_a.legend(loc="upper left")
    ax_a.grid(axis="y", linestyle="--", alpha=0.35)
    ax_a.set_axisbelow(True)
    _annotate_bars(ax_a, b1)
    _annotate_bars(ax_a, b1b)

    w2 = 0.35
    b2 = ax_b.bar(x - w2 / 2, df["有推荐信号日数"], width=w2, label="有推荐信号日数", color="#A23B72", alpha=0.85)
    b3 = ax_b.bar(x + w2 / 2, df["有买点成交日数"], width=w2, label="有买点成交日数", color="#F18F01", alpha=0.9)
    ax_b.set_xticks(x)
    ax_b.set_xticklabels(labels)
    ax_b.set_ylabel("天数")
    ax_b.set_title("漏斗（均按信号日所在月）")
    ax_b.legend(loc="upper left")
    ax_b.grid(axis="y", linestyle="--", alpha=0.35)
    ax_b.set_axisbelow(True)
    _annotate_bars(ax_b, b2)
    _annotate_bars(ax_b, b3)

    fig.suptitle(
        "宽进突破 wide_pool_strict_entry_v2：跨月确认时，成交在「确认月」与「信号月」可能不同",
        fontsize=9,
        y=1.01,
    )
    fig.tight_layout()
    fig.savefig(out_png, dpi=150, bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser(description="宽进突破按月成交/推荐频率图")
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="先运行 run_wide_breakout_window_backtest.py（20260101～20260410）再读最新 CSV",
    )
    parser.add_argument(
        "--start-date",
        default="20260101",
        help="重算时信号日起（YYYYMMDD）",
    )
    parser.add_argument(
        "--end-date",
        default="20260410",
        help="重算时信号日止（YYYYMMDD）",
    )
    args = parser.parse_args()

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    rep = os.path.join(root, "data", "reports")
    os.makedirs(rep, exist_ok=True)

    if args.refresh:
        script = os.path.join(root, "scripts", "run_wide_breakout_window_backtest.py")
        subprocess.check_call(
            [
                sys.executable,
                script,
                "--start-date",
                args.start_date,
                "--end-date",
                args.end_date,
            ],
            cwd=root,
        )
        funnels = sorted(
            glob.glob(os.path.join(rep, "wide_breakout_backtest_funnel_*.csv")),
            key=os.path.getmtime,
        )
        trades_files = sorted(
            glob.glob(os.path.join(rep, "wide_breakout_backtest_trades_*.csv")),
            key=os.path.getmtime,
        )
        if not funnels or not trades_files:
            raise RuntimeError("重算后未找到漏斗或成交 CSV")
        trades, funnel = load_merged_data(
            root, [trades_files[-1]], [funnels[-1]]
        )
    else:
        # 合并已产出的 1–2 月 + 3–4 月漏斗；成交明细仅 1–2 月文件（3–4 月无成交）
        trades, funnel = load_merged_data(
            root,
            trades_paths=["data/reports/wide_breakout_backtest_trades_20260411_194231.csv"],
            funnel_paths=[
                "data/reports/wide_breakout_backtest_funnel_20260411_194231.csv",
                "data/reports/wide_breakout_backtest_funnel_20260411_185800.csv",
            ],
        )

    stat = monthly_stats(trades, funnel)
    out_csv = os.path.join(rep, "wide_breakout_monthly_frequency.csv")
    out_png = os.path.join(rep, "wide_breakout_monthly_frequency.png")
    stat.to_csv(out_csv, index=False, encoding="utf-8-sig")

    title = "宽进突破（wide_pool_strict_entry_v2）月度分布"
    plot_frequency(stat, out_png, title)

    print("已写入:", out_csv)
    print("已写入:", out_png)
    print(stat.to_string(index=False))


if __name__ == "__main__":
    main()
