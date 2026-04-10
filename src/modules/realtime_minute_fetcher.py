# -*- coding: utf-8 -*-
"""
Auxiliary-grade realtime minute fetcher.

This module is intentionally built for public market data sources:
- prioritizes availability over low-latency guarantees
- supports graceful fallback and partial-symbol success
- keeps short in-memory cache to reduce repeated requests
"""

from __future__ import annotations

import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from concurrent.futures import TimeoutError as FutureTimeoutError
from datetime import datetime
from typing import Dict, List, Optional

import pandas as pd

from src.core.logger import get_logger

logger = get_logger("realtime_minute_fetcher")

try:
    import akshare as ak

    AKSHARE_AVAILABLE = True
except Exception as exc:  # pragma: no cover - depends on runtime environment
    ak = None
    AKSHARE_AVAILABLE = False
    _AKSHARE_IMPORT_ERROR = exc


class RealtimeMinuteFetcher:
    """Fetches 1-minute bars from public sources with fallback and caching."""

    STANDARD_COLUMNS = [
        "symbol",
        "trade_time",
        "trade_date",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "amount",
    ]

    def __init__(
        self,
        cache_ttl_seconds: int = 8,
        request_pause_seconds: float = 0.05,
        max_workers: int = 3,
        min_valid_rows: int = 20,
        enable_akshare_minute: bool = True,
        runtime_guard_py314_with_mini_racer: bool = False,
    ):
        self.cache_ttl_seconds = max(0, int(cache_ttl_seconds))
        self.request_pause_seconds = max(0.0, float(request_pause_seconds))
        self.max_workers = max(1, int(max_workers))
        self.min_valid_rows = max(1, int(min_valid_rows))
        self.enable_akshare_minute = bool(enable_akshare_minute)
        self.runtime_guard_py314_with_mini_racer = bool(runtime_guard_py314_with_mini_racer)

        self._cache_lock = threading.Lock()
        self._cache: Dict[str, Dict[str, object]] = {}

        self._consecutive_failures = 0
        self._circuit_open_until: float = 0.0
        self._circuit_failure_threshold = 3
        self._circuit_recovery_seconds = 300
        self._runtime_disabled_warned = False
        self._akshare_runtime_enabled = self._resolve_akshare_runtime_enabled()

        if not AKSHARE_AVAILABLE:
            logger.warning(
                "akshare is unavailable, realtime minute fetcher will only return empty data: %s",
                _AKSHARE_IMPORT_ERROR,
            )
        elif not self._akshare_runtime_enabled:
            logger.warning(
                "Realtime minute fetch is runtime-disabled; only empty minute map will be returned."
            )

    def _resolve_akshare_runtime_enabled(self) -> bool:
        if not AKSHARE_AVAILABLE:
            return False
        if not self.enable_akshare_minute:
            return False

        force_enable = str(os.getenv("QSYS_FORCE_AKSHARE_MINUTE", "")).strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        if force_enable:
            logger.warning(
                "QSYS_FORCE_AKSHARE_MINUTE is set, forcing akshare minute fetch on current runtime."
            )
            return True

        # Optional guard against py_mini_racer + Python 3.14 crash observed in monitor mode.
        if self.runtime_guard_py314_with_mini_racer and sys.version_info >= (3, 14):
            try:
                import py_mini_racer  # noqa: F401

                logger.error(
                    "Disable akshare minute fetch on Python %s.%s due py_mini_racer crash risk. "
                    "Set QSYS_FORCE_AKSHARE_MINUTE=1 to override at your own risk.",
                    sys.version_info.major,
                    sys.version_info.minor,
                )
                return False
            except Exception:
                return True

        return True

    def get_batch_minute_bars(
        self,
        symbols: List[str],
        trade_date: Optional[str] = None,
        max_workers: Optional[int] = None,
        overall_timeout_seconds: Optional[float] = None,
    ) -> Dict[str, pd.DataFrame]:
        """Fetch minute bars for multiple symbols, best-effort by symbol.

        实盘级约束：必须支持整体超时，避免单票卡死拖垮整轮监控。
        熔断保护：连续失败超过阈值后跳过请求，避免持续超时拖慢监控。
        """
        if not self._akshare_runtime_enabled:
            if not self._runtime_disabled_warned:
                logger.warning(
                    "Minute fetch skipped because akshare minute source is disabled for current runtime."
                )
                self._runtime_disabled_warned = True
            return {}

        if time.time() < self._circuit_open_until:
            logger.warning(
                "熔断器开启，跳过分钟数据获取（剩余 %.0f 秒）",
                self._circuit_open_until - time.time(),
            )
            return {}

        normalized_symbols: List[str] = []
        for symbol in symbols:
            normalized = self.normalize_symbol(symbol)
            if normalized and normalized not in normalized_symbols:
                normalized_symbols.append(normalized)

        if not normalized_symbols:
            return {}

        worker_count = max(1, int(max_workers or self.max_workers))
        if sys.version_info >= (3, 14) and worker_count > 1:
            logger.warning(
                "Python %s.%s runtime detected, minute fetch concurrency forced to 1 for stability.",
                sys.version_info.major,
                sys.version_info.minor,
            )
            worker_count = 1
        if worker_count == 1 or len(normalized_symbols) == 1:
            result: Dict[str, pd.DataFrame] = {}
            for symbol in normalized_symbols:
                frame = self.get_minute_bars(symbol, trade_date=trade_date)
                if not frame.empty:
                    result[symbol] = frame
            return result

        result: Dict[str, pd.DataFrame] = {}
        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            future_map = {
                executor.submit(self.get_minute_bars, symbol, trade_date): symbol
                for symbol in normalized_symbols
            }
            try:
                futures = as_completed(future_map, timeout=overall_timeout_seconds)
                for future in futures:
                    symbol = future_map[future]
                    try:
                        frame = future.result()
                    except Exception as exc:
                        logger.warning("Minute fetch failed for %s: %s", symbol, exc)
                        continue
                    if not frame.empty:
                        result[symbol] = frame
            except FutureTimeoutError:
                # 超时：直接返回已完成部分，剩余标的视为分钟数据缺失
                pending = [sym for fut, sym in future_map.items() if not fut.done()]
                if pending:
                    logger.warning(
                        "Minute batch fetch timeout (%.2fs), pending=%s/%s",
                        float(overall_timeout_seconds or 0.0),
                        len(pending),
                        len(normalized_symbols),
                    )

        if result:
            self._consecutive_failures = 0
        else:
            self._consecutive_failures += 1
            if self._consecutive_failures >= self._circuit_failure_threshold:
                self._circuit_open_until = time.time() + self._circuit_recovery_seconds
                logger.warning(
                    "熔断器触发：连续 %d 次获取失败，熔断 %d 秒",
                    self._consecutive_failures,
                    self._circuit_recovery_seconds,
                )

        return result

    def get_minute_bars(
        self,
        symbol: str,
        trade_date: Optional[str] = None,
        force_refresh: bool = False,
    ) -> pd.DataFrame:
        """Fetch minute bars for one symbol with cache and fallback."""
        normalized = self.normalize_symbol(symbol)
        if not normalized:
            return self._empty_frame()

        if not force_refresh:
            cached = self._read_cache(normalized)
            if cached is not None:
                return cached

        if not self._akshare_runtime_enabled:
            return self._empty_frame()

        frame = self._fetch_from_hist_min_em(normalized, trade_date=trade_date)
        if frame.empty:
            frame = self._fetch_from_sina_minute(normalized, trade_date=trade_date)

        if not frame.empty and len(frame) >= self.min_valid_rows:
            self._write_cache(normalized, frame)
            return frame

        if not frame.empty:
            logger.warning(
                "Minute bars for %s are too short (%s rows < %s)",
                normalized,
                len(frame),
                self.min_valid_rows,
            )
        return frame

    def build_quote_from_minute(
        self,
        symbol: str,
        minute_frame: pd.DataFrame,
        name: str = "",
    ) -> Dict[str, object]:
        """Build a quote-like snapshot from minute bars for compatibility."""
        if minute_frame is None or minute_frame.empty:
            return {}

        ordered = minute_frame.sort_values("trade_time").reset_index(drop=True)
        latest = ordered.iloc[-1]
        first = ordered.iloc[0]

        amount_series = ordered["amount"]
        if amount_series.isna().all():
            amount_value = float((ordered["close"] * ordered["volume"]).sum())
        else:
            amount_value = float(amount_series.fillna(0).sum())

        # pre_close 推断：尝试从首根 K 线的开盘前收盘推断。
        # 公开分时接口不暴露昨收价，以下按优先级 fallback：
        #   1. 第一根 K 线的 open（仅在开盘第一根时与昨收接近）
        #   2. 保持与 open 一致（open_pct 将为 0，优于用错误基准计算负涨幅）
        first_open = float(first["open"])
        pre_close = first_open  # fallback：开盘价作为基准

        quote = {
            "symbol": self.normalize_symbol(symbol),
            "name": name or "",
            "open": first_open,
            # 注意：公开分时接口无昨收价，此值为近似值，调用方需知晓局限
            "pre_close": pre_close,
            "price": float(latest["close"]),
            "high": float(ordered["high"].max()),
            "low": float(ordered["low"].min()),
            "volume": float(ordered["volume"].sum()),
            "amount": amount_value,
            "date": latest["trade_time"].strftime("%Y-%m-%d"),
            "time": latest["trade_time"].strftime("%H:%M:%S"),
            "pre_close_source": "minute_first_open_approx",  # 标记来源，供下游判断
        }
        return quote

    def build_quote_frame(
        self,
        minute_map: Dict[str, pd.DataFrame],
        names: Optional[Dict[str, str]] = None,
    ) -> pd.DataFrame:
        """Build a snapshot DataFrame from minute bars for multiple symbols."""
        rows: List[Dict[str, object]] = []
        for symbol, frame in minute_map.items():
            quote = self.build_quote_from_minute(
                symbol=symbol,
                minute_frame=frame,
                name=(names or {}).get(symbol, ""),
            )
            if quote:
                rows.append(quote)
        if not rows:
            return pd.DataFrame()
        return pd.DataFrame(rows)

    @staticmethod
    def normalize_symbol(symbol: object) -> str:
        text = str(symbol or "").strip().upper()
        if not text:
            return ""

        if "." in text:
            head = text.split(".", 1)[0]
            if head.isdigit():
                return head.zfill(6)

        if text.startswith("SH") or text.startswith("SZ"):
            code = text[2:]
            if code.isdigit():
                return code.zfill(6)

        digits = "".join(ch for ch in text if ch.isdigit())
        if len(digits) >= 6:
            return digits[-6:]
        return ""

    def _fetch_from_hist_min_em(self, symbol: str, trade_date: Optional[str] = None) -> pd.DataFrame:
        try:
            target_date = trade_date or datetime.now().strftime("%Y-%m-%d")
            raw = ak.stock_zh_a_hist_min_em(
                symbol=symbol,
                start_date=f"{target_date} 09:30:00",
                end_date=f"{target_date} 15:00:00",
                period="1",
                adjust="",
            )
            if self.request_pause_seconds > 0:
                time.sleep(self.request_pause_seconds)
            return self._normalize_hist_minute_df(raw, symbol=symbol)
        except Exception as exc:
            logger.debug("hist_min_em failed for %s: %s", symbol, exc)
            return self._empty_frame()

    def _fetch_from_sina_minute(self, symbol: str, trade_date: Optional[str] = None) -> pd.DataFrame:
        try:
            raw = ak.stock_zh_a_minute(symbol=self._to_sina_symbol(symbol), period="1")
            if self.request_pause_seconds > 0:
                time.sleep(self.request_pause_seconds)
            return self._normalize_sina_minute_df(raw, symbol=symbol, trade_date=trade_date)
        except Exception as exc:
            logger.debug("stock_zh_a_minute failed for %s: %s", symbol, exc)
            return self._empty_frame()

    def _normalize_hist_minute_df(self, raw: pd.DataFrame, symbol: str) -> pd.DataFrame:
        if raw is None or raw.empty:
            return self._empty_frame()

        column_map = {
            "时间": "trade_time",
            "开盘": "open",
            "收盘": "close",
            "最高": "high",
            "最低": "low",
            "成交量": "volume",
            "成交额": "amount",
        }
        required = {"时间", "开盘", "收盘", "最高", "最低", "成交量"}
        if not required.issubset(set(raw.columns)):
            return self._empty_frame()

        frame = raw.rename(columns=column_map).copy()
        return self._normalize_minute_frame(frame=frame, symbol=symbol)

    def _normalize_sina_minute_df(
        self,
        raw: pd.DataFrame,
        symbol: str,
        trade_date: Optional[str] = None,
    ) -> pd.DataFrame:
        if raw is None or raw.empty:
            return self._empty_frame()

        column_map = {
            "day": "trade_time",
            "open": "open",
            "high": "high",
            "low": "low",
            "close": "close",
            "volume": "volume",
            "amount": "amount",
        }
        required = {"day", "open", "high", "low", "close", "volume"}
        if not required.issubset(set(raw.columns)):
            return self._empty_frame()

        frame = raw.rename(columns=column_map).copy()
        normalized = self._normalize_minute_frame(frame=frame, symbol=symbol)

        if trade_date:
            normalized = normalized[normalized["trade_date"] == str(trade_date)]
            normalized = normalized.reset_index(drop=True)
        return normalized

    def _normalize_minute_frame(self, frame: pd.DataFrame, symbol: str) -> pd.DataFrame:
        if frame is None or frame.empty or "trade_time" not in frame.columns:
            return self._empty_frame()

        frame = frame.copy()
        frame["trade_time"] = pd.to_datetime(frame["trade_time"], errors="coerce")
        frame = frame.dropna(subset=["trade_time"])
        if frame.empty:
            return self._empty_frame()

        for numeric_col in ["open", "high", "low", "close", "volume", "amount"]:
            if numeric_col in frame.columns:
                frame[numeric_col] = pd.to_numeric(frame[numeric_col], errors="coerce")
            else:
                frame[numeric_col] = 0.0

        frame["close"] = frame["close"].fillna(frame["open"])
        frame["open"] = frame["open"].fillna(frame["close"])
        frame["high"] = frame["high"].fillna(frame["close"])
        frame["low"] = frame["low"].fillna(frame["close"])
        frame["volume"] = frame["volume"].fillna(0.0)
        frame["amount"] = frame["amount"].fillna(frame["close"] * frame["volume"])

        frame["symbol"] = self.normalize_symbol(symbol)
        frame["trade_date"] = frame["trade_time"].dt.strftime("%Y-%m-%d")

        frame = frame.drop_duplicates(subset=["trade_time"], keep="last")
        frame = frame.sort_values("trade_time").reset_index(drop=True)

        frame = frame[self.STANDARD_COLUMNS]
        return frame

    @staticmethod
    def _to_sina_symbol(symbol: str) -> str:
        if symbol.startswith("6"):
            return f"sh{symbol}"
        return f"sz{symbol}"

    def _read_cache(self, symbol: str) -> Optional[pd.DataFrame]:
        if self.cache_ttl_seconds <= 0:
            return None
        with self._cache_lock:
            cache_item = self._cache.get(symbol)
            if cache_item is None:
                return None

            cached_at: datetime = cache_item["cached_at"]  # type: ignore[assignment]
            elapsed = (datetime.now() - cached_at).total_seconds()
            if elapsed > self.cache_ttl_seconds:
                self._cache.pop(symbol, None)
                return None

            frame = cache_item["frame"]  # type: ignore[assignment]
            if isinstance(frame, pd.DataFrame):
                return frame.copy()
            return None

    def _write_cache(self, symbol: str, frame: pd.DataFrame):
        if self.cache_ttl_seconds <= 0:
            return
        with self._cache_lock:
            self._cache[symbol] = {
                "cached_at": datetime.now(),
                "frame": frame.copy(),
            }

    def _empty_frame(self) -> pd.DataFrame:
        return pd.DataFrame(columns=self.STANDARD_COLUMNS)
