from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pandas as pd


LIMIT_LIKE_PCT = 0.095
BURST_PCT = 0.05
DEFAULT_HORIZONS = [2, 3, 5]


def _norm_date(value: object) -> Optional[str]:
    if value is None:
        return None
    digits = "".join(ch for ch in str(value).strip() if ch.isdigit())
    if len(digits) < 8:
        return None
    return digits[:8]


def _fmt_pct(value: float) -> str:
    return f"{value * 100:.2f}%"


def _load_recommendations(
    conn: sqlite3.Connection,
    start_date: Optional[str],
    end_date: Optional[str],
    top_n_per_day: int,
) -> pd.DataFrame:
    sql = """
        SELECT symbol, name, recommendation_date, recommendation_score, strategy_type
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
    if top_n_per_day > 0:
        df = (
            df.sort_values(["rec_date", "recommendation_score", "symbol"], ascending=[True, False, True])
            .groupby("rec_date", group_keys=False)
            .head(top_n_per_day)
            .reset_index(drop=True)
        )
    return df


def _load_market_data(
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
    df = pd.read_sql(sql, conn, params=params)
    if df.empty:
        return {}

    for col in ("open", "high", "low", "close"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["open", "high", "low", "close"])

    price_map: Dict[Tuple[str, str], Dict[str, float]] = {}
    for row in df.to_dict("records"):
        price_map[(str(row["ts_code"]), str(row["trade_date"]))] = {
            "open": float(row["open"]),
            "high": float(row["high"]),
            "low": float(row["low"]),
            "close": float(row["close"]),
        }
    return price_map


def _build_analysis_frames(
    rec_df: pd.DataFrame,
    market_conn: sqlite3.Connection,
    horizons: List[int],
) -> Tuple[pd.DataFrame, pd.DataFrame, Dict[int, pd.DataFrame], Dict[str, object]]:
    trade_dates = [
        str(row[0]) for row in market_conn.execute("SELECT DISTINCT trade_date FROM stock_daily ORDER BY trade_date").fetchall()
    ]
    if not trade_dates:
        raise ValueError("stock_daily 中没有交易日数据")

    date_to_idx = {date: idx for idx, date in enumerate(trade_dates)}
    max_h = max(horizons)

    rec_df = rec_df[rec_df["rec_date"].isin(date_to_idx.keys())].copy()
    rec_df["rec_idx"] = rec_df["rec_date"].map(date_to_idx)
    rec_df = rec_df[rec_df["rec_idx"] + max_h < len(trade_dates)].copy()
    if rec_df.empty:
        raise ValueError("历史推荐名单没有足够未来交易日用于分析")

    rec_df["buy_date"] = rec_df["rec_idx"].map(lambda idx: trade_dates[int(idx) + 1])
    date_min = str(rec_df["buy_date"].min())
    date_max = str(trade_dates[int(rec_df["rec_idx"].max()) + max_h])

    price_map = _load_market_data(
        market_conn,
        symbols=sorted(rec_df["symbol"].dropna().unique().tolist()),
        date_min=date_min,
        date_max=date_max,
    )
    if not price_map:
        raise ValueError("无法从行情库读取对应价格数据")

    entry_rows: List[Dict[str, object]] = []
    horizon_rows: Dict[int, List[Dict[str, object]]] = {h: [] for h in horizons}

    for rec in rec_df.to_dict("records"):
        symbol = str(rec["symbol"])
        buy_date = str(rec["buy_date"])
        buy_bar = price_map.get((symbol, buy_date))
        if not buy_bar:
            continue
        buy_open = float(buy_bar["open"])
        if buy_open <= 0:
            continue

        entry_ret = float(buy_bar["close"]) / buy_open - 1.0
        entry_mfe = float(buy_bar["high"]) / buy_open - 1.0
        entry_mae = float(buy_bar["low"]) / buy_open - 1.0

        base_row = {
            "rec_date": str(rec["rec_date"]),
            "buy_date": buy_date,
            "symbol": symbol,
            "name": str(rec.get("name", "")),
            "recommendation_score": float(rec.get("recommendation_score", 0.0) or 0.0),
            "strategy_type": str(rec.get("strategy_type", "")),
        }
        entry_rows.append(
            {
                **base_row,
                "entry_ret": entry_ret,
                "entry_mfe": entry_mfe,
                "entry_mae": entry_mae,
            }
        )

        rec_idx = int(rec["rec_idx"])
        for horizon in horizons:
            sell_date = trade_dates[rec_idx + horizon]
            sell_bar = price_map.get((symbol, sell_date))
            if not sell_bar:
                continue
            sell_close = float(sell_bar["close"])
            if sell_close <= 0:
                continue

            highs: List[float] = []
            lows: List[float] = []
            for trade_date in trade_dates[rec_idx + 1 : rec_idx + horizon + 1]:
                bar = price_map.get((symbol, trade_date))
                if not bar:
                    continue
                highs.append(float(bar["high"]))
                lows.append(float(bar["low"]))
            if not highs or not lows:
                continue

            horizon_rows[horizon].append(
                {
                    **base_row,
                    "sell_date": sell_date,
                    "ret": sell_close / buy_open - 1.0,
                    "mfe": max(highs) / buy_open - 1.0,
                    "mae": min(lows) / buy_open - 1.0,
                }
            )

    entry_df = pd.DataFrame(entry_rows)
    horizon_df_map = {h: pd.DataFrame(rows) for h, rows in horizon_rows.items()}

    meta = {
        "trade_days": int(rec_df["rec_date"].nunique()),
        "recommendation_count": int(len(rec_df)),
        "date_range": [str(rec_df["rec_date"].min()), str(rec_df["rec_date"].max())],
        "top_n_per_day": int(rec_df.groupby("rec_date")["symbol"].count().max()),
        "date_min": date_min,
        "date_max": date_max,
    }
    return rec_df, entry_df, horizon_df_map, meta


def _summarize_entry(entry_df: pd.DataFrame) -> Tuple[Dict[str, float], pd.DataFrame]:
    if entry_df.empty:
        return {}, pd.DataFrame()

    daily = (
        entry_df.groupby("rec_date")
        .agg(
            sample=("symbol", "count"),
            avg_ret=("entry_ret", "mean"),
            avg_mfe=("entry_mfe", "mean"),
            avg_mae=("entry_mae", "mean"),
            positive_count=("entry_ret", lambda s: int((s > 0).sum())),
            burst_count=("entry_mfe", lambda s: int((s >= BURST_PCT).sum())),
            limit_like_count=("entry_mfe", lambda s: int((s >= LIMIT_LIKE_PCT).sum())),
        )
        .reset_index()
    )

    summary = {
        "sample_count": int(len(entry_df)),
        "trade_days": int(entry_df["rec_date"].nunique()),
        "mean_ret": float(entry_df["entry_ret"].mean()),
        "win_rate": float((entry_df["entry_ret"] > 0).mean()),
        "mean_mfe": float(entry_df["entry_mfe"].mean()),
        "mean_mae": float(entry_df["entry_mae"].mean()),
        "burst_rate": float((entry_df["entry_mfe"] >= BURST_PCT).mean()),
        "limit_like_rate": float((entry_df["entry_mfe"] >= LIMIT_LIKE_PCT).mean()),
        "avg_positive_count_per_day": float(daily["positive_count"].mean()),
        "avg_burst_count_per_day": float(daily["burst_count"].mean()),
        "avg_limit_like_count_per_day": float(daily["limit_like_count"].mean()),
        "days_with_limit_like": int((daily["limit_like_count"] >= 1).sum()),
        "days_with_2_limit_like": int((daily["limit_like_count"] >= 2).sum()),
    }
    return summary, daily


def _summarize_horizon(df: pd.DataFrame, horizon: int) -> Tuple[Dict[str, float], pd.DataFrame]:
    if df.empty:
        return {}, pd.DataFrame()

    work = df.copy()
    work["giveback"] = work["mfe"] - work["ret"]

    daily = (
        work.groupby("rec_date")
        .agg(
            sample=("symbol", "count"),
            avg_ret=("ret", "mean"),
            avg_mfe=("mfe", "mean"),
            avg_mae=("mae", "mean"),
            avg_giveback=("giveback", "mean"),
            positive_count=("ret", lambda s: int((s > 0).sum())),
            burst_count=("mfe", lambda s: int((s >= BURST_PCT).sum())),
            limit_like_count=("mfe", lambda s: int((s >= LIMIT_LIKE_PCT).sum())),
        )
        .reset_index()
    )

    summary = {
        "horizon": int(horizon),
        "sample_count": int(len(work)),
        "trade_days": int(work["rec_date"].nunique()),
        "mean_ret": float(work["ret"].mean()),
        "median_ret": float(work["ret"].median()),
        "win_rate": float((work["ret"] > 0).mean()),
        "mean_mfe": float(work["mfe"].mean()),
        "mean_mae": float(work["mae"].mean()),
        "mean_giveback": float(work["giveback"].mean()),
        "burst_rate": float((work["mfe"] >= BURST_PCT).mean()),
        "limit_like_rate": float((work["mfe"] >= LIMIT_LIKE_PCT).mean()),
        "avg_positive_count_per_day": float(daily["positive_count"].mean()),
        "avg_burst_count_per_day": float(daily["burst_count"].mean()),
        "avg_limit_like_count_per_day": float(daily["limit_like_count"].mean()),
        "days_with_2_limit_like": int((daily["limit_like_count"] >= 2).sum()),
        "days_with_3_limit_like": int((daily["limit_like_count"] >= 3).sum()),
    }
    return summary, daily


def _prepare_examples(
    entry_df: pd.DataFrame,
    entry_daily: pd.DataFrame,
    horizon_df_map: Dict[int, pd.DataFrame],
    horizon_daily_map: Dict[int, pd.DataFrame],
) -> List[Dict[str, object]]:
    examples: List[Dict[str, object]] = []
    chosen_dates: List[str] = []

    if not entry_daily.empty:
        top_entry = entry_daily.sort_values(
            ["limit_like_count", "avg_mfe", "avg_ret"], ascending=[False, False, False]
        ).head(1)
        if not top_entry.empty:
            chosen_dates.append(str(top_entry.iloc[0]["rec_date"]))

    h5_daily = horizon_daily_map.get(5, pd.DataFrame())
    if not h5_daily.empty:
        balanced = h5_daily[h5_daily["limit_like_count"] >= 3].sort_values(
            ["avg_ret", "limit_like_count", "avg_mfe"], ascending=[False, False, False]
        )
        if not balanced.empty:
            chosen_dates.append(str(balanced.iloc[0]["rec_date"]))

        giveback_pool = h5_daily[h5_daily["limit_like_count"] >= 5]
        if giveback_pool.empty:
            giveback_pool = h5_daily[h5_daily["limit_like_count"] >= 3]
        giveback = giveback_pool.sort_values(["avg_ret", "avg_giveback"], ascending=[True, False])
        if not giveback.empty:
            chosen_dates.append(str(giveback.iloc[0]["rec_date"]))

    dedup_dates: List[str] = []
    for rec_date in chosen_dates:
        if rec_date not in dedup_dates:
            dedup_dates.append(rec_date)

    h2_df = horizon_df_map.get(2, pd.DataFrame()).copy()
    h5_df = horizon_df_map.get(5, pd.DataFrame()).copy()
    if not h2_df.empty:
        h2_df = h2_df.rename(columns={"ret": "ret_h2", "mfe": "mfe_h2", "mae": "mae_h2"})
    if not h5_df.empty:
        h5_df = h5_df.rename(columns={"ret": "ret_h5", "mfe": "mfe_h5", "mae": "mae_h5"})
        h5_df["giveback_h5"] = h5_df["mfe_h5"] - h5_df["ret_h5"]

    for rec_date in dedup_dates:
        day_entry = entry_daily[entry_daily["rec_date"] == rec_date]
        day_h2 = horizon_daily_map.get(2, pd.DataFrame())
        day_h5 = horizon_daily_map.get(5, pd.DataFrame())
        day_h2 = day_h2[day_h2["rec_date"] == rec_date] if not day_h2.empty else pd.DataFrame()
        day_h5 = day_h5[day_h5["rec_date"] == rec_date] if not day_h5.empty else pd.DataFrame()

        stock_df = entry_df[entry_df["rec_date"] == rec_date].copy()
        if stock_df.empty:
            continue
        if not h2_df.empty:
            stock_df = stock_df.merge(
                h2_df[["rec_date", "symbol", "ret_h2", "mfe_h2", "mae_h2"]],
                on=["rec_date", "symbol"],
                how="left",
            )
        if not h5_df.empty:
            stock_df = stock_df.merge(
                h5_df[["rec_date", "symbol", "ret_h5", "mfe_h5", "mae_h5", "giveback_h5"]],
                on=["rec_date", "symbol"],
                how="left",
            )
        stock_df = stock_df.sort_values(
            ["mfe_h2", "entry_mfe", "recommendation_score"], ascending=[False, False, False]
        )

        examples.append(
            {
                "rec_date": rec_date,
                "entry_day_summary": day_entry.iloc[0].to_dict() if not day_entry.empty else {},
                "h2_summary": day_h2.iloc[0].to_dict() if not day_h2.empty else {},
                "h5_summary": day_h5.iloc[0].to_dict() if not day_h5.empty else {},
                "stocks": stock_df.head(8).to_dict("records"),
            }
        )
    return examples


def _build_report(
    meta: Dict[str, object],
    entry_summary: Dict[str, float],
    horizon_summaries: List[Dict[str, float]],
    entry_daily: pd.DataFrame,
    horizon_daily_map: Dict[int, pd.DataFrame],
    examples: List[Dict[str, object]],
) -> str:
    lines: List[str] = []
    lines.append("# 原策略爆发力与兑现能力专项报告")
    lines.append("")
    lines.append(f"- 生成时间: `{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}`")
    lines.append(f"- 历史推荐区间: `{meta['date_range'][0]}` ~ `{meta['date_range'][1]}`")
    lines.append(f"- 推荐交易日数: `{meta['trade_days']}`")
    lines.append(f"- 样本总数: `{meta['recommendation_count']}`")
    lines.append(f"- 每日取前N: `{meta['top_n_per_day']}`")
    lines.append("- 评估口径: `recommendation_date = T，按 T+1 开盘买入`")
    lines.append("- 说明: `history_recommendation.db 未记录 strategy_profile，本报告按“这批历史名单属于原策略”处理`")
    lines.append("")

    lines.append("## 1. 核心结论")
    lines.append("")
    lines.append(
        f"- 原策略的强项不是 `5日 close-to-close IC`，而是 `Top10 候选池的短线爆发力`。买入当日平均最大浮盈 `{_fmt_pct(entry_summary['mean_mfe'])}`，"
        f"买入后2日内平均最大浮盈 `{_fmt_pct(next(item['mean_mfe'] for item in horizon_summaries if item['horizon'] == 2))}`。"
    )
    lines.append(
        f"- 问题主要出在 `兑现能力`。持有到5日收盘时平均收益 `{_fmt_pct(next(item['mean_ret'] for item in horizon_summaries if item['horizon'] == 5))}`，"
        f"但5日内平均最大浮盈仍有 `{_fmt_pct(next(item['mean_mfe'] for item in horizon_summaries if item['horizon'] == 5))}`，平均回吐 `{_fmt_pct(next(item['mean_giveback'] for item in horizon_summaries if item['horizon'] == 5))}`。"
    )
    lines.append(
        f"- 这说明原策略更像 `会抓异动和冲板候选`，而不是 `靠长期持有自动兑现收益` 的策略。评价它时，应优先看 `Top10 爆发命中率`、`MFE` 和 `回吐率`。"
    )
    lines.append("")

    lines.append("## 2. 买入当日表现")
    lines.append("")
    lines.append(
        f"- 买入当日收盘平均收益: `{_fmt_pct(entry_summary['mean_ret'])}`，收红概率 `{entry_summary['win_rate'] * 100:.2f}%`。"
    )
    lines.append(
        f"- 买入当日平均最大浮盈(MFE): `{_fmt_pct(entry_summary['mean_mfe'])}`，平均最大浮亏(MAE): `{_fmt_pct(entry_summary['mean_mae'])}`。"
    )
    lines.append(
        f"- 买入当日 `>=5%` 冲高占比 `{entry_summary['burst_rate'] * 100:.2f}%`，`>=9.5%` 涨停级冲高占比 `{entry_summary['limit_like_rate'] * 100:.2f}%`。"
    )
    lines.append(
        f"- 按天看，平均每天约有 `{entry_summary['avg_burst_count_per_day']:.2f}` 只票盘中冲高 `>=5%`，"
        f"`{entry_summary['avg_limit_like_count_per_day']:.2f}` 只票达到 `>=9.5%`，`{entry_summary['days_with_limit_like']}/{entry_summary['trade_days']}` 天至少出现过 1 只涨停级冲高。"
    )
    lines.append("")

    lines.append("## 3. 持有窗口对比")
    lines.append("")
    lines.append("| 窗口 | 平均收益 | 胜率 | 平均MFE | 平均MAE | 平均回吐 | >=5%冲高占比 | >=9.5%冲高占比 | 平均每日涨停级个数 |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|")
    for item in horizon_summaries:
        lines.append(
            "| T+{h}收盘 | {ret} | {win:.2f}% | {mfe} | {mae} | {giveback} | {burst:.2f}% | {limit_like:.2f}% | {limit_like_day:.2f} |".format(
                h=item["horizon"],
                ret=_fmt_pct(item["mean_ret"]),
                win=item["win_rate"] * 100,
                mfe=_fmt_pct(item["mean_mfe"]),
                mae=_fmt_pct(item["mean_mae"]),
                giveback=_fmt_pct(item["mean_giveback"]),
                burst=item["burst_rate"] * 100,
                limit_like=item["limit_like_rate"] * 100,
                limit_like_day=item["avg_limit_like_count_per_day"],
            )
        )
    lines.append("")

    h2_summary = next(item for item in horizon_summaries if item["horizon"] == 2)
    h5_summary = next(item for item in horizon_summaries if item["horizon"] == 5)
    lines.append(
        f"- `T+2` 是目前最接近原策略爆发节奏的窗口: 平均收益 `{_fmt_pct(h2_summary['mean_ret'])}`，但2日内平均MFE 已有 `{_fmt_pct(h2_summary['mean_mfe'])}`。"
    )
    lines.append(
        f"- `T+5` 时爆发仍然很多，但兑现明显变差: `平均每日涨停级个数 {h5_summary['avg_limit_like_count_per_day']:.2f}`，"
        f"可平均收益已经滑到 `{_fmt_pct(h5_summary['mean_ret'])}`。"
    )
    lines.append("")

    if not horizon_daily_map[2].empty:
        top_h2_days = horizon_daily_map[2].sort_values(
            ["limit_like_count", "avg_ret", "avg_mfe"], ascending=[False, False, False]
        ).head(5)
        lines.append("## 4. 历史强势日期")
        lines.append("")
        lines.append("| 推荐日 | 样本数 | 2日内涨停级个数 | 2日平均收益 | 2日平均MFE | 2日收红个数 |")
        lines.append("|---|---:|---:|---:|---:|---:|")
        for row in top_h2_days.to_dict("records"):
            lines.append(
                f"| {row['rec_date']} | {int(row['sample'])} | {int(row['limit_like_count'])} | {_fmt_pct(float(row['avg_ret']))} | {_fmt_pct(float(row['avg_mfe']))} | {int(row['positive_count'])} |"
            )
        lines.append("")

    if examples:
        lines.append("## 5. 历史实例")
        lines.append("")
        for example in examples:
            rec_date = example["rec_date"]
            entry_day_summary = example.get("entry_day_summary", {})
            h2_summary = example.get("h2_summary", {})
            h5_summary = example.get("h5_summary", {})
            lines.append(f"### {rec_date}")
            lines.append("")
            if entry_day_summary:
                lines.append(
                    f"- 买入当日: 平均收益 `{_fmt_pct(float(entry_day_summary['avg_ret']))}`，"
                    f"平均MFE `{_fmt_pct(float(entry_day_summary['avg_mfe']))}`，"
                    f"涨停级冲高 `{int(entry_day_summary['limit_like_count'])}` 只。"
                )
            if h2_summary:
                lines.append(
                    f"- 2日窗口: 平均收益 `{_fmt_pct(float(h2_summary['avg_ret']))}`，"
                    f"平均MFE `{_fmt_pct(float(h2_summary['avg_mfe']))}`，"
                    f"涨停级冲高 `{int(h2_summary['limit_like_count'])}` 只。"
                )
            if h5_summary:
                lines.append(
                    f"- 5日窗口: 平均收益 `{_fmt_pct(float(h5_summary['avg_ret']))}`，"
                    f"平均MFE `{_fmt_pct(float(h5_summary['avg_mfe']))}`，"
                    f"平均回吐 `{_fmt_pct(float(h5_summary['avg_giveback']))}`。"
                )
            lines.append("")
            lines.append("| 股票 | 评分 | 当日收盘 | 当日MFE | 2日MFE | 5日收盘 | 5日回吐 |")
            lines.append("|---|---:|---:|---:|---:|---:|---:|")
            for stock in example.get("stocks", []):
                lines.append(
                    f"| {stock['symbol']} {stock['name']} | {float(stock['recommendation_score']):.1f} | "
                    f"{_fmt_pct(float(stock.get('entry_ret', 0.0)))} | {_fmt_pct(float(stock.get('entry_mfe', 0.0)))} | "
                    f"{_fmt_pct(float(stock.get('mfe_h2', 0.0) or 0.0))} | {_fmt_pct(float(stock.get('ret_h5', 0.0) or 0.0))} | "
                    f"{_fmt_pct(float(stock.get('giveback_h5', 0.0) or 0.0))} |"
                )
            lines.append("")

    lines.append("## 6. 判断")
    lines.append("")
    lines.append("- 原策略不是“不会选股”，而是“会选出会冲的票，但当前评价与兑现口径没有对上”。")
    lines.append("- 如果继续优化原策略，重点不该先放在删掉全部因子，而要放在三件事：")
    lines.append("  1. 重新定义评估指标，优先看 Top10 爆发命中率、2日内 MFE、冲板率。")
    lines.append("  2. 强化卖点/止盈模块，减少从高 MFE 到低收盘收益的回吐。")
    lines.append("  3. 识别“会冲但留不住”的票型特征，把它们从持有策略中单独分流。")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="分析原策略历史推荐名单的爆发力与兑现能力")
    parser.add_argument("--rec-db", default="data/history_recommendation.db")
    parser.add_argument("--market-db", default="data/database/quant_system.db")
    parser.add_argument("--start-date", default=None)
    parser.add_argument("--end-date", default=None)
    parser.add_argument("--top-n", type=int, default=10)
    parser.add_argument("--horizons", default="2,3,5")
    parser.add_argument("--output-dir", default="reports")
    args = parser.parse_args()

    horizons = sorted({max(1, int(x.strip())) for x in args.horizons.split(",") if x.strip()})
    if not horizons:
        horizons = DEFAULT_HORIZONS

    rec_db = Path(args.rec_db)
    market_db = Path(args.market_db)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    rec_conn = sqlite3.connect(str(rec_db))
    market_conn = sqlite3.connect(str(market_db))
    try:
        rec_df = _load_recommendations(
            conn=rec_conn,
            start_date=args.start_date,
            end_date=args.end_date,
            top_n_per_day=args.top_n,
        )
        if rec_df.empty:
            raise ValueError("recommendations 表中没有可用历史推荐名单")

        _, entry_df, horizon_df_map, meta = _build_analysis_frames(
            rec_df=rec_df,
            market_conn=market_conn,
            horizons=horizons,
        )
        entry_summary, entry_daily = _summarize_entry(entry_df)
        horizon_summaries: List[Dict[str, float]] = []
        horizon_daily_map: Dict[int, pd.DataFrame] = {}
        for horizon in horizons:
            summary, daily = _summarize_horizon(horizon_df_map[horizon], horizon=horizon)
            horizon_summaries.append(summary)
            horizon_daily_map[horizon] = daily

        examples = _prepare_examples(
            entry_df=entry_df,
            entry_daily=entry_daily,
            horizon_df_map=horizon_df_map,
            horizon_daily_map=horizon_daily_map,
        )

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_path = output_dir / f"legacy_burst_realization_{timestamp}.md"
        json_path = output_dir / f"legacy_burst_realization_{timestamp}.json"
        entry_daily_path = output_dir / f"legacy_burst_entry_daily_{timestamp}.csv"
        horizon_daily_paths = {
            h: output_dir / f"legacy_burst_h{h}_daily_{timestamp}.csv" for h in horizons
        }
        example_path = output_dir / f"legacy_burst_examples_{timestamp}.csv"

        report_text = _build_report(
            meta=meta,
            entry_summary=entry_summary,
            horizon_summaries=horizon_summaries,
            entry_daily=entry_daily,
            horizon_daily_map=horizon_daily_map,
            examples=examples,
        )
        report_path.write_text(report_text, encoding="utf-8")
        entry_daily.to_csv(entry_daily_path, index=False, encoding="utf-8-sig")
        for horizon, daily_df in horizon_daily_map.items():
            daily_df.to_csv(horizon_daily_paths[horizon], index=False, encoding="utf-8-sig")

        example_rows: List[Dict[str, object]] = []
        for example in examples:
            for stock in example.get("stocks", []):
                example_rows.append(
                    {
                        "rec_date": example["rec_date"],
                        "symbol": stock["symbol"],
                        "name": stock["name"],
                        "recommendation_score": stock["recommendation_score"],
                        "entry_ret": stock.get("entry_ret"),
                        "entry_mfe": stock.get("entry_mfe"),
                        "mfe_h2": stock.get("mfe_h2"),
                        "ret_h5": stock.get("ret_h5"),
                        "giveback_h5": stock.get("giveback_h5"),
                    }
                )
        pd.DataFrame(example_rows).to_csv(example_path, index=False, encoding="utf-8-sig")

        json_payload = {
            "meta": meta,
            "entry_summary": entry_summary,
            "horizon_summaries": horizon_summaries,
            "example_dates": examples,
            "files": {
                "report": str(report_path),
                "json": str(json_path),
                "entry_daily_csv": str(entry_daily_path),
                "example_csv": str(example_path),
                "horizon_daily_csv": {str(h): str(path) for h, path in horizon_daily_paths.items()},
            },
        }
        json_path.write_text(json.dumps(json_payload, ensure_ascii=False, indent=2), encoding="utf-8")

        print(f"report={report_path}")
        print(f"json={json_path}")
        print(f"entry_daily_csv={entry_daily_path}")
        print(f"example_csv={example_path}")
        for horizon, path in horizon_daily_paths.items():
            print(f"h{horizon}_daily_csv={path}")
        return 0
    finally:
        rec_conn.close()
        market_conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
