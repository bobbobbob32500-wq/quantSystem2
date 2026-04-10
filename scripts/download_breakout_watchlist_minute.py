# -*- coding: utf-8 -*-
"""
在突破策略导出选股名单后，按「信号日→若干自然日」窗口补齐分钟线（Tushare stk_mins），
结果写入 data/intraday_cache 下 parquet，供 IntradayDataDownloader 复用。

前置:
  先运行 scripts/export_breakout_watchlist_history.py 生成
  data/reports/breakout_watchlist_history_latest.csv

用法:
  python scripts/download_breakout_watchlist_minute.py
  python scripts/download_breakout_watchlist_minute.py --csv data/reports/breakout_watchlist_history_latest.csv --extend-days 7 --freq 1min

说明:
  - Tushare 分钟接口有频控与历史长度限制，仅下载选股相关区间，不拉全市场。
  - 同代码多信号日会合并为一条时间范围，减少重复请求。
  - 若无 stk_mins 权限，请改用 Baostock 5 分钟：download_breakout_watchlist_minute_baostock.py
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd

from src.core.config import ConfigManager
from src.core.logger import get_logger
from src.modules.backtest.intraday_data_downloader import IntradayDataDownloader

logger = get_logger("download_breakout_watchlist_minute")


def _parse_row_date(val) -> datetime.date | None:
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None
    s = str(val).strip().replace("-", "")[:8]
    if len(s) != 8 or not s.isdigit():
        return None
    return datetime.strptime(s, "%Y%m%d").date()


def _to_iso(d: datetime.date) -> str:
    return d.strftime("%Y-%m-%d")


def main() -> None:
    parser = argparse.ArgumentParser(description="突破选股名单补充分钟数据")
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    default_csv = os.path.join(root, "data", "reports", "breakout_watchlist_history_latest.csv")
    parser.add_argument("--csv", default=default_csv, help="选股导出 CSV 路径")
    parser.add_argument(
        "--extend-days",
        type=int,
        default=7,
        help="自信号日起向后覆盖的自然日数（含确认日 T+1 等，默认 7）",
    )
    parser.add_argument("--freq", default="1min", help="分钟周期，如 1min / 5min")
    parser.add_argument(
        "--max-symbols",
        type=int,
        default=0,
        help="仅调试用：最多处理前 N 个合并后的标的（0 表示不限制）",
    )
    args = parser.parse_args()

    if not os.path.isfile(args.csv):
        print(f"找不到文件: {args.csv}\n请先运行 export_breakout_watchlist_history.py")
        sys.exit(1)

    config = ConfigManager()
    token = config.get("data_source.tushare_token", "")
    if not token or "your_tushare_token" in str(token).lower():
        print("错误: 请在配置中设置有效的 data_source.tushare_token")
        sys.exit(1)

    df = pd.read_csv(args.csv, encoding="utf-8-sig")
    if df.empty:
        print("CSV 为空")
        sys.exit(0)

    if "ts_code" not in df.columns or "watch_date" not in df.columns:
        print("CSV 需包含列: ts_code, watch_date")
        sys.exit(1)

    # 按代码合并时间区间，减少 stk_mins 调用次数
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

    records = []
    for sym, (start_d, end_d) in items:
        records.append(
            {
                "symbol": sym,
                "selection_date": _to_iso(start_d),
                "sell_date": _to_iso(end_d),
            }
        )

    print(f"合并后待下载标的数: {len(records)}（原 CSV 行数 {len(df)}）")
    print("示例:", records[:3])

    dl = IntradayDataDownloader(token=token)
    out = dl.download_for_observation_pool(records, freq=args.freq, use_cache=True)
    print(f"\n完成，成功缓存 {len(out)} 只股票的分钟数据目录: {dl.cache_dir}")


if __name__ == "__main__":
    main()
