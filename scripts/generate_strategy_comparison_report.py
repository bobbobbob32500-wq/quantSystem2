# -*- coding: utf-8 -*-
"""
生成「突破策略」与「主板二次启动策略」在同一数据窗口下的对比统计报告。

输出：data/reports/strategy_comparison_report.md（及带时间戳副本）
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
from src.modules.breakout_strategy import BreakoutStrategy, BreakoutParams
from src.modules.mainboard_secondary_launch_backtester import MainboardSecondaryLaunchBacktester
from src.modules.mainboard_secondary_launch_strategy import (
    MainboardSecondaryLaunchStrategy,
    StrategyParams,
)


def _ret_stats(valid: pd.Series) -> dict:
    valid = valid.dropna()
    if valid.empty:
        return {
            "n": 0,
            "win_rate": float("nan"),
            "mean": float("nan"),
            "median": float("nan"),
            "pf": float("nan"),
        }
    n = int(len(valid))
    win_rate = float((valid > 0).mean())
    mean = float(valid.mean())
    median = float(valid.median())
    gross_win = float(valid[valid > 0].sum())
    gross_loss = float(-valid[valid < 0].sum())
    pf = gross_win / gross_loss if gross_loss > 1e-12 else 0.0
    return {"n": n, "win_rate": win_rate, "mean": mean, "median": median, "pf": pf}


def _build_price_map(features: pd.DataFrame) -> dict:
    price_df = features[["ts_code", "trade_date", "open", "close"]].copy()
    price_df = price_df.sort_values(["ts_code", "trade_date"]).reset_index(drop=True)
    price_map = {}
    for code, sub in price_df.groupby("ts_code"):
        sub = sub.sort_values("trade_date").reset_index(drop=True)
        sub["date_str"] = sub["trade_date"].dt.strftime("%Y%m%d")
        sub["trade_date"] = pd.to_datetime(sub["trade_date"])
        price_map[code] = sub
    return price_map


def _secondary_gross_returns(signals: pd.DataFrame, price_map: dict) -> pd.DataFrame:
    """二次启动：与回测器一致，信号日当日开盘价入场，统计 T+1/T+2/T+3 收盘相对入场开盘的毛收益。"""
    rows = []
    for _, sig in signals.iterrows():
        code = sig["ts_code"]
        sdate = pd.Timestamp(sig["signal_date"])
        sub = price_map.get(code)
        if sub is None or sub.empty:
            continue
        s = sub[sub["trade_date"] >= sdate].reset_index(drop=True)
        if len(s) < 4:
            continue
        o0 = float(s.iloc[0]["open"])
        if o0 <= 0:
            continue
        r1 = float(s.iloc[1]["close"]) / o0 - 1.0
        r2 = float(s.iloc[2]["close"]) / o0 - 1.0
        r3 = float(s.iloc[3]["close"]) / o0 - 1.0
        rows.append(
            {
                "signal_date": sdate.strftime("%Y%m%d"),
                "ts_code": code,
                "ret_t1": r1,
                "ret_t2": r2,
                "ret_t3": r3,
            }
        )
    return pd.DataFrame(rows)


def _run_breakout_collect(
    strategy: BreakoutStrategy,
    features: pd.DataFrame,
    price_map: dict,
    all_dates: list,
    signal_dates: list,
    use_ma120: bool,
) -> tuple[pd.DataFrame, dict]:
    date_pos = {d: i for i, d in enumerate(all_dates)}
    all_trades = []
    meta = {
        "total_watchlist_entries": 0,
        "days_with_watchlist": 0,
        "dates_with_confirm": 0,
        "gate_stats": {"normal": 0, "caution": 0, "stop": 0},
        "grade_counts": {"A": 0, "B": 0},
    }
    params = strategy.params

    for td in signal_dates:
        snapshot = strategy._build_snapshot(features, td)
        if snapshot.empty:
            continue
        filtered = strategy._layer_base_filter(snapshot)
        if filtered.empty:
            continue
        if use_ma120:
            filtered = strategy._layer_trend_filter(filtered)
        else:
            cond = (
                filtered["ma20"].notna()
                & filtered["ma60"].notna()
                & (filtered["ma20"] > filtered["ma60"])
                & (filtered["ma20_slope"].fillna(-1) > 0)
            )
            filtered = filtered.loc[cond].copy()
        if filtered.empty:
            continue
        filtered = strategy._layer_strength_filter(filtered)
        if filtered.empty:
            continue
        if use_ma120:
            filtered = strategy._layer_stability_filter(filtered)
        else:
            p = strategy.params
            cond = filtered["box_range"].notna() & (filtered["box_range"] <= p.box_max_range)
            if filtered["atr_ratio_q60"].notna().mean() > 0.3:
                cond = cond & (filtered["atr_ratio_q60"].fillna(0.5) <= p.atr_quantile_max)
            filtered = filtered.loc[cond].copy()
        if filtered.empty:
            continue
        scored = strategy._compute_scores(filtered)
        min_score, top_k = strategy._market_gate(features, td)
        if min_score >= 999 or top_k <= 0:
            meta["gate_stats"]["stop"] += 1
            continue
        elif min_score > strategy.params.min_signal_score:
            meta["gate_stats"]["caution"] += 1
        else:
            meta["gate_stats"]["normal"] += 1
        scored = scored[scored["signal_score"] >= min_score].copy()
        if scored.empty:
            continue
        scored = scored.sort_values("signal_score", ascending=False).head(top_k)
        pos = date_pos.get(td)
        if pos is None or pos + 1 >= len(all_dates):
            continue
        next_d = all_dates[pos + 1]
        confirm_map = strategy.bars_dict_for_trade_date(features, next_d)
        watch_items = strategy._to_watch_items(scored, td)
        meta["total_watchlist_entries"] += len(watch_items)
        meta["days_with_watchlist"] += 1
        confirmed = strategy.confirm_breakout_daily(watch_items, confirm_map)
        if not confirmed:
            continue
        meta["dates_with_confirm"] += 1
        for sig in confirmed:
            code = sig.ts_code
            sub = price_map.get(code)
            if sub is None:
                continue
            match_idx = sub.index[sub["date_str"] == sig.confirm_date]
            if len(match_idx) == 0:
                continue
            confirm_idx = int(match_idx[0])
            entry_price = float(sig.entry_price)
            if entry_price <= 0:
                continue
            gname = sig.signal_grade
            meta["grade_counts"][gname] = meta["grade_counts"].get(gname, 0) + 1
            trade_record = {
                "signal_date": td,
                "confirm_date": sig.confirm_date,
                "ts_code": code,
                "signal_score": float(sig.signal_score),
                "signal_grade": sig.signal_grade,
                "entry_price": entry_price,
            }
            for hold_n in [1, 2, 3]:
                target_idx = confirm_idx + hold_n
                if target_idx < len(sub):
                    exit_close = float(sub.loc[target_idx, "close"])
                    trade_record[f"ret_t{hold_n}"] = exit_close / entry_price - 1.0
                else:
                    trade_record[f"ret_t{hold_n}"] = np.nan
            all_trades.append(trade_record)

    df = pd.DataFrame(all_trades)
    return df, meta


def _fmt_pct(x: float) -> str:
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return "—"
    return f"{x:.2%}"


def main() -> None:
    config = ConfigManager()
    db = DatabaseManager(config)

    info = db.query(
        "SELECT MIN(trade_date) as min_d, MAX(trade_date) as max_d, "
        "COUNT(DISTINCT trade_date) as days FROM stock_daily"
    )
    min_d, max_d, total_days = info[0]["min_d"], info[0]["max_d"], info[0]["days"]

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
    else:
        print("数据不足，无法生成报告")
        return

    if len(all_dates) <= warmup_skip + 10:
        print("数据不足（warmup），无法生成报告")
        return

    backtest_dates = all_dates[warmup_skip:]
    signal_dates = backtest_dates[:-3]

    params = BreakoutParams()
    params.min_amt_ma20 = 8e4
    params.rs_quantile_max = 0.97
    params.min_signal_score = 60.0
    params.top_k = 15
    params.volume_confirm_ratio = 1.2
    params.volume_normal_ratio = 1.0
    if not use_ma120:
        params.atr_quantile_max = 0.50
        params.box_max_range = 0.08
    strategy = BreakoutStrategy(db=db, params=params)

    print("正在计算突破策略因子...", flush=True)
    raw_daily, raw_basic = strategy._load_data(max_d)
    if raw_daily.empty:
        print("日线数据为空")
        return
    features = strategy._compute_features(raw_daily, raw_basic, max_d)
    price_map_bo = _build_price_map(features)

    bo_df, bo_meta = _run_breakout_collect(
        strategy, features, price_map_bo, all_dates, signal_dates, use_ma120
    )

    start_s = str(signal_dates[0])
    end_s = str(signal_dates[-1])
    window_start = pd.Timestamp(datetime.strptime(start_s, "%Y%m%d"))
    window_end = pd.Timestamp(datetime.strptime(end_s, "%Y%m%d"))

    sec_strategy = MainboardSecondaryLaunchStrategy(StrategyParams())
    sec_bt = MainboardSecondaryLaunchBacktester(db, sec_strategy)
    print("正在加载二次启动策略数据并生成信号...", flush=True)
    data_sec = sec_bt.load_data(
        start_date=start_s,
        end_date=end_s,
        warmup_days=90,
        forward_days=10,
    )
    daily_s, basic_s = data_sec["daily"], data_sec["basic"]
    if daily_s.empty:
        print("二次启动：日线为空，仅输出突破侧统计")
        features_sec = pd.DataFrame()
        signals_sec = pd.DataFrame()
    else:
        features_sec = sec_strategy.prepare_features(daily_s, basic_s)
        signals_sec = sec_strategy.generate_signals(features_sec)
        if not signals_sec.empty:
            signals_sec["signal_date"] = pd.to_datetime(signals_sec["signal_date"])
            signals_sec = signals_sec[
                (signals_sec["signal_date"] >= window_start)
                & (signals_sec["signal_date"] <= window_end)
            ].copy()

    price_map_sec = _build_price_map(features_sec) if not features_sec.empty else {}
    sec_ret_df = (
        _secondary_gross_returns(signals_sec, price_map_sec)
        if not signals_sec.empty
        else pd.DataFrame()
    )

    # Markdown
    lines = []
    lines.append("# 策略对比统计报告\n")
    lines.append(f"- **生成时间**：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
    lines.append(f"- **数据库日线范围**：{min_d} → {max_d}（共 {total_days} 个交易日）\n")
    lines.append(f"- **本报告统一回测窗口**：{start_s} → {end_s}（信号日 {len(signal_dates)} 天）\n")
    lines.append(f"- **Warmup 跳过**：前 {warmup_skip} 个交易日；末尾保留 3 个交易日作为持有退出空间\n")
    lines.append("\n## 口径说明\n\n")
    lines.append(
        "| 策略 | 「信号」含义 | 「买入/成交」含义 | T+1/T+2/T+3 收益定义 |\n"
        "| --- | --- | --- | --- |\n"
        "| **突破策略** | 当日通过评分与市场闸门后进入**次日观察池**的标的条数（累计） | 下一交易日 **突破 pivot+缓冲 且量能达标** 的确认成交笔数 | 自**确认日触发价**至其后第 N 个交易日**收盘**的涨跌幅（**不含手续费**，与 `run_breakout_backtest.py` 一致） |\n"
        "| **二次启动** | 日线层输出的**候选信号条数**（可多日多票） | 本报告将每条日线信号对应 **1 笔模拟入场**（与回测器一致：**信号日开盘价**买入） | 自**信号日开盘价**至其后第 **N** 个交易日**收盘**的涨跌幅（**毛收益**，不计费以便与突破侧可比） |\n"
    )
    lines.append("\n> 说明：突破策略的「信号」为观察池规模；二次启动的「信号」为日线筛选结果。两者业务含义不同，**不宜直接比较绝对条数**，宜对比各自样本内的胜率与收益分布。\n")

    lines.append("\n## 一、突破策略（选强 → 等突破）\n\n")
    lines.append(f"- **观察池累计条数**：{bo_meta['total_watchlist_entries']}（出现在 **{bo_meta['days_with_watchlist']}** 个交易日中）\n")
    lines.append(
        f"- **市场闸门**：正常 {bo_meta['gate_stats']['normal']} 天 / 谨慎 {bo_meta['gate_stats']['caution']} 天 / 禁止开仓 {bo_meta['gate_stats']['stop']} 天\n"
    )
    lines.append(f"- **有突破确认成交的交易日数**：{bo_meta['dates_with_confirm']}\n")
    lines.append(
        f"- **突破+量能确认买入笔数**：{len(bo_df)}（A 级 {bo_meta['grade_counts'].get('A', 0)} / B 级 {bo_meta['grade_counts'].get('B', 0)}）\n"
    )

    lines.append("\n| 持有期 | 样本数 | 胜率 | 平均收益 | 中位数收益 | 盈亏比(PF) |\n| --- | ---: | ---: | ---: | ---: | ---: |\n")
    for hn in [1, 2, 3]:
        col = f"ret_t{hn}"
        st = _ret_stats(bo_df[col]) if not bo_df.empty else _ret_stats(pd.Series(dtype=float))
        lines.append(
            f"| T+{hn} | {st['n']} | {_fmt_pct(st['win_rate'])} | {_fmt_pct(st['mean'])} | {_fmt_pct(st['median'])} | {st['pf']:.2f} |\n"
        )

    lines.append("\n## 二、主板二次启动策略\n\n")
    lines.append(f"- **日线信号条数（窗口内）**：{len(signals_sec)}\n")
    lines.append(f"- **可计算 T+1~T+3 毛收益的样本数**：{len(sec_ret_df)}（需信号日后至少 3 个完整交易日）\n")

    lines.append("\n| 持有期 | 样本数 | 胜率 | 平均收益 | 中位数收益 | 盈亏比(PF) |\n| --- | ---: | ---: | ---: | ---: | ---: |\n")
    for hn in [1, 2, 3]:
        col = f"ret_t{hn}"
        st = _ret_stats(sec_ret_df[col]) if not sec_ret_df.empty else _ret_stats(pd.Series(dtype=float))
        lines.append(
            f"| T+{hn} | {st['n']} | {_fmt_pct(st['win_rate'])} | {_fmt_pct(st['mean'])} | {_fmt_pct(st['median'])} | {st['pf']:.2f} |\n"
        )

    lines.append("\n## 三、摘要对比（同窗口、毛收益口径）\n\n")
    lines.append("| 策略 | 买入/成交笔数 | T+1 胜率 | T+1 均收益 | T+3 胜率 | T+3 均收益 |\n| --- | ---: | ---: | ---: | ---: | ---: |\n")
    b1 = _ret_stats(bo_df["ret_t1"]) if not bo_df.empty else _ret_stats(pd.Series(dtype=float))
    b3 = _ret_stats(bo_df["ret_t3"]) if not bo_df.empty else _ret_stats(pd.Series(dtype=float))
    s1 = _ret_stats(sec_ret_df["ret_t1"]) if not sec_ret_df.empty else _ret_stats(pd.Series(dtype=float))
    s3 = _ret_stats(sec_ret_df["ret_t3"]) if not sec_ret_df.empty else _ret_stats(pd.Series(dtype=float))
    lines.append(
        f"| 突破确认 | {len(bo_df)} | {_fmt_pct(b1['win_rate'])} | {_fmt_pct(b1['mean'])} | {_fmt_pct(b3['win_rate'])} | {_fmt_pct(b3['mean'])} |\n"
    )
    lines.append(
        f"| 二次启动 | {len(sec_ret_df)} | {_fmt_pct(s1['win_rate'])} | {_fmt_pct(s1['mean'])} | {_fmt_pct(s3['win_rate'])} | {_fmt_pct(s3['mean'])} |\n"
    )
    lines.append(
        "\n> 二次启动行内「笔数」为可算满 T+3 的样本数；突破行内为确认成交笔数。若需二次启动全量信号的净收益（含滑点与费率），请使用 `MainboardSecondaryLaunchBacktester.run_backtest`。\n"
    )

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    rep_dir = os.path.join(root, "data", "reports")
    os.makedirs(rep_dir, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path_latest = os.path.join(rep_dir, "strategy_comparison_report.md")
    path_stamp = os.path.join(rep_dir, f"strategy_comparison_report_{stamp}.md")
    text = "".join(lines)
    with open(path_latest, "w", encoding="utf-8") as f:
        f.write(text)
    with open(path_stamp, "w", encoding="utf-8") as f:
        f.write(text)

    if not bo_df.empty:
        bo_df.to_csv(
            os.path.join(rep_dir, "strategy_comparison_breakout_trades_latest.csv"),
            index=False,
            encoding="utf-8-sig",
        )
    if not sec_ret_df.empty:
        sec_ret_df.to_csv(
            os.path.join(rep_dir, "strategy_comparison_secondary_returns_latest.csv"),
            index=False,
            encoding="utf-8-sig",
        )

    print("\n报告已写入:", flush=True)
    print(" ", path_latest, flush=True)
    print(" ", path_stamp, flush=True)
    print("\n预览:\n", flush=True)
    print(text[:2500], flush=True)
    if len(text) > 2500:
        print("\n...（后略）", flush=True)


if __name__ == "__main__":
    main()
