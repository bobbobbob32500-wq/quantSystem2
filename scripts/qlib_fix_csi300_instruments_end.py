# -*- coding: utf-8 -*-
"""
将 ~/.qlib/qlib_data/cn_data/instruments/csi300.txt 第三列（结束日）统一为指定日期。

官方包中成分「结束日」常停在 2020-09-25，会导致 2021 年及以后 segment 在 market=csi300 下无标的、
DatasetH 的 valid/test 行数为 0。研究用可将结束日延至与 calendars/day.txt 末交易日一致。

用法：
  python scripts/qlib_fix_csi300_instruments_end.py
  python scripts/qlib_fix_csi300_instruments_end.py --end-date 2022-12-30
"""
from __future__ import annotations

import argparse
import shutil
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--cn-data",
        type=str,
        default=str(Path.home() / ".qlib/qlib_data/cn_data"),
    )
    parser.add_argument("--end-date", type=str, default="2022-12-30")
    args = parser.parse_args()

    p = Path(args.cn_data) / "instruments" / "csi300.txt"
    if not p.exists():
        raise SystemExit(f"找不到 {p}")
    backup = p.with_suffix(".txt.bak_before_endfix")
    shutil.copy2(p, backup)
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split("\t")
        if len(parts) >= 3:
            parts[2] = args.end_date
        out.append("\t".join(parts) + "\n")
    p.write_text("".join(out), encoding="utf-8")
    print(f"已备份: {backup}")
    print(f"已将结束日统一为 {args.end_date}，共 {len(out)} 行")


if __name__ == "__main__":
    main()
