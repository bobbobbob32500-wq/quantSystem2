# -*- coding: utf-8 -*-
"""
突破策略日线回测循环（与 run_breakout_daily_backtest_report 口径一致），供报告与参数网格复用。
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

import numpy as np
import pandas as pd

from src.modules.breakout_strategy import BreakoutStrategy


def _build_price_map(features: pd.DataFrame) -> Dict[str, pd.DataFrame]:
    price_df = features[["ts_code", "trade_date", "open", "close"]].copy()
    price_df = price_df.sort_values(["ts_code", "trade_date"]).reset_index(drop=True)
    price_map: Dict[str, pd.DataFrame] = {}
    for code, sub in price_df.groupby("ts_code"):
        sub = sub.sort_values("trade_date").reset_index(drop=True)
        sub = sub.copy()
        sub["date_str"] = sub["trade_date"].dt.strftime("%Y%m%d")
        price_map[code] = sub
    return price_map


def run_breakout_backtest_loop(
    strategy: BreakoutStrategy,
    features: pd.DataFrame,
    all_dates: List[str],
    signal_dates: List[str],
    use_ma120: bool,
    progress_every: int = 0,
) -> Tuple[pd.DataFrame, pd.DataFrame, Dict[str, int]]:
    """
    对给定 signal_dates 子集跑完整选股→T+1 确认→收益计算。

    Returns:
        trades_df: 成交明细（含 ret_t1~3 等）
        funnel_df: 逐日漏斗
        gate_stats: {"normal","caution","stop"}
    """
    price_map = _build_price_map(features)
    date_pos = {d: i for i, d in enumerate(all_dates)}
    all_trades: List[dict] = []
    funnel_rows: List[dict] = []
    gate_stats = {"normal": 0, "caution": 0, "stop": 0}

    for i, td in enumerate(signal_dates):
        if progress_every and (i + 1) % progress_every == 0:
            print(f"  进度 {i+1}/{len(signal_dates)}", flush=True)
        fr: Dict[str, Any] = {
            "signal_date": td,
            "stage": "",
            "watchlist_n": 0,
            "confirmed_n": 0,
            "gate": "",
        }

        snapshot = strategy._build_snapshot(features, td)
        if snapshot.empty:
            fr["stage"] = "无截面"
            funnel_rows.append(fr)
            continue

        filtered = strategy._layer_base_filter(snapshot)
        if filtered.empty:
            fr["stage"] = "基础过滤后为空"
            funnel_rows.append(fr)
            continue

        if use_ma120:
            filtered = strategy._layer_trend_filter(filtered)
        else:
            cond = (
                filtered["ma20"].notna()
                & filtered["ma60"].notna()
                & (filtered["ma20"] > filtered["ma60"])
                & (filtered["ma20_slope"].fillna(-1) > 0)
            )
            filtered = filtered.loc[cond].copy()
        if filtered.empty:
            fr["stage"] = "趋势过滤后为空"
            funnel_rows.append(fr)
            continue

        filtered = strategy._layer_strength_filter(filtered)
        if filtered.empty:
            fr["stage"] = "强度过滤后为空"
            funnel_rows.append(fr)
            continue

        if use_ma120:
            filtered = strategy._layer_stability_filter(filtered)
        else:
            p = strategy.params
            cond = filtered["box_range"].notna() & (filtered["box_range"] <= p.box_max_range)
            if filtered["atr_ratio_q60"].notna().mean() > 0.3:
                cond = cond & (filtered["atr_ratio_q60"].fillna(0.5) <= p.atr_quantile_max)
            filtered = filtered.loc[cond].copy()
        if filtered.empty:
            fr["stage"] = "走稳过滤后为空"
            funnel_rows.append(fr)
            continue

        scored = strategy._compute_scores(filtered)
        min_score, top_k = strategy._market_gate(features, td)

        if min_score >= 999 or top_k <= 0:
            gate_stats["stop"] += 1
            fr["stage"] = "闸门禁止"
            fr["gate"] = "stop"
            funnel_rows.append(fr)
            continue
        if min_score > strategy.params.min_signal_score:
            gate_stats["caution"] += 1
            fr["gate"] = "caution"
        else:
            gate_stats["normal"] += 1
            fr["gate"] = "normal"

        scored = scored[scored["signal_score"] >= min_score].copy()
        if scored.empty:
            fr["stage"] = "评分后为空"
            funnel_rows.append(fr)
            continue
        scored = scored.sort_values("signal_score", ascending=False).head(top_k)

        pos = date_pos.get(td)
        if pos is None or pos + 1 >= len(all_dates):
            fr["stage"] = "无下一交易日"
            funnel_rows.append(fr)
            continue
        next_d = all_dates[pos + 1]
        confirm_map = strategy.bars_dict_for_trade_date(features, next_d)
        watch_items = strategy._to_watch_items(scored, td)
        fr["watchlist_n"] = len(watch_items)
        confirmed = strategy.confirm_breakout_daily(watch_items, confirm_map)
        fr["confirmed_n"] = len(confirmed)
        if not confirmed:
            fr["stage"] = "无突破确认"
            funnel_rows.append(fr)
            continue

        fr["stage"] = "有确认成交"
        funnel_rows.append(fr)

        for sig in confirmed:
            code = sig.ts_code
            sub = price_map.get(code)
            if sub is None:
                continue
            match_idx = sub.index[sub["date_str"] == sig.confirm_date]
            if len(match_idx) == 0:
                continue
            confirm_idx = int(match_idx[0])
            entry_price = float(sig.entry_price)
            if entry_price <= 0:
                continue
            open_px = float(sub.loc[confirm_idx, "open"])
            if open_px <= 0:
                open_px = float("nan")

            match_scored = scored.loc[scored["ts_code"] == code]
            if match_scored.empty:
                rs_q = atr_q = box_r = 0.0
            else:
                r0 = match_scored.iloc[0]
                rs_q = float(r0.get("rs20_xsec_q", 0) or 0)
                atr_q = float(r0.get("atr_ratio_q60", 0) or 0)
                box_r = float(r0.get("box_range", 0) or 0)

            trade_record = {
                "signal_date": td,
                "confirm_date": sig.confirm_date,
                "ts_code": code,
                "name": sig.name,
                "industry": getattr(sig, "industry", "") or "",
                "signal_score": float(sig.signal_score),
                "rs20_xsec_q": rs_q,
                "atr_ratio_q60": atr_q,
                "box_range": box_r,
                "pivot": float(sig.pivot),
                "entry_price": entry_price,
                "confirm_open": open_px,
                "stop_loss": float(sig.stop_loss),
                "signal_grade": sig.signal_grade,
                "volume_ratio": float(sig.volume_ratio),
            }
            for hold_n in [1, 2, 3, 4, 5]:
                target_idx = confirm_idx + hold_n
                if target_idx < len(sub):
                    exit_close = float(sub.loc[target_idx, "close"])
                    trade_record[f"ret_t{hold_n}"] = exit_close / entry_price - 1.0
                    if pd.notna(open_px) and open_px > 0:
                        trade_record[f"ret_t{hold_n}_open"] = exit_close / open_px - 1.0
                    else:
                        trade_record[f"ret_t{hold_n}_open"] = np.nan
                else:
                    trade_record[f"ret_t{hold_n}"] = np.nan
                    trade_record[f"ret_t{hold_n}_open"] = np.nan
            all_trades.append(trade_record)

    trades_df = pd.DataFrame(all_trades)
    funnel_df = pd.DataFrame(funnel_rows)
    return trades_df, funnel_df, gate_stats


def run_watchlist_open_backtest_loop(
    strategy: BreakoutStrategy,
    features: pd.DataFrame,
    all_dates: List[str],
    signal_dates: List[str],
    use_ma120: bool,
    progress_every: int = 0,
) -> Tuple[pd.DataFrame, pd.DataFrame, Dict[str, int]]:
    """
    原策略「仅选股」日线回测：T 日收盘后选股入池，假设 T+1 日**开盘价**买入，
    持有至 T+1 / T+2 / T+3 **收盘价** 的收益率（相对 T+1 开盘价）。

    与突破确认回测的区别：不要求 T+1 突破 pivot，凡进入当日观察池即计入样本。

    收益定义：
      - ret_t1 = close(T+1) / open(T+1) - 1
      - ret_t2 = close(T+2) / open(T+1) - 1
      - ret_t3 = close(T+3) / open(T+1) - 1
      - ret_t4 = close(T+4) / open(T+1) - 1
      - ret_t5 = close(T+5) / open(T+1) - 1
    """
    price_map = _build_price_map(features)
    date_pos = {d: i for i, d in enumerate(all_dates)}
    idx_code = str(strategy.params.index_code)
    all_trades: List[dict] = []
    funnel_rows: List[dict] = []
    gate_stats = {"normal": 0, "caution": 0, "stop": 0}

    for i, td in enumerate(signal_dates):
        if progress_every and (i + 1) % progress_every == 0:
            print(f"  进度 {i+1}/{len(signal_dates)}", flush=True)
        fr: Dict[str, Any] = {
            "signal_date": td,
            "stage": "",
            "watchlist_n": 0,
            "gate": "",
        }

        snapshot = strategy._build_snapshot(features, td)
        if snapshot.empty:
            fr["stage"] = "无截面"
            funnel_rows.append(fr)
            continue

        filtered = strategy._layer_base_filter(snapshot)
        if filtered.empty:
            fr["stage"] = "基础过滤后为空"
            funnel_rows.append(fr)
            continue

        if use_ma120:
            filtered = strategy._layer_trend_filter(filtered)
        else:
            cond = (
                filtered["ma20"].notna()
                & filtered["ma60"].notna()
                & (filtered["ma20"] > filtered["ma60"])
                & (filtered["ma20_slope"].fillna(-1) > 0)
            )
            filtered = filtered.loc[cond].copy()
        if filtered.empty:
            fr["stage"] = "趋势过滤后为空"
            funnel_rows.append(fr)
            continue

        filtered = strategy._layer_strength_filter(filtered)
        if filtered.empty:
            fr["stage"] = "强度过滤后为空"
            funnel_rows.append(fr)
            continue

        if use_ma120:
            filtered = strategy._layer_stability_filter(filtered)
        else:
            p = strategy.params
            cond = filtered["box_range"].notna() & (filtered["box_range"] <= p.box_max_range)
            if filtered["atr_ratio_q60"].notna().mean() > 0.3:
                cond = cond & (filtered["atr_ratio_q60"].fillna(0.5) <= p.atr_quantile_max)
            filtered = filtered.loc[cond].copy()
        if filtered.empty:
            fr["stage"] = "走稳过滤后为空"
            funnel_rows.append(fr)
            continue

        scored = strategy._compute_scores(filtered)
        min_score, top_k = strategy._market_gate(features, td)

        if min_score >= 999 or top_k <= 0:
            gate_stats["stop"] += 1
            fr["stage"] = "闸门禁止"
            fr["gate"] = "stop"
            funnel_rows.append(fr)
            continue
        if min_score > strategy.params.min_signal_score:
            gate_stats["caution"] += 1
            fr["gate"] = "caution"
        else:
            gate_stats["normal"] += 1
            fr["gate"] = "normal"

        scored = scored[scored["signal_score"] >= min_score].copy()
        if scored.empty:
            fr["stage"] = "评分后为空"
            funnel_rows.append(fr)
            continue
        scored = scored.sort_values("signal_score", ascending=False).head(top_k)

        pos = date_pos.get(td)
        if pos is None or pos + 1 >= len(all_dates):
            fr["stage"] = "无下一交易日"
            funnel_rows.append(fr)
            continue
        next_d = all_dates[pos + 1]
        watch_items = strategy._to_watch_items(scored, td)
        fr["watchlist_n"] = len(watch_items)
        fr["stage"] = "有观察池"
        funnel_rows.append(fr)

        for item in watch_items:
            code = item.ts_code
            if str(code) == idx_code:
                continue
            sub = price_map.get(code)
            if sub is None:
                continue
            match_idx = sub.index[sub["date_str"] == str(next_d)]
            if len(match_idx) == 0:
                continue
            t1_idx = int(match_idx[0])
            entry_open = float(sub.loc[t1_idx, "open"])
            if entry_open <= 0 or not np.isfinite(entry_open):
                continue

            match_scored = scored.loc[scored["ts_code"] == code]
            if match_scored.empty:
                rs_q = atr_q = box_r = 0.0
            else:
                r0 = match_scored.iloc[0]
                rs_q = float(r0.get("rs20_xsec_q", 0) or 0)
                atr_q = float(r0.get("atr_ratio_q60", 0) or 0)
                box_r = float(r0.get("box_range", 0) or 0)

            trade_record: Dict[str, Any] = {
                "signal_date": td,
                "buy_date": str(next_d),
                "ts_code": code,
                "name": item.name,
                "industry": getattr(item, "industry", "") or "",
                "signal_score": float(item.signal_score),
                "rs20_xsec_q": rs_q,
                "atr_ratio_q60": atr_q,
                "box_range": box_r,
                "entry_open": round(entry_open, 4),
            }
            for hn, off in [(1, 0), (2, 1), (3, 2), (4, 3), (5, 4)]:
                j = t1_idx + off
                if j < len(sub):
                    cx = float(sub.loc[j, "close"])
                    trade_record[f"ret_t{hn}"] = cx / entry_open - 1.0
                else:
                    trade_record[f"ret_t{hn}"] = np.nan
            all_trades.append(trade_record)

    trades_df = pd.DataFrame(all_trades)
    funnel_df = pd.DataFrame(funnel_rows)
    return trades_df, funnel_df, gate_stats


def summarize_t1_metrics(trades_df: pd.DataFrame) -> Dict[str, float]:
    """单笔 T+1（触发价）与等权按信号日聚合的简要指标。"""
    out: Dict[str, float] = {
        "n_trades": 0.0,
        "win_rate": float("nan"),
        "mean_ret": float("nan"),
        "pf": float("nan"),
        "port_total_ret": float("nan"),
        "port_mdd": float("nan"),
        "port_sharpe": float("nan"),
    }
    if trades_df is None or trades_df.empty or "ret_t1" not in trades_df.columns:
        return out
    v = trades_df["ret_t1"].dropna()
    if v.empty:
        return out
    out["n_trades"] = float(len(v))
    out["win_rate"] = float((v > 0).mean())
    out["mean_ret"] = float(v.mean())
    gw = float(v[v > 0].sum())
    gl = float(-v[v < 0].sum())
    out["pf"] = gw / gl if gl > 1e-12 else 0.0

    dr = trades_df.groupby("signal_date")["ret_t1"].mean().dropna().sort_index()
    if dr.empty:
        return out
    eq = (1.0 + dr).cumprod()
    out["port_total_ret"] = float(eq.iloc[-1] - 1.0)
    out["port_mdd"] = float((eq / eq.cummax() - 1.0).min())
    out["port_sharpe"] = (
        float(dr.mean() / dr.std() * np.sqrt(252)) if dr.std() > 1e-12 else 0.0
    )
    return out


def summarize_ret_column(trades_df: pd.DataFrame, col: str) -> Dict[str, float]:
    """单笔收益率列的胜率、均值、PF 及按 signal_date 等权组合的近似指标。"""
    out: Dict[str, float] = {
        "n_trades": 0.0,
        "win_rate": float("nan"),
        "mean_ret": float("nan"),
        "pf": float("nan"),
        "port_total_ret": float("nan"),
        "port_mdd": float("nan"),
        "port_sharpe": float("nan"),
    }
    if trades_df is None or trades_df.empty or col not in trades_df.columns:
        return out
    v = trades_df[col].dropna()
    if v.empty:
        return out
    out["n_trades"] = float(len(v))
    out["win_rate"] = float((v > 0).mean())
    out["mean_ret"] = float(v.mean())
    gw = float(v[v > 0].sum())
    gl = float(-v[v < 0].sum())
    out["pf"] = gw / gl if gl > 1e-12 else 0.0

    if "signal_date" not in trades_df.columns:
        return out
    dr = trades_df.groupby("signal_date")[col].mean().dropna().sort_index()
    if dr.empty:
        return out
    eq = (1.0 + dr).cumprod()
    out["port_total_ret"] = float(eq.iloc[-1] - 1.0)
    out["port_mdd"] = float((eq / eq.cummax() - 1.0).min())
    out["port_sharpe"] = (
        float(dr.mean() / dr.std() * np.sqrt(252)) if dr.std() > 1e-12 else 0.0
    )
    return out
