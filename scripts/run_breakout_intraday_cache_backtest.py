# -*- coding: utf-8 -*-
"""
Breakout intraday backtest on the breakout-specific data chain:
1) watchlist history from breakout strategy export
2) minute bars from data/intraday_cache parquet files
3) daily prices from data/database/quant_system.db for forward returns
"""

from __future__ import annotations

import os
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
WATCHLIST_CSV = ROOT / "data" / "reports" / "breakout_watchlist_history_latest.csv"
CACHE_DIR = ROOT / "data" / "intraday_cache"
DAILY_DB = ROOT / "data" / "database" / "quant_system.db"
REPORT_DIR = ROOT / "data" / "reports"

FNAME_RE = re.compile(r"^(\d{6})_(\d{4}-\d{2}-\d{2})_(\d{4}-\d{2}-\d{2})_(.+)\.parquet$")


@dataclass
class Params:
    breakout_max_chase: float = 0.008
    volume_confirm_ratio: float = 1.2
    volume_normal_ratio: float = 1.0
    max_intraday_gain: float = 0.05
    limit_up_pct: float = 0.10
    buy_slippage_bps: float = 10.0
    sell_slippage_bps: float = 10.0
    buy_commission_bps: float = 3.0
    sell_commission_bps: float = 3.0
    sell_stamp_duty_bps: float = 10.0


def is_mainboard(ts_code: str) -> bool:
    text = str(ts_code or "").upper()
    if text.endswith(".SH"):
        return text[:3] in {"600", "601", "603", "605"}
    if text.endswith(".SZ"):
        return text[:3] in {"000", "001", "002", "003"}
    return False


def parse_ymd(text: str) -> str:
    digits = "".join(ch for ch in str(text or "") if ch.isdigit())
    return digits[:8] if len(digits) >= 8 else ""


def ymd_to_iso(ymd: str) -> str:
    return f"{ymd[:4]}-{ymd[4:6]}-{ymd[6:8]}"


def load_watchlist() -> pd.DataFrame:
    if not WATCHLIST_CSV.exists():
        raise FileNotFoundError(f"watchlist not found: {WATCHLIST_CSV}")
    df = pd.read_csv(WATCHLIST_CSV, encoding="utf-8-sig")
    if df.empty:
        raise RuntimeError("watchlist is empty")
    df["watch_date"] = df["watch_date"].map(parse_ymd)
    df = df[df["watch_date"].str.len() == 8].copy()
    df = df[df["ts_code"].map(is_mainboard)].copy()
    df["symbol6"] = df["ts_code"].astype(str).str[:6]
    return df.reset_index(drop=True)


def load_daily_data(ts_codes: List[str], min_date: str, max_date: str) -> pd.DataFrame:
    conn = sqlite3.connect(str(DAILY_DB))
    try:
        placeholders = ",".join(["?"] * len(ts_codes))
        sql = f"""
        SELECT ts_code, trade_date, open, high, low, close, vol
        FROM stock_daily
        WHERE ts_code IN ({placeholders})
          AND trade_date >= ?
          AND trade_date <= ?
        ORDER BY ts_code, trade_date
        """
        params = list(ts_codes) + [min_date, max_date]
        df = pd.read_sql_query(sql, conn, params=params)
    finally:
        conn.close()
    df["trade_date"] = df["trade_date"].astype(str)
    for col in ["open", "high", "low", "close", "vol"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["close", "vol"]).copy()
    return df


def load_trade_dates() -> List[str]:
    conn = sqlite3.connect(str(DAILY_DB))
    try:
        cov = pd.read_sql_query(
            """
            SELECT trade_date, COUNT(DISTINCT ts_code) AS n_symbols
            FROM stock_daily
            GROUP BY trade_date
            ORDER BY trade_date
            """,
            conn,
        )
    finally:
        conn.close()
    cov["trade_date"] = cov["trade_date"].astype(str)
    # Only remove obvious broken dates.
    cov = cov[cov["n_symbols"] >= 1000].copy()
    return cov["trade_date"].tolist()


def build_next_trade_date_map(trade_dates: List[str]) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for i, d in enumerate(trade_dates[:-1]):
        out[d] = trade_dates[i + 1]
    return out


def build_cache_index(cache_dir: Path) -> Dict[str, List[Tuple[str, str, Path]]]:
    out: Dict[str, List[Tuple[str, str, Path]]] = {}
    for p in cache_dir.glob("*.parquet"):
        m = FNAME_RE.match(p.name)
        if not m:
            continue
        sym6, d0, d1, _ = m.groups()
        out.setdefault(sym6, []).append((d0, d1, p))
    return out


def find_cache_file(
    ranges: List[Tuple[str, str, Path]],
    target_iso: str,
) -> Optional[Path]:
    hit: List[Tuple[int, Path]] = []
    for d0, d1, p in ranges:
        if d0 <= target_iso <= d1:
            span = (datetime.strptime(d1, "%Y-%m-%d") - datetime.strptime(d0, "%Y-%m-%d")).days
            hit.append((span, p))
    if not hit:
        return None
    hit.sort(key=lambda x: x[0])
    return hit[0][1]


def build_vol_ma20_map(daily_df: pd.DataFrame) -> Dict[Tuple[str, str], float]:
    out: Dict[Tuple[str, str], float] = {}
    for code, sub in daily_df.groupby("ts_code"):
        s = sub.sort_values("trade_date").copy()
        s["vol_ma20"] = s["vol"].rolling(20, min_periods=20).mean()
        for _, r in s.iterrows():
            out[(str(code), str(r["trade_date"]))] = float(r["vol_ma20"]) if pd.notna(r["vol_ma20"]) else np.nan
    return out


def run() -> Tuple[pd.DataFrame, Dict[str, object]]:
    p = Params()
    watch = load_watchlist()
    trade_dates = load_trade_dates()
    next_map = build_next_trade_date_map(trade_dates)
    cache_index = build_cache_index(CACHE_DIR)

    min_watch = watch["watch_date"].min()
    max_watch = watch["watch_date"].max()
    max_need = trade_dates[min(len(trade_dates) - 1, trade_dates.index(max_watch) + 4)] if max_watch in trade_dates else trade_dates[-1]
    daily_df = load_daily_data(sorted(watch["ts_code"].unique().tolist()), min_watch, max_need)
    daily_close_map = {
        (str(r["ts_code"]), str(r["trade_date"])): float(r["close"])
        for _, r in daily_df.iterrows()
    }
    date_seq_by_code: Dict[str, List[str]] = {}
    for code, sub in daily_df.groupby("ts_code"):
        date_seq_by_code[str(code)] = sub["trade_date"].astype(str).tolist()
    vol_ma20_map = build_vol_ma20_map(daily_df)

    file_df_cache: Dict[Path, pd.DataFrame] = {}
    rows_total = len(watch)
    rows_with_next = 0
    rows_with_file = 0
    rows_with_daybars = 0
    rows_with_signal = 0
    blocked_limit_up = 0
    blocked_gap_chase = 0
    blocked_cost_nan = 0
    trades: List[dict] = []

    for _, row in watch.iterrows():
        ts_code = str(row["ts_code"])
        symbol6 = str(row["symbol6"])
        watch_date = str(row["watch_date"])
        entry_date = next_map.get(watch_date)
        if not entry_date:
            continue
        rows_with_next += 1
        entry_iso = ymd_to_iso(entry_date)

        ranges = cache_index.get(symbol6, [])
        if not ranges:
            continue
        cache_file = find_cache_file(ranges, entry_iso)
        if cache_file is None:
            continue
        rows_with_file += 1

        if cache_file not in file_df_cache:
            df_file = pd.read_parquet(cache_file)
            df_file["trade_time"] = pd.to_datetime(df_file["trade_time"], errors="coerce")
            if "trade_date" in df_file.columns:
                df_file["trade_date_iso"] = pd.to_datetime(df_file["trade_date"], errors="coerce").dt.strftime("%Y-%m-%d")
            else:
                df_file["trade_date_iso"] = df_file["trade_time"].dt.strftime("%Y-%m-%d")
            file_df_cache[cache_file] = df_file
        bars_all = file_df_cache[cache_file]
        bars = bars_all[bars_all["trade_date_iso"] == entry_iso].copy()
        if bars.empty:
            continue
        bars = bars.sort_values("trade_time").reset_index(drop=True)
        rows_with_daybars += 1

        trigger = float(row["trigger_price"])
        pivot = float(row["pivot"])
        max_entry = pivot * (1 + p.breakout_max_chase)
        prev_close = daily_close_map.get((ts_code, watch_date), np.nan)
        limit_up_price = prev_close * (1.0 + p.limit_up_pct) if np.isfinite(prev_close) else np.nan

        open_price = float(bars.iloc[0]["open"]) if pd.notna(bars.iloc[0]["open"]) else np.nan
        if not np.isfinite(open_price) or open_price <= 0:
            continue

        bars["high"] = pd.to_numeric(bars["high"], errors="coerce")
        bars["low"] = pd.to_numeric(bars["low"], errors="coerce")
        bars["close"] = pd.to_numeric(bars["close"], errors="coerce")
        bars["volume"] = pd.to_numeric(bars["volume"], errors="coerce")
        bars["cum_high"] = bars["high"].cummax()
        bars["cum_volume"] = bars["volume"].cumsum()

        vol_ma20_prev = vol_ma20_map.get((ts_code, watch_date), np.nan)
        hit = None
        gap_blocked_for_row = False

        for _, b in bars.iterrows():
            t = b["trade_time"]
            if pd.isna(t):
                continue
            hm = t.hour * 100 + t.minute
            if hm < 935 or hm > 1450:
                continue

            cum_high = float(b["cum_high"]) if pd.notna(b["cum_high"]) else np.nan
            bar_open = float(b["open"]) if pd.notna(b["open"]) else np.nan
            if not np.isfinite(cum_high) or cum_high < trigger:
                continue
            if trigger > max_entry:
                continue
            if (cum_high / open_price - 1.0) > p.max_intraday_gain:
                continue
            # Fill model closer to the original strategy semantics:
            # once the bar confirms a breakout, we buy at trigger or the bar open if it already gapped above.
            if not np.isfinite(bar_open) or bar_open <= 0:
                continue
            fill_price = max(trigger, bar_open)
            if fill_price > max_entry:
                gap_blocked_for_row = True
                continue
            # Avoid buying near daily upper limit where fills are often unavailable.
            if np.isfinite(limit_up_price) and fill_price >= limit_up_price * 0.999:
                blocked_limit_up += 1
                continue

            if np.isfinite(vol_ma20_prev) and vol_ma20_prev > 0:
                vol_ratio = (float(b["cum_volume"]) / 100.0) / float(vol_ma20_prev)
            else:
                vol_ratio = np.nan
            if not np.isfinite(vol_ratio) or vol_ratio < p.volume_normal_ratio:
                continue

            grade = "A" if vol_ratio >= p.volume_confirm_ratio else "B"
            pos_ratio = 1.0 if grade == "A" else 0.5
            buy_cost_rate = (p.buy_slippage_bps + p.buy_commission_bps) / 10000.0
            hit = {
                "confirm_time": t.strftime("%H:%M:%S"),
                "entry_price": fill_price,
                "entry_price_net": fill_price * (1.0 + buy_cost_rate),
                "entry_bar_close": float(b["close"]) if pd.notna(b["close"]) else np.nan,
                "volume_ratio": float(vol_ratio),
                "signal_grade": grade,
                "position_ratio": pos_ratio,
                "fill_vs_trigger_pct": fill_price / trigger - 1.0 if trigger > 0 else np.nan,
            }
            break

        if hit is None and gap_blocked_for_row:
            blocked_gap_chase += 1

        if hit is None:
            continue
        rows_with_signal += 1

        ret = {
            "ret_close0": np.nan,
            "ret_t1": np.nan,
            "ret_t2": np.nan,
            "ret_t3": np.nan,
            "ret_close0_gross": np.nan,
            "ret_t1_gross": np.nan,
            "ret_t2_gross": np.nan,
            "ret_t3_gross": np.nan,
        }
        seq = date_seq_by_code.get(ts_code, [])
        if entry_date in seq and hit["entry_price"] > 0 and hit["entry_price_net"] > 0:
            idx = seq.index(entry_date)
            d0 = seq[idx]
            c0 = daily_close_map.get((ts_code, d0), np.nan)
            if np.isfinite(c0) and c0 > 0:
                gross0 = c0 / hit["entry_price"] - 1.0
                sell_cost_rate = (
                    p.sell_slippage_bps + p.sell_commission_bps + p.sell_stamp_duty_bps
                ) / 10000.0
                net0 = (c0 * (1.0 - sell_cost_rate)) / hit["entry_price_net"] - 1.0
                ret["ret_close0"] = net0
                ret["ret_close0_gross"] = gross0
            for n in [1, 2, 3]:
                if idx + n < len(seq):
                    dn = seq[idx + n]
                    cn = daily_close_map.get((ts_code, dn), np.nan)
                    if np.isfinite(cn) and cn > 0:
                        gross_n = cn / hit["entry_price"] - 1.0
                        sell_cost_rate = (
                            p.sell_slippage_bps + p.sell_commission_bps + p.sell_stamp_duty_bps
                        ) / 10000.0
                        net_n = (cn * (1.0 - sell_cost_rate)) / hit["entry_price_net"] - 1.0
                        ret[f"ret_t{n}"] = net_n
                        ret[f"ret_t{n}_gross"] = gross_n
        else:
            blocked_cost_nan += 1

        trades.append(
            {
                "watch_date": watch_date,
                "entry_date": entry_date,
                "ts_code": ts_code,
                "name": row.get("name", ""),
                "industry": row.get("industry", ""),
                "signal_score": float(row["signal_score"]),
                "pivot": pivot,
                "trigger_price": trigger,
                "stop_loss": float(row["stop_loss"]),
                "confirm_time": hit["confirm_time"],
                "entry_price": hit["entry_price"],
                "entry_price_net": hit["entry_price_net"],
                "entry_bar_close": hit["entry_bar_close"],
                "fill_vs_trigger_pct": hit["fill_vs_trigger_pct"],
                "volume_ratio": hit["volume_ratio"],
                "vol_ma20_prev": vol_ma20_prev,
                "prev_close": prev_close,
                "limit_up_price": limit_up_price,
                "signal_grade": hit["signal_grade"],
                "position_ratio": hit["position_ratio"],
                **ret,
            }
        )

    trades_df = pd.DataFrame(trades).sort_values(["watch_date", "entry_date", "ts_code"]).reset_index(drop=True)
    summary = {
        "watch_rows_total": rows_total,
        "rows_with_next_trade_date": rows_with_next,
        "rows_with_cache_file": rows_with_file,
        "rows_with_entry_day_bars": rows_with_daybars,
        "rows_with_buy_signal": rows_with_signal,
        "blocked_limit_up": blocked_limit_up,
        "blocked_gap_chase": blocked_gap_chase,
        "blocked_cost_nan": blocked_cost_nan,
        "trade_rows": int(len(trades_df)),
        "cache_files": int(len(list(CACHE_DIR.glob("*.parquet")))),
        "cost_assumption": {
            "buy_slippage_bps": p.buy_slippage_bps,
            "sell_slippage_bps": p.sell_slippage_bps,
            "buy_commission_bps": p.buy_commission_bps,
            "sell_commission_bps": p.sell_commission_bps,
            "sell_stamp_duty_bps": p.sell_stamp_duty_bps,
        },
    }
    return trades_df, summary


def metric(series: pd.Series) -> Dict[str, float]:
    s = series.dropna()
    if s.empty:
        return {"n": 0, "win_rate": np.nan, "mean": np.nan, "median": np.nan, "pf": np.nan}
    gain = float(s[s > 0].sum())
    loss = float(-s[s < 0].sum())
    return {
        "n": int(len(s)),
        "win_rate": float((s > 0).mean()),
        "mean": float(s.mean()),
        "median": float(s.median()),
        "pf": (gain / loss) if loss > 1e-12 else np.nan,
    }


def fmt_pct(v: float) -> str:
    return "NA" if pd.isna(v) else f"{v * 100:.2f}%"


def fmt_num(v: float) -> str:
    return "NA" if pd.isna(v) else f"{v:.2f}"


def portfolio_stats(trades: pd.DataFrame, ret_col: str, weighted: bool) -> Dict[str, float]:
    if trades.empty or ret_col not in trades.columns:
        return {"total_ret": np.nan, "mdd": np.nan, "sharpe": np.nan}
    t = trades.dropna(subset=[ret_col]).copy()
    if t.empty:
        return {"total_ret": np.nan, "mdd": np.nan, "sharpe": np.nan}
    if weighted:
        t["r"] = t[ret_col] * t["position_ratio"]
    else:
        t["r"] = t[ret_col]
    day = t.groupby("watch_date")["r"].mean().sort_index()
    if day.empty:
        return {"total_ret": np.nan, "mdd": np.nan, "sharpe": np.nan}
    eq = (1.0 + day).cumprod()
    mdd = float((eq / eq.cummax() - 1.0).min())
    sharpe = float(day.mean() / day.std() * np.sqrt(252)) if day.std() > 1e-12 else np.nan
    return {"total_ret": float(eq.iloc[-1] - 1.0), "mdd": mdd, "sharpe": sharpe}


def main() -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    trades, summary = run()

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    trades_latest = REPORT_DIR / "breakout_intraday_cache_backtest_trades_latest.csv"
    trades_stamp = REPORT_DIR / f"breakout_intraday_cache_backtest_trades_{stamp}.csv"
    summary_latest = REPORT_DIR / "breakout_intraday_cache_backtest_summary_latest.md"
    summary_stamp = REPORT_DIR / f"breakout_intraday_cache_backtest_summary_{stamp}.md"

    trades.to_csv(trades_latest, index=False, encoding="utf-8-sig")
    trades.to_csv(trades_stamp, index=False, encoding="utf-8-sig")

    lines = [
        "# Breakout Intraday Cache Backtest Summary",
        "",
        "## Data Pipeline",
        f"- watchlist csv: {WATCHLIST_CSV}",
        f"- intraday cache dir: {CACHE_DIR}",
        f"- daily db: {DAILY_DB}",
        "",
        "## Coverage",
        f"- watchlist rows: {summary['watch_rows_total']}",
        f"- rows with next trade date (T+1): {summary['rows_with_next_trade_date']}",
        f"- rows with matched cache file: {summary['rows_with_cache_file']}",
        f"- rows with entry-day minute bars: {summary['rows_with_entry_day_bars']}",
        f"- rows with valid buy signal: {summary['rows_with_buy_signal']}",
        f"- blocked by limit-up guard: {summary['blocked_limit_up']}",
        f"- blocked by gap beyond max chase: {summary['blocked_gap_chase']}",
        f"- blocked by invalid entry/cost data: {summary['blocked_cost_nan']}",
        f"- executed trades: {summary['trade_rows']}",
        f"- intraday cache files parsed: {summary['cache_files']}",
        "",
        "## Cost Assumption",
        f"- buy slippage: {summary['cost_assumption']['buy_slippage_bps']} bps",
        f"- sell slippage: {summary['cost_assumption']['sell_slippage_bps']} bps",
        f"- buy commission: {summary['cost_assumption']['buy_commission_bps']} bps",
        f"- sell commission: {summary['cost_assumption']['sell_commission_bps']} bps",
        f"- stamp duty (sell): {summary['cost_assumption']['sell_stamp_duty_bps']} bps",
        "",
        "## Performance",
    ]

    for col in ["ret_close0", "ret_t1", "ret_t2", "ret_t3"]:
        m = metric(trades[col]) if (not trades.empty and col in trades.columns) else metric(pd.Series(dtype=float))
        lines.extend(
            [
                f"### {col}",
                f"- n: {m['n']}",
                f"- win_rate: {fmt_pct(m['win_rate'])}",
                f"- mean: {fmt_pct(m['mean'])}",
                f"- median: {fmt_pct(m['median'])}",
                f"- profit_factor: {fmt_num(m['pf'])}",
                "",
            ]
        )

    if not trades.empty:
        lines.append("## Portfolio (Net T+1)")
        eq_w = portfolio_stats(trades, "ret_t1", weighted=False)
        pos_w = portfolio_stats(trades, "ret_t1", weighted=True)
        lines.append(
            f"- equal-weight: total={fmt_pct(eq_w['total_ret'])}, mdd={fmt_pct(eq_w['mdd'])}, sharpe={fmt_num(eq_w['sharpe'])}"
        )
        lines.append(
            f"- A/B position-weight: total={fmt_pct(pos_w['total_ret'])}, mdd={fmt_pct(pos_w['mdd'])}, sharpe={fmt_num(pos_w['sharpe'])}"
        )

    if not trades.empty:
        lines.append("## Grade Breakdown (T+1)")
        for grade, sub in trades.groupby("signal_grade"):
            m = metric(sub["ret_t1"])
            lines.append(
                f"- Grade {grade}: n={m['n']}, win={fmt_pct(m['win_rate'])}, mean={fmt_pct(m['mean'])}, pf={fmt_num(m['pf'])}"
            )

    text = "\n".join(lines) + "\n"
    summary_latest.write_text(text, encoding="utf-8")
    summary_stamp.write_text(text, encoding="utf-8")

    print(text)
    print(trades_latest)
    print(summary_latest)


if __name__ == "__main__":
    main()
