#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
检查 quant_system.db 的关键表结构，定位缺表/缺列问题。
"""

from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path


def table_exists(cur: sqlite3.Cursor, name: str) -> bool:
    row = cur.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (name,),
    ).fetchone()
    return row is not None


def table_columns(cur: sqlite3.Cursor, name: str) -> list[str]:
    return [row[1] for row in cur.execute(f"PRAGMA table_info({name})").fetchall()]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default="data/database/quant_system.db")
    args = parser.parse_args()

    db = Path(args.db)
    print("db_path:", db)
    print("exists:", db.exists())
    if not db.exists():
        return

    conn = sqlite3.connect(db)
    cur = conn.cursor()

    targets = [
        "stock_daily",
        "factor_values",
        "stock_basic",
        "signal_history",
        "trade_log",
        "health_snapshot",
        "runtime_incident",
    ]
    for name in targets:
        if not table_exists(cur, name):
            print(f"[MISSING] {name}")
            continue
        cols = table_columns(cur, name)
        print(f"[OK] {name} cols={cols}")

    conn.close()


if __name__ == "__main__":
    main()

