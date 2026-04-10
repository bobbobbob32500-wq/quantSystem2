#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
二次启动 V3 最终版：全历史日线选股回测 + 导出信号名单与指标。

说明：
- 日线选股逻辑与 MainboardSecondaryLaunchStrategy 一致（config 中 secondary_launch）
- 盘中 V3 日线闸门在分钟回放中验证，见 tools/analyze_secondary_launch_unified_truth.py
"""

from __future__ import annotations

import argparse
import json
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


def _query_trade_date_bounds(main_db: Path) -> tuple[str, str]:
    conn = sqlite3.connect(str(main_db))
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT MIN(trade_date) AS a, MAX(trade_date) AS b FROM stock_daily").fetchone()
    conn.close()
    if not row or row["a"] is None:
        return "20200101", "20200101"
    return str(row["a"]), str(row["b"])


def main() -> int:
    parser = argparse.ArgumentParser(description="V3 二次启动全历史回测与导出")
    parser.add_argument("--start-date", default="", help="回测窗口起点 YYYYMMDD，默认库内最早交易日")
    parser.add_argument("--end-date", default="", help="回测窗口终点，默认库内最新交易日")
    parser.add_argument("--no-export-signals", action="store_true", help="仅打印指标不写出 CSV/JSON")
    args = parser.parse_args()

    config = ConfigManager()
    db = DatabaseManager(config)
    menu = SecondaryLaunchMenu(config, db)

    main_db = ROOT / config.get("database.path", "data/database/quant_system.db")
    dmin, dmax = _query_trade_date_bounds(main_db)
    start_date = args.start_date or dmin
    end_date = args.end_date or db.get_latest_trade_date("stock_daily") or dmax

    strategy, backtester = menu._build_strategy()
    hold_days = int(config.get("stock_selection.secondary_launch.hold_days", 2))

    data = backtester.load_data(
        start_date,
        end_date,
        warmup_days=120,
        forward_days=max(hold_days + 5, 15),
    )
    daily, basic = data["daily"], data["basic"]
    if daily.empty:
        print("错误: 日线数据为空", flush=True)
        return 1

    features = strategy.prepare_features(daily, basic)
    signal_frame = strategy.build_signal_frame(features)
    if signal_frame.empty:
        print("错误: 信号帧为空", flush=True)
        return 1

    signals = strategy.generate_signals_from_frame(signal_frame)
    bt_result = backtester.run_backtest(start_date, end_date, hold_days=hold_days)

    metrics = bt_result.get("metrics") or {}
    trades_df = bt_result.get("trades")
    if isinstance(trades_df, pd.DataFrame) and not trades_df.empty:
        trades_df = trades_df.copy()
        trades_df["signal_date_str"] = pd.to_datetime(trades_df["signal_date"]).dt.strftime("%Y%m%d")

    out_dir = ROOT / "results"
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    payload = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "strategy_version": str(config.get("stock_selection.secondary_launch.strategy_version", "")),
        "strategy_label": menu.get_strategy_label(),
        "data_range": {"stock_daily_min": dmin, "stock_daily_max": dmax},
        "backtest_window": {"start": start_date, "end": end_date},
        "hold_days": hold_days,
        "signal_count": int(len(signals)) if signals is not None and not signals.empty else 0,
        "metrics": {k: (float(v) if isinstance(v, (int, float)) else v) for k, v in metrics.items() if k != "regime"},
    }

    if not args.no_export_signals and signals is not None and not signals.empty:
        sig_path = out_dir / f"secondary_launch_v3_signals_full_{ts}.csv"
        signals.to_csv(sig_path, index=False, encoding="utf-8-sig")
        payload["signals_csv"] = str(sig_path)

    if not args.no_export_signals and isinstance(trades_df, pd.DataFrame) and not trades_df.empty:
        tr_path = out_dir / f"secondary_launch_v3_trades_{ts}.csv"
        trades_df.to_csv(tr_path, index=False, encoding="utf-8-sig")
        payload["trades_csv"] = str(tr_path)

    json_path = out_dir / f"secondary_launch_v3_backtest_{ts}.json"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    payload["json_report"] = str(json_path)

    # 简短 Markdown 摘要
    md_lines = [
        "# 二次启动 V3 全历史回测摘要",
        "",
        f"- 生成时间: {payload['generated_at']}",
        f"- 策略版本: {payload.get('strategy_version', '')} | {payload.get('strategy_label', '')}",
        f"- 日线库范围: {dmin} ~ {dmax}",
        f"- 本次回测窗口: {start_date} ~ {end_date}（持仓 {hold_days} 日）",
        f"- 选股信号条数: {payload['signal_count']}",
        "",
        "## 指标（日线开盘价买入、持仓 hold_days 日收盘卖出，含滑点与费用）",
        "",
    ]
    for key in (
        "total_trades",
        "total_signal_days",
        "win_rate",
        "day_win_rate",
        "annual_return",
        "sharpe_ratio",
        "max_drawdown",
        "total_return",
        "profit_factor",
    ):
        if key in metrics:
            md_lines.append(f"- **{key}**: {metrics[key]}")
    md_lines.extend(["", f"- 详细 JSON: `{json_path}`", ""])
    if payload.get("signals_csv"):
        md_lines.append(f"- 全量信号 CSV: `{payload['signals_csv']}`")
    if payload.get("trades_csv"):
        md_lines.append(f"- 交易明细 CSV: `{payload['trades_csv']}`")

    md_path = out_dir / f"secondary_launch_v3_backtest_{ts}.md"
    md_path.write_text("\n".join(md_lines), encoding="utf-8")
    payload["markdown_report"] = str(md_path)

    print(json.dumps(payload, ensure_ascii=False, indent=2))
    print(f"\nMarkdown: {md_path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
