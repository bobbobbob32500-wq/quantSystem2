from __future__ import annotations

import json
import sqlite3
from pathlib import Path
import sys

import pandas as pd

ROOT = Path(r"D:\HuaweiAI\quantSystem2")
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
MVP_CSV = ROOT / "data/research/strong_start_full/v4_scan/true_breakout_strategy_mvp.csv"
HIST_DB = ROOT / "data/history_recommendation.db"
OUT_JSON = ROOT / "data/research/strong_start_full/v4_scan/true_breakout_mvp_tday_5m_download_summary.json"


def ymd_to_dash(s: str) -> str:
    s = str(s)
    return f"{s[:4]}-{s[4:6]}-{s[6:8]}"


def load_existing_pairs(conn: sqlite3.Connection) -> set[tuple[str, str]]:
    q = "select distinct symbol, trade_date from intraday_data"
    d = pd.read_sql_query(q, conn)
    if d.empty:
        return set()
    return set(zip(d["symbol"].astype(str), d["trade_date"].astype(str)))


def main() -> None:
    from src.modules.backtest.history_recommendation_db import HistoryRecommendationDB
    from src.modules.backtest.batch_intraday_downloader import BatchIntradayDownloader

    mvp = pd.read_csv(MVP_CSV, usecols=["stock_code", "trade_date"])
    mvp["stock_code"] = mvp["stock_code"].astype(str)
    mvp["trade_date_dash"] = mvp["trade_date"].astype(str).map(ymd_to_dash)
    mvp = mvp.drop_duplicates(subset=["stock_code", "trade_date_dash"]).reset_index(drop=True)

    conn = sqlite3.connect(HIST_DB)
    try:
        existing_pairs = load_existing_pairs(conn)
    finally:
        conn.close()

    target_pairs = list(zip(mvp["stock_code"], mvp["trade_date_dash"]))
    todo_pairs = [p for p in target_pairs if p not in existing_pairs]

    db = HistoryRecommendationDB(str(HIST_DB))
    downloader = BatchIntradayDownloader(db=db)
    if downloader.bs is None:
        raise RuntimeError("baostock init failed, cannot download intraday data")

    ok_pairs = 0
    fail_pairs = 0
    inserted_rows = 0
    fail_samples: list[dict] = []

    for i, (symbol, day) in enumerate(todo_pairs, start=1):
        frame = downloader.download_intraday_data(symbol, day, day)
        if frame.empty:
            fail_pairs += 1
            if len(fail_samples) < 20:
                fail_samples.append({"symbol": symbol, "trade_date": day, "reason": "empty"})
            continue
        frame = frame[frame["trade_date"] == day].copy()
        if frame.empty:
            fail_pairs += 1
            if len(fail_samples) < 20:
                fail_samples.append({"symbol": symbol, "trade_date": day, "reason": "no_exact_day_rows"})
            continue
        ok = db.add_intraday_data(symbol, frame)
        if ok:
            ok_pairs += 1
            inserted_rows += int(len(frame))
        else:
            fail_pairs += 1
            if len(fail_samples) < 20:
                fail_samples.append({"symbol": symbol, "trade_date": day, "reason": "db_insert_failed"})

    # recompute coverage
    conn = sqlite3.connect(HIST_DB)
    try:
        existing_after = load_existing_pairs(conn)
    finally:
        conn.close()
    covered_after = sum(1 for p in target_pairs if p in existing_after)

    summary = {
        "target_pairs": len(target_pairs),
        "already_covered_before": len(target_pairs) - len(todo_pairs),
        "download_todo_pairs": len(todo_pairs),
        "download_ok_pairs": ok_pairs,
        "download_fail_pairs": fail_pairs,
        "inserted_rows": inserted_rows,
        "covered_after_pairs": covered_after,
        "coverage_after_ratio": (covered_after / len(target_pairs)) if target_pairs else None,
        "fail_samples": fail_samples,
        "output_json": str(OUT_JSON),
    }
    OUT_JSON.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))

    try:
        downloader.close()
    except Exception:
        pass


if __name__ == "__main__":
    main()
