# -*- coding: utf-8 -*-
"""Portfolio gate for post-selection risk budgeting."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from src.core.logger import get_logger

logger = get_logger("portfolio_gate")


class PortfolioGate:
    """Greedy portfolio constructor with risk-budget constraints."""

    def __init__(self, config, db):
        self.config = config
        self.db = db
        prefix = "stock_selection.portfolio_gate"
        self.enabled = bool(config.get(f"{prefix}.enabled", True))
        self.shortlist_multiplier = max(2, int(config.get(f"{prefix}.shortlist_multiplier", 4) or 4))
        self.lookback_days = max(20, int(config.get(f"{prefix}.lookback_days", 40) or 40))
        self.min_history = max(15, int(config.get(f"{prefix}.min_history", 25) or 25))
        self.max_per_industry = max(1, int(config.get(f"{prefix}.max_per_industry", 2) or 2))
        self.max_pair_corr = float(config.get(f"{prefix}.max_pair_corr", 0.78) or 0.78)
        self.max_avg_corr = float(config.get(f"{prefix}.max_avg_corr", 0.55) or 0.55)
        self.max_hot_industry_slots = max(
            1, int(config.get(f"{prefix}.max_hot_industry_slots", 1) or 1)
        )
        self.max_risk_flags = max(1, int(config.get(f"{prefix}.max_risk_flags", 2) or 2))
        self.correlation_penalty_weight = float(
            config.get(f"{prefix}.correlation_penalty_weight", 10.0) or 10.0
        )
        self.crowding_penalty_weight = float(
            config.get(f"{prefix}.crowding_penalty_weight", 8.0) or 8.0
        )
        self.industry_penalty_weight = float(
            config.get(f"{prefix}.industry_penalty_weight", 5.0) or 5.0
        )
        self.allow_fallback_fill = bool(config.get(f"{prefix}.allow_fallback_fill", False))
        self.trend_max_positions = max(1, int(config.get(f"{prefix}.trend_max_positions", 4) or 4))
        self.sideways_max_positions = max(1, int(config.get(f"{prefix}.sideways_max_positions", 3) or 3))
        self.weak_max_positions = max(1, int(config.get(f"{prefix}.weak_max_positions", 2) or 2))
        self.trend_min_gate_score = float(config.get(f"{prefix}.trend_min_gate_score", 68.0) or 68.0)
        self.sideways_min_gate_score = float(config.get(f"{prefix}.sideways_min_gate_score", 72.0) or 72.0)
        self.weak_min_gate_score = float(config.get(f"{prefix}.weak_min_gate_score", 76.0) or 76.0)

    def apply(
        self,
        results: List[Dict],
        end_date: str,
        target_count: int,
        regime_name: str = "",
        industry_strength_map: Optional[Dict[str, Dict]] = None,
    ) -> Tuple[List[Dict], Dict]:
        if not self.enabled or not results:
            return list(results or []), {"enabled": False, "reason": "disabled_or_empty"}

        target_count = max(1, int(target_count))
        regime_cap = self._get_regime_position_cap(regime_name)
        target_count = min(target_count, regime_cap)
        min_gate_score = self._get_regime_min_gate_score(regime_name)
        shortlist_size = min(len(results), max(target_count, target_count * self.shortlist_multiplier))
        shortlist = [dict(item) for item in results[:shortlist_size]]
        if len(shortlist) <= target_count:
            return shortlist, {"enabled": True, "reason": "shortlist_small", "selected": len(shortlist)}

        corr_map, returns_map = self._load_recent_returns(
            symbols=[str(item.get("ts_code", "")) for item in shortlist],
            end_date=end_date,
        )
        industry_strength_map = industry_strength_map or {}
        hot_industries = {
            str(ind)
            for ind, info in industry_strength_map.items()
            if isinstance(info, dict) and int(info.get("rank", 999) or 999) <= 5
        }

        selected: List[Dict] = []
        selected_symbols: List[str] = []
        industry_counts: Dict[str, int] = {}
        hot_industry_counts: Dict[str, int] = {}
        blocked: List[Dict] = []

        for item in shortlist:
            if len(selected) >= target_count:
                break

            ts_code = str(item.get("ts_code", "") or "")
            industry = str(item.get("industry", "未知") or "未知")
            risk_flags = list(item.get("risk_flags") or [])
            item["recent_returns"] = returns_map.get(ts_code, [])

            allow, reason, corr_penalty = self._can_add(
                item=item,
                selected_symbols=selected_symbols,
                corr_map=corr_map,
                industry=industry,
                industry_counts=industry_counts,
                hot_industries=hot_industries,
                hot_industry_counts=hot_industry_counts,
                regime_name=regime_name,
            )
            crowding_penalty = self._crowding_penalty(
                item=item,
                industry=industry,
                hot_industries=hot_industries,
                industry_counts=industry_counts,
            )
            adjusted_score = float(item.get("score_normalized", item.get("total_score", 0.0))) - corr_penalty - crowding_penalty
            item["portfolio_gate_score"] = round(adjusted_score, 2)
            item["portfolio_gate_correlation_penalty"] = round(corr_penalty, 2)
            item["portfolio_gate_crowding_penalty"] = round(crowding_penalty, 2)
            item["portfolio_gate_reason"] = reason

            if adjusted_score < min_gate_score:
                blocked.append(
                    {
                        "ts_code": ts_code,
                        "industry": industry,
                        "reason": "gate_score_floor",
                        "risk_flags": risk_flags,
                    }
                )
                continue

            if not allow:
                blocked.append(
                    {
                        "ts_code": ts_code,
                        "industry": industry,
                        "reason": reason,
                        "risk_flags": risk_flags,
                    }
                )
                continue

            selected.append(item)
            selected_symbols.append(ts_code)
            industry_counts[industry] = industry_counts.get(industry, 0) + 1
            if industry in hot_industries:
                hot_industry_counts[industry] = hot_industry_counts.get(industry, 0) + 1

        if self.allow_fallback_fill and len(selected) < target_count:
            fill_candidates = sorted(
                [item for item in shortlist if str(item.get("ts_code", "")) not in set(selected_symbols)],
                key=lambda row: float(row.get("portfolio_gate_score", row.get("score_normalized", row.get("total_score", 0.0)))),
                reverse=True,
            )
            for item in fill_candidates:
                if len(selected) >= target_count:
                    break
                item["portfolio_gate_reason"] = str(item.get("portfolio_gate_reason", "fallback_fill"))
                if item["portfolio_gate_reason"] not in {"selected", "selected_weak_relaxed"}:
                    item["portfolio_gate_reason"] = "fallback_fill"
                selected.append(item)
                selected_symbols.append(str(item.get("ts_code", "")))

        selected.sort(
            key=lambda row: float(row.get("portfolio_gate_score", row.get("score_normalized", row.get("total_score", 0.0)))),
            reverse=True,
        )
        for rank, item in enumerate(selected, start=1):
            item["rank"] = rank

        meta = {
            "enabled": True,
            "target_count": target_count,
            "shortlist_size": shortlist_size,
            "selected": len(selected),
            "blocked_count": len(blocked),
            "blocked_examples": blocked[:8],
            "industry_counts": industry_counts,
            "hot_industry_counts": hot_industry_counts,
            "regime_name": regime_name,
            "min_gate_score": min_gate_score,
            "regime_cap": regime_cap,
        }
        return selected, meta

    def _can_add(
        self,
        item: Dict,
        selected_symbols: List[str],
        corr_map: Dict[Tuple[str, str], float],
        industry: str,
        industry_counts: Dict[str, int],
        hot_industries: set[str],
        hot_industry_counts: Dict[str, int],
        regime_name: str,
    ) -> Tuple[bool, str, float]:
        ts_code = str(item.get("ts_code", "") or "")
        risk_flags = list(item.get("risk_flags") or [])
        if len(risk_flags) > self.max_risk_flags:
            return False, "too_many_risk_flags", 0.0

        industry_cap = self.max_per_industry
        if regime_name == "weak":
            industry_cap = 1
        if industry_counts.get(industry, 0) >= industry_cap:
            return False, "industry_cap", 0.0

        if industry in hot_industries and hot_industry_counts.get(industry, 0) >= self.max_hot_industry_slots:
            return False, "hot_industry_cap", 0.0

        if not selected_symbols:
            return True, "selected", 0.0

        pair_corrs: List[float] = []
        for selected in selected_symbols:
            corr = corr_map.get((ts_code, selected), corr_map.get((selected, ts_code), 0.0))
            if np.isnan(corr):
                corr = 0.0
            pair_corrs.append(float(corr))

        max_corr = max(pair_corrs) if pair_corrs else 0.0
        avg_corr = float(np.mean(pair_corrs)) if pair_corrs else 0.0
        if max_corr > self.max_pair_corr:
            return False, "pair_corr_cap", self.correlation_penalty_weight * max(0.0, max_corr - self.max_pair_corr)
        if avg_corr > self.max_avg_corr:
            return False, "avg_corr_cap", self.correlation_penalty_weight * max(0.0, avg_corr - self.max_avg_corr)

        corr_penalty = self.correlation_penalty_weight * max(0.0, avg_corr - 0.25)
        if regime_name == "weak" and avg_corr > 0.40:
            return False, "weak_corr_cap", corr_penalty
        return True, "selected_weak_relaxed" if regime_name == "weak" else "selected", corr_penalty

    def _get_regime_position_cap(self, regime_name: str) -> int:
        if regime_name == "trend":
            return self.trend_max_positions
        if regime_name == "weak":
            return self.weak_max_positions
        return self.sideways_max_positions

    def _get_regime_min_gate_score(self, regime_name: str) -> float:
        if regime_name == "trend":
            return self.trend_min_gate_score
        if regime_name == "weak":
            return self.weak_min_gate_score
        return self.sideways_min_gate_score

    def _crowding_penalty(
        self,
        item: Dict,
        industry: str,
        hot_industries: set[str],
        industry_counts: Dict[str, int],
    ) -> float:
        penalty = 0.0
        risk_flags = set(item.get("risk_flags") or [])
        penalty += len(risk_flags) * (self.crowding_penalty_weight * 0.28)
        metrics = item.get("metrics") or {}
        vol_ratio5 = float(metrics.get("vol_ratio5", 1.0) or 1.0)
        recent_limit_up = int(metrics.get("recent_limit_up_count20", 0) or 0)
        if vol_ratio5 > 1.5:
            penalty += self.crowding_penalty_weight * min(1.0, (vol_ratio5 - 1.5) / 1.5)
        if recent_limit_up >= 2:
            penalty += self.crowding_penalty_weight * min(0.8, recent_limit_up * 0.18)
        if industry in hot_industries:
            penalty += self.industry_penalty_weight * (1.0 + industry_counts.get(industry, 0) * 0.4)
        return float(penalty)

    def _load_recent_returns(
        self,
        symbols: List[str],
        end_date: str,
    ) -> Tuple[Dict[Tuple[str, str], float], Dict[str, List[float]]]:
        cleaned = [str(symbol or "").strip().upper() for symbol in symbols if str(symbol or "").strip()]
        if not cleaned:
            return {}, {}

        end_dt = datetime.strptime(str(end_date), "%Y%m%d")
        start_date = (end_dt - timedelta(days=self.lookback_days * 2)).strftime("%Y%m%d")
        placeholders = ",".join(["?"] * len(cleaned))
        sql = f"""
            SELECT ts_code, trade_date, close
            FROM stock_daily
            WHERE ts_code IN ({placeholders})
              AND trade_date >= ? AND trade_date <= ?
            ORDER BY ts_code ASC, trade_date ASC
        """
        rows = self.db.query(sql, tuple(cleaned + [start_date, end_date]))
        if not rows:
            return {}, {}

        df = pd.DataFrame(rows)
        if df.empty:
            return {}, {}
        df["close"] = pd.to_numeric(df["close"], errors="coerce")
        df = df.dropna(subset=["close"]).copy()
        if df.empty:
            return {}, {}

        returns_map: Dict[str, List[float]] = {}
        series_map: Dict[str, pd.Series] = {}
        for ts_code, group in df.groupby("ts_code", sort=False):
            series = pd.Series(group["close"].astype(float).to_numpy()).pct_change().dropna()
            series = series.replace([np.inf, -np.inf], np.nan).dropna()
            if len(series) < self.min_history:
                continue
            tail = series.tail(self.lookback_days).reset_index(drop=True)
            returns_map[str(ts_code)] = tail.astype(float).tolist()
            series_map[str(ts_code)] = tail

        corr_map: Dict[Tuple[str, str], float] = {}
        symbols_ready = list(series_map.keys())
        for idx, left in enumerate(symbols_ready):
            left_vals = series_map[left]
            for right in symbols_ready[idx + 1 :]:
                right_vals = series_map[right]
                min_len = min(len(left_vals), len(right_vals))
                if min_len < self.min_history:
                    corr = 0.0
                else:
                    corr = float(np.corrcoef(left_vals.tail(min_len), right_vals.tail(min_len))[0, 1])
                    if np.isnan(corr):
                        corr = 0.0
                corr_map[(left, right)] = corr

        return corr_map, returns_map
