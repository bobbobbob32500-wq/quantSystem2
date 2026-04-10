# -*- coding: utf-8 -*-
"""
导出突破策略「盘前观察池」历史名单（每个信号日一行多票），与当前 run() 逻辑一致。

输出:
  data/reports/breakout_watchlist_history_latest.csv
  data/reports/breakout_watchlist_history_<时间戳>.csv

说明:
  - 非「次日突破确认成交」名单；成交明细见 breakout_backtest_trades_*.csv
"""
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
from src.core.config import ConfigManager
from src.core.database import DatabaseManager
from src.modules.breakout_strategy import BreakoutStrategy, BreakoutParams


def main():
    config = ConfigManager()
    db = DatabaseManager(config)
    info = db.query(
        "SELECT MAX(trade_date) AS max_d FROM stock_daily"
    )
    max_d = info[0]["max_d"] if info else None
    if not max_d:
        print("无日线数据")
        return

    all_dates = [
        r["trade_date"]
        for r in db.query(
            "SELECT DISTINCT trade_date FROM stock_daily ORDER BY trade_date ASC"
        )
    ]
    if len(all_dates) >= 180:
        warmup_skip = 125
    elif len(all_dates) >= 75:
        warmup_skip = 65
    else:
        print(f"数据不足: {len(all_dates)} 天")
        return

    signal_dates = all_dates[warmup_skip:-1]

    params = BreakoutParams()
    params.min_amt_ma20 = 8e4
    params.rs_quantile_max = 0.97
    params.rs_quantile_min = 0.80
    params.min_signal_score = 60.0
    # 与 run_breakout_daily_backtest_report / OOS 网格推荐一致
    params.top_k = 20
    if len(all_dates) < 180:
        params.atr_quantile_max = 0.50
        params.box_max_range = 0.08

    strategy = BreakoutStrategy(db=db, params=params)
    raw_daily, raw_basic = strategy._load_data(str(max_d))
    if raw_daily.empty:
        print("加载日线失败")
        return
    features = strategy._compute_features(raw_daily, raw_basic, str(max_d))

    rows = []
    for td in signal_dates:
        items = strategy.select_watchlist_from_features(features, str(td))
        for it in items:
            rows.append(
                {
                    "watch_date": it.watch_date,
                    "ts_code": it.ts_code,
                    "name": it.name,
                    "signal_score": it.signal_score,
                    "close": it.close,
                    "pivot": it.pivot,
                    "trigger_price": it.trigger_price,
                    "stop_loss": it.stop_loss,
                    "rs20_xsec_q": it.rs20_xsec_q,
                    "box_range_pct": it.box_range,
                    "industry": it.industry,
                }
            )

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    rep = os.path.join(root, "data", "reports")
    os.makedirs(rep, exist_ok=True)
    df = pd.DataFrame(rows)
    latest = os.path.join(rep, "breakout_watchlist_history_latest.csv")
    stamp = os.path.join(
        rep, f"breakout_watchlist_history_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    )
    df.to_csv(latest, index=False, encoding="utf-8-sig")
    df.to_csv(stamp, index=False, encoding="utf-8-sig")
    print(f"共 {len(df)} 条记录，覆盖 {df['watch_date'].nunique() if not df.empty else 0} 个信号日")
    print(latest)
    print(stamp)


if __name__ == "__main__":
    main()
