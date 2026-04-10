# -*- coding: utf-8 -*-
"""
IC analysis for legacy_opt using historical recommendation records.

Method:
1. Load historical recommendation list from history_recommendation.db.
2. Recalculate legacy-opt 5-factor scores on each recommendation date.
3. Attach T+1 open -> T+h close forward returns.
4. Compute pooled / daily IC and simple top-bottom spread diagnostics.

This analysis reflects the recommended pool, not the full stock universe.
"""

from __future__ import annotations

import argparse
import json
import math
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional

import pandas as pd
from scipy.stats import spearmanr

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.core.config import ConfigManager
from src.core.database import DatabaseManager
from src.modules.stock_selector import StockSelector


LEGACY_OPT_FACTORS = [
    "trend_score",
    "momentum_score",
    "volume_score",
    "fundamental_score",
    "pullback_score",
    "total_score",
]


def _norm_date(value: object) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    digits = "".join(ch for ch in text if ch.isdigit())
    if len(digits) < 8:
        return None
    return digits[:8]


def _mean(series: pd.Series) -> float:
    if series.empty:
        return 0.0
    return float(series.mean())


def _safe_spearman(x: pd.Series, y: pd.Series, min_samples: int) -> float:
    pair = pd.DataFrame({"x": x, "y": y}).dropna()
    if len(pair) < min_samples:
        return math.nan
    corr, _ = spearmanr(pair["x"], pair["y"])
    if pd.isna(corr):
        return math.nan
    return float(corr)


def _safe_pearson(x: pd.Series, y: pd.Series, min_samples: int) -> float:
    pair = pd.DataFrame({"x": x, "y": y}).dropna()
    if len(pair) < min_samples:
        return math.nan
    corr = pair["x"].corr(pair["y"], method="pearson")
    if pd.isna(corr):
        return math.nan
    return float(corr)


def _load_recommendations(
    recommendation_db: Path,
    start_date: Optional[str],
    end_date: Optional[str],
    top_n_per_day: int,
) -> pd.DataFrame:
    conn = sqlite3.connect(str(recommendation_db))
    try:
        sql = """
            SELECT symbol, name, recommendation_date, recommendation_score
            FROM recommendations
            WHERE 1=1
        """
        params: List[object] = []
        if start_date:
            sql += " AND recommendation_date >= ?"
            params.append(f"{start_date[:4]}-{start_date[4:6]}-{start_date[6:]}")
        if end_date:
            sql += " AND recommendation_date <= ?"
            params.append(f"{end_date[:4]}-{end_date[4:6]}-{end_date[6:]}")
        sql += " ORDER BY recommendation_date ASC, recommendation_score DESC, symbol ASC"

        df = pd.read_sql(sql, conn, params=params)
    finally:
        conn.close()

    if df.empty:
        return df

    df["rec_date"] = df["recommendation_date"].map(_norm_date)
    df = df.dropna(subset=["rec_date"]).reset_index(drop=True)
    if top_n_per_day > 0:
        df = (
            df.sort_values(["rec_date", "recommendation_score", "symbol"], ascending=[True, False, True])
            .groupby("rec_date", as_index=False, group_keys=False)
            .head(top_n_per_day)
            .reset_index(drop=True)
        )
    return df


def _calc_legacy_opt_factor_panel(
    recommendation_df: pd.DataFrame,
    selector: StockSelector,
) -> pd.DataFrame:
    if recommendation_df.empty:
        return pd.DataFrame()

    weights = selector._get_active_weights()
    rows: List[Dict[str, object]] = []

    for item in recommendation_df.to_dict("records"):
        ts_code = str(item["symbol"])
        name = str(item.get("name", ""))
        rec_date = str(item["rec_date"])

        stock_row = selector.db.query_one(
            "SELECT name, industry, list_date FROM stock_basic WHERE ts_code = ?",
            (ts_code,),
        )
        if not stock_row:
            continue

        df = selector.get_stock_daily_data(ts_code=ts_code, days=120, end_date=rec_date)
        if df.empty or len(df) < 20:
            continue

        trend_score, _ = selector.calculate_trend_factor(df)
        momentum_score, _ = selector.calculate_momentum_factor_legacy(df)
        volume_score, _ = selector.calculate_volume_factor_legacy(df)
        fundamental_score, _ = selector.calculate_fundamental_factor_legacy(
            ts_code=ts_code,
            end_date=rec_date,
            name=stock_row.get("name", name),
            industry=stock_row.get("industry", ""),
            list_date=stock_row.get("list_date", ""),
        )
        pullback_score, _ = selector.calculate_pullback_factor(df)

        total_score = (
            trend_score * weights["trend"]
            + momentum_score * weights["momentum"]
            + volume_score * weights["volume"]
            + fundamental_score * weights["fundamental"]
            + pullback_score * weights["pullback"]
        )

        rows.append(
            {
                "ts_code": ts_code,
                "name": stock_row.get("name", name),
                "industry": stock_row.get("industry", ""),
                "rec_date": rec_date,
                "stored_recommendation_score": float(item.get("recommendation_score", 0.0) or 0.0),
                "trend_score": float(trend_score),
                "momentum_score": float(momentum_score),
                "volume_score": float(volume_score),
                "fundamental_score": float(fundamental_score),
                "pullback_score": float(pullback_score),
                "total_score": float(total_score),
            }
        )

    return pd.DataFrame(rows)


def _load_trade_dates(market_db: Path) -> List[str]:
    conn = sqlite3.connect(str(market_db))
    try:
        rows = conn.execute("SELECT DISTINCT trade_date FROM stock_daily ORDER BY trade_date").fetchall()
    finally:
        conn.close()
    return [str(row[0]) for row in rows]


def _attach_forward_returns(
    panel: pd.DataFrame,
    market_db: Path,
    trade_dates: List[str],
    horizons: List[int],
) -> pd.DataFrame:
    if panel.empty or not horizons:
        return pd.DataFrame()

    date_to_idx = {d: i for i, d in enumerate(trade_dates)}
    x = panel.copy()
    x["rec_idx"] = x["rec_date"].map(date_to_idx)
    x = x.dropna(subset=["rec_idx"]).copy()
    x["rec_idx"] = x["rec_idx"].astype(int)
    x = x[x["rec_idx"] + max(horizons) < len(trade_dates)].copy()
    if x.empty:
        return x

    x["buy_date"] = x["rec_idx"].map(lambda idx: trade_dates[idx + 1])
    for h in horizons:
        x[f"sell_{h}_date"] = x["rec_idx"].map(lambda idx, hh=h: trade_dates[idx + hh])

    all_dates = set(x["buy_date"].astype(str).tolist())
    for h in horizons:
        all_dates.update(x[f"sell_{h}_date"].astype(str).tolist())
    min_date = min(all_dates)
    max_date = max(all_dates)

    conn = sqlite3.connect(str(market_db))
    try:
        price_df = pd.read_sql(
            """
            SELECT ts_code, trade_date, open, high, low, close
            FROM stock_daily
            WHERE trade_date >= ? AND trade_date <= ?
            """,
            conn,
            params=(min_date, max_date),
        )
    finally:
        conn.close()

    if price_df.empty:
        return pd.DataFrame()

    price_df["trade_date"] = price_df["trade_date"].astype(str)
    for col in ("open", "high", "low", "close"):
        price_df[col] = pd.to_numeric(price_df[col], errors="coerce")
    price_df = price_df.dropna(subset=["open", "high", "low", "close"])
    if price_df.empty:
        return pd.DataFrame()

    symbols = set(x["ts_code"].astype(str).tolist())
    price_df = price_df[price_df["ts_code"].isin(symbols)].copy()
    price_map: Dict[tuple[str, str], Dict[str, float]] = {}
    for row in price_df.to_dict("records"):
        price_map[(str(row["ts_code"]), str(row["trade_date"]))] = {
            "open": float(row["open"]),
            "high": float(row["high"]),
            "low": float(row["low"]),
            "close": float(row["close"]),
        }

    details: List[Dict[str, object]] = []
    for item in x.to_dict("records"):
        symbol = str(item["ts_code"])
        rec_idx = int(item["rec_idx"])
        buy_date = str(item["buy_date"])
        buy_bar = price_map.get((symbol, buy_date))
        if not buy_bar or float(buy_bar["open"]) <= 0:
            continue
        buy_open = float(buy_bar["open"])

        for horizon in horizons:
            sell_date = str(item[f"sell_{horizon}_date"])
            sell_bar = price_map.get((symbol, sell_date))
            if not sell_bar or float(sell_bar["close"]) <= 0:
                continue

            period_dates = trade_dates[rec_idx + 1 : rec_idx + horizon + 1]
            highs: List[float] = []
            lows: List[float] = []
            for trade_date in period_dates:
                bar = price_map.get((symbol, trade_date))
                if not bar:
                    continue
                highs.append(float(bar["high"]))
                lows.append(float(bar["low"]))
            if not highs or not lows:
                continue

            details.append(
                {
                    **item,
                    "horizon": int(horizon),
                    "buy_date": buy_date,
                    "sell_date": sell_date,
                    "buy_open": buy_open,
                    "sell_close": float(sell_bar["close"]),
                    "ret_oc": float(sell_bar["close"]) / buy_open - 1.0,
                    "mfe": max(highs) / buy_open - 1.0,
                    "mae": min(lows) / buy_open - 1.0,
                }
            )

    return pd.DataFrame(details)


def _calc_factor_ic(
    detail_df: pd.DataFrame,
    factors: Iterable[str],
    min_daily_samples: int,
) -> pd.DataFrame:
    rows: List[Dict[str, object]] = []
    if detail_df.empty:
        return pd.DataFrame()

    for horizon, horizon_df in detail_df.groupby("horizon", sort=True):
        for factor in factors:
            daily_rank: List[float] = []
            daily_pearson: List[float] = []
            sample_sizes: List[int] = []

            for _, day_df in horizon_df.groupby("rec_date", sort=True):
                pair = day_df[[factor, "ret_oc"]].dropna()
                if len(pair) < min_daily_samples:
                    continue
                rank_ic = _safe_spearman(pair[factor], pair["ret_oc"], min_daily_samples)
                pearson_ic = _safe_pearson(pair[factor], pair["ret_oc"], min_daily_samples)
                if pd.isna(rank_ic) or pd.isna(pearson_ic):
                    continue
                daily_rank.append(float(rank_ic))
                daily_pearson.append(float(pearson_ic))
                sample_sizes.append(int(len(pair)))

            pooled_rank = _safe_spearman(horizon_df[factor], horizon_df["ret_oc"], min_daily_samples)
            pooled_pearson = _safe_pearson(horizon_df[factor], horizon_df["ret_oc"], min_daily_samples)

            spread_rows: List[float] = []
            for _, day_df in horizon_df.groupby("rec_date", sort=True):
                day_df = day_df[[factor, "ret_oc"]].dropna().sort_values(factor)
                if len(day_df) < min_daily_samples:
                    continue
                split = max(1, len(day_df) // 2)
                bottom = day_df.head(split)["ret_oc"]
                top = day_df.tail(split)["ret_oc"]
                if bottom.empty or top.empty:
                    continue
                spread_rows.append(float(top.mean() - bottom.mean()))

            daily_rank_series = pd.Series(daily_rank, dtype=float)
            rows.append(
                {
                    "horizon": int(horizon),
                    "factor": factor,
                    "sample_rows": int(len(horizon_df)),
                    "sample_days": int(len(daily_rank)),
                    "avg_cross_section": float(sum(sample_sizes) / len(sample_sizes)) if sample_sizes else 0.0,
                    "pooled_rank_ic": float(pooled_rank) if not pd.isna(pooled_rank) else math.nan,
                    "pooled_pearson_ic": float(pooled_pearson) if not pd.isna(pooled_pearson) else math.nan,
                    "daily_rank_ic_mean": float(daily_rank_series.mean()) if not daily_rank_series.empty else math.nan,
                    "daily_rank_ic_std": float(daily_rank_series.std(ddof=0)) if not daily_rank_series.empty else math.nan,
                    "daily_rank_ic_positive_ratio": (
                        float((daily_rank_series > 0).mean()) if not daily_rank_series.empty else math.nan
                    ),
                    "top_bottom_half_spread": float(pd.Series(spread_rows, dtype=float).mean()) if spread_rows else math.nan,
                }
            )

    return pd.DataFrame(rows).sort_values(["horizon", "daily_rank_ic_mean"], ascending=[True, False])


def _calc_factor_correlation(panel_df: pd.DataFrame) -> pd.DataFrame:
    if panel_df.empty:
        return pd.DataFrame()
    return panel_df[LEGACY_OPT_FACTORS].corr(method="pearson")


def _render_markdown(
    report_path: Path,
    meta: Dict[str, object],
    ic_df: pd.DataFrame,
    corr_df: pd.DataFrame,
) -> None:
    lines: List[str] = []
    lines.append("# 原策略优化版 IC 分析报告")
    lines.append("")
    lines.append("## 口径")
    lines.append("")
    lines.append("- 样本来源：历史推荐名单（recommendations 表）")
    lines.append("- 因子口径：按 `legacy_opt` 当前 5 因子公式重新计算")
    lines.append("- 收益口径：T+1 开盘买入，T+2 / T+3 / T+5 收盘卖出")
    lines.append("- 说明：本报告反映“推荐池内”的因子区分能力，不代表全市场横截面 IC")
    lines.append("")
    lines.append("## 样本概览")
    lines.append("")
    lines.append(f"- 推荐日期范围：`{meta['date_range'][0]}` ~ `{meta['date_range'][1]}`")
    lines.append(f"- 推荐交易日数：`{meta['rec_days']}`")
    lines.append(f"- 推荐样本数：`{meta['rec_rows']}`")
    lines.append(f"- 成功重算因子样本：`{meta['factor_rows']}`")
    lines.append(f"- 有效收益样本：`{meta['detail_rows']}`")
    lines.append(f"- legacy_opt 权重：`{meta['weights']}`")
    lines.append("")
    lines.append("## IC 汇总")
    lines.append("")
    if ic_df.empty:
        lines.append("无有效 IC 结果。")
    else:
        header = (
            "| 周期 | 因子 | 样本日 | 行内样本均值 | Pooled RankIC | Daily RankIC均值 | 正IC占比 | "
            "Top-Bottom半组收益差 |"
        )
        sep = "| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: |"
        lines.extend([header, sep])
        for row in ic_df.to_dict("records"):
            lines.append(
                "| {horizon} | {factor} | {sample_days} | {avg_cross_section:.1f} | "
                "{pooled_rank_ic:.4f} | {daily_rank_ic_mean:.4f} | {daily_rank_ic_positive_ratio:.2%} | "
                "{top_bottom_half_spread:.2%} |".format(**row)
            )
    lines.append("")
    lines.append("## 因子相关性")
    lines.append("")
    if corr_df.empty:
        lines.append("无相关性结果。")
    else:
        header = "| 因子 | " + " | ".join(corr_df.columns.tolist()) + " |"
        sep = "| --- | " + " | ".join(["---:" for _ in corr_df.columns]) + " |"
        lines.extend([header, sep])
        for factor, row in corr_df.iterrows():
            lines.append(
                "| {} | {} |".format(
                    factor,
                    " | ".join(f"{float(value):.4f}" for value in row.tolist()),
                )
            )

    report_path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze legacy_opt IC from historical recommendation pool.")
    parser.add_argument("--rec-db", type=str, default="data/history_recommendation.db")
    parser.add_argument("--market-db", type=str, default="data/database/quant_system.db")
    parser.add_argument("--start-date", type=str, default=None)
    parser.add_argument("--end-date", type=str, default=None)
    parser.add_argument("--top-n-per-day", type=int, default=10)
    parser.add_argument("--horizons", type=str, default="2,3,5")
    parser.add_argument("--min-daily-samples", type=int, default=5)
    parser.add_argument("--report-dir", type=str, default="reports")
    args = parser.parse_args()

    recommendation_db = ROOT / args.rec_db
    market_db = ROOT / args.market_db
    report_dir = ROOT / args.report_dir
    report_dir.mkdir(parents=True, exist_ok=True)

    start_date = _norm_date(args.start_date)
    end_date = _norm_date(args.end_date)
    horizons = sorted({int(x.strip()) for x in str(args.horizons).split(",") if x.strip()})
    if not horizons:
        raise SystemExit("No valid horizons.")

    recommendation_df = _load_recommendations(
        recommendation_db=recommendation_db,
        start_date=start_date,
        end_date=end_date,
        top_n_per_day=int(args.top_n_per_day),
    )
    if recommendation_df.empty:
        raise SystemExit("No recommendation records found.")

    config = ConfigManager()
    config.set("stock_selection.strategy_profile", "legacy_opt", save=False)
    config.set("stock_selection.save_factor_values", False, save=False)
    db = DatabaseManager(config)
    selector = StockSelector(config=config, db=db)

    panel_df = _calc_legacy_opt_factor_panel(recommendation_df=recommendation_df, selector=selector)
    trade_dates = _load_trade_dates(market_db=market_db)
    detail_df = _attach_forward_returns(
        panel=panel_df,
        market_db=market_db,
        trade_dates=trade_dates,
        horizons=horizons,
    )
    ic_df = _calc_factor_ic(
        detail_df=detail_df,
        factors=LEGACY_OPT_FACTORS,
        min_daily_samples=int(args.min_daily_samples),
    )
    corr_df = _calc_factor_correlation(panel_df)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    md_path = report_dir / f"legacy_opt_ic_{timestamp}.md"
    json_path = report_dir / f"legacy_opt_ic_{timestamp}.json"
    detail_csv_path = report_dir / f"legacy_opt_ic_detail_{timestamp}.csv"
    ic_csv_path = report_dir / f"legacy_opt_ic_summary_{timestamp}.csv"

    if not detail_df.empty:
        detail_df.to_csv(detail_csv_path, index=False, encoding="utf-8-sig")
    if not ic_df.empty:
        ic_df.to_csv(ic_csv_path, index=False, encoding="utf-8-sig")

    meta = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "date_range": [str(recommendation_df["rec_date"].min()), str(recommendation_df["rec_date"].max())],
        "rec_days": int(recommendation_df["rec_date"].nunique()),
        "rec_rows": int(len(recommendation_df)),
        "factor_rows": int(len(panel_df)),
        "detail_rows": int(len(detail_df)),
        "weights": selector._get_active_weights(),
        "horizons": horizons,
        "top_n_per_day": int(args.top_n_per_day),
        "min_daily_samples": int(args.min_daily_samples),
        "files": {
            "markdown": str(md_path),
            "json": str(json_path),
            "detail_csv": str(detail_csv_path),
            "summary_csv": str(ic_csv_path),
        },
    }

    _render_markdown(md_path, meta=meta, ic_df=ic_df, corr_df=corr_df)
    json_path.write_text(
        json.dumps(
            {
                "meta": meta,
                "ic_summary": json.loads(ic_df.to_json(orient="records", force_ascii=False)) if not ic_df.empty else [],
                "correlation": json.loads(corr_df.reset_index().to_json(orient="records", force_ascii=False))
                if not corr_df.empty
                else [],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print(f"markdown: {md_path}")
    print(f"json: {json_path}")
    if not ic_df.empty:
        print(f"summary_csv: {ic_csv_path}")
    if not detail_df.empty:
        print(f"detail_csv: {detail_csv_path}")
    if not ic_df.empty:
        for horizon in horizons:
            subset = ic_df[ic_df["horizon"] == horizon].head(3)
            if subset.empty:
                continue
            print(f"Top factors @ T+{horizon}:")
            for row in subset.to_dict("records"):
                print(
                    f"  {row['factor']}: daily_rank_ic_mean={row['daily_rank_ic_mean']:.4f}, "
                    f"pooled_rank_ic={row['pooled_rank_ic']:.4f}, spread={row['top_bottom_half_spread']:.2%}"
                )


if __name__ == "__main__":
    main()
