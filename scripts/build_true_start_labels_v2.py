#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""构建「真实启动标签 v2」候选池并打标，输出 parquet/csv 与质检摘要。"""

from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.core.config import ConfigManager
from src.core.database import DatabaseManager
from src.modules.true_start_label_v2 import (
    TrueStartLabelV2Config,
    build_true_start_labels_v2,
    save_outputs,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="真实启动标签 v2（平台突破候选池）")
    parser.add_argument("--start-date", required=True, help="YYYYMMDD")
    parser.add_argument("--end-date", required=True, help="YYYYMMDD")
    parser.add_argument(
        "--output-dir",
        default="data/research/strong_start/true_start_v2",
        help="输出目录",
    )
    parser.add_argument("--db-path", default=None, help="可选：SQLite 路径覆盖")
    args = parser.parse_args()

    cfg_mgr = ConfigManager()
    db = DatabaseManager(cfg_mgr, db_path=args.db_path) if args.db_path else DatabaseManager(cfg_mgr)

    df, summary, tables = build_true_start_labels_v2(
        db,
        start_date=args.start_date.replace("-", ""),
        end_date=args.end_date.replace("-", ""),
        cfg=TrueStartLabelV2Config(),
    )

    if df.empty:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        print("未产出候选或面板为空，请检查数据区间与库内日线。")
        return

    paths = save_outputs(df, summary, args.output_dir, tables=tables)
    print("=" * 60)
    print("真实启动标签 v2 完成")
    print("=" * 60)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    for k, v in paths.items():
        print(f"{k}: {v}")


if __name__ == "__main__":
    main()
