#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Diagnose wide-breakout V2/V5 optimization on exported trade details."""

from __future__ import annotations

import argparse
import json
import math
import os
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

OUT_DIR = ROOT / "reports" / "strategy_optimization"
DB_PATH = Path(os.environ.get("DATABASE_PATH") or ROOT / "data" / "database" / "quant_system.db")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Diagnose wide-breakout optimization profiles.")
    parser.add_argument("--trades-csv", required=True, help="wide_breakout_backtest_trades_*.csv")
    parser.add_argument("--cost-bps", type=float, default=12.0)
    parser.add_argument("--score-min", type=float, default=80.0)
    parser.add_argument("--volume-min", type=float, default=1.35)
    parser.add_argument("--disable-v2-entry-guard", action="store_true")
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
    daily = df.assign(_ret=v).groupby("signal_date")["_ret"].mean().dropna().sort_index()
    eq = (1.0 + daily).cumprod() if not daily.empty else pd.Series(dtype=float)
    hold = pd.to_numeric(df.get("exit_hold_days", pd.Series(dtype=float)), errors="coerce").dropna()
    return {
        "n_trades": float(len(v)),
        "win_rate": float((v > 0).mean()),
        "mean_ret": float(v.mean()),
        "median_ret": float(v.median()),
        "pf": gain / loss if loss > 1e-12 else (99.0 if gain > 1e-12 else 0.0),
        "port_total_ret": float(eq.iloc[-1] - 1.0) if not eq.empty else 0.0,
        "port_mdd": float((eq / eq.cummax() - 1.0).min()) if not eq.empty else 0.0,
        "port_sharpe": float(daily.mean() / daily.std() * np.sqrt(252)) if len(daily) > 1 and daily.std() > 1e-12 else 0.0,
        "avg_hold_days": float(hold.mean()) if not hold.empty else float("nan"),
    }


def _load_trades(path: Path, cost_bps: float, apply_v2_guard: bool, score_min: float, volume_min: float) -> tuple[pd.DataFrame, int]:
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
    before = len(trades)
    if apply_v2_guard and not trades.empty:
        weak_confirm = (trades["signal_score"] >= score_min) & (trades["volume_ratio"] < volume_min)
        trades = trades.loc[~weak_confirm].copy()
    return trades.sort_values(["signal_date", "ts_code"]).reset_index(drop=True), before - len(trades)


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
    if rec.empty:
        return {}
    rec["confirm_idx"] = rec["confirm_idx"].astype(int)
    rec["exit_idx"] = rec["confirm_idx"].apply(lambda i: min(i + max_hold_days - 1, len(dates) - 1))
    symbols = sorted(rec["ts_code"].astype(str).unique().tolist())
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
    by_code = {code: sub.sort_values("trade_date").reset_index(drop=True) for code, sub in px.groupby("ts_code")}
    paths: Dict[int, pd.DataFrame] = {}
    for row in rec.itertuples(index=False):
        sub = by_code.get(str(row.ts_code))
        if sub is None:
            continue
        end = dates[int(row.exit_idx)]
        path = sub[(sub["trade_date"] >= str(row.confirm_date)) & (sub["trade_date"] <= end)].copy()
        if not path.empty:
            paths[int(row.trade_id)] = path.reset_index(drop=True)
    return paths


def _simulate_exit(
    path: pd.DataFrame,
    entry_price: float,
    *,
    max_hold_days: int,
    stop_pct: float = -0.045,
    trail_arm: float | None = None,
    trail_gap: float | None = None,
) -> Dict[str, Any]:
    if path.empty or not np.isfinite(entry_price) or entry_price <= 0:
        return {"ret": np.nan, "hold_days": 0, "reason": "no_path"}
    peak_ret = -0.99
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
        if open_ret <= stop_pct:
            return {"ret": open_ret, "hold_days": day_idx, "reason": "gap_stop"}
        if low_ret <= stop_pct:
            return {"ret": stop_pct, "hold_days": day_idx, "reason": "stop_loss"}
        peak_ret = max(peak_ret, high_ret, close_ret)
        if trail_arm is not None and trail_gap is not None and peak_ret >= trail_arm:
            if close_ret <= peak_ret - trail_gap:
                return {"ret": close_ret, "hold_days": day_idx, "reason": "trailing_stop"}
        if day_idx >= max_hold_days:
            return {"ret": close_ret, "hold_days": day_idx, "reason": "time_exit"}
    return {"ret": last_close_ret, "hold_days": limit, "reason": "time_exit"}


def _profile_grid() -> List[Dict[str, Any]]:
    profiles: List[Dict[str, Any]] = []
    for n in range(1, 6):
        profiles.append({"name": f"fixed_t{n}", "kind": "fixed", "hold": n})
    for stop in (-0.035, -0.045, -0.055):
        for arm in (0.035, 0.04, 0.045, 0.05):
            for gap in (0.02, 0.025, 0.03):
                for hold in (2, 3, 4, 5):
                    profiles.append(
                        {
                            "name": f"trail{arm:.1%}_{gap:.1%}_stop{abs(stop):.1%}_t{hold}",
                            "hold": hold,
                            "stop_pct": stop,
                            "trail_arm": arm,
                            "trail_gap": gap,
                        }
                    )
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
            rows.append({"profile": name, **_metric(tmp, ret_col), "reason_top": "fixed_close"})
            continue
        recs: List[Dict[str, Any]] = []
        for idx, trade in trades.iterrows():
            sim = _simulate_exit(
                paths.get(int(idx), pd.DataFrame()),
                float(trade.get("entry_price", np.nan)),
                max_hold_days=int(profile["hold"]),
                stop_pct=float(profile["stop_pct"]),
                trail_arm=float(profile["trail_arm"]),
                trail_gap=float(profile["trail_gap"]),
            )
            recs.append(
                {
                    "signal_date": str(trade.get("signal_date")),
                    "confirm_date": str(trade.get("confirm_date")),
                    "ts_code": str(trade.get("ts_code")),
                    "name": str(trade.get("name")),
                    "signal_grade": str(trade.get("signal_grade")),
                    "exit_ret_net": sim["ret"] - cost if pd.notna(sim["ret"]) else np.nan,
                    "exit_hold_days": int(sim["hold_days"]),
                    "exit_reason": str(sim["reason"]),
                }
            )
        df = pd.DataFrame(recs)
        rows.append({"profile": name, **_metric(df, "exit_ret_net"), "reason_top": df["exit_reason"].value_counts().head(3).to_dict()})
        details[name] = recs
    ranking = pd.DataFrame(rows).sort_values(
        ["pf", "mean_ret", "port_mdd", "port_total_ret"],
        ascending=[False, False, False, False],
    )
    return {"ranking": ranking.to_dict(orient="records"), "details": details}


def _details_frame(details: Dict[str, List[Dict[str, Any]]], profile: str) -> pd.DataFrame:
    df = pd.DataFrame(details.get(profile, []))
    if not df.empty:
        df["signal_date"] = df["signal_date"].astype(str)
    return df


def _split_dates(trades: pd.DataFrame, train_ratio: float = 0.70) -> Dict[str, set[str]]:
    dates = sorted(trades["signal_date"].astype(str).dropna().unique().tolist()) if not trades.empty else []
    if len(dates) < 3:
        return {"train": set(dates), "oos": set(), "recent": set(dates)}
    split_at = int(len(dates) * train_ratio)
    split_at = max(1, min(len(dates) - 1, split_at))
    recent_n = min(30, max(5, len(dates) // 4))
    return {
        "train": set(dates[:split_at]),
        "oos": set(dates[split_at:]),
        "recent": set(dates[-recent_n:]),
    }


def _profile_split_stability(
    details: Dict[str, List[Dict[str, Any]]],
    trades: pd.DataFrame,
    profiles: List[str],
) -> Dict[str, Dict[str, Dict[str, float]]]:
    splits = _split_dates(trades)
    out: Dict[str, Dict[str, Dict[str, float]]] = {}
    for profile in profiles:
        df = _details_frame(details, profile)
        if df.empty:
            continue
        out[profile] = {}
        for split_name, split_dates in splits.items():
            sub = df[df["signal_date"].isin(split_dates)].copy()
            out[profile][split_name] = _metric(sub, "exit_ret_net")
    return out


def _combine_policy(details: Dict[str, List[Dict[str, Any]]], a_profile: str, b_profile: str) -> pd.DataFrame:
    a_df = _details_frame(details, a_profile)
    b_df = _details_frame(details, b_profile)
    if a_df.empty or b_df.empty:
        return pd.DataFrame()
    return pd.concat(
        [a_df[a_df["signal_grade"].eq("A")], b_df[~b_df["signal_grade"].eq("A")]],
        ignore_index=True,
    )


def _policy_split_stability(
    details: Dict[str, List[Dict[str, Any]]],
    trades: pd.DataFrame,
    policies: List[Dict[str, Any]],
) -> Dict[str, Dict[str, Dict[str, float]]]:
    splits = _split_dates(trades)
    out: Dict[str, Dict[str, Dict[str, float]]] = {}
    for policy in policies:
        name = str(policy.get("policy", ""))
        chosen = _combine_policy(
            details,
            str(policy.get("a_profile", "")),
            str(policy.get("b_profile", "")),
        )
        if chosen.empty:
            continue
        out[name] = {}
        for split_name, split_dates in splits.items():
            sub = chosen[chosen["signal_date"].isin(split_dates)].copy()
            out[name][split_name] = _metric(sub, "exit_ret_net")
    return out


def _grade_policies(details: Dict[str, List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    a_options = ["fixed_t3", "fixed_t4", "trail4.5%_2.5%_stop4.5%_t4", "trail5.0%_2.5%_stop4.5%_t4"]
    b_options = ["fixed_t2", "fixed_t3", "trail4.0%_2.5%_stop4.5%_t3", "trail4.5%_2.5%_stop4.5%_t3"]
    rows: List[Dict[str, Any]] = []
    for a in a_options:
        for b in b_options:
            a_df = _details_frame(details, a)
            b_df = _details_frame(details, b)
            if a_df.empty or b_df.empty:
                continue
            chosen = pd.concat([a_df[a_df["signal_grade"].eq("A")], b_df[~b_df["signal_grade"].eq("A")]], ignore_index=True)
            rows.append({"policy": f"A={a};B={b}", "a_profile": a, "b_profile": b, **_metric(chosen, "exit_ret_net")})
    rows.sort(key=lambda r: (r.get("pf", 0.0), r.get("mean_ret", 0.0), r.get("port_mdd", -99.0)), reverse=True)
    return rows


def _write_markdown(path: Path, payload: Dict[str, Any]) -> None:
    lines: List[str] = []
    lines.append("# Wide Breakout Optimization Diagnosis\n\n")
    lines.append(f"- generated_at: {payload['generated_at']}\n")
    lines.append(f"- source_trades: `{payload['source_trades']}`\n")
    lines.append(f"- raw_trades: {payload['raw_trades']}\n")
    lines.append(f"- v2_filtered_out: {payload['v2_filtered_out']}\n")
    lines.append(f"- effective_trades: {payload['effective_trades']}\n\n")
    lines.append("## Fixed Horizon\n\n")
    lines.append("| horizon | trades | win | mean | median | PF | total | maxdd |\n")
    lines.append("| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |\n")
    fixed = {row["profile"]: row for row in payload["ranking"] if str(row["profile"]).startswith("fixed_")}
    for n in range(1, 6):
        row = fixed.get(f"fixed_t{n}", {})
        lines.append(
            f"| T+{n} | {int(row.get('n_trades', 0) or 0)} | {_fmt_pct(row.get('win_rate'))} | "
            f"{_fmt_pct(row.get('mean_ret'))} | {_fmt_pct(row.get('median_ret'))} | {_fmt_num(row.get('pf'))} | "
            f"{_fmt_pct(row.get('port_total_ret'))} | {_fmt_pct(row.get('port_mdd'))} |\n"
        )
    lines.append("\n## Profile Ranking\n\n")
    lines.append("| rank | profile | trades | win | mean | PF | total | maxdd | avg_hold |\n")
    lines.append("| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |\n")
    for i, row in enumerate(payload["ranking"][:20], start=1):
        lines.append(
            f"| {i} | `{row['profile']}` | {int(row.get('n_trades', 0) or 0)} | {_fmt_pct(row.get('win_rate'))} | "
            f"{_fmt_pct(row.get('mean_ret'))} | {_fmt_num(row.get('pf'))} | {_fmt_pct(row.get('port_total_ret'))} | "
            f"{_fmt_pct(row.get('port_mdd'))} | {_fmt_num(row.get('avg_hold_days'))} |\n"
        )
    lines.append("\n## A/B Policies\n\n")
    lines.append("| rank | policy | trades | win | mean | PF | total | maxdd |\n")
    lines.append("| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: |\n")
    for i, row in enumerate(payload.get("grade_policy_ranking", [])[:12], start=1):
        lines.append(
            f"| {i} | `{row['policy']}` | {int(row.get('n_trades', 0) or 0)} | {_fmt_pct(row.get('win_rate'))} | "
            f"{_fmt_pct(row.get('mean_ret'))} | {_fmt_num(row.get('pf'))} | {_fmt_pct(row.get('port_total_ret'))} | "
            f"{_fmt_pct(row.get('port_mdd'))} |\n"
        )
    lines.append("\n## Profile Walk-Forward Stability\n\n")
    lines.append("| profile | split | trades | win | mean | PF | total | maxdd |\n")
    lines.append("| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |\n")
    for profile, splits in payload.get("profile_split_stability", {}).items():
        for split_name, row in splits.items():
            lines.append(
                f"| `{profile}` | {split_name} | {int(row.get('n_trades', 0) or 0)} | {_fmt_pct(row.get('win_rate'))} | "
                f"{_fmt_pct(row.get('mean_ret'))} | {_fmt_num(row.get('pf'))} | {_fmt_pct(row.get('port_total_ret'))} | "
                f"{_fmt_pct(row.get('port_mdd'))} |\n"
            )
    lines.append("\n## Policy Walk-Forward Stability\n\n")
    lines.append("| policy | split | trades | win | mean | PF | total | maxdd |\n")
    lines.append("| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |\n")
    for policy, splits in payload.get("policy_split_stability", {}).items():
        for split_name, row in splits.items():
            lines.append(
                f"| `{policy}` | {split_name} | {int(row.get('n_trades', 0) or 0)} | {_fmt_pct(row.get('win_rate'))} | "
                f"{_fmt_pct(row.get('mean_ret'))} | {_fmt_num(row.get('pf'))} | {_fmt_pct(row.get('port_total_ret'))} | "
                f"{_fmt_pct(row.get('port_mdd'))} |\n"
            )
    path.write_text("".join(lines), encoding="utf-8")


def main() -> None:
    args = build_parser().parse_args()
    trades, filtered_out = _load_trades(
        Path(args.trades_csv),
        cost_bps=float(args.cost_bps),
        apply_v2_guard=not bool(args.disable_v2_entry_guard),
        score_min=float(args.score_min),
        volume_min=float(args.volume_min),
    )
    paths = _load_paths(trades, max_hold_days=5)
    evaluated = _evaluate_profiles(trades, paths, float(args.cost_bps))
    grade_policy_ranking = _grade_policies(evaluated["details"])
    focus_profiles = [
        "fixed_t1",
        "fixed_t3",
        "fixed_t5",
        "trail4.0%_2.5%_stop4.5%_t3",
        "trail4.5%_2.5%_stop4.5%_t4",
        "trail5.0%_2.5%_stop4.5%_t4",
        "trail5.0%_3.0%_stop4.5%_t4",
    ]
    focus_policies = grade_policy_ranking[:6]
    payload = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "source_trades": str(Path(args.trades_csv).resolve()),
        "raw_trades": int(len(trades) + filtered_out),
        "v2_filtered_out": int(filtered_out),
        "effective_trades": int(len(trades)),
        "cost_bps": float(args.cost_bps),
        "v2_guard": {
            "enabled": not bool(args.disable_v2_entry_guard),
            "score_min": float(args.score_min),
            "volume_min": float(args.volume_min),
        },
        "ranking": evaluated["ranking"],
        "grade_policy_ranking": grade_policy_ranking,
        "profile_split_stability": _profile_split_stability(evaluated["details"], trades, focus_profiles),
        "policy_split_stability": _policy_split_stability(evaluated["details"], trades, focus_policies),
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = OUT_DIR / f"wide_breakout_optimization_diagnosis_{stamp}.json"
    md_path = OUT_DIR / f"wide_breakout_optimization_diagnosis_{stamp}.md"
    latest_json = OUT_DIR / "wide_breakout_optimization_diagnosis_latest.json"
    latest_md = OUT_DIR / "wide_breakout_optimization_diagnosis_latest.md"
    text = json.dumps(_jsonify(payload), ensure_ascii=False, indent=2)
    json_path.write_text(text + "\n", encoding="utf-8")
    latest_json.write_text(text + "\n", encoding="utf-8")
    _write_markdown(md_path, payload)
    _write_markdown(latest_md, payload)
    print(f"raw_trades={payload['raw_trades']} v2_filtered_out={filtered_out} effective={len(trades)}")
    if payload["ranking"]:
        top = payload["ranking"][0]
        print(
            "best",
            top["profile"],
            "win",
            _fmt_pct(top.get("win_rate")),
            "mean",
            _fmt_pct(top.get("mean_ret")),
            "pf",
            _fmt_num(top.get("pf")),
            "mdd",
            _fmt_pct(top.get("port_mdd")),
        )
    print(f"wrote {md_path}")


if __name__ == "__main__":
    main()
