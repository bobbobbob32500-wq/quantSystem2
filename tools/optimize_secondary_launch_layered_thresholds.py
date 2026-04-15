#!/usr/bin/env python
# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import json
import sqlite3
import statistics
import sys
from dataclasses import dataclass
from datetime import datetime, time
from itertools import product
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(ROOT / "tools"))

from scripts.analyze_secondary_launch_intraday import _load_session
from tools.analyze_secondary_launch_unified_truth import _fetch_daily_features
from src.modules.backtest.history_recommendation_db import HistoryRecommendationDB
from src.modules.secondary_launch_intraday import (
    _build_breakout_signal,
    _build_pullback_signal,
    _prepare_minute_frame,
    _resolve_breakout_threshold,
    _resolve_market_gate,
)


def _to_day(v: Any) -> str:
    s = str(v).strip()
    return s.replace("-", "")[:8] if s else ""


def _metric(vals: List[Optional[float]]) -> Dict[str, float]:
    x = [float(v) for v in vals if v is not None]
    if not x:
        return {
            "count": 0,
            "win_rate_pct": 0.0,
            "avg_return_pct": 0.0,
            "median_return_pct": 0.0,
            "profit_factor": 0.0,
        }
    pos = sum(v for v in x if v > 0)
    neg = -sum(v for v in x if v < 0)
    return {
        "count": len(x),
        "win_rate_pct": round(sum(v > 0 for v in x) / len(x) * 100, 2),
        "avg_return_pct": round(sum(x) / len(x) * 100, 2),
        "median_return_pct": round(statistics.median(x) * 100, 2),
        "profit_factor": round((pos / neg) if neg > 1e-12 else 0.0, 2),
    }


@dataclass
class ThresholdParams:
    direct_score_min: float
    direct_lgb_min: float
    semi_score_min: float
    semi_lgb_min: float
    direct_conf_min: float
    semi_conf_min: float

    def as_dict(self) -> Dict[str, float]:
        return {
            "direct_score_min": self.direct_score_min,
            "direct_lgb_min": self.direct_lgb_min,
            "semi_score_min": self.semi_score_min,
            "semi_lgb_min": self.semi_lgb_min,
            "direct_conf_min": self.direct_conf_min,
            "semi_conf_min": self.semi_conf_min,
        }

    def label(self) -> str:
        return (
            f"D(score>={self.direct_score_min:.1f},lgb>={self.direct_lgb_min:.3f},conf>={self.direct_conf_min:.2f}) | "
            f"S(score>={self.semi_score_min:.1f},lgb>={self.semi_lgb_min:.3f},conf>={self.semi_conf_min:.2f})"
        )


def _resolve_tier(candidate: Dict[str, Any], p: ThresholdParams) -> str:
    rank = int(candidate.get("rank") or 0)
    score = float(candidate.get("signal_score", candidate.get("score", 0.0)) or 0.0)
    lgb_prob_raw = candidate.get("lgb_prob")
    lgb_prob = float(lgb_prob_raw) if lgb_prob_raw is not None else None

    if rank == 1 and score >= p.direct_score_min and (lgb_prob is None or lgb_prob >= p.direct_lgb_min):
        return "direct"
    if rank == 1 and score >= p.semi_score_min and (lgb_prob is None or lgb_prob >= p.semi_lgb_min):
        return "semi"
    return "confirm"


def _exit_t2(conn: sqlite3.Connection, symbol: str, signal_date: str, entry_price: float) -> Optional[float]:
    rows = list(
        conn.execute(
            "SELECT trade_date, close FROM stock_daily WHERE ts_code=? AND trade_date>? ORDER BY trade_date ASC LIMIT 2",
            (symbol, signal_date),
        )
    )
    if len(rows) >= 2 and rows[1]["close"] is not None and entry_price > 0:
        return float(rows[1]["close"]) / entry_price - 1.0
    return None


def _resolve_entry(frame: pd.DataFrame, candidate: Dict[str, Any], p: ThresholdParams) -> Optional[Dict[str, Any]]:
    market_confirm = {"market_score": 50.0, "trend": "neutral", "index_below_vwap": False}
    market_gate = _resolve_market_gate(market_confirm)

    for idx in range(len(frame)):
        now = pd.Timestamp(frame.iloc[idx]["trade_time"]).to_pydatetime()
        if now.time() < time(9, 35) or now.time() > time(14, 20):
            continue
        window = frame.iloc[: idx + 1].copy()
        prepared = _prepare_minute_frame(window)
        if prepared.empty:
            continue
        quote = {"price": float(prepared.iloc[-1]["close"])}

        pullback = _build_pullback_signal(prepared, candidate, quote, now)
        breakout = _build_breakout_signal(prepared, candidate, quote, now, market_confirm=market_confirm)
        best = pullback if float(pullback.confidence or 0.0) >= float(breakout.confidence or 0.0) else breakout

        tier = _resolve_tier(candidate, p)
        conf = float(best.confidence or 0.0)
        blocked = bool((best.details or {}).get("route_blocked", False))
        weak_market = bool(market_gate.get("weak_market"))
        passed = False

        if tier == "direct":
            passed = now.time() >= time(9, 40) and conf >= p.direct_conf_min and (not blocked) and (not weak_market)
        elif tier == "semi":
            passed = now.time() >= time(9, 40) and conf >= p.semi_conf_min and (not blocked)
        else:
            breakout_threshold = _resolve_breakout_threshold(now, market_gate)
            passed = bool(
                (pullback.signal and float(pullback.confidence or 0.0) >= 0.60)
                or (breakout.signal and float(breakout.confidence or 0.0) >= breakout_threshold)
            )

        if passed:
            return {
                "entry_time": now.strftime("%H:%M:%S"),
                "entry_price": float(window.iloc[-1]["close"]),
                "signal_type": str(best.signal_type or ""),
                "execution_tier": tier,
                "confidence": conf,
            }
    return None


def _score(entry_rate: float, win_rate_pct: float, avg_ret_pct: float, profit_factor: float) -> float:
    # 平衡目标：优先中位收益/均收和触发率，避免频率过度牺牲。
    return (
        avg_ret_pct * 0.45
        + win_rate_pct * 0.20
        + entry_rate * 0.25
        + min(profit_factor, 4.0) * 2.5
    )


def _build_grid() -> List[ThresholdParams]:
    direct_score_grid = [76.0, 78.0, 80.0]
    direct_lgb_grid = [0.58, 0.60, 0.62]
    semi_score_grid = [70.0, 72.0, 74.0]
    semi_lgb_grid = [0.55, 0.569, 0.59]
    direct_conf_grid = [0.42, 0.45, 0.48]
    semi_conf_grid = [0.52, 0.55, 0.58]
    out: List[ThresholdParams] = []
    for ds, dl, ss, sl, dc, sc in product(
        direct_score_grid,
        direct_lgb_grid,
        semi_score_grid,
        semi_lgb_grid,
        direct_conf_grid,
        semi_conf_grid,
    ):
        if ss > ds:
            continue
        if sl > dl:
            continue
        if sc < dc:
            continue
        out.append(
            ThresholdParams(
                direct_score_min=ds,
                direct_lgb_min=dl,
                semi_score_min=ss,
                semi_lgb_min=sl,
                direct_conf_min=dc,
                semi_conf_min=sc,
            )
        )
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="二次启动分层阈值参数寻优")
    parser.add_argument("--signals-csv", default="results/secondary_launch_v3_signals_FINAL.csv")
    parser.add_argument("--minute-db", default="data/history_recommendation.db")
    parser.add_argument("--daily-db", default="data/database/quant_system.db")
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument("--max-samples", type=int, default=0, help="仅回放前N个样本，0表示全量")
    parser.add_argument("--max-combos", type=int, default=0, help="仅评估前N个参数组合，0表示全量")
    args = parser.parse_args()

    sig = pd.read_csv(ROOT / args.signals_csv)
    minute_db = HistoryRecommendationDB(str(ROOT / args.minute_db))
    conn = sqlite3.connect(str(ROOT / args.daily_db))
    conn.row_factory = sqlite3.Row

    rows = []
    for _, r in sig.iterrows():
        rows.append(
            {
                "signal_date": _to_day(r.get("signal_date")),
                "ts_code": str(r.get("ts_code", "") or "").strip().upper(),
                "name": str(r.get("name", "") or ""),
                "rank": int(r.get("rank") or 0),
                "signal_score": float(r.get("signal_score", 0.0) or 0.0),
                "lgb_prob": float(r.get("lgb_prob")) if pd.notna(r.get("lgb_prob")) else None,
            }
        )

    samples: List[Dict[str, Any]] = []
    for idx, row in enumerate(rows, start=1):
        frame = _load_session(minute_db, row["ts_code"], row["signal_date"])
        if frame.empty:
            continue
        feat = _fetch_daily_features(conn, row["ts_code"], row["signal_date"])
        candidate = {
            "symbol": row["ts_code"],
            "name": row["name"],
            "score": row["signal_score"],
            "signal_score": row["signal_score"],
            "rank": row["rank"],
            "lgb_prob": row["lgb_prob"],
            "pool_type": "core" if row["rank"] == 1 else "reserve",
            "industry": str((feat or {}).get("industry", "") or ""),
            "strategy_profile": "secondary_launch",
        }
        candidate.update(feat or {})
        samples.append({"row": row, "frame": frame, "candidate": candidate})
        if idx % 20 == 0:
            print(f"[样本加载] {idx}/{len(rows)}", flush=True)
        if args.max_samples > 0 and len(samples) >= args.max_samples:
            break

    grid = _build_grid()
    if args.max_combos > 0:
        grid = grid[: args.max_combos]
    print(f"有效样本数: {len(samples)} | 参数组合数: {len(grid)}", flush=True)
    total = len(samples)
    eval_rows = []
    baseline = ThresholdParams(78.0, 0.60, 72.0, 0.569, 0.45, 0.55)

    for i, p in enumerate(grid, start=1):
        entries = []
        for item in samples:
            hit = _resolve_entry(item["frame"], item["candidate"], p)
            if not hit:
                continue
            t2_ret = _exit_t2(
                conn,
                item["row"]["ts_code"],
                item["row"]["signal_date"],
                float(hit["entry_price"]),
            )
            entries.append({**hit, "t2_ret": t2_ret})

        m = _metric([x.get("t2_ret") for x in entries])
        entry_rate = round((len(entries) / total * 100), 2) if total > 0 else 0.0
        s = _score(entry_rate, m["win_rate_pct"], m["avg_return_pct"], m["profit_factor"])
        by_tier = {}
        for tier in ("direct", "semi", "confirm"):
            sub = [x.get("t2_ret") for x in entries if x.get("execution_tier") == tier]
            by_tier[tier] = _metric(sub)
        eval_rows.append(
            {
                "score": round(s, 4),
                "trade_count": len(entries),
                "entry_rate_pct": entry_rate,
                "metrics": m,
                "tier_metrics": by_tier,
                "params": p.as_dict(),
                "label": p.label(),
            }
        )
        if i % 120 == 0 or i == len(grid):
            print(f"[{i}/{len(grid)}] 已完成参数组合评估")

    eval_rows.sort(key=lambda x: x["score"], reverse=True)
    best = eval_rows[0]
    base = next((x for x in eval_rows if x["params"] == baseline.as_dict()), None)
    if base is None:
        base = eval_rows[0]

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_json = ROOT / "data" / "reports" / f"secondary_launch_layered_threshold_opt_{ts}.json"
    out_md = ROOT / "data" / "reports" / f"secondary_launch_layered_threshold_opt_{ts}.md"

    payload = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "sample_count": total,
        "grid_size": len(grid),
        "baseline": base,
        "best": best,
        "top_k": eval_rows[: max(1, args.top_k)],
    }
    out_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        "# 二次启动分层阈值优化报告",
        "",
        f"- 生成时间：{payload['generated_at']}",
        f"- 样本数：{total}",
        f"- 参数组合数：{len(grid)}",
        "",
        "## 当前参数 vs 最优参数",
        "",
        "| 指标 | 当前参数 | 最优参数 | 变化 |",
        "| --- | ---: | ---: | ---: |",
        f"| 综合得分 | {base['score']:.4f} | {best['score']:.4f} | {best['score']-base['score']:+.4f} |",
        f"| 交易数 | {base['trade_count']} | {best['trade_count']} | {best['trade_count']-base['trade_count']:+d} |",
        f"| 触发率 | {base['entry_rate_pct']:.2f}% | {best['entry_rate_pct']:.2f}% | {best['entry_rate_pct']-base['entry_rate_pct']:+.2f}% |",
        f"| 胜率 | {base['metrics']['win_rate_pct']:.2f}% | {best['metrics']['win_rate_pct']:.2f}% | {best['metrics']['win_rate_pct']-base['metrics']['win_rate_pct']:+.2f}% |",
        f"| 平均收益 | {base['metrics']['avg_return_pct']:.2f}% | {best['metrics']['avg_return_pct']:.2f}% | {best['metrics']['avg_return_pct']-base['metrics']['avg_return_pct']:+.2f}% |",
        f"| 中位收益 | {base['metrics']['median_return_pct']:.2f}% | {best['metrics']['median_return_pct']:.2f}% | {best['metrics']['median_return_pct']-base['metrics']['median_return_pct']:+.2f}% |",
        f"| 盈亏比 | {base['metrics']['profit_factor']:.2f} | {best['metrics']['profit_factor']:.2f} | {best['metrics']['profit_factor']-base['metrics']['profit_factor']:+.2f} |",
        "",
        "### 最优参数",
        "",
    ]
    for k, v in best["params"].items():
        lines.append(f"- `{k}` = `{v}`")

    lines.extend(
        [
            "",
            "## 最优参数按执行层表现",
            "",
            "| 执行层 | 样本数 | 胜率 | 平均收益 | 中位收益 | 盈亏比 |",
            "| --- | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for tier in ("direct", "semi", "confirm"):
        m = best["tier_metrics"][tier]
        lines.append(
            f"| {tier} | {m['count']} | {m['win_rate_pct']:.2f}% | {m['avg_return_pct']:.2f}% | {m['median_return_pct']:.2f}% | {m['profit_factor']:.2f} |"
        )

    lines.extend(
        [
            "",
            "## Top 10 参数组合",
            "",
            "| 排名 | 得分 | 交易数 | 触发率 | 胜率 | 平均收益 | 中位收益 | 盈亏比 | 参数 |",
            "| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
        ]
    )
    for idx, row in enumerate(eval_rows[:10], start=1):
        m = row["metrics"]
        lines.append(
            f"| {idx} | {row['score']:.4f} | {row['trade_count']} | {row['entry_rate_pct']:.2f}% | {m['win_rate_pct']:.2f}% | {m['avg_return_pct']:.2f}% | {m['median_return_pct']:.2f}% | {m['profit_factor']:.2f} | {row['label']} |"
        )

    out_md.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"JSON: {out_json}")
    print(f"MD: {out_md}")

    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
