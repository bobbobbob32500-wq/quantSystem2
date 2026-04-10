# -*- coding: utf-8 -*-
"""
基于历史推荐名单的轻量回测：

口径：
1. T日推荐；
2. T+1 开盘买入；
3. 分别在 T+2 / T+3 / T+4 / T+5 收盘卖出；
4. 统计收益率、期间最大涨幅（MFE）、最大跌幅（MAE）。
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pandas as pd


@dataclass
class HorizonSummary:
    horizon: int
    sample_count: int
    trade_days: int
    mean_return: float
    median_return: float
    win_rate: float
    p25_return: float
    p75_return: float
    mean_mfe: float
    mean_mae: float
    day_mean_return: float
    day_win_rate: float

    def to_dict(self) -> Dict:
        return {
            "horizon": int(self.horizon),
            "sample_count": int(self.sample_count),
            "trade_days": int(self.trade_days),
            "mean_return": float(self.mean_return),
            "median_return": float(self.median_return),
            "win_rate": float(self.win_rate),
            "p25_return": float(self.p25_return),
            "p75_return": float(self.p75_return),
            "mean_mfe": float(self.mean_mfe),
            "mean_mae": float(self.mean_mae),
            "day_mean_return": float(self.day_mean_return),
            "day_win_rate": float(self.day_win_rate),
        }


def _norm_date(value: object) -> Optional[str]:
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    digits = "".join(ch for ch in s if ch.isdigit())
    if len(digits) < 8:
        return None
    return digits[:8]


def _mean(series: pd.Series) -> float:
    if series.empty:
        return 0.0
    return float(series.mean())


def _quantile(series: pd.Series, q: float) -> float:
    if series.empty:
        return 0.0
    return float(series.quantile(q))


def _load_recommendations(
    conn: sqlite3.Connection,
    start_date: Optional[str],
    end_date: Optional[str],
    top_n_per_day: int,
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
    if df.empty:
        return df

    if top_n_per_day > 0:
        df = (
            df.sort_values(["rec_date", "recommendation_score", "symbol"], ascending=[True, False, True])
            .groupby("rec_date", as_index=False, group_keys=False)
            .head(top_n_per_day)
            .reset_index(drop=True)
        )
    return df


def _load_market_data(
    conn: sqlite3.Connection,
    symbols: List[str],
    date_min: str,
    date_max: str,
) -> pd.DataFrame:
    if not symbols:
        return pd.DataFrame()

    placeholders = ",".join(["?"] * len(symbols))
    sql = f"""
        SELECT ts_code, trade_date, open, high, low, close
        FROM stock_daily
        WHERE ts_code IN ({placeholders})
          AND trade_date >= ?
          AND trade_date <= ?
    """
    params = list(symbols) + [date_min, date_max]
    raw = pd.read_sql(sql, conn, params=params)
    if raw.empty:
        return raw

    for col in ("open", "high", "low", "close"):
        raw[col] = pd.to_numeric(raw[col], errors="coerce")
    raw = raw.dropna(subset=["open", "high", "low", "close"])
    return raw


def _summarize(df: pd.DataFrame, horizon: int) -> HorizonSummary:
    ret = df["ret"]
    mfe = df["mfe"]
    mae = df["mae"]

    daily = df.groupby("rec_date", as_index=False)["ret"].mean()
    day_ret = daily["ret"]

    return HorizonSummary(
        horizon=horizon,
        sample_count=int(len(df)),
        trade_days=int(df["rec_date"].nunique()),
        mean_return=_mean(ret),
        median_return=_quantile(ret, 0.5),
        win_rate=float((ret > 0).mean()) if not ret.empty else 0.0,
        p25_return=_quantile(ret, 0.25),
        p75_return=_quantile(ret, 0.75),
        mean_mfe=_mean(mfe),
        mean_mae=_mean(mae),
        day_mean_return=_mean(day_ret),
        day_win_rate=float((day_ret > 0).mean()) if not day_ret.empty else 0.0,
    )


def run_backtest(
    recommendation_db: Path,
    market_db: Path,
    start_date: Optional[str],
    end_date: Optional[str],
    top_n_per_day: int,
    horizons: List[int],
) -> Tuple[pd.DataFrame, List[HorizonSummary], Dict]:
    rec_conn = sqlite3.connect(str(recommendation_db))
    mkt_conn = sqlite3.connect(str(market_db))

    try:
        rec_df = _load_recommendations(
            rec_conn,
            start_date=start_date,
            end_date=end_date,
            top_n_per_day=top_n_per_day,
        )
        if rec_df.empty:
            return pd.DataFrame(), [], {"error": "no_recommendations"}

        trade_dates = [
            str(r[0]) for r in mkt_conn.execute("SELECT DISTINCT trade_date FROM stock_daily ORDER BY trade_date").fetchall()
        ]
        if len(trade_dates) < 10:
            return pd.DataFrame(), [], {"error": "insufficient_trade_calendar"}

        date_to_idx = {d: i for i, d in enumerate(trade_dates)}
        max_h = max(horizons)

        valid_rec = rec_df[rec_df["rec_date"].isin(date_to_idx.keys())].copy()
        if valid_rec.empty:
            return pd.DataFrame(), [], {"error": "no_rec_date_in_trade_calendar"}

        valid_rec["rec_idx"] = valid_rec["rec_date"].map(date_to_idx)
        valid_rec = valid_rec[valid_rec["rec_idx"] + max_h < len(trade_dates)].copy()
        if valid_rec.empty:
            return pd.DataFrame(), [], {"error": "no_records_with_enough_future_days"}

        min_buy_idx = int(valid_rec["rec_idx"].min() + 1)
        max_sell_idx = int(valid_rec["rec_idx"].max() + max_h)
        date_min = trade_dates[min_buy_idx]
        date_max = trade_dates[max_sell_idx]

        symbols = sorted(valid_rec["symbol"].dropna().unique().tolist())
        price_df = _load_market_data(mkt_conn, symbols=symbols, date_min=date_min, date_max=date_max)
        if price_df.empty:
            return pd.DataFrame(), [], {"error": "no_market_prices"}

        price_map: Dict[Tuple[str, str], Dict[str, float]] = {}
        for row in price_df.to_dict("records"):
            key = (str(row["ts_code"]), str(row["trade_date"]))
            price_map[key] = {
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
            }

        details: List[Dict] = []
        for rec in valid_rec.to_dict("records"):
            symbol = str(rec["symbol"])
            rec_date = str(rec["rec_date"])
            rec_idx = int(rec["rec_idx"])
            buy_date = trade_dates[rec_idx + 1]
            buy_row = price_map.get((symbol, buy_date))
            if not buy_row:
                continue
            buy_open = float(buy_row["open"])
            if buy_open <= 0:
                continue

            for h in horizons:
                sell_date = trade_dates[rec_idx + h]
                sell_row = price_map.get((symbol, sell_date))
                if not sell_row:
                    continue
                sell_close = float(sell_row["close"])
                if sell_close <= 0:
                    continue

                period_dates = trade_dates[rec_idx + 1 : rec_idx + h + 1]
                highs: List[float] = []
                lows: List[float] = []
                for d in period_dates:
                    bar = price_map.get((symbol, d))
                    if not bar:
                        continue
                    highs.append(float(bar["high"]))
                    lows.append(float(bar["low"]))
                if not highs or not lows:
                    continue

                details.append(
                    {
                        "symbol": symbol,
                        "name": rec.get("name", ""),
                        "rec_date": rec_date,
                        "buy_date": buy_date,
                        "sell_date": sell_date,
                        "horizon": int(h),
                        "buy_open": buy_open,
                        "sell_close": sell_close,
                        "ret": sell_close / buy_open - 1.0,
                        "mfe": max(highs) / buy_open - 1.0,
                        "mae": min(lows) / buy_open - 1.0,
                        "recommendation_score": float(rec.get("recommendation_score", 0.0) or 0.0),
                    }
                )

        detail_df = pd.DataFrame(details)
        if detail_df.empty:
            return detail_df, [], {"error": "no_valid_trade_records"}

        summaries: List[HorizonSummary] = []
        for h in horizons:
            sub = detail_df[detail_df["horizon"] == h]
            if sub.empty:
                continue
            summaries.append(_summarize(sub, horizon=h))

        meta = {
            "recommendation_db": recommendation_db.as_posix(),
            "market_db": market_db.as_posix(),
            "start_date": start_date,
            "end_date": end_date,
            "top_n_per_day": top_n_per_day,
            "horizons": horizons,
            "recommendation_records": int(len(rec_df)),
            "valid_recommendation_records": int(len(valid_rec)),
            "detail_records": int(len(detail_df)),
            "date_range_rec": [
                str(valid_rec["rec_date"].min()),
                str(valid_rec["rec_date"].max()),
            ],
        }
        return detail_df, summaries, meta
    finally:
        rec_conn.close()
        mkt_conn.close()


def _build_markdown(meta: Dict, summaries: List[HorizonSummary]) -> str:
    lines: List[str] = []
    lines.append("# 历史推荐回测报告（T+1开盘买）")
    lines.append("")
    lines.append(f"- 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"- 推荐库: `{meta.get('recommendation_db')}`")
    lines.append(f"- 行情库: `{meta.get('market_db')}`")
    lines.append(f"- 推荐日期范围: `{meta.get('date_range_rec', ['-', '-'])[0]}` ~ `{meta.get('date_range_rec', ['-', '-'])[1]}`")
    lines.append(f"- 每日取前N: `{meta.get('top_n_per_day')}`")
    lines.append("")
    lines.append("## 统计汇总")
    lines.append("")
    lines.append("| 持有到 | 样本数 | 交易日数 | 平均涨幅 | 中位涨幅 | 胜率 | 25%分位 | 75%分位 | 平均最大涨幅(MFE) | 平均最大跌幅(MAE) | 日均收益(等权) | 日胜率 |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for s in summaries:
        lines.append(
            f"| T+{s.horizon} | {s.sample_count} | {s.trade_days} | "
            f"{s.mean_return:.2%} | {s.median_return:.2%} | {s.win_rate:.2%} | "
            f"{s.p25_return:.2%} | {s.p75_return:.2%} | {s.mean_mfe:.2%} | {s.mean_mae:.2%} | "
            f"{s.day_mean_return:.2%} | {s.day_win_rate:.2%} |"
        )
    lines.append("")
    lines.append("说明：MFE/MAE基于持有区间（日线高低价）相对买入价的浮动。")
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Backtest historical recommendations with T+1 open entry and T+2..T+5 exits."
    )
    parser.add_argument("--rec-db", default="data/history_recommendation.db")
    parser.add_argument("--market-db", default="data/database/quant_system.db")
    parser.add_argument("--start-date", default=None, help="YYYY-MM-DD or YYYYMMDD")
    parser.add_argument("--end-date", default=None, help="YYYY-MM-DD or YYYYMMDD")
    parser.add_argument("--top-n-per-day", type=int, default=10, help="0 means keep all records per day")
    parser.add_argument("--horizons", default="2,3,4,5", help="comma-separated horizons (relative to T day)")
    parser.add_argument("--out-dir", default="reports")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    rec_db = Path(args.rec_db)
    market_db = Path(args.market_db)
    start_date = _norm_date(args.start_date) if args.start_date else None
    end_date = _norm_date(args.end_date) if args.end_date else None
    horizons = [int(x.strip()) for x in str(args.horizons).split(",") if x.strip()]
    horizons = sorted(set([h for h in horizons if h >= 2]))
    if not horizons:
        raise SystemExit("No valid horizons")

    detail_df, summaries, meta = run_backtest(
        recommendation_db=rec_db,
        market_db=market_db,
        start_date=start_date,
        end_date=end_date,
        top_n_per_day=int(args.top_n_per_day),
        horizons=horizons,
    )

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    md_path = out_dir / f"legacy_recommendation_backtest_{ts}.md"
    json_path = out_dir / f"legacy_recommendation_backtest_{ts}.json"
    csv_path = out_dir / f"legacy_recommendation_backtest_details_{ts}.csv"

    payload = {
        "meta": meta,
        "summaries": [s.to_dict() for s in summaries],
    }
    if not detail_df.empty:
        detail_df.to_csv(csv_path, index=False, encoding="utf-8-sig")
        payload["detail_csv"] = csv_path.as_posix()

    md_text = _build_markdown(meta, summaries) if summaries else "# 回测报告\n\n无有效样本。"
    md_path.write_text(md_text, encoding="utf-8")
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print("markdown:", md_path.as_posix())
    print("json:", json_path.as_posix())
    if not detail_df.empty:
        print("details:", csv_path.as_posix())
    if summaries:
        for s in summaries:
            print(
                f"T+{s.horizon} | samples={s.sample_count} | mean={s.mean_return:.2%} | "
                f"win={s.win_rate:.2%} | mfe={s.mean_mfe:.2%} | mae={s.mean_mae:.2%}"
            )
    else:
        print("no valid summary records")


if __name__ == "__main__":
    main()

