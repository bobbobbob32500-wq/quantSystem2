# -*- coding: utf-8 -*-
"""Startup self-check service for backend and mobile-app observability."""
from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.core.config import ConfigManager
from src.core.logger import get_logger

logger = get_logger("startup_self_check_service")


class StartupSelfCheckService:
    """Run lightweight startup checks and expose a structured health summary."""

    def __init__(
        self,
        project_root: Optional[str | Path] = None,
        config: Optional[ConfigManager] = None,
        stale_days_threshold: int = 5,
    ):
        self.project_root = Path(project_root or Path(__file__).resolve().parents[2])
        self.config = config or ConfigManager()
        self.stale_days_threshold = max(1, int(stale_days_threshold or 5))

    def run_check(self) -> Dict[str, Any]:
        checked_at = datetime.now().isoformat()
        items: List[Dict[str, Any]] = []

        self._check_config_file(items)
        self._check_strategy_profile(items)
        self._check_required_directories(items)
        self._check_database_file(items)
        self._check_market_data_freshness(items)
        self._check_bootstrap_toggle(items)
        self._check_cache_files(items)

        fail_count = sum(1 for item in items if item["status"] == "fail")
        warn_count = sum(1 for item in items if item["status"] == "warn")
        pass_count = sum(1 for item in items if item["status"] == "pass")

        if fail_count > 0:
            overall_status = "fail"
            summary = f"Startup self-check failed: {fail_count} blocking item(s), {warn_count} warning(s)."
        elif warn_count > 0:
            overall_status = "warn"
            summary = f"Startup self-check completed with warnings: {warn_count} warning(s)."
        else:
            overall_status = "pass"
            summary = "Startup self-check passed."

        return {
            "checked_at": checked_at,
            "overall_status": overall_status,
            "overall_status_label": self._status_label(overall_status),
            "summary": summary,
            "stats": {
                "pass_count": pass_count,
                "warn_count": warn_count,
                "fail_count": fail_count,
            },
            "items": items,
        }

    def _check_config_file(self, items: List[Dict[str, Any]]) -> None:
        config_file = Path(str(getattr(self.config, "config_file", "") or ""))
        if config_file.exists():
            self._append_item(
                items,
                key="config_file",
                status="pass",
                message=f"Config file found: {config_file}",
                meta={"path": str(config_file)},
            )
            return
        self._append_item(
            items,
            key="config_file",
            status="fail",
            message=f"Config file missing: {config_file}",
            meta={"path": str(config_file)},
        )

    def _check_strategy_profile(self, items: List[Dict[str, Any]]) -> None:
        profile = str(self.config.get("stock_selection.strategy_profile", "legacy") or "legacy").strip()
        frozen_profiles = {
            "legacy",
            "legacy_opt",
            "enhanced",
            "secondary_launch",
            "breakout",
            "wide_breakout",
            "wide_breakout_strategy",
            "strong_start",
            "both",
        }
        if profile in frozen_profiles:
            self._append_item(
                items,
                key="strategy_profile",
                status="pass",
                message=f"Strategy profile is frozen-compatible: {profile}",
                meta={"profile": profile},
            )
            return
        self._append_item(
            items,
            key="strategy_profile",
            status="warn",
            message=f"Unknown strategy profile '{profile}', verify freeze policy compatibility.",
            meta={"profile": profile},
        )

    def _check_required_directories(self, items: List[Dict[str, Any]]) -> None:
        relative_dirs = ["data/cache", "data/database", "reports"]
        for relative in relative_dirs:
            directory = self.project_root / relative
            try:
                directory.mkdir(parents=True, exist_ok=True)
                self._append_item(
                    items,
                    key=f"dir:{relative}",
                    status="pass",
                    message=f"Directory ready: {relative}",
                    meta={"path": str(directory)},
                )
            except Exception as exc:
                logger.exception("Failed to prepare directory: %s", directory)
                self._append_item(
                    items,
                    key=f"dir:{relative}",
                    status="fail",
                    message=f"Directory unavailable: {relative} ({exc})",
                    meta={"path": str(directory)},
                )

    def _check_database_file(self, items: List[Dict[str, Any]]) -> None:
        db_path = self._resolve_path(self.config.get("database.path", "data/database/quant_system.db"))
        if db_path.exists():
            self._append_item(
                items,
                key="database_file",
                status="pass",
                message=f"Database file found: {db_path.name}",
                meta={"path": str(db_path)},
            )
            return
        self._append_item(
            items,
            key="database_file",
            status="fail",
            message=f"Database file missing: {db_path}",
            meta={"path": str(db_path)},
        )

    def _check_market_data_freshness(self, items: List[Dict[str, Any]]) -> None:
        db_path = self._resolve_path(self.config.get("database.path", "data/database/quant_system.db"))
        if not db_path.exists():
            self._append_item(
                items,
                key="market_data_freshness",
                status="fail",
                message="Cannot evaluate market-data freshness because database file is missing.",
                meta={"path": str(db_path)},
            )
            return

        latest_trade_date = self._fetch_latest_trade_date(db_path)
        if not latest_trade_date:
            self._append_item(
                items,
                key="market_data_freshness",
                status="warn",
                message="stock_daily has no trade_date records yet.",
                meta={"path": str(db_path)},
            )
            return

        age_days = self._trade_date_age_days(latest_trade_date)
        if age_days is None:
            self._append_item(
                items,
                key="market_data_freshness",
                status="warn",
                message=f"Latest trade_date format is invalid: {latest_trade_date}",
                meta={"latest_trade_date": latest_trade_date},
            )
            return

        if age_days > self.stale_days_threshold:
            self._append_item(
                items,
                key="market_data_freshness",
                status="warn",
                message=(
                    f"Latest trade_date is stale by {age_days} day(s): {latest_trade_date}. "
                    f"Threshold={self.stale_days_threshold}."
                ),
                meta={
                    "latest_trade_date": latest_trade_date,
                    "age_days": age_days,
                    "threshold_days": self.stale_days_threshold,
                },
            )
            return

        self._append_item(
            items,
            key="market_data_freshness",
            status="pass",
            message=f"Latest trade_date is fresh: {latest_trade_date} (age={age_days} day(s)).",
            meta={
                "latest_trade_date": latest_trade_date,
                "age_days": age_days,
                "threshold_days": self.stale_days_threshold,
            },
        )

    def _check_bootstrap_toggle(self, items: List[Dict[str, Any]]) -> None:
        enabled = bool(self.config.get("data_source.startup_auto_update_enabled", True))
        if enabled:
            self._append_item(
                items,
                key="startup_auto_update",
                status="pass",
                message="Startup market-data auto-sync is enabled.",
                meta={"enabled": True},
            )
            return
        self._append_item(
            items,
            key="startup_auto_update",
            status="warn",
            message="Startup market-data auto-sync is disabled.",
            meta={"enabled": False},
        )

    def _check_cache_files(self, items: List[Dict[str, Any]]) -> None:
        targets = {
            "virtual_trades_cache": self.project_root / "data" / "cache" / "virtual_trades.json",
            "execution_journal_cache": self.project_root / "data" / "cache" / "execution_journal.json",
        }
        for key, target in targets.items():
            if target.exists():
                self._append_item(
                    items,
                    key=key,
                    status="pass",
                    message=f"Cache file exists: {target.name}",
                    meta={"path": str(target)},
                )
            else:
                self._append_item(
                    items,
                    key=key,
                    status="warn",
                    message=f"Cache file not generated yet: {target.name}",
                    meta={"path": str(target)},
                )

    def _fetch_latest_trade_date(self, db_path: Path) -> Optional[str]:
        conn: Optional[sqlite3.Connection] = None
        try:
            conn = sqlite3.connect(str(db_path))
            row = conn.execute("SELECT MAX(trade_date) FROM stock_daily").fetchone()
            if not row:
                return None
            value = row[0]
            text = str(value or "").strip()
            return text or None
        except sqlite3.Error:
            logger.exception("Failed to query latest trade_date from %s", db_path)
            return None
        finally:
            if conn is not None:
                conn.close()

    @staticmethod
    def _trade_date_age_days(trade_date: str) -> Optional[int]:
        text = str(trade_date or "").strip()
        if len(text) >= 10 and "-" in text:
            text = text[:10].replace("-", "")
        if len(text) != 8 or not text.isdigit():
            return None
        try:
            parsed = datetime.strptime(text, "%Y%m%d")
        except ValueError:
            return None
        return max((datetime.now().date() - parsed.date()).days, 0)

    def _resolve_path(self, raw_path: str | Path) -> Path:
        path = Path(raw_path)
        if path.is_absolute():
            return path
        return self.project_root / path

    def _append_item(
        self,
        items: List[Dict[str, Any]],
        key: str,
        status: str,
        message: str,
        meta: Optional[Dict[str, Any]] = None,
    ) -> None:
        normalized_status = status if status in {"pass", "warn", "fail"} else "warn"
        items.append(
            {
                "key": key,
                "status": normalized_status,
                "status_label": self._status_label(normalized_status),
                "message": message,
                "meta": meta if isinstance(meta, dict) else {},
            }
        )

    @staticmethod
    def _status_label(status: str) -> str:
        return {
            "pass": "PASS",
            "warn": "WARN",
            "fail": "FAIL",
        }.get(status, "WARN")
