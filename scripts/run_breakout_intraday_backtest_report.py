# -*- coding: utf-8 -*-
"""
突破策略分钟级回放回测。

口径：
1. 先按历史交易日运行突破策略，生成当日盘前观察池；
2. 仅在下一交易日使用分钟级数据重放盘中买点；
3. 第一次满足突破条件的分钟 bar 记为成交；
4. 统计入场当日收盘及后续 1/2/3 个交易日收益。

输出：
  data/reports/breakout_intraday_backtest_trades_latest.csv
  data/reports/breakout_intraday_backtest_summary_latest.md
"""

from __future__ import annotations

import os
import sqlite3
import sys
from dataclasses import asdict
from datetime import datetime
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.core.config import ConfigManager
from src.core.database import DatabaseManager
from src.modules.breakout_strategy import BreakoutParams, BreakoutStrategy, WatchItem


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPORT_DIR = os.path.join(ROOT, "data", "reports")
INTRADAY_DB = os.path.join(ROOT, "data", "history_recommendation.db")


def _is_mainboard_symbol(symbol: str) -> bool:
    text = str(symbol or "").upper()
    if text.endswith(".SH"):
        return text[:3] in {"600", "601", "603", "605"}
    if text.endswith(".SZ"):
        return text[:3] in {"000", "001", "002", "003"}
    return False


def _normalize_ymd(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    digits = "".join(ch for ch in text if ch.isdigit())
    return digits[:8] if len(digits) >= 8 else ""


def _load_intraday() -> Tuple[pd.DataFrame, pd.DataFrame]:
    conn = sqlite3.connect(INTRADAY_DB)
    intraday = pd.read_sql_query(
        """
        SELECT symbol, trade_date, trade_time, open, high, low, close, volume
        FROM intraday_data
        ORDER BY symbol, trade_date, trade_time
        """,
        conn,
    )
    recommendations = pd.read_sql_query(
        """
        SELECT symbol, recommendation_date, strategy_type, buy_date, status
        FROM recommendations
        """,
        conn,
    )
    conn.close()

    intraday["trade_date"] = intraday["trade_date"].map(_normalize_ymd)
    intraday["trade_time"] = pd.to_datetime(intraday["trade_time"], errors="coerce")
    intraday = intraday.dropna(subset=["trade_time"]).copy()
    intraday = intraday[intraday["symbol"].map(_is_mainboard_symbol)].copy()

    recommendations["recommendation_date"] = recommendations["recommendation_date"].map(
        _normalize_ymd
    )
    recommendations["buy_date"] = recommendations["buy_date"].map(_normalize_ymd)
    recommendations = recommendations[recommendations["symbol"].map(_is_mainboard_symbol)].copy()
    return intraday, recommendations


def _find_valid_daily_dates(db: DatabaseManager) -> Tuple[List[str], pd.DataFrame]:
    rows = db.query(
        """
        SELECT trade_date, COUNT(*) AS n_rows, COUNT(DISTINCT ts_code) AS n_symbols
        FROM stock_daily
        GROUP BY trade_date
        ORDER BY trade_date
        """
    )
    coverage = pd.DataFrame(rows)
    coverage["trade_date"] = coverage["trade_date"].astype(str)
    rolling_ref = (
        coverage["n_symbols"]
        .rolling(window=21, center=True, min_periods=5)
        .median()
        .bfill()
        .ffill()
    )
    coverage["rolling_ref"] = rolling_ref
    threshold = np.maximum(1000.0, coverage["rolling_ref"] * 0.5)
    coverage["is_valid"] = coverage["n_symbols"] >= threshold
    valid_dates = coverage.loc[coverage["is_valid"], "trade_date"].tolist()
    return valid_dates, coverage


def _prepare_strategy_and_features(
    db: DatabaseManager,
    valid_dates: List[str],
    max_end_date: str,
) -> Tuple[BreakoutStrategy, pd.DataFrame, List[str], int]:
    params = BreakoutParams()
    params.min_amt_ma20 = 8e4
    params.rs_quantile_max = 0.97
    params.rs_quantile_min = 0.80
    params.min_signal_score = 60.0
    params.top_k = 20

    strategy = BreakoutStrategy(db=db, params=params)
    raw_daily, raw_basic = strategy._load_data(max_end_date)
    if raw_daily.empty:
        raise RuntimeError("stock_daily 为空，无法回测")

    raw_daily["trade_date"] = raw_daily["trade_date"].astype(str)
    raw_daily = raw_daily[raw_daily["trade_date"].isin(valid_dates)].copy()
    features = strategy._compute_features(raw_daily, raw_basic, max_end_date)
    features = features[
        features["trade_date"].dt.strftime("%Y%m%d").isin(valid_dates)
    ].copy()

    all_dates = sorted(valid_dates)
    warmup_skip = 125 if len(all_dates) >= 180 else 65
    return strategy, features, all_dates, warmup_skip


def _build_snapshot_map(features: pd.DataFrame, signal_date: str) -> pd.DataFrame:
    target = pd.Timestamp(signal_date)
    snap = (
        features[features["trade_date"] == target]
        .copy()
        .sort_values("ts_code")
        .reset_index(drop=True)
    )
    return snap


def _build_price_map(features: pd.DataFrame) -> Dict[str, pd.DataFrame]:
    price_df = features[["ts_code", "trade_date", "open", "close"]].copy()
    price_df = price_df.sort_values(["ts_code", "trade_date"]).reset_index(drop=True)
    price_map: Dict[str, pd.DataFrame] = {}
    for code, sub in price_df.groupby("ts_code"):
        sub = sub.copy()
        sub["date_str"] = sub["trade_date"].dt.strftime("%Y%m%d")
        price_map[code] = sub.reset_index(drop=True)
    return price_map


def _build_intraday_group_map(intraday: pd.DataFrame) -> Dict[Tuple[str, str], pd.DataFrame]:
    grouped: Dict[Tuple[str, str], pd.DataFrame] = {}
    for (symbol, trade_date), sub in intraday.groupby(["symbol", "trade_date"], sort=False):
        ordered = sub.sort_values("trade_time").reset_index(drop=True).copy()
        ordered["cum_high"] = ordered["high"].cummax()
        ordered["cum_volume"] = ordered["volume"].cumsum()
        grouped[(symbol, trade_date)] = ordered
    return grouped


def _first_intraday_breakout(
    item: WatchItem,
    bars: pd.DataFrame,
    vol_ma20_prev: float,
    trade_date: str,
    params: BreakoutParams,
) -> dict | None:
    if bars.empty or vol_ma20_prev <= 0:
        return None

    open_price = float(bars.iloc[0]["open"] or 0)
    if open_price <= 0:
        return None

    trigger = float(item.pivot) * (1 + params.breakout_buffer)
    max_entry = float(item.pivot) * (1 + params.breakout_max_chase)

    for _, row in bars.iterrows():
        ts = row["trade_time"]
        hm = ts.hour * 100 + ts.minute
        if hm < 935 or hm > 1450:
            continue

        high = float(row["cum_high"] or 0)
        if high < trigger:
            continue

        entry_price = trigger
        if entry_price > max_entry or entry_price > high:
            continue

        if (high / open_price - 1.0) > params.max_intraday_gain:
            continue

        # intraday_data.volume is in shares, stock_daily.vol_ma20 is in lots (100 shares).
        vol_ratio = (float(row["cum_volume"] or 0) / 100.0) / float(vol_ma20_prev)
        if vol_ratio < params.volume_normal_ratio:
            continue

        if vol_ratio >= params.volume_confirm_ratio:
            grade = "A"
            pos_ratio = 1.0
            confirm_type = "breakout+volume"
        else:
            grade = "B"
            pos_ratio = 0.5
            confirm_type = "breakout"

        return {
            "confirm_date": trade_date,
            "confirm_time": ts.strftime("%H:%M:%S"),
            "entry_price": round(entry_price, 4),
            "entry_bar_close": float(row["close"]),
            "volume_ratio": round(vol_ratio, 4),
            "signal_grade": grade,
            "position_ratio": pos_ratio,
            "confirm_type": confirm_type,
            "day_open": open_price,
            "day_high_at_signal": high,
        }

    return None


def _calc_forward_returns(
    price_map: Dict[str, pd.DataFrame],
    ts_code: str,
    entry_date: str,
    entry_price: float,
) -> dict:
    result = {
        "ret_close0": np.nan,
        "ret_t1": np.nan,
        "ret_t2": np.nan,
        "ret_t3": np.nan,
    }
    sub = price_map.get(ts_code)
    if sub is None or entry_price <= 0:
        return result
    idx_match = sub.index[sub["date_str"] == entry_date]
    if len(idx_match) == 0:
        return result

    entry_idx = int(idx_match[0])
    same_close = float(sub.loc[entry_idx, "close"])
    if same_close > 0:
        result["ret_close0"] = same_close / entry_price - 1.0

    for hold_n in [1, 2, 3]:
        target_idx = entry_idx + hold_n
        if target_idx < len(sub):
            exit_close = float(sub.loc[target_idx, "close"])
            if exit_close > 0:
                result[f"ret_t{hold_n}"] = exit_close / entry_price - 1.0
    return result


def _metric_line(series: pd.Series) -> dict:
    vals = series.dropna()
    if vals.empty:
        return {
            "n": 0,
            "win_rate": np.nan,
            "mean_ret": np.nan,
            "median_ret": np.nan,
            "pf": np.nan,
        }
    gains = float(vals[vals > 0].sum())
    losses = float(-vals[vals < 0].sum())
    return {
        "n": int(len(vals)),
        "win_rate": float((vals > 0).mean()),
        "mean_ret": float(vals.mean()),
        "median_ret": float(vals.median()),
        "pf": (gains / losses) if losses > 1e-12 else np.nan,
    }


def _portfolio_stats(trades_df: pd.DataFrame, col: str, weighted: bool) -> dict:
    if trades_df.empty or col not in trades_df.columns:
        return {"total_ret": np.nan, "mdd": np.nan, "sharpe": np.nan}
    temp = trades_df.dropna(subset=[col]).copy()
    if temp.empty:
        return {"total_ret": np.nan, "mdd": np.nan, "sharpe": np.nan}

    if weighted:
        temp["weighted_ret"] = temp[col] * temp["position_ratio"]
        daily_ret = temp.groupby("signal_date")["weighted_ret"].mean().sort_index()
    else:
        daily_ret = temp.groupby("signal_date")[col].mean().sort_index()

    if daily_ret.empty:
        return {"total_ret": np.nan, "mdd": np.nan, "sharpe": np.nan}
    equity = (1.0 + daily_ret).cumprod()
    return {
        "total_ret": float(equity.iloc[-1] - 1.0),
        "mdd": float((equity / equity.cummax() - 1.0).min()),
        "sharpe": float(daily_ret.mean() / daily_ret.std() * np.sqrt(252))
        if daily_ret.std() > 1e-12
        else np.nan,
    }


def _fmt_pct(value: float) -> str:
    return "NA" if pd.isna(value) else f"{value * 100:.2f}%"


def _fmt_num(value: float) -> str:
    return "NA" if pd.isna(value) else f"{value:.2f}"


def main() -> None:
    os.makedirs(REPORT_DIR, exist_ok=True)

    config = ConfigManager()
    db = DatabaseManager(config)
    intraday, recommendations = _load_intraday()
    intraday_dates = sorted(set(intraday["trade_date"]))
    intraday_symbols = set(intraday["symbol"])

    if not intraday_dates:
        raise RuntimeError("分钟级数据库为空，无法执行回测")

    valid_dates, coverage = _find_valid_daily_dates(db)
    max_end_date = intraday_dates[-1]
    valid_dates = [d for d in valid_dates if d <= max_end_date]

    strategy, features, all_dates, warmup_skip = _prepare_strategy_and_features(
        db, valid_dates, max_end_date
    )
    price_map = _build_price_map(features)
    intraday_map = _build_intraday_group_map(intraday)
    date_pos = {d: i for i, d in enumerate(all_dates)}
    intraday_date_set = set(intraday_dates)

    candidate_signal_dates = []
    for d in all_dates[warmup_skip:-1]:
        pos = date_pos[d]
        next_d = all_dates[pos + 1]
        if next_d in intraday_date_set:
            candidate_signal_dates.append(d)

    trades: List[dict] = []
    watch_rows: List[dict] = []

    for idx, signal_date in enumerate(candidate_signal_dates, start=1):
        if idx % 20 == 0:
            print(f"[progress] {idx}/{len(candidate_signal_dates)} signal dates", flush=True)

        watch_items = strategy.select_watchlist_from_features(features, signal_date)
        if not watch_items:
            continue

        next_d = all_dates[date_pos[signal_date] + 1]
        snapshot = _build_snapshot_map(features, signal_date).set_index("ts_code", drop=False)

        for item in watch_items:
            watch_rows.append(
                {
                    "signal_date": signal_date,
                    "entry_date": next_d,
                    "ts_code": item.ts_code,
                    "name": item.name,
                    "signal_score": item.signal_score,
                    "trigger_price": item.trigger_price,
                    "pivot": item.pivot,
                    "has_intraday_symbol": item.ts_code in intraday_symbols,
                    "has_intraday_entry_date": next_d in intraday_date_set,
                }
            )

            bars = intraday_map.get((item.ts_code, next_d))
            if bars is None:
                continue

            prev_row = snapshot.loc[item.ts_code] if item.ts_code in snapshot.index else None
            if prev_row is None:
                continue
            vol_ma20_prev = float(prev_row.get("vol_ma20") or 0)
            trade_sig = _first_intraday_breakout(
                item=item,
                bars=bars,
                vol_ma20_prev=vol_ma20_prev,
                trade_date=next_d,
                params=strategy.params,
            )
            if trade_sig is None:
                continue

            forward = _calc_forward_returns(
                price_map=price_map,
                ts_code=item.ts_code,
                entry_date=next_d,
                entry_price=float(trade_sig["entry_price"]),
            )

            record = {
                "signal_date": signal_date,
                "entry_date": next_d,
                "ts_code": item.ts_code,
                "name": item.name,
                "industry": item.industry,
                "signal_score": item.signal_score,
                "pivot": item.pivot,
                "trigger_price": item.trigger_price,
                "stop_loss": item.stop_loss,
                "rs20_xsec_q": item.rs20_xsec_q,
                "box_range": item.box_range,
                "vol_ma20_prev": vol_ma20_prev,
                **trade_sig,
                **forward,
            }
            trades.append(record)

    trades_df = pd.DataFrame(trades)
    watch_df = pd.DataFrame(watch_rows)

    raw_cov = coverage.copy()
    abnormal_dates = raw_cov.loc[~raw_cov["is_valid"], ["trade_date", "n_symbols"]]

    coverage_summary = {
        "intraday_dates": len(intraday_dates),
        "intraday_symbols": len(intraday_symbols),
        "intraday_rows": int(len(intraday)),
        "recommendations_rows": int(len(recommendations)),
        "candidate_signal_dates": len(candidate_signal_dates),
        "watch_rows": int(len(watch_df)),
        "trade_rows": int(len(trades_df)),
        "watch_dates_with_trades": int(trades_df["signal_date"].nunique()) if not trades_df.empty else 0,
        "abnormal_daily_dates": abnormal_dates.to_dict("records"),
    }

    metrics_cols = ["ret_close0", "ret_t1", "ret_t2", "ret_t3"]
    metrics = {col: _metric_line(trades_df[col]) if not trades_df.empty else _metric_line(pd.Series(dtype=float)) for col in metrics_cols}
    weighted_port = {col: _portfolio_stats(trades_df, col, weighted=True) for col in metrics_cols}
    raw_port = {col: _portfolio_stats(trades_df, col, weighted=False) for col in metrics_cols}

    grade_stats = {}
    if not trades_df.empty and "signal_grade" in trades_df.columns:
        for grade, sub in trades_df.groupby("signal_grade"):
            grade_stats[grade] = _metric_line(sub["ret_t1"])

    strategy_type_counts = (
        recommendations["strategy_type"].fillna("NA").value_counts().sort_index().to_dict()
        if not recommendations.empty
        else {}
    )

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    trades_latest = os.path.join(REPORT_DIR, "breakout_intraday_backtest_trades_latest.csv")
    trades_stamp = os.path.join(REPORT_DIR, f"breakout_intraday_backtest_trades_{stamp}.csv")
    summary_latest = os.path.join(REPORT_DIR, "breakout_intraday_backtest_summary_latest.md")
    summary_stamp = os.path.join(REPORT_DIR, f"breakout_intraday_backtest_summary_{stamp}.md")

    if not trades_df.empty:
        trades_df = trades_df.sort_values(["signal_date", "entry_date", "ts_code"]).reset_index(drop=True)
    trades_df.to_csv(trades_latest, index=False, encoding="utf-8-sig")
    trades_df.to_csv(trades_stamp, index=False, encoding="utf-8-sig")

    overlap_note = (
        "分钟级数据库只覆盖 121 个交易日、185 只股票，属于部分样本，不是全市场分钟库。"
        "因此本回测反映的是“数据库可回放样本”上的策略表现。"
    )

    lines = [
        "# Breakout Intraday Backtest Summary",
        "",
        "## Data Scope",
        f"- Intraday rows: {coverage_summary['intraday_rows']}",
        f"- Intraday trade dates: {coverage_summary['intraday_dates']}",
        f"- Intraday symbols: {coverage_summary['intraday_symbols']}",
        f"- Recommendations rows in intraday DB: {coverage_summary['recommendations_rows']}",
        f"- Recommendation strategy types: {strategy_type_counts}",
        f"- Candidate signal dates with next-day intraday coverage: {coverage_summary['candidate_signal_dates']}",
        f"- Watchlist rows generated by breakout strategy: {coverage_summary['watch_rows']}",
        f"- Intraday breakout trades replayed: {coverage_summary['trade_rows']}",
        f"- Watch dates with at least one trade: {coverage_summary['watch_dates_with_trades']}",
        f"- Abnormal partial stock_daily dates removed: {coverage_summary['abnormal_daily_dates']}",
        f"- Note: {overlap_note}",
        "",
        "## Performance",
    ]

    for col in metrics_cols:
        m = metrics[col]
        wp = weighted_port[col]
        rp = raw_port[col]
        lines.extend(
            [
                f"### {col}",
                f"- Trades: {m['n']}",
                f"- Win rate: {_fmt_pct(m['win_rate'])}",
                f"- Mean return: {_fmt_pct(m['mean_ret'])}",
                f"- Median return: {_fmt_pct(m['median_ret'])}",
                f"- Profit factor: {_fmt_num(m['pf'])}",
                f"- Equal-weight portfolio total return: {_fmt_pct(rp['total_ret'])}",
                f"- Equal-weight portfolio max drawdown: {_fmt_pct(rp['mdd'])}",
                f"- Equal-weight portfolio sharpe: {_fmt_num(rp['sharpe'])}",
                f"- Position-weighted portfolio total return: {_fmt_pct(wp['total_ret'])}",
                f"- Position-weighted portfolio max drawdown: {_fmt_pct(wp['mdd'])}",
                f"- Position-weighted portfolio sharpe: {_fmt_num(wp['sharpe'])}",
                "",
            ]
        )

    lines.append("## Grade Breakdown (T+1)")
    if grade_stats:
        for grade, m in sorted(grade_stats.items()):
            lines.append(
                f"- Grade {grade}: n={m['n']}, win={_fmt_pct(m['win_rate'])}, "
                f"mean={_fmt_pct(m['mean_ret'])}, pf={_fmt_num(m['pf'])}"
            )
    else:
        lines.append("- No trades")

    summary_text = "\n".join(lines) + "\n"
    with open(summary_latest, "w", encoding="utf-8") as f:
        f.write(summary_text)
    with open(summary_stamp, "w", encoding="utf-8") as f:
        f.write(summary_text)

    print(summary_text)
    print(trades_latest)
    print(summary_latest)


if __name__ == "__main__":
    main()
