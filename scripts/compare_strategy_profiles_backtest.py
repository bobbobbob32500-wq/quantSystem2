# -*- coding: utf-8 -*-
"""
Compare legacy vs enhanced stock-selection profiles on the same historical window.

Backtest convention:
1. Run pre-market selection on trade date T.
2. Buy at T+1 open.
3. Sell at T+2 / T+3 / T+4 / T+5 close.
4. Track return, MFE, MAE and daily average return.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.core.config import ConfigManager
from src.core.database import DatabaseManager
from src.modules.stock_selector import StockSelector


@dataclass
class HorizonSummary:
    strategy_profile: str
    enhanced_weight_profile: str
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

    def to_dict(self) -> Dict[str, object]:
        return {
            "strategy_profile": self.strategy_profile,
            "enhanced_weight_profile": self.enhanced_weight_profile,
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
    text = str(value).strip()
    if not text:
        return None
    digits = "".join(ch for ch in text if ch.isdigit())
    if len(digits) < 8:
        return None
    return digits[:8]


def _resolve_path(raw_path: str) -> Path:
    path = Path(raw_path)
    if path.is_absolute():
        return path
    return ROOT / path


def _mean(series: pd.Series) -> float:
    if series.empty:
        return 0.0
    return float(series.mean())


def _quantile(series: pd.Series, q: float) -> float:
    if series.empty:
        return 0.0
    return float(series.quantile(q))


def load_trade_dates(conn: sqlite3.Connection) -> List[str]:
    sql = "SELECT DISTINCT trade_date FROM stock_daily ORDER BY trade_date"
    return [str(row[0]) for row in conn.execute(sql).fetchall()]


def choose_signal_dates(
    trade_dates: List[str],
    signal_days: int,
    horizon_max: int,
    start_date: Optional[str],
    end_date: Optional[str],
) -> List[str]:
    normalized_start = _norm_date(start_date)
    normalized_end = _norm_date(end_date)
    selected = [
        d for d in trade_dates
        if (normalized_start is None or d >= normalized_start)
        and (normalized_end is None or d <= normalized_end)
    ]
    if len(selected) <= horizon_max:
        return []
    selected = selected[: len(selected) - horizon_max]
    if signal_days > 0 and len(selected) > signal_days:
        selected = selected[-signal_days:]
    return selected


def _build_selector(
    strategy_profile: str,
    db: DatabaseManager,
    enhanced_weight_profile: Optional[str],
) -> StockSelector:
    config = ConfigManager()
    config.set("stock_selection.save_factor_values", False, save=False)
    config.set("stock_selection.strategy_profile", strategy_profile, save=False)
    if enhanced_weight_profile:
        config.set("stock_selection.enhanced_weight_profile", enhanced_weight_profile, save=False)
    return StockSelector(config=config, db=db)


def collect_recommendations(
    strategy_profile: str,
    signal_dates: List[str],
    db: DatabaseManager,
    top_n: int,
    enhanced_weight_profile: Optional[str],
) -> Tuple[pd.DataFrame, Dict[str, object]]:
    selector = _build_selector(
        strategy_profile=strategy_profile,
        db=db,
        enhanced_weight_profile=enhanced_weight_profile,
    )
    records: List[Dict[str, object]] = []
    errors: List[Dict[str, str]] = []
    selected_days = 0
    total_recommendations = 0
    start_time = time.time()

    for idx, trade_date in enumerate(signal_dates, start=1):
        try:
            results = selector.run_selection(end_date=trade_date)
            if top_n > 0:
                results = results[:top_n]
            if results:
                selected_days += 1
            total_recommendations += len(results)
            for rank, item in enumerate(results, start=1):
                records.append(
                    {
                        "strategy_profile": strategy_profile,
                        "enhanced_weight_profile": (
                            selector.get_enhanced_weight_profile_name()
                            if strategy_profile == "enhanced"
                            else "legacy"
                        ),
                        "rec_date": trade_date,
                        "ts_code": str(item.get("ts_code", "")),
                        "name": str(item.get("name", "")),
                        "industry": str(item.get("industry", "")),
                        "rank": int(rank),
                        "score": float(item.get("total_score", 0.0) or 0.0),
                        "level": str(item.get("level", "")),
                    }
                )
        except Exception as exc:
            errors.append({"trade_date": trade_date, "error": str(exc)})

        if idx % 10 == 0 or idx == len(signal_dates):
            print(
                f"[{strategy_profile}] progress {idx}/{len(signal_dates)} | "
                f"selected_days={selected_days} | total_records={len(records)}"
            )

    elapsed = time.time() - start_time
    meta = {
        "strategy_profile": strategy_profile,
        "enhanced_weight_profile": (
            selector.get_enhanced_weight_profile_name()
            if strategy_profile == "enhanced"
            else "legacy"
        ),
        "signal_days": len(signal_dates),
        "selected_days": int(selected_days),
        "total_recommendations": int(total_recommendations),
        "average_candidates_per_selected_day": (
            float(total_recommendations / selected_days) if selected_days > 0 else 0.0
        ),
        "error_count": int(len(errors)),
        "errors": errors[:20],
        "elapsed_seconds": float(elapsed),
    }
    return pd.DataFrame(records), meta


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
    return raw.dropna(subset=["open", "high", "low", "close"])


def evaluate_recommendations(
    recommendation_df: pd.DataFrame,
    market_db_path: Path,
    trade_dates: List[str],
    horizons: List[int],
) -> Tuple[pd.DataFrame, List[HorizonSummary]]:
    if recommendation_df.empty:
        return pd.DataFrame(), []

    date_to_idx = {d: i for i, d in enumerate(trade_dates)}
    max_h = max(horizons)

    rec = recommendation_df.copy()
    rec["rec_idx"] = rec["rec_date"].map(date_to_idx)
    rec = rec.dropna(subset=["rec_idx"])
    rec["rec_idx"] = rec["rec_idx"].astype(int)
    rec = rec[rec["rec_idx"] + max_h < len(trade_dates)].copy()
    if rec.empty:
        return pd.DataFrame(), []

    min_buy_idx = int(rec["rec_idx"].min() + 1)
    max_sell_idx = int(rec["rec_idx"].max() + max_h)
    date_min = trade_dates[min_buy_idx]
    date_max = trade_dates[max_sell_idx]

    symbols = sorted(rec["ts_code"].dropna().unique().tolist())
    conn = sqlite3.connect(str(market_db_path))
    try:
        price_df = _load_market_data(conn, symbols=symbols, date_min=date_min, date_max=date_max)
    finally:
        conn.close()

    if price_df.empty:
        return pd.DataFrame(), []

    price_map: Dict[Tuple[str, str], Dict[str, float]] = {}
    for row in price_df.to_dict("records"):
        price_map[(str(row["ts_code"]), str(row["trade_date"]))] = {
            "open": float(row["open"]),
            "high": float(row["high"]),
            "low": float(row["low"]),
            "close": float(row["close"]),
        }

    details: List[Dict[str, object]] = []
    for item in rec.to_dict("records"):
        symbol = str(item["ts_code"])
        rec_idx = int(item["rec_idx"])
        buy_date = trade_dates[rec_idx + 1]
        buy_bar = price_map.get((symbol, buy_date))
        if not buy_bar:
            continue
        buy_open = float(buy_bar["open"])
        if buy_open <= 0:
            continue

        for horizon in horizons:
            sell_date = trade_dates[rec_idx + horizon]
            sell_bar = price_map.get((symbol, sell_date))
            if not sell_bar:
                continue
            sell_close = float(sell_bar["close"])
            if sell_close <= 0:
                continue

            holding_dates = trade_dates[rec_idx + 1 : rec_idx + horizon + 1]
            highs: List[float] = []
            lows: List[float] = []
            for hold_date in holding_dates:
                bar = price_map.get((symbol, hold_date))
                if not bar:
                    continue
                highs.append(float(bar["high"]))
                lows.append(float(bar["low"]))
            if not highs or not lows:
                continue

            details.append(
                {
                    **item,
                    "buy_date": buy_date,
                    "sell_date": sell_date,
                    "horizon": int(horizon),
                    "buy_open": buy_open,
                    "sell_close": sell_close,
                    "ret": sell_close / buy_open - 1.0,
                    "mfe": max(highs) / buy_open - 1.0,
                    "mae": min(lows) / buy_open - 1.0,
                }
            )

    detail_df = pd.DataFrame(details)
    if detail_df.empty:
        return detail_df, []

    summaries: List[HorizonSummary] = []
    grouped = detail_df.groupby(["strategy_profile", "enhanced_weight_profile", "horizon"])
    for (strategy_profile, weight_profile, horizon), group in grouped:
        daily = group.groupby("rec_date", as_index=False)["ret"].mean()
        day_ret = daily["ret"]
        ret = group["ret"]
        summaries.append(
            HorizonSummary(
                strategy_profile=str(strategy_profile),
                enhanced_weight_profile=str(weight_profile),
                horizon=int(horizon),
                sample_count=int(len(group)),
                trade_days=int(group["rec_date"].nunique()),
                mean_return=_mean(ret),
                median_return=_quantile(ret, 0.5),
                win_rate=float((ret > 0).mean()) if not ret.empty else 0.0,
                p25_return=_quantile(ret, 0.25),
                p75_return=_quantile(ret, 0.75),
                mean_mfe=_mean(group["mfe"]),
                mean_mae=_mean(group["mae"]),
                day_mean_return=_mean(day_ret),
                day_win_rate=float((day_ret > 0).mean()) if not day_ret.empty else 0.0,
            )
        )

    summaries.sort(key=lambda x: (x.horizon, x.strategy_profile))
    return detail_df, summaries


def build_comparison(summary_df: pd.DataFrame) -> pd.DataFrame:
    if summary_df.empty:
        return pd.DataFrame()

    rows: List[Dict[str, object]] = []
    for horizon, group in summary_df.groupby("horizon"):
        legacy = group[group["strategy_profile"] == "legacy"]
        enhanced = group[group["strategy_profile"] == "enhanced"]
        if legacy.empty or enhanced.empty:
            continue

        l = legacy.iloc[0]
        e = enhanced.iloc[0]
        rows.append(
            {
                "horizon": int(horizon),
                "legacy_mean_return": float(l["mean_return"]),
                "enhanced_mean_return": float(e["mean_return"]),
                "delta_mean_return": float(e["mean_return"] - l["mean_return"]),
                "legacy_win_rate": float(l["win_rate"]),
                "enhanced_win_rate": float(e["win_rate"]),
                "delta_win_rate": float(e["win_rate"] - l["win_rate"]),
                "legacy_day_mean_return": float(l["day_mean_return"]),
                "enhanced_day_mean_return": float(e["day_mean_return"]),
                "delta_day_mean_return": float(e["day_mean_return"] - l["day_mean_return"]),
                "legacy_mean_mae": float(l["mean_mae"]),
                "enhanced_mean_mae": float(e["mean_mae"]),
                "delta_mean_mae": float(e["mean_mae"] - l["mean_mae"]),
                "winner": (
                    "enhanced"
                    if float(e["mean_return"]) > float(l["mean_return"])
                    else "legacy"
                    if float(l["mean_return"]) > float(e["mean_return"])
                    else "tie"
                ),
            }
        )

    return pd.DataFrame(rows).sort_values("horizon").reset_index(drop=True)


def render_report(
    output_path: Path,
    meta: Dict[str, object],
    summary_df: pd.DataFrame,
    comparison_df: pd.DataFrame,
) -> None:
    lines: List[str] = []
    lines.append("# 原策略 vs 增强策略 同窗回测报告")
    lines.append("")
    lines.append("## 回测口径")
    lines.append("")
    lines.append("- T日盘前选股")
    lines.append("- T+1开盘买入")
    lines.append("- T+2 / T+3 / T+4 / T+5收盘卖出")
    lines.append("- 使用本地真实A股历史日线数据，不使用模拟数据")
    lines.append("")
    lines.append("## 回测范围")
    lines.append("")
    lines.append(f"- 信号日期范围: `{meta['signal_date_start']}` ~ `{meta['signal_date_end']}`")
    lines.append(f"- 信号交易日数: `{meta['signal_days']}`")
    lines.append(f"- TopN: `{meta['top_n']}`")
    lines.append(f"- 增强权重档位: `{meta['enhanced_weight_profile']}`")
    lines.append("")
    lines.append("## 选股执行概览")
    lines.append("")
    for profile_meta in meta["profiles"]:
        lines.append(
            f"- `{profile_meta['strategy_profile']}`: 触发天数 `{profile_meta['selected_days']}` / "
            f"`{profile_meta['signal_days']}`，总样本 `{profile_meta['total_recommendations']}`，"
            f"平均每个出股日 `{profile_meta['average_candidates_per_selected_day']:.2f}` 只，"
            f"报错 `{profile_meta['error_count']}` 次，用时 `{profile_meta['elapsed_seconds']:.1f}` 秒"
        )
    lines.append("")
    lines.append("## 分策略分周期汇总")
    lines.append("")
    if summary_df.empty:
        lines.append("无有效汇总结果。")
    else:
        header = (
            "| 策略 | 权重档 | 周期 | 样本 | 交易日 | 均值收益 | 胜率 | 日均收益 | 日胜率 | 平均MFE | 平均MAE |"
        )
        sep = "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"
        lines.extend([header, sep])
        for row in summary_df.to_dict("records"):
            lines.append(
                "| {strategy_profile} | {enhanced_weight_profile} | {horizon} | {sample_count} | {trade_days} | "
                "{mean_return:.2%} | {win_rate:.2%} | {day_mean_return:.2%} | {day_win_rate:.2%} | "
                "{mean_mfe:.2%} | {mean_mae:.2%} |".format(**row)
            )
    lines.append("")
    lines.append("## 直接对比")
    lines.append("")
    if comparison_df.empty:
        lines.append("无可对比结果。")
    else:
        header = (
            "| 周期 | 原策略均值 | 增强策略均值 | 差值(增强-原) | 原策略胜率 | 增强策略胜率 | "
            "差值(增强-原) | 原策略日均收益 | 增强策略日均收益 | 胜出方 |"
        )
        sep = "| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |"
        lines.extend([header, sep])
        for row in comparison_df.to_dict("records"):
            lines.append(
                "| {horizon} | {legacy_mean_return:.2%} | {enhanced_mean_return:.2%} | {delta_mean_return:.2%} | "
                "{legacy_win_rate:.2%} | {enhanced_win_rate:.2%} | {delta_win_rate:.2%} | "
                "{legacy_day_mean_return:.2%} | {enhanced_day_mean_return:.2%} | {winner} |".format(**row)
            )

        main_horizon = int(meta["main_horizon"])
        main_row = comparison_df[comparison_df["horizon"] == main_horizon]
        if not main_row.empty:
            row = main_row.iloc[0]
            lines.append("")
            lines.append("## 结论")
            lines.append("")
            lines.append(
                f"- 主观察周期 `T+{main_horizon}` 下，`{row['winner']}` 更优；"
                f"增强相对原策略的均值收益差为 `{row['delta_mean_return']:.2%}`，"
                f"胜率差为 `{row['delta_win_rate']:.2%}`。"
            )

    output_path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare legacy and enhanced selection strategies by backtest.")
    parser.add_argument("--signal-days", type=int, default=60, help="Number of signal trade days to test")
    parser.add_argument("--start-date", type=str, default=None, help="Signal start date YYYYMMDD")
    parser.add_argument("--end-date", type=str, default=None, help="Signal end date YYYYMMDD")
    parser.add_argument("--top-n", type=int, default=10, help="Recommendations per day")
    parser.add_argument("--horizons", type=str, default="2,3,4,5", help="Sell horizons, comma separated")
    parser.add_argument("--main-horizon", type=int, default=5, help="Primary horizon for conclusion")
    parser.add_argument(
        "--enhanced-weight-profile",
        type=str,
        default=None,
        help="Named enhanced weight profile, default uses current active profile",
    )
    parser.add_argument("--report-dir", type=str, default="reports", help="Output report directory")
    args = parser.parse_args()

    config = ConfigManager()
    market_db_path = _resolve_path(str(config.get("database.path", "data/database/quant_system.db")))
    report_dir = _resolve_path(args.report_dir)
    report_dir.mkdir(parents=True, exist_ok=True)

    horizons = sorted({int(x.strip()) for x in args.horizons.split(",") if x.strip()})
    if not horizons:
        raise ValueError("No valid horizons provided.")
    horizon_max = max(horizons)

    conn = sqlite3.connect(str(market_db_path))
    try:
        trade_dates = load_trade_dates(conn)
    finally:
        conn.close()
    signal_dates = choose_signal_dates(
        trade_dates=trade_dates,
        signal_days=args.signal_days,
        horizon_max=horizon_max,
        start_date=args.start_date,
        end_date=args.end_date,
    )
    if not signal_dates:
        raise ValueError("No valid signal dates found for requested window.")

    active_enhanced_profile = (
        str(args.enhanced_weight_profile).strip().lower()
        if args.enhanced_weight_profile
        else str(config.get("stock_selection.enhanced_weight_profile", "active")).strip().lower() or "active"
    )

    db = DatabaseManager(config)
    profile_metas: List[Dict[str, object]] = []
    recommendation_frames: List[pd.DataFrame] = []
    for strategy_profile in ("legacy", "enhanced"):
        rec_df, profile_meta = collect_recommendations(
            strategy_profile=strategy_profile,
            signal_dates=signal_dates,
            db=db,
            top_n=args.top_n,
            enhanced_weight_profile=active_enhanced_profile,
        )
        profile_metas.append(profile_meta)
        recommendation_frames.append(rec_df)

    all_recommendations = pd.concat(recommendation_frames, ignore_index=True)
    detail_df, summaries = evaluate_recommendations(
        recommendation_df=all_recommendations,
        market_db_path=market_db_path,
        trade_dates=trade_dates,
        horizons=horizons,
    )
    summary_df = pd.DataFrame([item.to_dict() for item in summaries])
    comparison_df = build_comparison(summary_df)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    md_path = report_dir / f"strategy_profile_compare_{timestamp}.md"
    json_path = report_dir / f"strategy_profile_compare_{timestamp}.json"
    summary_csv_path = report_dir / f"strategy_profile_compare_summary_{timestamp}.csv"
    detail_csv_path = report_dir / f"strategy_profile_compare_details_{timestamp}.csv"

    meta = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "signal_date_start": signal_dates[0],
        "signal_date_end": signal_dates[-1],
        "signal_days": len(signal_dates),
        "top_n": int(args.top_n),
        "horizons": horizons,
        "main_horizon": int(args.main_horizon),
        "enhanced_weight_profile": active_enhanced_profile,
        "market_db_path": str(market_db_path),
        "profiles": profile_metas,
    }

    render_report(md_path, meta=meta, summary_df=summary_df, comparison_df=comparison_df)
    summary_df.to_csv(summary_csv_path, index=False, encoding="utf-8-sig")
    detail_df.to_csv(detail_csv_path, index=False, encoding="utf-8-sig")
    json_path.write_text(
        json.dumps(
            {
                "meta": meta,
                "summary": summary_df.to_dict("records"),
                "comparison": comparison_df.to_dict("records"),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print(f"Markdown report: {md_path}")
    print(f"JSON report: {json_path}")
    print(f"Summary CSV: {summary_csv_path}")
    print(f"Detail CSV: {detail_csv_path}")


if __name__ == "__main__":
    main()
