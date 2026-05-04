from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

from src.services.startup_self_check_service import StartupSelfCheckService


class FakeConfig:
    def __init__(self, config_file: str, values: dict[str, object]):
        self.config_file = config_file
        self.values = values

    def get(self, key: str, default=None):
        return self.values.get(key, default)


def _prepare_db(db_path: Path, trade_date: str) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute("CREATE TABLE IF NOT EXISTS stock_daily (trade_date TEXT)")
        conn.execute("DELETE FROM stock_daily")
        conn.execute("INSERT INTO stock_daily(trade_date) VALUES (?)", (trade_date,))
        conn.commit()
    finally:
        conn.close()


def test_startup_self_check_pass_when_core_dependencies_ready(tmp_path: Path) -> None:
    config_file = tmp_path / "config.yaml"
    config_file.write_text("system: {}\n", encoding="utf-8")

    db_path = tmp_path / "data" / "database" / "quant_system.db"
    _prepare_db(db_path, datetime.now().strftime("%Y%m%d"))

    cache_dir = tmp_path / "data" / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    (cache_dir / "virtual_trades.json").write_text("{}", encoding="utf-8")
    (cache_dir / "execution_journal.json").write_text("{}", encoding="utf-8")

    config = FakeConfig(
        config_file=str(config_file),
        values={
            "database.path": str(db_path),
            "stock_selection.strategy_profile": "legacy",
            "data_source.startup_auto_update_enabled": True,
        },
    )

    service = StartupSelfCheckService(project_root=tmp_path, config=config, stale_days_threshold=5)
    result = service.run_check()

    assert result["overall_status"] == "pass"
    assert result["stats"]["fail_count"] == 0
    assert result["stats"]["warn_count"] == 0


def test_startup_self_check_warn_for_stale_data_and_disabled_startup_sync(tmp_path: Path) -> None:
    config_file = tmp_path / "config.yaml"
    config_file.write_text("system: {}\n", encoding="utf-8")

    db_path = tmp_path / "data" / "database" / "quant_system.db"
    _prepare_db(db_path, "20000101")

    config = FakeConfig(
        config_file=str(config_file),
        values={
            "database.path": str(db_path),
            "stock_selection.strategy_profile": "legacy",
            "data_source.startup_auto_update_enabled": False,
        },
    )

    service = StartupSelfCheckService(project_root=tmp_path, config=config, stale_days_threshold=3)
    result = service.run_check()

    assert result["overall_status"] == "warn"
    keys_to_status = {item["key"]: item["status"] for item in result["items"]}
    assert keys_to_status["market_data_freshness"] == "warn"
    assert keys_to_status["startup_auto_update"] == "warn"


def test_startup_self_check_fail_when_database_missing(tmp_path: Path) -> None:
    config_file = tmp_path / "config.yaml"
    config_file.write_text("system: {}\n", encoding="utf-8")

    missing_db = tmp_path / "data" / "database" / "missing.db"
    config = FakeConfig(
        config_file=str(config_file),
        values={
            "database.path": str(missing_db),
            "stock_selection.strategy_profile": "legacy",
            "data_source.startup_auto_update_enabled": True,
        },
    )

    service = StartupSelfCheckService(project_root=tmp_path, config=config, stale_days_threshold=3)
    result = service.run_check()

    assert result["overall_status"] == "fail"
    keys_to_status = {item["key"]: item["status"] for item in result["items"]}
    assert keys_to_status["database_file"] == "fail"
