# -*- coding: utf-8 -*-
"""
P0: 反馈闭环自动结算脚本

功能：
  对 history_recommendation.db 中所有 status='active' 且
  buy_date + hold_days <= end_date 的推荐记录，
  用实际收盘价（stock_daily）自动补录 sell_price / profit_pct，
  并将 status 更新为 'closed'。

  同时触发一次 SignalFeedbackEvaluator，将闭环数据写入
  quant_system.db 的 signal_feedback_detail 表，激活 FeedbackGuard。

用法：
  python tools/settle_recommendations.py                  # 结算截至今天
  python tools/settle_recommendations.py --end 20260327   # 指定截止日
  python tools/settle_recommendations.py --dry-run        # 仅预览，不写库
"""

import argparse
import sqlite3
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

# 确保能 import 项目模块
SYS_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SYS_ROOT))

HIST_DB   = str(SYS_ROOT / "data" / "history_recommendation.db")
QUANT_DB  = str(SYS_ROOT / "data" / "database" / "quant_system.db")
DEFAULT_HOLD_DAYS = 5   # 默认持有天数
BUY_FEE   = 0.0003      # 买入佣金
SELL_FEE  = 0.0003      # 卖出佣金
STAMP_TAX = 0.001       # 印花税（单向，卖出时收）


def norm_date(s) -> str:
    """统一日期格式为 YYYYMMDD。"""
    if not s:
        return ""
    digits = "".join(c for c in str(s) if c.isdigit())
    return digits[:8] if len(digits) >= 8 else ""


def get_close_price(quant_conn: sqlite3.Connection, ts_code: str, trade_date: str) -> float:
    """
    从 stock_daily 取指定股票指定日期的收盘价。
    若当天无数据（非交易日），取最近一个交易日的收盘价。
    """
    cur = quant_conn.cursor()
    # 先精确匹配
    cur.execute(
        "SELECT close FROM stock_daily WHERE ts_code=? AND trade_date=? LIMIT 1",
        (ts_code, trade_date),
    )
    row = cur.fetchone()
    if row:
        return float(row[0])

    # 取最近一个不晚于 trade_date 的交易日
    cur.execute(
        "SELECT close FROM stock_daily WHERE ts_code=? AND trade_date<=? "
        "ORDER BY trade_date DESC LIMIT 1",
        (ts_code, trade_date),
    )
    row = cur.fetchone()
    return float(row[0]) if row else 0.0


def get_ts_code(symbol: str) -> str:
    """将 symbol（纯数字股票代码）转为 ts_code（如 000001.SZ）。"""
    if "." in symbol:
        return symbol.upper()
    s = symbol.strip()
    if s.startswith(("6", "9")):
        return f"{s}.SH"
    return f"{s}.SZ"


def add_trading_days(start_date: str, days: int) -> str:
    """
    简单日历日偏移（近似）。
    严格版本需要查交易日历，此处用 days*1.5 的日历日近似覆盖节假日。
    """
    dt = datetime.strptime(start_date, "%Y%m%d")
    # 用日历日估算（5交易日 ≈ 7日历日，加缓冲）
    cal_days = int(days * 1.5) + 2
    result = dt + timedelta(days=cal_days)
    return result.strftime("%Y%m%d")


def settle(end_date: str, dry_run: bool = False, hold_days: int = DEFAULT_HOLD_DAYS):
    if not os.path.exists(HIST_DB):
        print(f"[ERROR] history_recommendation.db 不存在: {HIST_DB}")
        return
    if not os.path.exists(QUANT_DB):
        print(f"[ERROR] quant_system.db 不存在: {QUANT_DB}")
        return

    hist_conn  = sqlite3.connect(HIST_DB)
    hist_conn.row_factory = sqlite3.Row
    quant_conn = sqlite3.connect(QUANT_DB)

    cur = hist_conn.cursor()

    # 查询所有 active 且有买入价的推荐
    cur.execute(
        "SELECT id, symbol, name, buy_date, buy_price, recommendation_date "
        "FROM recommendations WHERE status='active' AND buy_price IS NOT NULL AND buy_price > 0"
    )
    rows = cur.fetchall()
    print(f"\n找到 {len(rows)} 条 active 推荐记录")

    settled = 0
    skipped = 0
    errors  = 0

    for row in rows:
        rec_id    = row["id"]
        symbol    = row["symbol"]
        name      = row["name"] or ""
        buy_date  = norm_date(row["buy_date"])
        buy_price = float(row["buy_price"])
        rec_date  = norm_date(row["recommendation_date"])

        if not buy_date:
            # buy_date 为空，用推荐日 +1
            if rec_date:
                buy_date = add_trading_days(rec_date, 1)
            else:
                print(f"  [SKIP] id={rec_id} {symbol} {name}: buy_date 为空")
                skipped += 1
                continue

        # 计算应结算日
        settle_date = add_trading_days(buy_date, hold_days)

        # 如果结算日还未到，跳过
        if settle_date > end_date:
            skipped += 1
            continue

        # 取结算日收盘价
        ts_code = get_ts_code(symbol)
        sell_price = get_close_price(quant_conn, ts_code, settle_date)

        if sell_price <= 0:
            print(f"  [WARN] id={rec_id} {symbol} {name}: 找不到 {settle_date} 收盘价，跳过")
            errors += 1
            continue

        # 计算净收益（扣除双边佣金 + 印花税）
        gross_return = (sell_price - buy_price) / buy_price
        cost = BUY_FEE + SELL_FEE + STAMP_TAX
        net_return = gross_return - cost
        profit_pct = round(net_return * 100, 4)
        hold_days_actual = (datetime.strptime(settle_date, "%Y%m%d")
                            - datetime.strptime(buy_date, "%Y%m%d")).days

        print(
            f"  {'[DRY]' if dry_run else '[OK] '} id={rec_id} {symbol} {name}: "
            f"买入{buy_date}@{buy_price:.2f} -> 卖出{settle_date}@{sell_price:.2f} "
            f"净收益{profit_pct:+.2f}% (持有{hold_days_actual}天)"
        )

        if not dry_run:
            try:
                hist_conn.execute(
                    "UPDATE recommendations SET "
                    "  sell_date=?, sell_price=?, profit_pct=?, hold_days=?, "
                    "  status='closed', updated_time=? "
                    "WHERE id=?",
                    (
                        settle_date,
                        round(sell_price, 2),
                        profit_pct,
                        hold_days_actual,
                        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        rec_id,
                    ),
                )
                settled += 1
            except Exception as e:
                print(f"  [ERROR] 更新 id={rec_id} 失败: {e}")
                errors += 1

    if not dry_run:
        hist_conn.commit()

    hist_conn.close()
    quant_conn.close()

    print(f"\n结算完成: 成功={settled}, 跳过={skipped}, 错误={errors}")

    if settled > 0 and not dry_run:
        print("\n开始触发信号闭环评估（写入 signal_feedback_detail）...")
        try:
            from src.core.config import ConfigManager
            from src.core.database import DatabaseManager
            from src.modules.signal_feedback_evaluator import SignalFeedbackEvaluator

            cfg = ConfigManager()
            db  = DatabaseManager(cfg)
            evaluator = SignalFeedbackEvaluator(config=cfg, db=db, persist_to_db=True)
            report = evaluator.run(
                end_date=end_date,
                lookback_days=180,
            )
            print(f"  闭环评估完成: {report.get('summary', '详情见数据库')}")
        except Exception as e:
            print(f"  [WARN] 闭环评估失败（不影响结算结果）: {e}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="自动结算历史推荐记录")
    parser.add_argument("--end",      default=datetime.now().strftime("%Y%m%d"),
                        help="结算截止日（YYYYMMDD），默认今天")
    parser.add_argument("--hold",     type=int, default=DEFAULT_HOLD_DAYS,
                        help=f"默认持有天数（默认{DEFAULT_HOLD_DAYS}）")
    parser.add_argument("--dry-run",  action="store_true",
                        help="仅预览结果，不写数据库")
    args = parser.parse_args()

    print(f"结算截止日: {args.end} | 持有天数: {args.hold} | dry-run: {args.dry_run}")
    settle(end_date=args.end, dry_run=args.dry_run, hold_days=args.hold)
