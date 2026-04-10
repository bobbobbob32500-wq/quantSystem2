#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
验证二次启动策略的历史候选是否能成功写入两个数据库。
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.core.config import ConfigManager
from src.core.database import DatabaseManager
from src.modules.secondary_launch_menu import SecondaryLaunchMenu


def main() -> int:
    trade_date = "20260316"

    config = ConfigManager()
    db = DatabaseManager(config)
    menu = SecondaryLaunchMenu(config, db)

    rows = menu.get_daily_selection(trade_date)
    persisted = menu.persist_daily_selection(trade_date, rows)

    main_conn = sqlite3.connect("data/database/quant_system.db")
    main_cur = main_conn.cursor()
    main_cur.execute(
        """
        SELECT trade_date, ts_code, strategy_name, rank
        FROM secondary_launch_selection_history
        WHERE trade_date = ?
        ORDER BY rank
        """,
        (trade_date,),
    )
    main_rows = main_cur.fetchall()
    main_conn.close()

    history_conn = sqlite3.connect("data/history_recommendation.db")
    history_cur = history_conn.cursor()
    history_cur.execute(
        """
        SELECT recommendation_date, symbol, strategy_type, recommendation_reason
        FROM recommendations
        WHERE recommendation_date = ?
          AND strategy_type = ?
        ORDER BY symbol
        """,
        (trade_date, "secondary_launch_walkforward"),
    )
    history_rows = history_cur.fetchall()
    history_conn.close()

    print(f"trade_date={trade_date}")
    print(f"selection_count={len(rows)}")
    print(f"persisted_count={persisted}")
    print(f"main_db_rows={main_rows}")
    print(f"history_db_rows={history_rows}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
