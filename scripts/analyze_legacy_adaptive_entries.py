from __future__ import annotations

import argparse
import json
import math
import os
import sqlite3
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.modules.optimized_buy_signals import IntradayData, OptimizedBuySignals


DEFAULT_HORIZONS = [2, 3, 5]
PRIMARY_HORIZON = 2


@dataclass
class EntrySignal:
    template_name: str
    entry_time: str
    entry_price: float
    entry_index: int
    entry_label: str


def _norm_date(value: object) -> Optional[str]:
    if value is None:
        return None
    digits = "".join(ch for ch in str(value).strip() if ch.isdigit())
    if len(digits) < 8:
        return None
    return digits[:8]


def _to_trade_date(digits: str) -> str:
    return f"{digits[:4]}-{digits[4:6]}-{digits[6:8]}"


def _fmt_pct(value: float) -> str:
    return f"{value * 100:.2f}%"


def _fmt_ratio(value: float) -> str:
    return f"{value * 100:.2f}%"


def _safe_float(value: object, default: float = 0.0) -> float:
    try:
        result = float(value)
        if math.isnan(result) or math.isinf(result):
            return default
        return result
    except Exception:
        return default


def _infer_interval_minutes(session_df: pd.DataFrame) -> int:
    if len(session_df) < 2:
        return 5
    timestamps = pd.to_datetime(session_df["trade_time"], errors="coerce").dropna()
    if len(timestamps) < 2:
        return 5
    diffs = timestamps.diff().dropna()
    if diffs.empty:
        return 5
    minutes = diffs.dt.total_seconds() / 60.0
    minutes = minutes[minutes > 0]
    if minutes.empty:
        return 5
    return max(1, int(round(float(minutes.median()))))


def _running_vwap(frame: pd.DataFrame) -> np.ndarray:
    price = frame["close"].astype(float).to_numpy()
    volume = frame["volume"].fillna(0.0).astype(float).to_numpy()
    cumulative_amount = np.cumsum(price * volume)
    cumulative_volume = np.cumsum(volume)
    return np.divide(
        cumulative_amount,
        np.where(cumulative_volume <= 0, np.nan, cumulative_volume),
    )


def _build_intraday_input(frame: pd.DataFrame) -> IntradayData:
    ordered = frame.sort_values("trade_time").reset_index(drop=True)
    return IntradayData(
        price=ordered["close"].astype(float).to_numpy(),
        volume=ordered["volume"].fillna(0.0).astype(float).to_numpy(),
        high=ordered["high"].fillna(ordered["close"]).astype(float).to_numpy(),
        low=ordered["low"].fillna(ordered["close"]).astype(float).to_numpy(),
        timestamp=pd.to_datetime(ordered["trade_time"]).to_numpy(),
    )


def _load_recommendations(
    conn: sqlite3.Connection,
    start_date: Optional[str],
    end_date: Optional[str],
    top_n: int,
) -> pd.DataFrame:
    sql = """
        SELECT symbol, name, recommendation_date, recommendation_score
        FROM recommendations
        WHERE 1=1
    """
    params: List[object] = []
    if start_date:
        sql += " AND recommendation_date >= ?"
        params.append(start_date)
    if end_date:
        sql += " AND recommendation_date <= ?"
        params.append(end_date)
    sql += " ORDER BY recommendation_date ASC, recommendation_score DESC, symbol ASC"

    df = pd.read_sql(sql, conn, params=params)
    if df.empty:
        return df
    df["rec_date"] = df["recommendation_date"].map(_norm_date)
    df = df.dropna(subset=["rec_date"])
    if top_n > 0:
        df = (
            df.sort_values(["rec_date", "recommendation_score", "symbol"], ascending=[True, False, True])
            .groupby("rec_date", group_keys=False)
            .head(top_n)
            .reset_index(drop=True)
        )
    return df


def _load_trade_calendar(conn: sqlite3.Connection) -> List[str]:
    rows = conn.execute("SELECT DISTINCT trade_date FROM stock_daily ORDER BY trade_date").fetchall()
    return [str(row[0]) for row in rows]


def _load_intraday_map(
    conn: sqlite3.Connection,
    symbols: List[str],
    date_min: str,
    date_max: str,
) -> Dict[Tuple[str, str], pd.DataFrame]:
    if not symbols:
        return {}
    placeholders = ",".join(["?"] * len(symbols))
    sql = f"""
        SELECT symbol, trade_time, trade_date, open, high, low, close, volume, amount
        FROM intraday_data
        WHERE symbol IN ({placeholders})
          AND trade_date >= ?
          AND trade_date <= ?
        ORDER BY symbol ASC, trade_date ASC, trade_time ASC
    """
    params = list(symbols) + [date_min, date_max]
    df = pd.read_sql_query(sql, conn, params=params)
    if df.empty:
        return {}

    for col in ("open", "high", "low", "close", "volume", "amount"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df["trade_time"] = pd.to_datetime(df["trade_time"], errors="coerce")
    df = df.dropna(subset=["trade_time", "open", "high", "low", "close"])

    data_map: Dict[Tuple[str, str], pd.DataFrame] = {}
    for (symbol, trade_date), group in df.groupby(["symbol", "trade_date"], sort=False):
        data_map[(str(symbol), str(trade_date))] = group.sort_values("trade_time").reset_index(drop=True)
    return data_map


def _load_daily_map(
    conn: sqlite3.Connection,
    symbols: List[str],
    date_min: str,
    date_max: str,
) -> Dict[Tuple[str, str], Dict[str, float]]:
    if not symbols:
        return {}
    placeholders = ",".join(["?"] * len(symbols))
    sql = f"""
        SELECT ts_code, trade_date, open, high, low, close
        FROM stock_daily
        WHERE ts_code IN ({placeholders})
          AND trade_date >= ?
          AND trade_date <= ?
    """
    params = list(symbols) + [date_min, date_max]
    df = pd.read_sql_query(sql, conn, params=params)
    if df.empty:
        return {}

    for col in ("open", "high", "low", "close"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["open", "high", "low", "close"])
    result: Dict[Tuple[str, str], Dict[str, float]] = {}
    for row in df.to_dict("records"):
        result[(str(row["ts_code"]), str(row["trade_date"]))] = {
            "open": float(row["open"]),
            "high": float(row["high"]),
            "low": float(row["low"]),
            "close": float(row["close"]),
        }
    return result


def _simulate_open_buy(session_df: pd.DataFrame) -> Optional[EntrySignal]:
    if session_df.empty:
        return None
    first = session_df.iloc[0]
    price = _safe_float(first["open"], 0.0)
    if price <= 0:
        return None
    return EntrySignal(
        template_name="open_buy",
        entry_time=str(first["trade_time"]),
        entry_price=price,
        entry_index=0,
        entry_label="首根开盘价",
    )


def _simulate_first_bar_close(session_df: pd.DataFrame) -> Optional[EntrySignal]:
    if session_df.empty:
        return None
    first = session_df.iloc[0]
    price = _safe_float(first["close"], 0.0)
    if price <= 0:
        return None
    return EntrySignal(
        template_name="first_bar_close",
        entry_time=str(first["trade_time"]),
        entry_price=price,
        entry_index=0,
        entry_label="首根收盘确认",
    )


def _simulate_first_bar_close_gap_guard(
    session_df: pd.DataFrame,
    open_gap: Optional[float],
    max_gap: float = 0.04,
) -> Optional[EntrySignal]:
    if open_gap is not None and open_gap > max_gap:
        return None
    signal = _simulate_first_bar_close(session_df)
    if signal is None:
        return None
    return EntrySignal(
        template_name="first_bar_close_gap_guard",
        entry_time=signal.entry_time,
        entry_price=signal.entry_price,
        entry_index=signal.entry_index,
        entry_label=f"首根收盘确认(高开>{max_gap:.0%}跳过)",
    )


def _simulate_open_buy_nonflat_gap(
    session_df: pd.DataFrame,
    open_gap: Optional[float],
) -> Optional[EntrySignal]:
    if open_gap is None:
        return None
    if not (open_gap < -0.02 or open_gap >= 0.01):
        return None
    signal = _simulate_open_buy(session_df)
    if signal is None:
        return None
    return EntrySignal(
        template_name="open_buy_nonflat_gap",
        entry_time=signal.entry_time,
        entry_price=signal.entry_price,
        entry_index=signal.entry_index,
        entry_label="开盘买(跳过平弱开)",
    )


def _simulate_open_buy_mid_gap(
    session_df: pd.DataFrame,
    open_gap: Optional[float],
) -> Optional[EntrySignal]:
    if open_gap is None:
        return None
    if not (0.01 <= open_gap < 0.04):
        return None
    signal = _simulate_open_buy(session_df)
    if signal is None:
        return None
    return EntrySignal(
        template_name="open_buy_mid_gap",
        entry_time=signal.entry_time,
        entry_price=signal.entry_price,
        entry_index=signal.entry_index,
        entry_label="开盘买(仅1%-4%开盘)",
    )


def _simulate_opening_range_breakout(session_df: pd.DataFrame) -> Optional[EntrySignal]:
    if len(session_df) < 4:
        return None
    interval = _infer_interval_minutes(session_df)
    opening_bars = max(2, int(math.ceil(15 / interval)))
    if len(session_df) <= opening_bars:
        return None

    frame = session_df.copy().reset_index(drop=True)
    vwap = _running_vwap(frame)
    opening_high = float(frame.iloc[:opening_bars]["high"].max())

    for idx in range(opening_bars, len(frame)):
        close = _safe_float(frame.iloc[idx]["close"], 0.0)
        if close <= 0:
            continue
        if close > opening_high * 1.001 and close > _safe_float(vwap[idx], 0.0):
            return EntrySignal(
                template_name="opening_range_breakout",
                entry_time=str(frame.iloc[idx]["trade_time"]),
                entry_price=close,
                entry_index=idx,
                entry_label=f"{opening_bars}根开盘区间突破",
            )
    return None


def _simulate_vwap_reclaim(session_df: pd.DataFrame) -> Optional[EntrySignal]:
    if len(session_df) < 6:
        return None
    frame = session_df.copy().reset_index(drop=True)
    vwap = _running_vwap(frame)
    interval = _infer_interval_minutes(frame)
    start_idx = max(3, int(math.ceil(20 / interval)))
    day_open = _safe_float(frame.iloc[0]["open"], 0.0)
    if day_open <= 0:
        return None

    for idx in range(start_idx, len(frame)):
        prev_close = _safe_float(frame.iloc[idx - 1]["close"], 0.0)
        current_close = _safe_float(frame.iloc[idx]["close"], 0.0)
        prev_vwap = _safe_float(vwap[idx - 1], np.nan)
        current_vwap = _safe_float(vwap[idx], np.nan)
        prev_high = _safe_float(frame.iloc[idx - 1]["high"], 0.0)
        if any(math.isnan(x) for x in [prev_vwap, current_vwap]):
            continue
        if (
            prev_close <= prev_vwap * 1.001
            and current_close > current_vwap * 1.001
            and current_close > prev_high * 0.999
            and current_close > day_open * 0.995
        ):
            return EntrySignal(
                template_name="vwap_reclaim",
                entry_time=str(frame.iloc[idx]["trade_time"]),
                entry_price=current_close,
                entry_index=idx,
                entry_label="回踩VWAP后重夺",
            )
    return None


def _simulate_adaptive_gap_policy(
    session_df: pd.DataFrame,
    open_gap: Optional[float],
) -> Optional[EntrySignal]:
    if open_gap is None:
        open_gap = 0.0

    if open_gap >= 0.04:
        base_signal = _simulate_vwap_reclaim(session_df)
        if base_signal is None:
            return None
        return EntrySignal(
            template_name="adaptive_gap_policy",
            entry_time=base_signal.entry_time,
            entry_price=base_signal.entry_price,
            entry_index=base_signal.entry_index,
            entry_label="自适应:高开走VWAP重夺",
        )
    if open_gap >= 0.01:
        base_signal = _simulate_opening_range_breakout(session_df) or _simulate_vwap_reclaim(session_df)
        if base_signal is None:
            return None
        return EntrySignal(
            template_name="adaptive_gap_policy",
            entry_time=base_signal.entry_time,
            entry_price=base_signal.entry_price,
            entry_index=base_signal.entry_index,
            entry_label="自适应:中高开确认后进",
        )
    if open_gap > -0.02:
        base_signal = _simulate_vwap_reclaim(session_df) or _simulate_opening_range_breakout(session_df)
        if base_signal is None:
            return None
        return EntrySignal(
            template_name="adaptive_gap_policy",
            entry_time=base_signal.entry_time,
            entry_price=base_signal.entry_price,
            entry_index=base_signal.entry_index,
            entry_label="自适应:平低开优先回踩确认",
        )
    return None


def _simulate_current_detector(session_df: pd.DataFrame) -> Optional[EntrySignal]:
    if len(session_df) < 22:
        return None
    detector = OptimizedBuySignals()
    signal_history: List[bool] = []
    frame = session_df.copy().reset_index(drop=True)

    for idx in range(len(frame)):
        if idx < 21:
            signal_history.append(False)
            continue
        partial = frame.iloc[: idx + 1].copy()
        row_time = pd.to_datetime(partial.iloc[-1]["trade_time"]).to_pydatetime()
        intraday_data = _build_intraday_input(partial)
        try:
            signal = detector.mutual_exclusive_signal(
                intraday_data,
                row_time,
                open_pct=0.0,
                market_score=65.0,
            )
        except Exception:
            signal_history.append(False)
            continue
        signal_history.append(bool(signal.signal))
        if signal.signal and detector.debounce(signal_history, window=2):
            price = _safe_float(partial.iloc[-1]["close"], 0.0)
            if price <= 0:
                continue
            label = signal.signal_type or "current_detector"
            return EntrySignal(
                template_name="current_detector",
                entry_time=str(partial.iloc[-1]["trade_time"]),
                entry_price=price,
                entry_index=idx,
                entry_label=f"当前买点器:{label}",
            )
    return None


def _evaluate_signal(
    signal: EntrySignal,
    session_df: pd.DataFrame,
    daily_map: Dict[Tuple[str, str], Dict[str, float]],
    symbol: str,
    trade_dates: List[str],
    rec_idx: int,
    horizons: List[int],
) -> List[Dict[str, object]]:
    rows: List[Dict[str, object]] = []
    entry_price = signal.entry_price
    if entry_price <= 0:
        return rows

    session_df = session_df.sort_values("trade_time").reset_index(drop=True)
    tail = session_df.iloc[signal.entry_index :].copy()
    if tail.empty:
        return rows

    intraday_highs = tail["high"].astype(float).tolist()
    intraday_lows = tail["low"].astype(float).tolist()
    entry_day_close = _safe_float(session_df.iloc[-1]["close"], 0.0)
    entry_day_ret = entry_day_close / entry_price - 1.0 if entry_day_close > 0 else np.nan
    entry_day_mfe = max(intraday_highs) / entry_price - 1.0 if intraday_highs else np.nan
    entry_day_mae = min(intraday_lows) / entry_price - 1.0 if intraday_lows else np.nan

    for horizon in horizons:
        sell_date = trade_dates[rec_idx + horizon]
        sell_bar = daily_map.get((symbol, sell_date))
        if not sell_bar:
            continue
        sell_close = _safe_float(sell_bar["close"], 0.0)
        if sell_close <= 0:
            continue

        highs = list(intraday_highs)
        lows = list(intraday_lows)
        for date in trade_dates[rec_idx + 2 : rec_idx + horizon + 1]:
            daily_bar = daily_map.get((symbol, date))
            if not daily_bar:
                continue
            highs.append(_safe_float(daily_bar["high"], 0.0))
            lows.append(_safe_float(daily_bar["low"], 0.0))
        highs = [value for value in highs if value > 0]
        lows = [value for value in lows if value > 0]

        ret = sell_close / entry_price - 1.0
        mfe = max(highs) / entry_price - 1.0 if highs else np.nan
        mae = min(lows) / entry_price - 1.0 if lows else np.nan
        giveback = mfe - ret if not math.isnan(mfe) else np.nan

        rows.append(
            {
                "template_name": signal.template_name,
                "entry_label": signal.entry_label,
                "entry_time": signal.entry_time,
                "entry_index": signal.entry_index,
                "entry_price": entry_price,
                "horizon": int(horizon),
                "sell_date": sell_date,
                "sell_close": sell_close,
                "ret": ret,
                "mfe": mfe,
                "mae": mae,
                "giveback": giveback,
                "entry_day_ret": entry_day_ret,
                "entry_day_mfe": entry_day_mfe,
                "entry_day_mae": entry_day_mae,
            }
        )
    return rows


def _summarize_template(trades: pd.DataFrame, possible_sessions: int) -> pd.DataFrame:
    rows: List[Dict[str, object]] = []
    if trades.empty:
        return pd.DataFrame()

    for template_name, group in trades.groupby("template_name"):
        coverage_sessions = int(group["session_key"].nunique())
        unique_entries = group.drop_duplicates(subset=["session_key"]).copy()
        entry_stats = {
            "avg_entry_index": float(unique_entries["entry_index"].mean()),
            "avg_open_gap": float(unique_entries["open_gap"].mean()),
            "avg_entry_day_ret": float(unique_entries["entry_day_ret"].mean()),
            "avg_entry_day_mfe": float(unique_entries["entry_day_mfe"].mean()),
        }
        for horizon, horizon_df in group.groupby("horizon"):
            rows.append(
                {
                    "template_name": template_name,
                    "horizon": int(horizon),
                    "possible_sessions": int(possible_sessions),
                    "trade_sessions": coverage_sessions,
                    "coverage_rate": coverage_sessions / possible_sessions if possible_sessions else 0.0,
                    "sample_count": int(len(horizon_df)),
                    "mean_ret": float(horizon_df["ret"].mean()),
                    "median_ret": float(horizon_df["ret"].median()),
                    "win_rate": float((horizon_df["ret"] > 0).mean()),
                    "mean_mfe": float(horizon_df["mfe"].mean()),
                    "mean_mae": float(horizon_df["mae"].mean()),
                    "mean_giveback": float(horizon_df["giveback"].mean()),
                    "avg_entry_day_ret": float(entry_stats.get("avg_entry_day_ret", 0.0)),
                    "avg_entry_day_mfe": float(entry_stats.get("avg_entry_day_mfe", 0.0)),
                    "avg_entry_index": float(entry_stats.get("avg_entry_index", 0.0)),
                    "avg_open_gap": float(entry_stats.get("avg_open_gap", 0.0)),
                }
            )
    return pd.DataFrame(rows)


def _summarize_open_gap(trades: pd.DataFrame) -> pd.DataFrame:
    baseline = trades[trades["template_name"] == "open_buy"].copy()
    if baseline.empty:
        return pd.DataFrame()

    bins = [-999, -0.02, 0.01, 0.04, 999]
    labels = ["gap<-2%", "-2%~1%", "1%~4%", ">=4%"]
    baseline["gap_bucket"] = pd.cut(baseline["open_gap"], bins=bins, labels=labels, right=False)

    rows: List[Dict[str, object]] = []
    for (gap_bucket, horizon), group in baseline.groupby(["gap_bucket", "horizon"], dropna=False):
        rows.append(
            {
                "gap_bucket": str(gap_bucket),
                "horizon": int(horizon),
                "sample_count": int(len(group)),
                "mean_ret": float(group["ret"].mean()),
                "win_rate": float((group["ret"] > 0).mean()),
                "mean_entry_day_ret": float(group["entry_day_ret"].mean()),
                "mean_entry_day_mfe": float(group["entry_day_mfe"].mean()),
                "mean_mfe": float(group["mfe"].mean()),
            }
        )
    return pd.DataFrame(rows)


def _build_examples(trades: pd.DataFrame) -> Dict[str, pd.DataFrame]:
    primary = trades[(trades["horizon"] == PRIMARY_HORIZON) & (trades["template_name"] == "open_buy")].copy()
    if primary.empty:
        return {
            "mid_gap_winners": pd.DataFrame(),
            "flat_gap_losers": pd.DataFrame(),
        }

    primary = primary.drop_duplicates("session_key").copy()
    mid_gap_winners = primary[(primary["open_gap"] >= 0.01) & (primary["open_gap"] < 0.04)].sort_values(
        "ret", ascending=False
    ).head(12)
    flat_gap_losers = primary[(primary["open_gap"] >= -0.02) & (primary["open_gap"] < 0.01)].sort_values(
        "ret", ascending=True
    ).head(12)
    return {
        "mid_gap_winners": mid_gap_winners,
        "flat_gap_losers": flat_gap_losers,
    }


def _build_report(
    meta: Dict[str, object],
    summary_df: pd.DataFrame,
    gap_df: pd.DataFrame,
    example_frames: Dict[str, pd.DataFrame],
) -> str:
    lines: List[str] = []
    lines.append("# 原策略买点适应性回测报告")
    lines.append("")
    lines.append(f"- 生成时间: `{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}`")
    lines.append(f"- 历史推荐区间: `{meta['start_rec_date']}` ~ `{meta['end_rec_date']}`")
    lines.append(f"- 历史推荐交易日: `{meta['rec_days']}`")
    lines.append(f"- 可回测入场会话: `{meta['possible_sessions']}`")
    lines.append(f"- 分时数据分辨率中位数: `{meta['median_interval_minutes']} 分钟`")
    lines.append("- 说明: `intraday_data 大部分是 48 根/日，实际更接近 5 分钟级分时，不是标准 1 分钟逐笔`")
    lines.append(f"- 统一口径: `recommendation_date = T，买入发生在 T+1 分时，卖出按 T+{','.join(str(h) for h in meta['horizons'])} 收盘`")
    lines.append("")

    lines.append("## 1. 核心结论")
    lines.append("")
    if not summary_df.empty:
        primary = summary_df[summary_df["horizon"] == PRIMARY_HORIZON].copy().sort_values(
            ["mean_ret", "coverage_rate"], ascending=[False, False]
        )
        best = primary.iloc[0].to_dict()
        baseline = primary[primary["template_name"] == "open_buy"]
        if not baseline.empty:
            baseline_row = baseline.iloc[0].to_dict()
            lines.append(
                f"- 在 `T+{PRIMARY_HORIZON}` 口径下，表现最好的入场模板是 `{best['template_name']}`，平均收益 `{_fmt_pct(best['mean_ret'])}`，覆盖率 `{best['coverage_rate'] * 100:.2f}%`。"
            )
            lines.append(
                f"- 基线 `open_buy` 的平均收益是 `{_fmt_pct(baseline_row['mean_ret'])}`。如果最优模板明显更好，就说明原策略确实需要 `按开盘形态做适应性买点优化`。"
            )
        detector = primary[primary["template_name"] == "current_detector"]
        if not detector.empty:
            detector_row = detector.iloc[0].to_dict()
            lines.append(
                f"- 当前系统买点器 `current_detector` 的覆盖率 `{detector_row['coverage_rate'] * 100:.2f}%`，`T+{PRIMARY_HORIZON}` 平均收益 `{_fmt_pct(detector_row['mean_ret'])}`。"
            )
            lines.append("- 这项结果可以直接判断现有盘中买点逻辑，是否与原策略候选池的真实分时节奏匹配。")
    lines.append("")

    lines.append("## 2. 入场模板对比")
    lines.append("")
    lines.append("| 模板 | 窗口 | 覆盖率 | 平均收益 | 胜率 | 平均MFE | 平均回吐 | 买入当日收益 | 买入当日MFE | 平均入场bar |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for row in summary_df.sort_values(["horizon", "mean_ret", "coverage_rate"], ascending=[True, False, False]).to_dict("records"):
        lines.append(
            f"| {row['template_name']} | T+{int(row['horizon'])} | {_fmt_ratio(float(row['coverage_rate']))} | {_fmt_pct(float(row['mean_ret']))} | {float(row['win_rate']) * 100:.2f}% | {_fmt_pct(float(row['mean_mfe']))} | {_fmt_pct(float(row['mean_giveback']))} | {_fmt_pct(float(row['avg_entry_day_ret']))} | {_fmt_pct(float(row['avg_entry_day_mfe']))} | {float(row['avg_entry_index']):.1f} |"
        )
    lines.append("")

    if not gap_df.empty:
        lines.append("## 3. 基线开盘买的 Gap 分层")
        lines.append("")
        lines.append("| Gap分层 | 窗口 | 样本数 | 平均收益 | 胜率 | 买入当日收益 | 买入当日MFE | 总MFE |")
        lines.append("|---|---:|---:|---:|---:|---:|---:|---:|")
        for row in gap_df.sort_values(["horizon", "gap_bucket"]).to_dict("records"):
            lines.append(
                f"| {row['gap_bucket']} | T+{int(row['horizon'])} | {int(row['sample_count'])} | {_fmt_pct(float(row['mean_ret']))} | {float(row['win_rate']) * 100:.2f}% | {_fmt_pct(float(row['mean_entry_day_ret']))} | {_fmt_pct(float(row['mean_entry_day_mfe']))} | {_fmt_pct(float(row['mean_mfe']))} |"
            )
        lines.append("")
        lines.append("- 如果高开组最终收益弱、但 MFE 仍然很高，就说明原策略更怕“开盘追脉冲”，适合等确认后再进。")
        lines.append("")

    mid_gap_winners = example_frames.get("mid_gap_winners", pd.DataFrame())
    if not mid_gap_winners.empty:
        lines.append("## 4. 1%-4%开盘的强势实例")
        lines.append("")
        lines.append("| 推荐日 | 股票 | 开盘Gap | 评分 | T+2收益 | 买入当日收益 | 买入当日MFE |")
        lines.append("|---|---|---:|---:|---:|---:|---:|")
        for row in mid_gap_winners.to_dict("records"):
            lines.append(
                f"| {row['rec_date']} | {row['symbol']} {row['name']} | {_fmt_pct(float(row['open_gap']))} | {float(row['recommendation_score']):.1f} | {_fmt_pct(float(row['ret']))} | {_fmt_pct(float(row['entry_day_ret']))} | {_fmt_pct(float(row['entry_day_mfe']))} |"
            )
        lines.append("")

    flat_gap_losers = example_frames.get("flat_gap_losers", pd.DataFrame())
    if not flat_gap_losers.empty:
        lines.append("## 5. -2%~1%平弱开盘的亏损实例")
        lines.append("")
        lines.append("| 推荐日 | 股票 | 开盘Gap | 评分 | T+2收益 | 买入当日收益 | 买入当日MFE |")
        lines.append("|---|---|---:|---:|---:|---:|---:|")
        for row in flat_gap_losers.to_dict("records"):
            lines.append(
                f"| {row['rec_date']} | {row['symbol']} {row['name']} | {_fmt_pct(float(row['open_gap']))} | {float(row['recommendation_score']):.1f} | {_fmt_pct(float(row['ret']))} | {_fmt_pct(float(row['entry_day_ret']))} | {_fmt_pct(float(row['entry_day_mfe']))} |"
            )
        lines.append("")

    lines.append("## 6. 建议")
    lines.append("")
    lines.append("- 若 `adaptive_gap_policy` 或 `gap_guard + 确认买入` 明显优于 `open_buy`，下一步就应把原策略盘中买点切到“按开盘 Gap 分流”的执行模板。")
    lines.append("- 若 `current_detector` 覆盖率很低或收益不佳，说明当前买点器和库里的 5 分钟级分时节奏不匹配，需要针对真实 bar 分辨率重写。")
    lines.append("- 若高开组普遍 `MFE 高、最终收益低`，应避免开盘直接追高，把高开票统一改为“只允许回踩 VWAP 重夺后再买”。")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="原策略买点适应性回测")
    parser.add_argument("--rec-db", default="data/history_recommendation.db")
    parser.add_argument("--market-db", default="data/database/quant_system.db")
    parser.add_argument("--start-date", default=None)
    parser.add_argument("--end-date", default=None)
    parser.add_argument("--top-n", type=int, default=10)
    parser.add_argument("--horizons", default="2,3,5")
    parser.add_argument("--output-dir", default="reports")
    args = parser.parse_args()

    horizons = sorted({max(1, int(item.strip())) for item in args.horizons.split(",") if item.strip()})
    if not horizons:
        horizons = DEFAULT_HORIZONS

    rec_conn = sqlite3.connect(args.rec_db)
    market_conn = sqlite3.connect(args.market_db)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    try:
        rec_df = _load_recommendations(rec_conn, args.start_date, args.end_date, args.top_n)
        if rec_df.empty:
            raise ValueError("没有找到可用的历史推荐名单")

        trade_dates = _load_trade_calendar(market_conn)
        date_to_idx = {date: idx for idx, date in enumerate(trade_dates)}
        rec_df = rec_df[rec_df["rec_date"].isin(date_to_idx.keys())].copy()
        rec_df["rec_idx"] = rec_df["rec_date"].map(date_to_idx)
        rec_df = rec_df[rec_df["rec_idx"] + max(horizons) < len(trade_dates)].copy()
        rec_df["buy_trade_date"] = rec_df["rec_idx"].map(lambda idx: _to_trade_date(trade_dates[int(idx) + 1]))
        if rec_df.empty:
            raise ValueError("推荐名单没有足够的未来交易日用于回测")

        symbols = sorted(rec_df["symbol"].dropna().unique().tolist())
        intraday_map = _load_intraday_map(
            rec_conn,
            symbols=symbols,
            date_min=str(rec_df["buy_trade_date"].min()),
            date_max=str(rec_df["buy_trade_date"].max()),
        )
        daily_map = _load_daily_map(
            market_conn,
            symbols=symbols,
            date_min=str(rec_df["rec_date"].min()),
            date_max=str(trade_dates[int(rec_df["rec_idx"].max()) + max(horizons)]),
        )

        rows: List[Dict[str, object]] = []
        skipped = 0
        intervals: List[int] = []

        for item in rec_df.to_dict("records"):
            symbol = str(item["symbol"])
            rec_date = str(item["rec_date"])
            buy_trade_date = str(item["buy_trade_date"])
            session_df = intraday_map.get((symbol, buy_trade_date))
            prev_bar = daily_map.get((symbol, rec_date))
            if session_df is None or session_df.empty or not prev_bar:
                skipped += 1
                continue

            session_df = session_df.sort_values("trade_time").reset_index(drop=True)
            if len(session_df) < 10:
                skipped += 1
                continue

            prev_close = _safe_float(prev_bar["close"], 0.0)
            first_open = _safe_float(session_df.iloc[0]["open"], 0.0)
            if prev_close <= 0 or first_open <= 0:
                skipped += 1
                continue

            session_key = f"{rec_date}|{symbol}"
            open_gap = first_open / prev_close - 1.0
            interval_min = _infer_interval_minutes(session_df)
            intervals.append(interval_min)

            templates = [
                _simulate_open_buy(session_df),
                _simulate_open_buy_nonflat_gap(session_df, open_gap=open_gap),
                _simulate_open_buy_mid_gap(session_df, open_gap=open_gap),
                _simulate_first_bar_close(session_df),
                _simulate_first_bar_close_gap_guard(session_df, open_gap=open_gap),
                _simulate_opening_range_breakout(session_df),
                _simulate_vwap_reclaim(session_df),
                _simulate_adaptive_gap_policy(session_df, open_gap=open_gap),
                _simulate_current_detector(session_df),
            ]
            for signal in templates:
                if signal is None:
                    continue
                eval_rows = _evaluate_signal(
                    signal=signal,
                    session_df=session_df,
                    daily_map=daily_map,
                    symbol=symbol,
                    trade_dates=trade_dates,
                    rec_idx=int(item["rec_idx"]),
                    horizons=horizons,
                )
                for row in eval_rows:
                    rows.append(
                        {
                            **row,
                            "rec_date": rec_date,
                            "buy_date": buy_trade_date,
                            "symbol": symbol,
                            "name": str(item.get("name", "")),
                            "recommendation_score": _safe_float(item.get("recommendation_score", 0.0), 0.0),
                            "open_gap": open_gap,
                            "session_key": session_key,
                            "interval_minutes": interval_min,
                        }
                    )

        trades_df = pd.DataFrame(rows)
        possible_sessions = int(rec_df["symbol"].count() - skipped)
        if trades_df.empty:
            raise ValueError("没有生成任何可用的买点回测结果")

        summary_df = _summarize_template(trades_df, possible_sessions=possible_sessions)
        gap_df = _summarize_open_gap(trades_df)
        examples = _build_examples(trades_df)

        meta = {
            "start_rec_date": str(rec_df["rec_date"].min()),
            "end_rec_date": str(rec_df["rec_date"].max()),
            "rec_days": int(rec_df["rec_date"].nunique()),
            "possible_sessions": possible_sessions,
            "median_interval_minutes": int(np.median(intervals)) if intervals else 5,
            "skipped_sessions": int(skipped),
            "horizons": horizons,
        }

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_path = output_dir / f"legacy_adaptive_entries_{timestamp}.md"
        json_path = output_dir / f"legacy_adaptive_entries_{timestamp}.json"
        detail_path = output_dir / f"legacy_adaptive_entries_detail_{timestamp}.csv"
        summary_path = output_dir / f"legacy_adaptive_entries_summary_{timestamp}.csv"
        gap_path = output_dir / f"legacy_adaptive_entries_gap_{timestamp}.csv"

        report_text = _build_report(meta=meta, summary_df=summary_df, gap_df=gap_df, example_frames=examples)
        report_path.write_text(report_text, encoding="utf-8")
        trades_df.to_csv(detail_path, index=False, encoding="utf-8-sig")
        summary_df.to_csv(summary_path, index=False, encoding="utf-8-sig")
        gap_df.to_csv(gap_path, index=False, encoding="utf-8-sig")

        json_payload = {
            "meta": meta,
            "summary": summary_df.to_dict("records"),
            "gap_summary": gap_df.to_dict("records"),
            "examples": {key: frame.to_dict("records") for key, frame in examples.items()},
            "files": {
                "report": str(report_path),
                "json": str(json_path),
                "detail_csv": str(detail_path),
                "summary_csv": str(summary_path),
                "gap_csv": str(gap_path),
            },
        }
        json_path.write_text(json.dumps(json_payload, ensure_ascii=False, indent=2), encoding="utf-8")

        print(f"report={report_path}")
        print(f"json={json_path}")
        print(f"detail_csv={detail_path}")
        print(f"summary_csv={summary_path}")
        print(f"gap_csv={gap_path}")
        return 0
    finally:
        rec_conn.close()
        market_conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
