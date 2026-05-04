# -*- coding: utf-8 -*-
"""
机构化核心选股器

设计目标：
1. 摆脱单一打分链，改为趋势领导 / 回撤承接 / 质量稳定 / 行业强度四袖口融合；
2. 引入市场状态路由，在 trend / sideways / weak 不同环境下自动切换权重；
3. 先做收益潜力评分，再做追涨 / 波动 / 上影 / 异常放量惩罚，更接近机构风控思路。
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from src.core.logger import get_logger

logger = get_logger("institutional_core_selector")


class InstitutionalCoreSelector:
    """机构化多袖口选股器。"""

    MAINBOARD_SQL = """
        SELECT ts_code, trade_date, open, close, high, low, vol, amount, pct_chg
        FROM stock_daily
        WHERE trade_date >= ? AND trade_date <= ?
          AND (
                ts_code LIKE '600%.SH' OR ts_code LIKE '601%.SH'
             OR ts_code LIKE '603%.SH' OR ts_code LIKE '605%.SH'
             OR ts_code LIKE '000%.SZ' OR ts_code LIKE '001%.SZ'
             OR ts_code LIKE '002%.SZ' OR ts_code LIKE '003%.SZ'
          )
        ORDER BY ts_code ASC, trade_date ASC
    """

    def __init__(self, config, db, regime_router=None):
        self.config = config
        self.db = db
        self.regime_router = regime_router

        prefix = "stock_selection.institutional_core"
        self.lookback_days = max(80, int(config.get(f"{prefix}.lookback_days", 120) or 120))
        self.min_history_days = max(60, int(config.get(f"{prefix}.min_history_days", 80) or 80))
        self.min_amount = float(config.get(f"{prefix}.min_amount", 150000.0) or 150000.0)
        self.score_threshold = float(config.get(f"{prefix}.score_threshold", 58.0) or 58.0)
        self.min_quality_score = float(config.get(f"{prefix}.min_quality_score", 42.0) or 42.0)
        self.risk_penalty_weight = float(
            config.get(f"{prefix}.risk_penalty_weight", 28.0) or 28.0
        )
        self.min_close_to_ma60 = float(
            config.get(f"{prefix}.min_close_to_ma60", 0.96) or 0.96
        )
        self.min_ret60 = float(config.get(f"{prefix}.min_ret60", -0.03) or -0.03)
        self.max_top_distance = float(
            config.get(f"{prefix}.max_top_distance", 0.18) or 0.18
        )

    def run(
        self,
        end_date: str,
        stock_list: pd.DataFrame,
        industry_strength_map: Optional[Dict[str, Dict]] = None,
    ) -> List[Dict]:
        if stock_list is None or stock_list.empty:
            return []

        regime_decision = self._decide_regime(end_date=end_date)
        market_df = self._load_market_window(end_date=end_date)
        if market_df.empty:
            logger.warning("机构核心策略缺少市场窗口数据: %s", end_date)
            return []

        base_meta = stock_list[["ts_code", "name", "industry"]].drop_duplicates("ts_code").copy()
        market_df = market_df.merge(base_meta, on="ts_code", how="inner")
        if market_df.empty:
            logger.warning("机构核心策略合并股票池后为空: %s", end_date)
            return []

        industry_strength_map = industry_strength_map or {}
        weights = self._get_regime_weights(regime_decision.regime)
        dynamic_threshold = self._get_dynamic_threshold(regime_decision.regime)

        results: List[Dict] = []
        for ts_code, group in market_df.groupby("ts_code", sort=False):
            row = self._score_stock(
                ts_code=str(ts_code),
                daily_df=group.reset_index(drop=True),
                regime_decision=regime_decision,
                regime_weights=weights,
                dynamic_threshold=dynamic_threshold,
                industry_strength=industry_strength_map.get(str(group["industry"].iloc[0] or "")),
            )
            if row is not None:
                results.append(row)

        results.sort(key=lambda item: item.get("total_score", 0.0), reverse=True)

        logger.info(
            "机构核心策略完成: %s | regime=%s | threshold=%.1f | candidates=%d",
            end_date,
            regime_decision.regime,
            dynamic_threshold,
            len(results),
        )
        for idx, item in enumerate(results[:10], start=1):
            logger.info(
                "  %d. %s %s - total=%.1f trend=%.1f pullback=%.1f quality=%.1f industry=%.1f penalty=%.1f",
                idx,
                item["ts_code"],
                item.get("name", ""),
                item["total_score"],
                item["score_breakdown"]["trend"],
                item["score_breakdown"]["pullback"],
                item["score_breakdown"]["quality"],
                item["score_breakdown"]["industry"],
                item["score_breakdown"]["risk_penalty"],
            )

        return results

    def _load_market_window(self, end_date: str) -> pd.DataFrame:
        end_dt = datetime.strptime(str(end_date), "%Y%m%d")
        start_date = (end_dt - timedelta(days=self.lookback_days * 2)).strftime("%Y%m%d")
        rows = self.db.query(self.MAINBOARD_SQL, (start_date, end_date))
        if not rows:
            return pd.DataFrame()

        df = pd.DataFrame(rows)
        if df.empty:
            return df

        for col in ("open", "close", "high", "low", "vol", "amount", "pct_chg"):
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")

        df = df.dropna(subset=["close", "high", "low"]).copy()
        df = df.sort_values(["ts_code", "trade_date"]).reset_index(drop=True)
        return df

    def _score_stock(
        self,
        ts_code: str,
        daily_df: pd.DataFrame,
        regime_decision,
        regime_weights: Dict[str, float],
        dynamic_threshold: float,
        industry_strength: Optional[Dict],
    ) -> Optional[Dict]:
        if daily_df.empty or len(daily_df) < self.min_history_days:
            return None

        close = daily_df["close"].astype(float).to_numpy()
        open_ = daily_df["open"].astype(float).fillna(daily_df["close"]).to_numpy()
        high = daily_df["high"].astype(float).to_numpy()
        low = daily_df["low"].astype(float).to_numpy()
        vol = daily_df["vol"].astype(float).fillna(0.0).to_numpy()
        amount = daily_df["amount"].astype(float).fillna(0.0).to_numpy()
        pct_chg = daily_df["pct_chg"].astype(float).fillna(0.0).to_numpy()

        if len(close) < 61 or close[-1] <= 0:
            return None

        ma10 = self._tail_mean(close, 10)
        ma20 = self._tail_mean(close, 20)
        ma60 = self._tail_mean(close, 60)
        avg_amount20 = self._tail_mean(amount, 20)
        if ma20 <= 0 or ma60 <= 0 or avg_amount20 < self.min_amount:
            return None

        ret5 = self._window_return(close, 5)
        ret20 = self._window_return(close, 20)
        ret60 = self._window_return(close, 60)
        close_to_ma20 = close[-1] / (ma20 + 1e-8) - 1.0
        close_to_ma60 = close[-1] / (ma60 + 1e-8) - 1.0
        top60 = float(np.max(high[-60:])) if len(high) >= 60 else float(np.max(high))
        drawdown60 = close[-1] / (top60 + 1e-8) - 1.0 if top60 > 0 else 0.0
        top_distance = max(0.0, top60 / (close[-1] + 1e-8) - 1.0)
        if top_distance > self.max_top_distance:
            return None
        if close_to_ma60 < (self.min_close_to_ma60 - 1.0) and ret60 < self.min_ret60:
            return None

        vol_ratio5 = self._tail_mean(amount, 5) / (avg_amount20 + 1e-8)
        returns = pd.Series(close).pct_change().replace([np.inf, -np.inf], np.nan).fillna(0.0).to_numpy()
        volatility20 = float(np.nanstd(returns[-20:])) if len(returns) >= 20 else 0.0
        downside_window = returns[-20:] if len(returns) >= 20 else returns
        downside_only = downside_window[downside_window < 0]
        downside_vol20 = float(np.nanstd(downside_only)) if len(downside_only) > 0 else 0.0
        prev_close = np.roll(close, 1)
        prev_close[0] = close[0]
        amplitude20 = float(
            np.nanmean(((high[-20:] - low[-20:]) / (prev_close[-20:] + 1e-8)))
        ) if len(close) >= 20 else 0.0
        amplitude1 = float((high[-1] - low[-1]) / (prev_close[-1] + 1e-8)) if prev_close[-1] > 0 else 0.0
        range_last = max(high[-1] - low[-1], 1e-8)
        upper_shadow = max(high[-1] - max(open_[-1], close[-1]), 0.0) / range_last
        prev_day_close = float(close[-2]) if len(close) >= 2 else float(close[-1])
        gap_pct = float(open_[-1] / (prev_day_close + 1e-8) - 1.0) if prev_day_close > 0 else 0.0
        pct_chg_day = float(pct_chg[-1] / 100.0) if len(pct_chg) else 0.0
        down_days = 0
        for value in pct_chg[::-1]:
            if float(value) < 0:
                down_days += 1
            else:
                break
        down_day_ratio20 = float(np.mean(returns[-20:] < 0)) if len(returns) >= 20 else 0.5
        ma_stack_score = (
            100.0
            if ma10 > ma20 > ma60
            else 72.0
            if ma20 > ma60 and close[-1] >= ma20
            else 45.0
            if close[-1] >= ma60
            else 20.0
        )
        industry_score = self._score_industry(industry_strength)

        trend_score = (
            self._linear_score(ret20, 0.01, 0.18) * 0.28
            + self._linear_score(ret60, 0.03, 0.35) * 0.24
            + self._linear_score(close_to_ma20, 0.00, 0.08) * 0.14
            + self._linear_score(close_to_ma60, 0.00, 0.18) * 0.14
            + self._inverse_linear_score(top_distance, 0.00, 0.12) * 0.10
            + ma_stack_score * 0.10
        )

        pullback_depth = max(0.0, -drawdown60)
        pullback_score = (
            self._band_score(pullback_depth, 0.00, 0.03, 0.10, 0.18) * 0.28
            + self._band_score(close_to_ma20, -0.06, -0.02, 0.03, 0.10) * 0.24
            + self._band_score(ret5, -0.08, -0.03, 0.02, 0.08) * 0.18
            + self._band_score(vol_ratio5, 0.35, 0.60, 1.05, 1.80) * 0.14
            + self._linear_score(close_to_ma60, -0.01, 0.12) * 0.16
        )

        quality_score = (
            self._inverse_linear_score(downside_vol20, 0.012, 0.045) * 0.28
            + self._inverse_linear_score(amplitude20, 0.020, 0.085) * 0.24
            + self._inverse_linear_score(upper_shadow, 0.15, 0.60) * 0.18
            + self._inverse_linear_score(down_day_ratio20, 0.40, 0.70) * 0.12
            + self._linear_score(avg_amount20 / max(self.min_amount, 1.0), 1.0, 4.0) * 0.18
        )

        base_score = (
            trend_score * regime_weights["trend"]
            + pullback_score * regime_weights["pullback"]
            + quality_score * regime_weights["quality"]
            + industry_score * regime_weights["industry"]
        )

        risk_penalty_frac = (
            self._fraction_score(ret5, 0.06, 0.14) * 0.30
            + self._fraction_score(close_to_ma20, 0.07, 0.16) * 0.22
            + self._fraction_score(vol_ratio5, 1.80, 3.20) * 0.16
            + self._fraction_score(upper_shadow, 0.35, 0.75) * 0.12
            + self._fraction_score(volatility20, 0.032, 0.075) * 0.12
            + self._fraction_score(-close_to_ma60, 0.00, 0.08) * 0.08
        )
        risk_penalty = self.risk_penalty_weight * float(np.clip(risk_penalty_frac, 0.0, 1.0))
        total_score = float(np.clip(base_score - risk_penalty, 0.0, 100.0))

        if ret5 >= 0.12:
            return None
        if regime_decision.regime == "weak":
            if quality_score < max(self.min_quality_score, 55.0):
                return None
            if risk_penalty > self.risk_penalty_weight * 0.34:
                return None
            if vol_ratio5 > 1.45 or close_to_ma20 > 0.07:
                return None
        elif regime_decision.regime == "sideways":
            if quality_score < max(self.min_quality_score, 48.0):
                return None
            if risk_penalty > self.risk_penalty_weight * 0.42 and trend_score < 62.0:
                return None

        if quality_score < self.min_quality_score or total_score < dynamic_threshold:
            return None

        level = (
            "strong"
            if total_score >= 72
            else "medium"
            if total_score >= 64
            else "watch"
        )

        name = str(daily_df["name"].iloc[0] or "")
        industry = str(daily_df["industry"].iloc[0] or "")
        return {
            "ts_code": ts_code,
            "name": name,
            "industry": industry,
            "total_score": round(total_score, 2),
            "level": level,
            "strategy_profile": "institutional_core",
            "strategy_label": "机构核心策略",
            "institutional_core_raw": round(base_score - risk_penalty, 4),
            "market_below_ma20": regime_decision.regime == "weak",
            "regime_name": regime_decision.regime,
            "regime_reason": regime_decision.reason,
            "regime_top_n_multiplier": float(regime_decision.top_n_multiplier),
            "score_breakdown": {
                "trend": round(trend_score, 2),
                "pullback": round(pullback_score, 2),
                "quality": round(quality_score, 2),
                "industry": round(industry_score, 2),
                "risk_penalty": round(risk_penalty, 2),
            },
            "signal_score": round(total_score, 2),
            "risk_flags": self._build_risk_flags(
                ret5=ret5,
                close_to_ma20=close_to_ma20,
                vol_ratio5=vol_ratio5,
                upper_shadow=upper_shadow,
                volatility20=volatility20,
            ),
            "metrics": {
                "ret5": round(ret5, 4),
                "ret20": round(ret20, 4),
                "ret60": round(ret60, 4),
                "close_to_ma20": round(close_to_ma20, 4),
                "close_to_ma60": round(close_to_ma60, 4),
                "drawdown60": round(drawdown60, 4),
                "pct_chg_day": round(pct_chg_day, 4),
                "vol_ratio5": round(vol_ratio5, 4),
                "avg_amount20": round(avg_amount20, 2),
                "upper_shadow": round(upper_shadow, 4),
                "upper_shadow_day": round(upper_shadow, 4),
                "gap_pct": round(gap_pct, 4),
                "amplitude1": round(amplitude1, 4),
                "downside_vol20": round(downside_vol20, 4),
                "amplitude20": round(amplitude20, 4),
                "down_days": int(down_days),
                "recent_limit_up_count20": int(np.sum(pct_chg[-20:] >= 9.7)) if len(pct_chg) >= 20 else 0,
            },
        }

    def _get_regime_weights(self, regime: str) -> Dict[str, float]:
        mapping = {
            "trend": {"trend": 0.42, "pullback": 0.20, "quality": 0.23, "industry": 0.15},
            "sideways": {"trend": 0.26, "pullback": 0.34, "quality": 0.24, "industry": 0.16},
            "weak": {"trend": 0.14, "pullback": 0.28, "quality": 0.38, "industry": 0.20},
        }
        return mapping.get(regime, {"trend": 0.30, "pullback": 0.28, "quality": 0.27, "industry": 0.15})

    def _get_dynamic_threshold(self, regime: str) -> float:
        base = self.score_threshold
        if regime == "trend":
            return base - 1.0
        if regime == "weak":
            return base + 4.0
        return base + 1.0

    def _score_industry(self, industry_strength: Optional[Dict]) -> float:
        if not isinstance(industry_strength, dict):
            return 50.0

        heat_score = float(industry_strength.get("heat_score", 50.0) or 50.0)
        rank = int(industry_strength.get("rank", 999) or 999)
        stock_count = int(industry_strength.get("stock_count", 0) or 0)

        rank_bonus = 12.0 if rank <= 5 else 7.0 if rank <= 12 else 0.0
        depth_bonus = 6.0 if stock_count >= 20 else 2.0 if stock_count >= 10 else 0.0
        return float(np.clip(heat_score + rank_bonus + depth_bonus, 0.0, 100.0))

    def _build_risk_flags(
        self,
        ret5: float,
        close_to_ma20: float,
        vol_ratio5: float,
        upper_shadow: float,
        volatility20: float,
    ) -> List[str]:
        flags: List[str] = []
        if ret5 >= 0.08 or close_to_ma20 >= 0.09:
            flags.append("chasing_extension")
        if vol_ratio5 >= 1.9:
            flags.append("volume_spike")
        if upper_shadow >= 0.40:
            flags.append("upper_shadow")
        if volatility20 >= 0.04:
            flags.append("high_volatility")
        return flags

    def _decide_regime(self, end_date: str):
        if self.regime_router is not None:
            try:
                return self.regime_router.decide(end_date=end_date)
            except Exception as exc:
                logger.warning("机构核心策略状态路由失败，回退neutral: %s", exc)

        class _Fallback:
            regime = "neutral"
            reason = "fallback"
            top_n_multiplier = 1.0

        return _Fallback()

    @staticmethod
    def _tail_mean(arr: np.ndarray, window: int) -> float:
        if len(arr) < max(1, int(window)):
            return float(np.mean(arr)) if len(arr) else 0.0
        return float(np.mean(arr[-int(window):]))

    @staticmethod
    def _window_return(close: np.ndarray, periods: int) -> float:
        periods = max(1, int(periods))
        if len(close) <= periods or close[-periods - 1] <= 0:
            return 0.0
        return float(close[-1] / close[-periods - 1] - 1.0)

    @staticmethod
    def _fraction_score(value: float, low: float, high: float) -> float:
        if high <= low:
            return 0.0
        return float(np.clip((value - low) / (high - low), 0.0, 1.0))

    @staticmethod
    def _linear_score(value: float, low: float, high: float) -> float:
        return InstitutionalCoreSelector._fraction_score(value, low, high) * 100.0

    @staticmethod
    def _inverse_linear_score(value: float, low: float, high: float) -> float:
        return (1.0 - InstitutionalCoreSelector._fraction_score(value, low, high)) * 100.0

    @staticmethod
    def _band_score(value: float, low: float, inner_low: float, inner_high: float, high: float) -> float:
        if inner_low < low:
            inner_low = low
        if high < inner_high:
            inner_high = high
        if value <= low or value >= high:
            return 0.0
        if inner_low <= value <= inner_high:
            return 100.0
        if value < inner_low:
            return InstitutionalCoreSelector._linear_score(value, low, inner_low)
        return InstitutionalCoreSelector._inverse_linear_score(value, inner_high, high)
