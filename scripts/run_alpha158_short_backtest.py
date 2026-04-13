# -*- coding: utf-8 -*-
"""
Alpha158 选股短时窗回测（与菜单「每日选股→Alpha158」一致）

规则：
- 信号日 T 日收盘后选股（使用 end_date=T 的日线，与实盘盘前一致）；
- 买入价：T+1 开盘价；
- 卖出价：T+h 日收盘价（h=2/3/5 表示持有到第 h 个交易日收盘）。

用法示例：
  python scripts/run_alpha158_short_backtest.py
  python scripts/run_alpha158_short_backtest.py --start 20251101 --end 20260131 --top-n 5
  python scripts/run_alpha158_short_backtest.py --signal-days 40 --horizons 3 5

说明：
- total_return 为对每笔独立交易收益率连乘，不等价于单账户净值，仅作粗参考；
- 样本短、Sharpe 年化波动大，请结合均值/胜率/分位数解读。
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
from pathlib import Path
from typing import Dict, List

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _load_qfp():
    """加载 qlib_full_optimize_pipeline 中的回测工具（避免重复粘贴大段代码）。"""
    path = ROOT / "scripts" / "qlib_full_optimize_pipeline.py"
    spec = importlib.util.spec_from_file_location("qfp_alpha158_bt", path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def load_trade_dates(db) -> List[str]:
    conn = db._get_connection()
    sql = "SELECT DISTINCT trade_date FROM stock_daily ORDER BY trade_date"
    dates = [str(row[0]) for row in conn.execute(sql).fetchall()]
    conn.close()
    return dates


def pick_signal_dates(
    trade_dates: List[str],
    start: str,
    end: str,
    horizon_max: int,
    signal_days: int,
) -> List[str]:
    """在 [start,end] 内取信号日；若 signal_days>0 则只保留区间内最后 signal_days 个交易日。"""
    selected = [d for d in trade_dates if start <= d <= end]
    if len(selected) <= horizon_max:
        return []
    selected = selected[: len(selected) - horizon_max]
    if signal_days > 0 and len(selected) > signal_days:
        selected = selected[-signal_days:]
    return selected


def per_trade_detail(
    rec_df: pd.DataFrame,
    db,
    trade_dates: List[str],
    horizon: int,
) -> pd.DataFrame:
    """逐笔交易明细，便于导出与分位数分析。"""
    if rec_df.empty:
        return pd.DataFrame()

    date_to_idx = {d: i for i, d in enumerate(trade_dates)}
    rec = rec_df.copy()
    rec["rec_idx"] = rec["rec_date"].map(date_to_idx)
    rec = rec.dropna(subset=["rec_idx"])
    rec["rec_idx"] = rec["rec_idx"].astype(int)
    rec = rec[rec["rec_idx"] + horizon < len(trade_dates)].copy()
    if rec.empty:
        return pd.DataFrame()

    symbols = sorted(rec["ts_code"].unique().tolist())
    min_idx = int(rec["rec_idx"].min() + 1)
    max_idx = int(rec["rec_idx"].max() + horizon)
    date_min = trade_dates[min_idx]
    date_max = trade_dates[max_idx]

    conn = db._get_connection()
    ph = ",".join(["?"] * len(symbols))
    sql = f"""
        SELECT ts_code, trade_date, open, close, high, low
        FROM stock_daily
        WHERE ts_code IN ({ph})
          AND trade_date >= ? AND trade_date <= ?
    """
    price_df = pd.read_sql(sql, conn, params=symbols + [date_min, date_max])
    conn.close()
    if price_df.empty:
        return pd.DataFrame()

    for col in ("open", "close", "high", "low"):
        price_df[col] = pd.to_numeric(price_df[col], errors="coerce")

    price_map = {}
    for _, row in price_df.iterrows():
        price_map[(str(row["ts_code"]), str(row["trade_date"]))] = {
            "open": row["open"],
            "close": row["close"],
            "high": row["high"],
            "low": row["low"],
        }

    rows = []
    for _, row in rec.iterrows():
        symbol = row["ts_code"]
        rec_idx = int(row["rec_idx"])
        buy_date = trade_dates[rec_idx + 1]
        sell_date = trade_dates[rec_idx + horizon]
        buy_price = price_map.get((symbol, buy_date), {}).get("open")
        sell_price = price_map.get((symbol, sell_date), {}).get("close")
        if buy_price and sell_price and float(buy_price) > 0:
            ret = (float(sell_price) - float(buy_price)) / float(buy_price)
            rows.append(
                {
                    "rec_date": row["rec_date"],
                    "ts_code": symbol,
                    "rank": row.get("rank"),
                    "score": row.get("score"),
                    "h": horizon,
                    "ret": ret,
                }
            )
    return pd.DataFrame(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="Alpha158 短时窗选股回测")
    parser.add_argument(
        "--start",
        default="",
        help="信号日开始 YYYYMMDD，默认：数据库内倒数第 80 个交易日附近（见 --signal-days）",
    )
    parser.add_argument("--end", default="", help="信号日结束 YYYYMMDD，默认：数据库最新日")
    parser.add_argument(
        "--signal-days",
        type=int,
        default=45,
        help="短时窗：在 [start,end] 截断后只保留最后 N 个交易日作为信号日（默认 45）",
    )
    parser.add_argument("--top-n", type=int, default=5, help="每日最多取前 N 只（默认 5）")
    parser.add_argument(
        "--horizons",
        type=int,
        nargs="+",
        default=[3, 5],
        help="持有期（交易日），默认 3 5",
    )
    parser.add_argument(
        "--out-json",
        default="",
        help="可选：将摘要写入 output/alpha158_short_backtest.json",
    )
    args = parser.parse_args()

    from src.core.config import ConfigManager
    from src.core.database import DatabaseManager

    qfp = _load_qfp()

    config = ConfigManager()
    db = DatabaseManager(config)
    trade_dates = load_trade_dates(db)
    if len(trade_dates) < 20:
        print("数据库交易日过少，无法回测")
        return

    end = args.end.strip() or trade_dates[-1]
    start = args.start.strip()
    if not start:
        # 默认：从 end 往前覆盖约 signal_days + max_h + 缓冲
        max_h = max(args.horizons)
        need = args.signal_days + max_h + 5
        idx = max(0, len(trade_dates) - 1 - need)
        start = trade_dates[idx]

    horizon_max = max(args.horizons)
    signal_dates = pick_signal_dates(trade_dates, start, end, horizon_max, args.signal_days)
    if not signal_dates:
        print("信号日为空：请放宽日期区间或减小 --signal-days / --horizons")
        return

    print("=" * 60)
    print("Alpha158 短时窗回测")
    print(f"  数据区间: {trade_dates[0]} ~ {trade_dates[-1]}")
    print(f"  信号区间: {signal_dates[0]} ~ {signal_dates[-1]}  （共 {len(signal_dates)} 个交易日）")
    print(f"  每日取前 {args.top_n} 只 | 持有期: {args.horizons}")
    print("=" * 60)

    overrides: Dict = {
        "stock_selection.strategy_profile": "alpha158",
        "stock_selection.save_factor_values": False,
        "stock_selection.min_score": 0.0,
    }

    rec_df = qfp.run_selection_for_dates(
        signal_dates,
        db,
        config_overrides=overrides,
        top_n=args.top_n,
    )

    non_empty_days = rec_df["rec_date"].nunique() if not rec_df.empty else 0
    print(f"\n  有推荐记录交易日: {non_empty_days}/{len(signal_dates)}")
    print(f"  推荐条数合计: {len(rec_df)}")

    summaries = []
    for h in args.horizons:
        res = qfp.evaluate_recommendations(rec_df, db, trade_dates, h)
        qfp.print_backtest_result(f"Alpha158 T+1 入 T+{h} 出", res, h)
        detail = per_trade_detail(rec_df, db, trade_dates, h)
        if not detail.empty:
            rets = detail["ret"]
            print(
                f"    分位: P25={_quantile_np(rets, 0.25):.4f}  P50={_quantile_np(rets, 0.50):.4f}  "
                f"P75={_quantile_np(rets, 0.75):.4f}"
            )
        summaries.append(
            {
                "horizon": h,
                "sample_count": res.sample_count,
                "trade_days": res.trade_days,
                "mean_return": res.mean_return,
                "median_return": res.median_return,
                "win_rate": res.win_rate,
                "sharpe_ratio": res.sharpe_ratio,
                "max_drawdown": res.max_drawdown,
                "day_mean_return": res.day_mean_return,
                "day_win_rate": res.day_win_rate,
            }
        )

    print("\n" + "-" * 60)
    print("效果解读提示：")
    print("  - 均值/胜率：单笔样本越多越稳；短窗易受板块与行情阶段影响。")
    print("  - Sharpe：按「每日等权平均收益」年化，样本日少时波动极大。")
    print("  - total_return（连乘）：多笔并行持仓的近似，勿等同真实账户复利。")
    print("-" * 60)

    out_path = args.out_json.strip()
    if not out_path:
        out_path = str(ROOT / "output" / "alpha158_short_backtest.json")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    payload = {
        "signal_start": signal_dates[0],
        "signal_end": signal_dates[-1],
        "signal_days": len(signal_dates),
        "top_n": args.top_n,
        "horizons": summaries,
        "recommendation_rows": int(len(rec_df)),
        "days_with_picks": int(non_empty_days),
    }
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"\n  摘要已写入: {out_path}")


def _quantile_np(s: pd.Series, q: float) -> float:
    if s.empty:
        return 0.0
    return float(np.quantile(s.values, q))


if __name__ == "__main__":
    main()
