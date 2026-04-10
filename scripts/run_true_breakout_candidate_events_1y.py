from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(r"D:\HuaweiAI\quantSystem2")
DB_PATH = ROOT / "data/database/quant_system.db"
OUT_DIR = ROOT / "data/research/strong_start_full/v4_scan"

OUT_EVENTS = OUT_DIR / "true_breakout_candidate_events_1y.parquet"
OUT_SUMMARY = OUT_DIR / "true_breakout_candidate_events_1y_summary.json"
OUT_DAILY = OUT_DIR / "true_breakout_candidate_events_1y_daily_stats.csv"
OUT_MONTHLY = OUT_DIR / "true_breakout_candidate_events_1y_monthly_stats.csv"
OUT_REPORT = OUT_DIR / "true_breakout_candidate_events_1y_report.md"
OUT_INTERVAL = OUT_DIR / "true_breakout_candidate_events_1y_interval_audit.csv"
MIN_AMOUNT = 1e5


def _is_main_board(ts: str) -> bool:
    if not isinstance(ts, str) or "." not in ts:
        return False
    code, exch = ts.split(".")
    if exch == "SH":
        return code.startswith(("600", "601", "603", "605"))
    if exch == "SZ":
        return code.startswith(("000", "001", "002", "003"))
    return False


def _is_risk_name(name: str) -> bool:
    if not isinstance(name, str):
        return False
    s = name.upper().strip()
    return s.startswith("*ST") or s.startswith("ST") or s.startswith("S*ST") or s.startswith("SST")


def _load_data() -> pd.DataFrame:
    conn = sqlite3.connect(DB_PATH)
    try:
        daily = pd.read_sql_query(
            "select ts_code, trade_date, open, close, high, low, vol, amount, pct_chg from stock_daily",
            conn,
        )
        basic = pd.read_sql_query(
            "select ts_code, name, industry, list_date from stock_basic",
            conn,
        )
    finally:
        conn.close()

    df = daily.merge(basic, on="ts_code", how="left")
    df["trade_date"] = df["trade_date"].astype(str)
    df["list_date"] = df["list_date"].astype(str)
    for c in ["open", "close", "high", "low", "vol", "amount", "pct_chg"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


def _prepare_1y_universe(df: pd.DataFrame) -> tuple[pd.DataFrame, str, str]:
    max_t = pd.to_datetime(df["trade_date"].max(), format="%Y%m%d")
    start_t = max_t - pd.Timedelta(days=365)

    x = df[
        (pd.to_datetime(df["trade_date"], format="%Y%m%d") >= start_t)
        & (pd.to_datetime(df["trade_date"], format="%Y%m%d") <= max_t)
    ].copy()

    # universe boundaries
    x = x[x["ts_code"].map(_is_main_board)].copy()
    x = x[~x["name"].map(_is_risk_name)].copy()
    x["list_days"] = (
        pd.to_datetime(x["trade_date"], format="%Y%m%d")
        - pd.to_datetime(x["list_date"], format="%Y%m%d", errors="coerce")
    ).dt.days
    x = x[x["list_days"] >= 180].copy()  # approx >=120 trading days
    x = x[x["amount"] >= MIN_AMOUNT].copy()  # minimum liquidity (DB amount scale)

    return x, start_t.strftime("%Y%m%d"), max_t.strftime("%Y%m%d")


def _build_candidate_signals(df: pd.DataFrame) -> pd.DataFrame:
    x = df.sort_values(["ts_code", "trade_date"]).copy()
    g = x.groupby("ts_code", group_keys=False)

    # trend/strength
    x["ma20"] = g["close"].transform(lambda s: s.rolling(20, min_periods=20).mean())
    x["ma60"] = g["close"].transform(lambda s: s.rolling(60, min_periods=60).mean())
    x["ma20_slope5"] = x["ma20"] / g["ma20"].shift(5) - 1
    x["ret20"] = x["close"] / g["close"].shift(20) - 1
    x["ret20_q"] = x.groupby("trade_date")["ret20"].rank(method="average", pct=True)

    # price structure
    x["hh20_prev"] = g["high"].transform(lambda s: s.rolling(20, min_periods=20).max().shift(1))
    x["hh10_prev"] = g["high"].transform(lambda s: s.rolling(10, min_periods=10).max().shift(1))
    x["ll20_prev"] = g["low"].transform(lambda s: s.rolling(20, min_periods=20).min().shift(1))
    x["range20"] = (x["hh20_prev"] - x["ll20_prev"]) / x["close"].replace(0, np.nan)
    x["range10_prev"] = g["high"].transform(lambda s: s.rolling(10, min_periods=10).max().shift(1)) - g["low"].transform(
        lambda s: s.rolling(10, min_periods=10).min().shift(1)
    )
    x["range20_prev"] = x["hh20_prev"] - x["ll20_prev"]
    x["compress_ratio"] = x["range10_prev"] / x["range20_prev"].replace(0, np.nan)

    # volume
    x["vol20"] = g["vol"].transform(lambda s: s.rolling(20, min_periods=20).mean())
    x["vol60"] = g["vol"].transform(lambda s: s.rolling(60, min_periods=60).mean())
    x["vol_ratio20"] = x["vol"] / x["vol20"].replace(0, np.nan)
    x["vol20_vol60"] = x["vol20"] / x["vol60"].replace(0, np.nan)

    # four loose trigger classes
    x["trend_flag"] = (
        ((x["close"] > x["ma20"]) & (x["ma20_slope5"] >= 0))
        | (x["ret20_q"] >= 0.65)
    )
    x["price_flag"] = (
        (x["close"] >= x["hh20_prev"] * 0.995)
        | ((x["pct_chg"] >= 3.0) & (x["close"] >= x["hh10_prev"]))
    )
    x["volume_flag"] = (
        (x["vol_ratio20"] >= 1.20)
        | ((x["pct_chg"] > 0) & (x["vol_ratio20"] >= 1.05) & (x["vol20_vol60"] <= 0.90))
    )
    x["structure_flag"] = (
        (x["range20"] <= 0.20)
        | (x["compress_ratio"] <= 0.85)
    )

    flags = ["trend_flag", "price_flag", "volume_flag", "structure_flag"]
    x["candidate_trigger_count"] = x[flags].sum(axis=1)
    x["raw_candidate"] = (x["candidate_trigger_count"] >= 2) & (x["close"] > x["ma20"])
    x["candidate_trigger_types"] = x.apply(
        lambda r: "|".join(
            [k.replace("_flag", "") for k in flags if bool(r[k])]
        ),
        axis=1,
    )

    return x


def _cooldown_dedup(df: pd.DataFrame, cooldown_bars: int = 12) -> pd.DataFrame:
    rows = []
    for ts, g in df.groupby("ts_code", sort=False):
        g = g.sort_values("trade_date").copy()
        g["bar_idx"] = np.arange(len(g))
        cands = g[g["raw_candidate"]].copy()
        last_keep_bar = None
        cooling_group = 0
        for idx, r in cands.iterrows():
            keep = False
            mode = "cooldown_pass"
            if last_keep_bar is None:
                keep = True
            else:
                gap = int(r["bar_idx"] - last_keep_bar)
                if gap > cooldown_bars:
                    keep = True
                else:
                    # secondary restart release: re-platform + re-strength
                    secondary_restart = (
                        (gap >= 5)
                        and (pd.notna(r["range20"]) and r["range20"] <= 0.12)
                        and (pd.notna(r["vol_ratio20"]) and r["vol_ratio20"] >= 1.10)
                        and (pd.notna(r["hh20_prev"]) and r["close"] >= r["hh20_prev"] * 0.995)
                    )
                    if secondary_restart:
                        keep = True
                        mode = "secondary_restart_release"
            if keep:
                cooling_group += 1
                last_keep_bar = int(r["bar_idx"])
                out = r.to_dict()
                out["event_cooling_group"] = cooling_group
                out["cooling_mode"] = mode
                rows.append(out)
    return pd.DataFrame(rows)


def main() -> None:
    raw = _load_data()
    base, start_s, end_s = _prepare_1y_universe(raw)
    sig = _build_candidate_signals(base)
    events = _cooldown_dedup(sig, cooldown_bars=12)

    # output table fields
    keep_cols = [
        "ts_code",
        "trade_date",
        "name",
        "industry",
        "event_cooling_group",
        "cooling_mode",
        "candidate_trigger_count",
        "candidate_trigger_types",
        "list_days",
        "amount",
        "pct_chg",
        "close",
        "vol",
        "ret20_q",
        "vol_ratio20",
        "range20",
        "compress_ratio",
        "trend_flag",
        "price_flag",
        "volume_flag",
        "structure_flag",
    ]
    if len(events) == 0:
        events = pd.DataFrame(columns=keep_cols)
    else:
        events = events[keep_cols].copy()
    events["candidate_event_id"] = (
        events["ts_code"].astype(str) + "_" + events["trade_date"].astype(str)
    )
    events = events.sort_values(["trade_date", "ts_code"]).reset_index(drop=True)
    events.to_parquet(OUT_EVENTS, index=False)

    # profiles
    daily = (
        events.groupby("trade_date")
        .agg(event_count=("ts_code", "size"), stock_count=("ts_code", "nunique"))
        .reset_index()
    )
    daily.to_csv(OUT_DAILY, index=False, encoding="utf-8-sig")

    monthly = (
        events.assign(month=pd.to_datetime(events["trade_date"], format="%Y%m%d").dt.strftime("%Y-%m"))
        .groupby("month")
        .agg(event_count=("ts_code", "size"), stock_count=("ts_code", "nunique"))
        .reset_index()
    )
    monthly.to_csv(OUT_MONTHLY, index=False, encoding="utf-8-sig")

    # interval audit
    interval_rows = []
    for ts, g in events.sort_values(["ts_code", "trade_date"]).groupby("ts_code"):
        d = pd.to_datetime(g["trade_date"], format="%Y%m%d")
        diffs = d.diff().dt.days.dropna()
        for v in diffs:
            interval_rows.append({"ts_code": ts, "event_interval_days": int(v)})
    interval = pd.DataFrame(interval_rows)
    if len(interval) == 0:
        interval = pd.DataFrame(columns=["ts_code", "event_interval_days"])
    interval.to_csv(OUT_INTERVAL, index=False, encoding="utf-8-sig")

    # summary
    industry_top = (
        events.groupby("industry").size().sort_values(ascending=False).head(20).to_dict()
        if "industry" in events.columns
        else {}
    )
    summary = {
        "time_range": {"start": start_s, "end": end_s},
        "universe_boundaries": {
            "main_board_only": True,
            "min_list_days": 180,
            "min_amount": MIN_AMOUNT,
            "st_excluded": True,
        },
        "candidate_rule": {
            "classes": ["trend", "price", "volume", "structure"],
            "in_pool_logic": "candidate_trigger_count >= 2 and close > ma20",
            "cooldown_bars": 12,
            "secondary_restart_release": True,
        },
        "pool_profile": {
            "candidate_event_count": int(len(events)),
            "covered_stock_count": int(events["ts_code"].nunique()),
            "daily_event_count_mean": float(daily["event_count"].mean()) if len(daily) else 0.0,
            "daily_event_count_median": float(daily["event_count"].median()) if len(daily) else 0.0,
            "daily_event_count_p90": float(daily["event_count"].quantile(0.9)) if len(daily) else 0.0,
            "monthly_rows": int(len(monthly)),
            "top_industries": industry_top,
        },
        "repeat_risk_hint": {
            "same_stock_multi_event_count": int((events.groupby("ts_code").size() > 1).sum()),
            "interval_median_days": float(interval["event_interval_days"].median()) if len(interval) else None,
            "interval_p25_days": float(interval["event_interval_days"].quantile(0.25)) if len(interval) else None,
        },
        "ready_for_labeling": True,
    }
    OUT_SUMMARY.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    report = [
        "# true_breakout_candidate_events_1y_report",
        "",
        f"- time range: {start_s} ~ {end_s}",
        "- universe: main-board + list_days>=180 + amount>=1e8 + non-ST",
        "- candidate logic: 4-class loose scan; in-pool when >=2 classes and close>MA20",
        "- dedup: same-stock cooldown 12 bars, with secondary restart release",
        "",
        "## pool profile",
        f"- candidate events: {len(events)}",
        f"- covered stocks: {events['ts_code'].nunique()}",
        f"- daily mean events: {daily['event_count'].mean():.2f}" if len(daily) else "- daily mean events: 0",
        f"- daily median events: {daily['event_count'].median():.2f}" if len(daily) else "- daily median events: 0",
        f"- daily p90 events: {daily['event_count'].quantile(0.9):.2f}" if len(daily) else "- daily p90 events: 0",
        "",
        "## repeat risk",
        f"- stocks with >1 event: {(events.groupby('ts_code').size() > 1).sum()}",
        f"- event interval median days: {interval['event_interval_days'].median():.1f}" if len(interval) else "- event interval median days: n/a",
        "",
        "## judgement",
        "- candidate pool is intentionally wide for next-step labeling and true/false startup split.",
        "- next stage can proceed: true/false startup labeling.",
    ]
    OUT_REPORT.write_text("\n".join(report), encoding="utf-8")

    print("Generated:")
    print(" -", OUT_EVENTS)
    print(" -", OUT_SUMMARY)
    print(" -", OUT_DAILY)
    print(" -", OUT_MONTHLY)
    print(" -", OUT_REPORT)
    print(" -", OUT_INTERVAL)


if __name__ == "__main__":
    main()
