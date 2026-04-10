# -*- coding: utf-8 -*-
"""
突破策略选股名单：使用 Baostock 下载 5 分钟 K 线，写入 data/intraday_cache。

与 Tushare 版脚本口径一致：读同一份 CSV，按 6 位代码合并 watch_date～watch_date+extend_days，
缓存文件名与 IntradayDataDownloader 风格对齐：{symbol}_{start}_{end}_5MIN.parquet

前置:
  pip install baostock
  python scripts/export_breakout_watchlist_history.py

用法:
  python scripts/download_breakout_watchlist_minute_baostock.py
  python scripts/download_breakout_watchlist_minute_baostock.py --max-symbols 5 --extend-days 7
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd

from src.core.logger import get_logger
from src.modules.backtest.batch_intraday_downloader import BatchIntradayDownloader

logger = get_logger("download_breakout_watchlist_minute_baostock")

CACHE_DIR = "data/intraday_cache"
FREQ_TAG = "5MIN"


def _parse_row_date(val) -> datetime.date | None:
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None
    s = str(val).strip().replace("-", "")[:8]
    if len(s) != 8 or not s.isdigit():
        return None
    return datetime.strptime(s, "%Y%m%d").date()


def _to_iso(d: datetime.date) -> str:
    return d.strftime("%Y-%m-%d")


def _normalize_for_cache(df: pd.DataFrame) -> pd.DataFrame:
    """与 IntradayDataDownloader 输出尽量一致，便于下游复用。"""
    if df.empty:
        return df
    out = df.copy()
    if "trade_time" in out.columns:
        out["trade_time"] = pd.to_datetime(out["trade_time"])
    if "trade_date" in out.columns:
        # 统一为 date 类型
        td = out["trade_date"]
        if td.dtype == object:
            out["trade_date"] = pd.to_datetime(td, errors="coerce").dt.date
    if "vol" not in out.columns and "volume" in out.columns:
        out["vol"] = out["volume"]
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="突破选股名单 — Baostock 5 分钟")
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    default_csv = os.path.join(root, "data", "reports", "breakout_watchlist_history_latest.csv")
    parser.add_argument("--csv", default=default_csv, help="选股导出 CSV")
    parser.add_argument("--extend-days", type=int, default=7, help="自信号日起向后自然日数")
    parser.add_argument("--max-symbols", type=int, default=0, help="仅处理前 N 个标的，0 为全部")
    parser.add_argument("--sleep", type=float, default=0.35, help="每只股票请求间隔（秒）")
    args = parser.parse_args()

    if not os.path.isfile(args.csv):
        print(f"找不到文件: {args.csv}")
        sys.exit(1)

    df = pd.read_csv(args.csv, encoding="utf-8-sig")
    if df.empty:
        print("CSV 为空")
        sys.exit(0)
    if "ts_code" not in df.columns or "watch_date" not in df.columns:
        print("CSV 需包含: ts_code, watch_date")
        sys.exit(1)

    ranges: dict[str, tuple[datetime.date, datetime.date]] = {}
    for _, row in df.iterrows():
        code = str(row["ts_code"]).strip()
        sym = code.split(".")[0]
        d0 = _parse_row_date(row["watch_date"])
        if not d0:
            continue
        d1 = d0 + timedelta(days=max(1, args.extend_days))
        if sym not in ranges:
            ranges[sym] = (d0, d1)
        else:
            a, b = ranges[sym]
            ranges[sym] = (min(a, d0), max(b, d1))

    if not ranges:
        print("没有可解析的 watch_date")
        sys.exit(0)

    items = sorted(ranges.items(), key=lambda x: x[0])
    if args.max_symbols and args.max_symbols > 0:
        items = items[: args.max_symbols]

    os.makedirs(os.path.join(root, CACHE_DIR), exist_ok=True)

    downloader = BatchIntradayDownloader()
    if downloader.bs is None:
        print("错误: baostock 未安装或未登录成功，请执行: pip install baostock")
        sys.exit(1)

    ok = 0
    fail = 0
    try:
        print(f"待下载标的: {len(items)}（CSV 行数 {len(df)}）")
        for i, (sym, (start_d, end_d)) in enumerate(items, 1):
            start_iso = _to_iso(start_d)
            end_iso = _to_iso(end_d)
            raw = downloader.download_intraday_data(sym, start_iso, end_iso)
            if raw is None or raw.empty:
                logger.warning("无数据: %s %s~%s", sym, start_iso, end_iso)
                fail += 1
                time.sleep(args.sleep)
                continue
            out = _normalize_for_cache(raw)
            cache_key = f"{sym}_{start_iso}_{end_iso}_{FREQ_TAG}"
            path = os.path.join(root, CACHE_DIR, f"{cache_key}.parquet")
            try:
                out.to_parquet(path, index=False)
                print(f"  [{i}/{len(items)}] {sym} -> {len(out)} 条 {path}")
                ok += 1
            except Exception as e:
                logger.error("写入失败 %s: %s", path, e)
                fail += 1
            time.sleep(args.sleep)
    finally:
        downloader.close()

    print(f"\n完成: 成功 {ok}，失败 {fail}，目录 {os.path.join(root, CACHE_DIR)}")


if __name__ == "__main__":
    main()
