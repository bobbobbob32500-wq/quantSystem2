# -*- coding: utf-8 -*-
"""Daily-bar exit simulation utilities for alpha158-style selections."""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from src.core.database import DatabaseManager


@dataclass
class ExitProfile:
    stop_loss_pct: float = -0.04
    tp1_pct: float = 0.05
    take_profit_pct: float = 0.10
    trailing_stop_pct: float = 0.03
    max_hold_days: int = 5
    partial_take_ratio: float = 0.50
    weak_time_stop_days: int = 2
    intraday_priority: str = "stop_first"


@dataclass
class ExitStats:
    trade_count: int = 0
    trade_days: int = 0
    mean_return: float = 0.0
    median_return: float = 0.0
    win_rate: float = 0.0
    sharpe_ratio: float = 0.0
    max_drawdown: float = 0.0
    total_return: float = 0.0
    avg_hold_days: float = 0.0


def _exit_all(
    remaining_weight: float,
    realized_return: float,
    exit_pnl: float,
) -> Tuple[float, float]:
    if remaining_weight <= 0:
        return realized_return, 0.0
    realized_return += remaining_weight * float(exit_pnl)
    return realized_return, 0.0


def simulate_trade_exit(
    path_df: pd.DataFrame,
    profile: ExitProfile,
    regime_name: Optional[str] = None,
) -> Dict[str, object]:
    if path_df is None or path_df.empty:
        return {
            "realized_return": 0.0,
            "exit_reason": "no_path",
            "hold_days": 0,
            "peak_pnl_pct": 0.0,
            "entry_price": np.nan,
            "exit_price": np.nan,
        }

    entry_row = path_df.iloc[0]
    entry_price = float(entry_row["open"]) if pd.notna(entry_row["open"]) else np.nan
    if not np.isfinite(entry_price) or entry_price <= 0:
        return {
            "realized_return": 0.0,
            "exit_reason": "invalid_entry_price",
            "hold_days": 0,
            "peak_pnl_pct": 0.0,
            "entry_price": entry_price,
            "exit_price": np.nan,
        }

    stop_loss_pct = float(profile.stop_loss_pct)
    trail_arm_pct = float(profile.tp1_pct)
    trailing_stop_pct = float(profile.trailing_stop_pct)
    max_hold_days = max(1, int(profile.max_hold_days))

    realized_return = 0.0
    remaining_weight = 1.0
    peak_pnl_pct = 0.0
    exit_reason = "time_exit"
    exit_price = float(entry_row["close"]) if pd.notna(entry_row["close"]) else entry_price
    hold_days = 1
    armed_trailing = False
    armed_day_idx = 0
    exit_price_rule = "close"
    regime_key = str(regime_name or "").strip().lower()

    for day_idx, row in enumerate(path_df.itertuples(index=False), start=1):
        o = float(row.open) if pd.notna(row.open) else np.nan
        h = float(row.high) if pd.notna(row.high) else np.nan
        l = float(row.low) if pd.notna(row.low) else np.nan
        c = float(row.close) if pd.notna(row.close) else np.nan
        trade_date = str(row.trade_date)
        hold_days = day_idx

        if not np.isfinite(o) or not np.isfinite(h) or not np.isfinite(l) or not np.isfinite(c):
            continue

        open_pnl = o / entry_price - 1.0
        high_pnl = h / entry_price - 1.0
        low_pnl = l / entry_price - 1.0
        close_pnl = c / entry_price - 1.0
        peak_before_day = peak_pnl_pct

        # Gap exits for an already-armed position.
        if armed_trailing and remaining_weight > 0 and day_idx > armed_day_idx:
            trailing_floor = peak_before_day - trailing_stop_pct
            if peak_before_day >= trail_arm_pct and open_pnl <= trailing_floor:
                realized_return, remaining_weight = _exit_all(remaining_weight, realized_return, open_pnl)
                exit_reason = "trailing_gap"
                exit_price = o
                exit_price_rule = "open_gap"
                break

        if remaining_weight > 0 and open_pnl <= stop_loss_pct:
            realized_return, remaining_weight = _exit_all(remaining_weight, realized_return, open_pnl)
            exit_reason = "gap_stop"
            exit_price = o
            exit_price_rule = "open_gap"
            break

        if (not armed_trailing) and remaining_weight > 0 and open_pnl >= trail_arm_pct:
            peak_pnl_pct = max(peak_pnl_pct, open_pnl)
            armed_trailing = True
            armed_day_idx = day_idx

        stop_hit = low_pnl <= stop_loss_pct
        peak_pnl_pct = max(peak_pnl_pct, high_pnl, open_pnl)
        if (not armed_trailing) and peak_pnl_pct >= trail_arm_pct:
            armed_trailing = True
            armed_day_idx = day_idx

        if remaining_weight > 0 and stop_hit:
            realized_return, remaining_weight = _exit_all(remaining_weight, realized_return, stop_loss_pct)
            exit_reason = "stop_loss_intraday"
            exit_price = entry_price * (1.0 + stop_loss_pct)
            exit_price_rule = "pct_rule"
            break

        if (
            remaining_weight > 0
            and regime_key == "weak"
            and day_idx >= max(1, int(profile.weak_time_stop_days))
            and close_pnl < 0
        ):
            realized_return, remaining_weight = _exit_all(remaining_weight, realized_return, close_pnl)
            exit_reason = "weak_time_stop"
            exit_price = c
            exit_price_rule = "close"
            break

        if armed_trailing and remaining_weight > 0 and day_idx > armed_day_idx:
            trailing_floor = peak_pnl_pct - trailing_stop_pct
            if peak_pnl_pct >= trail_arm_pct and close_pnl <= trailing_floor:
                realized_return, remaining_weight = _exit_all(remaining_weight, realized_return, close_pnl)
                exit_reason = "trailing_stop_close"
                exit_price = c
                exit_price_rule = "close"
                break

        if day_idx >= max_hold_days:
            realized_return, remaining_weight = _exit_all(remaining_weight, realized_return, close_pnl)
            exit_reason = "time_exit"
            exit_price = c
            exit_price_rule = "close"
            break

        # Keep end-of-day mark only for the residual unrealized risk tracking.
        peak_pnl_pct = max(peak_pnl_pct, close_pnl)
        exit_price = c

    return {
        "realized_return": float(realized_return),
        "exit_reason": str(exit_reason),
        "exit_day": int(hold_days),
        "exit_price_rule": str(exit_price_rule),
        "hold_days": int(hold_days),
        "peak_pnl_pct": float(peak_pnl_pct),
        "entry_price": float(entry_price),
        "exit_price": float(exit_price) if np.isfinite(exit_price) else np.nan,
        "profile": asdict(profile),
        "partial_take_done": False,
        "armed_trailing": bool(armed_trailing),
    }


def load_trade_price_paths(
    rec_df: pd.DataFrame,
    db: DatabaseManager,
    trade_dates: List[str],
    max_hold_days: int,
) -> Dict[int, pd.DataFrame]:
    if rec_df is None or rec_df.empty:
        return {}

    date_to_idx = {d: i for i, d in enumerate(trade_dates)}
    rec = rec_df.reset_index(drop=True).copy()
    rec["rec_idx"] = rec["rec_date"].map(date_to_idx)
    rec = rec.dropna(subset=["rec_idx"]).copy()
    rec["rec_idx"] = rec["rec_idx"].astype(int)
    rec = rec[rec["rec_idx"] + 1 < len(trade_dates)].copy()
    if rec.empty:
        return {}

    rec["exit_idx"] = rec["rec_idx"].apply(lambda idx: min(idx + max_hold_days, len(trade_dates) - 1))
    symbols = sorted(rec["ts_code"].astype(str).unique().tolist())
    min_idx = int(rec["rec_idx"].min() + 1)
    max_idx = int(rec["exit_idx"].max())
    date_min = trade_dates[min_idx]
    date_max = trade_dates[max_idx]

    conn = db._get_connection()
    placeholders = ",".join(["?"] * len(symbols))
    sql = f"""
        SELECT ts_code, trade_date, open, high, low, close
        FROM stock_daily
        WHERE ts_code IN ({placeholders})
          AND trade_date >= ? AND trade_date <= ?
        ORDER BY ts_code ASC, trade_date ASC
    """
    price_df = pd.read_sql(sql, conn, params=symbols + [date_min, date_max])
    conn.close()
    if price_df.empty:
        return {}

    for col in ("open", "high", "low", "close"):
        price_df[col] = pd.to_numeric(price_df[col], errors="coerce")
    price_df["trade_date"] = price_df["trade_date"].astype(str)

    by_symbol = {
        str(ts_code): frame.reset_index(drop=True)
        for ts_code, frame in price_df.groupby("ts_code", sort=False)
    }

    paths: Dict[int, pd.DataFrame] = {}
    for idx, row in rec.iterrows():
        symbol = str(row["ts_code"])
        frame = by_symbol.get(symbol)
        if frame is None or frame.empty:
            continue
        start_date = trade_dates[int(row["rec_idx"]) + 1]
        end_date = trade_dates[int(row["exit_idx"])]
        path = frame[(frame["trade_date"] >= start_date) & (frame["trade_date"] <= end_date)].copy()
        if path.empty:
            continue
        paths[int(idx)] = path.reset_index(drop=True)
    return paths


def simulate_recommendation_exits(
    rec_df: pd.DataFrame,
    db: DatabaseManager,
    trade_dates: List[str],
    profile: ExitProfile,
    price_paths: Dict[int, pd.DataFrame] | None = None,
    horizon_col: str = "suggested_hold_days",
    min_horizon: int = 2,
    max_horizon: int = 5,
    profile_by_regime: Dict[str, ExitProfile] | None = None,
    activation_loss_avoidance_threshold: float | None = None,
    activation_loss_avoidance_threshold_by_regime: Dict[str, float | None] | None = None,
) -> pd.DataFrame:
    if rec_df is None or rec_df.empty:
        return pd.DataFrame()
    if price_paths is None:
        price_paths = load_trade_price_paths(
            rec_df=rec_df,
            db=db,
            trade_dates=trade_dates,
            max_hold_days=max(1, int(profile.max_hold_days)),
        )

    rows: List[Dict[str, object]] = []
    rec = rec_df.reset_index(drop=True)
    for idx, row in rec.iterrows():
        path = price_paths.get(int(idx))
        if path is None or path.empty:
            continue
        try:
            resolved_max_hold = int(pd.to_numeric(row.get(horizon_col, profile.max_hold_days), errors="coerce"))
        except Exception:
            resolved_max_hold = int(profile.max_hold_days)
        resolved_max_hold = int(max(int(min_horizon), min(int(max_horizon), int(resolved_max_hold))))
        regime_name = str(row.get("regime_name", "") or "")
        regime_key = str(regime_name or "").strip().lower()
        profile_base = profile
        if isinstance(profile_by_regime, dict) and regime_key in profile_by_regime:
            profile_base = profile_by_regime[regime_key]
        guard_active = True
        guard_force_disabled = False
        threshold_for_row: float | None = activation_loss_avoidance_threshold
        if isinstance(activation_loss_avoidance_threshold_by_regime, dict):
            if regime_key in activation_loss_avoidance_threshold_by_regime:
                regime_threshold = activation_loss_avoidance_threshold_by_regime.get(regime_key)
                if regime_threshold is None:
                    guard_force_disabled = True
                    threshold_for_row = None
                else:
                    try:
                        threshold_for_row = float(regime_threshold)
                    except Exception:
                        threshold_for_row = activation_loss_avoidance_threshold
            else:
                threshold_for_row = activation_loss_avoidance_threshold

        if guard_force_disabled:
            guard_active = False
        elif threshold_for_row is not None:
            try:
                loss_score = float(pd.to_numeric(row.get("loss_avoidance_score", np.nan), errors="coerce"))
            except Exception:
                loss_score = float("nan")
            if np.isfinite(loss_score):
                guard_active = bool(loss_score >= float(threshold_for_row))
            else:
                guard_active = False
        if not guard_active:
            profile_base = ExitProfile(
                stop_loss_pct=-0.99,
                tp1_pct=9.99,
                take_profit_pct=1.0,
                trailing_stop_pct=9.99,
                max_hold_days=int(profile_base.max_hold_days),
                partial_take_ratio=0.0,
                weak_time_stop_days=5,
                intraday_priority="stop_first",
            )
        local_profile = replace(profile_base, max_hold_days=resolved_max_hold)
        sim = simulate_trade_exit(path_df=path, profile=local_profile, regime_name=regime_name)
        rows.append(
            {
                "rec_date": str(row["rec_date"]),
                "ts_code": str(row["ts_code"]),
                "name": str(row.get("name", "")),
                "rank": int(row.get("rank", 0) or 0),
                "score": float(row.get("score", 0.0) or 0.0),
                "regime_name": regime_name,
                "exit_profile_regime": regime_key,
                "exit_guard_active": bool(guard_active),
                "suggested_hold_days": int(resolved_max_hold),
                "entry_date": str(path.iloc[0]["trade_date"]),
                "exit_date": str(path.iloc[min(max(int(sim["hold_days"]) - 1, 0), len(path) - 1)]["trade_date"]),
                **sim,
            }
        )
    return pd.DataFrame(rows)


def summarize_simulated_trades(trades_df: pd.DataFrame) -> ExitStats:
    if trades_df is None or trades_df.empty:
        return ExitStats()
    returns = pd.to_numeric(trades_df["realized_return"], errors="coerce").dropna()
    if returns.empty:
        return ExitStats()
    grouped = trades_df.groupby("rec_date", sort=True)["realized_return"].mean()
    day_returns = pd.to_numeric(grouped, errors="coerce").dropna()
    sharpe = 0.0
    if len(day_returns) > 1:
        std = float(np.std(day_returns))
        sharpe = float(np.mean(day_returns) / std * np.sqrt(252)) if std > 0 else 0.0
    cumulative = np.cumprod(1.0 + returns.to_numpy(dtype=float))
    running_max = np.maximum.accumulate(cumulative)
    drawdowns = (cumulative - running_max) / running_max
    return ExitStats(
        trade_count=int(len(returns)),
        trade_days=int(trades_df["rec_date"].nunique()),
        mean_return=float(returns.mean()),
        median_return=float(returns.median()),
        win_rate=float((returns > 0).mean()),
        sharpe_ratio=float(sharpe),
        max_drawdown=float(np.min(drawdowns)) if len(drawdowns) else 0.0,
        total_return=float(np.prod(1.0 + returns.to_numpy(dtype=float)) - 1.0),
        avg_hold_days=float(pd.to_numeric(trades_df["hold_days"], errors="coerce").dropna().mean()),
    )


def summarize_portfolio_curve(trades_df: pd.DataFrame) -> Dict[str, float]:
    empty = {
        "portfolio_trade_days": 0,
        "portfolio_mean_return": 0.0,
        "portfolio_win_rate": 0.0,
        "portfolio_sharpe": 0.0,
        "portfolio_max_drawdown": 0.0,
        "portfolio_total_return": 0.0,
    }
    if trades_df is None or trades_df.empty:
        return dict(empty)
    grouped = trades_df.groupby("rec_date", sort=True)["realized_return"].mean()
    day_returns = pd.to_numeric(grouped, errors="coerce").dropna().to_numpy(dtype=float)
    if day_returns.size == 0:
        return dict(empty)
    cumulative = np.cumprod(1.0 + day_returns)
    running_max = np.maximum.accumulate(cumulative)
    drawdowns = (cumulative - running_max) / running_max
    sharpe = 0.0
    if day_returns.size > 1:
        std = float(np.std(day_returns))
        sharpe = float(np.mean(day_returns) / std * np.sqrt(252)) if std > 0 else 0.0
    return {
        "portfolio_trade_days": int(day_returns.size),
        "portfolio_mean_return": float(np.mean(day_returns)),
        "portfolio_win_rate": float(np.mean(day_returns > 0)),
        "portfolio_sharpe": float(sharpe),
        "portfolio_max_drawdown": float(np.min(drawdowns)) if drawdowns.size else 0.0,
        "portfolio_total_return": float(np.prod(1.0 + day_returns) - 1.0),
    }
