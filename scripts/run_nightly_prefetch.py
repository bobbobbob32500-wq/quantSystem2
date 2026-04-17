#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Nightly stock data refresh + precompute selections for four strategies.
"""

from __future__ import annotations

import argparse
import json
import sys
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.core.config import ConfigManager
from src.core.database import DatabaseManager
from src.core.logger import get_logger
from src.services.dashboard_task_runner import DashboardTaskRunner

logger = get_logger("nightly_prefetch")


def _run_secondary(runner: DashboardTaskRunner, trade_date: str | None) -> tuple[int, int, str | None]:
    effective_date = str(trade_date or "").strip() or runner.db.get_latest_trade_date("stock_daily")
    if not effective_date:
        effective_date = datetime.now().strftime("%Y%m%d")
    rows = list(runner.secondary_launch.get_daily_selection(effective_date) or [])
    if rows:
        runner.secondary_launch.persist_daily_selection(trade_date=effective_date, selections=rows)
    sync_count = runner.secondary_launch.sync_to_candidate_pool(trade_date=effective_date, selections=rows) if rows else 0
    return len(rows), int(sync_count), effective_date


def run(skip_update: bool = False) -> dict[str, Any]:
    config = ConfigManager()
    db = DatabaseManager(config)
    runner = DashboardTaskRunner(config=config, db=db)
    summary: dict[str, Any] = {
        "started_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "skip_update": bool(skip_update),
        "data_update_ok": False,
        "trade_date": None,
        "strategies": {},
        "errors": [],
    }

    if not skip_update:
        try:
            runner.data_updater.ensure_latest_market_data()
            summary["data_update_ok"] = True
        except Exception as exc:
            logger.exception("Nightly data update failed")
            summary["errors"].append({"stage": "data_update", "error": str(exc)})
    else:
        summary["data_update_ok"] = True

    trade_date = db.get_latest_trade_date("stock_daily")
    if not trade_date:
        trade_date = datetime.now().strftime("%Y%m%d")
    summary["trade_date"] = trade_date

    jobs = [
        ("alpha158", lambda: runner._run_alpha158_selection(trade_date)),
        ("secondary_launch", lambda: _run_secondary(runner, trade_date)),
        ("breakout", lambda: runner._run_breakout_selection(trade_date)),
        ("wide_breakout", lambda: runner._run_wide_breakout_selection(trade_date)),
    ]

    for name, fn in jobs:
        try:
            selected_count, sync_count, used_date = fn()
            summary["strategies"][name] = {
                "ok": True,
                "selected_count": int(selected_count or 0),
                "sync_count": int(sync_count or 0),
                "trade_date": str(used_date or trade_date),
            }
        except Exception as exc:
            logger.exception("Nightly strategy run failed: %s", name)
            summary["strategies"][name] = {
                "ok": False,
                "selected_count": 0,
                "sync_count": 0,
                "trade_date": str(trade_date),
                "error": str(exc),
            }
            summary["errors"].append(
                {
                    "stage": f"strategy:{name}",
                    "error": str(exc),
                    "traceback": traceback.format_exc(limit=3),
                }
            )

    summary["finished_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    summary["ok"] = not bool(summary["errors"])
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Run nightly data+strategy prefetch for mobile app.")
    parser.add_argument("--skip-update", action="store_true", help="Skip market data update phase.")
    args = parser.parse_args()

    payload = run(skip_update=bool(args.skip_update))
    out_path = PROJECT_ROOT / "data" / "cache" / "nightly_selection_summary.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False))
    return 0 if payload.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
