# -*- coding: utf-8 -*-
"""
按当前优化后的二次启动策略，重建主库 secondary_launch_selection_history。

处理原则：
1. 仅处理 strategy_name = secondary_launch_walkforward
2. 先全量重算历史最终信号
3. 删除主库中已不存在于新信号集的旧脏数据
4. 使用当前最终结果重写 rank / rs20 / 回撤 / 距涨停等字段
"""

from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.core.config import ConfigManager
from src.core.database import DatabaseManager
from src.modules.secondary_launch_menu import SecondaryLaunchMenu


STRATEGY_NAME = "secondary_launch_walkforward"


def _backup_file(path: Path) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = path.with_name(f"{path.stem}_backup_{timestamp}{path.suffix}")
    shutil.copy2(path, backup_path)
    return backup_path


def _load_existing_rows(main_db_path: Path) -> dict[tuple[str, str], dict]:
    conn = sqlite3.connect(main_db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute(
        """
        SELECT *
        FROM secondary_launch_selection_history
        WHERE strategy_name = ?
        """,
        (STRATEGY_NAME,),
    )
    rows = {(str(row["trade_date"]), str(row["ts_code"]).upper()): dict(row) for row in cur.fetchall()}
    conn.close()
    return rows


def _rebuild_rows(menu: SecondaryLaunchMenu, start_date: str, end_date: str) -> list[dict]:
    strategy, backtester = menu._build_strategy()
    data = backtester.load_data(start_date, end_date, warmup_days=90, forward_days=10)
    features = strategy.prepare_features(data["daily"], data["basic"])
    signal_frame = strategy.build_signal_frame(features)
    if signal_frame.empty:
        return []
    signals = strategy.generate_signals_from_frame(signal_frame)
    if signals.empty:
        return []

    feature_map = (
        signal_frame.sort_values(["signal_date", "ts_code"])
        .drop_duplicates(subset=["signal_date", "ts_code"], keep="last")
        .set_index(["signal_date", "ts_code"])
    )

    rebuilt_rows = []
    for _, row in signals.iterrows():
        trade_date = pd.Timestamp(row["signal_date"]).strftime("%Y%m%d")
        ts_code = str(row["ts_code"]).upper()
        feature_row = feature_map.loc[(pd.Timestamp(row["signal_date"]), ts_code)]
        gate = menu._compute_v3_daily_gate_fields(feature_row)
        rebuilt_rows.append(
            {
                "trade_date": trade_date,
                "ts_code": ts_code,
                "name": str(row.get("name", "") or ""),
                "industry": str(feature_row.get("industry", "未知") or "未知"),
                "rank": int(row.get("rank", 0) or 0),
                "rs20": float(row.get("rs20", 0.0) or 0.0),
                "drawdown_from_peak": float(feature_row.get("drawdown_from_peak", 0.0) or 0.0),
                "days_since_last_limit_up": int(feature_row.get("days_since_last_limit_up", 0) or 0),
                "strategy_name": STRATEGY_NAME,
                "strategy_label": menu.get_strategy_label(),
                "extra_json": {
                    "total_score": round(float(row.get("signal_score", 0.0) or 0.0), 4),
                    "short_cycle_score": round(float(row.get("rs20", 0.0) * 100), 4),
                    "tradeability_score": round(float((1.0 - feature_row.get("drawdown_from_peak", 0.0)) * 100), 4),
                    "strategy_version": str(
                        menu.config.get("stock_selection.secondary_launch.strategy_version", "")
                    ),
                    "v3_daily_gate": {
                        "pct_chg": gate.get("pct_chg"),
                        "vol_ratio_5": gate.get("vol_ratio_5"),
                        "upper_shadow_pct": gate.get("upper_shadow_pct"),
                    },
                },
            }
        )
    return rebuilt_rows


def _write_rows(main_db_path: Path, rebuilt_rows: list[dict], existing_map: dict[tuple[str, str], dict], dry_run: bool) -> dict:
    rebuilt_map = {
        (str(row["trade_date"]), str(row["ts_code"]).upper()): row
        for row in rebuilt_rows
    }
    stale_keys = sorted(set(existing_map.keys()) - set(rebuilt_map.keys()))
    upsert_keys = sorted(rebuilt_map.keys())

    if dry_run:
        return {
            "deleted_count": len(stale_keys),
            "upserted_count": len(upsert_keys),
            "stale_keys": stale_keys[:20],
        }

    conn = sqlite3.connect(main_db_path)
    cur = conn.cursor()

    if stale_keys:
        cur.executemany(
            """
            DELETE FROM secondary_launch_selection_history
            WHERE trade_date = ? AND ts_code = ? AND strategy_name = ?
            """,
            [(date, code, STRATEGY_NAME) for date, code in stale_keys],
        )

    created_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    upsert_sql = """
        INSERT OR REPLACE INTO secondary_launch_selection_history (
            trade_date, ts_code, name, industry, rank, rs20, drawdown_from_peak,
            days_since_last_limit_up, strategy_name, strategy_label, extra_json, created_time
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """
    records = []
    for key in upsert_keys:
        rebuilt = rebuilt_map[key]
        existing = existing_map.get(key, {})
        records.append(
            (
                rebuilt["trade_date"],
                rebuilt["ts_code"],
                rebuilt["name"],
                rebuilt["industry"],
                rebuilt["rank"],
                rebuilt["rs20"],
                rebuilt["drawdown_from_peak"],
                rebuilt["days_since_last_limit_up"],
                rebuilt["strategy_name"],
                rebuilt["strategy_label"],
                json.dumps(rebuilt["extra_json"], ensure_ascii=False),
                existing.get("created_time", created_time),
            )
        )

    cur.executemany(upsert_sql, records)
    conn.commit()
    conn.close()
    return {
        "deleted_count": len(stale_keys),
        "upserted_count": len(upsert_keys),
        "stale_keys": stale_keys[:20],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="重建主库二次启动历史记录")
    parser.add_argument("--start-date", default="20250901", help="开始日期 YYYYMMDD")
    parser.add_argument("--end-date", default="", help="结束日期 YYYYMMDD，默认使用 stock_daily 最新交易日")
    parser.add_argument("--dry-run", action="store_true", help="只预览，不写库")
    args = parser.parse_args()

    config = ConfigManager()
    db = DatabaseManager(config)
    menu = SecondaryLaunchMenu(config, db)
    end_date = args.end_date or db.get_latest_trade_date("stock_daily")
    if not end_date:
        raise RuntimeError("未找到最新交易日")

    main_db_path = ROOT / config.get("database.path", "data/database/quant_system.db")
    if not main_db_path.exists():
        raise FileNotFoundError(f"主库不存在: {main_db_path}")

    backup_path = None
    if not args.dry_run:
        backup_path = _backup_file(main_db_path)

    existing_map = _load_existing_rows(main_db_path)
    rebuilt_rows = _rebuild_rows(menu, args.start_date, end_date)
    write_result = _write_rows(main_db_path, rebuilt_rows, existing_map, dry_run=args.dry_run)

    payload = {
        "strategy_name": STRATEGY_NAME,
        "start_date": args.start_date,
        "end_date": end_date,
        "existing_count": len(existing_map),
        "rebuilt_count": len(rebuilt_rows),
        "deleted_count": int(write_result["deleted_count"]),
        "upserted_count": int(write_result["upserted_count"]),
        "backup_path": str(backup_path) if backup_path else None,
        "dry_run": bool(args.dry_run),
        "stale_examples": write_result.get("stale_keys", []),
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
