# -*- coding: utf-8 -*-

from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd

from src.modules.signal_feedback_evaluator import SignalFeedbackEvaluator


class _SimpleDB:
    def __init__(self, db_path: Path):
        self.db_path = str(db_path)

    def query_to_dataframe(self, sql: str, params=None):
        conn = sqlite3.connect(self.db_path)
        try:
            return pd.read_sql_query(sql, conn, params=params)
        finally:
            conn.close()

    def execute(self, sql: str, params=None):
        conn = sqlite3.connect(self.db_path)
        try:
            cur = conn.cursor()
            if params:
                cur.execute(sql, params)
            else:
                cur.execute(sql)
            conn.commit()
            return cur.rowcount
        finally:
            conn.close()

    def execute_many(self, sql: str, params_list):
        conn = sqlite3.connect(self.db_path)
        try:
            cur = conn.cursor()
            cur.executemany(sql, params_list)
            conn.commit()
            return cur.rowcount
        finally:
            conn.close()

    def get_latest_trade_date(self, table_name: str = "stock_daily"):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            row = conn.execute(f"SELECT MAX(trade_date) AS latest FROM {table_name}").fetchone()
            return row["latest"] if row else None
        finally:
            conn.close()


def _prepare_quant_db(path: Path):
    conn = sqlite3.connect(str(path))
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE stock_daily (
            ts_code TEXT,
            trade_date TEXT,
            open REAL,
            high REAL,
            low REAL,
            close REAL
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE signal_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts_code TEXT,
            name TEXT,
            signal_type TEXT,
            signal_time TEXT,
            trigger_reason TEXT,
            suggestion TEXT
        )
        """
    )

    bars = [
        ("000001.SZ", "20260102", 10.0, 10.5, 9.9, 10.2),
        ("000001.SZ", "20260103", 10.3, 10.8, 10.1, 10.6),
        ("000001.SZ", "20260104", 10.7, 11.0, 10.5, 10.9),
        ("000001.SZ", "20260105", 10.8, 11.2, 10.6, 11.1),
        ("000001.SZ", "20260106", 11.0, 11.3, 10.7, 11.2),
        ("000001.SZ", "20260107", 11.1, 11.4, 10.8, 11.0),
    ]
    cur.executemany(
        "INSERT INTO stock_daily (ts_code, trade_date, open, high, low, close) VALUES (?, ?, ?, ?, ?, ?)",
        bars,
    )
    cur.executemany(
        """
        INSERT INTO signal_history (ts_code, name, signal_type, signal_time, trigger_reason, suggestion)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        [
            ("000001.SZ", "平安银行", "买入信号", "2026-01-03 10:00:00", "突破", "可建仓"),
            ("000001.SZ", "平安银行", "止盈卖点", "2026-01-04 11:00:00", "涨幅过快", "考虑减仓"),
        ],
    )
    conn.commit()
    conn.close()


def _prepare_rec_db(path: Path):
    conn = sqlite3.connect(str(path))
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE recommendations (
            symbol TEXT,
            name TEXT,
            recommendation_date TEXT,
            recommendation_score REAL,
            strategy_type TEXT
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE intraday_data (
            symbol TEXT,
            trade_time TEXT,
            trade_date TEXT,
            open REAL,
            high REAL,
            low REAL,
            close REAL,
            volume REAL,
            amount REAL
        )
        """
    )
    cur.executemany(
        """
        INSERT INTO recommendations (symbol, name, recommendation_date, recommendation_score, strategy_type)
        VALUES (?, ?, ?, ?, ?)
        """,
        [
            ("000001.SZ", "平安银行", "2026-01-02", 92.0, "legacy"),
        ],
    )
    minute_bars = [
        ("000001", "2026-01-03 10:00:00", "2026-01-03", 10.60, 10.62, 10.58, 10.60, 1000, 10600),
        ("000001", "2026-01-03 10:01:00", "2026-01-03", 10.61, 10.64, 10.60, 10.63, 1100, 11693),
        ("000001", "2026-01-03 10:02:00", "2026-01-03", 10.63, 10.66, 10.62, 10.65, 1200, 12780),
        ("000001", "2026-01-03 10:03:00", "2026-01-03", 10.65, 10.67, 10.63, 10.64, 1000, 10640),
        ("000001", "2026-01-03 10:04:00", "2026-01-03", 10.64, 10.69, 10.63, 10.68, 1000, 10680),
        ("000001", "2026-01-03 10:05:00", "2026-01-03", 10.68, 10.72, 10.67, 10.70, 1200, 12840),
        ("000001", "2026-01-03 10:06:00", "2026-01-03", 10.70, 10.73, 10.69, 10.71, 900, 9639),
        ("000001", "2026-01-03 10:07:00", "2026-01-03", 10.71, 10.74, 10.70, 10.72, 900, 9648),
        ("000001", "2026-01-03 10:08:00", "2026-01-03", 10.72, 10.75, 10.71, 10.73, 900, 9657),
        ("000001", "2026-01-03 10:09:00", "2026-01-03", 10.73, 10.77, 10.72, 10.74, 900, 9666),
        ("000001", "2026-01-03 10:10:00", "2026-01-03", 10.74, 10.78, 10.73, 10.76, 1000, 10760),
        ("000001", "2026-01-03 10:11:00", "2026-01-03", 10.76, 10.79, 10.74, 10.77, 900, 9693),
        ("000001", "2026-01-03 10:12:00", "2026-01-03", 10.77, 10.80, 10.76, 10.78, 900, 9702),
        ("000001", "2026-01-03 10:13:00", "2026-01-03", 10.78, 10.82, 10.77, 10.80, 900, 9720),
        ("000001", "2026-01-03 10:14:00", "2026-01-03", 10.80, 10.84, 10.79, 10.81, 900, 9729),
        ("000001", "2026-01-03 10:15:00", "2026-01-03", 10.81, 10.85, 10.80, 10.83, 1000, 10830),
        ("000001", "2026-01-03 10:16:00", "2026-01-03", 10.83, 10.86, 10.82, 10.84, 900, 9756),
        ("000001", "2026-01-03 10:17:00", "2026-01-03", 10.84, 10.88, 10.83, 10.86, 900, 9774),
        ("000001", "2026-01-03 10:18:00", "2026-01-03", 10.86, 10.89, 10.85, 10.87, 900, 9783),
        ("000001", "2026-01-03 10:19:00", "2026-01-03", 10.87, 10.90, 10.86, 10.88, 900, 9792),
        ("000001", "2026-01-03 10:20:00", "2026-01-03", 10.88, 10.92, 10.87, 10.90, 1100, 11990),
        ("000001", "2026-01-03 10:21:00", "2026-01-03", 10.90, 10.93, 10.89, 10.91, 900, 9819),
        ("000001", "2026-01-03 10:22:00", "2026-01-03", 10.91, 10.94, 10.90, 10.92, 900, 9828),
        ("000001", "2026-01-03 10:23:00", "2026-01-03", 10.92, 10.95, 10.91, 10.93, 900, 9837),
        ("000001", "2026-01-03 10:24:00", "2026-01-03", 10.93, 10.96, 10.92, 10.94, 900, 9846),
        ("000001", "2026-01-03 10:25:00", "2026-01-03", 10.94, 10.98, 10.93, 10.96, 1100, 12056),
        ("000001", "2026-01-03 10:26:00", "2026-01-03", 10.96, 10.99, 10.95, 10.97, 900, 9873),
        ("000001", "2026-01-03 10:27:00", "2026-01-03", 10.97, 11.00, 10.96, 10.98, 900, 9882),
        ("000001", "2026-01-03 10:28:00", "2026-01-03", 10.98, 11.02, 10.97, 10.99, 900, 9891),
        ("000001", "2026-01-03 10:29:00", "2026-01-03", 10.99, 11.03, 10.98, 11.00, 900, 9900),
        ("000001", "2026-01-03 10:30:00", "2026-01-03", 11.00, 11.05, 10.99, 11.02, 1200, 13224),
    ]
    cur.executemany(
        """
        INSERT INTO intraday_data (symbol, trade_time, trade_date, open, high, low, close, volume, amount)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        minute_bars,
    )
    conn.commit()
    conn.close()


def test_infer_signal_direction():
    assert SignalFeedbackEvaluator.infer_signal_direction("止盈卖点", "立即减仓", "") == "sell"
    assert SignalFeedbackEvaluator.infer_signal_direction("突破买点", "考虑建仓", "") == "buy"
    assert SignalFeedbackEvaluator.infer_signal_direction("观察", "等待", "") == "unknown"


def test_run_feedback_generates_reports(tmp_path: Path):
    quant_db_path = tmp_path / "quant.db"
    rec_db_path = tmp_path / "rec.db"
    _prepare_quant_db(quant_db_path)
    _prepare_rec_db(rec_db_path)

    evaluator = SignalFeedbackEvaluator(
        db=_SimpleDB(quant_db_path),
        recommendation_db_path=str(rec_db_path),
        persist_to_db=False,
    )

    result = evaluator.run_feedback(
        start_date="20260101",
        end_date="20260107",
        top_n_per_day=10,
        recommendation_horizons=[2],
        signal_horizons=[1],
        out_dir=str(tmp_path),
        persist=False,
    )

    assert result["status"] == "success"
    assert result["detail_count"] > 0
    assert result["summary_count"] > 0
    stats = result.get("stats", [])
    assert any(s.get("source_type") == SignalFeedbackEvaluator.SOURCE_PRE_MARKET for s in stats)
    assert any(s.get("source_type") == SignalFeedbackEvaluator.SOURCE_INTRADAY for s in stats)
    signal_meta = result.get("meta", {}).get("intraday_signal", {})
    assert signal_meta.get("signal_type_stats")
    assert signal_meta.get("window_stats")
    assert signal_meta.get("insights")
    assert signal_meta["insights"].get("conclusions")
    assert any(item.get("window_minutes") == 5 for item in signal_meta.get("window_stats", []))
    assert any(item.get("signal_type") == "买入信号" for item in signal_meta.get("signal_type_stats", []))
    assert result.get("intraday_insights", {}).get("best_window", {}).get("window_minutes") == 30

    files = result.get("files", {})
    assert Path(files["markdown"]).exists()
    assert Path(files["json"]).exists()
    assert Path(files["csv"]).exists()
