# -*- coding: utf-8 -*-
"""
信号收益闭环评估脚本

示例：
    .\\.venv\\Scripts\\python.exe scripts/evaluate_signal_feedback.py --start-date 20260101 --end-date 20260327 --top-n-per-day 10
"""

from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.core.config import ConfigManager
from src.core.database import DatabaseManager
from src.modules.signal_feedback_evaluator import SignalFeedbackEvaluator


def _parse_horizons(raw: str):
    values = []
    for token in str(raw).split(","):
        token = token.strip()
        if not token:
            continue
        try:
            values.append(int(token))
        except Exception:
            continue
    return values


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate signal-result feedback loop.")
    parser.add_argument("--start-date", default=None, help="YYYYMMDD or YYYY-MM-DD")
    parser.add_argument("--end-date", default=None, help="YYYYMMDD or YYYY-MM-DD")
    parser.add_argument("--top-n-per-day", type=int, default=None, help="Top N recommendations per day.")
    parser.add_argument("--rec-horizons", default=None, help="Recommendation horizons, e.g. 2,3,4,5")
    parser.add_argument("--sig-horizons", default=None, help="Signal horizons, e.g. 1,2,3")
    parser.add_argument("--strategy-type", default=None, help="Filter recommendation strategy_type.")
    parser.add_argument("--out-dir", default=None, help="Output report directory.")
    parser.add_argument("--no-persist", action="store_true", help="Disable DB persistence for this run.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    config = ConfigManager()
    db = DatabaseManager(config)
    evaluator = SignalFeedbackEvaluator(config=config, db=db)

    result = evaluator.run_feedback(
        start_date=args.start_date,
        end_date=args.end_date,
        top_n_per_day=args.top_n_per_day,
        recommendation_horizons=_parse_horizons(args.rec_horizons) if args.rec_horizons else None,
        signal_horizons=_parse_horizons(args.sig_horizons) if args.sig_horizons else None,
        strategy_type=args.strategy_type,
        out_dir=args.out_dir,
        persist=False if args.no_persist else None,
    )

    print("run_id:", result.get("run_id"))
    print("window:", result.get("start_date"), "~", result.get("end_date"))
    print("detail_count:", result.get("detail_count"))
    print("summary_count:", result.get("summary_count"))
    files = result.get("files", {}) or {}
    print("markdown:", files.get("markdown", ""))
    print("json:", files.get("json", ""))
    if files.get("csv"):
        print("csv:", files.get("csv", ""))

    stats = result.get("stats", []) or []
    if stats:
        print("\nsummary:")
        for s in stats:
            print(
                f"  [{s.get('source_type')}/{s.get('direction')}] "
                f"T+{s.get('horizon')} samples={s.get('sample_count')} "
                f"win={float(s.get('win_rate', 0)):.2%} "
                f"mean_net={float(s.get('mean_net_return', 0)):.2%}"
            )

    print("\njson_payload:")
    print(json.dumps(result, ensure_ascii=False, indent=2)[:2000])


if __name__ == "__main__":
    main()
