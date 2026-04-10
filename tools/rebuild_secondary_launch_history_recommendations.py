# -*- coding: utf-8 -*-
"""
按当前优化后的二次启动策略，重建 history_recommendation.db 中的历史推荐记录。

处理原则：
1. 仅处理 strategy_type = secondary_launch_walkforward
2. 先用当前策略全量重算历史最终信号
3. 删除历史库中已不存在于新信号集的旧脏数据
4. 对仍然有效的记录，尽量保留原有买卖、收益、状态字段
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
from src.modules.mainboard_secondary_launch_backtester import MainboardSecondaryLaunchBacktester
from src.modules.secondary_launch_menu import SecondaryLaunchMenu


STRATEGY_TYPE = "secondary_launch_walkforward"


def _backup_file(path: Path) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = path.with_name(f"{path.stem}_backup_{timestamp}{path.suffix}")
    shutil.copy2(path, backup_path)
    return backup_path


def _load_existing_rows(history_db_path: Path) -> dict[tuple[str, str], dict]:
    conn = sqlite3.connect(history_db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute(
        """
        SELECT *
        FROM recommendations
        WHERE strategy_type = ?
        """,
        (STRATEGY_TYPE,),
    )
    rows = {(str(row["recommendation_date"]), str(row["symbol"]).upper()): dict(row) for row in cur.fetchall()}
    conn.close()
    return rows


def _rebuild_rows(menu: SecondaryLaunchMenu, start_date: str, end_date: str) -> list[dict]:
    strategy, backtester = menu._build_strategy()
    hold_days = int(menu.config.get("stock_selection.secondary_launch.hold_days", 2))
    data = backtester.load_data(start_date, end_date, warmup_days=90, forward_days=max(hold_days + 2, 10))
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
        signal_date = pd.Timestamp(row["signal_date"]).strftime("%Y%m%d")
        ts_code = str(row["ts_code"]).upper()
        feature_row = feature_map.loc[(pd.Timestamp(row["signal_date"]), ts_code)]
        rebuilt_rows.append(
            {
                "symbol": ts_code,
                "name": str(row.get("name", "") or ""),
                "recommendation_date": signal_date,
                "recommendation_reason": (
                    f"二次启动策略候选 | RS20={float(row.get('rs20', 0.0)):.3f} | "
                    f"回撤={float(feature_row.get('drawdown_from_peak', 0.0)):.2%}"
                ),
                "recommendation_score": float(row.get("signal_score", 0.0) or 0.0),
                "strategy_type": STRATEGY_TYPE,
                "hold_days": hold_days,
            }
        )
    return rebuilt_rows


def _write_rows(history_db_path: Path, rebuilt_rows: list[dict], existing_map: dict[tuple[str, str], dict], dry_run: bool) -> dict:
    rebuilt_map = {
        (str(row["recommendation_date"]), str(row["symbol"]).upper()): row
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

    conn = sqlite3.connect(history_db_path)
    cur = conn.cursor()

    if stale_keys:
        cur.executemany(
            """
            DELETE FROM recommendations
            WHERE recommendation_date = ? AND symbol = ? AND strategy_type = ?
            """,
            [(date, symbol, STRATEGY_TYPE) for date, symbol in stale_keys],
        )

    now = datetime.now().isoformat()
    upsert_sql = """
        INSERT OR REPLACE INTO recommendations (
            symbol, name, recommendation_date, recommendation_reason,
            recommendation_score, strategy_type, buy_date, buy_price,
            buy_signal, buy_signal_score, sell_date, sell_price,
            sell_signal, sell_signal_score, profit_pct, hold_days,
            status, created_time, updated_time
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """

    records = []
    for key in upsert_keys:
        rebuilt = rebuilt_map[key]
        existing = existing_map.get(key, {})
        records.append(
            (
                rebuilt["symbol"],
                rebuilt["name"],
                rebuilt["recommendation_date"],
                rebuilt["recommendation_reason"],
                rebuilt["recommendation_score"],
                rebuilt["strategy_type"],
                existing.get("buy_date"),
                existing.get("buy_price"),
                existing.get("buy_signal"),
                existing.get("buy_signal_score"),
                existing.get("sell_date"),
                existing.get("sell_price"),
                existing.get("sell_signal"),
                existing.get("sell_signal_score"),
                existing.get("profit_pct"),
                rebuilt["hold_days"],
                existing.get("status", "active"),
                existing.get("created_time", now),
                now,
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
    parser = argparse.ArgumentParser(description="重建二次启动历史推荐记录")
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

    history_db_path = ROOT / config.get("feedback.history_recommendation_db", "data/history_recommendation.db")
    if not history_db_path.exists():
        raise FileNotFoundError(f"历史推荐库不存在: {history_db_path}")

    backup_path = None
    if not args.dry_run:
        backup_path = _backup_file(history_db_path)

    existing_map = _load_existing_rows(history_db_path)
    rebuilt_rows = _rebuild_rows(menu, args.start_date, end_date)
    write_result = _write_rows(history_db_path, rebuilt_rows, existing_map, dry_run=args.dry_run)

    payload = {
        "strategy_type": STRATEGY_TYPE,
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
