# -*- coding: utf-8 -*-
"""Daily abstain guard for strategy selection."""

from __future__ import annotations

from typing import Dict, List

import numpy as np

from src.core.logger import get_logger

logger = get_logger("selection_abstain_guard")


class SelectionAbstainGuard:
    """Decide whether a strategy should abstain on a given day."""

    def __init__(self, config):
        self.config = config
        prefix = "stock_selection.abstain_guard"
        self.enabled = bool(config.get(f"{prefix}.enabled", True))
        raw_profiles = config.get(f"{prefix}.apply_profiles", ["alpha158"])
        if not isinstance(raw_profiles, list):
            raw_profiles = ["alpha158"]
        self.apply_profiles = {str(item or "").strip().lower() for item in raw_profiles}
        self.trend_top1_min_score = float(config.get(f"{prefix}.trend_top1_min_score", 58.0) or 58.0)
        self.sideways_top1_min_score = float(config.get(f"{prefix}.sideways_top1_min_score", 62.0) or 62.0)
        self.weak_top1_min_score = float(config.get(f"{prefix}.weak_top1_min_score", 66.0) or 66.0)
        self.trend_top3_avg_min_score = float(config.get(f"{prefix}.trend_top3_avg_min_score", 56.0) or 56.0)
        self.sideways_top3_avg_min_score = float(config.get(f"{prefix}.sideways_top3_avg_min_score", 60.0) or 60.0)
        self.weak_top3_avg_min_score = float(config.get(f"{prefix}.weak_top3_avg_min_score", 64.0) or 64.0)
        self.max_avg_loss_avoidance_score = float(
            config.get(f"{prefix}.max_avg_loss_avoidance_score", 0.90) or 0.90
        )
        self.sideways_min_candidates = max(2, int(config.get(f"{prefix}.sideways_min_candidates", 2) or 2))
        self.weak_min_candidates = max(1, int(config.get(f"{prefix}.weak_min_candidates", 2) or 2))
        self.sideways_single_candidate_min_score = float(
            config.get(f"{prefix}.sideways_single_candidate_min_score", 76.0) or 76.0
        )
        self.weak_single_candidate_min_score = float(
            config.get(f"{prefix}.weak_single_candidate_min_score", 76.0) or 76.0
        )
        self.weak_force_abstain_if_market_below_ma20 = bool(
            config.get(f"{prefix}.weak_force_abstain_if_market_below_ma20", False)
        )
        self.route_aware_positioning_enabled = bool(
            config.get(f"{prefix}.route_aware_positioning_enabled", True)
        )
        self.dynamic_route_min_count = max(1, int(config.get(f"{prefix}.dynamic_route_min_count", 1) or 1))
        self.sideways_keep_n_with_dynamic = max(
            1, int(config.get(f"{prefix}.sideways_keep_n_with_dynamic", 3) or 3)
        )
        self.sideways_keep_n_without_dynamic = max(
            0, int(config.get(f"{prefix}.sideways_keep_n_without_dynamic", 2) or 2)
        )
        self.weak_keep_n_with_dynamic = max(
            0, int(config.get(f"{prefix}.weak_keep_n_with_dynamic", 1) or 1)
        )
        self.weak_keep_n_without_dynamic = max(
            0, int(config.get(f"{prefix}.weak_keep_n_without_dynamic", 1) or 1)
        )

    def should_apply(self, strategy_profile: str) -> bool:
        return self.enabled and str(strategy_profile or "").strip().lower() in self.apply_profiles

    def decide(
        self,
        results: List[Dict],
        strategy_profile: str,
        regime_name: str,
        market_below_ma20: bool,
        effective_top_n: int,
    ) -> Dict:
        if not self.should_apply(strategy_profile):
            return {"enabled": False, "abstain": False, "effective_top_n": int(effective_top_n)}

        regime = str(regime_name or "").strip().lower()
        effective_top_n = max(0, int(effective_top_n))
        if effective_top_n <= 0:
            return {
                "enabled": True,
                "abstain": True,
                "reason": "effective_top_n_zero",
                "effective_top_n": 0,
            }
        if not results:
            return {
                "enabled": True,
                "abstain": True,
                "reason": "no_candidates",
                "effective_top_n": 0,
            }

        top_slice = results[: max(1, min(3, len(results)))]
        top1_score = float(
            top_slice[0].get(
                "abstain_score",
                top_slice[0].get("score_normalized", top_slice[0].get("total_score", 0.0)),
            )
            or 0.0
        )
        top3_avg = float(
            np.mean(
                [
                    float(
                        item.get(
                            "abstain_score",
                            item.get("score_normalized", item.get("total_score", 0.0)),
                        )
                        or 0.0
                    )
                    for item in top_slice
                ]
            )
        )
        avg_loss_score = float(
            np.mean([float(item.get("loss_avoidance_score", 0.0) or 0.0) for item in top_slice])
        )
        risk_flag_mean = float(
            np.mean([len(list(item.get("risk_flags") or [])) for item in top_slice])
        )
        candidate_count = len(results)
        dynamic_route_count = int(
            sum(
                1
                for item in results
                if str(item.get("holding_route", "fixed_t5") or "fixed_t5").strip().lower() != "fixed_t5"
            )
        )

        top1_floor = self._top1_floor(regime)
        top3_floor = self._top3_floor(regime)

        reason = "pass"
        abstain = False
        adjusted_top_n = effective_top_n

        if regime == "weak" and self.weak_force_abstain_if_market_below_ma20 and market_below_ma20:
            abstain = True
            reason = "weak_market_below_ma20"
        elif top1_score < top1_floor:
            abstain = True
            reason = f"top1_score_{top1_score:.2f}_lt_{top1_floor:.2f}"
        elif top3_avg < top3_floor:
            abstain = True
            reason = f"top3_avg_{top3_avg:.2f}_lt_{top3_floor:.2f}"
        elif avg_loss_score > self.max_avg_loss_avoidance_score:
            abstain = True
            reason = f"avg_loss_avoidance_{avg_loss_score:.2f}_gt_{self.max_avg_loss_avoidance_score:.2f}"
        elif regime == "weak" and candidate_count < self.weak_min_candidates:
            if self._allow_single_candidate_override(
                regime=regime,
                candidate_count=candidate_count,
                top1_score=top1_score,
                avg_loss_score=avg_loss_score,
                risk_flag_mean=risk_flag_mean,
            ):
                adjusted_top_n = 1
                reason = "weak_single_candidate_override"
            else:
                abstain = True
                reason = "weak_candidate_count_too_small"
        elif regime == "sideways" and candidate_count < self.sideways_min_candidates:
            if self._allow_single_candidate_override(
                regime=regime,
                candidate_count=candidate_count,
                top1_score=top1_score,
                avg_loss_score=avg_loss_score,
                risk_flag_mean=risk_flag_mean,
            ):
                adjusted_top_n = 1
                reason = "sideways_single_candidate_override"
            else:
                abstain = True
                reason = "sideways_candidate_count_too_small"
        elif regime == "weak":
            if self.route_aware_positioning_enabled:
                route_keep_n = (
                    self.weak_keep_n_with_dynamic
                    if dynamic_route_count >= self.dynamic_route_min_count
                    else self.weak_keep_n_without_dynamic
                )
                adjusted_top_n = min(effective_top_n, route_keep_n)
                reason = "weak_route_aware_positions"
            else:
                adjusted_top_n = min(effective_top_n, 1 if risk_flag_mean >= 1.0 else 2)
                reason = "weak_reduce_positions"
        elif regime == "sideways":
            if self.route_aware_positioning_enabled:
                route_keep_n = (
                    self.sideways_keep_n_with_dynamic
                    if dynamic_route_count >= self.dynamic_route_min_count
                    else self.sideways_keep_n_without_dynamic
                )
                adjusted_top_n = min(effective_top_n, route_keep_n)
                reason = "sideways_route_aware_positions"
            else:
                adjusted_top_n = min(effective_top_n, 2 if risk_flag_mean >= 1.0 else 3)
                reason = "sideways_reduce_positions"

        meta = {
            "enabled": True,
            "abstain": bool(abstain),
            "reason": reason,
            "effective_top_n": 0 if abstain else int(max(1, adjusted_top_n)),
            "regime_name": regime,
            "market_below_ma20": bool(market_below_ma20),
            "top1_score": round(top1_score, 2),
            "top3_avg_score": round(top3_avg, 2),
            "avg_loss_avoidance_score": round(avg_loss_score, 2),
            "risk_flag_mean": round(risk_flag_mean, 2),
            "dynamic_route_count": int(dynamic_route_count),
            "candidate_count": candidate_count,
        }
        logger.info(
            "abstain guard: profile=%s regime=%s abstain=%s top1=%.2f top3=%.2f reason=%s",
            strategy_profile,
            regime,
            abstain,
            top1_score,
            top3_avg,
            reason,
        )
        return meta

    def _top1_floor(self, regime: str) -> float:
        if regime == "trend":
            return self.trend_top1_min_score
        if regime == "weak":
            return self.weak_top1_min_score
        return self.sideways_top1_min_score

    def _top3_floor(self, regime: str) -> float:
        if regime == "trend":
            return self.trend_top3_avg_min_score
        if regime == "weak":
            return self.weak_top3_avg_min_score
        return self.sideways_top3_avg_min_score

    def _allow_single_candidate_override(
        self,
        regime: str,
        candidate_count: int,
        top1_score: float,
        avg_loss_score: float,
        risk_flag_mean: float,
    ) -> bool:
        if candidate_count != 1:
            return False
        if avg_loss_score > self.max_avg_loss_avoidance_score:
            return False
        if risk_flag_mean > 1.0:
            return False
        if regime == "weak":
            return top1_score >= self.weak_single_candidate_min_score
        if regime == "sideways":
            return top1_score >= self.sideways_single_candidate_min_score
        return False
