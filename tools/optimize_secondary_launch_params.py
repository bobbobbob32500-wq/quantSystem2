#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
二次启动盘中参数网格搜索优化器。

核心优化：
  - 预计算每个样本的完整 prepared DataFrame（含 VWAP）
  - 回放时只做 iloc 切片 + 纯数值计算
  - 分阶段降维搜索
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time as _time
from dataclasses import dataclass, field
from datetime import datetime, time
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.modules.backtest.history_recommendation_db import HistoryRecommendationDB


# ---------------------------------------------------------------------------
# 参数定义
# ---------------------------------------------------------------------------

@dataclass
class IntradayParams:
    monitor_start: time = time(9, 45)
    monitor_end: time = time(14, 20)

    # 回踩
    pullback_min_bars: int = 8
    pullback_recent_window: int = 6
    support_factor: float = 1.001
    low_hold_factor: float = 0.996
    rebound_factor: float = 1.003
    not_far_factor: float = 0.985
    volume_ratio_low: float = 0.6
    volume_ratio_high: float = 1.35
    pullback_confidence_threshold: float = 0.70

    # 突破
    breakout_min_bars: int = 15
    breakout_price_factor: float = 1.002
    hold_above_factor: float = 0.998
    vwap_support_factor: float = 1.001
    compact_range_max: float = 0.025
    follow_through_low_factor: float = 0.997
    required_vol_ratio_am: float = 1.4
    required_vol_ratio_pm: float = 1.6
    near_high_dist: float = 0.015
    near_high_vol: float = 1.5
    breakout_threshold_am: float = 0.68
    breakout_threshold_pm: float = 0.73
    afternoon_time: time = time(13, 30)

    def label(self) -> str:
        return (
            f"PB cf{self.pullback_confidence_threshold:.2f} "
            f"v{self.volume_ratio_low:.1f}-{self.volume_ratio_high:.1f} "
            f"sf{self.support_factor:.3f} rb{self.rebound_factor:.3f} "
            f"nf{self.not_far_factor:.3f} | "
            f"BO am{self.breakout_threshold_am:.2f} pm{self.breakout_threshold_pm:.2f} "
            f"va{self.required_vol_ratio_am:.1f} vp{self.required_vol_ratio_pm:.1f} "
            f"cr{self.compact_range_max:.3f} | "
            f"{self.monitor_start.strftime('%H:%M')}-{self.monitor_end.strftime('%H:%M')}"
        )


BASELINE = IntradayParams()


# ---------------------------------------------------------------------------
# 预处理
# ---------------------------------------------------------------------------

def _prepare_full_day(raw_frame: pd.DataFrame) -> pd.DataFrame:
    """对一整天的分钟数据做一次 prepare（含 VWAP）。"""
    df = raw_frame.copy()

    def _resolve(names):
        for n in names:
            if n in df.columns:
                return pd.to_numeric(df[n], errors="coerce")
        return None

    price = _resolve(["close", "price", "last"])
    high = _resolve(["high"])
    low = _resolve(["low"])
    open_ = _resolve(["open"])
    volume = _resolve(["volume", "vol"])

    for name in ("timestamp", "datetime", "time", "trade_time"):
        if name in df.columns:
            ts = pd.to_datetime(df[name], errors="coerce")
            break
    else:
        ts = pd.Series(pd.NaT, index=df.index)

    prepared = pd.DataFrame({
        "timestamp": ts,
        "open": open_ if open_ is not None else price,
        "high": high if high is not None else price,
        "low": low if low is not None else price,
        "close": price,
        "volume": volume if volume is not None else 0.0,
    }).dropna(subset=["close"])

    if prepared.empty:
        return prepared
    prepared = prepared.ffill().bfill()
    prepared = prepared.sort_values("timestamp").reset_index(drop=True)
    cum_pv = (prepared["close"] * prepared["volume"]).cumsum()
    cum_v = prepared["volume"].replace(0, np.nan).cumsum()
    prepared["vwap"] = (cum_pv / cum_v).fillna(prepared["close"])
    return prepared


# ---------------------------------------------------------------------------
# 纯 numpy 的回踩/突破检测（用 prepared 的 iloc 前缀切片）
# ---------------------------------------------------------------------------

def _check_pullback(
    close: np.ndarray,
    high: np.ndarray,
    low: np.ndarray,
    volume: np.ndarray,
    vwap: np.ndarray,
    session_open: float,
    n: int,
    p: IntradayParams,
) -> tuple[bool, float]:
    """纯数组操作的回踩检测。n = 当前根序号 (0-based)。"""
    if n + 1 < p.pullback_min_bars:
        return False, 0.0

    rw = p.pullback_recent_window
    start = max(0, n + 1 - rw)
    recent_close = close[start: n + 1]
    recent_low = low[start: n + 1]
    recent_vol = volume[start: n + 1]

    current_price = close[n]
    current_vwap = vwap[n]

    recent_low_min = float(np.min(recent_low))

    # 前高
    if n > 0:
        prior_end = n
        prior_start = max(0, prior_end - 20)
        prior_high = float(np.max(high[prior_start:prior_end]))
    else:
        prior_high = current_price

    # 量比
    recent_avg_vol = float(np.mean(recent_vol[-3:])) if len(recent_vol) >= 3 else float(np.mean(recent_vol))
    total_bars = 12
    prev_bars = 9
    if n + 1 >= total_bars:
        prev_slice = volume[n + 1 - total_bars: n + 1 - total_bars + prev_bars]
        prev_avg_vol = float(np.mean(prev_slice))
    else:
        prev_avg_vol = recent_avg_vol
    volume_ratio = recent_avg_vol / prev_avg_vol if prev_avg_vol > 0 else 1.0

    support_price = max(current_vwap, session_open)
    support_hold = (
        current_price >= support_price * p.support_factor
        and recent_low_min >= support_price * p.low_hold_factor
    )

    prev_close = close[n - 1] if n > 0 else current_price
    recent_close_min = float(np.min(recent_close))
    rebound = current_price >= prev_close and current_price >= recent_close_min * p.rebound_factor
    not_far = prior_high <= 0 or current_price >= prior_high * p.not_far_factor
    vol_ok = p.volume_ratio_low <= volume_ratio <= p.volume_ratio_high

    sig = support_hold and rebound and not_far and vol_ok
    conf = 0.0
    if support_hold: conf += 0.35
    if rebound: conf += 0.25
    if not_far: conf += 0.20
    if vol_ok: conf += 0.20
    return sig, conf


def _check_breakout(
    close: np.ndarray,
    high: np.ndarray,
    low: np.ndarray,
    volume: np.ndarray,
    vwap: np.ndarray,
    n: int,
    is_afternoon: bool,
    p: IntradayParams,
) -> tuple[bool, float]:
    if n + 1 < p.breakout_min_bars:
        return False, 0.0

    current_price = close[n]
    current_volume = volume[n]
    current_vwap = vwap[n]

    pw = 15
    w_start = max(0, n + 1 - pw)
    w_end = n  # 不含当前根
    if w_end <= w_start:
        return False, 0.0

    window_high = high[w_start:w_end]
    window_low = low[w_start:w_end]
    window_vol = volume[w_start:w_end]

    breakout_price = float(np.max(window_high))
    consolidation_low = float(np.min(window_low))
    range_pct = (breakout_price - consolidation_low) / consolidation_low if consolidation_low > 0 else 0.0
    avg_vol_5 = float(np.mean(window_vol[-5:])) if len(window_vol) >= 5 else float(np.mean(window_vol))
    vol_ratio = current_volume / avg_vol_5 if avg_vol_5 > 0 else 0.0

    rh_start = max(0, n + 1 - 30)
    recent_high = float(np.max(high[rh_start:n + 1]))
    dist_to_high = max(0.0, recent_high / current_price - 1.0) if current_price > 0 else 0.0

    req_vr = p.required_vol_ratio_pm if is_afternoon else p.required_vol_ratio_am

    breakout = current_price > breakout_price * p.breakout_price_factor
    hold_above = all(close[max(0, n - 2):n + 1] >= breakout_price * p.hold_above_factor)
    vwap_sup = current_price >= current_vwap * p.vwap_support_factor
    compact = range_pct <= p.compact_range_max

    tail3_close = close[max(0, n - 2):n + 1]
    tail3_low = low[max(0, n - 2):n + 1]
    up_count = int(np.sum(np.diff(tail3_close) > 0)) if len(tail3_close) > 1 else 0
    follow = up_count >= 2 and float(np.min(tail3_low)) >= breakout_price * p.follow_through_low_factor
    vol_ok = vol_ratio >= req_vr
    near_high_veto = dist_to_high <= p.near_high_dist and vol_ratio < p.near_high_vol

    sig = breakout and hold_above and vwap_sup and compact and vol_ok and follow and not near_high_veto
    conf = 0.0
    if breakout: conf += 0.30
    if hold_above: conf += 0.20
    if vwap_sup: conf += 0.20
    if compact: conf += 0.15
    if vol_ok: conf += 0.10
    if follow: conf += 0.05
    return sig, conf


# ---------------------------------------------------------------------------
# 预计算的样本容器
# ---------------------------------------------------------------------------

@dataclass
class SampleData:
    symbol: str
    signal_date: str
    name: str
    rank: int
    # 预提取的 numpy 数组（全天）
    timestamps: np.ndarray  # datetime64
    close: np.ndarray
    high: np.ndarray
    low: np.ndarray
    volume: np.ndarray
    vwap: np.ndarray
    session_open: float
    n_bars: int
    # 每根 bar 的 time 对象（用于时间窗过滤）
    bar_times: List[time]


def _trade_date(signal_date: str) -> str:
    s = str(signal_date)
    return f"{s[:4]}-{s[4:6]}-{s[6:8]}"


def _flush(*args):
    print(*args, flush=True)


def preload_samples(
    report_path: Path,
    minute_db: HistoryRecommendationDB,
) -> List[SampleData]:
    report = json.loads(report_path.read_text(encoding="utf-8"))
    details = list(report.get("details", []) or [])
    samples: List[SampleData] = []

    _flush(f"  从报表加载 {len(details)} 条记录...")
    loaded = 0
    skipped = 0
    for item in details:
        symbol = str(item.get("ts_code", "") or "").strip().upper()
        signal_date = str(item.get("signal_date", "") or "").strip()
        if not symbol or not signal_date:
            continue

        day_str = _trade_date(signal_date)
        start_t = f"{day_str}T09:00:00"
        end_t = f"{day_str}T15:30:00"
        raw = minute_db.get_intraday_data(symbol, start_time=start_t, end_time=end_t)
        if raw.empty:
            skipped += 1
            continue

        prepared = _prepare_full_day(raw)
        if prepared.empty or len(prepared) < 2:
            skipped += 1
            continue

        ts_series = prepared["timestamp"]
        bar_times = [pd.Timestamp(t).time() for t in ts_series]

        samples.append(SampleData(
            symbol=symbol,
            signal_date=signal_date,
            name=str(item.get("name", "")),
            rank=int(item.get("rank") or 0),
            timestamps=ts_series.values,
            close=prepared["close"].values.astype(float),
            high=prepared["high"].values.astype(float),
            low=prepared["low"].values.astype(float),
            volume=prepared["volume"].values.astype(float),
            vwap=prepared["vwap"].values.astype(float),
            session_open=float(prepared.iloc[0]["open"]),
            n_bars=len(prepared),
            bar_times=bar_times,
        ))
        loaded += 1
        if loaded % 20 == 0:
            _flush(f"    已加载 {loaded} 条...")

    _flush(f"  加载完成: {loaded} 条有效, {skipped} 条跳过")
    return samples


# ---------------------------------------------------------------------------
# 回放 + 评估
# ---------------------------------------------------------------------------

def replay_sample(sample: SampleData, p: IntradayParams) -> Optional[Dict[str, Any]]:
    for n in range(sample.n_bars):
        bt = sample.bar_times[n]
        if bt < p.monitor_start or bt > p.monitor_end:
            continue

        # 回踩
        pb_sig, pb_conf = _check_pullback(
            sample.close, sample.high, sample.low, sample.volume, sample.vwap,
            sample.session_open, n, p,
        )
        if pb_sig and pb_conf >= p.pullback_confidence_threshold:
            return {
                "entry_idx": n,
                "entry_time": bt,
                "entry_price": float(sample.close[n]),
                "signal_type": "pullback",
                "confidence": pb_conf,
            }

        # 突破
        is_afternoon = bt >= p.afternoon_time
        bo_sig, bo_conf = _check_breakout(
            sample.close, sample.high, sample.low, sample.volume, sample.vwap,
            n, is_afternoon, p,
        )
        bo_threshold = p.breakout_threshold_pm if is_afternoon else p.breakout_threshold_am
        if bo_sig and bo_conf >= bo_threshold:
            return {
                "entry_idx": n,
                "entry_time": bt,
                "entry_price": float(sample.close[n]),
                "signal_type": "breakout",
                "confidence": bo_conf,
            }

    return None


def compute_t2_return(symbol: str, signal_date: str, entry_price: float, daily_conn: sqlite3.Connection) -> Optional[float]:
    rows = list(daily_conn.execute(
        "SELECT trade_date, close FROM stock_daily "
        "WHERE ts_code = ? AND trade_date > ? ORDER BY trade_date ASC LIMIT 2",
        (symbol, signal_date),
    ))
    if len(rows) >= 2 and rows[1]["close"] is not None:
        return float(rows[1]["close"]) / entry_price - 1.0
    return None


@dataclass
class EvalResult:
    params: IntradayParams
    entries: List[Dict[str, Any]] = field(default_factory=list)
    total_samples: int = 0
    trigger_count: int = 0
    positive_triggers: int = 0
    negative_triggers: int = 0
    win_rate: float = 0.0
    avg_return: float = 0.0
    score: float = -999.0


def evaluate_params(
    samples: List[SampleData],
    daily_conn: sqlite3.Connection,
    p: IntradayParams,
) -> EvalResult:
    result = EvalResult(params=p, total_samples=len(samples))
    t2_returns: List[float] = []

    for sample in samples:
        entry = replay_sample(sample, p)
        if entry is None:
            continue
        t2_ret = compute_t2_return(sample.symbol, sample.signal_date, entry["entry_price"], daily_conn)
        bt = entry["entry_time"]
        entry_info = {
            "symbol": sample.symbol,
            "signal_date": sample.signal_date,
            "name": sample.name,
            "rank": sample.rank,
            "entry_time": f"{bt.hour:02d}:{bt.minute:02d}:{bt.second:02d}",
            "entry_price": entry["entry_price"],
            "signal_type": entry["signal_type"],
            "T+2_close_ret": t2_ret,
        }
        result.entries.append(entry_info)
        result.trigger_count += 1
        if t2_ret is not None:
            t2_returns.append(t2_ret)
            if t2_ret > 0:
                result.positive_triggers += 1
            else:
                result.negative_triggers += 1

    if not t2_returns or len(t2_returns) < 3:
        result.score = -999.0
        return result

    result.win_rate = result.positive_triggers / len(t2_returns)
    result.avg_return = sum(t2_returns) / len(t2_returns)
    result.score = (
        result.win_rate * 40
        + result.avg_return * 100 * 30
        + min(result.trigger_count, 50) * 0.5
        - result.negative_triggers * 2
    )
    return result


# ---------------------------------------------------------------------------
# 参数网格
# ---------------------------------------------------------------------------

def pullback_grid() -> List[IntradayParams]:
    grid = []
    for pb_cf in [0.60, 0.65, 0.70, 0.75]:
        for vl in [0.4, 0.6, 0.7]:
            for vh in [1.2, 1.35, 1.5]:
                for sf in [0.999, 1.001, 1.002]:
                    for rb in [1.001, 1.003, 1.005]:
                        for nf in [0.980, 0.985, 0.990]:
                            grid.append(IntradayParams(
                                pullback_confidence_threshold=pb_cf,
                                volume_ratio_low=vl,
                                volume_ratio_high=vh,
                                support_factor=sf,
                                rebound_factor=rb,
                                not_far_factor=nf,
                            ))
    return grid


def breakout_grid(best_pb: IntradayParams) -> List[IntradayParams]:
    grid = []
    for bt_am in [0.60, 0.65, 0.68, 0.72]:
        for bt_pm in [0.68, 0.73, 0.78]:
            for vr_am in [1.2, 1.4, 1.6]:
                for vr_pm in [1.4, 1.6, 1.8]:
                    for cr in [0.020, 0.025, 0.030]:
                        grid.append(IntradayParams(
                            pullback_confidence_threshold=best_pb.pullback_confidence_threshold,
                            volume_ratio_low=best_pb.volume_ratio_low,
                            volume_ratio_high=best_pb.volume_ratio_high,
                            support_factor=best_pb.support_factor,
                            rebound_factor=best_pb.rebound_factor,
                            not_far_factor=best_pb.not_far_factor,
                            breakout_threshold_am=bt_am,
                            breakout_threshold_pm=bt_pm,
                            required_vol_ratio_am=vr_am,
                            required_vol_ratio_pm=vr_pm,
                            compact_range_max=cr,
                        ))
    return grid


def time_window_grid(best: IntradayParams) -> List[IntradayParams]:
    grid = []
    for ms in [time(9, 35), time(9, 45), time(9, 55), time(10, 0)]:
        for me in [time(14, 0), time(14, 10), time(14, 20)]:
            grid.append(IntradayParams(
                pullback_confidence_threshold=best.pullback_confidence_threshold,
                volume_ratio_low=best.volume_ratio_low,
                volume_ratio_high=best.volume_ratio_high,
                support_factor=best.support_factor,
                rebound_factor=best.rebound_factor,
                not_far_factor=best.not_far_factor,
                breakout_threshold_am=best.breakout_threshold_am,
                breakout_threshold_pm=best.breakout_threshold_pm,
                required_vol_ratio_am=best.required_vol_ratio_am,
                required_vol_ratio_pm=best.required_vol_ratio_pm,
                compact_range_max=best.compact_range_max,
                monitor_start=ms,
                monitor_end=me,
            ))
    return grid


# ---------------------------------------------------------------------------
# 搜索引擎
# ---------------------------------------------------------------------------

def search_phase(
    name: str,
    grid: List[IntradayParams],
    samples: List[SampleData],
    daily_conn: sqlite3.Connection,
    top_n: int = 10,
) -> List[EvalResult]:
    total = len(grid)
    _flush(f"\n{'='*60}")
    _flush(f"阶段: {name} | 参数组合数: {total}")
    _flush(f"{'='*60}")

    results: List[EvalResult] = []
    best_score = -999.0
    t0 = _time.time()

    for i, p in enumerate(grid):
        r = evaluate_params(samples, daily_conn, p)
        results.append(r)
        if r.score > best_score:
            best_score = r.score
        if (i + 1) % 50 == 0 or i + 1 == total:
            elapsed = _time.time() - t0
            rate = (i + 1) / elapsed if elapsed > 0 else 0
            eta = (total - i - 1) / rate if rate > 0 else 0
            _flush(
                f"  [{i+1}/{total}] 最优score={best_score:.2f} "
                f"速率={rate:.1f}组/秒 预计剩余={eta:.0f}秒"
            )

    results.sort(key=lambda x: x.score, reverse=True)
    best = results[0]
    _flush(
        f"\n  完成! 最优: score={best.score:.2f} 触发={best.trigger_count} "
        f"胜率={best.win_rate:.1%} 均收={best.avg_return:.2%}"
    )
    return results[:top_n]


# ---------------------------------------------------------------------------
# 报告
# ---------------------------------------------------------------------------

def format_comparison(base: EvalResult, best: EvalResult) -> str:
    lines = [
        "", "=" * 70, "  当前参数 vs 最优参数 对比", "=" * 70, "",
        f"  {'指标':<20} {'当前':>12} {'最优':>12} {'变化':>12}",
        "  " + "-" * 56,
    ]

    def row(label, v1, v2, fmt=".2f", pct=False):
        s1 = f"{v1:{fmt}}{'%' if pct else ''}"
        s2 = f"{v2:{fmt}}{'%' if pct else ''}"
        d = v2 - v1
        sd = f"{'+' if d > 0 else ''}{d:{fmt}}{'%' if pct else ''}"
        lines.append(f"  {label:<20} {s1:>12} {s2:>12} {sd:>12}")

    row("目标函数得分", base.score, best.score)
    row("触发信号数", base.trigger_count, best.trigger_count, ".0f")
    row("正收益信号", base.positive_triggers, best.positive_triggers, ".0f")
    row("负收益信号", base.negative_triggers, best.negative_triggers, ".0f")
    row("胜率", base.win_rate * 100, best.win_rate * 100, ".1f", True)
    row("T+2 均收", base.avg_return * 100, best.avg_return * 100, ".2f", True)

    lines.append("\n  参数变更:")
    bp, op = base.params, best.params
    changes = []
    for attr in [
        "pullback_confidence_threshold", "volume_ratio_low", "volume_ratio_high",
        "support_factor", "rebound_factor", "not_far_factor",
        "breakout_threshold_am", "breakout_threshold_pm",
        "required_vol_ratio_am", "required_vol_ratio_pm", "compact_range_max",
    ]:
        old, new = getattr(bp, attr), getattr(op, attr)
        if old != new:
            changes.append((attr, old, new))
    for attr in ["monitor_start", "monitor_end"]:
        old, new = getattr(bp, attr), getattr(op, attr)
        if old != new:
            changes.append((attr, old.strftime("%H:%M"), new.strftime("%H:%M")))

    if not changes:
        lines.append("    (无变化)")
    for name, old, new in changes:
        lines.append(f"    {name}: {old} -> {new}")
    lines.append("")
    return "\n".join(lines)


def save_report(base: EvalResult, best: EvalResult, top: List[EvalResult], out_dir: Path):
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = out_dir / f"param_optimization_{ts}.json"
    md_path = out_dir / f"param_optimization_{ts}.md"

    payload = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "baseline": {
            "score": round(base.score, 2), "trigger_count": base.trigger_count,
            "positive": base.positive_triggers, "negative": base.negative_triggers,
            "win_rate": round(base.win_rate, 4), "avg_return": round(base.avg_return, 6),
        },
        "best": {
            "score": round(best.score, 2), "trigger_count": best.trigger_count,
            "positive": best.positive_triggers, "negative": best.negative_triggers,
            "win_rate": round(best.win_rate, 4), "avg_return": round(best.avg_return, 6),
            "params": {
                "pullback_confidence_threshold": best.params.pullback_confidence_threshold,
                "volume_ratio_low": best.params.volume_ratio_low,
                "volume_ratio_high": best.params.volume_ratio_high,
                "support_factor": best.params.support_factor,
                "rebound_factor": best.params.rebound_factor,
                "not_far_factor": best.params.not_far_factor,
                "breakout_threshold_am": best.params.breakout_threshold_am,
                "breakout_threshold_pm": best.params.breakout_threshold_pm,
                "required_vol_ratio_am": best.params.required_vol_ratio_am,
                "required_vol_ratio_pm": best.params.required_vol_ratio_pm,
                "compact_range_max": best.params.compact_range_max,
                "monitor_start": best.params.monitor_start.strftime("%H:%M"),
                "monitor_end": best.params.monitor_end.strftime("%H:%M"),
            },
            "entries": best.entries,
        },
        "top_10": [
            {"rank": i + 1, "score": round(r.score, 2), "triggers": r.trigger_count,
             "win_rate": round(r.win_rate, 4), "avg_return": round(r.avg_return, 6),
             "label": r.params.label()}
            for i, r in enumerate(top[:10])
        ],
    }
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    comp = format_comparison(base, best)
    md = [
        "# 二次启动盘中参数优化报告", "",
        f"- 生成时间: {payload['generated_at']}",
        f"- 样本数: {base.total_samples}", "",
        comp, "",
        "## Top 10", "",
        "| # | 得分 | 触发 | 胜率 | T+2均收 | 参数 |",
        "| ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for i, r in enumerate(top[:10]):
        md.append(f"| {i+1} | {r.score:.2f} | {r.trigger_count} | {r.win_rate:.1%} | {r.avg_return:.2%} | {r.params.label()} |")

    if best.entries:
        md.extend(["", "## 最优参数买点明细", "",
                    "| 日期 | 股票 | 排名 | 时间 | 类型 | 价格 | T+2 |",
                    "| --- | --- | ---: | --- | --- | ---: | ---: |"])
        for e in best.entries:
            t2 = e.get("T+2_close_ret")
            md.append(
                f"| {e['signal_date']} | {e['name']} | {e['rank']} | "
                f"{e['entry_time']} | {e['signal_type']} | {e['entry_price']:.2f} | "
                f"{f'{t2:.2%}' if t2 is not None else '-'} |"
            )

    md_path.write_text("\n".join(md), encoding="utf-8")
    print(f"\nJSON: {json_path}")
    print(f"Markdown: {md_path}")


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description="二次启动盘中参数优化")
    parser.add_argument("--report-json", default="results/secondary_launch_recent_tracking_20260402_021443.json")
    parser.add_argument("--minute-db", default="data/history_recommendation.db")
    parser.add_argument("--daily-db", default="data/database/quant_system.db")
    args = parser.parse_args()

    report_path = ROOT / args.report_json
    if not report_path.exists():
        print(f"错误: {report_path} 不存在")
        return 1

    minute_db = HistoryRecommendationDB(str(ROOT / args.minute_db))
    daily_conn = sqlite3.connect(str(ROOT / args.daily_db))
    daily_conn.row_factory = sqlite3.Row

    _flush("预加载样本数据...")
    t0 = _time.time()
    samples = preload_samples(report_path, minute_db)
    _flush(f"  耗时: {_time.time() - t0:.1f}秒\n")

    _flush("评估 baseline...")
    base = evaluate_params(samples, daily_conn, BASELINE)
    _flush(f"  Baseline: score={base.score:.2f} 触发={base.trigger_count} 胜率={base.win_rate:.1%} 均收={base.avg_return:.2%}")

    # 阶段1: 回踩 (972组)
    pb = pullback_grid()
    pb_top = search_phase("回踩参数搜索", pb, samples, daily_conn)
    best_pb = pb_top[0].params

    # 阶段2: 突破 (324组)
    bo = breakout_grid(best_pb)
    bo_top = search_phase("突破参数搜索", bo, samples, daily_conn)
    best_bo = bo_top[0].params

    # 阶段3: 时间窗 (12组)
    tw = time_window_grid(best_bo)
    tw_top = search_phase("时间窗微调", tw, samples, daily_conn)
    final = tw_top[0]

    print(format_comparison(base, final))

    out_dir = ROOT / "results"
    out_dir.mkdir(exist_ok=True)
    save_report(base, final, tw_top, out_dir)

    daily_conn.close()
    print("\n优化完成!")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
