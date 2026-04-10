# -*- coding: utf-8 -*-
"""
基于真实分时数据的模拟实盘回放与压力测试工具。
"""

from __future__ import annotations

import sqlite3
import tracemalloc
from time import perf_counter
from typing import Dict, List, Optional, Tuple

import pandas as pd

from src.core.runtime_monitor import IncidentCategory, RuntimeHealthMonitor
from src.modules.backtest.history_recommendation_db import HistoryRecommendationDB
from src.modules.optimized_buy_signals import IntradayData, OptimizedBuySignals


class LiveReplayEngine:
    """使用项目内真实分时库进行盘中信号回放。"""

    def __init__(
        self,
        db_path: str = "data/history_recommendation.db",
        signal_detector: Optional[OptimizedBuySignals] = None,
        runtime_monitor: Optional[RuntimeHealthMonitor] = None,
        warmup_bars: int = 30,
        debounce_window: int = 2,
    ):
        self.db_path = str(db_path)
        self.db = HistoryRecommendationDB(self.db_path)
        self.signal_detector = signal_detector or OptimizedBuySignals()
        self.runtime_monitor = runtime_monitor
        self.warmup_bars = warmup_bars
        self.debounce_window = debounce_window

    def list_available_sessions(
        self,
        symbol: Optional[str] = None,
        limit: int = 20,
        min_rows: int = 120,
    ) -> List[Dict]:
        """列出可回放的真实分时会话。"""
        conn = sqlite3.connect(self.db_path)
        try:
            sql = """
                SELECT symbol, trade_date, COUNT(*) AS rows_count,
                       MIN(trade_time) AS min_time, MAX(trade_time) AS max_time
                FROM intraday_data
                WHERE (? IS NULL OR symbol = ?)
                GROUP BY symbol, trade_date
                HAVING COUNT(*) >= ?
                ORDER BY trade_date DESC, rows_count DESC, symbol ASC
                LIMIT ?
            """
            rows = conn.execute(sql, (symbol, symbol, min_rows, limit)).fetchall()
        finally:
            conn.close()

        return [
            {
                "symbol": row[0],
                "trade_date": row[1],
                "rows_count": int(row[2]),
                "min_time": row[3],
                "max_time": row[4],
            }
            for row in rows
        ]

    def load_session_data(self, symbol: str, trade_date: str) -> pd.DataFrame:
        """读取单日真实分时数据。"""
        conn = sqlite3.connect(self.db_path)
        try:
            query = """
                SELECT symbol, trade_time, trade_date, open, high, low, close, volume, amount
                FROM intraday_data
                WHERE symbol = ? AND trade_date = ?
                ORDER BY trade_time ASC
            """
            df = pd.read_sql_query(query, conn, params=[symbol, trade_date])
        finally:
            conn.close()

        if not df.empty:
            df["trade_time"] = pd.to_datetime(df["trade_time"])
        return df

    def resolve_session(
        self,
        symbol: Optional[str] = None,
        trade_date: Optional[str] = None,
        min_rows: int = 120,
    ) -> Tuple[str, str]:
        """解析默认回放会话。"""
        if symbol and trade_date:
            return symbol, trade_date

        sessions = self.list_available_sessions(symbol=symbol, limit=1, min_rows=min_rows)
        if not sessions:
            raise ValueError("未找到满足条件的真实分时回放会话")

        session = sessions[0]
        return session["symbol"], session["trade_date"]

    @staticmethod
    def build_intraday_data(frame: pd.DataFrame) -> IntradayData:
        """将真实分时 DataFrame 转为信号检测器需要的结构。"""
        ordered = frame.sort_values("trade_time").reset_index(drop=True)
        return IntradayData(
            price=ordered["close"].astype(float).to_numpy(),
            volume=ordered["volume"].fillna(0).astype(float).to_numpy(),
            high=ordered["high"].fillna(ordered["close"]).astype(float).to_numpy(),
            low=ordered["low"].fillna(ordered["close"]).astype(float).to_numpy(),
            timestamp=ordered["trade_time"].to_numpy(),
        )

    def replay_session(
        self,
        symbol: Optional[str] = None,
        trade_date: Optional[str] = None,
        market_score: float = 65.0,
        min_rows: int = 120,
        max_signals: int = 20,
    ) -> Dict:
        """按分钟顺序回放一段真实盘中会话。"""
        symbol, trade_date = self.resolve_session(symbol=symbol, trade_date=trade_date, min_rows=min_rows)
        intraday_df = self.load_session_data(symbol, trade_date)
        if intraday_df.empty:
            raise ValueError(f"{symbol} {trade_date} 没有找到真实分时数据")

        if len(intraday_df) <= self.warmup_bars:
            raise ValueError(
                f"{symbol} {trade_date} 分时记录不足，至少需要 {self.warmup_bars + 1} 条，实际 {len(intraday_df)} 条"
            )

        signal_history: List[bool] = []
        detected_signals: List[Dict] = []
        latency_samples_ms: List[float] = []
        error_count = 0
        last_emitted_signature: Optional[Tuple[str, str]] = None

        for index in range(self.warmup_bars, len(intraday_df)):
            frame = intraday_df.iloc[: index + 1].copy()
            current_bar = frame.iloc[-1]
            intraday_data = self.build_intraday_data(frame)

            started_at = perf_counter()
            try:
                signal = self.signal_detector.mutual_exclusive_signal(
                    intraday_data,
                    current_bar["trade_time"].to_pydatetime(),
                    market_score=market_score,
                )
            except Exception as exc:
                error_count += 1
                if self.runtime_monitor:
                    self.runtime_monitor.record_incident(
                        exception=exc,
                        title="模拟实盘回放失败",
                        component="replay.session",
                        category=IncidentCategory.MONITOR,
                        context={
                            "symbol": symbol,
                            "trade_date": trade_date,
                            "bar_index": index,
                        },
                    )
                continue

            latency_ms = (perf_counter() - started_at) * 1000
            latency_samples_ms.append(latency_ms)
            signal_history.append(bool(signal.signal))

            if not signal.signal:
                continue

            if not self.signal_detector.debounce(signal_history, window=self.debounce_window):
                continue

            signal_signature = (
                signal.signal_type or "unknown",
                current_bar["trade_time"].strftime("%Y-%m-%d %H:%M"),
            )
            if signal_signature == last_emitted_signature:
                continue

            detected_signals.append(
                {
                    "symbol": symbol,
                    "trade_date": trade_date,
                    "trade_time": current_bar["trade_time"].strftime("%Y-%m-%d %H:%M:%S"),
                    "price": round(float(current_bar["close"]), 4),
                    "signal_type": signal.signal_type,
                    "confidence": round(float(signal.confidence), 4),
                    "reason": signal.reason,
                    "details": signal.details or {},
                }
            )
            last_emitted_signature = signal_signature

            if len(detected_signals) >= max_signals:
                break

        summary = {
            "symbol": symbol,
            "trade_date": trade_date,
            "bars_total": int(len(intraday_df)),
            "bars_processed": max(0, int(len(intraday_df) - self.warmup_bars)),
            "warmup_bars": self.warmup_bars,
            "signals_detected": len(detected_signals),
            "error_count": error_count,
            "avg_latency_ms": round(sum(latency_samples_ms) / max(len(latency_samples_ms), 1), 3),
            "p95_latency_ms": round(self._percentile(latency_samples_ms, 95), 3),
            "max_latency_ms": round(max(latency_samples_ms) if latency_samples_ms else 0.0, 3),
            "first_signal_time": detected_signals[0]["trade_time"] if detected_signals else None,
            "last_signal_time": detected_signals[-1]["trade_time"] if detected_signals else None,
            "signals": detected_signals,
        }

        if self.runtime_monitor:
            self.runtime_monitor.record_success(
                "replay.session",
                context={
                    "symbol": symbol,
                    "trade_date": trade_date,
                    "signals_detected": len(detected_signals),
                },
            )

        return summary

    def stress_test(
        self,
        session_limit: int = 20,
        loop_count: int = 1,
        min_rows: int = 120,
        market_score: float = 65.0,
    ) -> Dict:
        """对多段真实会话执行回放压力测试。"""
        sessions = self.list_available_sessions(limit=session_limit, min_rows=min_rows)
        if not sessions:
            raise ValueError("未找到可用于压力测试的真实分时会话")

        tracemalloc.start()
        started_at = perf_counter()

        total_bars = 0
        total_signals = 0
        total_failures = 0
        latency_samples = []
        session_reports = []

        for _ in range(max(loop_count, 1)):
            for session in sessions:
                try:
                    report = self.replay_session(
                        symbol=session["symbol"],
                        trade_date=session["trade_date"],
                        market_score=market_score,
                        min_rows=min_rows,
                    )
                    session_reports.append(report)
                    total_bars += report["bars_processed"]
                    total_signals += report["signals_detected"]
                    latency_samples.append(report["avg_latency_ms"])
                except Exception:
                    total_failures += 1

        current_memory, peak_memory = tracemalloc.get_traced_memory()
        tracemalloc.stop()

        duration_seconds = perf_counter() - started_at
        summary = {
            "sessions_selected": len(sessions),
            "loop_count": max(loop_count, 1),
            "session_runs": len(session_reports),
            "failures": total_failures,
            "total_bars_processed": total_bars,
            "total_signals_detected": total_signals,
            "duration_seconds": round(duration_seconds, 3),
            "bars_per_second": round(total_bars / duration_seconds, 3) if duration_seconds else 0.0,
            "avg_session_latency_ms": round(sum(latency_samples) / max(len(latency_samples), 1), 3),
            "p95_session_latency_ms": round(self._percentile(latency_samples, 95), 3),
            "peak_memory_mb": round(peak_memory / 1024 / 1024, 3),
            "current_memory_mb": round(current_memory / 1024 / 1024, 3),
            "sample_sessions": [
                {
                    "symbol": report["symbol"],
                    "trade_date": report["trade_date"],
                    "signals_detected": report["signals_detected"],
                    "avg_latency_ms": report["avg_latency_ms"],
                }
                for report in session_reports[:5]
            ],
        }

        if self.runtime_monitor:
            self.runtime_monitor.record_success(
                "replay.stress_test",
                context={
                    "session_runs": len(session_reports),
                    "failures": total_failures,
                    "bars_per_second": summary["bars_per_second"],
                },
            )

        return summary

    @staticmethod
    def _percentile(values: List[float], percentile: int) -> float:
        """计算简单百分位。"""
        if not values:
            return 0.0
        ordered = sorted(values)
        index = int((len(ordered) - 1) * percentile / 100)
        return float(ordered[index])


def build_live_replay_engine(
    db_path: str = "data/history_recommendation.db",
    runtime_monitor: Optional[RuntimeHealthMonitor] = None,
) -> LiveReplayEngine:
    """构建默认回放引擎。"""
    return LiveReplayEngine(db_path=db_path, runtime_monitor=runtime_monitor)
