# -*- coding: utf-8 -*-
"""
检查 quant_system.db 中 stock_daily 覆盖与缺失概况；
若存在 history_recommendation.db 则顺带统计 intraday_data 行数。

用法：python scripts/diagnose_db_coverage.py
"""

from __future__ import annotations

import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd

from src.core.config import ConfigManager
from src.core.database import DatabaseManager


def main() -> None:
    cfg = ConfigManager()
    db = DatabaseManager(cfg)
    path = db.db_path
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    print("=" * 70)
    print("主库:", path)
    print("=" * 70)

    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row

    # 全表交易日历（以全市场并集近似）
    cal = pd.read_sql_query(
        "SELECT DISTINCT trade_date FROM stock_daily ORDER BY trade_date", conn
    )
    cal["trade_date"] = cal["trade_date"].astype(str)
    n_cal = len(cal)
    dmin, dmax = cal["trade_date"].iloc[0], cal["trade_date"].iloc[-1]
    print(f"\n【stock_daily】库内交易日历: {dmin} -> {dmax}，共 {n_cal} 个交易日")

    tot = pd.read_sql_query(
        "SELECT COUNT(*) AS n FROM stock_daily", conn
    ).iloc[0]["n"]
    n_sym = pd.read_sql_query(
        "SELECT COUNT(DISTINCT ts_code) AS n FROM stock_daily", conn
    ).iloc[0]["n"]
    print(f"总行数: {int(tot):,} | 不同 ts_code 数: {int(n_sym)}")

    cov2 = pd.read_sql_query(
        """
        SELECT ts_code,
               MIN(trade_date) AS min_d,
               MAX(trade_date) AS max_d,
               COUNT(DISTINCT trade_date) AS days
        FROM stock_daily
        WHERE SUBSTR(ts_code,1,3) IN ('600','601','603','605','000','001','002')
        GROUP BY ts_code
        """,
        conn,
    )
    print(f"\n【主板口径】约 {len(cov2)} 只股票在 stock_daily 中有记录")

    # 期望覆盖：从每只股票 min_d 到 max_d 的日历天数与应有交易日数对比
    # 用全库日历作为「应有」上限：每只股票在 [min_d,max_d] 内应有交易日数 = cal 中落在区间内的条数
    cal_set = set(cal["trade_date"].tolist())

    def expected_days(rmin: str, rmax: str) -> int:
        return int(((cal["trade_date"] >= rmin) & (cal["trade_date"] <= rmax)).sum())

    ratios = []
    gaps = []
    for _, r in cov2.iterrows():
        ed = expected_days(str(r["min_d"]), str(r["max_d"]))
        if ed <= 0:
            continue
        ratio = float(r["days"]) / ed
        ratios.append(ratio)
        if ratio < 0.85 and ed >= 60:
            gaps.append((r["ts_code"], r["min_d"], r["max_d"], int(r["days"]), ed, ratio))

    if ratios:
        s = pd.Series(ratios)
        print(
            f"\n【主板】相对各自上市区间的日历覆盖比（相对库内交易日并集）"
            f"\n  中位数: {s.median():.3f}  均值: {s.mean():.3f}  最小: {s.min():.3f}"
        )

    gaps.sort(key=lambda x: x[5])
    print(f"\n【疑似日线缺失较多】覆盖比<0.85 且区间≥60交易日的股票数: {len(gaps)}")
    for row in gaps[:25]:
        print(
            f"  {row[0]}  {row[1]}~{row[2]}  实际{row[3]}天/期望约{row[4]}天  比例{row[5]:.2%}"
        )
    if len(gaps) > 25:
        print(f"  ... 其余 {len(gaps)-25} 只略")

    # 指数 000001.SH
    sh = pd.read_sql_query(
        """
        SELECT MIN(trade_date), MAX(trade_date), COUNT(*)
        FROM stock_daily WHERE ts_code='000001.SH'
        """,
        conn,
    )
    print("\n【上证指数 000001.SH】", tuple(sh.iloc[0].tolist()))

    conn.close()

    # 分钟数据：主库无分钟表；检查独立库
    hist_paths = [
        os.path.join(root, "data", "database", "history_recommendation.db"),
        os.path.join(root, "data", "history_recommendation.db"),
    ]
    print("\n" + "=" * 70)
    print("分钟/分时数据（不在 quant_system.stock_daily）")
    print("=" * 70)
    hist_db = next((p for p in hist_paths if os.path.isfile(p)), None)
    if hist_db:
        print("使用库文件:", hist_db)
        h = sqlite3.connect(hist_db)
        try:
            all_t = [r[0] for r in h.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            ).fetchall()]
            print("其中表:", all_t)
            intraday_like = [x for x in all_t if "intraday" in x.lower() or "minute" in x.lower()]
            if intraday_like:
                for tn in intraday_like:
                    n = h.execute(f"SELECT COUNT(*) FROM {tn}").fetchone()[0]
                    print(f"  {tn} 行数: {n:,}")
            else:
                print("（无表名含 intraday/minute；旧版可能用其它表名）")
        except Exception as e:
            print("读取失败:", e)
        h.close()
    else:
        print("未找到 history_recommendation.db（已检查 data/database 与 data/ 根目录）")

    cache_dir = os.path.join(root, "data", "intraday_cache")
    if os.path.isdir(cache_dir):
        files = [f for f in os.listdir(cache_dir) if f.endswith((".parquet", ".csv"))]
        print(f"\ndata/intraday_cache 下数据文件约 {len(files)} 个（分钟缓存，非 SQLite）")
    else:
        print("\n无目录 data/intraday_cache")

    print("\n说明：「期望天数」按库内统一交易日历截断，若某股 start/end 与日历不完全对齐会略有误差。")


if __name__ == "__main__":
    main()
