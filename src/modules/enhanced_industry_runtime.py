"""Intraday industry confirmation helpers for EnhancedHybridSystem."""

from __future__ import annotations

from datetime import datetime
from typing import Dict, Optional

import logging

import pandas as pd

try:
    import akshare as ak

    AKSHARE_AVAILABLE = True
except Exception:
    ak = None
    AKSHARE_AVAILABLE = False

logger = logging.getLogger(__name__)


def _safe_int(value: object, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)


def industry_level_by_score(system, score: float) -> str:
    if score >= system.intraday_industry_strong_threshold:
        return "strong"
    if score <= system.intraday_industry_weak_threshold:
        return "weak"
    return "neutral"


def build_candidate_minute_industry_context(
    system,
    minute_map: Optional[Dict[str, pd.DataFrame]],
) -> Dict:
    lookback_bars = max(1, _safe_int(getattr(system, "intraday_industry_lookback_bars", 20), 20))
    min_symbols = max(1, _safe_int(getattr(system, "intraday_industry_min_symbols", 1), 1))

    if not minute_map:
        return {"industry_map": {}, "top_industries": [], "bottom_industries": []}

    metrics = []
    for candidate in system.candidate_pool:
        symbol = str(candidate.get("symbol", ""))
        industry = str(candidate.get("industry", "")).strip()
        if not symbol or not industry:
            continue

        minute_df = minute_map.get(symbol)
        if minute_df is None or minute_df.empty:
            continue

        ordered = minute_df.sort_values("trade_time").reset_index(drop=True)
        if len(ordered) < 6:
            continue

        lookback = min(lookback_bars, len(ordered) - 1)
        if lookback < 3:
            continue

        close = pd.to_numeric(ordered["close"], errors="coerce").ffill().bfill()
        volume = pd.to_numeric(ordered["volume"], errors="coerce").fillna(0.0)
        if close.empty:
            continue

        base = float(close.iloc[-lookback - 1]) if len(close) > lookback else float(close.iloc[0])
        latest = float(close.iloc[-1])
        if base <= 0:
            continue

        ret_lb = (latest / base - 1) * 100
        recent_vol = float(volume.tail(lookback).mean())
        if len(volume) >= lookback * 2:
            prev_vol = float(volume.iloc[-lookback * 2 : -lookback].mean())
        else:
            prev_vol = float(volume.head(lookback).mean()) if len(volume) >= lookback else recent_vol
        vol_ratio = recent_vol / prev_vol if prev_vol > 0 else 1.0

        metrics.append(
            {
                "industry": industry,
                "symbol": symbol,
                "ret_lb": ret_lb,
                "up_flag": 1.0 if ret_lb > 0 else 0.0,
                "vol_ratio": vol_ratio,
            }
        )

    if not metrics:
        return {"industry_map": {}, "top_industries": [], "bottom_industries": []}

    stock_df = pd.DataFrame(metrics)
    industry_df = (
        stock_df.groupby("industry")
        .agg(
            symbol_count=("symbol", "count"),
            avg_return=("ret_lb", "mean"),
            breadth=("up_flag", "mean"),
            avg_vol_ratio=("vol_ratio", "mean"),
        )
        .reset_index()
    )
    industry_df = industry_df[industry_df["symbol_count"] >= min_symbols]
    if industry_df.empty:
        return {"industry_map": {}, "top_industries": [], "bottom_industries": []}

    if len(industry_df) > 1:
        ret_rank = industry_df["avg_return"].rank(pct=True)
        breadth_rank = industry_df["breadth"].rank(pct=True)
        vol_rank = industry_df["avg_vol_ratio"].rank(pct=True)
        industry_df["score"] = ret_rank * 60 + breadth_rank * 25 + vol_rank * 15
    else:
        industry_df["score"] = 50.0

    industry_df["score"] = industry_df["score"].clip(lower=0, upper=100)
    industry_df = industry_df.sort_values("score", ascending=False).reset_index(drop=True)
    industry_df["level"] = industry_df["score"].apply(system._industry_level_by_score)

    industry_map = {}
    for idx, row in industry_df.iterrows():
        industry_map[str(row["industry"])] = {
            "industry": str(row["industry"]),
            "score": round(float(row["score"]), 2),
            "level": row["level"],
            "rank": int(idx + 1),
            "symbol_count": int(row["symbol_count"]),
            "avg_return": round(float(row["avg_return"]), 3),
            "breadth": round(float(row["breadth"]), 3),
            "avg_vol_ratio": round(float(row["avg_vol_ratio"]), 3),
            "source": "candidate_minute",
        }

    records = list(industry_map.values())
    return {
        "industry_map": industry_map,
        "top_industries": records[:5],
        "bottom_industries": list(reversed(records[-5:])) if records else [],
    }


def fetch_realtime_industry_context_from_source(system) -> Optional[Dict]:
    if not AKSHARE_AVAILABLE:
        return None

    now = datetime.now()
    cached_ts = system._industry_realtime_cache.get("ts")
    cached_context = system._industry_realtime_cache.get("context")
    if (
        cached_ts is not None
        and cached_context is not None
        and (now - cached_ts).total_seconds() <= max(0, system.intraday_industry_cache_seconds)
    ):
        return cached_context

    try:
        spot_df = ak.stock_board_industry_spot_em()
    except Exception as exc:
        logger.warning("行业实时主源获取失败，降级到候选分钟聚合: %s", exc)
        return None

    if spot_df is None or spot_df.empty:
        return None

    name_col = next((c for c in spot_df.columns if "名称" in str(c) or "板块" in str(c)), None)
    change_col = next((c for c in spot_df.columns if "涨跌幅" in str(c)), None)
    if not name_col or not change_col:
        logger.warning("行业实时主源字段不匹配，降级到候选分钟聚合")
        return None

    normalized = pd.DataFrame(
        {
            "industry": spot_df[name_col].astype(str).str.strip(),
            "pct_change": pd.to_numeric(spot_df[change_col], errors="coerce"),
            "amount": pd.to_numeric(
                spot_df[next((c for c in spot_df.columns if "成交额" in str(c)), change_col)],
                errors="coerce",
            ),
        }
    )
    normalized = normalized.dropna(subset=["industry", "pct_change"])
    normalized = normalized[normalized["industry"] != ""]
    if normalized.empty:
        return None

    if len(normalized) > 1:
        pct_rank = normalized["pct_change"].rank(pct=True)
        liquidity_rank = (
            normalized["amount"].rank(pct=True) if normalized["amount"].notna().any() else 0.5
        )
        normalized["score"] = pct_rank * 85 + liquidity_rank * 15
    else:
        normalized["score"] = 50.0

    normalized["score"] = normalized["score"].clip(lower=0, upper=100)
    normalized = normalized.sort_values("score", ascending=False).reset_index(drop=True)
    normalized["level"] = normalized["score"].apply(system._industry_level_by_score)

    industry_map: Dict[str, Dict] = {}
    for idx, row in normalized.iterrows():
        industry_map[str(row["industry"])] = {
            "industry": str(row["industry"]),
            "score": round(float(row["score"]), 2),
            "level": row["level"],
            "rank": int(idx + 1),
            "pct_change": round(float(row["pct_change"]), 3),
            "amount": round(float(row["amount"]), 3) if pd.notna(row["amount"]) else None,
            "source": "akshare_industry_spot",
        }

    records = list(industry_map.values())
    context = {
        "industry_map": industry_map,
        "top_industries": records[:5],
        "bottom_industries": list(reversed(records[-5:])) if records else [],
    }
    system._industry_realtime_cache["ts"] = now
    system._industry_realtime_cache["context"] = context
    return context


def match_industry_context(
    system,
    industry_name: str,
    industry_map: Dict[str, Dict],
) -> Optional[Dict]:
    if not industry_name or not industry_map:
        return None

    if industry_name in industry_map:
        return industry_map[industry_name]

    target = system._normalize_industry_key(industry_name)
    if not target:
        return None

    normalized_map = {system._normalize_industry_key(key): key for key in industry_map.keys()}
    if target in normalized_map:
        return industry_map[normalized_map[target]]

    for normalized_key, original_key in normalized_map.items():
        if not normalized_key:
            continue
        if target in normalized_key or normalized_key in target:
            return industry_map[original_key]
    return None


def build_intraday_industry_context(
    system,
    minute_map: Optional[Dict[str, pd.DataFrame]],
    now: Optional[datetime] = None,
) -> Dict:
    if not system.enable_intraday_industry_confirmation:
        context = {
            "enabled": False,
            "timestamp": (now or datetime.now()).strftime("%Y-%m-%d %H:%M:%S"),
            "industry_map": {},
            "top_industries": [],
            "bottom_industries": [],
            "source": "disabled",
        }
        system.latest_industry_context = context
        return context

    fallback_context = system._build_candidate_minute_industry_context(minute_map)

    industry_map: Dict[str, Dict] = {}
    if fallback_context.get("industry_map"):
        industry_map.update(fallback_context["industry_map"])

    ranked = sorted(
        industry_map.values(),
        key=lambda item: float(item.get("score", 50.0)),
        reverse=True,
    )

    context = {
        "enabled": True,
        "timestamp": (now or datetime.now()).strftime("%Y-%m-%d %H:%M:%S"),
        "industry_map": industry_map,
        "top_industries": ranked[:5],
        "bottom_industries": list(reversed(ranked[-5:])) if ranked else [],
        "source": "candidate_minute_fallback",
        "source_available": False,
    }
    system.latest_industry_context = context
    return context


def resolve_candidate_industry_confirm(
    system,
    candidate: Dict,
    industry_context: Optional[Dict],
) -> Dict:
    default = {
        "industry": candidate.get("industry", ""),
        "score": 50.0,
        "level": "neutral",
        "score_adjustment": 0.0,
        "source": "none",
    }
    if not industry_context or not industry_context.get("industry_map"):
        return default

    matched = system._match_industry_context(
        industry_name=str(candidate.get("industry", "")),
        industry_map=industry_context.get("industry_map", {}),
    )
    if not matched:
        return default

    score = float(matched.get("score", 50.0))
    level = str(matched.get("level", system._industry_level_by_score(score)))
    if level == "strong":
        adjustment = 3.0
    elif level == "weak":
        adjustment = -4.0
    else:
        adjustment = 0.0

    return {
        "industry": str(matched.get("industry", candidate.get("industry", ""))),
        "score": round(score, 2),
        "level": level,
        "score_adjustment": adjustment,
        "source": str(matched.get("source", industry_context.get("source", "unknown"))),
        "rank": matched.get("rank"),
    }
