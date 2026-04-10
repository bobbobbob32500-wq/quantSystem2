# -*- coding: utf-8 -*-
"""
数据库优化器单元测试
"""

import sqlite3

from tools.db_optimizer import DatabaseOptimizer


def _build_optimizer_with_connection(conn: sqlite3.Connection) -> DatabaseOptimizer:
    optimizer = DatabaseOptimizer(db_path=":memory:")
    optimizer.conn = conn
    return optimizer


def _index_exists(conn: sqlite3.Connection, index_name: str) -> bool:
    cursor = conn.cursor()
    cursor.execute(
        "SELECT 1 FROM sqlite_master WHERE type='index' AND name=?",
        (index_name,),
    )
    return cursor.fetchone() is not None


def test_create_indexes_with_runtime_schema_columns():
    """当表结构使用 ts_code/trade_date/signal_time/trade_time 时应正确建索引"""
    conn = sqlite3.connect(":memory:")
    cursor = conn.cursor()
    cursor.execute("CREATE TABLE stock_daily (ts_code TEXT, trade_date TEXT)")
    cursor.execute("CREATE TABLE factor_values (ts_code TEXT, trade_date TEXT)")
    cursor.execute("CREATE TABLE signal_history (ts_code TEXT, signal_time TEXT)")
    cursor.execute("CREATE TABLE trade_log (ts_code TEXT, trade_time TEXT)")
    cursor.execute("CREATE TABLE hold_stock (ts_code TEXT)")
    conn.commit()

    optimizer = _build_optimizer_with_connection(conn)
    assert optimizer.create_indexes() is True

    assert _index_exists(conn, "idx_stock_daily_ts_code_date")
    assert _index_exists(conn, "idx_factor_values_code_date")
    assert _index_exists(conn, "idx_signal_history_code_time")
    assert _index_exists(conn, "idx_trade_log_code_time")
    assert _index_exists(conn, "idx_hold_stock_ts_code")

    conn.close()


def test_create_indexes_with_legacy_schema_columns():
    """当表结构使用 symbol/calc_date/signal_date/trade_date 时应兼容建索引"""
    conn = sqlite3.connect(":memory:")
    cursor = conn.cursor()
    cursor.execute("CREATE TABLE factor_values (symbol TEXT, calc_date TEXT)")
    cursor.execute("CREATE TABLE signal_history (ts_code TEXT, signal_date TEXT)")
    cursor.execute("CREATE TABLE trade_log (ts_code TEXT, trade_date TEXT)")
    conn.commit()

    optimizer = _build_optimizer_with_connection(conn)
    assert optimizer.create_indexes() is True

    assert _index_exists(conn, "idx_factor_values_code_date")
    assert _index_exists(conn, "idx_signal_history_code_time")
    assert _index_exists(conn, "idx_trade_log_code_time")

    conn.close()


def test_create_indexes_without_matching_columns_returns_false():
    """当字段不匹配时应跳过并返回 False"""
    conn = sqlite3.connect(":memory:")
    cursor = conn.cursor()
    cursor.execute("CREATE TABLE factor_values (id INTEGER)")
    conn.commit()

    optimizer = _build_optimizer_with_connection(conn)
    assert optimizer.create_indexes() is False

    conn.close()
