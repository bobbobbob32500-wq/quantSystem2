# -*- coding: utf-8 -*-
"""Dynamic position sizing for alpha158 protected selections."""

from __future__ import annotations

from typing import Dict, List

import numpy as np


class Alpha158PositionSizer:
    """Allocate daily portfolio weights from alpha158 protected candidates."""

    def __init__(self, config):
        self.config = config
        prefix = "stock_selection.position_sizing"
        self.enabled = bool(config.get(f"{prefix}.enabled", True))
        self.mode = str(config.get(f"{prefix}.mode", "score_weighted") or "score_weighted").strip().lower()
        self.apply_profiles = {
            str(item or "").strip().lower()
            for item in (
                config.get(f"{prefix}.apply_profiles", ["alpha158"])
                if isinstance(config.get(f"{prefix}.apply_profiles", ["alpha158"]), list)
                else ["alpha158"]
            )
        }
        self.trend_gross_exposure = float(config.get(f"{prefix}.trend_gross_exposure", 1.00) or 1.00)
        self.sideways_gross_exposure = float(config.get(f"{prefix}.sideways_gross_exposure", 0.72) or 0.72)
        self.weak_gross_exposure = float(config.get(f"{prefix}.weak_gross_exposure", 0.45) or 0.45)
        self.market_below_ma20_multiplier = float(
            config.get(f"{prefix}.market_below_ma20_multiplier", 0.75) or 0.75
        )
        self.score_power = float(config.get(f"{prefix}.score_power", 1.35) or 1.35)
        self.top_rank_boost = float(config.get(f"{prefix}.top_rank_boost", 0.18) or 0.18)
        self.loss_penalty_weight = float(config.get(f"{prefix}.loss_penalty_weight", 0.28) or 0.28)
        self.risk_flag_penalty = float(config.get(f"{prefix}.risk_flag_penalty", 0.12) or 0.12)
        self.sideways_risk_penalty_multiplier = float(
            config.get(f"{prefix}.sideways_risk_penalty_multiplier", 1.10) or 1.10
        )
        self.weak_risk_penalty_multiplier = float(
            config.get(f"{prefix}.weak_risk_penalty_multiplier", 1.25) or 1.25
        )
        self.dynamic_hold_route_boost = float(
            config.get(f"{prefix}.dynamic_hold_route_boost", 0.0) or 0.0
        )
        self.quality_route_boost = float(
            config.get(f"{prefix}.quality_route_boost", 0.0) or 0.0
        )
        self.pullback_route_boost = float(
            config.get(f"{prefix}.pullback_route_boost", 0.0) or 0.0
        )
        self.short_hold_penalty = float(
            config.get(f"{prefix}.short_hold_penalty", 0.0) or 0.0
        )
        self.single_name_cap = float(config.get(f"{prefix}.single_name_cap", 0.40) or 0.40)
        self.min_name_weight = float(config.get(f"{prefix}.min_name_weight", 0.08) or 0.08)

    def should_apply(self, strategy_profile: str) -> bool:
        return self.enabled and str(strategy_profile or "").strip().lower() in self.apply_profiles

    def allocate(
        self,
        results: List[Dict],
        strategy_profile: str,
    ) -> List[Dict]:
        rows = [dict(item) for item in (results or [])]
        if not rows or not self.should_apply(strategy_profile):
            for item in rows:
                item["position_weight"] = round(1.0 / len(rows), 6) if rows else 0.0
                item["position_weight_meta"] = {"enabled": False}
            return rows

        regime_name = str(rows[0].get("regime_name", rows[0].get("alpha158_regime", "")) or "").strip().lower()
        market_below_ma20 = bool(rows[0].get("market_below_ma20", False))
        gross_exposure = self._gross_exposure(regime_name, market_below_ma20)
        if self.mode == "risk_budget_equal_weight":
            weights, meta = self._allocate_risk_budget_equal_weight(rows=rows, gross_exposure=gross_exposure)
            for item, weight in zip(rows, weights):
                item["position_weight"] = round(float(weight), 6)
                item["position_strength"] = round(float(weight), 6)
                item["position_weight_meta"] = dict(meta)
            return rows

        raw_strengths: List[float] = []
        for rank, item in enumerate(rows, start=1):
            score = float(item.get("score_normalized", item.get("total_score", 50.0)) or 50.0)
            loss_score = float(item.get("loss_avoidance_score", 0.0) or 0.0)
            risk_flags = len(list(item.get("risk_flags") or []))
            holding_route = str(item.get("holding_route", "fixed_t5") or "fixed_t5").strip().lower()
            prototype_label = str(item.get("alpha158_prototype_label", "") or "").strip().lower()
            suggested_hold_days = int(float(item.get("suggested_hold_days", 5) or 5))
            score_component = max(0.05, (max(score - 50.0, 0.0) + 8.0) / 58.0) ** self.score_power
            rank_component = max(0.65, 1.0 - self.top_rank_boost * (rank - 1))
            loss_penalty = max(0.40, 1.0 - loss_score * self.loss_penalty_weight)
            risk_penalty = max(0.45, 1.0 - risk_flags * self.risk_flag_penalty * self._risk_regime_multiplier(regime_name))
            route_multiplier = 1.0
            if holding_route != "fixed_t5":
                route_multiplier += self.dynamic_hold_route_boost
            if prototype_label == "quality":
                route_multiplier += self.quality_route_boost
            elif prototype_label == "pullback":
                route_multiplier += self.pullback_route_boost
            if suggested_hold_days <= 3:
                route_multiplier *= max(0.70, 1.0 - self.short_hold_penalty)
            raw_strengths.append(score_component * rank_component * loss_penalty * risk_penalty * route_multiplier)

        weights = self._cap_and_normalize(raw_strengths, gross_exposure)
        meta = {
            "enabled": True,
            "gross_exposure": round(float(gross_exposure), 4),
            "regime_name": regime_name,
            "market_below_ma20": market_below_ma20,
            "single_name_cap": round(float(self.single_name_cap), 4),
            "dynamic_hold_route_boost": round(float(self.dynamic_hold_route_boost), 4),
            "mode": self.mode,
        }
        for item, weight, strength in zip(rows, weights, raw_strengths):
            item["position_weight"] = round(float(weight), 6)
            item["position_strength"] = round(float(strength), 6)
            item["position_weight_meta"] = dict(meta)
        return rows

    def _allocate_risk_budget_equal_weight(
        self,
        rows: List[Dict],
        gross_exposure: float,
    ) -> tuple[List[float], Dict]:
        n = max(1, len(rows))
        per_name = float(min(self.single_name_cap, gross_exposure / n))
        if per_name < 0:
            per_name = 0.0
        weights = [per_name for _ in rows]
        allocated = float(sum(weights))
        meta = {
            "enabled": True,
            "mode": "risk_budget_equal_weight",
            "gross_exposure_target": round(float(gross_exposure), 4),
            "gross_exposure_allocated": round(float(allocated), 4),
            "cash_buffer": round(max(0.0, float(gross_exposure) - float(allocated)), 4),
            "single_name_cap": round(float(self.single_name_cap), 4),
            "name_count": int(len(rows)),
        }
        return weights, meta

    def _gross_exposure(self, regime_name: str, market_below_ma20: bool) -> float:
        if regime_name == "trend":
            exposure = self.trend_gross_exposure
        elif regime_name == "weak":
            exposure = self.weak_gross_exposure
        else:
            exposure = self.sideways_gross_exposure
        if market_below_ma20:
            exposure *= self.market_below_ma20_multiplier
        return float(np.clip(exposure, 0.15, 1.0))

    def _risk_regime_multiplier(self, regime_name: str) -> float:
        if regime_name == "weak":
            return self.weak_risk_penalty_multiplier
        if regime_name == "sideways":
            return self.sideways_risk_penalty_multiplier
        return 1.0

    def _cap_and_normalize(self, strengths: List[float], gross_exposure: float) -> List[float]:
        if not strengths:
            return []
        arr = np.asarray(strengths, dtype=float)
        arr = np.where(np.isfinite(arr), arr, 0.0)
        arr = np.clip(arr, 0.001, None)
        weights = arr / arr.sum()
        weights = weights * gross_exposure

        cap = max(self.min_name_weight, min(self.single_name_cap, gross_exposure))
        for _ in range(8):
            over = weights > cap
            if not np.any(over):
                break
            excess = float(weights[over].sum() - cap * np.sum(over))
            weights[over] = cap
            under = ~over
            if excess <= 0 or not np.any(under):
                break
            room = np.clip(cap - weights[under], 0.0, None)
            room_sum = float(room.sum())
            if room_sum <= 0:
                break
            weights[under] += excess * (room / room_sum)

        total = float(weights.sum())
        if total > 0:
            weights *= gross_exposure / total
        return weights.tolist()
