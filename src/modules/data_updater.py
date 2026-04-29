# -*- coding: utf-8 -*-
"""
鏁版嵁鏇存柊妯″潡
璐熻矗浠嶵ushare/adata鑾峰彇A鑲℃暟鎹苟鏇存柊鍒版湰鍦版暟鎹簱
"""

import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional
import pandas as pd

from src.core.logger import get_logger
from src.core.config import ConfigManager
from src.core.database import DatabaseManager
from src.core.exceptions import DataSourceException, DatabaseException

logger = get_logger("data_updater")


class DataSourceBase:
    """鏁版嵁婧愬熀绫?"""
    
    def __init__(self, config: ConfigManager):
        self.config = config
        self.retry_times = config.get("data_source.retry_times", 3)
        self.retry_delay = config.get("data_source.retry_delay", 5)
        self.fail_fast_on_quota_limit = bool(
            config.get("data_source.fail_fast_on_quota_limit", True)
        )
        self._quota_limited_until_ts = 0.0
        self._last_quota_error = ""
        self._quota_error_keywords = (
            "\u6bcf\u5206\u949f\u6700\u591a\u8bbf\u95ee\u8be5\u63a5\u53e3",
            "\u6bcf\u5c0f\u65f6\u6700\u591a\u8bbf\u95ee\u8be5\u63a5\u53e3",
            "\u6bcf\u5929\u6700\u591a\u8bbf\u95ee\u8be5\u63a5\u53e3",
            "\u79ef\u5206",
            "\u6743\u9650\u7684\u5177\u4f53\u8be6\u60c5",
            "per minute",
            "per hour",
            "quota",
        )
    
    def get_quota_cooldown_remaining(self) -> float:
        return max(0.0, float(self._quota_limited_until_ts - time.time()))

    def has_quota_cooldown(self) -> bool:
        return self.get_quota_cooldown_remaining() > 0

    def _quota_cooldown_seconds(self, error_text: str) -> float:
        text = str(error_text or "").lower()
        if not text:
            return 60.0
        if ("\u6bcf\u5206\u949f" in text) or ("minute" in text):
            return 65.0
        if ("\u6bcf\u5c0f\u65f6" in text) or ("hour" in text):
            return 3660.0
        if ("\u6bcf\u5929" in text) or ("\u6bcf\u65e5" in text) or ("day" in text):
            return 86460.0
        # Unknown quota message: conservative short cooldown.
        return 120.0

    def _retry_request(self, func, *args, **kwargs):
        """Request wrapper with retry and quota cooldown."""
        if self.has_quota_cooldown():
            remaining = int(self.get_quota_cooldown_remaining())
            logger.warning(
                "Data source in quota cooldown, skip request (remaining ~%ss)",
                remaining,
            )
            return None

        for i in range(self.retry_times):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                error_text = str(e or "")
                is_quota_limited = any(k in error_text for k in self._quota_error_keywords)
                if self.fail_fast_on_quota_limit and is_quota_limited:
                    cooldown_seconds = self._quota_cooldown_seconds(error_text)
                    self._quota_limited_until_ts = max(
                        self._quota_limited_until_ts,
                        time.time() + cooldown_seconds,
                    )
                    self._last_quota_error = error_text
                    logger.warning(
                        "Request hit upstream quota limit, fail fast (no retry): %s",
                        error_text,
                    )
                    raise e

                if i < self.retry_times - 1:
                    logger.warning(
                        "Request failed, retry after %ss (%s/%s): %s",
                        self.retry_delay,
                        i + 1,
                        self.retry_times,
                        e,
                    )
                    time.sleep(self.retry_delay)
                else:
                    raise e
        return None

class TushareDataSource(DataSourceBase):
    """Tushare鏁版嵁婧?"""
    
    def __init__(self, config: ConfigManager):
        super().__init__(config)
        self.token = config.get("data_source.tushare_token", "")
        self._pro = None
    
    def _init_pro(self):
        """鍒濆鍖朤ushare Pro鎺ュ彛"""
        if self._pro is None:
            try:
                import tushare as ts
                ts.set_token(self.token)
                self._pro = ts.pro_api()
                import os
                os.environ.setdefault("TUSHARE_TIMEOUT", "30")
                logger.info("Tushare initialized successfully")
            except Exception as e:
                logger.error(f"Tushare鍒濆鍖栧け璐? {e}")
                raise DataSourceException(f"Tushare鍒濆鍖栧け璐? {e}", "tushare")
        return self._pro
    
    def get_stock_basic(self) -> pd.DataFrame:
        """鑾峰彇鑲＄エ鍩虹淇℃伅"""
        pro = self._init_pro()
        
        def _request():
            df = pro.stock_basic(exchange='', list_status='L', fields='ts_code,symbol,name,industry,list_date')
            return df
        
        df = self._retry_request(_request)
        if df is not None and not df.empty:
            logger.info("Fetched stock basic data, rows=%s", len(df))
        return df if df is not None else pd.DataFrame()
    
    def get_daily_data(self, ts_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        """
        鑾峰彇鏃ョ嚎琛屾儏鏁版嵁
        
        Args:
            ts_code: 鑲＄エ浠ｇ爜
            start_date: 寮€濮嬫棩鏈?YYYYMMDD
            end_date: 缁撴潫鏃ユ湡 YYYYMMDD
        
        Returns:
            鏃ョ嚎鏁版嵁DataFrame
        """
        pro = self._init_pro()
        
        def _request():
            df = pro.daily(ts_code=ts_code, start_date=start_date, end_date=end_date)
            return df
        
        df = self._retry_request(_request)
        return df if df is not None else pd.DataFrame()
    
    def get_daily_data_batch(self, trade_date: str) -> pd.DataFrame:
        """
        鎵归噺鑾峰彇鏌愭棩鍏ㄩ儴鑲＄エ琛屾儏
        
        Args:
            trade_date: 浜ゆ槗鏃ユ湡 YYYYMMDD
        
        Returns:
            鏃ョ嚎鏁版嵁DataFrame
        """
        pro = self._init_pro()
        
        def _request():
            df = pro.daily(trade_date=trade_date)
            return df
        
        df = self._retry_request(_request)
        if df is not None and not df.empty:
            logger.info("Fetched daily data for %s, rows=%s", trade_date, len(df))
        return df if df is not None else pd.DataFrame()
    
    def get_chip_perf_batch(self, trade_date: str) -> pd.DataFrame:
        """閹靛綊鍣洪懢宄板絿閺屾劖妫╃粵鍦垳濮掑倽顩﹂弫鐗堝祦閵?"""
        pro = self._init_pro()

        def _request():
            return pro.cyq_perf(
                trade_date=trade_date,
                fields=(
                    "ts_code,trade_date,cost_5pct,cost_15pct,cost_50pct,"
                    "cost_85pct,cost_95pct,weight_avg,winner_rate"
                ),
            )

        df = self._retry_request(_request)
        if df is not None and not df.empty:
            logger.info("Fetched chip summary for %s, rows=%s", trade_date, len(df))
        return df if df is not None else pd.DataFrame()

    def get_chip_distribution(
        self,
        ts_code: str,
        start_date: str,
        end_date: str,
    ) -> pd.DataFrame:
        """Fetch chip distribution rows (`cyq_chips`) for one symbol."""
        pro = self._init_pro()

        def _request():
            return pro.cyq_chips(
                ts_code=ts_code,
                start_date=start_date,
                end_date=end_date,
            )

        df = self._retry_request(_request)
        if df is not None and not df.empty:
            logger.info(
                "Fetched chip distribution: %s [%s~%s], rows=%s",
                ts_code,
                start_date,
                end_date,
                len(df),
            )
        return df if df is not None else pd.DataFrame()

    def get_index_daily(self, ts_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        """鑾峰彇鎸囨暟鏃ョ嚎鏁版嵁"""
        pro = self._init_pro()
        
        def _request():
            df = pro.index_daily(ts_code=ts_code, start_date=start_date, end_date=end_date)
            return df
        
        df = self._retry_request(_request)
        return df if df is not None else pd.DataFrame()
    
    def get_trade_calendar(self, start_date: str, end_date: str) -> List[str]:
        """鑾峰彇浜ゆ槗鏃ュ巻"""
        pro = self._init_pro()
        
        def _request():
            df = pro.trade_cal(exchange='SSE', start_date=start_date, end_date=end_date, is_open='1')
            return df['cal_date'].tolist() if df is not None and not df.empty else []
        
        trade_dates = self._retry_request(_request)
        return trade_dates if trade_dates else []


class AdataDataSource(DataSourceBase):
    """adata澶囩敤鏁版嵁婧?"""
    
    def __init__(self, config: ConfigManager):
        super().__init__(config)
    
    def get_stock_basic(self) -> pd.DataFrame:
        """鑾峰彇鑲＄エ鍩虹淇℃伅"""
        try:
            import adata
            
            def _request():
                df = adata.stock.info.all_code()
                return df
            
            df = self._retry_request(_request)
            if df is not None and not df.empty:
                # 杞崲鍒楀悕浠ュ尮閰峊ushare鏍煎紡
                df = df.rename(columns={
                    'stock_code': 'ts_code',
                    'code': 'symbol',
                    'short_name': 'name'
                })
                logger.info("Fetched stock basic data from adata, rows=%s", len(df))
            return df if df is not None else pd.DataFrame()
        except Exception as e:
            logger.error(f"adata鑾峰彇鑲＄エ鍩虹淇℃伅澶辫触: {e}")
            return pd.DataFrame()
    
    def get_daily_data(self, ts_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        """鑾峰彇鏃ョ嚎琛屾儏鏁版嵁"""
        try:
            import adata
            
            # 杞崲鏃ユ湡鏍煎紡
            start_date_fmt = f"{start_date[:4]}-{start_date[4:6]}-{start_date[6:]}"
            end_date_fmt = f"{end_date[:4]}-{end_date[4:6]}-{end_date[6:]}"
            
            def _request():
                df = adata.stock.market.get_market(stock_code=ts_code[:6], start_date=start_date_fmt, end_date=end_date_fmt)
                return df
            
            df = self._retry_request(_request)
            if df is not None and not df.empty:
                # 杞崲鍒楀悕
                df = df.rename(columns={
                    'trade_date': 'trade_date',
                    'open': 'open',
                    'close': 'close',
                    'high': 'high',
                    'low': 'low',
                    'volume': 'vol',
                    'amount': 'amount'
                })
                df['ts_code'] = ts_code
            return df if df is not None else pd.DataFrame()
        except Exception as e:
            logger.error(f"adata鑾峰彇鏃ョ嚎鏁版嵁澶辫触: {e}")
            return pd.DataFrame()


class DataUpdater:
    MAINBOARD_PREFIXES = ("600", "601", "603", "605", "000", "001", "002", "003")
    """鏁版嵁鏇存柊鍣?"""
    
    def __init__(self, config: ConfigManager = None, db: DatabaseManager = None):
        """
        鍒濆鍖栨暟鎹洿鏂板櫒
        
        Args:
            config: 閰嶇疆绠＄悊鍣?            db: 鏁版嵁搴撶鐞嗗櫒
        """
        if config is None:
            config = ConfigManager()
        if db is None:
            db = DatabaseManager(config)
        
        self.config = config
        self.db = db
        
        # 鍒濆鍖栨暟鎹簮
        primary_source = config.get("data_source.primary", "tushare")
        if primary_source == "tushare":
            self.primary_source = TushareDataSource(config)
        else:
            self.primary_source = AdataDataSource(config)
        
        secondary_source = config.get("data_source.secondary", "adata")
        if secondary_source == "adata":
            self.secondary_source = AdataDataSource(config)
        else:
            self.secondary_source = TushareDataSource(config)
        
        logger.info(f"鏁版嵁鏇存柊鍣ㄥ垵濮嬪寲瀹屾垚锛屼富鏁版嵁婧? {primary_source}锛屽鐢ㄦ暟鎹簮: {secondary_source}")

    @classmethod
    def _is_mainboard_symbol(cls, ts_code: str) -> bool:
        code = str(ts_code or "").strip().upper()
        if "." in code:
            code = code.split(".", 1)[0]
        return code.startswith(cls.MAINBOARD_PREFIXES)

    @staticmethod
    def _normalize_trade_date(value: Optional[str]) -> Optional[str]:
        text = str(value or "").strip()
        if not text:
            return None
        text = text.replace("-", "")
        return text if len(text) == 8 and text.isdigit() else None

    @staticmethod
    def _compact_to_dash(value: str) -> str:
        compact = str(value or "").replace("-", "")
        if len(compact) != 8:
            return str(value or "")
        return f"{compact[:4]}-{compact[4:6]}-{compact[6:8]}"

    def _resolve_trade_calendar(self, start_compact: str, end_compact: str) -> List[str]:
        for source in (self.primary_source, self.secondary_source):
            if hasattr(source, "get_trade_calendar"):
                try:
                    dates = source.get_trade_calendar(start_compact, end_compact)
                    if dates:
                        return sorted(
                            {
                                date_text
                                for date_text in (self._normalize_trade_date(item) for item in dates)
                                if date_text
                            }
                        )
                except Exception as exc:
                    logger.warning(f"鑾峰彇浜ゆ槗鏃ュ巻澶辫触: {exc}")
        return []

    def _resolve_startup_target_trade_date(self, reference_time: Optional[datetime] = None) -> Optional[str]:
        now = reference_time or datetime.now()
        lookback_days = int(self.config.get("data_source.startup_trade_calendar_lookback_days", 14) or 14)
        ready_time_text = str(
            self.config.get(
                "data_source.startup_update_ready_time",
                self.config.get("scheduler.data_update_time", "17:30"),
            )
            or "17:30"
        ).strip()
        try:
            ready_hour, ready_minute = [int(part) for part in ready_time_text.split(":", 1)]
        except Exception:
            ready_hour, ready_minute = 17, 30

        start_compact = (now - timedelta(days=max(lookback_days, 3))).strftime("%Y%m%d")
        end_compact = now.strftime("%Y%m%d")
        trade_dates = self._resolve_trade_calendar(start_compact, end_compact)
        if not trade_dates:
            return None

        target = trade_dates[-1]
        current_hhmm = now.hour * 100 + now.minute
        ready_hhmm = ready_hour * 100 + ready_minute
        if target == end_compact and current_hhmm < ready_hhmm and len(trade_dates) >= 2:
            return trade_dates[-2]
        return target

    def _get_mainboard_stock_basic_count(self) -> int:
        row = self.db.query_one(
            """
            SELECT COUNT(*) AS cnt
            FROM stock_basic
            WHERE (
                ts_code LIKE '600%.SH' OR ts_code LIKE '601%.SH' OR ts_code LIKE '603%.SH' OR ts_code LIKE '605%.SH'
                OR ts_code LIKE '000%.SZ' OR ts_code LIKE '001%.SZ' OR ts_code LIKE '002%.SZ' OR ts_code LIKE '003%.SZ'
            )
            """
        )
        return int((row or {}).get("cnt") or 0)

    def _get_mainboard_daily_count(self, trade_date: str) -> int:
        compact = self._normalize_trade_date(trade_date)
        if not compact:
            return 0
        row = self.db.query_one(
            """
            SELECT COUNT(DISTINCT ts_code) AS cnt
            FROM stock_daily
            WHERE trade_date = ?
              AND (
                ts_code LIKE '600%.SH' OR ts_code LIKE '601%.SH' OR ts_code LIKE '603%.SH' OR ts_code LIKE '605%.SH'
                OR ts_code LIKE '000%.SZ' OR ts_code LIKE '001%.SZ' OR ts_code LIKE '002%.SZ' OR ts_code LIKE '003%.SZ'
              )
            """,
            (compact,),
        )
        return int((row or {}).get("cnt") or 0)

    def _get_mainboard_chip_count(self, trade_date: str) -> int:
        compact = self._normalize_trade_date(trade_date)
        if not compact:
            return 0
        try:
            row = self.db.query_one(
                """
                SELECT COUNT(DISTINCT ts_code) AS cnt
                FROM stock_chip_perf
                WHERE trade_date = ?
                  AND (
                    ts_code LIKE '600%.SH' OR ts_code LIKE '601%.SH' OR ts_code LIKE '603%.SH' OR ts_code LIKE '605%.SH'
                    OR ts_code LIKE '000%.SZ' OR ts_code LIKE '001%.SZ' OR ts_code LIKE '002%.SZ' OR ts_code LIKE '003%.SZ'
                  )
                """,
                (compact,),
            )
            return int((row or {}).get("cnt") or 0)
        except Exception:
            # Some lightweight test doubles may not implement this query.
            return 0

    def _chip_sources(self) -> List[DataSourceBase]:
        sources: List[DataSourceBase] = []
        for source in (self.primary_source, self.secondary_source):
            if hasattr(source, "get_chip_perf_batch") and source not in sources:
                sources.append(source)
        return sources

    def _chip_dist_sources(self) -> List[DataSourceBase]:
        sources: List[DataSourceBase] = []
        for source in (self.primary_source, self.secondary_source):
            if hasattr(source, "get_chip_distribution") and source not in sources:
                sources.append(source)
        return sources

    @staticmethod
    def _source_quota_cooldown_remaining(source: DataSourceBase) -> float:
        getter = getattr(source, "get_quota_cooldown_remaining", None)
        if callable(getter):
            try:
                return float(getter() or 0.0)
            except Exception:
                return 0.0
        return 0.0

    def _any_source_in_quota_cooldown(
        self,
        sources: Optional[List[DataSourceBase]] = None,
    ) -> bool:
        target_sources = sources or [self.primary_source, self.secondary_source]
        for source in target_sources:
            if self._source_quota_cooldown_remaining(source) > 0:
                return True
        return False

    @staticmethod
    def _normalize_chip_dist_df(df: pd.DataFrame) -> pd.DataFrame:
        if df is None or df.empty:
            return pd.DataFrame(columns=["ts_code", "trade_date", "price", "weight"])

        normalized = df.copy()
        col_map = {str(col).lower(): str(col) for col in normalized.columns}

        price_col = None
        for candidate in ("price", "cost_price"):
            if candidate in col_map:
                price_col = col_map[candidate]
                break
        weight_col = None
        for candidate in ("percent", "weight", "ratio", "chip"):
            if candidate in col_map:
                weight_col = col_map[candidate]
                break
        ts_col = col_map.get("ts_code")
        td_col = col_map.get("trade_date")

        if not all([price_col, weight_col, ts_col, td_col]):
            return pd.DataFrame(columns=["ts_code", "trade_date", "price", "weight"])

        out = normalized[[ts_col, td_col, price_col, weight_col]].copy()
        out.columns = ["ts_code", "trade_date", "price", "weight"]
        out["trade_date"] = out["trade_date"].astype(str).str.replace("-", "", regex=False)
        out["price"] = pd.to_numeric(out["price"], errors="coerce")
        out["weight"] = pd.to_numeric(out["weight"], errors="coerce")
        out = out.dropna(subset=["ts_code", "trade_date", "price", "weight"]).copy()

        if out.empty:
            return out

        # Convert 0~100 percentages to 0~1 weights.
        if float(out["weight"].max()) > 1.5:
            out["weight"] = out["weight"] / 100.0

        out["weight"] = out["weight"].clip(lower=0.0)
        return out

    def sync_chip_perf_with_latest_data(self, reference_trade_date: str = None) -> Dict[str, object]:
        """
        閸氬本顒炵粵鍦垳濮掑倽顩﹂弫鐗堝祦閸掔増娓堕弬棰佹唉閺勬挻妫╅妴?

        - 婵″倹鐏?stock_chip_perf 閺堝秴濮熸＃鏍偧閸氼垳鏁ら敍宀勭帛鐠併倕娲栫悰?30 娑擃亙姘﹂弰鎾存）
        - 閸氬海鐢婚崣顏囁夋鎰繁婢惰京娈戞禍銈嗘閺?
        """
        latest_daily = self._normalize_trade_date(reference_trade_date) or self._normalize_trade_date(
            self.db.get_latest_trade_date("stock_daily")
        )
        result: Dict[str, object] = {
            "updated_rows": 0,
            "updated_dates": [],
            "target_trade_date": latest_daily,
            "latest_chip_trade_date_before": self._normalize_trade_date(
                self.db.get_latest_trade_date("stock_chip_perf")
            ),
            "latest_chip_trade_date_after": None,
        }
        if not latest_daily:
            result["message"] = "stock_daily 閺堫亜鍣径鍥с偨閿涘本妫ゅ▔鏇炴倱濮濄儳顒查惍浣规殶閹?"
            return result

        chip_sources = self._chip_sources()
        if not chip_sources:
            result["message"] = "No data source available for chip perf sync."
            result["latest_chip_trade_date_after"] = result["latest_chip_trade_date_before"]
            return result

        latest_chip = str(result["latest_chip_trade_date_before"] or "")
        bootstrap_days = int(self.config.get("data_source.chip_perf_bootstrap_trade_days", 30) or 30)
        start_anchor = (
            datetime.strptime(latest_daily, "%Y%m%d") - timedelta(days=max(bootstrap_days * 3, 45))
        ).strftime("%Y%m%d")
        trade_dates = self._resolve_trade_calendar(start_anchor, latest_daily)
        if not trade_dates:
            trade_dates = [latest_daily]

        if latest_chip and latest_chip >= latest_daily:
            if self._get_mainboard_chip_count(latest_daily) > 0:
                result["updated_dates"] = []
                result["latest_chip_trade_date_after"] = latest_chip
                result["message"] = "缁涘湱鐖滈弫鐗堝祦瀹稿弶妲搁張鈧弬?"
                return result
            dates_to_update = [latest_daily]
        elif latest_chip:
            dates_to_update = [date_text for date_text in trade_dates if date_text > latest_chip]
        else:
            dates_to_update = trade_dates[-bootstrap_days:]

        total_rows = 0
        updated_dates: List[str] = []
        quota_blocked = False
        for trade_date in dates_to_update:
            if self._any_source_in_quota_cooldown(chip_sources):
                quota_blocked = True
                logger.warning(
                    "Quota cooldown detected while syncing chip perf, stop remaining dates."
                )
                break
            count = int(self.update_chip_perf(self._compact_to_dash(trade_date)) or 0)
            if count > 0:
                total_rows += count
                updated_dates.append(trade_date)
            sleep_seconds = float(self.config.get("data_source.chip_perf_update_sleep_seconds", 0.3) or 0.3)
            if sleep_seconds > 0:
                time.sleep(sleep_seconds)

        latest_after = self._normalize_trade_date(self.db.get_latest_trade_date("stock_chip_perf"))
        result["updated_rows"] = total_rows
        result["updated_dates"] = updated_dates
        result["latest_chip_trade_date_after"] = latest_after
        if quota_blocked and updated_dates:
            result["message"] = (
                f"chip perf partial sync completed ({len(updated_dates)} dates), "
                "stopped by quota cooldown"
            )
        elif quota_blocked:
            result["message"] = "chip perf sync paused by quota cooldown"
        else:
            result["message"] = (
                f"缁涘湱鐖滈弫鐗堝祦閸氬本顒炵€瑰本鍨氶敍灞炬纯閺?{len(updated_dates)} 娑擃亙姘﹂弰鎾存）"
                if updated_dates
                else "缁涘湱鐖滈弫鐗堝祦閺冪娀娓堕弴瀛樻煀"
            )
        return result
    
    def _try_data_source(self, source_func, fallback_func=None):
        """
        灏濊瘯浣跨敤涓绘暟鎹簮锛屽け璐ュ垯鍒囨崲澶囩敤鏁版嵁婧?        
        Args:
            source_func: 涓绘暟鎹簮鍑芥暟锛堟棤鍙傛暟鐨勫彲璋冪敤瀵硅薄锛?            fallback_func: 澶囩敤鏁版嵁婧愬嚱鏁帮紙鏃犲弬鏁扮殑鍙皟鐢ㄥ璞★級
        
        Returns:
            鏁版嵁缁撴灉
        """
        try:
            result = source_func()
            if result is not None and (not isinstance(result, pd.DataFrame) or not result.empty):
                return result
        except Exception as e:
            logger.warning(f"涓绘暟鎹簮璇锋眰澶辫触: {e}")
        
        # 灏濊瘯澶囩敤鏁版嵁婧?        if fallback_func is not None:
            try:
                logger.info("鍒囨崲鍒板鐢ㄦ暟鎹簮...")
                result = fallback_func()
                if result is not None and (not isinstance(result, pd.DataFrame) or not result.empty):
                    return result
            except Exception as e:
                logger.error(f"澶囩敤鏁版嵁婧愯姹傚け璐? {e}")
        
        return pd.DataFrame()
    
    def update_stock_basic(self) -> int:
        """
        鏇存柊鑲＄エ鍩虹淇℃伅
        
        Returns:
            鏇存柊鐨勮褰曟暟
        """
        logger.info("寮€濮嬫洿鏂拌偂绁ㄥ熀纭€淇℃伅...")
        
        # 鑾峰彇鏁版嵁
        df = self._try_data_source(
            self.primary_source.get_stock_basic,
            self.secondary_source.get_stock_basic
        )
        
        if df.empty:
            logger.warning("鏈幏鍙栧埌鑲＄エ鍩虹淇℃伅鏁版嵁")
            return 0
        
        # Normalize common backup-source columns and drop invalid rows.
        if "ts_code" not in df.columns:
            for alt in ("stock_code", "code", "symbol"):
                if alt in df.columns:
                    df["ts_code"] = df[alt]
                    break
        if "symbol" not in df.columns:
            for alt in ("code", "stock_code"):
                if alt in df.columns:
                    df["symbol"] = df[alt]
                    break
        if "name" not in df.columns:
            for alt in ("short_name", "stock_name"):
                if alt in df.columns:
                    df["name"] = df[alt]
                    break
        if "symbol" not in df.columns and "ts_code" in df.columns:
            df["symbol"] = df["ts_code"].astype(str).str.split(".").str[0]
        if "name" not in df.columns and "ts_code" in df.columns:
            df["name"] = df["ts_code"]
        if "industry" not in df.columns:
            df["industry"] = None
        if "list_date" not in df.columns:
            df["list_date"] = None

        df = df.where(pd.notnull(df), None)

        # Fallback derive symbol/name from ts_code when backup source is sparse.
        if "symbol" in df.columns and "ts_code" in df.columns:
            df["symbol"] = df["symbol"].where(df["symbol"].notna(), df["ts_code"].astype(str).str.split(".").str[0])
        if "name" in df.columns and "ts_code" in df.columns:
            df["name"] = df["name"].where(df["name"].notna(), df["ts_code"])

        required = ["ts_code", "symbol", "name"]
        before_rows = len(df)
        df = df.dropna(subset=required)
        if len(df) < before_rows:
            logger.warning("stock_basic dropped invalid rows: %s -> %s", before_rows, len(df))
        
        # 鍑嗗鎻掑叆鏁版嵁
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        params_list = []
        
        for _, row in df.iterrows():
            params_list.append((
                row.get('ts_code'),
                row.get('symbol'),
                row.get('name'),
                row.get('industry'),
                row.get('list_date'),
                current_time,
                current_time
            ))
        
        # 浣跨敤REPLACE INTO瀹炵幇upsert
        sql = """
            REPLACE INTO stock_basic (ts_code, symbol, name, industry, list_date, create_time, update_time)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """
        
        try:
            count = self.db.execute_many(sql, params_list)
            logger.info("Stock basic upsert completed, rows=%s", count)
            return count
        except Exception as e:
            logger.error(f"鑲＄エ鍩虹淇℃伅鍏ュ簱澶辫触: {e}")
            raise DatabaseException(f"鑲＄エ鍩虹淇℃伅鍏ュ簱澶辫触: {e}")
    
    def update_daily_data(self, trade_date: str = None, days: int = 1) -> int:
        """
        鏇存柊鏃ョ嚎琛屾儏鏁版嵁
        
        Args:
            trade_date: 浜ゆ槗鏃ユ湡 YYYY-MM-DD鏍煎紡锛岄粯璁や负褰撳ぉ
            days: 鏇存柊澶╂暟锛岄粯璁?澶?        
        Returns:
            鏇存柊鐨勮褰曟暟
        """
        if trade_date is None:
            trade_date = datetime.now().strftime("%Y-%m-%d")
        
        logger.info(f"寮€濮嬫洿鏂版棩绾胯鎯呮暟鎹紝鏃ユ湡: {trade_date}")
        
        # 杞崲鏃ユ湡鏍煎紡涓篩YYYMMDD
        trade_date_compact = trade_date.replace("-", "")
        
        # 鎵归噺鑾峰彇褰撴棩鏁版嵁
        df = self._try_data_source(
            lambda: self.primary_source.get_daily_data_batch(trade_date_compact),
            None
        )
        
        if df.empty:
            logger.warning("No daily data returned for %s", trade_date)
            return 0
        
        # 鏁版嵁娓呮礂
        df = df.where(pd.notnull(df), None)
        
        # 鍑嗗鎻掑叆鏁版嵁
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        params_list = []
        
        for _, row in df.iterrows():
            # 璁＄畻娑ㄨ穼骞?            pct_chg = None
            if row.get('pre_close') and row.get('pre_close') != 0:
                pct_chg = round((row.get('close', 0) - row.get('pre_close')) / row.get('pre_close') * 100, 2)
            
            params_list.append((
                row.get('ts_code'),
                row.get('trade_date'),
                row.get('open'),
                row.get('close'),
                row.get('high'),
                row.get('low'),
                row.get('vol'),
                row.get('amount'),
                pct_chg,
                current_time
            ))
        
        sql = """
            REPLACE INTO stock_daily (ts_code, trade_date, open, close, high, low, vol, amount, pct_chg, create_time)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        
        try:
            count = self.db.execute_many(sql, params_list)
            logger.info("Daily data upsert completed for %s, rows=%s", trade_date, count)
            return count
        except Exception as e:
            logger.error(f"鏃ョ嚎琛屾儏鏁版嵁鍏ュ簱澶辫触: {e}")
            raise DatabaseException(f"鏃ョ嚎琛屾儏鏁版嵁鍏ュ簱澶辫触: {e}")
    
    def update_daily_data_range(self, start_date: str, end_date: str) -> int:
        """
        鏇存柊鏃ユ湡鑼冨洿鍐呯殑鏃ョ嚎鏁版嵁
        
        Args:
            start_date: 寮€濮嬫棩鏈?YYYY-MM-DD
            end_date: 缁撴潫鏃ユ湡 YYYY-MM-DD
        
        Returns:
            鎬绘洿鏂拌褰曟暟
        """
        logger.info(f"寮€濮嬫壒閲忔洿鏂版棩绾挎暟鎹紝鑼冨洿: {start_date} ~ {end_date}")
        
        # 鑾峰彇浜ゆ槗鏃ュ巻
        start_compact = start_date.replace("-", "")
        end_compact = end_date.replace("-", "")
        
        trade_dates = []
        if isinstance(self.primary_source, TushareDataSource):
            trade_dates = self.primary_source.get_trade_calendar(start_compact, end_compact)
        
        if not trade_dates:
            # 濡傛灉娌℃湁鑾峰彇鍒颁氦鏄撴棩鍘嗭紝鎸夎嚜鐒舵棩澶勭悊
            current = datetime.strptime(start_date, "%Y-%m-%d")
            end = datetime.strptime(end_date, "%Y-%m-%d")
            while current <= end:
                trade_dates.append(current.strftime("%Y%m%d"))
                current += timedelta(days=1)
        
        total_count = 0
        for trade_date_compact in trade_dates:
            trade_date = f"{trade_date_compact[:4]}-{trade_date_compact[4:6]}-{trade_date_compact[6:]}"
            count = self.update_daily_data(trade_date)
            total_count += count
            time.sleep(0.5)  # 閬垮厤璇锋眰杩囧揩
        
        logger.info("Batch daily update completed, total rows=%s", total_count)
        return total_count
    
    def update_chip_perf(self, trade_date: str = None) -> int:
        """閺囧瓨鏌婇弻鎰）缁涘湱鐖滃鍌濐洣閺佺増宓侀敍鍦昚Q perf閿涘鈧?"""
        trade_date = trade_date or datetime.now().strftime("%Y-%m-%d")
        trade_date_compact = self._normalize_trade_date(trade_date)
        if not trade_date_compact:
            logger.warning("缁涘湱鐖滈弫鐗堝祦閺囧瓨鏌婇弮銉︽埂閺冪姵鏅? %s", trade_date)
            return 0

        sources = self._chip_sources()
        if not sources:
            logger.warning("No data source available for chip perf sync.")
            return 0

        fallback = None
        if len(sources) >= 2:
            fallback = lambda: sources[1].get_chip_perf_batch(trade_date_compact)
        df = self._try_data_source(
            lambda: sources[0].get_chip_perf_batch(trade_date_compact),
            fallback,
        )

        if df.empty:
            logger.warning("閺堫亣骞忛崣鏍у煂 %s 閻ㄥ嫮顒查惍浣规殶閹?", trade_date_compact)
            return 0

        df = df.where(pd.notnull(df), None)
        if "ts_code" in df.columns:
            df = df[df["ts_code"].astype(str).map(self._is_mainboard_symbol)].copy()
        if df.empty:
            logger.warning("No mainboard chip perf data after filtering for %s", trade_date_compact)
            return 0

        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        params_list = []
        for _, row in df.iterrows():
            params_list.append(
                (
                    row.get("ts_code"),
                    row.get("trade_date"),
                    row.get("cost_5pct"),
                    row.get("cost_15pct"),
                    row.get("cost_50pct"),
                    row.get("cost_85pct"),
                    row.get("cost_95pct"),
                    row.get("weight_avg"),
                    row.get("winner_rate"),
                    current_time,
                )
            )

        sql = """
            REPLACE INTO stock_chip_perf (
                ts_code, trade_date, cost_5pct, cost_15pct, cost_50pct,
                cost_85pct, cost_95pct, weight_avg, winner_rate, create_time
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """

        try:
            count = self.db.execute_many(sql, params_list)
            logger.info("缁涘湱鐖滈弫鐗堝祦閺囧瓨鏌婄€瑰本鍨氶敍灞炬）閺? %s閿涘苯鍙?s閺?", trade_date_compact, count)
            return count
        except Exception as e:
            logger.error("缁涘湱鐖滈弫鐗堝祦閸忋儱绨辨径杈Е: %s", e)
            raise DatabaseException(f"缁涘湱鐖滈弫鐗堝祦閸忋儱绨辨径杈Е: {e}")

    def update_chip_perf_range(self, start_date: str, end_date: str) -> int:
        """閹靛綊鍣洪弴瀛樻煀閺冦儲婀￠懠鍐ㄦ纯閸愬懐娈戠粵鍦垳濮掑倽顩﹂弫鐗堝祦閵?"""
        start_compact = self._normalize_trade_date(start_date)
        end_compact = self._normalize_trade_date(end_date)
        if not start_compact or not end_compact:
            return 0

        trade_dates = self._resolve_trade_calendar(start_compact, end_compact)
        if not trade_dates:
            trade_dates = [start_compact] if start_compact == end_compact else []

        total_count = 0
        for trade_date_compact in trade_dates:
            total_count += int(self.update_chip_perf(self._compact_to_dash(trade_date_compact)) or 0)
            sleep_seconds = float(self.config.get("data_source.chip_perf_update_sleep_seconds", 0.3) or 0.3)
            if sleep_seconds > 0:
                time.sleep(sleep_seconds)
        return total_count

    def update_chip_dist(
        self,
        trade_date: str = None,
        symbols: Optional[List[str]] = None,
        max_symbols: Optional[int] = None,
    ) -> int:
        """
        Update chip distribution rows (`cyq_chips`) for one trade date.
        """
        trade_date_compact = self._normalize_trade_date(trade_date or datetime.now().strftime("%Y%m%d"))
        if not trade_date_compact:
            return 0

        source_list = self._chip_dist_sources()
        if not source_list:
            logger.warning("No data source supports cyq_chips.")
            return 0

        symbol_list: List[str] = []
        if symbols:
            symbol_list = [str(item).strip().upper() for item in symbols if str(item).strip()]
        else:
            rows = self.db.query(
                """
                SELECT ts_code
                FROM stock_basic
                WHERE (
                    ts_code LIKE '600%.SH' OR ts_code LIKE '601%.SH' OR ts_code LIKE '603%.SH' OR ts_code LIKE '605%.SH'
                    OR ts_code LIKE '000%.SZ' OR ts_code LIKE '001%.SZ' OR ts_code LIKE '002%.SZ' OR ts_code LIKE '003%.SZ'
                )
                ORDER BY ts_code
                """
            )
            symbol_list = [str(row.get("ts_code") or "").strip().upper() for row in rows]

        effective_max = int(
            max_symbols
            if max_symbols is not None
            else self.config.get("data_source.chip_dist_max_symbols_per_run", 1000)
            or 1000
        )
        if effective_max > 0:
            symbol_list = symbol_list[:effective_max]
        if not symbol_list:
            return 0

        all_rows: List[tuple] = []
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        request_sleep = float(self.config.get("data_source.chip_dist_request_sleep_seconds", 0.05) or 0.05)

        for ts_code in symbol_list:
            if self._any_source_in_quota_cooldown(source_list):
                logger.warning(
                    "Quota cooldown detected while syncing chip distribution, stop remaining symbols."
                )
                break
            raw_df = pd.DataFrame()
            for source in source_list:
                try:
                    raw_df = source.get_chip_distribution(ts_code, trade_date_compact, trade_date_compact)
                    if raw_df is not None and not raw_df.empty:
                        break
                except Exception as exc:
                    logger.debug("cyq_chips fetch failed for %s via %s: %s", ts_code, source.__class__.__name__, exc)
                    raw_df = pd.DataFrame()
            if raw_df is None or raw_df.empty:
                if request_sleep > 0:
                    time.sleep(request_sleep)
                continue

            dist_df = self._normalize_chip_dist_df(raw_df)
            if dist_df.empty:
                if request_sleep > 0:
                    time.sleep(request_sleep)
                continue

            dist_df = dist_df[dist_df["trade_date"] == trade_date_compact]
            if dist_df.empty:
                if request_sleep > 0:
                    time.sleep(request_sleep)
                continue

            for _, row in dist_df.iterrows():
                all_rows.append(
                    (
                        row.get("ts_code"),
                        row.get("trade_date"),
                        row.get("price"),
                        row.get("weight"),
                        current_time,
                    )
                )
            if request_sleep > 0:
                time.sleep(request_sleep)

        if not all_rows:
            logger.warning("No cyq_chips rows collected for %s.", trade_date_compact)
            return 0

        sql = """
            REPLACE INTO stock_chip_dist (ts_code, trade_date, price, weight, create_time)
            VALUES (?, ?, ?, ?, ?)
        """
        try:
            count = self.db.execute_many(sql, all_rows)
            logger.info(
                "Chip distribution updated for %s: symbols=%d rows=%d",
                trade_date_compact,
                len(symbol_list),
                count,
            )
            return count
        except Exception as exc:
            logger.error("Failed to save chip distribution rows: %s", exc)
            raise DatabaseException(f"chip distribution upsert failed: {exc}")

    def sync_chip_dist_with_latest_data(
        self,
        reference_trade_date: str = None,
        symbols: Optional[List[str]] = None,
        max_symbols: Optional[int] = None,
    ) -> Dict[str, object]:
        latest_daily = self._normalize_trade_date(reference_trade_date) or self._normalize_trade_date(
            self.db.get_latest_trade_date("stock_daily")
        )
        result: Dict[str, object] = {
            "updated_rows": 0,
            "target_trade_date": latest_daily,
        }
        if not latest_daily:
            result["message"] = "No daily trade date available."
            return result

        row = self.db.query_one(
            """
            SELECT COUNT(*) AS cnt
            FROM stock_chip_dist
            WHERE trade_date = ?
            """,
            (latest_daily,),
        )
        existing_count = int((row or {}).get("cnt") or 0)
        min_rows = int(self.config.get("data_source.chip_dist_min_rows_per_day", 1000) or 1000)
        if existing_count >= min_rows:
            result["message"] = "chip distribution already up to date"
            return result

        updated = int(
            self.update_chip_dist(
                trade_date=latest_daily,
                symbols=symbols,
                max_symbols=max_symbols,
            )
            or 0
        )
        result["updated_rows"] = updated
        result["message"] = "chip distribution synced" if updated > 0 else "chip distribution sync skipped"
        return result

    def update_index_data(self, index_code: str, days: int = 30) -> int:
        """
        鏇存柊鎸囨暟鏁版嵁
        
        Args:
            index_code: 鎸囨暟浠ｇ爜
            days: 鏇存柊澶╂暟
        
        Returns:
            鏇存柊鐨勮褰曟暟
        """
        logger.info(f"寮€濮嬫洿鏂版寚鏁版暟鎹? {index_code}")
        
        end_date = datetime.now().strftime("%Y%m%d")
        start_date = (datetime.now() - timedelta(days=days)).strftime("%Y%m%d")
        
        if isinstance(self.primary_source, TushareDataSource):
            df = self.primary_source.get_index_daily(index_code, start_date, end_date)
        else:
            logger.warning("褰撳墠鏁版嵁婧愪笉鏀寔鎸囨暟鏁版嵁鑾峰彇")
            return 0
        
        if df.empty:
            logger.warning("No index data returned for %s", index_code)
            return 0
        
        # 鏁版嵁娓呮礂
        df = df.where(pd.notnull(df), None)
        
        # 鍑嗗鎻掑叆鏁版嵁
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        params_list = []
        
        for _, row in df.iterrows():
            params_list.append((
                row.get('ts_code'),
                row.get('trade_date'),
                row.get('open'),
                row.get('close'),
                row.get('high'),
                row.get('low'),
                row.get('vol'),
                row.get('amount'),
                row.get('pct_chg'),
                current_time
            ))
        
        sql = """
            REPLACE INTO stock_daily (ts_code, trade_date, open, close, high, low, vol, amount, pct_chg, create_time)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        
        try:
            count = self.db.execute_many(sql, params_list)
            logger.info("Index data update completed for %s, rows=%s", index_code, count)
            return count
        except Exception as e:
            logger.error(f"鎸囨暟鏁版嵁鍏ュ簱澶辫触: {e}")
            raise DatabaseException(f"鎸囨暟鏁版嵁鍏ュ簱澶辫触: {e}")

    def ensure_latest_market_data(self, reference_time: Optional[datetime] = None) -> dict:
        """鍚姩鏃舵牎楠屽苟琛ラ綈鏈€鏂板競鍦烘暟鎹€?"""
        now = reference_time or datetime.now()
        result = {
            "start_time": now.strftime("%Y-%m-%d %H:%M:%S"),
            "status": "success",
            "message": "",
            "stock_basic_count": 0,
            "daily_data_count": 0,
            "index_data_count": 0,
            "chip_perf_count": 0,
            "chip_dist_count": 0,
            "stock_basic_refreshed": False,
            "latest_trade_date_before": self._normalize_trade_date(self.db.get_latest_trade_date("stock_daily")),
            "latest_trade_date_after": None,
            "target_trade_date": None,
            "mainboard_stock_count": 0,
            "mainboard_daily_count_before": 0,
            "mainboard_daily_count_after": 0,
            "mainboard_chip_count_after": 0,
            "latest_chip_trade_date_before": self._normalize_trade_date(self.db.get_latest_trade_date("stock_chip_perf")),
            "latest_chip_trade_date_after": None,
            "chip_updated_dates": [],
            "chip_dist_message": "",
            "missing_trade_dates": [],
        }

        try:
            refresh_basic = bool(self.config.get("data_source.startup_refresh_stock_basic", True))
            if refresh_basic:
                result["stock_basic_count"] = int(self.update_stock_basic() or 0)
                result["stock_basic_refreshed"] = True

            result["mainboard_stock_count"] = self._get_mainboard_stock_basic_count()
            target_trade_date = self._resolve_startup_target_trade_date(reference_time=now)
            result["target_trade_date"] = target_trade_date
            if not target_trade_date:
                result["status"] = "skipped"
                result["message"] = "Unable to resolve target trade date; startup sync skipped"
                result["latest_trade_date_after"] = result["latest_trade_date_before"]
                result["end_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                return result

            latest_before = result["latest_trade_date_before"]
            result["mainboard_daily_count_before"] = self._get_mainboard_daily_count(
                latest_before or target_trade_date
            )
            coverage_ratio = float(
                self.config.get("data_source.startup_min_mainboard_coverage_ratio", 0.7) or 0.7
            )
            expected_floor = int(result["mainboard_stock_count"] * coverage_ratio)
            missing_trade_dates: List[str] = []

            if latest_before is None:
                missing_trade_dates = [target_trade_date]
            elif latest_before < target_trade_date:
                next_day = (datetime.strptime(latest_before, "%Y%m%d") + timedelta(days=1)).strftime("%Y%m%d")
                missing_trade_dates = [
                    date_text
                    for date_text in self._resolve_trade_calendar(next_day, target_trade_date)
                    if date_text and date_text > latest_before
                ]
                if not missing_trade_dates:
                    missing_trade_dates = [target_trade_date]
            elif latest_before == target_trade_date:
                current_count = self._get_mainboard_daily_count(target_trade_date)
                if current_count <= 0 or (expected_floor > 0 and current_count < expected_floor):
                    missing_trade_dates = [target_trade_date]

            result["missing_trade_dates"] = missing_trade_dates

            if missing_trade_dates:
                if len(missing_trade_dates) == 1:
                    result["daily_data_count"] = int(
                        self.update_daily_data(self._compact_to_dash(missing_trade_dates[0])) or 0
                    )
                else:
                    result["daily_data_count"] = int(
                        self.update_daily_data_range(
                            self._compact_to_dash(missing_trade_dates[0]),
                            self._compact_to_dash(missing_trade_dates[-1]),
                        )
                        or 0
                    )

                indices = self.config.get("market_analysis.indices", ["000001.SH", "399001.SZ", "399006.SZ"])
                for index_code in indices:
                    result["index_data_count"] += int(self.update_index_data(index_code, days=30) or 0)
            else:
                result["message"] = "鏃ョ嚎涓庡綋鍓嶄富鏉挎暟鎹凡鏄渶鏂帮紝鏃犻渶琛ラ綈"

            startup_sync_chip_data_enabled = bool(
                self.config.get("data_source.startup_sync_chip_data_enabled", False)
            )
            if startup_sync_chip_data_enabled:
                chip_sync = self.sync_chip_perf_with_latest_data(reference_trade_date=target_trade_date)
                result["chip_perf_count"] = int(chip_sync.get("updated_rows", 0) or 0)
                result["chip_updated_dates"] = list(chip_sync.get("updated_dates") or [])
                result["latest_chip_trade_date_after"] = chip_sync.get("latest_chip_trade_date_after")
                chip_dist_sync = self.sync_chip_dist_with_latest_data(
                    reference_trade_date=target_trade_date,
                )
                result["chip_dist_count"] = int(chip_dist_sync.get("updated_rows", 0) or 0)
                result["chip_dist_message"] = str(chip_dist_sync.get("message") or "")
            else:
                result["latest_chip_trade_date_after"] = result["latest_chip_trade_date_before"]
                result["chip_dist_message"] = "startup chip sync disabled by config"

            result["latest_trade_date_after"] = self._normalize_trade_date(
                self.db.get_latest_trade_date("stock_daily")
            )
            result["mainboard_daily_count_after"] = self._get_mainboard_daily_count(
                result["latest_trade_date_after"] or target_trade_date
            )
            result["mainboard_chip_count_after"] = self._get_mainboard_chip_count(
                result["latest_chip_trade_date_after"] or target_trade_date
            )
            if not result["message"]:
                result["message"] = f"Startup market data check completed for {target_trade_date}, filled {len(missing_trade_dates)} trade dates"



        except Exception as exc:
            result["status"] = "failed"
            result["message"] = str(exc)
            logger.error(f"鍚姩甯傚満鏁版嵁鏍￠獙澶辫触: {exc}")

        result["end_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        return result
    
    def run_full_update(self) -> dict:
        """
        鎵ц鍏ㄩ噺鏁版嵁鏇存柊
        
        Returns:
            鏇存柊缁撴灉缁熻
        """
        logger.info("=" * 50)
        logger.info("寮€濮嬫墽琛屽叏閲忔暟鎹洿鏂?..")
        logger.info("=" * 50)
        
        result = {
            "start_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "stock_basic_count": 0,
            "daily_data_count": 0,
            "index_data_count": 0,
            "chip_perf_count": 0,
            "chip_dist_count": 0,
            "chip_dist_message": "",
            "target_trade_date": None,
            "chip_sync_enabled": False,
            "status": "success",
            "message": ""
        }
        
        try:
            # 1. 鏇存柊鑲＄エ鍩虹淇℃伅
            result["stock_basic_count"] = self.update_stock_basic()
            
            # 2. Smart target trade date: before ready time use previous trading day.
            target_trade_date = self._resolve_startup_target_trade_date()
            if not target_trade_date:
                target_trade_date = datetime.now().strftime("%Y%m%d")
            result["target_trade_date"] = target_trade_date
            result["daily_data_count"] = self.update_daily_data(
                self._compact_to_dash(target_trade_date)
            )
            
            # 3. 鏇存柊涓昏鎸囨暟鏁版嵁
            indices = self.config.get("market_analysis.indices", ["000001.SH", "399001.SZ", "399006.SZ"])
            for index_code in indices:
                count = self.update_index_data(index_code, days=30)
                result["index_data_count"] += count

            # 4. Optional chip sync in full update (off by default for low-quota accounts).
            full_update_sync_chip = bool(
                self.config.get("data_source.full_update_sync_chip_data_enabled", False)
            )
            result["chip_sync_enabled"] = full_update_sync_chip
            if full_update_sync_chip:
                chip_sync = self.sync_chip_perf_with_latest_data(reference_trade_date=target_trade_date)
                result["chip_perf_count"] = int(chip_sync.get("updated_rows", 0) or 0)
                chip_dist_sync = self.sync_chip_dist_with_latest_data(reference_trade_date=target_trade_date)
                result["chip_dist_count"] = int(chip_dist_sync.get("updated_rows", 0) or 0)
                result["chip_dist_message"] = str(chip_dist_sync.get("message") or "")
            else:
                result["chip_dist_message"] = "full update chip sync disabled by config"

            result["message"] = "鍏ㄩ噺鏁版嵁鏇存柊瀹屾垚"
            logger.info("=" * 50)
            logger.info("鍏ㄩ噺鏁版嵁鏇存柊瀹屾垚")
            logger.info("Stock basic rows: %s", result["stock_basic_count"])
            logger.info("Daily rows: %s", result["daily_data_count"])
            logger.info("Index rows: %s", result["index_data_count"])
            logger.info("Chip perf rows: %s", result["chip_perf_count"])
            logger.info("=" * 50)

            try:
                from src.modules.auto_push_manager import AutoPushManager
                apm = AutoPushManager(self.config, self.db)
                apm.invalidate_push_cache()
                logger.info("Push cache invalidated after data update")
            except Exception as cache_err:
                logger.warning(f"娓呯悊鎺ㄩ€佺紦瀛樺け璐? {cache_err}")
            
        except Exception as e:
            result["status"] = "failed"
            result["message"] = str(e)
            logger.error(f"鍏ㄩ噺鏁版嵁鏇存柊澶辫触: {e}")
        
        result["end_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        return result
    
    def verify_data(self) -> dict:
        """
        鏁版嵁鏍￠獙
        
        Returns:
            鏍￠獙缁撴灉
        """
        logger.info("寮€濮嬫暟鎹牎楠?..")
        
        result = {
            "stock_basic_count": self.db.get_table_count("stock_basic"),
            "stock_daily_count": self.db.get_table_count("stock_daily"),
            "stock_chip_perf_count": self.db.get_table_count("stock_chip_perf"),
            "stock_chip_dist_count": self.db.get_table_count("stock_chip_dist"),
            "latest_trade_date": self.db.get_latest_trade_date("stock_daily"),
            "latest_chip_trade_date": self.db.get_latest_trade_date("stock_chip_perf"),
            "latest_chip_dist_trade_date": self.db.get_latest_trade_date("stock_chip_dist"),
            "is_valid": True,
            "issues": []
        }
        
        # 妫€鏌ヨ偂绁ㄥ熀纭€淇℃伅
        if result["stock_basic_count"] == 0:
            result["is_valid"] = False
            result["issues"].append("stock_basic table is empty")
        
        # 妫€鏌ユ棩绾挎暟鎹?        if result["stock_daily_count"] == 0:
            result["is_valid"] = False
            result["issues"].append("stock_daily table is empty")
        if result["stock_chip_perf_count"] == 0:
            result["issues"].append("stock_chip_perf table is empty")
        
        # 妫€鏌ユ暟鎹椂鏁堟€?        if result["stock_chip_dist_count"] == 0:
            result["issues"].append("chip distribution table is empty")
        if result["latest_trade_date"]:
            # 澶勭悊涓ょ鏃ユ湡鏍煎紡锛歒YYYMMDD 鎴?YYYY-MM-DD
            try:
                if len(result["latest_trade_date"]) == 8:
                    latest_date = datetime.strptime(result["latest_trade_date"], "%Y%m%d")
                else:
                    latest_date = datetime.strptime(result["latest_trade_date"], "%Y-%m-%d")
                days_diff = (datetime.now() - latest_date).days
                if days_diff > 3:
                    result["issues"].append(f"daily data is stale by {days_diff} days")
            except Exception as e:
                logger.warning(f"鏃ユ湡瑙ｆ瀽澶辫触: {e}")
        
        logger.info(f"鏁版嵁鏍￠獙瀹屾垚锛岀粨鏋? {'閫氳繃' if result['is_valid'] else '鏈€氳繃'}")
        return result

    def scan_daily_gaps(self, lookback_days: int = 60) -> dict:
        """
        鎵弿鏃ョ嚎鏁版嵁缂哄彛锛氬姣斾氦鏄撴棩鍘嗕笌stock_daily瀹為檯鏃ユ湡锛?        鍙戠幇涓棿鏃ユ湡缂哄け骞跺皾璇曡嚜鍔ㄨˉ缂恒€?
        Args:
            lookback_days: 鍥炴函澶╂暟

        Returns:
            {"missing_dates": [...], "repaired_dates": [...], "unrepairable_dates": [...]}
        """
        logger.info(f"寮€濮嬫壂鎻忔棩绾挎暟鎹己鍙ｏ紝鍥炴函 {lookback_days} 澶?..")

        end_date = datetime.now().strftime("%Y%m%d")
        start_date = (datetime.now() - timedelta(days=lookback_days)).strftime("%Y%m%d")

        trade_calendar = self.db.get_trade_dates(start_date, end_date)
        if not trade_calendar:
            logger.warning("Trade calendar is empty, skip daily gap scan")
            return {"missing_dates": [], "repaired_dates": [], "unrepairable_dates": []}

        actual_dates_rows = self.db.query(
            "SELECT DISTINCT trade_date FROM stock_daily WHERE trade_date >= ? AND trade_date <= ?",
            (start_date, end_date)
        )
        actual_dates = set(r["trade_date"] for r in actual_dates_rows)

        missing_dates = sorted(set(trade_calendar) - actual_dates)
        logger.info("Trade dates=%s, with data=%s, missing=%s", len(trade_calendar), len(actual_dates), len(missing_dates))

        repaired = []
        unrepairable = []
        for date_str in missing_dates:
            try:
                df = self.primary_source.get_daily_data_batch(date_str)
                if df is not None and not df.empty:
                    self._save_daily_data(df)
                    repaired.append(date_str)
                    logger.info("Gap repair succeeded for %s, rows=%s", date_str, len(df))
                else:
                    unrepairable.append(date_str)
                    logger.warning(f"琛ョ己澶辫触锛堟棤鏁版嵁杩斿洖锛? {date_str}")
            except Exception as e:
                unrepairable.append(date_str)
                logger.warning(f"琛ョ己澶辫触: {date_str}, 閿欒: {e}")

        logger.info(f"缂哄彛鎵弿瀹屾垚: 缂哄け {len(missing_dates)}, 琛ョ己鎴愬姛 {len(repaired)}, 涓嶅彲琛?{len(unrepairable)}")
        return {
            "missing_dates": missing_dates,
            "repaired_dates": repaired,
            "unrepairable_dates": unrepairable,
        }

    def validate_data_quality(self, trade_date: str = None) -> dict:
        """
        鏁版嵁璐ㄩ噺鏍￠獙锛氭娴嬬┖鍊肩巼銆佸紓甯稿€笺€侀噸澶嶈褰?
        Args:
            trade_date: 鏍￠獙鏃ユ湡锛岄粯璁ゆ渶鏂颁氦鏄撴棩

        Returns:
            {"is_valid": bool, "issues": [...], "stats": {...}}
        """
        if trade_date is None:
            trade_date = self.db.get_latest_trade_date("stock_daily")
        if not trade_date:
            return {"is_valid": False, "issues": ["no trade date available"], "stats": {}}

        logger.info(f"寮€濮嬫暟鎹川閲忔牎楠? {trade_date}")

        df = self.db.query_to_dataframe(
            "SELECT * FROM stock_daily WHERE trade_date = ?",
            (trade_date,)
        )

        issues = []
        stats = {"total_rows": len(df), "null_rate": 0.0, "anomaly_count": 0, "duplicate_count": 0}

        if df.empty:
            return {"is_valid": False, "issues": [f"{trade_date} has no daily data"], "stats": stats}

        null_counts = df[["open", "close", "high", "low", "vol", "amount"]].isnull().sum()
        null_rate = null_counts.sum() / (len(df) * 6) if len(df) > 0 else 0
        stats["null_rate"] = round(null_rate, 4)
        if null_rate > 0.05:
            issues.append(f"绌哄€肩巼杩囬珮: {null_rate:.2%}")

        anomaly_mask = (
            (df["close"] <= 0) | (df["open"] <= 0) | (df["high"] <= 0) | (df["low"] <= 0)
            | (df["vol"] < 0) | (df["amount"] < 0)
            | (df["high"] < df["low"])
        )
        anomaly_count = int(anomaly_mask.sum())
        stats["anomaly_count"] = anomaly_count
        if anomaly_count > 0:
            anomaly_codes = df.loc[anomaly_mask, "ts_code"].head(10).tolist()
            issues.append(f"寮傚父鍊?{anomaly_count} 鏉? {anomaly_codes}")

        dup_count = int(df.duplicated(subset=["ts_code", "trade_date"]).sum())
        stats["duplicate_count"] = dup_count
        if dup_count > 0:
            issues.append(f"duplicate rows: {dup_count}")

        is_valid = len(issues) == 0
        logger.info(f"鏁版嵁璐ㄩ噺鏍￠獙瀹屾垚: {'閫氳繃' if is_valid else '鏈€氳繃'}, 闂: {issues}")
        return {"is_valid": is_valid, "issues": issues, "stats": stats}

