# -*- coding: utf-8 -*-
"""
更新本机 Qlib cn_data：先拉取 SunsetWolf/qlib_dataset 最新日线全量包，再自项目 SQLite
将 CSI300 成分在「日历缺口」内的 OHLCV 增量写入 bin（与 microsoft/qlib dump_bin 一致）。

范围说明：
- 官方包：覆盖全市场（体积较大）；增量仅导出 **沪深300 成分**（与 Alpha158+csi300 口径一致，且控制耗时）。
- 目标：使日历尽量延伸至参数 --end-date（默认 20260401），受限于 stock_daily 实际有数据的日期。

用法（需在 qlib_env 下）：
  python scripts/qlib_update_cn_data.py
  python scripts/qlib_update_cn_data.py --skip-download   # 已有新包时跳过下载，仅做 SQLite 增量
  python scripts/qlib_update_cn_data.py --end-date 20260401

依赖：requests、tqdm、loguru、numpy、pandas（qlib_env 已具备）
"""

from __future__ import annotations

import argparse
import importlib.util
import os
import shutil
import sqlite3
import sys
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Set

import numpy as np
import pandas as pd
import requests
from loguru import logger

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# 官方数据集（与 pyqlib GetData 一致）
QLIB_CN_ZIP_URL = (
    "https://github.com/SunsetWolf/qlib_dataset/releases/download/v3/qlib_data_cn_1d_latest.zip"
)


def _load_dump_update():
    vendor = ROOT / "scripts" / "qlib_dump_bin_vendor.py"
    spec = importlib.util.spec_from_file_location("qlib_dump_bin_vendor", vendor)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod.DumpDataUpdate


def _ts_code_to_qlib(ts_code: str) -> str:
    """600000.SH -> SH600000"""
    code, mkt = ts_code.upper().split(".")
    if mkt == "SH":
        return "SH" + code.zfill(6)
    if mkt == "SZ":
        return "SZ" + code.zfill(6)
    raise ValueError(f"无法解析 ts_code: {ts_code}")


def _download_file(url: str, dest: Path, chunk: int = 4 * 1024 * 1024) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    logger.info("开始下载: {}", url)
    with requests.get(url, stream=True, timeout=120) as r:
        r.raise_for_status()
        total = int(r.headers.get("Content-Length", 0))
        got = 0
        with open(dest, "wb") as f:
            for part in r.iter_content(chunk):
                if part:
                    f.write(part)
                    got += len(part)
                    if total and got % (16 * chunk) < chunk:
                        logger.info("已下载 {:.1f} MB / {:.1f} MB", got / 1e6, total / 1e6)
    logger.info("下载完成: {} ({:.1f} MB)", dest, dest.stat().st_size / 1e6)


def _backup_and_extract(zip_path: Path, cn_data: Path) -> None:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = cn_data.parent / f"cn_data_backup_{ts}"
    if cn_data.exists():
        logger.info("备份 cn_data -> {}", backup)
        shutil.copytree(cn_data, backup)
    # 清空后解压全量包（官方 zip 为完整目录结构）
    for name in ("features", "calendars", "instruments", "features_cache", "dataset_cache"):
        p = cn_data / name
        if p.exists():
            shutil.rmtree(p)
    cn_data.mkdir(parents=True, exist_ok=True)
    logger.info("解压 {} -> {}", zip_path, cn_data)
    with zipfile.ZipFile(zip_path, "r") as zf:
        zf.extractall(cn_data)
    logger.info("解压完成")


def _calendar_last(qlib_dir: Path, freq: str = "day") -> Optional[pd.Timestamp]:
    cal_file = qlib_dir / "calendars" / f"{freq}.txt"
    if not cal_file.exists():
        return None
    lines = [x.strip() for x in cal_file.read_text(encoding="utf-8").splitlines() if x.strip()]
    if not lines:
        return None
    return pd.Timestamp(lines[-1])


def _sym_line_to_ts(sym: str) -> str:
    """SH600000 -> 600000.SH"""
    s = sym.strip().upper()
    if s.startswith("SH"):
        return s[2:] + ".SH"
    if s.startswith("SZ"):
        return s[2:] + ".SZ"
    raise ValueError(sym)


def _load_csi300_ts_codes(cn_data: Path) -> List[str]:
    """从 instruments/csi300.txt 读取全部曾纳入成分（去重为 ts_code）。"""
    p = cn_data / "instruments" / "csi300.txt"
    if not p.exists():
        raise FileNotFoundError(f"缺少 {p}，请先完成官方包解压")
    seen: Set[str] = set()
    out: List[str] = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        sym = line.split("\t")[0].strip()
        ts = _sym_line_to_ts(sym)
        if ts not in seen:
            seen.add(ts)
            out.append(ts)
    return out


def _export_sqlite_incremental_csv(
    db_path: Path,
    ts_codes: List[str],
    start_d: str,
    end_d: str,
    out_dir: Path,
) -> int:
    """导出 YYYYMMDD 区间内的增量 CSV（每只一个文件），返回写出文件数。"""
    out_dir.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    ts_list = list(dict.fromkeys(ts_codes))
    if not ts_list:
        conn.close()
        return 0

    ph = ",".join(["?"] * len(ts_list))
    sql = f"""
        SELECT ts_code, trade_date, open, high, low, close, vol, amount, pct_chg
        FROM stock_daily
        WHERE ts_code IN ({ph})
          AND trade_date >= ? AND trade_date <= ?
        ORDER BY ts_code, trade_date
    """
    params: List = ts_list + [start_d, end_d]
    df = pd.read_sql(sql, conn, params=params)
    conn.close()
    if df.empty:
        logger.warning("SQLite 在 {}～{} 无选中股票数据", start_d, end_d)
        return 0

    df["trade_date"] = df["trade_date"].astype(str)
    df["date"] = pd.to_datetime(df["trade_date"], format="%Y%m%d")
    n_files = 0
    for ts_code, g in df.groupby("ts_code"):
        try:
            qlib_code = _ts_code_to_qlib(str(ts_code))
        except Exception:
            continue
        g2 = g.sort_values("date").copy()
        g2["open"] = pd.to_numeric(g2["open"], errors="coerce")
        g2["high"] = pd.to_numeric(g2["high"], errors="coerce")
        g2["low"] = pd.to_numeric(g2["low"], errors="coerce")
        g2["close"] = pd.to_numeric(g2["close"], errors="coerce")
        g2["volume"] = pd.to_numeric(g2["vol"], errors="coerce")
        g2["factor"] = 1.0
        g2["change"] = pd.to_numeric(g2["pct_chg"], errors="coerce")
        out = g2[["date", "open", "high", "low", "close", "volume", "factor", "change"]]
        fname = f"{qlib_code.lower()}.csv"
        out.to_csv(out_dir / fname, index=False)
        n_files += 1
    logger.info("已写出 {} 个 CSV（CSI300 有数据的股票）", n_files)
    return n_files


def main() -> None:
    parser = argparse.ArgumentParser(description="更新 Qlib cn_data（下载 + SQLite 增量）")
    parser.add_argument(
        "--cn-data",
        type=str,
        default=str(Path.home() / ".qlib/qlib_data/cn_data"),
        help="cn_data 目录",
    )
    parser.add_argument(
        "--db",
        type=str,
        default=str(ROOT / "data" / "database" / "quant_system.db"),
        help="项目 SQLite 路径",
    )
    parser.add_argument("--end-date", type=str, default="20260401", help="目标最后自然日 YYYYMMDD")
    parser.add_argument("--skip-download", action="store_true", help="跳过官方 zip 下载与解压")
    parser.add_argument("--keep-zip", action="store_true", help="保留下载的 zip 文件")
    parser.add_argument(
        "--force-sqlite-without-v3",
        action="store_true",
        help="跳过下载时仍强制做 SQLite 增量（仅当你确认 cn_data 日历已连续覆盖至近端；否则可能损坏 bin）",
    )
    args = parser.parse_args()

    cn_data = Path(args.cn_data).expanduser()
    db_path = Path(args.db)
    end_ymd = args.end_date.strip()

    if not db_path.is_file():
        logger.error("找不到数据库: {}", db_path)
        sys.exit(1)

    zip_path = cn_data.parent / "qlib_data_cn_1d_v3.zip"

    if not args.skip_download:
        _download_file(QLIB_CN_ZIP_URL, zip_path)
        _backup_and_extract(zip_path, cn_data)
        if not args.keep_zip:
            zip_path.unlink(missing_ok=True)
    else:
        logger.info("已跳过下载；使用现有 {}", cn_data)

    last_cal = _calendar_last(cn_data)
    logger.info("当前 Qlib 日历最后交易日: {}", last_cal)

    if args.skip_download and not args.force_sqlite_without_v3:
        if last_cal is None or last_cal < pd.Timestamp("2024-06-01"):
            logger.error(
                "跳过下载时，本机 cn_data 日历最后日（{}）过早；请先执行一次**不带** --skip-download 以拉取 v3 全量包，"
                "或确认已手动替换为含近端日历的数据后再试。若仍要强跑，请加 --force-sqlite-without-v3（风险自负）。",
                last_cal,
            )
            sys.exit(1)

    target_end = pd.Timestamp(f"{end_ymd[:4]}-{end_ymd[4:6]}-{end_ymd[6:8]}")
    if last_cal is not None and last_cal >= target_end:
        logger.info("日历已覆盖目标日 {}，无需 SQLite 增量。", target_end.date())
        return

    # 增量从下一天开始（SQLite 为自然日；与 A 股对齐由数据本身决定）
    inc_start = (last_cal + pd.Timedelta(days=1)).strftime("%Y%m%d") if last_cal is not None else "20250101"
    inc_end = end_ymd

    if inc_start > inc_end:
        logger.info("无需增量（inc_start {} > inc_end {}）", inc_start, inc_end)
        return

    logger.info("从 SQLite 增量: {} ～ {}（CSI300 成分，来自 instruments/csi300.txt）", inc_start, inc_end)

    ts_codes = _load_csi300_ts_codes(cn_data)
    with tempfile.TemporaryDirectory(prefix="qlib_inc_csv_") as tmp:
        tmp_path = Path(tmp)
        n = _export_sqlite_incremental_csv(db_path, ts_codes, inc_start, inc_end, tmp_path)
        if n == 0:
            logger.error("未导出任何 CSV，请检查 stock_daily 是否含 CSI300 在以上区间的数据。")
            sys.exit(2)

        DumpDataUpdate = _load_dump_update()
        dumper = DumpDataUpdate(
            data_path=str(tmp_path),
            qlib_dir=str(cn_data),
            freq="day",
            max_workers=8,
            date_field_name="date",
            file_suffix=".csv",
            include_fields="open,high,low,close,volume,factor,change",
        )
        dumper.dump()

    import qlib
    from qlib.data import D

    qlib.init(provider_uri=str(cn_data))
    cal = D.calendar()
    logger.info("更新后日历: {} ～ {}", cal[0], cal[-1])


if __name__ == "__main__":
    main()
