#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
穷举过滤规则组合，找到提升胜率最大且误伤最少的方案。

核心思路：从高区分度维度中构造候选过滤条件，组合搜索最优。
目标函数：最大化 (新胜率 - 旧胜率) * 权重 + 净避免亏损 * 权重，约束误伤正收益不超过总正收益的 15%。
"""

from __future__ import annotations

import json
import sqlite3
import sys
from itertools import combinations
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Tuple

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _flush(*args):
    print(*args, flush=True)


def get_daily_features(conn: sqlite3.Connection, symbol: str, signal_date: str) -> Dict[str, Any]:
    rows = list(conn.execute(
        """SELECT trade_date, open, close, high, low, vol, amount, pct_chg
           FROM stock_daily
           WHERE ts_code = ? AND trade_date <= ?
           ORDER BY trade_date DESC LIMIT 20""",
        (symbol, signal_date),
    ))
    if not rows:
        return {}

    today = rows[0]
    today_close = float(today["close"]) if today["close"] else None
    today_open = float(today["open"]) if today["open"] else None
    pct_chg = float(today["pct_chg"]) if today["pct_chg"] is not None else None

    vols = [float(r["vol"]) for r in rows[:5] if r["vol"] is not None]
    avg_vol_5 = sum(vols) / len(vols) if vols else None
    today_vol = float(today["vol"]) if today["vol"] else None
    vol_ratio_5 = (today_vol / avg_vol_5) if today_vol and avg_vol_5 and avg_vol_5 > 0 else None

    amplitude = None
    if today["high"] and today["low"] and today["close"]:
        amplitude = (float(today["high"]) - float(today["low"])) / float(today["close"]) * 100

    ret_5d = None
    if len(rows) >= 5 and rows[4]["close"] and today_close:
        ret_5d = (today_close / float(rows[4]["close"]) - 1.0) * 100

    ret_10d = None
    if len(rows) >= 10 and rows[9]["close"] and today_close:
        ret_10d = (today_close / float(rows[9]["close"]) - 1.0) * 100

    upper_shadow_pct = None
    if today["high"] and today["close"] and today["open"] and today["low"]:
        h, c, o, l = float(today["high"]), float(today["close"]), float(today["open"]), float(today["low"])
        total_range = h - l
        if total_range > 0:
            upper_shadow_pct = (h - max(c, o)) / total_range * 100

    down_days = 0
    for r in rows[:5]:
        if r["pct_chg"] is not None and float(r["pct_chg"]) < 0:
            down_days += 1
        else:
            break

    limit_up = pct_chg is not None and pct_chg > 9.5

    return {
        "pct_chg": pct_chg,
        "vol_ratio_5": round(vol_ratio_5, 4) if vol_ratio_5 else None,
        "amplitude": round(amplitude, 2) if amplitude else None,
        "ret_5d": round(ret_5d, 2) if ret_5d else None,
        "ret_10d": round(ret_10d, 2) if ret_10d else None,
        "upper_shadow_pct": round(upper_shadow_pct, 1) if upper_shadow_pct is not None else None,
        "down_days": down_days,
        "limit_up": limit_up,
    }


# 候选原子条件
ATOMS: List[Tuple[str, Callable]] = [
    ("跌>3%",            lambda r: r.get("pct_chg") is not None and r["pct_chg"] < -3),
    ("跌>5%",            lambda r: r.get("pct_chg") is not None and r["pct_chg"] < -5),
    ("跌[-5%,-3%)",      lambda r: r.get("pct_chg") is not None and -5 <= r["pct_chg"] < -3),
    ("上影>50%",         lambda r: r.get("upper_shadow_pct") is not None and r["upper_shadow_pct"] > 50),
    ("上影>40%",         lambda r: r.get("upper_shadow_pct") is not None and r["upper_shadow_pct"] > 40),
    ("上影>60%",         lambda r: r.get("upper_shadow_pct") is not None and r["upper_shadow_pct"] > 60),
    ("连跌>=3",          lambda r: r.get("down_days") is not None and r["down_days"] >= 3),
    ("连跌>=2",          lambda r: r.get("down_days") is not None and r["down_days"] >= 2),
    ("量比>1.2",         lambda r: r.get("vol_ratio_5") is not None and r["vol_ratio_5"] > 1.2),
    ("量比>1.3",         lambda r: r.get("vol_ratio_5") is not None and r["vol_ratio_5"] > 1.3),
    ("振幅>10%",         lambda r: r.get("amplitude") is not None and r["amplitude"] > 10),
    ("振幅>9%",          lambda r: r.get("amplitude") is not None and r["amplitude"] > 9),
    ("5日跌>5%+当日跌",   lambda r: (r.get("ret_5d") is not None and r["ret_5d"] < -5) and (r.get("pct_chg") is not None and r["pct_chg"] < 0)),
    ("跌>3%+放量>0.9",   lambda r: (r.get("pct_chg") is not None and r["pct_chg"] < -3) and (r.get("vol_ratio_5") is not None and r["vol_ratio_5"] > 0.9)),
    ("跌+上影>40%",      lambda r: (r.get("pct_chg") is not None and r["pct_chg"] < 0) and (r.get("upper_shadow_pct") is not None and r["upper_shadow_pct"] > 40)),
    ("跌>3%+上影>30%",   lambda r: (r.get("pct_chg") is not None and r["pct_chg"] < -3) and (r.get("upper_shadow_pct") is not None and r["upper_shadow_pct"] > 30)),
    ("10日涨>30%",       lambda r: r.get("ret_10d") is not None and r["ret_10d"] > 30),
    ("10日涨>25%",       lambda r: r.get("ret_10d") is not None and r["ret_10d"] > 25),
    ("缩量<0.55",        lambda r: r.get("vol_ratio_5") is not None and r["vol_ratio_5"] < 0.55),
    ("rank3",            lambda r: r.get("rank") == 3),
]


def main() -> int:
    truth_path = ROOT / "results" / "secondary_launch_unified_truth_20260402_114221.json"
    truth = json.loads(truth_path.read_text(encoding="utf-8"))

    daily_conn = sqlite3.connect(str(ROOT / "data/database/quant_system.db"))
    daily_conn.row_factory = sqlite3.Row

    entries = truth.get("entries", [])
    records = []
    for e in entries:
        daily_feat = get_daily_features(daily_conn, e["symbol"], e["signal_date"])
        t2_ret = e.get("T+2_close_ret")
        records.append({
            **e,
            **daily_feat,
            "T+2_ret": round(t2_ret * 100, 2) if t2_ret is not None else None,
            "T+2_positive": t2_ret is not None and t2_ret > 0,
        })
    daily_conn.close()

    has_t2 = [r for r in records if r.get("T+2_ret") is not None]
    positive = [r for r in has_t2 if r["T+2_positive"]]
    negative = [r for r in has_t2 if not r["T+2_positive"]]
    base_wr = len(positive) / len(has_t2) * 100
    base_avg = sum(r["T+2_ret"] for r in has_t2) / len(has_t2)
    total_pos = len(positive)

    _flush(f"基线: {len(has_t2)}条 胜率={base_wr:.1f}% T+2均收={base_avg:.2f}%")
    _flush(f"正收益={total_pos} 负收益={len(negative)}\n")

    # OR 组合搜索（1~3个原子条件取 OR）
    best_results = []

    for combo_size in range(1, 4):
        for combo in combinations(range(len(ATOMS)), combo_size):
            names = [ATOMS[i][0] for i in combo]
            fns = [ATOMS[i][1] for i in combo]

            def combined_filter(r, _fns=fns):
                return any(fn(r) for fn in _fns)

            blocked_pos = [r for r in positive if combined_filter(r)]
            blocked_neg = [r for r in negative if combined_filter(r)]

            # 约束：误伤不超过正收益的 20%
            if len(blocked_pos) > total_pos * 0.20:
                continue

            remain_pos = [r for r in positive if not combined_filter(r)]
            remain_neg = [r for r in negative if not combined_filter(r)]
            new_total = len(remain_pos) + len(remain_neg)
            if new_total < 50:
                continue

            new_wr = len(remain_pos) / new_total * 100
            new_avg = sum(r["T+2_ret"] for r in remain_pos + remain_neg) / new_total

            avoided_loss = sum(abs(r["T+2_ret"]) for r in blocked_neg)
            lost_profit = sum(r["T+2_ret"] for r in blocked_pos)
            net = avoided_loss - lost_profit

            # 综合得分：胜率提升 * 40 + 均收提升 * 30 + 精确度 * 20 + 净收益 * 0.1
            wr_gain = new_wr - base_wr
            avg_gain = new_avg - base_avg
            precision = len(blocked_neg) / (len(blocked_pos) + len(blocked_neg)) * 100 if (len(blocked_pos) + len(blocked_neg)) > 0 else 0
            score = wr_gain * 40 + avg_gain * 30 + precision * 0.2 + net * 0.1

            best_results.append({
                "names": " | ".join(names),
                "blocked_pos": len(blocked_pos),
                "blocked_neg": len(blocked_neg),
                "remain": new_total,
                "new_wr": round(new_wr, 1),
                "wr_gain": round(wr_gain, 1),
                "new_avg": round(new_avg, 2),
                "avg_gain": round(avg_gain, 2),
                "precision": round(precision, 1),
                "net_benefit": round(net, 1),
                "score": round(score, 1),
            })

    best_results.sort(key=lambda x: x["score"], reverse=True)

    _flush(f"符合约束的组合: {len(best_results)}")
    _flush(f"\n{'='*90}")
    _flush(f"Top 30 过滤规则组合 (按综合得分排序)")
    _flush(f"{'='*90}")
    _flush(f"\n{'#':>3} {'得分':>6} {'规则':<45} {'拦正':>4} {'拦负':>4} {'剩余':>4} {'新胜率':>6} {'提升':>5} {'新均收':>6} {'精确':>5}")
    _flush(f"{'':>3} {'':>6} {'':45} {'':>4} {'':>4} {'':>4} {'':>6} {'':>5} {'':>6} {'':>5}")

    for i, r in enumerate(best_results[:30]):
        _flush(
            f"{i+1:>3} {r['score']:>6.1f} {r['names']:<45} "
            f"{r['blocked_pos']:>4} {r['blocked_neg']:>4} {r['remain']:>4} "
            f"{r['new_wr']:>5.1f}% {r['wr_gain']:>+4.1f} {r['new_avg']:>5.2f}% "
            f"{r['precision']:>4.1f}%"
        )

    # 保存
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = ROOT / "results" / f"filter_search_{ts}.json"
    out.write_text(json.dumps(best_results[:50], ensure_ascii=False, indent=2), encoding="utf-8")
    _flush(f"\n结果已保存: {out}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
