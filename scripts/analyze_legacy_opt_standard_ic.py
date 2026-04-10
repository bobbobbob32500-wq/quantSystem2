# -*- coding: utf-8 -*-
"""
Standard IC analysis for legacy_opt using the same methodology as factor_analysis.py.

Methodology alignment:
1. Cross-sectional daily IC on full filtered main-board universe.
2. future_return = close.pct_change(period).shift(-period)
3. Daily IC uses Spearman correlation, requiring >= 30 samples per day.
4. Layer analysis uses 5 buckets and requires >= 100 samples per day.

The script recomputes legacy_opt factors directly from stock_daily / stock_basic
instead of reusing factor_values, so the result is strategy-profile specific.
"""

from __future__ import annotations

import argparse
import json
import math
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.core.config import ConfigManager
from src.modules.factor_analysis import FactorWeightOptimizer


DEFAULT_FACTOR_NAMES = [
    "trend_score",
    "momentum_score",
    "volume_score",
    "pullback_score",
]

HOT_INDUSTRIES = {
    "电子",
    "计算机",
    "通信",
    "电气设备",
    "机械设备",
    "汽车",
    "医药生物",
    "化工",
}

NEUTRAL_INDUSTRIES = {
    "房地产",
    "银行",
    "非银金融",
    "建筑装饰",
    "建筑材料",
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


def _safe_spearman(x: pd.Series, y: pd.Series) -> Tuple[float, float]:
    corr, p_value = spearmanr(x, y)
    if pd.isna(corr):
        return math.nan, math.nan
    return float(corr), float(p_value)


def _today_yyyymmdd() -> str:
    return datetime.now().strftime("%Y%m%d")


def _load_default_range(conn: sqlite3.Connection) -> Tuple[str, str]:
    factor_row = conn.execute(
        "SELECT MIN(trade_date), MAX(trade_date) FROM factor_values WHERE factor_name = 'trend_score'"
    ).fetchone()
    daily_row = conn.execute(
        "SELECT MIN(trade_date), MAX(trade_date) FROM stock_daily"
    ).fetchone()
    daily_min = _norm_date(daily_row[0]) if daily_row else None
    daily_max = _norm_date(daily_row[1]) if daily_row else None
    factor_min = _norm_date(factor_row[0]) if factor_row else None
    factor_max = _norm_date(factor_row[1]) if factor_row else None

    start_date = factor_min or daily_min
    if factor_max and daily_max:
        end_date = min(factor_max, daily_max)
    else:
        end_date = factor_max or daily_max

    if not start_date or not end_date:
        raise RuntimeError("无法确定默认分析日期范围")
    return start_date, end_date


def _load_base_data(
    market_db: Path,
    start_date: str,
    end_date: str,
) -> pd.DataFrame:
    conn = sqlite3.connect(str(market_db))
    try:
        sql = """
            SELECT
                d.ts_code,
                d.trade_date,
                d.open,
                d.close,
                d.high,
                d.low,
                d.vol,
                d.amount,
                d.pct_chg,
                b.name,
                b.industry,
                b.list_date
            FROM stock_daily d
            JOIN stock_basic b ON d.ts_code = b.ts_code
            WHERE d.trade_date <= ?
              AND (
                    d.ts_code LIKE '600%.SH' OR d.ts_code LIKE '601%.SH'
                 OR d.ts_code LIKE '603%.SH' OR d.ts_code LIKE '605%.SH'
                 OR d.ts_code LIKE '000%.SZ' OR d.ts_code LIKE '001%.SZ'
                 OR d.ts_code LIKE '002%.SZ' OR d.ts_code LIKE '003%.SZ'
              )
            ORDER BY d.ts_code, d.trade_date
        """
        df = pd.read_sql(sql, conn, params=(end_date,))
    finally:
        conn.close()

    if df.empty:
        return df

    for col in ("open", "close", "high", "low", "vol", "amount", "pct_chg"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df["trade_date"] = df["trade_date"].astype(str)
    df["list_date"] = df["list_date"].astype(str)

    # legacy family filter: static ST / new-stock / main-board rule
    df = df[~df["name"].astype(str).str.contains("ST|st|退", na=False)].copy()

    today = datetime.strptime(_today_yyyymmdd(), "%Y%m%d")
    min_list_date = (today - timedelta(days=60)).strftime("%Y%m%d")
    normalized_list_date = df["list_date"].str.replace("-", "", regex=False).str.slice(0, 8)
    keep_mask = normalized_list_date.isna() | (normalized_list_date == "None") | (normalized_list_date < min_list_date)
    df = df[keep_mask].copy()

    # keep rows with enough prehistory for rolling factors
    # load full history <= end_date, then cut to analysis start later
    df = df.sort_values(["ts_code", "trade_date"]).reset_index(drop=True)
    return df


def _compute_consecutive_up_days(pct_chg: pd.Series) -> pd.Series:
    out: List[int] = []
    streak = 0
    for value in pct_chg.fillna(0.0).tolist():
        if value > 0:
            streak += 1
        else:
            streak = 0
        out.append(streak)
    return pd.Series(out, index=pct_chg.index, dtype=float)


def _compute_legacy_opt_factors(df: pd.DataFrame, period: int) -> pd.DataFrame:
    x = df.copy()
    grouped = x.groupby("ts_code", sort=False)

    x["ma5"] = grouped["close"].transform(lambda s: s.rolling(5).mean())
    x["ma10"] = grouped["close"].transform(lambda s: s.rolling(10).mean())
    x["ma20"] = grouped["close"].transform(lambda s: s.rolling(20).mean())

    x["high20"] = grouped["high"].transform(lambda s: s.rolling(20).max())
    x["low20"] = grouped["low"].transform(lambda s: s.rolling(20).min())

    ma_score = np.select(
        [
            (x["close"] > x["ma5"]) & (x["ma5"] > x["ma10"]) & (x["ma10"] > x["ma20"]),
            (x["close"] > x["ma5"]) & (x["ma5"] > x["ma10"]),
            (x["close"] > x["ma5"]),
            (x["close"] < x["ma5"]) & (x["ma5"] < x["ma10"]) & (x["ma10"] < x["ma20"]),
        ],
        [40.0, 30.0, 20.0, 5.0],
        default=15.0,
    )
    strength_score = np.where(
        (x["high20"].notna()) & (x["low20"].notna()) & ((x["high20"] - x["low20"]).abs() > 1e-12),
        (x["close"] - x["low20"]) / (x["high20"] - x["low20"]) * 30.0,
        np.nan,
    )
    ma_diff = (x["ma5"] - x["ma20"]).abs() / x["ma20"] * 100.0
    divergence_score = np.select(
        [ma_diff > 5, ma_diff > 3, ma_diff > 1],
        [30.0, 25.0, 20.0],
        default=15.0,
    )
    x["trend_score"] = ma_score + strength_score + divergence_score

    return_20 = x["close"] / grouped["close"].shift(19) - 1.0
    return_20 = return_20 * 100.0
    return_score = np.select(
        [return_20 > 20, return_20 > 10, return_20 > 5, return_20 > 0, return_20 > -5],
        [35.0, 30.0, 25.0, 20.0, 15.0],
        default=10.0,
    )

    delta = grouped["close"].diff()
    gain = delta.where(delta > 0, 0.0)
    loss = (-delta.where(delta < 0, 0.0))
    avg_gain = gain.groupby(x["ts_code"], sort=False).transform(lambda s: s.rolling(14).mean())
    avg_loss = loss.groupby(x["ts_code"], sort=False).transform(lambda s: s.rolling(14).mean())
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    rsi_score = np.select(
        [
            (rsi >= 50) & (rsi <= 65),
            ((rsi >= 45) & (rsi < 50)) | ((rsi > 65) & (rsi <= 70)),
            (rsi >= 40) & (rsi < 45),
            rsi > 70,
        ],
        [35.0, 30.0, 25.0, 20.0],
        default=15.0,
    )

    up_days = grouped["pct_chg"].transform(_compute_consecutive_up_days)
    up_days_score = np.select(
        [up_days >= 5, up_days >= 3, up_days >= 2],
        [30.0, 25.0, 20.0],
        default=15.0,
    )
    x["momentum_score"] = return_score + rsi_score + up_days_score

    vol_ma5 = grouped["vol"].transform(lambda s: s.rolling(5).mean())
    vol_ma20 = grouped["vol"].transform(lambda s: s.rolling(20).mean())
    vol_ratio = x["vol"] / vol_ma20
    vol_expand_score = np.select(
        [vol_ratio > 2, vol_ratio > 1.5, vol_ratio > 1.2, vol_ratio > 1],
        [35.0, 30.0, 25.0, 20.0],
        default=15.0,
    )

    price_change = x["close"] / grouped["close"].shift(4) - 1.0
    vol_change = x["vol"] / grouped["vol"].shift(4) - 1.0
    vp_score = np.select(
        [
            (price_change > 0) & (vol_change > 0),
            (price_change > 0) & (vol_change < 0),
            (price_change < 0) & (vol_change > 0),
        ],
        [35.0, 20.0, 25.0],
        default=15.0,
    )

    vol_slope = (vol_ma5 - vol_ma5.groupby(x["ts_code"], sort=False).shift(9)) / vol_ma5.groupby(x["ts_code"], sort=False).shift(9) * 100.0
    vol_trend_score = np.select(
        [vol_slope > 20, vol_slope > 10, vol_slope > 0],
        [30.0, 25.0, 20.0],
        default=15.0,
    )
    x["volume_score"] = vol_expand_score + vp_score + vol_trend_score

    pullback_from_high = (x["high20"] - x["close"]) / x["high20"] * 100.0
    pullback_score = np.select(
        [
            (pullback_from_high >= 5) & (pullback_from_high <= 15),
            (pullback_from_high >= 3) & (pullback_from_high < 5),
            (pullback_from_high > 15) & (pullback_from_high <= 25),
            pullback_from_high < 3,
        ],
        [40.0, 35.0, 30.0, 15.0],
        default=20.0,
    )

    dist_to_ma20 = (x["close"] - x["ma20"]) / x["ma20"] * 100.0
    support_score = np.select(
        [
            (dist_to_ma20 >= 0) & (dist_to_ma20 <= 5),
            (dist_to_ma20 >= -5) & (dist_to_ma20 < 0),
            (dist_to_ma20 > 5) & (dist_to_ma20 <= 10),
        ],
        [30.0, 25.0, 20.0],
        default=15.0,
    )

    returns = grouped["close"].pct_change()
    volatility = returns.groupby(x["ts_code"], sort=False).transform(lambda s: s.rolling(20).std()) * 100.0
    vol_score = np.select(
        [
            (volatility >= 2) & (volatility <= 4),
            (volatility >= 1) & (volatility < 2),
            (volatility > 4) & (volatility <= 6),
        ],
        [30.0, 25.0, 20.0],
        default=15.0,
    )
    x["pullback_score"] = pullback_score + support_score + vol_score

    industry_score = np.where(
        x["industry"].isin(HOT_INDUSTRIES),
        35.0,
        np.where(x["industry"].isin(NEUTRAL_INDUSTRIES), 25.0, 20.0),
    )
    name_score = np.where(
        x["name"].astype(str).str.contains("ST|st|退|\\*ST", na=False),
        0.0,
        30.0,
    )
    list_date = pd.to_datetime(x["list_date"].str.slice(0, 8), format="%Y%m%d", errors="coerce")
    days_listed = (pd.Timestamp(datetime.now().date()) - list_date).dt.days
    list_score = np.select(
        [days_listed > 365 * 3, days_listed > 365 * 2, days_listed > 365],
        [35.0, 30.0, 25.0],
        default=15.0,
    )
    list_score = np.where(days_listed.isna(), 25.0, list_score)
    x["fundamental_score"] = industry_score + name_score + list_score

    x["future_return"] = grouped["close"].pct_change(period).shift(-period)

    valid_history = (
        x["ma20"].notna()
        & grouped["close"].shift(19).notna()
        & grouped["close"].shift(4).notna()
        & vol_ma20.notna()
        & vol_ma5.groupby(x["ts_code"], sort=False).shift(9).notna()
        & rsi.notna()
        & volatility.notna()
        & x["future_return"].notna()
    )
    x["is_valid_factor_row"] = valid_history
    return x


def _calc_ic_statistics(ic_df: pd.DataFrame) -> Dict[str, float]:
    if ic_df.empty:
        return {}

    ic_mean = float(ic_df["ic"].mean())
    ic_std = float(ic_df["ic"].std())
    ic_ir = float(ic_mean / ic_std) if ic_std > 0 else 0.0
    ic_abs_mean = float(ic_df["ic"].abs().mean())
    ic_positive_ratio = float((ic_df["ic"] > 0).mean())
    ic_effective_ratio = float((ic_df["ic"].abs() > 0.05).mean())
    ic_strong_effective_ratio = float((ic_df["ic"].abs() > 0.10).mean())
    t_stat = float(ic_mean / (ic_std / np.sqrt(len(ic_df)))) if ic_std > 0 else 0.0

    return {
        "ic_mean": ic_mean,
        "ic_std": ic_std,
        "ic_ir": ic_ir,
        "ic_abs_mean": ic_abs_mean,
        "ic_positive_ratio": ic_positive_ratio,
        "ic_effective_ratio": ic_effective_ratio,
        "ic_strong_effective_ratio": ic_strong_effective_ratio,
        "t_stat": t_stat,
        "sample_count": int(len(ic_df)),
    }


def _calculate_stock_factor_ic(
    factor_df: pd.DataFrame,
    factor_name: str,
    min_samples_per_day: int = 30,
) -> pd.DataFrame:
    records: List[Dict[str, object]] = []
    for trade_date, group in factor_df.groupby("trade_date", sort=True):
        pair = group[[factor_name, "future_return"]].dropna()
        if len(pair) < min_samples_per_day:
            continue
        ic, p_value = _safe_spearman(pair[factor_name], pair["future_return"])
        if pd.isna(ic):
            continue
        records.append(
            {
                "date": trade_date,
                "ic": float(ic),
                "p_value": float(p_value),
                "sample_size": int(len(pair)),
            }
        )
    return pd.DataFrame(records)


def _layer_analysis(
    factor_df: pd.DataFrame,
    factor_name: str,
    n_layers: int = 5,
    min_samples_per_day: int = 100,
) -> pd.DataFrame:
    layer_returns: List[Dict[str, object]] = []

    for trade_date, group in factor_df.groupby("trade_date", sort=True):
        day = group[[factor_name, "future_return"]].dropna().copy()
        if len(day) < min_samples_per_day:
            continue
        try:
            day["layer"] = pd.qcut(day[factor_name], n_layers, labels=False, duplicates="drop")
        except Exception:
            continue
        for layer in sorted(day["layer"].dropna().unique().tolist()):
            layer_data = day[day["layer"] == layer]
            if layer_data.empty:
                continue
            layer_returns.append(
                {
                    "date": trade_date,
                    "layer": int(layer),
                    "avg_return": float(layer_data["future_return"].mean()),
                    "count": int(len(layer_data)),
                }
            )

    if not layer_returns:
        return pd.DataFrame()

    layer_df = pd.DataFrame(layer_returns)
    summary = layer_df.groupby("layer")["avg_return"].agg(["mean", "std", "count"])
    summary["cumulative_return"] = (1 + summary["mean"]).pow(layer_df["date"].nunique()) - 1
    return summary


def _validate_factor(
    factor_df: pd.DataFrame,
    factor_name: str,
) -> Dict[str, object]:
    ic_df = _calculate_stock_factor_ic(factor_df, factor_name)
    ic_stats = _calc_ic_statistics(ic_df)
    layer_summary = _layer_analysis(factor_df, factor_name)

    if not ic_stats:
        return {
            "factor_name": factor_name,
            "ic_mean": math.nan,
            "ic_ir": math.nan,
            "ic_positive_ratio": math.nan,
            "ic_effective_ratio": math.nan,
            "t_stat": math.nan,
            "top_layer_return": None,
            "bottom_layer_return": None,
            "is_effective": False,
            "recommendation": "无有效样本",
        }

    is_effective = True
    if abs(ic_stats["ic_mean"]) <= 0.01:
        is_effective = False
    if ic_stats["ic_positive_ratio"] <= 0.55:
        is_effective = False
    if abs(ic_stats["t_stat"]) < 2:
        is_effective = False
    if not layer_summary.empty:
        if float(layer_summary.iloc[-1]["mean"]) <= float(layer_summary.iloc[0]["mean"]):
            is_effective = False

    return {
        "factor_name": factor_name,
        "ic_mean": float(ic_stats["ic_mean"]),
        "ic_ir": float(ic_stats["ic_ir"]),
        "ic_positive_ratio": float(ic_stats["ic_positive_ratio"]),
        "ic_effective_ratio": float(ic_stats["ic_effective_ratio"]),
        "t_stat": float(ic_stats["t_stat"]),
        "top_layer_return": float(layer_summary.iloc[-1]["mean"]) if not layer_summary.empty else None,
        "bottom_layer_return": float(layer_summary.iloc[0]["mean"]) if not layer_summary.empty else None,
        "is_effective": bool(is_effective),
        "recommendation": "保留" if is_effective else "删除或优化",
    }


def _calc_correlation_matrix(
    factor_df: pd.DataFrame,
    factor_names: List[str],
) -> pd.DataFrame:
    merged = factor_df[factor_names].dropna()
    if merged.empty:
        return pd.DataFrame()
    return merged.corr(method="spearman")


def _identify_redundant_factors(
    correlation_matrix: pd.DataFrame,
    threshold: float = 0.7,
) -> List[Tuple[str, str, float]]:
    redundant_pairs: List[Tuple[str, str, float]] = []
    if correlation_matrix.empty:
        return redundant_pairs

    for i in range(len(correlation_matrix)):
        for j in range(i + 1, len(correlation_matrix)):
            factor1 = str(correlation_matrix.index[i])
            factor2 = str(correlation_matrix.columns[j])
            corr = float(correlation_matrix.iloc[i, j])
            if abs(corr) > threshold:
                redundant_pairs.append((factor1, factor2, corr))
    return redundant_pairs


def _build_report(
    ic_results: pd.DataFrame,
    validation_results: pd.DataFrame,
    correlation_matrix: pd.DataFrame,
    redundant_pairs: List[Tuple[str, str, float]],
    meta: Dict[str, object],
) -> str:
    lines: List[str] = []
    lines.extend(
        [
            "=" * 80,
            "legacy_opt 标准 IC 分析报告",
            f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"分析区间: {meta['start_date']} ~ {meta['end_date']}",
            f"收益周期: {meta['period']}日 future_return",
            f"有效主板样本行数: {meta['row_count']}",
            "=" * 80,
            "",
            "一、IC统计",
            "-" * 80,
        ]
    )

    if not ic_results.empty:
        lines.append(ic_results.to_string(index=False))
    else:
        lines.append("无IC统计结果")

    lines.extend(["", "二、因子有效性验证", "-" * 80])
    if not validation_results.empty:
        lines.append(validation_results.to_string(index=False))
    else:
        lines.append("无验证结果")

    lines.extend(["", "三、因子相关性矩阵", "-" * 80])
    if not correlation_matrix.empty:
        lines.append(correlation_matrix.to_string())
        if redundant_pairs:
            lines.append("")
            lines.append("冗余因子对（相关系数 > 0.7）:")
            for factor1, factor2, corr in redundant_pairs:
                lines.append(f"  {factor1} <-> {factor2}: {corr:.3f}")
    else:
        lines.append("无相关性矩阵")

    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run standard IC analysis for legacy_opt.")
    parser.add_argument("--market-db", type=str, default="data/database/quant_system.db")
    parser.add_argument("--start-date", type=str, default=None)
    parser.add_argument("--end-date", type=str, default=None)
    parser.add_argument("--period", type=int, default=5)
    parser.add_argument("--factors", type=str, default="trend_score,momentum_score,volume_score,pullback_score")
    parser.add_argument("--report-dir", type=str, default="reports")
    args = parser.parse_args()

    market_db = ROOT / args.market_db
    report_dir = ROOT / args.report_dir
    report_dir.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(market_db))
    try:
        default_start, default_end = _load_default_range(conn)
    finally:
        conn.close()

    start_date = _norm_date(args.start_date) or default_start
    end_date = _norm_date(args.end_date) or default_end
    period = max(int(args.period), 1)
    factor_names = [item.strip() for item in str(args.factors).split(",") if item.strip()]
    if not factor_names:
        factor_names = list(DEFAULT_FACTOR_NAMES)

    base_df = _load_base_data(market_db=market_db, start_date=start_date, end_date=end_date)
    if base_df.empty:
        raise SystemExit("未加载到可分析的主板日线数据")

    factor_df = _compute_legacy_opt_factors(base_df, period=period)
    factor_df = factor_df[
        (factor_df["trade_date"] >= start_date)
        & (factor_df["trade_date"] <= end_date)
        & factor_df["is_valid_factor_row"]
    ].copy()
    if factor_df.empty:
        raise SystemExit("legacy_opt 在当前区间无有效因子样本")

    ic_rows: List[Dict[str, object]] = []
    validation_rows: List[Dict[str, object]] = []
    effective_ic_stats: Dict[str, Dict[str, float]] = {}
    for factor_name in factor_names:
        ic_df = _calculate_stock_factor_ic(factor_df, factor_name)
        ic_stats = _calc_ic_statistics(ic_df)
        if ic_stats:
            ic_rows.append(
                {
                    "factor_name": factor_name,
                    "ic_mean": ic_stats["ic_mean"],
                    "ic_std": ic_stats["ic_std"],
                    "ic_ir": ic_stats["ic_ir"],
                    "ic_abs_mean": ic_stats["ic_abs_mean"],
                    "ic_positive_ratio": ic_stats["ic_positive_ratio"],
                    "ic_effective_ratio": ic_stats["ic_effective_ratio"],
                    "ic_strong_effective_ratio": ic_stats["ic_strong_effective_ratio"],
                    "t_stat": ic_stats["t_stat"],
                    "sample_count": ic_stats["sample_count"],
                }
            )

        validation = _validate_factor(factor_df, factor_name)
        validation_rows.append(validation)
        if validation["is_effective"]:
            effective_ic_stats[factor_name] = {
                "ic_mean": float(validation["ic_mean"]),
                "ic_ir": float(validation["ic_ir"]),
            }

    ic_results = pd.DataFrame(ic_rows)
    validation_results = pd.DataFrame(validation_rows)
    correlation_matrix = _calc_correlation_matrix(factor_df, factor_names)
    redundant_pairs = _identify_redundant_factors(correlation_matrix, threshold=0.7)

    meta = {
        "start_date": start_date,
        "end_date": end_date,
        "period": period,
        "row_count": int(len(factor_df)),
        "factor_names": factor_names,
    }

    report = _build_report(
        ic_results=ic_results,
        validation_results=validation_results,
        correlation_matrix=correlation_matrix,
        redundant_pairs=redundant_pairs,
        meta=meta,
    )

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    txt_path = report_dir / f"legacy_opt_standard_ic_{timestamp}.txt"
    json_path = report_dir / f"legacy_opt_standard_ic_{timestamp}.json"
    txt_path.write_text(report, encoding="utf-8")

    payload: Dict[str, object] = {
        "meta": meta,
        "ic_results": json.loads(ic_results.to_json(orient="records", force_ascii=False)) if not ic_results.empty else [],
        "validation_results": json.loads(validation_results.to_json(orient="records", force_ascii=False))
        if not validation_results.empty
        else [],
        "correlation_matrix": json.loads(correlation_matrix.reset_index().to_json(orient="records", force_ascii=False))
        if not correlation_matrix.empty
        else [],
        "redundant_pairs": [
            {"factor1": f1, "factor2": f2, "correlation": corr}
            for f1, f2, corr in redundant_pairs
        ],
    }

    if effective_ic_stats:
        optimizer = FactorWeightOptimizer()
        payload["weights_by_ic"] = optimizer.calculate_weights_by_ic(effective_ic_stats)
        payload["weights_by_ic_ir"] = optimizer.calculate_weights_by_ic_ir(effective_ic_stats)

    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"report: {txt_path}")
    print(f"json: {json_path}")
    print(report)


if __name__ == "__main__":
    main()
