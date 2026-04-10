# -*- coding: utf-8 -*-
"""
审查：突破策略观察池（breakout_watchlist_history*.csv）中每一行 (watch_date, ts_code)
是否在 data/intraday_cache 中存在可覆盖该日期的分钟线缓存（parquet）。

缓存命名约定（与 IntradayDataDownloader / download_breakout_watchlist_minute 一致）：
  {6位数字代码}_{YYYY-MM-DD}_{YYYY-MM-DD}_{freq}.parquet
  例如 600000_2025-07-01_2025-07-08_1MIN.parquet

用法:
  python scripts/audit_breakout_watchlist_minute_coverage.py
  python scripts/audit_breakout_watchlist_minute_coverage.py --verify-rows
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from datetime import datetime
from typing import Dict, List, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd

# 600000_2025-07-01_2025-07-15_1MIN.parquet
FNAME_RE = re.compile(
    r"^(\d{6})_(\d{4}-\d{2}-\d{2})_(\d{4}-\d{2}-\d{2})_(.+)\.parquet$"
)


def _parse_watch_date(val) -> datetime.date | None:
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None
    s = str(val).strip().replace("-", "")[:8]
    if len(s) != 8 or not s.isdigit():
        return None
    return datetime.strptime(s, "%Y%m%d").date()


def load_cache_ranges(cache_dir: str) -> Dict[str, List[Tuple[datetime.date, datetime.date, str]]]:
    """symbol -> [(start, end, filepath), ...]"""
    out: Dict[str, List[Tuple[datetime.date, datetime.date, str]]] = {}
    if not os.path.isdir(cache_dir):
        return out
    for fn in os.listdir(cache_dir):
        if not fn.endswith(".parquet"):
            continue
        m = FNAME_RE.match(fn)
        if not m:
            continue
        sym, s1, s2, _freq = m.groups()
        d0 = datetime.strptime(s1, "%Y-%m-%d").date()
        d1 = datetime.strptime(s2, "%Y-%m-%d").date()
        path = os.path.join(cache_dir, fn)
        out.setdefault(sym, []).append((d0, d1, path))
    return out


def date_in_any_range(
    d: datetime.date, ranges: List[Tuple[datetime.date, datetime.date, str]]
) -> Tuple[bool, str | None]:
    for a, b, p in ranges:
        if a <= d <= b:
            return True, p
    return False, None


def verify_file_has_date(parquet_path: str, target_date: datetime.date) -> bool:
    try:
        df = pd.read_parquet(parquet_path, columns=["trade_time"])
    except Exception:
        try:
            df = pd.read_parquet(parquet_path)
        except Exception:
            return False
    if df.empty:
        return False
    tt = pd.to_datetime(df["trade_time"], errors="coerce")
    if hasattr(tt.dt, "date"):
        days = set(tt.dt.date.dropna().tolist())
    else:
        days = set()
    return target_date in days


def main() -> None:
    parser = argparse.ArgumentParser(description="突破观察池 vs 分钟缓存覆盖审查")
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    default_csv = os.path.join(root, "data", "reports", "breakout_watchlist_history_latest.csv")
    parser.add_argument("--csv", default=default_csv, help="观察池导出 CSV")
    parser.add_argument(
        "--cache-dir",
        default=os.path.join(root, "data", "intraday_cache"),
        help="分钟 parquet 目录",
    )
    parser.add_argument(
        "--verify-rows",
        action="store_true",
        help="在文件名覆盖基础上，再读 parquet 检查是否含该日 trade_time",
    )
    args = parser.parse_args()

    if not os.path.isfile(args.csv):
        print(f"找不到观察池文件: {args.csv}\n请先运行 export_breakout_watchlist_history.py")
        sys.exit(1)

    df = pd.read_csv(args.csv, encoding="utf-8-sig")
    if df.empty:
        print("观察池 CSV 为空")
        sys.exit(0)

    ranges_by_sym = load_cache_ranges(args.cache_dir)
    n_files = sum(len(v) for v in ranges_by_sym.values())
    print("=" * 70)
    print("分钟缓存目录:", args.cache_dir)
    print(f"已解析 parquet 文件数: {n_files}（符合命名规则 6位代码_start_end_freq.parquet）")
    print("观察池行数:", len(df))
    print("=" * 70)

    miss: list[dict] = []
    ok_name = 0
    ok_verify = 0

    for _, row in df.iterrows():
        code = str(row["ts_code"]).strip()
        sym = code.split(".")[0]
        wd = _parse_watch_date(row.get("watch_date"))
        if wd is None:
            miss.append(
                {
                    "watch_date": row.get("watch_date"),
                    "ts_code": code,
                    "reason": "watch_date 无法解析",
                }
            )
            continue
        rlist = ranges_by_sym.get(sym, [])
        ok, path = date_in_any_range(wd, rlist)
        if not ok:
            miss.append({"watch_date": wd.isoformat(), "ts_code": code, "reason": "无覆盖该区间的缓存文件"})
            continue
        ok_name += 1
        if args.verify_rows and path:
            if verify_file_has_date(path, wd):
                ok_verify += 1
            else:
                miss.append(
                    {
                        "watch_date": wd.isoformat(),
                        "ts_code": code,
                        "reason": f"文件覆盖日期但内容无该日K线: {os.path.basename(path)}",
                    }
                )

    total = len(df)
    bad_parse = sum(1 for m in miss if m.get("reason") == "watch_date 无法解析")
    sym_label = "6位代码"

    print(f"\n【文件名日期区间覆盖】（watch_date 落在任一 {sym_label}_start_end_*.parquet 的 [start,end] 内）")
    print(f"  有覆盖: {ok_name} / {total} ({ok_name/total:.2%})")
    print(f"  无覆盖: {total - ok_name - bad_parse} 行（已排除日期解析失败 {bad_parse} 行）")

    if args.verify_rows:
        print(f"\n【文件内 trade_time 含当日】（在「文件名有覆盖」的 {ok_name} 行上）")
        print(f"  验证通过: {ok_verify} / {ok_name} ({(ok_verify/ok_name if ok_name else 0):.2%})")

    if miss:
        miss_df = pd.DataFrame(miss)
        rep = os.path.join(root, "data", "reports", "breakout_watchlist_minute_coverage_missing.csv")
        miss_df.to_csv(rep, index=False, encoding="utf-8-sig")
        print(f"\n缺失或异常明细已写入: {rep}（共 {len(miss)} 条）")
        print(miss_df.head(10).to_string())
        if len(miss) > 10:
            print(f"... 其余 {len(miss)-10} 条见 CSV")
    else:
        print("\n无缺失记录。")

    print(
        "\n说明: 突破确认通常在「信号日次日」看盘；若需核对 T+1 分钟线，"
        "可将本脚本逻辑中的 watch_date 改为次日交易日再跑，或扩大下载 extend_days。"
    )


if __name__ == "__main__":
    main()
