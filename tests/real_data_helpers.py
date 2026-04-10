# -*- coding: utf-8 -*-
"""
测试用真实市场数据加载工具。

统一从项目现有 SQLite 数据库中读取日线与分时数据，避免在测试里生成模拟行情。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

import pandas as pd

from src.core.config import ConfigManager
from src.modules.backtest.history_recommendation_db import HistoryRecommendationDB


DEFAULT_DAILY_SYMBOLS = [
    "000001.SZ",
    "000002.SZ",
    "000004.SZ",
    "600000.SH",
    "600036.SH",
    "601318.SH",
]


def get_daily_db_path() -> Path:
    """获取主行情数据库路径。"""
    config = ConfigManager()
    return Path(config.get("database.path"))


def _connect_daily_db() -> sqlite3.Connection:
    db_path = get_daily_db_path()
    if not db_path.exists():
        raise FileNotFoundError(f"未找到主行情数据库: {db_path}")
    return sqlite3.connect(db_path)


def get_available_daily_symbols(limit: int = 20, min_rows: int = 60) -> List[str]:
    """获取数据量足够的日线样本股票。"""
    conn = _connect_daily_db()
    try:
        rows = conn.execute(
            """
            SELECT ts_code
            FROM stock_daily
            GROUP BY ts_code
            HAVING COUNT(*) >= ?
            ORDER BY COUNT(*) DESC, ts_code ASC
            LIMIT ?
            """,
            (min_rows, limit),
        ).fetchall()
        return [row[0] for row in rows]
    finally:
        conn.close()


def load_daily_data(
    ts_code: str,
    bars: int = 90,
) -> pd.DataFrame:
    """读取单只股票最近 N 根真实日线数据。"""
    conn = _connect_daily_db()
    try:
        query = """
            SELECT trade_date, open, high, low, close, vol, amount
            FROM stock_daily
            WHERE ts_code = ?
            ORDER BY trade_date DESC
            LIMIT ?
        """
        df = pd.read_sql_query(query, conn, params=[ts_code, bars])
    finally:
        conn.close()

    if df.empty:
        return df

    df = df.sort_values("trade_date").reset_index(drop=True)
    df["trade_date"] = pd.to_datetime(df["trade_date"], format="%Y%m%d")
    return df


def load_daily_data_dict(
    symbols: Optional[Iterable[str]] = None,
    bars: int = 90,
    strip_suffix: bool = True,
) -> Dict[str, pd.DataFrame]:
    """批量读取真实日线数据，返回回测引擎可直接使用的字典。"""
    if symbols is None:
        symbols = DEFAULT_DAILY_SYMBOLS

    data_dict: Dict[str, pd.DataFrame] = {}
    for ts_code in symbols:
        df = load_daily_data(ts_code, bars=bars)
        if df.empty:
            continue
        key = ts_code.split(".")[0] if strip_suffix else ts_code
        data_dict[key] = df

    return data_dict


def get_history_recommendation_db() -> HistoryRecommendationDB:
    """获取真实分时数据库访问对象。"""
    db_path = Path("data/history_recommendation.db")
    if not db_path.exists():
        raise FileNotFoundError(f"未找到历史推荐数据库: {db_path}")
    return HistoryRecommendationDB(str(db_path))


def get_intraday_sample(
    symbol: Optional[str] = None,
    min_rows: int = 120,
) -> Tuple[str, pd.DataFrame]:
    """获取一只具备足够分时记录的真实样本股票。"""
    db = get_history_recommendation_db()

    if symbol:
        df = db.get_intraday_data(symbol)
        if len(df) >= min_rows:
            return symbol, df
        raise ValueError(f"{symbol} 的分时数据不足 {min_rows} 条")

    conn = sqlite3.connect(db.db_path)
    try:
        row = conn.execute(
            """
            SELECT symbol
            FROM intraday_data
            GROUP BY symbol
            HAVING COUNT(*) >= ?
            ORDER BY COUNT(*) DESC, symbol ASC
            LIMIT 1
            """,
            (min_rows,),
        ).fetchone()
    finally:
        conn.close()

    if not row:
        raise ValueError("未找到满足条件的真实分时样本")

    sample_symbol = row[0]
    return sample_symbol, db.get_intraday_data(sample_symbol)


def get_real_recommendations(limit: int = 5) -> List[Dict]:
    """读取真实推荐记录样本。"""
    db = get_history_recommendation_db()
    recommendations = db.get_recommendations()
    return recommendations[:limit]
