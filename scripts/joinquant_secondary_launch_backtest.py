# -*- coding: utf-8 -*-
"""
聚宽平台回测脚本：沪深主板「强势回调缩量二次启动」策略（日线版，去集合竞价过滤）

【使用说明】
1. 在 https://www.joinquant.com 研究环境新建策略，将本文件全文粘贴替换默认代码。
2. 需开通聚宽数据权限（jqdata）；回测周期、初始资金在网页端设置。
3. 盘中确认（use_intraday_confirm=True）依赖「分钟」频率回测；若选「每日」频率，请设 use_intraday_confirm=False，否则 handle_data 无法按分钟触发。
4. 逻辑对齐本仓库：
   - 日线：mainboard_secondary_launch_strategy.py + mainboard_secondary_launch_backtester.py
   - 盘中（可选）：secondary_launch_intraday.py（回踩确认 / 平台突破 / 日线闸门 / 监控时段）
5. 默认参数侧重「低频、高门槛」：提高得分与冷却、收紧盘中/日线闸门、单笔最小建仓市值，以压换手并改善胜率和盈亏比；若样本过少可略放宽 min_score / intraday_pullback_confidence_min。

【免责声明】
回测结果不代表实盘表现；注意滑点、停牌、涨跌停无法成交等现实约束。
"""

from datetime import datetime
from datetime import time as dt_time  # jqdata 的 import * 会覆盖名 time，必须用别名
from typing import Any, Dict, Optional, Tuple

import numpy as np
import pandas as pd

# 聚宽云端必有 jqdata；本地未安装时跳过以便语法检查
try:
    from jqdata import *  # noqa: F401,F403
except ImportError:
    pass


# ---------------------------------------------------------------------------
# 与仓库 StrategyParams 保持一致的默认参数（可按需微调）
# ---------------------------------------------------------------------------
class StrategyParams:
    def __init__(self):
        self.min_list_days = 60
        self.limit_up_threshold = 9.7
        self.limit_down_threshold = -9.7
        self.limit_up_count_10_min = 1
        self.limit_up_count_10_max = 3
        self.last_limit_up_days_min = 1
        self.last_limit_up_days_max = 8
        self.drawdown_min = 0.01
        # 略收紧：减少「深跌中继」混入二次启动池
        self.drawdown_max = 0.10
        self.vol_shrink_ratio = 0.92
        self.close_ma5_dev_max = 0.03
        self.close_ma10_min_ratio = 0.99
        # 仓库 StrategyParams 中 amount 与 Tushare 一致为「千元」；聚宽 get_price 的 money 为「元」
        # 此处必须换算为元再与 amt_ma20 比较，否则会误用 5e6 元≈500 万上限，主板几乎全被过滤、无交易
        self.min_amt_ma20 = 1e5 * 1000.0
        self.max_amt_ma20 = 5e6 * 1000.0
        self.min_price = 3.0
        self.limit_up_amt_ratio_min = 0.6
        self.limit_up_amt_ratio_max = 3.5
        self.rs_lookback = 20
        # 少而精：压缩池子、拉长冷却，降低换手
        self.max_candidates = 8
        self.picks_per_day = 1
        self.min_score = 62.0
        self.cooldown_days = 12
        # 上证 5 日收益 ≤ 阈值视为弱市；-1.5% 比 -2% 更早停手，略减逆势单
        self.weak_market_ret5_threshold = -0.015
        self.weak_market_min_score_boost = 8.0
        self.weak_market_max_picks = 1
        # 弱市（上证 5 日收益低于阈值）时直接 0 只，不交易
        self.weak_market_zero_picks = True
        self.second_pick_min_score = 85.0
        self.second_pick_score_gap = 8.0
        # True：仅当分钟线触发回踩/突破确认后买入（对齐系统盘中路由）；False：延续开盘即建仓
        self.use_intraday_confirm = True
        # 盘中回踩置信度：再抬高以减少触发次数、偏胜率
        self.intraday_pullback_confidence_min = 0.72
        # 日线形态闸门：量比/上影线略收紧
        self.daily_gate_vol_ratio_max = 1.15
        self.daily_gate_upper_shadow_max = 48.0
        # 单笔最小目标市值（元）：低于则当日不买该标的，避免碎单、最低佣金拖累盈亏比
        self.min_entry_value = 12000.0


def _is_mainboard_jq(code: str) -> bool:
    """聚宽代码如 600000.XSHG / 000001.XSHE"""
    c = code.split(".")[0]
    return c.startswith(("600", "601", "603", "605", "000", "001", "002"))


def _is_risk_name(name: str) -> bool:
    if not isinstance(name, str):
        return False
    n = name.upper()
    return ("ST" in n) or ("*ST" in n) or ("退" in name)


def _bounded_score(series: pd.Series, target_min: float, target_max: float) -> pd.Series:
    values = series.astype(float)
    score = pd.Series(1.0, index=values.index, dtype=float)
    score = score.mask(
        values < target_min, 1.0 - (target_min - values).clip(lower=0.0) / max(target_min, 1e-6)
    )
    score = score.mask(
        values > target_max, 1.0 - (values - target_max).clip(lower=0.0) / max(target_max, 1e-6)
    )
    return score.clip(lower=0.0, upper=1.0)


def _last_limit_up_days_array(trade_dates: np.ndarray, is_limit_up: np.ndarray) -> np.ndarray:
    """与仓库 _last_limit_up_days 等价（向量化循环）"""
    n = len(trade_dates)
    days = np.full(n, np.nan)
    last_idx = None
    for i in range(n):
        if last_idx is not None:
            days[i] = (np.datetime64(trade_dates[i], "D") - np.datetime64(trade_dates[last_idx], "D")).astype(int)
        if is_limit_up[i]:
            last_idx = i
    return days


def _fill_limit_up_meta(close: np.ndarray, is_up: np.ndarray, amt: np.ndarray, amt20: np.ndarray):
    """涨停日量能比、涨停次日收益（与仓库循环一致）"""
    n = len(close)
    limit_up_amt_ratio = np.full(n, np.nan)
    next_ret_after_limit_up = np.full(n, np.nan)
    last_up_i = None
    for i in range(n):
        if last_up_i is not None:
            base = amt20[last_up_i]
            if base and base > 0:
                limit_up_amt_ratio[i] = float(amt[last_up_i] / base)
            if last_up_i + 1 < n:
                next_ret_after_limit_up[i] = float(close[last_up_i + 1] / close[last_up_i] - 1.0)
        if is_up[i]:
            last_up_i = i
    return limit_up_amt_ratio, next_ret_after_limit_up


def _fill_drawdown_from_peak(close: np.ndarray, is_up: np.ndarray) -> np.ndarray:
    n = len(close)
    out = np.full(n, np.nan)
    last_up_i = None
    for i in range(n):
        if is_up[i]:
            last_up_i = i
        if last_up_i is not None and i > last_up_i:
            peak = float(np.max(close[last_up_i : i + 1]))
            if peak > 0:
                out[i] = 1.0 - float(close[i] / peak)
    return out


def prepare_single_stock_features(
    df: pd.DataFrame, p: StrategyParams, name: str, list_days: int
) -> Optional[Dict]:
    """
    df: index 为日期，列含 open, close, high, low, volume, money（聚宽日线 money=成交额）
    返回：截至最后一根 K 线的特征字典；数据不足则 None
    """
    need = max(60, p.rs_lookback + 5, 25)
    if len(df) < need:
        return None

    df = df.sort_index()
    c = df["close"].astype(float)
    o = df["open"].astype(float)
    h = df["high"].astype(float)
    low = df["low"].astype(float)
    vol = df["volume"].astype(float)
    amt = df["money"].astype(float)

    ret_1d = c.pct_change()
    ma5 = c.rolling(5).mean()
    ma10 = c.rolling(10).mean()
    vol_ma5 = vol.rolling(5).mean()
    vol_ma20 = vol.rolling(20).mean()
    amt_ma20 = amt.rolling(20).mean()
    rs20 = c / c.shift(p.rs_lookback) - 1.0
    ret5 = c / c.shift(5) - 1.0

    pct_chg = ret_1d * 100.0
    is_limit_up = (pct_chg >= p.limit_up_threshold) & (c >= h * 0.999)
    is_limit_down = (pct_chg <= p.limit_down_threshold) & (c <= low * 1.001)
    limit_up_count_10 = is_limit_up.astype(float).rolling(10).sum()
    limit_down_count_20 = is_limit_down.astype(float).rolling(20).sum()

    idx_arr = df.index.values
    is_up_arr = is_limit_up.values
    days_since = _last_limit_up_days_array(idx_arr, is_up_arr)

    amt_arr = amt.values
    amt20_arr = amt_ma20.values
    close_arr = c.values
    limit_up_amt_ratio, next_ret_after_limit_up = _fill_limit_up_meta(
        close_arr, is_up_arr, amt_arr, amt20_arr
    )
    drawdown_from_peak = _fill_drawdown_from_peak(close_arr, is_up_arr)

    i = -1
    return {
        "name": name,
        "list_days": float(list_days),
        "vol": float(vol.iloc[i]),
        "close": float(c.iloc[i]),
        "amt_ma20": float(amt_ma20.iloc[i]) if not np.isnan(amt_ma20.iloc[i]) else np.nan,
        "limit_down_count_20": float(limit_down_count_20.iloc[i]),
        "limit_up_count_10": float(limit_up_count_10.iloc[i]),
        "days_since_last_limit_up": float(days_since[i]),
        "drawdown_from_peak": float(drawdown_from_peak[i]) if not np.isnan(drawdown_from_peak[i]) else np.nan,
        "vol_ma5": float(vol_ma5.iloc[i]),
        "vol_ma20": float(vol_ma20.iloc[i]),
        "ma5": float(ma5.iloc[i]),
        "ma10": float(ma10.iloc[i]),
        "is_limit_up": bool(is_limit_up.iloc[i]),
        "rs20": float(rs20.iloc[i]) if not np.isnan(rs20.iloc[i]) else np.nan,
        "limit_up_amt_ratio": float(limit_up_amt_ratio[i]) if not np.isnan(limit_up_amt_ratio[i]) else np.nan,
        "next_ret_after_limit_up": (
            float(next_ret_after_limit_up[i])
            if not np.isnan(next_ret_after_limit_up[i])
            else np.nan
        ),
        "ret5": float(ret5.iloc[i]) if not np.isnan(ret5.iloc[i]) else 0.0,
        # 供 secondary_launch_intraday 日线形态闸门（与仓库 _check_daily_profile_gate 字段一致）
        "pct_chg": float(ret_1d.iloc[i] * 100.0) if not np.isnan(ret_1d.iloc[i]) else 0.0,
        "open": float(o.iloc[i]),
        "high": float(h.iloc[i]),
        "low": float(low.iloc[i]),
        "close": float(c.iloc[i]),
        "vol": float(vol.iloc[i]),
        "vol_ma5": float(vol_ma5.iloc[i]),
    }


def base_filter_row(row: dict, p: StrategyParams) -> bool:
    if row.get("list_days", 0) < p.min_list_days:
        return False
    if row["vol"] <= 0 or row["close"] < p.min_price:
        return False
    am = row.get("amt_ma20")
    if am is None or np.isnan(am) or am < p.min_amt_ma20 or am > p.max_amt_ma20:
        return False
    if row["limit_down_count_20"] > 1:
        return False
    if row["limit_up_count_10"] < 1:
        return False
    ds = row.get("days_since_last_limit_up")
    if np.isnan(ds) or ds < p.last_limit_up_days_min or ds > p.last_limit_up_days_max:
        return False
    dd = row.get("drawdown_from_peak")
    if dd is None or np.isnan(dd) or dd < p.drawdown_min or dd > p.drawdown_max:
        return False
    if row["close"] < row["ma10"] * p.close_ma10_min_ratio:
        return False
    if row["ma5"] < row["ma10"] * 0.998:
        return False
    if row["is_limit_up"]:
        return False
    return True


def score_row(row: dict, p: StrategyParams, rs_rank: float) -> float:
    """单票打分（与 _score_candidates 公式一致；rs_rank 需在全市场候选内预先算分位）"""
    limit_up_count_score = _bounded_score(
        pd.Series([row["limit_up_count_10"]]), float(p.limit_up_count_10_min), float(p.limit_up_count_10_max)
    ).iloc[0]
    last_limit_up_score = _bounded_score(
        pd.Series([row.get("days_since_last_limit_up", 99.0)]),
        float(p.last_limit_up_days_min),
        float(p.last_limit_up_days_max),
    ).iloc[0]
    drawdown_score = _bounded_score(
        pd.Series([row.get("drawdown_from_peak", 1.0)]), float(p.drawdown_min), float(p.drawdown_max)
    ).iloc[0]

    vol_ma5 = max(row["vol_ma5"], 1e-9)
    volume_ratio = row["vol"] / vol_ma5
    if volume_ratio is None:
        volume_ratio = 1.5
    elif isinstance(volume_ratio, float) and np.isnan(volume_ratio):
        volume_ratio = 1.5

    shrink_target = float(p.vol_shrink_ratio)
    raw_shrink = 1.0 - (max(0.0, volume_ratio - shrink_target) / max(1.0 - shrink_target, 1e-6))
    volume_shrink_score = float(np.clip(raw_shrink, 0.0, 1.0))

    ma5_dev = abs(row["close"] / row["ma5"] - 1.0)
    raw_ma5 = 1.0 - (ma5_dev / max(float(p.close_ma5_dev_max), 1e-6))
    ma5_dev_score = float(np.clip(raw_ma5, 0.0, 1.0))

    trend_score = 0.6 * float(row["ma5"] > row["ma10"]) + 0.4 * float(row["close"] >= row["ma10"])
    vtr = row["vol_ma5"] / max(row["vol_ma20"], 1e-9)
    raw_vtr = (vtr - 0.8) / 0.4
    volume_trend_score = float(np.clip(raw_vtr, 0.0, 1.0))

    lur = row.get("limit_up_amt_ratio")
    if lur is None or np.isnan(lur):
        lur = 0.0
    limit_up_amt_score = _bounded_score(
        pd.Series([lur]), float(p.limit_up_amt_ratio_min), float(p.limit_up_amt_ratio_max)
    ).iloc[0]

    nr = row.get("next_ret_after_limit_up")
    if nr is None or np.isnan(nr):
        nr = 0.0
    raw_nr = (nr + 0.06) / 0.16
    next_ret_score = float(np.clip(raw_nr, 0.0, 1.0))

    return float(
        rs_rank * 24.0
        + limit_up_count_score * 10.0
        + last_limit_up_score * 16.0
        + drawdown_score * 18.0
        + volume_shrink_score * 8.0
        + ma5_dev_score * 12.0
        + trend_score * 6.0
        + volume_trend_score * 3.0
        + limit_up_amt_score * 2.0
        + next_ret_score * 5.0
    )


def get_index_ret5(context) -> float:
    """上证指数 5 日涨跌幅（用于弱市闸门）"""
    try:
        idx = get_price(
            "000001.XSHG",
            end_date=context.previous_date,
            count=10,
            frequency="daily",
            fields=["close"],
            skip_paused=True,
            fq="pre",
        )
        if idx is None or len(idx) < 6:
            return 0.0
        c = idx["close"].astype(float)
        return float(c.iloc[-1] / c.iloc[-6] - 1.0)
    except Exception:
        return 0.0


def get_market_gate(ret5: float, p: StrategyParams) -> Tuple[float, int]:
    effective_min_score = float(p.min_score)
    effective_picks = int(p.picks_per_day)
    if ret5 <= float(p.weak_market_ret5_threshold):
        effective_min_score += float(p.weak_market_min_score_boost)
        if getattr(p, "weak_market_zero_picks", False):
            effective_picks = 0
        else:
            effective_picks = min(effective_picks, int(p.weak_market_max_picks))
    return effective_min_score, effective_picks


def refine_daily_picks(day_df: pd.DataFrame, p: StrategyParams) -> pd.DataFrame:
    """第二名质量过滤（与 _refine_daily_picks 一致）"""
    if day_df.empty:
        return day_df
    day_df = day_df.sort_values(["signal_score", "rs20"], ascending=[False, False]).copy()
    if len(day_df) <= 1:
        return day_df
    first_row = day_df.iloc[0]
    keep = [first_row]
    for idx in range(1, len(day_df)):
        row = day_df.iloc[idx]
        gap = float(first_row["signal_score"]) - float(row["signal_score"])
        if float(row["signal_score"]) < float(p.second_pick_min_score):
            continue
        if gap > float(p.second_pick_score_gap):
            continue
        keep.append(row)
    return pd.DataFrame(keep)


# ---------------------------------------------------------------------------
# 盘中买点：移植自 src/modules/secondary_launch_intraday.py（与系统路由对齐）
# ---------------------------------------------------------------------------
class _SignalOutput:
    __slots__ = ("signal", "signal_type", "confidence", "reason", "details")

    def __init__(
        self,
        signal: bool,
        signal_type: str,
        confidence: float,
        reason: str,
        details: Optional[Dict[str, Any]] = None,
    ):
        self.signal = bool(signal)
        self.signal_type = signal_type or ""
        self.confidence = float(confidence or 0.0)
        self.reason = reason or ""
        self.details = dict(details or {})


def _jq_resolve_market_gate(market_confirm: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    payload = market_confirm or {}
    raw_score = payload.get("market_score", payload.get("score", 50.0))
    try:
        market_score = float(raw_score or 50.0)
    except (TypeError, ValueError):
        market_score = 50.0
    trend = str(payload.get("trend", payload.get("level", "neutral")) or "neutral").lower()
    index_below_vwap = bool(payload.get("index_below_vwap", False))
    weak_market = (
        market_score < 45.0
        or trend in {"down", "weak", "poor", "defensive", "bear"}
        or index_below_vwap
    )
    return {
        "market_score": market_score,
        "trend": trend,
        "index_below_vwap": index_below_vwap,
        "weak_market": weak_market,
        "label": "偏弱" if weak_market else "正常",
    }


def _jq_resolve_breakout_threshold(now: datetime, market_gate: Dict[str, Any]) -> float:
    threshold = 0.68 if now.time() >= dt_time(13, 30) else 0.60
    if market_gate.get("weak_market"):
        threshold += 0.05
    return threshold


def _jq_resolve_series(df: pd.DataFrame, *candidates: str) -> Optional[pd.Series]:
    for name in candidates:
        if name in df.columns:
            return pd.to_numeric(df[name], errors="coerce")
    return None


def _jq_resolve_timestamp_series(df: pd.DataFrame) -> pd.Series:
    for name in ("timestamp", "datetime", "time", "trade_time"):
        if name in df.columns:
            return pd.to_datetime(df[name], errors="coerce")
    return pd.Series(pd.NaT, index=df.index)


def _jq_prepare_minute_frame(minute_df: Optional[pd.DataFrame]) -> pd.DataFrame:
    if minute_df is None or minute_df.empty:
        return pd.DataFrame()

    df = minute_df.copy()
    if "timestamp" not in df.columns:
        df = df.reset_index()
        first_col = df.columns[0]
        if first_col not in ("open", "close", "high", "low", "volume"):
            df.rename(columns={first_col: "timestamp"}, inplace=True)

    price = _jq_resolve_series(df, "close", "price", "last")
    high = _jq_resolve_series(df, "high")
    low = _jq_resolve_series(df, "low")
    open_ = _jq_resolve_series(df, "open")
    volume = _jq_resolve_series(df, "volume", "vol")
    ts = _jq_resolve_timestamp_series(df)

    prepared = pd.DataFrame(
        {
            "timestamp": ts,
            "open": open_ if open_ is not None else price,
            "high": high if high is not None else price,
            "low": low if low is not None else price,
            "close": price,
            "volume": volume if volume is not None else 0.0,
        }
    ).dropna(subset=["close"])
    if prepared.empty:
        return prepared

    prepared = prepared.ffill().bfill()
    prepared = prepared.sort_values("timestamp").reset_index(drop=True)
    prepared["vwap"] = (
        (prepared["close"] * prepared["volume"]).cumsum()
        / prepared["volume"].replace(0, np.nan).cumsum()
    ).fillna(prepared["close"])
    return prepared


def _jq_build_pullback_signal(
    prepared: pd.DataFrame,
    candidate: Dict[str, Any],
    quote: Dict[str, float],
    now: datetime,
    min_confidence: float = 0.65,
) -> _SignalOutput:
    if len(prepared) < 8:
        return _SignalOutput(False, "", 0.0, "分钟数据不足", details={"route_blocked": True})

    recent = prepared.tail(6).reset_index(drop=True)
    current_price = float(recent.iloc[-1]["close"])
    current_vwap = float(recent.iloc[-1]["vwap"])
    session_open = float(prepared.iloc[0]["open"])
    recent_low = float(recent["low"].min())
    prior_high = float(prepared.iloc[:-1]["high"].tail(20).max()) if len(prepared) > 1 else current_price
    recent_avg_vol = float(recent["volume"].tail(3).mean())
    prev_avg_vol = float(prepared["volume"].tail(12).head(9).mean()) if len(prepared) >= 12 else recent_avg_vol
    volume_ratio = (recent_avg_vol / prev_avg_vol) if prev_avg_vol > 0 else 1.0

    support_price = max(current_vwap, session_open)
    price_support_ratio = current_price / support_price if support_price > 0 else 1.0
    low_support_ratio = recent_low / support_price if support_price > 0 else 1.0

    support_strict = price_support_ratio >= 0.999 and low_support_ratio >= 0.996
    support_loose = price_support_ratio >= 0.985 and low_support_ratio >= 0.970
    support_deep = price_support_ratio >= 0.970 and low_support_ratio >= 0.950

    rebound_strong = current_price >= float(recent.iloc[-2]["close"]) and current_price >= recent["close"].min() * 1.005
    rebound_mild = current_price >= float(recent.iloc[-2]["close"]) and current_price >= recent["close"].min() * 1.002
    not_far_from_break = prior_high <= 0 or current_price >= prior_high * 0.980
    volume_ok_strict = 0.6 <= volume_ratio <= 1.35
    volume_ok_loose = 0.35 <= volume_ratio <= 1.50

    confidence = 0.0
    if support_strict:
        confidence += 0.35
    elif support_loose:
        confidence += 0.22
    elif support_deep:
        confidence += 0.10
    if rebound_strong:
        confidence += 0.25
    elif rebound_mild:
        confidence += 0.15
    if not_far_from_break:
        confidence += 0.20
    if volume_ok_strict:
        confidence += 0.20
    elif volume_ok_loose:
        confidence += 0.10

    hard_reject = (
        price_support_ratio < 0.970
        or low_support_ratio < 0.950
        or (not rebound_mild)
        or (not not_far_from_break)
        or (not volume_ok_loose)
    )
    signal = (not hard_reject) and confidence >= float(min_confidence)

    details = {
        "buy_route": "secondary_launch_pullback",
        "buy_route_label": "二次启动回踩确认",
        "trigger_price": round(float(current_price), 3),
        "volume_ratio": round(float(volume_ratio), 3),
    }
    return _SignalOutput(
        signal=signal,
        signal_type="secondary_launch_pullback",
        confidence=confidence,
        reason="二次启动回踩确认" if signal else "二次启动回踩条件未满足",
        details=details,
    )


def _jq_build_breakout_signal(
    prepared: pd.DataFrame,
    candidate: Dict[str, Any],
    quote: Dict[str, float],
    now: datetime,
    market_confirm: Optional[Dict[str, Any]] = None,
) -> _SignalOutput:
    if len(prepared) < 15:
        return _SignalOutput(False, "", 0.0, "分钟数据不足", details={"route_blocked": True})

    current_price = float(prepared.iloc[-1]["close"])
    current_volume = float(prepared.iloc[-1]["volume"])
    current_vwap = float(prepared.iloc[-1]["vwap"])
    recent_window = prepared.tail(15).iloc[:-1]
    breakout_price = float(recent_window["high"].max())
    consolidation_low = float(recent_window["low"].min())
    range_pct = (breakout_price - consolidation_low) / consolidation_low if consolidation_low > 0 else 0.0
    avg_volume = float(recent_window["volume"].tail(5).mean())
    volume_ratio = (current_volume / avg_volume) if avg_volume > 0 else 0.0
    recent_high = float(prepared["high"].tail(30).max())
    distance_to_recent_high = max(0.0, recent_high / current_price - 1.0) if current_price > 0 else 0.0
    market_gate = _jq_resolve_market_gate(market_confirm)
    afternoon_breakout = now.time() >= dt_time(13, 30)
    required_volume_ratio = 1.6 if afternoon_breakout else 1.2
    if market_gate.get("weak_market"):
        required_volume_ratio = max(required_volume_ratio, 1.6)
    breakout = current_price > breakout_price * 1.002
    hold_above = all(prepared["close"].tail(3) >= breakout_price * 0.998)
    vwap_support = current_price >= current_vwap * 1.001
    compact_platform = range_pct <= 0.020
    recent_closes = prepared["close"].tail(3).reset_index(drop=True)
    recent_lows = prepared["low"].tail(3)
    follow_through = int((recent_closes.diff() > 0).sum()) >= 2 and float(recent_lows.min()) >= breakout_price * 0.997
    volume_ok = volume_ratio >= required_volume_ratio
    near_high_supply_veto = distance_to_recent_high <= 0.015 and volume_ratio < 1.5

    signal = (
        breakout
        and hold_above
        and vwap_support
        and compact_platform
        and volume_ok
        and follow_through
        and not near_high_supply_veto
    )
    confidence = 0.0
    confidence += 0.30 if breakout else 0.0
    confidence += 0.20 if hold_above else 0.0
    confidence += 0.20 if vwap_support else 0.0
    confidence += 0.15 if compact_platform else 0.0
    confidence += 0.10 if volume_ok else 0.0
    confidence += 0.05 if follow_through else 0.0

    details = {
        "buy_route": "secondary_launch_breakout",
        "buy_route_label": "二次启动平台突破",
        "volume_ratio": round(float(volume_ratio), 3),
        "required_volume_ratio": round(float(required_volume_ratio), 3),
        "near_high_supply_veto": bool(near_high_supply_veto),
        "afternoon_breakout_tightened": bool(afternoon_breakout),
        "market_gate_tightened": bool(market_gate.get("weak_market")),
    }
    return _SignalOutput(
        signal=signal,
        signal_type="secondary_launch_breakout",
        confidence=confidence,
        reason="二次启动平台突破" if signal else "二次启动突破条件未满足",
        details=details,
    )


def _jq_check_daily_profile_gate(
    candidate: Dict[str, Any],
    vol_ratio_max: float = 1.3,
    upper_shadow_max: float = 60.0,
) -> Optional[_SignalOutput]:
    pct_chg = candidate.get("pct_chg")
    if pct_chg is not None:
        try:
            pct_chg = float(pct_chg)
        except (TypeError, ValueError):
            pct_chg = None

    upper_shadow_pct = candidate.get("upper_shadow_pct")
    if upper_shadow_pct is None:
        h = candidate.get("high")
        c = candidate.get("close")
        o = candidate.get("open")
        l = candidate.get("low")
        if h is not None and c is not None and o is not None and l is not None:
            try:
                h, c, o, l = float(h), float(c), float(o), float(l)
                total_range = h - l
                if total_range > 0:
                    upper_shadow_pct = (h - max(c, o)) / total_range * 100
            except (TypeError, ValueError):
                pass
    else:
        try:
            upper_shadow_pct = float(upper_shadow_pct)
        except (TypeError, ValueError):
            upper_shadow_pct = None

    vol_ratio_5 = candidate.get("vol_ratio_5")
    if vol_ratio_5 is None:
        vol = candidate.get("vol") or candidate.get("volume")
        vol_ma5 = candidate.get("vol_ma5")
        if vol is not None and vol_ma5 is not None:
            try:
                vol, vol_ma5 = float(vol), float(vol_ma5)
                if vol_ma5 > 0:
                    vol_ratio_5 = vol / vol_ma5
            except (TypeError, ValueError):
                pass
    else:
        try:
            vol_ratio_5 = float(vol_ratio_5)
        except (TypeError, ValueError):
            vol_ratio_5 = None

    blocked_reasons = []
    if pct_chg is not None and -5.0 <= pct_chg < -3.0:
        blocked_reasons.append("信号日跌幅处于[-5%,-3%)高危区间")
    if upper_shadow_pct is not None and upper_shadow_pct > float(upper_shadow_max):
        blocked_reasons.append("上影线过长")
    if vol_ratio_5 is not None and vol_ratio_5 > float(vol_ratio_max):
        blocked_reasons.append("量比异常放量")

    if blocked_reasons:
        reason = "日线形态过滤: " + "; ".join(blocked_reasons)
        return _SignalOutput(
            False,
            "",
            0.0,
            reason,
            details={"route_blocked": True, "blocker_tag": "daily_profile_gate"},
        )
    return None


def detect_secondary_launch_signal_jq(
    candidate: Dict[str, Any],
    quote: Dict[str, float],
    now: datetime,
    minute_df: Optional[pd.DataFrame],
    industry_confirm: Optional[Dict[str, Any]] = None,
    market_confirm: Optional[Dict[str, Any]] = None,
    pullback_conf_min: float = 0.65,
    daily_vol_ratio_max: float = 1.25,
    daily_upper_shadow_max: float = 55.0,
) -> _SignalOutput:
    """与仓库 detect_secondary_launch_signal 同序：先回踩再突破。"""
    if now.time() < dt_time(9, 35) or now.time() > dt_time(14, 20):
        return _SignalOutput(False, "", 0.0, "非二次启动监控窗口", details={"route_blocked": True})

    daily_gate = _jq_check_daily_profile_gate(
        candidate,
        vol_ratio_max=daily_vol_ratio_max,
        upper_shadow_max=daily_upper_shadow_max,
    )
    if daily_gate is not None:
        return daily_gate

    prepared = _jq_prepare_minute_frame(minute_df)
    if prepared.empty:
        return _SignalOutput(False, "", 0.0, "缺少有效分钟数据", details={"route_blocked": True})

    industry_info = industry_confirm or {}
    industry_score = float(industry_info.get("score", 50.0) or 50.0)
    industry_level = str(industry_info.get("level", "neutral") or "neutral")
    industry_blocked = industry_score < 45.0 or industry_level in {"weak", "poor"}

    market_gate = _jq_resolve_market_gate(market_confirm)

    pullback_signal = _jq_build_pullback_signal(
        prepared, candidate, quote, now, min_confidence=float(pullback_conf_min)
    )
    if industry_blocked:
        pullback_signal.signal = False
        pullback_signal.details["route_blocked"] = True
        pullback_signal.details["blocker_tag"] = "industry_blocked"
    if pullback_signal.signal and pullback_signal.confidence >= float(pullback_conf_min):
        return pullback_signal

    breakout_signal = _jq_build_breakout_signal(
        prepared, candidate, quote, now, market_confirm=market_confirm
    )
    if industry_blocked:
        breakout_signal.signal = False
        breakout_signal.details["route_blocked"] = True
        breakout_signal.details["blocker_tag"] = "industry_blocked"
    breakout_threshold = _jq_resolve_breakout_threshold(now, market_gate)
    breakout_signal.details["confidence_threshold"] = round(float(breakout_threshold), 2)
    if breakout_signal.signal and breakout_signal.confidence >= breakout_threshold:
        return breakout_signal

    return breakout_signal if breakout_signal.confidence >= pullback_signal.confidence else pullback_signal


def build_market_confirm_jq(context) -> Optional[Dict[str, Any]]:
    """用上证指数 1 分钟线近似系统里的 market_confirm（VWAP 与分时强弱）。"""
    try:
        idx = get_price(
            "000001.XSHG",
            end_date=context.current_dt,
            count=240,
            frequency="1m",
            fields=["close", "volume"],
            skip_paused=True,
            fq="pre",
        )
        if idx is None or len(idx) < 10:
            return None
        close = idx["close"].astype(float)
        vol = idx["volume"].astype(float)
        vwap = (close * vol).cumsum() / vol.replace(0, np.nan).cumsum()
        vwap = vwap.fillna(close)
        last_close = float(close.iloc[-1])
        last_vwap = float(vwap.iloc[-1])
        index_below_vwap = last_close < last_vwap * 0.999
        first = float(close.iloc[0])
        ret = (last_close / first - 1.0) if first > 0 else 0.0
        market_score = float(np.clip(50.0 + ret * 400.0, 0.0, 100.0))
        trend = "down" if ret < -0.003 else ("weak" if ret < -0.001 else "neutral")
        return {
            "market_score": market_score,
            "trend": trend,
            "index_below_vwap": index_below_vwap,
        }
    except Exception:
        return None


def _filter_minutes_today(minute_df: pd.DataFrame, current_dt: datetime) -> pd.DataFrame:
    """只保留当前交易日的分钟线，避免 count=240 跨日混入昨夜数据。"""
    if minute_df is None or minute_df.empty:
        return pd.DataFrame()
    df = minute_df.copy()
    if isinstance(df.index, pd.DatetimeIndex):
        day = current_dt.date()
        mask = [pd.Timestamp(x).date() == day for x in df.index]
        return df.loc[mask]
    df = df.reset_index()
    ts_col = df.columns[0]
    df[ts_col] = pd.to_datetime(df[ts_col])
    df = df[df[ts_col].dt.date == current_dt.date()]
    if df.empty:
        return pd.DataFrame()
    return df.set_index(ts_col)


def handle_data(context, data):
    """
    分钟级：对当日日线候选做「回踩确认 / 平台突破」触发后下单（对齐 secondary_launch_intraday）。
    需在聚宽选择「分钟」频率回测；若仅「每日」频率，本函数几乎不生效，请关闭 use_intraday_confirm 或改用分钟回测。
    """
    if not getattr(g.params, "use_intraday_confirm", False):
        return
    if not g.buy_list:
        return
    now = context.current_dt
    t = now.time()
    if t < dt_time(9, 35) or t > dt_time(14, 20):
        return

    pending = [
        c
        for c in g.buy_list
        if c not in g.intraday_filled
        and c not in g.intraday_abandoned_cash
        and c not in context.portfolio.positions
    ]
    if not pending:
        return
    cash = float(context.portfolio.available_cash)
    if cash < 1000:
        return

    market_confirm = build_market_confirm_jq(context)
    current_data = get_current_data()
    sig_ok: Dict[str, _SignalOutput] = {}
    for code in pending:
        cand = g.buy_candidates.get(code)
        if not cand:
            continue
        try:
            raw = get_price(
                code,
                end_date=now,
                count=240,
                frequency="1m",
                fields=["open", "close", "high", "low", "volume"],
                skip_paused=True,
                fq="pre",
            )
            raw = _filter_minutes_today(raw, now)
            if raw is None or len(raw) < 8:
                continue
            px = float(raw["close"].iloc[-1])
            op = float(raw["open"].iloc[0])
            hi = float(raw["high"].max())
            lo = float(raw["low"].min())
            vol = float(raw["volume"].iloc[-1])
            quote = {"price": px, "open": op, "high": hi, "low": lo, "volume": vol}
            so = detect_secondary_launch_signal_jq(
                candidate=cand,
                quote=quote,
                now=now,
                minute_df=raw,
                industry_confirm=None,
                market_confirm=market_confirm,
                pullback_conf_min=float(g.params.intraday_pullback_confidence_min),
                daily_vol_ratio_max=float(g.params.daily_gate_vol_ratio_max),
                daily_upper_shadow_max=float(g.params.daily_gate_upper_shadow_max),
            )
            if so.signal and not so.details.get("route_blocked"):
                sig_ok[code] = so
        except Exception:
            continue

    ordered = [c for c in g.buy_list if c in sig_ok]
    if not ordered:
        return

    codes = ordered
    prices = {}
    for code in codes:
        p = _estimate_ref_price(code, context, current_data)
        if p is not None and p > 0:
            prices[code] = p
    if not prices:
        return

    today = context.current_dt.date()
    plan = _plan_orders_min_lot_then_bonus(codes, prices, cash)
    if not plan:
        for c in codes:
            g.intraday_abandoned_cash.add(c)
        need0 = _min_cash_for_one_lot(prices[codes[0]])
        log.info(
            "盘中确认: 可用资金约%.0f 元不足以买入候选 %s 一手（首只参考下限约%.0f 元），当日不再重复尝试",
            cash,
            codes,
            need0,
        )
        return
    min_ev = float(getattr(g.params, "min_entry_value", 0) or 0)
    if min_ev > 0:
        plan = [(c, v) for c, v in plan if v >= min_ev]
        if not plan:
            for c in codes:
                g.intraday_abandoned_cash.add(c)
            log.info(
                "盘中确认: 计划市值低于单笔下限 %.0f 元，当日不交易（候选=%s）",
                min_ev,
                codes,
            )
            return
    for code, val in plan:
        _jq_intraday_buy_outcome(context, code, val, today)
    if len(plan) >= 2:
        log.info(
            "盘中确认买入 %s 目标市值≈%s 信号=%s",
            [c for c, _ in plan],
            [round(v, 2) for _, v in plan],
            [sig_ok[c].signal_type for c, _ in plan],
        )
    else:
        only = plan[0][0]
        log.info(
            "盘中确认: 仅首只 %s 类型=%s 目标≈%.0f（余下候选资金不足一手或仅一只触发）",
            only,
            sig_ok[only].signal_type,
            plan[0][1],
        )


def initialize(context):
    """聚宽初始化"""
    g.params = StrategyParams()
    g.hold_days = 5
    # 记录每只股票上次入选信号日（用于冷却）
    g.last_signal_date = {}
    # 记录买入日期（用于持仓天数卖出）
    g.entry_date = {}
    # 当日待买列表
    g.buy_list = []
    # 日线行字典 ts_code -> 特征（供盘中闸门）
    g.buy_candidates = {}
    # 盘中已下单代码（当日）
    g.intraday_filled = set()
    # 因资金不足已放弃当日再买的候选（避免每分钟重复算信号、刷日志）
    g.intraday_abandoned_cash = set()

    set_benchmark("000001.XSHG")
    set_option("use_real_price", True)
    # 与回测器 CostConfig 接近
    set_order_cost(
        OrderCost(
            open_tax=0,
            close_tax=0.001,
            open_commission=0.0003,
            close_commission=0.0003,
            min_commission=5,
        ),
        type="stock",
    )
    set_slippage(PriceRelatedSlippage(0.001))

    run_daily(before_open_select, time="before_open")
    run_daily(at_open_buy, time="open")
    run_daily(at_close_sell, time="close")
    run_daily(after_trading_end, time="after_close")


def before_open_select(context):
    """盘前：用前一交易日收盘完成的数据选股（等价于 t-1 特征 → t 日信号）"""
    p = g.params
    g.buy_list = []
    g.buy_candidates = {}
    g.intraday_filled = set()
    g.intraday_abandoned_cash = set()
    prev = context.previous_date
    all_stocks = get_all_securities(types=["stock"], date=prev)
    codes = [c for c in all_stocks.index if _is_mainboard_jq(c)]

    rows = []
    for code in codes:
        try:
            info = get_security_info(code)
            name = info.display_name
            if _is_risk_name(name):
                continue
            start_date = info.start_date
            if start_date is None:
                continue
            ld = (prev - start_date).days
            if ld < p.min_list_days:
                continue

            df = get_price(
                code,
                end_date=prev,
                count=120,
                frequency="daily",
                fields=["open", "close", "high", "low", "volume", "money"],
                skip_paused=False,
                fq="pre",
            )
            if df is None or len(df) < 60:
                continue

            feat = prepare_single_stock_features(df, p, name, ld)
            if feat is None:
                continue
            feat["ts_code"] = code
            feat["rs20_raw"] = feat.get("rs20") or 0.0
            rows.append(feat)
        except Exception:
            continue

    if not rows:
        log.info("二次启动 %s: 无有效特征（数据不足或主板为空）", str(prev))
        return

    base = pd.DataFrame(rows)
    # 底线过滤
    mask = base.apply(lambda r: base_filter_row(r.to_dict(), p), axis=1)
    filt = base.loc[mask].copy()
    n_base = len(filt)
    if filt.empty:
        log.info("二次启动 %s: 特征=%d 底线过滤后=0（检查成交额单位/涨停条件等）", str(prev), len(rows))
        return

    # RS 分位（仅在候选集内）
    filt["rs_rank"] = filt["rs20_raw"].rank(pct=True, method="average").fillna(0.0)

    ret5 = get_index_ret5(context)
    min_sc, max_picks = get_market_gate(ret5, p)
    if max_picks <= 0:
        log.info("二次启动 %s: 弱市闸门，当日不选股（ret5=%.4f）", str(prev), ret5)
        return

    scores = []
    for _, r in filt.iterrows():
        s = score_row(r.to_dict(), p, float(r["rs_rank"]))
        scores.append(s)
    filt["signal_score"] = scores
    filt["rs20"] = filt["rs20_raw"]
    filt = filt[filt["signal_score"] >= min_sc].copy()
    n_score = len(filt)
    if filt.empty:
        log.info(
            "二次启动 %s: 特征=%d 底线=%d 得分>=%.1f 为0（ret5=%.4f）",
            str(prev),
            len(rows),
            n_base,
            min_sc,
            ret5,
        )
        return

    filt = filt.sort_values(["signal_score", "rs20"], ascending=[False, False]).head(p.max_candidates)

    # 冷却：与仓库一致
    today = context.current_dt.date()
    eligible = []
    for _, r in filt.iterrows():
        code = r["ts_code"]
        last_d = g.last_signal_date.get(code)
        if last_d is None:
            eligible.append(r)
            continue
        gap = (today - last_d).days
        if gap > p.cooldown_days:
            eligible.append(r)

    if not eligible:
        log.info("二次启动 %s: 过线=%d 但全部被冷却挡回", str(prev), n_score)
        return

    day_df = pd.DataFrame(eligible).sort_values(["signal_score", "rs20"], ascending=[False, False])
    day_df = day_df.head(max_picks)
    day_df = refine_daily_picks(day_df, p)
    if day_df.empty:
        log.info("二次启动 %s: 第二名精炼后为空", str(prev))
        return

    g.buy_list = day_df["ts_code"].tolist()
    for _, r in day_df.iterrows():
        g.buy_candidates[str(r["ts_code"])] = r.to_dict()
    for c in g.buy_list:
        g.last_signal_date[c] = today
    log.info(
        "二次启动 %s: 特征=%d 底线=%d 过线=%d 当日候选=%s（盘中确认=%s）",
        str(prev),
        len(rows),
        n_base,
        n_score,
        str(g.buy_list),
        str(getattr(p, "use_intraday_confirm", False)),
    )


def _estimate_ref_price(code, context, current_data):
    """用于估算一手最低金额：优先当前价/开盘价，否则昨收。"""
    try:
        d = current_data[code]
        p = getattr(d, "last_price", None)
        if p is None or p <= 0:
            p = getattr(d, "day_open", None)
        if p is not None and p > 0:
            return float(p)
    except Exception:
        pass
    try:
        px = get_price(code, end_date=context.previous_date, count=1, fields=["close"], fq="pre")
        if px is not None and len(px) > 0:
            return float(px["close"].iloc[-1])
    except Exception:
        pass
    return None


def _min_cash_for_one_lot(ref_price: float) -> float:
    """A 股至少 100 股一手；加少量缓冲以覆盖舍入与最低佣金。"""
    return ref_price * 100.0 * 1.03 + 5.0


def _jq_order_status_is_cancelled(st) -> bool:
    """判断聚宽 Order.status 是否为撤单类终态（本地无 jqdata 时退回字符串判断）。"""
    if st is None:
        return False
    try:
        from jqdata import OrderStatus  # noqa: F401

        for name in ("canceled", "cancelled", "order_canceled", "order_cancelled"):
            v = getattr(OrderStatus, name, None)
            if v is not None and st == v:
                return True
    except Exception:
        pass
    s = str(st).lower()
    return "cancel" in s


def _jq_intraday_buy_outcome(context, code: str, val: float, today) -> None:
    """
    盘中市价/目标市值单之后：仅在实际成交或等价持仓时记入 intraday_filled + entry_date；
    撤单（如涨停）记入 intraday_abandoned_cash，避免误记建仓日、也避免与「未成交却占位」混淆。
    """
    o = order_target_value(code, val)
    pos = context.portfolio.positions.get(code)
    n = int(pos.total_amount) if pos else 0
    filled = int(getattr(o, "filled", 0) or 0) if o is not None else 0
    st = getattr(o, "status", None) if o is not None else None
    if n > 0 or filled > 0:
        g.intraday_filled.add(code)
        g.entry_date[code] = today
        return
    if _jq_order_status_is_cancelled(st):
        g.intraday_abandoned_cash.add(code)
        log.info("盘中确认: %s 下单未成交（订单已撤单），当日不再重试", code)
        return
    if o is None:
        g.intraday_abandoned_cash.add(code)
        log.info("盘中确认: %s 下单未生效（无订单对象），当日不再重试", code)
        return
    # 其它未持仓状态：防止同一标的反复下单
    g.intraday_filled.add(code)


def _plan_orders_min_lot_then_bonus(
    codes: list,
    prices: Dict[str, float],
    cash: float,
) -> list:
    """
    生成下单计划：先保证每只有一手最低市值，若总最低和 <= 预算则余量在各只间均分。
    解决「现金/2 买不起贵票一手但总现金够买两只各一手」的情况。
    返回 [(code, 目标市值), ...]；无法成交则返回 []。
    """
    codes = [c for c in codes if c in prices and prices[c] and prices[c] > 0]
    if not codes:
        return []
    budget = float(cash) * 0.98
    mns = {c: _min_cash_for_one_lot(prices[c]) for c in codes}
    for k in range(len(codes), 0, -1):
        subset = codes[:k]
        total_min = sum(mns[c] for c in subset)
        if total_min <= budget:
            excess = budget - total_min
            bonus = excess / k
            return [(c, mns[c] + bonus) for c in subset]
    first = codes[0]
    if budget >= mns[first]:
        return [(first, budget)]
    return []


def at_open_buy(context):
    """
    开盘：买入待买列表（已持仓则跳过）。

    资金分配：每只股票先满足一手最低市值，若多只股票一手下限之和不超过预算，
    则剩余现金在拟买入的各只间均分（_plan_orders_min_lot_then_bonus），避免「现金/只数」买不起贵票一手但总现金够两笔一手。
    """
    if getattr(g.params, "use_intraday_confirm", False):
        return
    if not g.buy_list:
        return
    cash = float(context.portfolio.available_cash)
    today = context.current_dt.date()
    candidates = [c for c in g.buy_list if c not in context.portfolio.positions]
    if not candidates or cash < 1000:
        return

    current_data = get_current_data()
    prices = {}
    for code in candidates:
        p = _estimate_ref_price(code, context, current_data)
        if p is not None and p > 0:
            prices[code] = p

    if not prices:
        log.info("二次启动开盘: 无法取得参考价，跳过买入")
        return

    plan = _plan_orders_min_lot_then_bonus(candidates, prices, cash)
    if not plan:
        log.info(
            "二次启动开盘: 可用资金不足以满足首只 %s 一手下限",
            candidates[0] if candidates else "",
        )
        return
    min_ev = float(getattr(g.params, "min_entry_value", 0) or 0)
    if min_ev > 0:
        plan = [(c, v) for c, v in plan if v >= min_ev]
        if not plan:
            log.info(
                "二次启动开盘: 计划市值低于单笔下限 %.0f 元，跳过买入（候选=%s）",
                min_ev,
                candidates,
            )
            return
    for code, val in plan:
        order_target_value(code, val)
        g.entry_date[code] = today
    n = len(candidates)
    if len(plan) < n:
        log.info(
            "二次启动开盘: 仅买入 %d/%d 只 %s（其余一手合计超预算）",
            len(plan),
            n,
            [c for c, _ in plan],
        )
    else:
        log.info(
            "二次启动开盘: 买入 %s 目标市值≈%s",
            [c for c, _ in plan],
            [round(v, 2) for _, v in plan],
        )


def at_close_sell(context):
    """
    收盘：卖出条件与仓库 MainboardSecondaryLaunchBacktester 一致：
    信号日对应 entry=iloc[0]，exit=iloc[hold_days]，即从建仓日到卖出日共 hold_days+1 个交易日（含首尾）。
    """
    today = context.current_dt.date()
    to_sell = []
    for code, pos in context.portfolio.positions.items():
        if pos.total_amount <= 0:
            continue
        ed = g.entry_date.get(code)
        if ed is None:
            continue
        try:
            days_list = get_trade_days(start_date=ed, end_date=today)
            # len>=hold_days+1 时到达 exit 那根 K 线对应日期（与 iloc[hold_days] 对齐）
            if len(days_list) >= g.hold_days + 1:
                to_sell.append(code)
        except Exception:
            if (today - ed).days >= g.hold_days + 3:
                to_sell.append(code)

    for code in to_sell:
        order_target_value(code, 0)
        g.entry_date.pop(code, None)


def after_trading_end(context):
    """补记建仓日：若开盘单延迟成交导致 entry 缺失（在收盘后执行）"""
    for code, pos in context.portfolio.positions.items():
        if pos.total_amount > 0 and code not in g.entry_date:
            g.entry_date[code] = context.current_dt.date()
