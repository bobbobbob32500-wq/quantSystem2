# -*- coding: utf-8 -*-
import json
import numpy as np
import pandas as pd
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.core.config import ConfigManager
from src.core.database import DatabaseManager
from src.modules.stock_selector import StockSelector


def main():
    config = ConfigManager()
    db = DatabaseManager(config)
    selector = StockSelector(config=config, db=db)

    all_dates = [r["trade_date"] for r in db.query("SELECT DISTINCT trade_date FROM stock_daily ORDER BY trade_date ASC")]
    all_dates = [d.strftime("%Y%m%d") if hasattr(d, "strftime") else str(d) for d in all_dates]
    signal_dates = all_dates[-(60 + 5) : -5]

    rows = []
    for td in signal_dates:
        recs = selector._run_alpha158_selection(td)
        recs = sorted(recs, key=lambda x: x.get("total_score", 0), reverse=True)[:5]
        td_idx = all_dates.index(td)
        buy_date = all_dates[td_idx + 1]
        sell_date = all_dates[td_idx + 3]

        for r in recs:
            ts_code = r["ts_code"]
            px_rows = db.query(
                "SELECT trade_date, open, close FROM stock_daily WHERE ts_code = ? AND trade_date IN (?, ?)",
                (ts_code, buy_date, sell_date),
            )
            pmap = {}
            for x in px_rows:
                ds = x["trade_date"].strftime("%Y%m%d") if hasattr(x["trade_date"], "strftime") else str(x["trade_date"])
                pmap[ds] = x
            if buy_date not in pmap or sell_date not in pmap:
                continue
            buy_open = float(pmap[buy_date]["open"])
            sell_close = float(pmap[sell_date]["close"])
            if buy_open <= 0:
                continue
            ret = (sell_close - buy_open) / buy_open

            factor_rows = db.query(
                "SELECT close, open, high, low, vol, amount FROM stock_daily "
                "WHERE ts_code = ? AND trade_date <= ? ORDER BY trade_date DESC LIMIT 61",
                (ts_code, td),
            )
            if len(factor_rows) < 61:
                continue
            fdf = pd.DataFrame(factor_rows).iloc[::-1]
            factors = selector._compute_alpha158_factors(
                fdf["close"].astype(float).values,
                fdf["high"].astype(float).values,
                fdf["low"].astype(float).values,
                fdf["vol"].astype(float).values,
                fdf["amount"].astype(float).values,
                len(fdf),
            )

            row = {
                "date": td,
                "ts_code": ts_code,
                "ret_t3": ret,
                "win": 1 if ret > 0 else 0,
                "regime": r.get("alpha158_regime", "unknown"),
                "score": float(r.get("alpha158_raw", 0.0)),
            }
            for k in [
                "ROC5",
                "ROC10",
                "MA_CROSS",
                "TURN20",
                "VOL_RATIO5",
                "VOL_RATIO20",
                "AMP20",
                "AMP5",
                "RSI14",
                "OBV_NORM",
                "BOLL_POS",
                "SUMN60",
                "VSTD30",
            ]:
                row[k] = float(factors.get(k, np.nan))
            rows.append(row)

    df = pd.DataFrame(rows)
    out = {"n": int(len(df)), "win_rate": float(df["win"].mean()) if not df.empty else 0.0}
    if not df.empty:
        win_df = df[df["win"] == 1]
        lose_df = df[df["win"] == 0]
        cols = [
            "ROC5",
            "ROC10",
            "MA_CROSS",
            "TURN20",
            "VOL_RATIO5",
            "VOL_RATIO20",
            "AMP20",
            "AMP5",
            "RSI14",
            "OBV_NORM",
            "BOLL_POS",
            "SUMN60",
            "VSTD30",
            "score",
        ]
        diffs = []
        for c in cols:
            w = float(win_df[c].mean())
            l = float(lose_df[c].mean())
            diffs.append({"feature": c, "win_mean": w, "lose_mean": l, "diff": w - l})
        diffs = sorted(diffs, key=lambda x: abs(x["diff"]), reverse=True)
        out["top_diffs"] = diffs[:10]
        out["threshold_hints"] = {}
        for c in ["TURN20", "VOL_RATIO20", "MA_CROSS", "AMP20", "RSI14", "ROC5"]:
            out["threshold_hints"][c] = {
                "win_q25": float(win_df[c].quantile(0.25)),
                "win_q50": float(win_df[c].quantile(0.50)),
                "lose_q50": float(lose_df[c].quantile(0.50)),
            }
        out["regime"] = {}
        for regime_name, sub in df.groupby("regime"):
            out["regime"][str(regime_name)] = {
                "n": int(len(sub)),
                "win_rate": float(sub["win"].mean()),
                "mean_ret": float(sub["ret_t3"].mean()),
            }

    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
