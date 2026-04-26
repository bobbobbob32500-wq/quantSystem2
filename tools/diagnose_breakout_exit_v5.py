#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Diagnose exit policies for breakout after v2/v3 entry guards."""

from __future__ import annotations

import argparse
import json
import math
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.diagnose_breakout_market_regime import _load_market_frame, _market_daily


OUT_DIR = ROOT / "reports" / "strategy_optimization"
DB_PATH = ROOT / "data" / "database" / "quant_system.db"
DEFAULT_TRADES = OUT_DIR / "breakout_v1_baseline_trades_latest.csv"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Diagnose breakout exit policies after v2/v3 guards.")
    parser.add_argument("--trades-csv", default=str(DEFAULT_TRADES))
    parser.add_argument("--cost-bps", type=float, default=12.0)
    parser.add_argument("--score-min", type=float, default=80.0)
    parser.add_argument("--volume-min", type=float, default=1.35)
    parser.add_argument("--market-ret5-stop", type=float, default=-0.01)
    parser.add_argument("--disable-market-ret5-filter", action="store_true")
    return parser


def _safe_float(v: Any) -> float | None:
    try:
        f = float(v)
    except Exception:
        return None
    if math.isnan(f) or math.isinf(f):
        return None
    return f


def _fmt_pct(v: Any) -> str:
    f = _safe_float(v)
    return "NA" if f is None else f"{f:.2%}"


def _fmt_num(v: Any, digits: int = 2) -> str:
    f = _safe_float(v)
    return "NA" if f is None else f"{f:.{digits}f}"


def _jsonify(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {str(k): _jsonify(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_jsonify(v) for v in obj]
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        return _safe_float(obj)
    if isinstance(obj, float):
        return _safe_float(obj)
    return obj


def _metric(df: pd.DataFrame, ret_col: str) -> Dict[str, float]:
    v = pd.to_numeric(df.get(ret_col, pd.Series(dtype=float)), errors="coerce").dropna()
    if v.empty:
        return {
            "n_trades": 0.0,
            "win_rate": float("nan"),
            "mean_ret": float("nan"),
            "median_ret": float("nan"),
            "pf": float("nan"),
            "port_total_ret": 0.0,
            "port_mdd": 0.0,
            "port_sharpe": 0.0,
            "avg_hold_days": float("nan"),
        }
    gain = float(v[v > 0].sum())
    loss = float(-v[v < 0].sum())
    dr = df.groupby("signal_date")[ret_col].mean().dropna().sort_index()
    eq = (1.0 + dr).cumprod() if not dr.empty else pd.Series(dtype=float)
    hold = pd.to_numeric(df.get("exit_hold_days", pd.Series(dtype=float)), errors="coerce").dropna()
    return {
        "n_trades": float(len(v)),
        "win_rate": float((v > 0).mean()),
        "mean_ret": float(v.mean()),
        "median_ret": float(v.median()),
        "pf": gain / loss if loss > 1e-12 else (99.0 if gain > 1e-12 else 0.0),
        "port_total_ret": float(eq.iloc[-1] - 1.0) if not eq.empty else 0.0,
        "port_mdd": float((eq / eq.cummax() - 1.0).min()) if not eq.empty else 0.0,
        "port_sharpe": float(dr.mean() / dr.std() * np.sqrt(252)) if len(dr) > 1 and dr.std() > 1e-12 else 0.0,
        "avg_hold_days": float(hold.mean()) if not hold.empty else float("nan"),
    }


def _load_filtered_trades(
    path: Path,
    cost_bps: float,
    score_min: float,
    volume_min: float,
    market_ret5_stop: float,
    apply_market_ret5_filter: bool,
) -> pd.DataFrame:
    trades = pd.read_csv(path)
    for col in ("signal_date", "confirm_date", "ts_code", "name", "industry", "signal_grade"):
        if col in trades.columns:
            trades[col] = trades[col].astype(str)
    for col in trades.columns:
        if col.startswith("ret_t") or col in {"signal_score", "volume_ratio", "entry_price", "stop_loss"}:
            trades[col] = pd.to_numeric(trades[col], errors="coerce")
    cost = float(cost_bps) / 10000.0
    for n in range(1, 6):
        col = f"ret_t{n}"
        if col in trades.columns:
            trades[f"{col}_net"] = trades[col] - cost

    weak_confirm = (trades["signal_score"] >= score_min) & (trades["volume_ratio"] < volume_min)
    trades = trades.loc[~weak_confirm].copy()

    if apply_market_ret5_filter:
        market = _market_daily(_load_market_frame())
        trades = trades.merge(market[["signal_date", "median_ret_5d"]], on="signal_date", how="left")
        trades = trades.loc[~(trades["median_ret_5d"] <= market_ret5_stop)].copy()
    trades = trades.sort_values(["signal_date", "ts_code"]).reset_index(drop=True)
    return trades


def _trade_dates() -> List[str]:
    conn = sqlite3.connect(DB_PATH.as_posix())
    try:
        rows = pd.read_sql("SELECT DISTINCT trade_date FROM stock_daily ORDER BY trade_date ASC", conn)
    finally:
        conn.close()
    return rows["trade_date"].astype(str).tolist()


def _load_paths(trades: pd.DataFrame, max_hold_days: int = 5) -> Dict[int, pd.DataFrame]:
    if trades.empty:
        return {}
    dates = _trade_dates()
    date_to_idx = {d: i for i, d in enumerate(dates)}
    rec = trades.reset_index(drop=False).rename(columns={"index": "trade_id"})
    rec["confirm_idx"] = rec["confirm_date"].map(date_to_idx)
    rec = rec.dropna(subset=["confirm_idx"]).copy()
    rec["confirm_idx"] = rec["confirm_idx"].astype(int)
    rec["exit_idx"] = rec["confirm_idx"].apply(lambda i: min(i + max_hold_days - 1, len(dates) - 1))
    symbols = sorted(rec["ts_code"].astype(str).unique().tolist())
    if not symbols:
        return {}
    date_min = dates[int(rec["confirm_idx"].min())]
    date_max = dates[int(rec["exit_idx"].max())]
    placeholders = ",".join(["?"] * len(symbols))
    conn = sqlite3.connect(DB_PATH.as_posix())
    try:
        px = pd.read_sql(
            f"""
            SELECT ts_code, trade_date, open, high, low, close
            FROM stock_daily
            WHERE ts_code IN ({placeholders})
              AND trade_date >= ? AND trade_date <= ?
            ORDER BY ts_code ASC, trade_date ASC
            """,
            conn,
            params=symbols + [date_min, date_max],
        )
    finally:
        conn.close()
    for col in ("open", "high", "low", "close"):
        px[col] = pd.to_numeric(px[col], errors="coerce")
    px["trade_date"] = px["trade_date"].astype(str)
    px = px.sort_values(["ts_code", "trade_date"]).reset_index(drop=True)
    px["ma5"] = px.groupby("ts_code")["close"].transform(lambda s: s.rolling(5, min_periods=3).mean())
    by_code = {code: sub.sort_values("trade_date").reset_index(drop=True) for code, sub in px.groupby("ts_code")}
    paths: Dict[int, pd.DataFrame] = {}
    for row in rec.itertuples(index=False):
        sub = by_code.get(str(row.ts_code))
        if sub is None:
            continue
        start = str(row.confirm_date)
        end = dates[int(row.exit_idx)]
        path = sub[(sub["trade_date"] >= start) & (sub["trade_date"] <= end)].copy()
        if not path.empty:
            paths[int(row.trade_id)] = path.reset_index(drop=True)
    return paths


def _simulate_exit(
    path: pd.DataFrame,
    entry_price: float,
    stop_loss_price: float,
    *,
    max_hold_days: int,
    stop_pct: float | None = None,
    use_atr_stop: bool = False,
    trail_arm: float | None = None,
    trail_gap: float | None = None,
    take_profit: float | None = None,
) -> Dict[str, Any]:
    if path.empty or not np.isfinite(entry_price) or entry_price <= 0:
        return {"ret": np.nan, "hold_days": 0, "reason": "no_path"}
    if use_atr_stop and np.isfinite(stop_loss_price) and stop_loss_price > 0:
        resolved_stop = stop_loss_price / entry_price - 1.0
    else:
        resolved_stop = float(stop_pct) if stop_pct is not None else -0.99
    resolved_stop = max(-0.20, min(-0.005, resolved_stop))
    peak = -0.99
    armed = False
    armed_day = 0
    last_close_ret = np.nan
    limit = min(max_hold_days, len(path))
    for day_idx, row in enumerate(path.iloc[:limit].itertuples(index=False), start=1):
        o = float(row.open)
        h = float(row.high)
        low = float(row.low)
        c = float(row.close)
        if not all(np.isfinite(x) and x > 0 for x in (o, h, low, c)):
            continue
        open_ret = o / entry_price - 1.0
        high_ret = h / entry_price - 1.0
        low_ret = low / entry_price - 1.0
        close_ret = c / entry_price - 1.0
        last_close_ret = close_ret

        if open_ret <= resolved_stop:
            return {"ret": open_ret, "hold_days": day_idx, "reason": "gap_stop"}
        if low_ret <= resolved_stop:
            return {"ret": resolved_stop, "hold_days": day_idx, "reason": "stop_loss"}

        if take_profit is not None and high_ret >= take_profit:
            return {"ret": float(take_profit), "hold_days": day_idx, "reason": "take_profit"}

        peak = max(peak, high_ret, open_ret)
        if trail_arm is not None and peak >= trail_arm and not armed:
            armed = True
            armed_day = day_idx
        if armed and day_idx > armed_day and trail_gap is not None:
            floor = peak - trail_gap
            if close_ret <= floor:
                return {"ret": close_ret, "hold_days": day_idx, "reason": "trailing_stop"}

        if day_idx >= max_hold_days:
            return {"ret": close_ret, "hold_days": day_idx, "reason": "time_exit"}

        peak = max(peak, close_ret)
    return {"ret": last_close_ret, "hold_days": limit, "reason": "time_exit"}


def _simulate_current_hold_weakness(
    path: pd.DataFrame,
    entry_price: float,
    stop_loss_price: float,
    *,
    max_hold_days: int,
    trail_arm: float | None = None,
    trail_gap: float | None = None,
) -> Dict[str, Any]:
    if path.empty or not np.isfinite(entry_price) or entry_price <= 0:
        return {"ret": np.nan, "hold_days": 0, "reason": "no_path"}
    last_close_ret = np.nan
    limit = min(max_hold_days, len(path))
    for day_idx in range(1, limit + 1):
        row = path.iloc[day_idx - 1]
        c = float(row.get("close", np.nan))
        low = float(row.get("low", c))
        ma5 = float(row.get("ma5", np.nan))
        prev_low = float(path.iloc[day_idx - 2].get("low", np.nan)) if day_idx >= 2 else np.nan
        if not np.isfinite(c) or c <= 0:
            continue
        last_close_ret = c / entry_price - 1.0

        if trail_arm is not None and trail_gap is not None:
            high_series = pd.to_numeric(path.iloc[:day_idx].get("high", pd.Series(dtype=float)), errors="coerce")
            observed_peak = float(high_series.max()) if not high_series.dropna().empty else c
            peak_ret = observed_peak / entry_price - 1.0 if observed_peak > 0 else np.nan
            if np.isfinite(peak_ret) and peak_ret >= trail_arm and last_close_ret <= peak_ret - trail_gap:
                return {"ret": last_close_ret, "hold_days": day_idx, "reason": "trailing_stop"}

        if day_idx >= max_hold_days:
            return {"ret": last_close_ret, "hold_days": day_idx, "reason": "time_exit"}
        if np.isfinite(low) and np.isfinite(stop_loss_price) and stop_loss_price > 0 and low <= stop_loss_price:
            return {"ret": stop_loss_price / entry_price - 1.0, "hold_days": day_idx, "reason": "atr_stop"}
        if np.isfinite(ma5) and ma5 > 0 and c < ma5:
            return {"ret": last_close_ret, "hold_days": day_idx, "reason": "below_ma5"}
        if np.isfinite(prev_low) and prev_low > 0 and c < prev_low:
            return {"ret": last_close_ret, "hold_days": day_idx, "reason": "below_prev_low"}
    return {"ret": last_close_ret, "hold_days": limit, "reason": "time_exit"}


def _profile_grid() -> List[Dict[str, Any]]:
    profiles: List[Dict[str, Any]] = []
    for n in range(1, 6):
        profiles.append({"name": f"fixed_t{n}", "kind": "fixed", "hold": n})
    for n in (3, 4, 5):
        profiles.append({"name": f"current_hold_weakness_t{n}", "kind": "current", "hold": n})
    for arm, gap in ((0.035, 0.02), (0.04, 0.02), (0.04, 0.025), (0.045, 0.025), (0.05, 0.03)):
        for n in (3, 4):
            profiles.append({
                "name": f"current_trail{arm:.1%}_{gap:.1%}_t{n}",
                "kind": "current",
                "hold": n,
                "trail_arm": arm,
                "trail_gap": gap,
            })
    for hold in (2, 3, 4, 5):
        profiles.append({"name": f"atr_stop_t{hold}", "hold": hold, "use_atr_stop": True})
    for stop in (-0.025, -0.035, -0.045):
        for hold in (3, 4, 5):
            profiles.append({"name": f"stop{abs(stop):.1%}_t{hold}", "hold": hold, "stop_pct": stop})
    for arm, gap in ((0.04, 0.025), (0.05, 0.03), (0.06, 0.035)):
        for hold in (3, 4, 5):
            profiles.append({"name": f"trail{arm:.0%}_{gap:.1%}_t{hold}", "hold": hold, "stop_pct": -0.045, "trail_arm": arm, "trail_gap": gap})
    for stop in (-0.035, -0.045):
        for arm in (0.035, 0.04, 0.045, 0.05):
            for gap in (0.02, 0.025, 0.03):
                for hold in (2, 3, 4):
                    profiles.append({
                        "name": f"trail{arm:.1%}_{gap:.1%}_stop{abs(stop):.1%}_t{hold}",
                        "hold": hold,
                        "stop_pct": stop,
                        "trail_arm": arm,
                        "trail_gap": gap,
                    })
    for tp in (0.04, 0.055, 0.07):
        for hold in (3, 4, 5):
            profiles.append({"name": f"tp{tp:.1%}_stop3.5_t{hold}", "hold": hold, "stop_pct": -0.035, "take_profit": tp})
    return profiles


def _evaluate_profiles(trades: pd.DataFrame, paths: Dict[int, pd.DataFrame], cost_bps: float) -> Dict[str, Any]:
    cost = float(cost_bps) / 10000.0
    rows: List[Dict[str, Any]] = []
    details: Dict[str, List[Dict[str, Any]]] = {}
    for profile in _profile_grid():
        name = str(profile["name"])
        if profile.get("kind") == "fixed":
            ret_col = f"ret_t{profile['hold']}_net"
            tmp = trades.copy()
            tmp["exit_hold_days"] = int(profile["hold"])
            metric = _metric(tmp, ret_col)
            rows.append({"profile": name, **metric, "reason_top": "fixed_close"})
            continue

        recs: List[Dict[str, Any]] = []
        for idx, trade in trades.iterrows():
            if profile.get("kind") == "current":
                sim = _simulate_current_hold_weakness(
                    paths.get(int(idx), pd.DataFrame()),
                    float(trade.get("entry_price", np.nan)),
                    float(trade.get("stop_loss", np.nan)),
                    max_hold_days=int(profile["hold"]),
                    trail_arm=profile.get("trail_arm"),
                    trail_gap=profile.get("trail_gap"),
                )
            else:
                sim = _simulate_exit(
                    paths.get(int(idx), pd.DataFrame()),
                    float(trade.get("entry_price", np.nan)),
                    float(trade.get("stop_loss", np.nan)),
                    max_hold_days=int(profile["hold"]),
                    stop_pct=profile.get("stop_pct"),
                    use_atr_stop=bool(profile.get("use_atr_stop", False)),
                    trail_arm=profile.get("trail_arm"),
                    trail_gap=profile.get("trail_gap"),
                    take_profit=profile.get("take_profit"),
                )
            recs.append(
                {
                    "signal_date": str(trade.get("signal_date")),
                    "confirm_date": str(trade.get("confirm_date")),
                    "ts_code": str(trade.get("ts_code")),
                    "name": str(trade.get("name")),
                    "signal_grade": str(trade.get("signal_grade")),
                    "signal_score": float(trade.get("signal_score", np.nan)),
                    "volume_ratio": float(trade.get("volume_ratio", np.nan)),
                    "exit_ret_net": sim["ret"] - cost if pd.notna(sim["ret"]) else np.nan,
                    "exit_hold_days": int(sim["hold_days"]),
                    "exit_reason": str(sim["reason"]),
                }
            )
        df = pd.DataFrame(recs)
        metric = _metric(df, "exit_ret_net")
        reason_top = df["exit_reason"].value_counts().head(3).to_dict() if not df.empty else {}
        rows.append({"profile": name, **metric, "reason_top": reason_top})
        details[name] = recs
    ranked = pd.DataFrame(rows).sort_values(
        ["port_total_ret", "pf", "mean_ret", "port_mdd"],
        ascending=[False, False, False, False],
    )
    return {"ranking": ranked.to_dict(orient="records"), "details": details}


def _split_dates(trades: pd.DataFrame, ratio: float = 0.72) -> Dict[str, set[str]]:
    dates = sorted(trades["signal_date"].astype(str).dropna().unique().tolist()) if not trades.empty else []
    if len(dates) < 3:
        return {"train": set(dates), "oos": set(), "recent": set(dates[-5:])}
    split_at = int(len(dates) * ratio)
    split_at = max(1, min(len(dates) - 1, split_at))
    recent_n = min(20, max(5, len(dates) // 5))
    return {
        "train": set(dates[:split_at]),
        "oos": set(dates[split_at:]),
        "recent": set(dates[-recent_n:]),
    }


def _profile_details_frame(details: Dict[str, List[Dict[str, Any]]], profile: str) -> pd.DataFrame:
    df = pd.DataFrame(details.get(profile, []))
    if df.empty:
        return df
    df["signal_date"] = df["signal_date"].astype(str)
    return df


def _split_stability(details: Dict[str, List[Dict[str, Any]]], trades: pd.DataFrame, profiles: List[str]) -> Dict[str, Any]:
    splits = _split_dates(trades)
    out: Dict[str, Any] = {}
    for profile in profiles:
        df = _profile_details_frame(details, profile)
        if df.empty:
            continue
        out[profile] = {}
        for split_name, split_dates in splits.items():
            sub = df[df["signal_date"].isin(split_dates)].copy()
            out[profile][split_name] = _metric(sub, "exit_ret_net")
    return out


def _evaluate_grade_policies(
    details: Dict[str, List[Dict[str, Any]]],
    trades: pd.DataFrame,
    ranking: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    profiles = [str(r["profile"]) for r in ranking]
    a_candidates = [
        p for p in profiles
        if p in {"fixed_t3", "fixed_t4", "fixed_t5", "trail4.0%_2.5%_stop4.5%_t3", "trail4.5%_2.5%_stop4.5%_t4", "trail5.0%_2.5%_stop4.5%_t4"}
    ]
    b_candidates = [
        p for p in profiles
        if p in {"fixed_t1", "fixed_t2", "fixed_t3", "trail4.0%_2.5%_stop4.5%_t3", "trail4.0%_2.5%_stop4.5%_t4", "trail5.0%_2.5%_stop4.5%_t3"}
    ]
    base_policy = ("trail4.0%_2.5%_stop4.5%_t3", "trail4.0%_2.5%_stop4.5%_t3")
    policies = set([base_policy])
    for a in a_candidates:
        for b in b_candidates:
            policies.add((a, b))

    rows: List[Dict[str, Any]] = []
    splits = _split_dates(trades)
    for a_profile, b_profile in sorted(policies):
        a_df = _profile_details_frame(details, a_profile)
        b_df = _profile_details_frame(details, b_profile)
        if a_df.empty or b_df.empty:
            continue
        chosen = pd.concat(
            [
                a_df[a_df["signal_grade"].eq("A")],
                b_df[~b_df["signal_grade"].eq("A")],
            ],
            ignore_index=True,
        ).sort_values(["signal_date", "ts_code"])
        metric = _metric(chosen, "exit_ret_net")
        split_metrics = {
            name: _metric(chosen[chosen["signal_date"].isin(ds)].copy(), "exit_ret_net")
            for name, ds in splits.items()
        }
        rows.append(
            {
                "policy": f"A={a_profile};B={b_profile}",
                "a_profile": a_profile,
                "b_profile": b_profile,
                **metric,
                "split": split_metrics,
            }
        )
    rows.sort(
        key=lambda r: (
            r.get("port_mdd", -99.0) >= -0.09,
            r.get("win_rate", 0.0) >= 0.65,
            r.get("pf", 0.0),
            r.get("port_total_ret", 0.0),
        ),
        reverse=True,
    )
    return rows


def _group_horizon_table(trades: pd.DataFrame) -> Dict[str, List[Dict[str, Any]]]:
    out: Dict[str, List[Dict[str, Any]]] = {}
    for group_col in ("signal_grade", "confirm_month"):
        rows: List[Dict[str, Any]] = []
        for key, sub in trades.groupby(group_col):
            row: Dict[str, Any] = {"group": str(key), "trades": int(len(sub))}
            for n in range(1, 6):
                m = _metric(sub.assign(exit_hold_days=n), f"ret_t{n}_net")
                row[f"t{n}_mean"] = m["mean_ret"]
                row[f"t{n}_pf"] = m["pf"]
            rows.append(row)
        out[group_col] = rows
    return out


def _write_markdown(path: Path, payload: Dict[str, Any]) -> None:
    lines: List[str] = []
    lines.append("# Breakout V5 Exit Diagnosis\n\n")
    lines.append(f"- generated_at: {payload['generated_at']}\n")
    lines.append(f"- source_trades: `{payload['source_trades']}`\n")
    lines.append(f"- filtered_trades: {payload['filtered_trades']}\n")
    lines.append(f"- recommendation: `{payload['recommendation']['profile']}`\n")
    lines.append(f"- recommendation_reason: {payload['recommendation']['reason']}\n\n")
    lines.append("## Profile Ranking\n\n")
    lines.append("| rank | profile | trades | win | mean | median | PF | total | maxdd | sharpe | avg_hold |\n")
    lines.append("| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |\n")
    for i, row in enumerate(payload["ranking"][:20], start=1):
        lines.append(
            f"| {i} | `{row['profile']}` | {int(row.get('n_trades', 0) or 0)} | {_fmt_pct(row.get('win_rate'))} | "
            f"{_fmt_pct(row.get('mean_ret'))} | {_fmt_pct(row.get('median_ret'))} | {_fmt_num(row.get('pf'))} | "
            f"{_fmt_pct(row.get('port_total_ret'))} | {_fmt_pct(row.get('port_mdd'))} | {_fmt_num(row.get('port_sharpe'))} | "
            f"{_fmt_num(row.get('avg_hold_days'))} |\n"
        )
    lines.append("\n## Fixed Horizon Summary\n\n")
    lines.append("| horizon | win | mean | median | PF | total | maxdd | sharpe |\n")
    lines.append("| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |\n")
    fixed = {row["profile"]: row for row in payload["ranking"] if str(row["profile"]).startswith("fixed_")}
    for n in range(1, 6):
        row = fixed.get(f"fixed_t{n}", {})
        lines.append(
            f"| T+{n} | {_fmt_pct(row.get('win_rate'))} | {_fmt_pct(row.get('mean_ret'))} | "
            f"{_fmt_pct(row.get('median_ret'))} | {_fmt_num(row.get('pf'))} | {_fmt_pct(row.get('port_total_ret'))} | "
            f"{_fmt_pct(row.get('port_mdd'))} | {_fmt_num(row.get('port_sharpe'))} |\n"
        )
    lines.append("\n## Grade Horizon Mean\n\n")
    lines.append("| grade | trades | T1 | T2 | T3 | T4 | T5 |\n")
    lines.append("| --- | ---: | ---: | ---: | ---: | ---: | ---: |\n")
    for row in payload["horizon_groups"].get("signal_grade", []):
        lines.append(
            f"| {row['group']} | {row['trades']} | {_fmt_pct(row.get('t1_mean'))} | {_fmt_pct(row.get('t2_mean'))} | "
            f"{_fmt_pct(row.get('t3_mean'))} | {_fmt_pct(row.get('t4_mean'))} | {_fmt_pct(row.get('t5_mean'))} |\n"
        )

    lines.append("\n## Stability Check\n\n")
    lines.append("| profile | split | trades | win | mean | PF | total | maxdd |\n")
    lines.append("| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |\n")
    for profile, splits in payload.get("split_stability", {}).items():
        for split, row in splits.items():
            lines.append(
                f"| `{profile}` | {split} | {int(row.get('n_trades', 0) or 0)} | {_fmt_pct(row.get('win_rate'))} | "
                f"{_fmt_pct(row.get('mean_ret'))} | {_fmt_num(row.get('pf'))} | {_fmt_pct(row.get('port_total_ret'))} | "
                f"{_fmt_pct(row.get('port_mdd'))} |\n"
            )

    lines.append("\n## A/B Exit Policies\n\n")
    lines.append("| rank | policy | trades | win | mean | PF | total | maxdd |\n")
    lines.append("| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: |\n")
    for i, row in enumerate(payload.get("grade_policy_ranking", [])[:12], start=1):
        lines.append(
            f"| {i} | `{row['policy']}` | {int(row.get('n_trades', 0) or 0)} | {_fmt_pct(row.get('win_rate'))} | "
            f"{_fmt_pct(row.get('mean_ret'))} | {_fmt_num(row.get('pf'))} | {_fmt_pct(row.get('port_total_ret'))} | "
            f"{_fmt_pct(row.get('port_mdd'))} |\n"
        )
    path.write_text("".join(lines), encoding="utf-8")


def _recommend(ranking: List[Dict[str, Any]]) -> Dict[str, Any]:
    fixed = {row["profile"]: row for row in ranking if str(row["profile"]).startswith("fixed_")}
    t1 = fixed.get("fixed_t1", {})
    candidates = [row for row in ranking if row.get("n_trades", 0) and not str(row["profile"]).startswith("tp4.0%")]
    best = candidates[0] if candidates else (ranking[0] if ranking else {})
    reason = "Highest portfolio total return among tested profiles."
    if best.get("profile") != "fixed_t1" and (best.get("port_mdd") or 0) < (t1.get("port_mdd") or 0):
        reason = "Improves return path but increases drawdown versus T+1; keep as diagnostic candidate."
    elif best.get("profile") == "fixed_t1":
        reason = "T+1 remains the cleanest exit on current sample."
    return {"profile": best.get("profile", ""), "reason": reason, "metrics": best}


def main() -> None:
    args = build_parser().parse_args()
    trades = _load_filtered_trades(
        Path(args.trades_csv),
        float(args.cost_bps),
        float(args.score_min),
        float(args.volume_min),
        float(args.market_ret5_stop),
        not bool(args.disable_market_ret5_filter),
    )
    paths = _load_paths(trades, max_hold_days=5)
    evaluated = _evaluate_profiles(trades, paths, float(args.cost_bps))
    focus_profiles = [
        "fixed_t1",
        "trail4.0%_2.5%_stop4.5%_t3",
        "trail5.0%_2.5%_stop4.5%_t4",
        "current_hold_weakness_t5",
    ]
    payload: Dict[str, Any] = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "source_trades": str(Path(args.trades_csv).resolve()),
        "cost_bps": float(args.cost_bps),
        "filters": {
            "score_min": float(args.score_min),
            "volume_min": float(args.volume_min),
            "market_ret5_stop": float(args.market_ret5_stop),
            "apply_market_ret5_filter": not bool(args.disable_market_ret5_filter),
        },
        "filtered_trades": int(len(trades)),
        "ranking": evaluated["ranking"],
        "split_stability": _split_stability(evaluated["details"], trades, focus_profiles),
        "grade_policy_ranking": _evaluate_grade_policies(evaluated["details"], trades, evaluated["ranking"]),
        "horizon_groups": _group_horizon_table(trades),
    }
    payload["recommendation"] = _recommend(payload["ranking"])

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = OUT_DIR / f"breakout_v5_exit_diagnosis_{stamp}.json"
    md_path = OUT_DIR / f"breakout_v5_exit_diagnosis_{stamp}.md"
    latest_json = OUT_DIR / "breakout_v5_exit_diagnosis_latest.json"
    latest_md = OUT_DIR / "breakout_v5_exit_diagnosis_latest.md"
    text = json.dumps(_jsonify(payload), ensure_ascii=False, indent=2)
    json_path.write_text(text + "\n", encoding="utf-8")
    latest_json.write_text(text + "\n", encoding="utf-8")
    _write_markdown(md_path, payload)
    _write_markdown(latest_md, payload)

    print(f"filtered_trades={len(trades)}")
    print(f"wrote {json_path}")
    print(f"wrote {md_path}")
    if payload["ranking"]:
        top = payload["ranking"][0]
        print(
            "best",
            top["profile"],
            "mean",
            _fmt_pct(top.get("mean_ret")),
            "pf",
            _fmt_num(top.get("pf")),
            "total",
            _fmt_pct(top.get("port_total_ret")),
            "mdd",
            _fmt_pct(top.get("port_mdd")),
        )


if __name__ == "__main__":
    main()
