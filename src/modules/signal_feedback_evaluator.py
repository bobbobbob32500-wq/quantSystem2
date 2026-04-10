# -*- coding: utf-8 -*-
"""
信号收益闭环评估模块

目标：
1. 盘前推荐闭环：T日推荐，T+1开盘入场，T+N收盘离场；
2. 盘中信号闭环：按买/卖方向评估后续N日方向有效性；
3. 输出统一报告（md/json/csv），并可选落库用于后续看板。
"""

from __future__ import annotations

import json
import sqlite3
from bisect import bisect_left
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import pandas as pd

from src.core.config import ConfigManager
from src.core.database import DatabaseManager
from src.core.logger import get_logger
from src.modules.position_controller import PositionController

logger = get_logger("signal_feedback")


@dataclass
class FeedbackStat:
    """闭环统计条目。"""

    source_type: str
    direction: str
    horizon: int
    sample_count: int
    win_rate: float
    mean_gross_return: float
    mean_net_return: float
    median_net_return: float
    p25_net_return: float
    p75_net_return: float
    mean_mfe: float
    mean_mae: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source_type": self.source_type,
            "direction": self.direction,
            "horizon": int(self.horizon),
            "sample_count": int(self.sample_count),
            "win_rate": float(self.win_rate),
            "mean_gross_return": float(self.mean_gross_return),
            "mean_net_return": float(self.mean_net_return),
            "median_net_return": float(self.median_net_return),
            "p25_net_return": float(self.p25_net_return),
            "p75_net_return": float(self.p75_net_return),
            "mean_mfe": float(self.mean_mfe),
            "mean_mae": float(self.mean_mae),
        }


class SignalFeedbackEvaluator:
    """信号收益闭环评估器。"""

    SOURCE_PRE_MARKET = "pre_market_recommendation"
    SOURCE_INTRADAY = "intraday_signal"
    DEFAULT_INTRADAY_WINDOWS = [5, 15, 30]

    def __init__(
        self,
        config: ConfigManager = None,
        db: DatabaseManager = None,
        recommendation_db_path: Optional[str] = None,
        persist_to_db: Optional[bool] = None,
    ):
        if config is None:
            config = ConfigManager()
        if db is None:
            db = DatabaseManager(config)

        self.config = config
        self.db = db
        self.position_controller = PositionController(config, db)
        self.project_root = Path(__file__).resolve().parents[2]
        self._market_regime_cache: Dict[str, str] = {}

        cfg_rec_path = recommendation_db_path or config.get(
            "feedback.history_recommendation_db", "data/history_recommendation.db"
        )
        self.recommendation_db_path = self._resolve_path(cfg_rec_path)

        self.buy_slippage = float(config.get("feedback.buy_slippage", 0.001))
        self.sell_slippage = float(config.get("feedback.sell_slippage", 0.001))
        self.buy_fee_rate = float(config.get("feedback.buy_fee_rate", 0.0003))
        self.sell_fee_rate = float(config.get("feedback.sell_fee_rate", 0.0003))
        self.stamp_tax_rate = float(config.get("feedback.stamp_tax_rate", 0.001))

        self.default_recommendation_horizons = self._parse_horizons(
            config.get("feedback.recommendation_horizons", [2, 3, 4, 5]),
            default=[2, 3, 4, 5],
            min_h=1,
        )
        self.default_signal_horizons = self._parse_horizons(
            config.get("feedback.signal_horizons", [1, 2, 3]),
            default=[1, 2, 3],
            min_h=1,
        )
        self.default_top_n_per_day = int(config.get("feedback.top_n_per_day", 10))
        self.default_lookback_days = int(config.get("feedback.default_lookback_days", 90))
        self.report_dir = self._resolve_path(config.get("feedback.report_dir", "reports"))
        self.persist_to_db = (
            bool(config.get("feedback.persist_to_db", True))
            if persist_to_db is None
            else bool(persist_to_db)
        )

        if self.persist_to_db:
            self._ensure_feedback_tables()

        logger.info(
            "信号闭环评估器初始化完成 | rec_db=%s | persist_to_db=%s",
            self.recommendation_db_path.as_posix(),
            self.persist_to_db,
        )

    @staticmethod
    def _norm_date(value: Any) -> Optional[str]:
        if value is None:
            return None
        s = str(value).strip()
        if not s:
            return None
        digits = "".join(ch for ch in s if ch.isdigit())
        if len(digits) < 8:
            return None
        return digits[:8]

    @staticmethod
    def _normalize_ts_code(ts_code: Any) -> str:
        if ts_code is None:
            return ""
        s = str(ts_code).strip().upper()
        if not s:
            return ""
        if "." in s:
            return s
        if len(s) == 6 and s.isdigit():
            if s.startswith(("6", "9")):
                return f"{s}.SH"
            return f"{s}.SZ"
        return s

    @staticmethod
    def _parse_horizons(raw: Any, default: Sequence[int], min_h: int = 1) -> List[int]:
        values: List[int] = []
        if isinstance(raw, (list, tuple)):
            for x in raw:
                try:
                    values.append(int(x))
                except Exception:
                    continue
        elif raw is not None:
            for token in str(raw).split(","):
                token = token.strip()
                if not token:
                    continue
                try:
                    values.append(int(token))
                except Exception:
                    continue
        if not values:
            values = list(default)
        return sorted(set([h for h in values if h >= int(min_h)]))

    def _resolve_path(self, path_value: str) -> Path:
        p = Path(str(path_value))
        if p.is_absolute():
            return p
        return self.project_root / p

    @staticmethod
    def _normalize_intraday_symbol(symbol: Any) -> str:
        if symbol is None:
            return ""
        text = str(symbol).strip().upper()
        if not text:
            return ""
        if "." in text:
            text = text.split(".", 1)[0]
        return text

    @staticmethod
    def infer_signal_direction(signal_type: str, suggestion: str = "", trigger_reason: str = "") -> str:
        """根据信号文本推断方向：buy/sell/unknown。"""
        text = f"{signal_type or ''} {suggestion or ''} {trigger_reason or ''}".lower()

        sell_keywords = ["卖", "止损", "止盈", "清仓", "减仓", "离场", "风控", "回撤"]
        buy_keywords = ["买", "加仓", "建仓", "低吸", "突破", "介入"]

        if any(word in text for word in sell_keywords):
            return "sell"
        if any(word in text for word in buy_keywords):
            return "buy"
        return "unknown"

    def _ensure_feedback_tables(self) -> None:
        self.db.execute(
            """
            CREATE TABLE IF NOT EXISTS signal_feedback_run (
                run_id TEXT PRIMARY KEY,
                start_date TEXT,
                end_date TEXT,
                recommendation_count INTEGER DEFAULT 0,
                signal_count INTEGER DEFAULT 0,
                detail_count INTEGER DEFAULT 0,
                summary_count INTEGER DEFAULT 0,
                report_md_path TEXT,
                report_json_path TEXT,
                report_csv_path TEXT,
                meta_json TEXT,
                created_time TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        self.db.execute(
            """
            CREATE TABLE IF NOT EXISTS signal_feedback_summary (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL,
                source_type TEXT NOT NULL,
                direction TEXT NOT NULL,
                horizon INTEGER NOT NULL,
                sample_count INTEGER NOT NULL,
                win_rate REAL,
                mean_gross_return REAL,
                mean_net_return REAL,
                median_net_return REAL,
                p25_net_return REAL,
                p75_net_return REAL,
                mean_mfe REAL,
                mean_mae REAL,
                created_time TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        self.db.execute(
            """
            CREATE TABLE IF NOT EXISTS signal_feedback_detail (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL,
                source_type TEXT NOT NULL,
                direction TEXT NOT NULL,
                horizon INTEGER NOT NULL,
                ts_code TEXT,
                name TEXT,
                signal_id INTEGER,
                signal_type TEXT,
                signal_time TEXT,
                signal_date TEXT,
                recommendation_score REAL,
                trigger_reason TEXT,
                suggestion TEXT,
                entry_date TEXT,
                exit_date TEXT,
                entry_price REAL,
                exit_price REAL,
                gross_return REAL,
                net_return REAL,
                mfe REAL,
                mae REAL,
                is_win INTEGER,
                extra_json TEXT,
                created_time TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        self.db.execute(
            "CREATE INDEX IF NOT EXISTS idx_feedback_summary_run ON signal_feedback_summary(run_id)"
        )
        self.db.execute(
            "CREATE INDEX IF NOT EXISTS idx_feedback_detail_run ON signal_feedback_detail(run_id)"
        )

    @staticmethod
    def _mean(series: pd.Series) -> float:
        if series.empty:
            return 0.0
        return float(series.mean())

    @staticmethod
    def _quantile(series: pd.Series, q: float) -> float:
        if series.empty:
            return 0.0
        return float(series.quantile(q))

    @staticmethod
    def _chunked(items: Sequence[str], size: int = 800) -> List[List[str]]:
        chunks: List[List[str]] = []
        arr = list(items)
        for i in range(0, len(arr), max(1, int(size))):
            chunks.append(arr[i : i + max(1, int(size))])
        return chunks

    def _get_trade_calendar(self) -> List[str]:
        calendar_df = self.db.query_to_dataframe(
            "SELECT DISTINCT trade_date FROM stock_daily ORDER BY trade_date"
        )
        if calendar_df.empty:
            return []
        return [
            d for d in calendar_df["trade_date"].map(self._norm_date).tolist() if d
        ]

    def _load_market_daily(
        self,
        symbols: Sequence[str],
        date_min: str,
        date_max: str,
    ) -> pd.DataFrame:
        symbols = [self._normalize_ts_code(s) for s in symbols if self._normalize_ts_code(s)]
        if not symbols:
            return pd.DataFrame()

        frames: List[pd.DataFrame] = []
        sql_template = """
            SELECT ts_code, trade_date, open, high, low, close
            FROM stock_daily
            WHERE ts_code IN ({placeholders})
              AND trade_date >= ?
              AND trade_date <= ?
        """

        for chunk in self._chunked(sorted(set(symbols)), size=800):
            placeholders = ",".join(["?"] * len(chunk))
            sql = sql_template.format(placeholders=placeholders)
            params: Tuple[Any, ...] = tuple(chunk + [date_min, date_max])
            sub = self.db.query_to_dataframe(sql, params)
            if not sub.empty:
                frames.append(sub)

        if not frames:
            return pd.DataFrame()

        df = pd.concat(frames, ignore_index=True)
        df["ts_code"] = df["ts_code"].map(self._normalize_ts_code)
        df["trade_date"] = df["trade_date"].map(self._norm_date)
        for col in ("open", "high", "low", "close"):
            df[col] = pd.to_numeric(df[col], errors="coerce")
        df = df.dropna(subset=["ts_code", "trade_date", "open", "high", "low", "close"])
        return df

    @staticmethod
    def _build_price_map(price_df: pd.DataFrame) -> Dict[Tuple[str, str], Dict[str, float]]:
        price_map: Dict[Tuple[str, str], Dict[str, float]] = {}
        for row in price_df.to_dict("records"):
            key = (str(row["ts_code"]), str(row["trade_date"]))
            price_map[key] = {
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
            }
        return price_map

    def _long_net_return(self, entry_price: float, exit_price: float) -> Optional[float]:
        if entry_price <= 0 or exit_price <= 0:
            return None
        buy_factor = 1.0 + self.buy_slippage + self.buy_fee_rate
        sell_factor = 1.0 - self.sell_slippage - self.sell_fee_rate - self.stamp_tax_rate
        if buy_factor <= 0 or sell_factor <= 0:
            return None
        return exit_price * sell_factor / (entry_price * buy_factor) - 1.0

    def _short_net_return(self, sell_price: float, buy_back_price: float) -> Optional[float]:
        if sell_price <= 0 or buy_back_price <= 0:
            return None
        sell_factor = 1.0 - self.sell_slippage - self.sell_fee_rate - self.stamp_tax_rate
        buy_factor = 1.0 + self.buy_slippage + self.buy_fee_rate
        if buy_factor <= 0 or sell_factor <= 0:
            return None
        return sell_price * sell_factor / (buy_back_price * buy_factor) - 1.0

    def _load_recommendations(
        self,
        start_date: str,
        end_date: str,
        top_n_per_day: int,
        strategy_type: Optional[str] = None,
    ) -> pd.DataFrame:
        if not self.recommendation_db_path.exists() or self.recommendation_db_path.stat().st_size <= 0:
            logger.warning("历史推荐库不存在或为空: %s", self.recommendation_db_path.as_posix())
            return pd.DataFrame()

        conn = sqlite3.connect(str(self.recommendation_db_path))
        try:
            params: List[Any] = []
            sql = """
                SELECT symbol, name, recommendation_date, recommendation_score, strategy_type
                FROM recommendations
                WHERE 1=1
            """
            if strategy_type:
                sql += " AND strategy_type = ?"
                params.append(str(strategy_type))

            rec_df = pd.read_sql_query(sql, conn, params=params)
        finally:
            conn.close()

        if rec_df.empty:
            return rec_df

        rec_df["symbol"] = rec_df["symbol"].map(self._normalize_ts_code)
        rec_df["rec_date"] = rec_df["recommendation_date"].map(self._norm_date)
        rec_df["recommendation_score"] = pd.to_numeric(rec_df["recommendation_score"], errors="coerce").fillna(0.0)
        rec_df = rec_df.dropna(subset=["symbol", "rec_date"])

        rec_df = rec_df[(rec_df["rec_date"] >= start_date) & (rec_df["rec_date"] <= end_date)].copy()
        if rec_df.empty:
            return rec_df

        rec_df = rec_df.sort_values(
            ["rec_date", "recommendation_score", "symbol"],
            ascending=[True, False, True],
        )
        if top_n_per_day > 0:
            rec_df = (
                rec_df.groupby("rec_date", as_index=False, group_keys=False)
                .head(int(top_n_per_day))
                .reset_index(drop=True)
            )
        return rec_df

    def _load_signal_history(self, start_date: str, end_date: str) -> pd.DataFrame:
        start_ts = f"{start_date[:4]}-{start_date[4:6]}-{start_date[6:]} 00:00:00"
        end_ts = f"{end_date[:4]}-{end_date[4:6]}-{end_date[6:]} 23:59:59"
        sql = """
            SELECT id, ts_code, name, signal_type, signal_time, trigger_reason, suggestion
            FROM signal_history
            WHERE signal_time >= ? AND signal_time <= ?
            ORDER BY signal_time ASC, id ASC
        """
        df = self.db.query_to_dataframe(sql, (start_ts, end_ts))
        if df.empty:
            return df

        df["ts_code"] = df["ts_code"].map(self._normalize_ts_code)
        df["signal_date"] = df["signal_time"].map(self._norm_date)
        df["direction"] = df.apply(
            lambda row: self.infer_signal_direction(
                row.get("signal_type", ""),
                row.get("suggestion", ""),
                row.get("trigger_reason", ""),
            ),
            axis=1,
        )
        df = df[df["direction"].isin(["buy", "sell"])].copy()
        return df

    def _load_intraday_bars(
        self,
        symbols: Sequence[str],
        start_date: str,
        end_date: str,
    ) -> pd.DataFrame:
        unique_symbols = sorted(
            {
                self._normalize_intraday_symbol(symbol)
                for symbol in (symbols or [])
                if self._normalize_intraday_symbol(symbol)
            }
        )
        if not unique_symbols:
            return pd.DataFrame()

        date_start = f"{start_date[:4]}-{start_date[4:6]}-{start_date[6:]}"
        date_end = f"{end_date[:4]}-{end_date[4:6]}-{end_date[6:]}"
        placeholders = ",".join(["?"] * len(unique_symbols))
        sql = f"""
            SELECT symbol, trade_time, trade_date, open, high, low, close, volume, amount
            FROM intraday_data
            WHERE symbol IN ({placeholders})
              AND trade_date >= ?
              AND trade_date <= ?
            ORDER BY symbol ASC, trade_time ASC
        """
        conn = sqlite3.connect(str(self.recommendation_db_path))
        try:
            df = pd.read_sql_query(sql, conn, params=tuple(unique_symbols) + (date_start, date_end))
        finally:
            conn.close()
        if df.empty:
            return df

        df["symbol"] = df["symbol"].map(self._normalize_intraday_symbol)
        df["trade_time"] = pd.to_datetime(df["trade_time"], errors="coerce")
        df = df.dropna(subset=["symbol", "trade_time"]).copy()
        for col in ("open", "high", "low", "close", "volume", "amount"):
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        df["trade_date"] = df["trade_time"].dt.strftime("%Y%m%d")
        df = df.sort_values(["symbol", "trade_time"]).reset_index(drop=True)
        return df

    def _summarize_intraday_signal_type(
        self,
        detail_df: pd.DataFrame,
        min_samples: int = 1,
    ) -> List[Dict[str, Any]]:
        if detail_df.empty or "signal_type" not in detail_df.columns:
            return []

        rows: List[Dict[str, Any]] = []
        grouped = detail_df.groupby(["signal_type", "direction", "horizon"], dropna=False)
        for (signal_type, direction, horizon), group in grouped:
            if len(group) < int(min_samples):
                continue
            net_series = pd.to_numeric(group["net_return"], errors="coerce").dropna()
            mfe_series = pd.to_numeric(group["mfe"], errors="coerce").dropna()
            mae_series = pd.to_numeric(group["mae"], errors="coerce").dropna()
            rows.append(
                {
                    "signal_type": str(signal_type or "unknown"),
                    "direction": str(direction or "unknown"),
                    "horizon": int(horizon or 0),
                    "sample_count": int(len(group)),
                    "win_rate": float((net_series > 0).mean()) if not net_series.empty else 0.0,
                    "mean_net_return": self._mean(net_series),
                    "median_net_return": self._quantile(net_series, 0.5),
                    "mean_mfe": self._mean(mfe_series),
                    "mean_mae": self._mean(mae_series),
                }
            )
        rows.sort(
            key=lambda item: (
                item["signal_type"],
                item["direction"],
                item["horizon"],
            )
        )
        return rows

    def _evaluate_intraday_signal_windows(
        self,
        signal_df: pd.DataFrame,
        windows: Sequence[int],
    ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        if signal_df.empty:
            return [], {"error": "no_intraday_signals"}

        minute_windows = sorted(set(int(x) for x in (windows or []) if int(x) > 0))
        if not minute_windows:
            minute_windows = list(self.DEFAULT_INTRADAY_WINDOWS)
        max_window = max(minute_windows)

        signal_rows = signal_df.copy()
        signal_rows["signal_dt"] = pd.to_datetime(signal_rows["signal_time"], errors="coerce")
        signal_rows = signal_rows.dropna(subset=["signal_dt"]).copy()
        if signal_rows.empty:
            return [], {"error": "invalid_signal_time"}

        symbols = [self._normalize_intraday_symbol(x) for x in signal_rows["ts_code"].tolist()]
        date_min = str(signal_rows["signal_date"].min() or "")
        date_max = str(signal_rows["signal_date"].max() or "")
        minute_df = self._load_intraday_bars(symbols=symbols, start_date=date_min, end_date=date_max)
        if minute_df.empty:
            return [], {"error": "no_intraday_bars"}

        grouped_map: Dict[tuple[str, str], pd.DataFrame] = {}
        for (symbol, trade_date), group in minute_df.groupby(["symbol", "trade_date"], sort=False):
            grouped_map[(str(symbol), str(trade_date))] = group.sort_values("trade_time").reset_index(drop=True)

        detail_rows: List[Dict[str, Any]] = []
        matched_signals = 0
        matched_windows = 0

        for sig in signal_rows.to_dict("records"):
            symbol = self._normalize_intraday_symbol(sig.get("ts_code"))
            trade_date = str(sig.get("signal_date", "") or "")
            frame = grouped_map.get((symbol, trade_date))
            if frame is None or frame.empty:
                continue

            signal_dt = pd.Timestamp(sig.get("signal_dt"))
            eligible = frame[frame["trade_time"] >= signal_dt].copy()
            if eligible.empty:
                continue
            entry_row = eligible.iloc[0]
            entry_price = float(entry_row.get("close") or 0.0)
            if entry_price <= 0:
                continue

            matched_signals += 1
            direction = str(sig.get("direction", "buy") or "buy")
            signal_type = str(sig.get("signal_type", "") or "unknown")

            for window in minute_windows:
                if len(eligible) <= int(window):
                    continue
                window_frame = eligible.iloc[: int(window) + 1].copy()
                exit_row = window_frame.iloc[-1]
                exit_price = float(exit_row.get("close") or 0.0)
                if exit_price <= 0:
                    continue

                highs = pd.to_numeric(window_frame["high"], errors="coerce").dropna()
                lows = pd.to_numeric(window_frame["low"], errors="coerce").dropna()
                if highs.empty or lows.empty:
                    continue

                gross_forward = exit_price / entry_price - 1.0
                long_mfe = float(highs.max()) / entry_price - 1.0
                long_mae = float(lows.min()) / entry_price - 1.0

                if direction == "sell":
                    net_ret = -gross_forward
                    mfe = -long_mae
                    mae = -long_mfe
                else:
                    net_ret = gross_forward
                    mfe = long_mfe
                    mae = long_mae

                matched_windows += 1
                detail_rows.append(
                    {
                        "signal_type": signal_type,
                        "direction": direction,
                        "window_minutes": int(window),
                        "sample_count": 1,
                        "net_return": float(net_ret),
                        "mfe": float(mfe),
                        "mae": float(mae),
                        "entry_time": pd.Timestamp(entry_row["trade_time"]).strftime("%Y-%m-%d %H:%M:%S"),
                        "exit_time": pd.Timestamp(exit_row["trade_time"]).strftime("%Y-%m-%d %H:%M:%S"),
                        "entry_price": entry_price,
                        "exit_price": exit_price,
                    }
                )

        detail_df = pd.DataFrame(detail_rows)
        if detail_df.empty:
            return [], {
                "windows": minute_windows,
                "matched_signals": int(matched_signals),
                "matched_windows": 0,
                "error": "no_intraday_window_match",
            }

        summary_rows: List[Dict[str, Any]] = []
        grouped = detail_df.groupby(["signal_type", "direction", "window_minutes"], dropna=False)
        for (signal_type, direction, window), group in grouped:
            net_series = pd.to_numeric(group["net_return"], errors="coerce").dropna()
            mfe_series = pd.to_numeric(group["mfe"], errors="coerce").dropna()
            mae_series = pd.to_numeric(group["mae"], errors="coerce").dropna()
            summary_rows.append(
                {
                    "signal_type": str(signal_type or "unknown"),
                    "direction": str(direction or "unknown"),
                    "window_minutes": int(window or 0),
                    "sample_count": int(len(group)),
                    "win_rate": float((net_series > 0).mean()) if not net_series.empty else 0.0,
                    "mean_net_return": self._mean(net_series),
                    "median_net_return": self._quantile(net_series, 0.5),
                    "mean_mfe": self._mean(mfe_series),
                    "mean_mae": self._mean(mae_series),
                }
            )
        summary_rows.sort(
            key=lambda item: (
                item["signal_type"],
                item["direction"],
                item["window_minutes"],
            )
        )
        return summary_rows, {
            "windows": minute_windows,
            "matched_signals": int(matched_signals),
            "matched_windows": int(matched_windows),
        }

    @staticmethod
    def _pick_best_row(
        rows: Sequence[Dict[str, Any]],
        value_key: str = "mean_net_return",
        min_samples: int = 1,
    ) -> Optional[Dict[str, Any]]:
        candidates = [dict(item) for item in (rows or []) if int(item.get("sample_count", 0) or 0) >= int(min_samples)]
        if not candidates:
            candidates = [dict(item) for item in (rows or [])]
        if not candidates:
            return None
        candidates.sort(
            key=lambda item: (
                float(item.get(value_key, -999.0) or -999.0),
                float(item.get("win_rate", 0.0) or 0.0),
                int(item.get("sample_count", 0) or 0),
            ),
            reverse=True,
        )
        return candidates[0]

    def _build_intraday_insights(
        self,
        intraday_type_stats: Sequence[Dict[str, Any]],
        intraday_window_stats: Sequence[Dict[str, Any]],
    ) -> Dict[str, Any]:
        best_type = self._pick_best_row(intraday_type_stats, value_key="mean_net_return", min_samples=3)
        best_window = self._pick_best_row(intraday_window_stats, value_key="mean_net_return", min_samples=3)

        subtype_rank = []
        for item in sorted(
            [dict(row) for row in (intraday_type_stats or [])],
            key=lambda row: (
                float(row.get("mean_net_return", -999.0) or -999.0),
                int(row.get("sample_count", 0) or 0),
            ),
            reverse=True,
        )[:5]:
            subtype_rank.append(
                {
                    "signal_type": str(item.get("signal_type", "") or "unknown"),
                    "direction": str(item.get("direction", "") or "unknown"),
                    "horizon": int(item.get("horizon", 0) or 0),
                    "sample_count": int(item.get("sample_count", 0) or 0),
                    "win_rate": float(item.get("win_rate", 0.0) or 0.0),
                    "mean_net_return": float(item.get("mean_net_return", 0.0) or 0.0),
                }
            )

        window_rank = []
        for item in sorted(
            [dict(row) for row in (intraday_window_stats or [])],
            key=lambda row: (
                float(row.get("mean_net_return", -999.0) or -999.0),
                int(row.get("sample_count", 0) or 0),
            ),
            reverse=True,
        )[:5]:
            window_rank.append(
                {
                    "signal_type": str(item.get("signal_type", "") or "unknown"),
                    "direction": str(item.get("direction", "") or "unknown"),
                    "window_minutes": int(item.get("window_minutes", 0) or 0),
                    "sample_count": int(item.get("sample_count", 0) or 0),
                    "win_rate": float(item.get("win_rate", 0.0) or 0.0),
                    "mean_net_return": float(item.get("mean_net_return", 0.0) or 0.0),
                }
            )

        conclusions: List[str] = []
        if best_type:
            conclusions.append(
                f"当前盘中最优子类型为 `{best_type.get('signal_type', 'unknown')}`，"
                f"样本 `{int(best_type.get('sample_count', 0) or 0)}` 条，"
                f"胜率 `{float(best_type.get('win_rate', 0.0) or 0.0):.2%}`，"
                f"平均净收益 `{float(best_type.get('mean_net_return', 0.0) or 0.0):.2%}`。"
            )
        if best_window:
            conclusions.append(
                f"当前最优分钟窗口为 `{int(best_window.get('window_minutes', 0) or 0)} 分钟`，"
                f"对应子类型 `{best_window.get('signal_type', 'unknown')}`，"
                f"平均净收益 `{float(best_window.get('mean_net_return', 0.0) or 0.0):.2%}`。"
            )

        action_items: List[str] = []
        if best_type:
            win_rate = float(best_type.get("win_rate", 0.0) or 0.0)
            mean_ret = float(best_type.get("mean_net_return", 0.0) or 0.0)
            signal_type = str(best_type.get("signal_type", "") or "unknown")
            if win_rate >= 0.55 and mean_ret > 0:
                action_items.append(f"优先保留并加权 `{signal_type}`，可作为二次启动主推送形态。")
            else:
                action_items.append(f"`{signal_type}` 领先但优势仍不稳，建议继续累计样本后再做强制偏置。")
        if best_window:
            window = int(best_window.get("window_minutes", 0) or 0)
            if window > 0:
                action_items.append(f"后续盘中复盘优先跟踪信号后 `{window}` 分钟表现，作为最短验证窗口。")
        if not action_items:
            action_items.append("当前盘中样本仍偏少，建议继续积累实盘推送记录后再下结论。")

        return {
            "best_signal_type": best_type,
            "best_window": best_window,
            "subtype_ranking": subtype_rank,
            "window_ranking": window_rank,
            "conclusions": conclusions,
            "action_items": action_items,
        }

    def evaluate_pre_market_recommendations(
        self,
        start_date: str,
        end_date: str,
        top_n_per_day: int,
        horizons: Sequence[int],
        strategy_type: Optional[str] = None,
    ) -> Tuple[pd.DataFrame, List[FeedbackStat], Dict[str, Any]]:
        rec_df = self._load_recommendations(
            start_date=start_date,
            end_date=end_date,
            top_n_per_day=top_n_per_day,
            strategy_type=strategy_type,
        )
        if rec_df.empty:
            return pd.DataFrame(), [], {"error": "no_recommendations"}

        calendar = self._get_trade_calendar()
        if not calendar:
            return pd.DataFrame(), [], {"error": "no_trade_calendar"}
        date_to_idx = {d: i for i, d in enumerate(calendar)}
        max_h = max(horizons)

        rec_df = rec_df[rec_df["rec_date"].isin(date_to_idx.keys())].copy()
        if rec_df.empty:
            return pd.DataFrame(), [], {"error": "no_rec_date_in_trade_calendar"}

        rec_df["rec_idx"] = rec_df["rec_date"].map(date_to_idx)
        rec_df = rec_df[rec_df["rec_idx"] + max_h < len(calendar)].copy()
        if rec_df.empty:
            return pd.DataFrame(), [], {"error": "no_rec_with_enough_horizon"}

        date_min = calendar[int(rec_df["rec_idx"].min()) + 1]
        date_max = calendar[int(rec_df["rec_idx"].max()) + max_h]
        symbols = sorted(rec_df["symbol"].dropna().unique().tolist())
        market_df = self._load_market_daily(symbols=symbols, date_min=date_min, date_max=date_max)
        if market_df.empty:
            return pd.DataFrame(), [], {"error": "no_market_data_for_recommendations"}

        price_map = self._build_price_map(market_df)
        details: List[Dict[str, Any]] = []

        for rec in rec_df.to_dict("records"):
            symbol = str(rec["symbol"])
            rec_date = str(rec["rec_date"])
            rec_idx = int(rec["rec_idx"])

            entry_date = calendar[rec_idx + 1]
            entry_bar = price_map.get((symbol, entry_date))
            if not entry_bar:
                continue
            entry_price = float(entry_bar["open"])
            if entry_price <= 0:
                continue

            for h in horizons:
                exit_date = calendar[rec_idx + int(h)]
                exit_bar = price_map.get((symbol, exit_date))
                if not exit_bar:
                    continue
                exit_price = float(exit_bar["close"])
                if exit_price <= 0:
                    continue

                period_dates = calendar[rec_idx + 1 : rec_idx + int(h) + 1]
                highs: List[float] = []
                lows: List[float] = []
                for d in period_dates:
                    bar = price_map.get((symbol, d))
                    if not bar:
                        continue
                    highs.append(float(bar["high"]))
                    lows.append(float(bar["low"]))
                if not highs or not lows:
                    continue

                gross_ret = exit_price / entry_price - 1.0
                net_ret = self._long_net_return(entry_price, exit_price)
                if net_ret is None:
                    net_ret = gross_ret

                details.append(
                    {
                        "source_type": self.SOURCE_PRE_MARKET,
                        "direction": "buy",
                        "horizon": int(h),
                        "ts_code": symbol,
                        "name": rec.get("name", ""),
                        "signal_id": None,
                        "signal_type": "pre_market_selection",
                        "signal_time": f"{rec_date[:4]}-{rec_date[4:6]}-{rec_date[6:]} 09:00:00",
                        "signal_date": rec_date,
                        "recommendation_score": float(rec.get("recommendation_score", 0.0) or 0.0),
                        "trigger_reason": "",
                        "suggestion": "",
                        "entry_date": entry_date,
                        "exit_date": exit_date,
                        "entry_price": entry_price,
                        "exit_price": exit_price,
                        "gross_return": gross_ret,
                        "net_return": net_ret,
                        "mfe": max(highs) / entry_price - 1.0,
                        "mae": min(lows) / entry_price - 1.0,
                        "is_win": 1 if net_ret > 0 else 0,
                        "extra_json": json.dumps(
                            {
                                "rec_date": rec_date,
                                "strategy_type": rec.get("strategy_type", "unknown"),
                            },
                            ensure_ascii=False,
                        ),
                    }
                )

        detail_df = pd.DataFrame(details)
        stats = self._summarize(detail_df, self.SOURCE_PRE_MARKET) if not detail_df.empty else []
        meta = {
            "recommendation_db": self.recommendation_db_path.as_posix(),
            "recommendation_count": int(len(rec_df)),
            "detail_count": int(len(detail_df)),
            "date_range_rec": [
                str(rec_df["rec_date"].min()) if not rec_df.empty else "",
                str(rec_df["rec_date"].max()) if not rec_df.empty else "",
            ],
            "top_n_per_day": int(top_n_per_day),
            "horizons": list(horizons),
        }
        return detail_df, stats, meta

    def evaluate_intraday_signals(
        self,
        start_date: str,
        end_date: str,
        horizons: Sequence[int],
    ) -> Tuple[pd.DataFrame, List[FeedbackStat], Dict[str, Any]]:
        signal_df = self._load_signal_history(start_date=start_date, end_date=end_date)
        if signal_df.empty:
            return pd.DataFrame(), [], {"error": "no_intraday_signals"}

        calendar = self._get_trade_calendar()
        if not calendar:
            return pd.DataFrame(), [], {"error": "no_trade_calendar"}
        date_to_idx = {d: i for i, d in enumerate(calendar)}
        max_h = max(horizons)

        def _entry_idx(d: str) -> Optional[int]:
            if not d:
                return None
            idx = date_to_idx.get(d)
            if idx is not None:
                return int(idx)
            pos = bisect_left(calendar, d)
            if pos >= len(calendar):
                return None
            return int(pos)

        signal_df["entry_idx"] = signal_df["signal_date"].map(_entry_idx)
        signal_df = signal_df.dropna(subset=["entry_idx"]).copy()
        signal_df["entry_idx"] = signal_df["entry_idx"].astype(int)
        signal_df = signal_df[signal_df["entry_idx"] + max_h < len(calendar)].copy()
        if signal_df.empty:
            return pd.DataFrame(), [], {"error": "no_signal_with_enough_horizon"}

        date_min = calendar[int(signal_df["entry_idx"].min())]
        date_max = calendar[int(signal_df["entry_idx"].max()) + max_h]
        symbols = sorted(signal_df["ts_code"].dropna().unique().tolist())
        market_df = self._load_market_daily(symbols=symbols, date_min=date_min, date_max=date_max)
        if market_df.empty:
            return pd.DataFrame(), [], {"error": "no_market_data_for_signals"}

        price_map = self._build_price_map(market_df)
        details: List[Dict[str, Any]] = []

        for sig in signal_df.to_dict("records"):
            ts_code = str(sig.get("ts_code", ""))
            direction = str(sig.get("direction", "unknown"))
            entry_idx = int(sig.get("entry_idx", -1))
            if entry_idx < 0:
                continue

            entry_date = calendar[entry_idx]
            entry_bar = price_map.get((ts_code, entry_date))
            if not entry_bar:
                continue
            entry_price = float(entry_bar["close"])
            if entry_price <= 0:
                continue

            for h in horizons:
                exit_idx = entry_idx + int(h)
                if exit_idx >= len(calendar):
                    continue
                exit_date = calendar[exit_idx]
                exit_bar = price_map.get((ts_code, exit_date))
                if not exit_bar:
                    continue
                exit_price = float(exit_bar["close"])
                if exit_price <= 0:
                    continue

                period_dates = calendar[entry_idx : exit_idx + 1]
                highs: List[float] = []
                lows: List[float] = []
                for d in period_dates:
                    bar = price_map.get((ts_code, d))
                    if not bar:
                        continue
                    highs.append(float(bar["high"]))
                    lows.append(float(bar["low"]))
                if not highs or not lows:
                    continue

                gross_forward = exit_price / entry_price - 1.0
                long_mfe = max(highs) / entry_price - 1.0
                long_mae = min(lows) / entry_price - 1.0

                if direction == "sell":
                    gross_ret = -gross_forward
                    net_ret = self._short_net_return(entry_price, exit_price)
                    if net_ret is None:
                        net_ret = gross_ret
                    mfe = -long_mae
                    mae = -long_mfe
                else:
                    gross_ret = gross_forward
                    net_ret = self._long_net_return(entry_price, exit_price)
                    if net_ret is None:
                        net_ret = gross_ret
                    mfe = long_mfe
                    mae = long_mae

                details.append(
                    {
                        "source_type": self.SOURCE_INTRADAY,
                        "direction": direction,
                        "horizon": int(h),
                        "ts_code": ts_code,
                        "name": sig.get("name", ""),
                        "signal_id": int(sig.get("id")) if sig.get("id") is not None else None,
                        "signal_type": sig.get("signal_type", ""),
                        "signal_time": sig.get("signal_time", ""),
                        "signal_date": sig.get("signal_date", ""),
                        "recommendation_score": None,
                        "trigger_reason": sig.get("trigger_reason", ""),
                        "suggestion": sig.get("suggestion", ""),
                        "entry_date": entry_date,
                        "exit_date": exit_date,
                        "entry_price": entry_price,
                        "exit_price": exit_price,
                        "gross_return": gross_ret,
                        "net_return": net_ret,
                        "mfe": mfe,
                        "mae": mae,
                        "is_win": 1 if net_ret > 0 else 0,
                        "extra_json": json.dumps(
                            {"forward_return": gross_forward},
                            ensure_ascii=False,
                        ),
                    }
                )

        detail_df = pd.DataFrame(details)
        stats = self._summarize(detail_df, self.SOURCE_INTRADAY) if not detail_df.empty else []
        meta = {
            "signal_count": int(len(signal_df)),
            "detail_count": int(len(detail_df)),
            "horizons": list(horizons),
            "date_range_signal": [
                str(signal_df["signal_date"].min()) if not signal_df.empty else "",
                str(signal_df["signal_date"].max()) if not signal_df.empty else "",
            ],
        }
        return detail_df, stats, meta

    def _summarize(self, df: pd.DataFrame, source_type: str) -> List[FeedbackStat]:
        if df.empty:
            return []

        stats: List[FeedbackStat] = []
        grouped = df.groupby(["direction", "horizon"], as_index=False)
        for _, row in grouped:
            direction = str(row["direction"].iloc[0])
            horizon = int(row["horizon"].iloc[0])
            net_series = row["net_return"]
            gross_series = row["gross_return"]
            mfe_series = row["mfe"]
            mae_series = row["mae"]

            stat = FeedbackStat(
                source_type=source_type,
                direction=direction,
                horizon=horizon,
                sample_count=int(len(row)),
                win_rate=float((net_series > 0).mean()) if not net_series.empty else 0.0,
                mean_gross_return=self._mean(gross_series),
                mean_net_return=self._mean(net_series),
                median_net_return=self._quantile(net_series, 0.5),
                p25_net_return=self._quantile(net_series, 0.25),
                p75_net_return=self._quantile(net_series, 0.75),
                mean_mfe=self._mean(mfe_series),
                mean_mae=self._mean(mae_series),
            )
            stats.append(stat)

        stats.sort(key=lambda x: (x.direction, x.horizon))
        return stats

    def _get_market_regime_for_date(self, trade_date: str) -> str:
        date_norm = self._norm_date(trade_date)
        if not date_norm:
            return "UNKNOWN"
        if date_norm in self._market_regime_cache:
            return self._market_regime_cache[date_norm]
        try:
            result = self.position_controller.analyze_market(end_date=date_norm)
            regime = str(result.get("market_regime", "UNKNOWN") or "UNKNOWN").upper()
        except Exception:
            regime = "UNKNOWN"
        self._market_regime_cache[date_norm] = regime
        return regime

    def _attach_market_regime(
        self,
        detail_df: pd.DataFrame,
        date_col: str = "signal_date",
    ) -> pd.DataFrame:
        if detail_df.empty:
            return detail_df
        if date_col not in detail_df.columns:
            out = detail_df.copy()
            out["market_regime"] = "UNKNOWN"
            return out

        out = detail_df.copy()
        unique_dates = sorted(
            {
                self._norm_date(x)
                for x in out[date_col].tolist()
                if self._norm_date(x)
            }
        )
        regime_map = {d: self._get_market_regime_for_date(d) for d in unique_dates}
        out["market_regime"] = out[date_col].map(lambda x: regime_map.get(self._norm_date(x), "UNKNOWN"))
        return out

    def _summarize_by_regime(self, detail_df: pd.DataFrame) -> List[Dict[str, Any]]:
        if detail_df.empty:
            return []
        if "market_regime" not in detail_df.columns:
            return []

        rows: List[Dict[str, Any]] = []
        grouped = detail_df.groupby(
            ["source_type", "market_regime", "direction", "horizon"],
            as_index=False,
        )
        for _, grp in grouped:
            net_series = grp["net_return"]
            gross_series = grp["gross_return"]
            mfe_series = grp["mfe"]
            mae_series = grp["mae"]
            rows.append(
                {
                    "source_type": str(grp["source_type"].iloc[0]),
                    "market_regime": str(grp["market_regime"].iloc[0]),
                    "direction": str(grp["direction"].iloc[0]),
                    "horizon": int(grp["horizon"].iloc[0]),
                    "sample_count": int(len(grp)),
                    "win_rate": float((net_series > 0).mean()) if not net_series.empty else 0.0,
                    "mean_gross_return": self._mean(gross_series),
                    "mean_net_return": self._mean(net_series),
                    "median_net_return": self._quantile(net_series, 0.5),
                    "mean_mfe": self._mean(mfe_series),
                    "mean_mae": self._mean(mae_series),
                }
            )

        rows.sort(
            key=lambda x: (
                str(x.get("source_type", "")),
                str(x.get("market_regime", "")),
                str(x.get("direction", "")),
                int(x.get("horizon", 0)),
            )
        )
        return rows

    def _persist(
        self,
        run_id: str,
        start_date: str,
        end_date: str,
        detail_df: pd.DataFrame,
        stats: List[FeedbackStat],
        report_paths: Dict[str, str],
        meta: Dict[str, Any],
    ) -> None:
        self.db.execute(
            """
            INSERT INTO signal_feedback_run (
                run_id, start_date, end_date,
                recommendation_count, signal_count, detail_count, summary_count,
                report_md_path, report_json_path, report_csv_path, meta_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                start_date,
                end_date,
                int(meta.get("recommendation_count", 0)),
                int(meta.get("signal_count", 0)),
                int(len(detail_df)),
                int(len(stats)),
                report_paths.get("markdown", ""),
                report_paths.get("json", ""),
                report_paths.get("csv", ""),
                json.dumps(meta, ensure_ascii=False),
            ),
        )

        if stats:
            params_list = [
                (
                    run_id,
                    s.source_type,
                    s.direction,
                    int(s.horizon),
                    int(s.sample_count),
                    float(s.win_rate),
                    float(s.mean_gross_return),
                    float(s.mean_net_return),
                    float(s.median_net_return),
                    float(s.p25_net_return),
                    float(s.p75_net_return),
                    float(s.mean_mfe),
                    float(s.mean_mae),
                )
                for s in stats
            ]
            self.db.execute_many(
                """
                INSERT INTO signal_feedback_summary (
                    run_id, source_type, direction, horizon, sample_count,
                    win_rate, mean_gross_return, mean_net_return, median_net_return,
                    p25_net_return, p75_net_return, mean_mfe, mean_mae
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                params_list,
            )

        if not detail_df.empty:
            records = detail_df.to_dict("records")
            params_list = [
                (
                    run_id,
                    str(r.get("source_type", "")),
                    str(r.get("direction", "")),
                    int(r.get("horizon", 0) or 0),
                    str(r.get("ts_code", "")),
                    str(r.get("name", "")),
                    r.get("signal_id"),
                    str(r.get("signal_type", "")),
                    str(r.get("signal_time", "")),
                    str(r.get("signal_date", "")),
                    r.get("recommendation_score"),
                    str(r.get("trigger_reason", "")),
                    str(r.get("suggestion", "")),
                    str(r.get("entry_date", "")),
                    str(r.get("exit_date", "")),
                    float(r.get("entry_price", 0.0) or 0.0),
                    float(r.get("exit_price", 0.0) or 0.0),
                    float(r.get("gross_return", 0.0) or 0.0),
                    float(r.get("net_return", 0.0) or 0.0),
                    float(r.get("mfe", 0.0) or 0.0),
                    float(r.get("mae", 0.0) or 0.0),
                    int(r.get("is_win", 0) or 0),
                    str(r.get("extra_json", "")),
                )
                for r in records
            ]
            self.db.execute_many(
                """
                INSERT INTO signal_feedback_detail (
                    run_id, source_type, direction, horizon, ts_code, name, signal_id,
                    signal_type, signal_time, signal_date, recommendation_score,
                    trigger_reason, suggestion, entry_date, exit_date, entry_price, exit_price,
                    gross_return, net_return, mfe, mae, is_win, extra_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                params_list,
            )

    def _build_markdown(self, payload: Dict[str, Any]) -> str:
        stats = payload.get("stats", [])
        lines: List[str] = [
            "# 信号收益闭环评估报告",
            "",
            f"- 运行ID: `{payload.get('run_id', '')}`",
            f"- 生成时间: `{payload.get('generated_time', '')}`",
            f"- 评估区间: `{payload.get('start_date', '')}` ~ `{payload.get('end_date', '')}`",
            f"- 推荐库: `{self.recommendation_db_path.as_posix()}`",
            f"- 费用口径: 买滑点 `{self.buy_slippage:.4f}` / 卖滑点 `{self.sell_slippage:.4f}` / 买费率 `{self.buy_fee_rate:.4f}` / 卖费率 `{self.sell_fee_rate:.4f}` / 印花税 `{self.stamp_tax_rate:.4f}`",
            "",
            "## 汇总统计",
            "",
            "| 来源 | 方向 | 持有到 | 样本数 | 胜率 | 平均毛收益 | 平均净收益 | 中位净收益 | 25%分位 | 75%分位 | 平均MFE | 平均MAE |",
            "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]

        if stats:
            for s in stats:
                lines.append(
                    f"| {s.get('source_type', '')} | {s.get('direction', '')} | T+{int(s.get('horizon', 0))} | "
                    f"{int(s.get('sample_count', 0))} | {float(s.get('win_rate', 0)):.2%} | "
                    f"{float(s.get('mean_gross_return', 0)):.2%} | {float(s.get('mean_net_return', 0)):.2%} | "
                    f"{float(s.get('median_net_return', 0)):.2%} | {float(s.get('p25_net_return', 0)):.2%} | "
                    f"{float(s.get('p75_net_return', 0)):.2%} | {float(s.get('mean_mfe', 0)):.2%} | "
                    f"{float(s.get('mean_mae', 0)):.2%} |"
                )
        else:
            lines.append("| - | - | - | 0 | 0.00% | 0.00% | 0.00% | 0.00% | 0.00% | 0.00% | 0.00% | 0.00% |")

        lines.extend(
            [
                "",
                "## 说明",
                "- 盘前推荐口径：`T+1` 开盘入场，`T+N` 收盘离场。",
                "- 盘中信号口径：买信号看后续上涨，卖信号看后续下跌（方向收益为正视为命中）。",
                "- 报告仅用于策略迭代与辅助决策，不构成投资建议。",
            ]
        )
        return "\n".join(lines)

    def _build_markdown_v2(self, payload: Dict[str, Any]) -> str:
        stats = payload.get("stats", [])
        regime_stats = payload.get("regime_stats", [])
        intraday_type_stats = payload.get("intraday_type_stats", [])
        intraday_window_stats = payload.get("intraday_window_stats", [])
        intraday_insights = payload.get("intraday_insights", {}) or {}

        lines: List[str] = [
            "# 信号收益闭环评估报告",
            "",
            f"- 运行ID: `{payload.get('run_id', '')}`",
            f"- 生成时间: `{payload.get('generated_time', '')}`",
            f"- 评估区间: `{payload.get('start_date', '')}` ~ `{payload.get('end_date', '')}`",
            f"- 推荐库: `{self.recommendation_db_path.as_posix()}`",
            f"- 费用口径: 买滑点`{self.buy_slippage:.4f}` / 卖滑点`{self.sell_slippage:.4f}` / 买费率`{self.buy_fee_rate:.4f}` / 卖费率`{self.sell_fee_rate:.4f}` / 印花税`{self.stamp_tax_rate:.4f}`",
            "",
            "## 汇总统计",
            "",
            "| 来源 | 方向 | 持有期 | 样本数 | 胜率 | 平均毛收益 | 平均净收益 | 中位净收益 | 25%分位 | 75%分位 | 平均MFE | 平均MAE |",
            "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]

        if stats:
            for s in stats:
                lines.append(
                    f"| {s.get('source_type', '')} | {s.get('direction', '')} | T+{int(s.get('horizon', 0))} | "
                    f"{int(s.get('sample_count', 0))} | {float(s.get('win_rate', 0)):.2%} | "
                    f"{float(s.get('mean_gross_return', 0)):.2%} | {float(s.get('mean_net_return', 0)):.2%} | "
                    f"{float(s.get('median_net_return', 0)):.2%} | {float(s.get('p25_net_return', 0)):.2%} | "
                    f"{float(s.get('p75_net_return', 0)):.2%} | {float(s.get('mean_mfe', 0)):.2%} | "
                    f"{float(s.get('mean_mae', 0)):.2%} |"
                )
        else:
            lines.append(
                "| - | - | - | 0 | 0.00% | 0.00% | 0.00% | 0.00% | 0.00% | 0.00% | 0.00% | 0.00% |"
            )

        lines.extend(
            [
                "",
                "## 市场状态分层统计",
                "",
                "| 来源 | 市场状态 | 方向 | 持有期 | 样本数 | 胜率 | 平均净收益 | 中位净收益 | 平均MFE | 平均MAE |",
                "|---|---|---|---:|---:|---:|---:|---:|---:|---:|",
            ]
        )

        if regime_stats:
            for s in regime_stats:
                lines.append(
                    f"| {s.get('source_type', '')} | {s.get('market_regime', 'UNKNOWN')} | {s.get('direction', '')} | "
                    f"T+{int(s.get('horizon', 0))} | {int(s.get('sample_count', 0))} | "
                    f"{float(s.get('win_rate', 0)):.2%} | {float(s.get('mean_net_return', 0)):.2%} | "
                    f"{float(s.get('median_net_return', 0)):.2%} | {float(s.get('mean_mfe', 0)):.2%} | "
                    f"{float(s.get('mean_mae', 0)):.2%} |"
                )
        else:
            lines.append("| - | - | - | - | 0 | 0.00% | 0.00% | 0.00% | 0.00% | 0.00% |")

        lines.extend(
            [
                "",
                "## 盘中子类型统计",
                "",
                "| 子类型 | 方向 | 持有期 | 样本数 | 胜率 | 平均净收益 | 中位净收益 | 平均MFE | 平均MAE |",
                "|---|---|---:|---:|---:|---:|---:|---:|---:|",
            ]
        )
        if intraday_type_stats:
            for s in intraday_type_stats:
                lines.append(
                    f"| {s.get('signal_type', '')} | {s.get('direction', '')} | T+{int(s.get('horizon', 0))} | "
                    f"{int(s.get('sample_count', 0))} | {float(s.get('win_rate', 0)):.2%} | "
                    f"{float(s.get('mean_net_return', 0)):.2%} | {float(s.get('median_net_return', 0)):.2%} | "
                    f"{float(s.get('mean_mfe', 0)):.2%} | {float(s.get('mean_mae', 0)):.2%} |"
                )
        else:
            lines.append("| - | - | - | 0 | 0.00% | 0.00% | 0.00% | 0.00% | 0.00% |")

        lines.extend(
            [
                "",
                "## 盘中分钟窗口表现",
                "",
                "| 子类型 | 方向 | 分钟窗口 | 样本数 | 胜率 | 平均净收益 | 中位净收益 | 平均MFE | 平均MAE |",
                "|---|---|---:|---:|---:|---:|---:|---:|---:|",
            ]
        )
        if intraday_window_stats:
            for s in intraday_window_stats:
                lines.append(
                    f"| {s.get('signal_type', '')} | {s.get('direction', '')} | {int(s.get('window_minutes', 0))}m | "
                    f"{int(s.get('sample_count', 0))} | {float(s.get('win_rate', 0)):.2%} | "
                    f"{float(s.get('mean_net_return', 0)):.2%} | {float(s.get('median_net_return', 0)):.2%} | "
                    f"{float(s.get('mean_mfe', 0)):.2%} | {float(s.get('mean_mae', 0)):.2%} |"
                )
        else:
            lines.append("| - | - | - | 0 | 0.00% | 0.00% | 0.00% | 0.00% | 0.00% |")

        lines.extend(
            [
                "",
                "## 二次启动观察结论",
                "",
            ]
        )
        for item in intraday_insights.get("conclusions", []) or []:
            lines.append(f"- {item}")
        for item in intraday_insights.get("action_items", []) or []:
            lines.append(f"- 建议：{item}")
        if not (intraday_insights.get("conclusions") or intraday_insights.get("action_items")):
            lines.append("- 当前暂无足够样本生成观察结论。")

        lines.extend(
            [
                "",
                "## 说明",
                "- 盘前推荐口径：`T+1` 开盘入场，`T+N` 收盘离场。",
                "- 盘中信号口径：买信号看后续上涨，卖信号看后续下跌（方向收益为正视为命中）。",
                "- 分钟窗口口径：使用同日 `intraday_data` 分时数据，按信号触发后的第 `5/15/30` 根分钟线收盘统计。",
                "- 报告用于策略迭代与风控闸门，不构成投资建议。",
            ]
        )
        return "\n".join(lines)

    def run_feedback(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        top_n_per_day: Optional[int] = None,
        recommendation_horizons: Optional[Sequence[int]] = None,
        signal_horizons: Optional[Sequence[int]] = None,
        strategy_type: Optional[str] = None,
        out_dir: Optional[str] = None,
        persist: Optional[bool] = None,
    ) -> Dict[str, Any]:
        latest_trade_date = self._norm_date(self.db.get_latest_trade_date("stock_daily"))
        if not latest_trade_date:
            latest_trade_date = datetime.now().strftime("%Y%m%d")

        end_date_norm = self._norm_date(end_date) if end_date else latest_trade_date
        if not end_date_norm:
            end_date_norm = latest_trade_date

        if start_date:
            start_date_norm = self._norm_date(start_date)
        else:
            dt = datetime.strptime(end_date_norm, "%Y%m%d")
            start_date_norm = (dt - timedelta(days=self.default_lookback_days)).strftime("%Y%m%d")
        if not start_date_norm:
            start_date_norm = end_date_norm

        top_n = int(self.default_top_n_per_day if top_n_per_day is None else top_n_per_day)
        rec_h = self._parse_horizons(
            recommendation_horizons,
            default=self.default_recommendation_horizons,
            min_h=1,
        )
        sig_h = self._parse_horizons(
            signal_horizons,
            default=self.default_signal_horizons,
            min_h=1,
        )

        logger.info(
            "开始执行信号闭环评估 | start=%s end=%s top_n=%s rec_h=%s sig_h=%s strategy=%s",
            start_date_norm,
            end_date_norm,
            top_n,
            rec_h,
            sig_h,
            strategy_type or "all",
        )

        rec_detail, rec_stats, rec_meta = self.evaluate_pre_market_recommendations(
            start_date=start_date_norm,
            end_date=end_date_norm,
            top_n_per_day=top_n,
            horizons=rec_h,
            strategy_type=strategy_type,
        )
        sig_detail, sig_stats, sig_meta = self.evaluate_intraday_signals(
            start_date=start_date_norm,
            end_date=end_date_norm,
            horizons=sig_h,
        )
        intraday_type_stats = self._summarize_intraday_signal_type(sig_detail)
        intraday_window_stats, intraday_window_meta = self._evaluate_intraday_signal_windows(
            signal_df=self._load_signal_history(start_date=start_date_norm, end_date=end_date_norm),
            windows=self.DEFAULT_INTRADAY_WINDOWS,
        )
        intraday_insights = self._build_intraday_insights(
            intraday_type_stats=intraday_type_stats,
            intraday_window_stats=intraday_window_stats,
        )

        detail_parts = []
        for frame in (rec_detail, sig_detail):
            if frame is None or frame.empty:
                continue
            cleaned = frame.dropna(axis=1, how="all")
            if cleaned.dropna(how="all").empty:
                continue
            detail_parts.append(cleaned)
        detail_df = pd.concat(detail_parts, ignore_index=True) if detail_parts else pd.DataFrame()
        if not detail_df.empty:
            detail_df = self._attach_market_regime(detail_df, date_col="signal_date")
        all_stats = [s.to_dict() for s in (rec_stats + sig_stats)]
        regime_stats = self._summarize_by_regime(detail_df) if not detail_df.empty else []

        run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        target_dir = self._resolve_path(out_dir) if out_dir else self.report_dir
        target_dir.mkdir(parents=True, exist_ok=True)

        report_base = target_dir / f"signal_feedback_{run_id}"
        csv_path = report_base.with_suffix(".csv")
        md_path = report_base.with_suffix(".md")
        json_path = report_base.with_suffix(".json")

        if not detail_df.empty:
            detail_df.to_csv(csv_path, index=False, encoding="utf-8-sig")

        payload = {
            "run_id": run_id,
            "generated_time": now_str,
            "start_date": start_date_norm,
            "end_date": end_date_norm,
            "stats": all_stats,
            "regime_stats": regime_stats,
            "intraday_type_stats": intraday_type_stats,
            "intraday_window_stats": intraday_window_stats,
            "intraday_insights": intraday_insights,
            "meta": {
                "recommendation": rec_meta,
                "intraday_signal": {
                    **sig_meta,
                    "signal_type_stats": intraday_type_stats,
                    "window_stats": intraday_window_stats,
                    "window_meta": intraday_window_meta,
                    "insights": intraday_insights,
                },
                "regime_split_enabled": True,
            },
            "files": {
                "markdown": md_path.as_posix(),
                "json": json_path.as_posix(),
                "csv": csv_path.as_posix() if not detail_df.empty else "",
            },
        }
        md_text = self._build_markdown_v2(payload)
        md_path.write_text(md_text, encoding="utf-8")
        json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

        persist_flag = self.persist_to_db if persist is None else bool(persist)
        if persist_flag:
            try:
                if not self.persist_to_db:
                    self._ensure_feedback_tables()
                self._persist(
                    run_id=run_id,
                    start_date=start_date_norm,
                    end_date=end_date_norm,
                    detail_df=detail_df,
                    stats=rec_stats + sig_stats,
                    report_paths=payload["files"],
                    meta={
                        "recommendation_count": rec_meta.get("recommendation_count", 0),
                        "signal_count": sig_meta.get("signal_count", 0),
                        "regime_summary_count": len(regime_stats),
                        "recommendation_meta": rec_meta,
                        "signal_meta": {
                            **sig_meta,
                            "signal_type_stats": intraday_type_stats,
                            "window_stats": intraday_window_stats,
                            "window_meta": intraday_window_meta,
                            "insights": intraday_insights,
                        },
                    },
                )
            except Exception as e:
                logger.error("闭环评估落库失败: %s", e)
                payload["persist_error"] = str(e)

        payload["status"] = "success"
        payload["detail_count"] = int(len(detail_df))
        payload["summary_count"] = int(len(all_stats))
        payload["regime_summary_count"] = int(len(regime_stats))
        payload["recommendation_detail_count"] = int(len(rec_detail))
        payload["signal_detail_count"] = int(len(sig_detail))

        logger.info(
            "信号闭环评估完成 | run_id=%s | detail=%d | summary=%d",
            run_id,
            payload["detail_count"],
            payload["summary_count"],
        )
        return payload

    @staticmethod
    def _stat_brief(stat: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "horizon": int(stat.get("horizon", 0)),
            "sample_count": int(stat.get("sample_count", 0)),
            "win_rate": float(stat.get("win_rate", 0.0)),
            "mean_net_return": float(stat.get("mean_net_return", 0.0)),
            "mean_mfe": float(stat.get("mean_mfe", 0.0)),
            "mean_mae": float(stat.get("mean_mae", 0.0)),
        }

    @staticmethod
    def _best_by_mean_net(stats: List[Dict[str, Any]], min_samples: int = 10) -> Optional[Dict[str, Any]]:
        if not stats:
            return None
        eligible = [s for s in stats if int(s.get("sample_count", 0)) >= int(min_samples)]
        target = eligible if eligible else stats
        target = sorted(
            target,
            key=lambda x: (float(x.get("mean_net_return", -999)), int(x.get("sample_count", 0))),
            reverse=True,
        )
        return target[0] if target else None

    def _get_latest_persisted_snapshot(
        self,
        end_date: Optional[str] = None,
        max_age_hours: float = 24.0,
        min_samples_for_best: int = 10,
    ) -> Optional[Dict[str, Any]]:
        """
        从落库结果恢复最近快照，避免日报重复重算。
        """
        try:
            run_row = self.db.query_one(
                """
                SELECT run_id, start_date, end_date, recommendation_count, signal_count,
                       detail_count, summary_count, meta_json, created_time
                FROM signal_feedback_run
                ORDER BY created_time DESC
                LIMIT 1
                """
            )
            if not run_row:
                return None

            created_time = str(run_row.get("created_time", "") or "")
            if created_time:
                try:
                    created_dt = datetime.strptime(created_time, "%Y-%m-%d %H:%M:%S")
                    age_hours = (datetime.now() - created_dt).total_seconds() / 3600.0
                    if age_hours > float(max_age_hours):
                        return None
                except Exception:
                    pass

            run_end_date = str(run_row.get("end_date", "") or "")
            if end_date and run_end_date and run_end_date != str(end_date):
                return None

            run_id = str(run_row.get("run_id", "") or "")
            if not run_id:
                return None

            summary_rows = self.db.query(
                """
                SELECT source_type, direction, horizon, sample_count, win_rate,
                       mean_gross_return, mean_net_return, median_net_return,
                       p25_net_return, p75_net_return, mean_mfe, mean_mae
                FROM signal_feedback_summary
                WHERE run_id = ?
                ORDER BY source_type, direction, horizon
                """,
                (run_id,),
            )
            if not summary_rows:
                return None

            rec_stats = [
                r for r in summary_rows if str(r.get("source_type", "")) == self.SOURCE_PRE_MARKET
            ]
            sig_buy = [
                r
                for r in summary_rows
                if str(r.get("source_type", "")) == self.SOURCE_INTRADAY
                and str(r.get("direction", "")) == "buy"
            ]
            sig_sell = [
                r
                for r in summary_rows
                if str(r.get("source_type", "")) == self.SOURCE_INTRADAY
                and str(r.get("direction", "")) == "sell"
            ]

            meta = {}
            try:
                meta = json.loads(str(run_row.get("meta_json", "") or "{}"))
            except Exception:
                meta = {}

            snapshot = {
                "start_date": str(run_row.get("start_date", "") or ""),
                "end_date": run_end_date,
                "recommendation_detail_count": int(
                    meta.get("recommendation_meta", {}).get("detail_count", 0)
                    if isinstance(meta.get("recommendation_meta"), dict)
                    else 0
                ),
                "signal_detail_count": int(
                    meta.get("signal_meta", {}).get("detail_count", 0)
                    if isinstance(meta.get("signal_meta"), dict)
                    else 0
                ),
                "recommendation_count": int(run_row.get("recommendation_count", 0) or 0),
                "signal_count": int(run_row.get("signal_count", 0) or 0),
                "pre_market_stats": [self._stat_brief(s) for s in rec_stats],
                "intraday_buy_stats": [self._stat_brief(s) for s in sig_buy],
                "intraday_sell_stats": [self._stat_brief(s) for s in sig_sell],
                "pre_market_best": self._best_by_mean_net(rec_stats, min_samples=min_samples_for_best),
                "intraday_buy_best": self._best_by_mean_net(sig_buy, min_samples=min_samples_for_best),
                "intraday_sell_best": self._best_by_mean_net(sig_sell, min_samples=min_samples_for_best),
                "meta": {
                    "recommendation": meta.get("recommendation_meta", {}),
                    "intraday_signal": meta.get("signal_meta", {}),
                },
                "snapshot_source": "persisted_run",
                "snapshot_run_id": run_id,
                "snapshot_created_time": created_time,
            }
            return snapshot
        except Exception:
            return None

    def build_feedback_snapshot(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        top_n_per_day: Optional[int] = None,
        recommendation_horizons: Optional[Sequence[int]] = None,
        signal_horizons: Optional[Sequence[int]] = None,
        strategy_type: Optional[str] = None,
        min_samples_for_best: int = 10,
    ) -> Dict[str, Any]:
        """
        生成轻量闭环快照（不写文件、不落库），用于日报/推送摘要。
        """
        latest_trade_date = self._norm_date(self.db.get_latest_trade_date("stock_daily"))
        if not latest_trade_date:
            latest_trade_date = datetime.now().strftime("%Y%m%d")

        end_date_norm = self._norm_date(end_date) if end_date else latest_trade_date
        if not end_date_norm:
            end_date_norm = latest_trade_date

        if start_date:
            start_date_norm = self._norm_date(start_date)
        else:
            dt = datetime.strptime(end_date_norm, "%Y%m%d")
            start_date_norm = (dt - timedelta(days=self.default_lookback_days)).strftime("%Y%m%d")
        if not start_date_norm:
            start_date_norm = end_date_norm

        use_latest_run = bool(self.config.get("feedback.snapshot_use_latest_run", True))
        latest_run_max_age_hours = float(
            self.config.get("feedback.snapshot_latest_run_max_age_hours", 24)
        )
        if use_latest_run:
            latest_snapshot = self._get_latest_persisted_snapshot(
                end_date=end_date_norm,
                max_age_hours=latest_run_max_age_hours,
                min_samples_for_best=min_samples_for_best,
            )
            if latest_snapshot:
                return latest_snapshot

        top_n = int(self.default_top_n_per_day if top_n_per_day is None else top_n_per_day)
        rec_h = self._parse_horizons(
            recommendation_horizons,
            default=self.default_recommendation_horizons,
            min_h=1,
        )
        sig_h = self._parse_horizons(
            signal_horizons,
            default=self.default_signal_horizons,
            min_h=1,
        )

        rec_detail, rec_stats, rec_meta = self.evaluate_pre_market_recommendations(
            start_date=start_date_norm,
            end_date=end_date_norm,
            top_n_per_day=top_n,
            horizons=rec_h,
            strategy_type=strategy_type,
        )
        sig_detail, sig_stats, sig_meta = self.evaluate_intraday_signals(
            start_date=start_date_norm,
            end_date=end_date_norm,
            horizons=sig_h,
        )

        rec_stats_dict = [s.to_dict() for s in rec_stats]
        sig_stats_dict = [s.to_dict() for s in sig_stats]
        sig_buy = [s for s in sig_stats_dict if str(s.get("direction")) == "buy"]
        sig_sell = [s for s in sig_stats_dict if str(s.get("direction")) == "sell"]

        snapshot = {
            "start_date": start_date_norm,
            "end_date": end_date_norm,
            "recommendation_detail_count": int(len(rec_detail)),
            "signal_detail_count": int(len(sig_detail)),
            "recommendation_count": int(rec_meta.get("recommendation_count", 0)),
            "signal_count": int(sig_meta.get("signal_count", 0)),
            "pre_market_stats": [self._stat_brief(s) for s in rec_stats_dict],
            "intraday_buy_stats": [self._stat_brief(s) for s in sig_buy],
            "intraday_sell_stats": [self._stat_brief(s) for s in sig_sell],
            "pre_market_best": self._best_by_mean_net(rec_stats_dict, min_samples=min_samples_for_best),
            "intraday_buy_best": self._best_by_mean_net(sig_buy, min_samples=min_samples_for_best),
            "intraday_sell_best": self._best_by_mean_net(sig_sell, min_samples=min_samples_for_best),
            "meta": {
                "recommendation": rec_meta,
                "intraday_signal": sig_meta,
            },
            "snapshot_source": "recomputed",
        }
        return snapshot
