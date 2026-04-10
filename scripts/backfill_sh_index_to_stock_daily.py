# -*- coding: utf-8 -*-
"""
将上证指数(000001.SH)日线回填到现有 stock_daily 表。

优先使用 AKShare（免 token），失败时回退到 Tushare。
"""

from __future__ import annotations

import os
import sys
from datetime import datetime
import time

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.core.config import ConfigManager
from src.core.database import DatabaseManager


INDEX_TS_CODE = "000001.SH"


def _normalize_trade_date(series: pd.Series) -> pd.Series:
    dt = pd.to_datetime(series, errors="coerce")
    return dt.dt.strftime("%Y%m%d")


def fetch_from_akshare(start_date: str, end_date: str) -> pd.DataFrame:
    import akshare as ak

    # 先尝试东方财富接口，再尝试新浪接口
    raw = pd.DataFrame()
    try:
        raw = ak.stock_zh_index_daily_em(symbol="sh000001")
    except Exception:
        raw = pd.DataFrame()
    if raw is None or raw.empty:
        raw = ak.stock_zh_index_daily(symbol="sh000001")
    if raw is None or raw.empty:
        return pd.DataFrame()

    df = raw.rename(
        columns={
            "date": "trade_date",
            "open": "open",
            "high": "high",
            "low": "low",
            "close": "close",
            "volume": "vol",
            "amount": "amount",
        }
    ).copy()
    df["trade_date"] = _normalize_trade_date(df["trade_date"])
    df = df.dropna(subset=["trade_date", "close"]).copy()
    df = df[(df["trade_date"] >= start_date) & (df["trade_date"] <= end_date)].copy()
    if df.empty:
        return df

    df = df.sort_values("trade_date").reset_index(drop=True)
    df["pct_chg"] = df["close"].pct_change() * 100.0
    df["ts_code"] = INDEX_TS_CODE
    return df[["ts_code", "trade_date", "open", "close", "high", "low", "vol", "amount", "pct_chg"]]


def fetch_from_tushare(start_date: str, end_date: str) -> pd.DataFrame:
    import tushare as ts

    config = ConfigManager()
    token = config.get("data_source.tushare_token", "")
    if not token or "your_tushare_token_here" in str(token):
        raise RuntimeError("Tushare token 未配置")
    ts.set_token(token)
    pro = ts.pro_api()
    raw = pro.index_daily(ts_code=INDEX_TS_CODE, start_date=start_date, end_date=end_date)
    if raw is None or raw.empty:
        return pd.DataFrame()

    df = raw.copy()
    df = df.rename(
        columns={
            "vol": "vol",
            "amount": "amount",
        }
    )
    for col in ["open", "close", "high", "low", "vol", "amount", "pct_chg"]:
        if col not in df.columns:
            df[col] = None
    df = df[["ts_code", "trade_date", "open", "close", "high", "low", "vol", "amount", "pct_chg"]]
    df = df.sort_values("trade_date").reset_index(drop=True)
    return df


def upsert_to_stock_daily(db: DatabaseManager, df: pd.DataFrame) -> int:
    if df.empty:
        return 0
    sql = """
    INSERT OR REPLACE INTO stock_daily
    (ts_code, trade_date, open, close, high, low, vol, amount, pct_chg)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """
    params = [
        (
            str(r.ts_code),
            str(r.trade_date),
            float(r.open) if pd.notna(r.open) else None,
            float(r.close) if pd.notna(r.close) else None,
            float(r.high) if pd.notna(r.high) else None,
            float(r.low) if pd.notna(r.low) else None,
            float(r.vol) if pd.notna(r.vol) else None,
            float(r.amount) if pd.notna(r.amount) else None,
            float(r.pct_chg) if pd.notna(r.pct_chg) else None,
        )
        for r in df.itertuples(index=False)
    ]
    return db.execute_many(sql, params)


def main() -> None:
    config = ConfigManager()
    db = DatabaseManager(config)

    window = db.query(
        "SELECT MIN(trade_date) AS min_d, MAX(trade_date) AS max_d FROM stock_daily WHERE ts_code != ?",
        (INDEX_TS_CODE,),
    )
    if not window or not window[0]["min_d"] or not window[0]["max_d"]:
        raise RuntimeError("stock_daily 无可用个股时间范围，无法确定回填窗口。")
    start_date = str(window[0]["min_d"])
    end_date = str(window[0]["max_d"])

    print(f"回填窗口: {start_date} -> {end_date}")
    print("优先尝试 AKShare ...")
    data = pd.DataFrame()
    source = ""

    # AKShare 多次重试
    for i in range(3):
        try:
            data = fetch_from_akshare(start_date, end_date)
            if not data.empty:
                source = "AKShare"
                break
            print(f"AKShare 第{i+1}次返回空数据")
        except Exception as e:
            print(f"AKShare 第{i+1}次失败: {e}")
        time.sleep(1.2 + i * 0.8)

    if data.empty:
        print("尝试 Tushare ...")
        try:
            data = fetch_from_tushare(start_date, end_date)
            source = "Tushare"
        except Exception as e:
            raise RuntimeError(f"Tushare 拉取也失败: {e}") from e

    if data.empty:
        raise RuntimeError("指数数据为空，未写入数据库。")

    affected = upsert_to_stock_daily(db, data)

    verify = db.query(
        "SELECT MIN(trade_date) AS min_d, MAX(trade_date) AS max_d, COUNT(*) AS cnt "
        "FROM stock_daily WHERE ts_code = ?",
        (INDEX_TS_CODE,),
    )[0]
    print(f"数据源: {source}")
    print(f"写入行数(受影响): {affected}")
    print(
        f"当前库中 {INDEX_TS_CODE} 覆盖: {verify['min_d']} -> {verify['max_d']}, 共 {verify['cnt']} 条"
    )
    print(f"完成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")


if __name__ == "__main__":
    main()
