# -*- coding: utf-8 -*-
"""
从当前库中「最早个股交易日」起，再向前补沪深主板日线。

写入表：stock_daily（与 DataUpdater.update_daily_data 同结构）。
同时补上证指数 000001.SH 同一区间（突破策略 BreakoutStrategy 需指数序列）。

用法:
  python scripts/backfill_main_board_daily_backward.py
  python scripts/backfill_main_board_daily_backward.py --months 3 --dry-run
  # 将最早数据推到不晚于 20250101（从该日起的首个交易日补到当前库最早日之前）
  python scripts/backfill_main_board_daily_backward.py --target-start 20250101

依赖: Tushare Pro（环境变量 TUSHARE_TOKEN 或 config 中 data_source.tushare_token）
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import time
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
from dateutil.relativedelta import relativedelta

from src.core.config import ConfigManager
from src.core.database import DatabaseManager
from src.core.logger import get_logger
from src.modules.data_updater import DataUpdater, TushareDataSource

logger = get_logger("backfill_main_board_daily_backward")

INDEX_CODE = "000001.SH"


def _is_hs_main_board(ts_code: str) -> bool:
    """沪深主板（与 scripts/download_daily_data_tushare 口径一致）。"""
    if not ts_code or "." not in ts_code:
        return False
    sym, suf = ts_code.split(".")
    if suf == "SH":
        return bool(re.match(r"^60[01235]", sym))
    if suf == "SZ":
        return bool(re.match(r"^00[01]", sym))
    return False


def _rows_from_daily_df(df: pd.DataFrame, create_time: str) -> list[tuple]:
    """将 Tushare daily 单日全市场行情转为 stock_daily 插入行。"""
    params_list: list[tuple] = []
    for _, row in df.iterrows():
        ts_code = row.get("ts_code")
        if not ts_code or not _is_hs_main_board(str(ts_code)):
            continue
        pct_chg = row.get("pct_chg")
        if pct_chg is None and row.get("pre_close") not in (None, 0):
            try:
                pc = float(row.get("pre_close"))
                if pc:
                    pct_chg = round(
                        (float(row.get("close", 0) or 0) - pc) / pc * 100, 2
                    )
            except (TypeError, ValueError):
                pct_chg = None
        params_list.append(
            (
                ts_code,
                row.get("trade_date"),
                row.get("open"),
                row.get("close"),
                row.get("high"),
                row.get("low"),
                row.get("vol"),
                row.get("amount"),
                pct_chg,
                create_time,
            )
        )
    return params_list


def _rows_from_index_df(df: pd.DataFrame, create_time: str) -> list[tuple]:
    params_list: list[tuple] = []
    for _, row in df.iterrows():
        params_list.append(
            (
                row.get("ts_code"),
                row.get("trade_date"),
                row.get("open"),
                row.get("close"),
                row.get("high"),
                row.get("low"),
                row.get("vol"),
                row.get("amount"),
                row.get("pct_chg"),
                create_time,
            )
        )
    return params_list


def _normalize_yyyymmdd(s: str) -> str:
    """接受 YYYYMMDD 或 YYYY-MM-DD，返回 8 位数字串。"""
    raw = str(s).strip().replace("-", "")
    if len(raw) != 8 or not raw.isdigit():
        raise ValueError(f"日期格式无效: {s}")
    return raw


def main() -> None:
    parser = argparse.ArgumentParser(description="向前补沪深主板日线 + 上证指数")
    parser.add_argument(
        "--months",
        type=int,
        default=3,
        help="从最早数据日再往前覆盖的自然月数（默认 3；与 --target-start 二选一生效）",
    )
    parser.add_argument(
        "--target-start",
        type=str,
        default=None,
        help="目标最早窗口：补全从该日起（含当日或之后首个交易日）到当前库最早个股日之前的主板日线，例如 20250101",
    )
    parser.add_argument(
        "--sleep",
        type=float,
        default=0.45,
        help="每个交易日请求后的休眠秒数，降频防限流（默认 0.45）",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只打印拟补区间与交易日数量，不写库",
    )
    args = parser.parse_args()

    config = ConfigManager()
    db = DatabaseManager(config)
    token = (config.get("data_source.tushare_token", "") or "").strip()
    if not token or "your_tushare_token" in str(token).lower():
        print(
            "错误: 请设置 Tushare Token：环境变量 TUSHARE_TOKEN，"
            "或在项目根目录 .env 中配置，或写入 config 的 data_source.tushare_token"
        )
        sys.exit(1)

    row = db.query_one(
        "SELECT MIN(trade_date) AS min_d FROM stock_daily WHERE ts_code != ?",
        (INDEX_CODE,),
    )
    anchor = row["min_d"] if row else None
    if not anchor:
        print("stock_daily 无个股数据，无法确定锚点")
        sys.exit(1)

    anchor_str = str(anchor).replace("-", "")[:8]
    if len(anchor_str) != 8:
        print(f"无法解析最早交易日: {anchor}")
        sys.exit(1)

    ts = TushareDataSource(config)
    pro = ts._init_pro()

    trade_dates: list[str]

    if args.target_start:
        try:
            target_str = _normalize_yyyymmdd(args.target_start)
        except ValueError as e:
            print(f"错误: {e}")
            sys.exit(1)

        if anchor_str <= target_str:
            print(
                f"当前个股最早日 {anchor_str} 已不晚于目标 {target_str}，无需向前补数"
            )
            sys.exit(0)

        cal_range = pro.trade_cal(
            exchange="SSE",
            start_date=target_str,
            end_date=anchor_str,
            is_open="1",
        )
        if cal_range is None or cal_range.empty:
            print("无法获取交易日历")
            sys.exit(1)

        trade_dates = sorted(
            str(x) for x in cal_range["cal_date"].tolist() if str(x) < anchor_str
        )
        trade_dates = [d for d in trade_dates if d >= target_str]
    else:
        anchor_dt = datetime.strptime(anchor_str, "%Y%m%d")
        start_hint = (anchor_dt - relativedelta(months=max(1, args.months))).strftime(
            "%Y%m%d"
        )

        cal_before = pro.trade_cal(
            exchange="SSE",
            start_date=start_hint,
            end_date=anchor_str,
            is_open="1",
        )
        if cal_before is None or cal_before.empty:
            print("无法获取交易日历")
            sys.exit(1)

        prev_open = [str(x) for x in cal_before["cal_date"].tolist() if str(x) < anchor_str]
        if not prev_open:
            print(f"锚点 {anchor_str} 之前无交易日，无需向前补数")
            sys.exit(0)

        end_backfill = max(prev_open)
        cal_window = pro.trade_cal(
            exchange="SSE",
            start_date=start_hint,
            end_date=end_backfill,
            is_open="1",
        )
        trade_dates = sorted(str(x) for x in cal_window["cal_date"].tolist())

    if not trade_dates:
        print("拟补交易日列表为空，无需写入")
        sys.exit(0)

    print("=" * 60)
    print("向前补沪深主板日线 + 上证指数")
    print(f"  锚点(当前最早个股交易日): {anchor_str}")
    if args.target_start:
        print(f"  目标起始: {_normalize_yyyymmdd(args.target_start)}（含该日及之后、早于锚点的交易日）")
    print(f"  拟补区间: {trade_dates[0]} -> {trade_dates[-1]}  共 {len(trade_dates)} 个交易日")
    print("=" * 60)

    if args.dry_run:
        print("--dry-run 已指定，未写入数据库")
        return

    updater = DataUpdater(config, db)
    sql_daily = """
        REPLACE INTO stock_daily (ts_code, trade_date, open, close, high, low, vol, amount, pct_chg, create_time)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """
    create_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    total_stocks = 0
    for i, td in enumerate(trade_dates, 1):
        df = updater._try_data_source(
            lambda d=td: ts.get_daily_data_batch(d),
            None,
        )
        if df is None or df.empty:
            logger.warning("日期 %s 无全市场行情", td)
            time.sleep(0.35)
            continue
        df = df.where(pd.notnull(df), None)
        params = _rows_from_daily_df(df, create_time)
        n = db.execute_many(sql_daily, params) if params else 0
        total_stocks += n
        print(f"  [{i}/{len(trade_dates)}] {td} 主板写入约 {len(params)} 条 (executemany 返回 {n})")
        time.sleep(max(0.05, float(args.sleep)))

    # 上证指数同区间
    idx_df = ts.get_index_daily(INDEX_CODE, trade_dates[0], trade_dates[-1])
    if idx_df is not None and not idx_df.empty:
        idx_df = idx_df.where(pd.notnull(idx_df), None)
        idx_params = _rows_from_index_df(idx_df, create_time)
        idx_exec = db.execute_many(sql_daily, idx_params) if idx_params else 0
        print(f"  指数 {INDEX_CODE} 写入 {len(idx_params)} 条 (executemany 返回 {idx_exec})")
    else:
        print(f"  警告: 未取到指数 {INDEX_CODE} 日线，请稍后单独运行 backfill_sh_index_to_stock_daily.py")

    verify = db.query_one(
        "SELECT MIN(trade_date) AS a FROM stock_daily WHERE ts_code != ?",
        (INDEX_CODE,),
    )
    print("\n完成。当前个股日线最早日期:", verify.get("a") if verify else None)
    print("主板按日累计 executemany 返回值合计(参考):", total_stocks)


if __name__ == "__main__":
    main()
