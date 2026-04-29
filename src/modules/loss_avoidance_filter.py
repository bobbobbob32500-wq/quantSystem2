# -*- coding: utf-8 -*-
"""Loss-avoidance filter for high-score but fragile candidates."""

from __future__ import annotations

from typing import Dict, List, Tuple

from src.core.logger import get_logger

logger = get_logger("loss_avoidance_filter")


class LossAvoidanceFilter:
    """Rule-based negative-sample guard distilled from failure studies."""

    def __init__(self, config):
        self.config = config
        prefix = "stock_selection.loss_avoidance"
        self.enabled = bool(config.get(f"{prefix}.enabled", True))
        self.apply_profiles = {
            str(item or "").strip().lower()
            for item in (
                config.get(f"{prefix}.apply_profiles", ["institutional_core", "alpha158"])
                if isinstance(config.get(f"{prefix}.apply_profiles", ["institutional_core", "alpha158"]), list)
                else ["institutional_core", "alpha158"]
            )
        }
        self.trend_block_score = float(config.get(f"{prefix}.trend_block_score", 2.3) or 2.3)
        self.sideways_block_score = float(config.get(f"{prefix}.sideways_block_score", 1.5) or 1.5)
        self.weak_block_score = float(config.get(f"{prefix}.weak_block_score", 1.1) or 1.1)

    def should_apply(self, strategy_profile: str) -> bool:
        return self.enabled and str(strategy_profile or "").strip().lower() in self.apply_profiles

    def apply(
        self,
        results: List[Dict],
        regime_name: str = "",
    ) -> Tuple[List[Dict], Dict]:
        if not self.enabled or not results:
            return list(results or []), {"enabled": False, "reason": "disabled_or_empty"}

        kept: List[Dict] = []
        blocked: List[Dict] = []
        regime_name = str(regime_name or "").strip().lower()

        for item in results:
            decision = self._evaluate_candidate(item=item, regime_name=regime_name)
            item["loss_avoidance_score"] = round(float(decision["score"]), 2)
            item["loss_avoidance_flags"] = list(decision["flags"])
            item["loss_avoidance_reason"] = str(decision["reason"])
            if bool(decision["blocked"]):
                blocked.append(
                    {
                        "ts_code": str(item.get("ts_code", "")),
                        "reason": str(decision["reason"]),
                        "score": round(float(decision["score"]), 2),
                        "flags": list(decision["flags"]),
                    }
                )
                continue
            kept.append(item)

        logger.info(
            "失败样本规避层: kept=%d blocked=%d regime=%s",
            len(kept),
            len(blocked),
            regime_name or "unknown",
        )
        return kept, {
            "enabled": True,
            "regime_name": regime_name,
            "kept": len(kept),
            "blocked": len(blocked),
            "blocked_examples": blocked[:8],
        }

    def _evaluate_candidate(self, item: Dict, regime_name: str) -> Dict:
        metrics = item.get("metrics") or {}
        score_breakdown = item.get("score_breakdown") or {}
        total_score = float(item.get("score_normalized", item.get("total_score", 0.0)) or 0.0)
        quality_score = float(score_breakdown.get("quality", total_score) or total_score)
        trend_score = float(score_breakdown.get("trend", total_score) or total_score)

        pct_chg_day = float(metrics.get("pct_chg_day", 0.0) or 0.0)
        ret5 = float(metrics.get("ret5", 0.0) or 0.0)
        amplitude1 = float(metrics.get("amplitude1", 0.0) or 0.0)
        vol_ratio5 = float(metrics.get("vol_ratio5", 1.0) or 1.0)
        upper_shadow_day = float(metrics.get("upper_shadow_day", 0.0) or 0.0)
        gap_pct = float(metrics.get("gap_pct", 0.0) or 0.0)
        down_days = int(metrics.get("down_days", 0) or 0)
        recent_limit_up_count20 = int(metrics.get("recent_limit_up_count20", 0) or 0)
        close_to_ma20 = float(metrics.get("close_to_ma20", 0.0) or 0.0)

        score = 0.0
        flags: List[str] = []

        if pct_chg_day <= -0.05:
            score += 1.25
            flags.append("deep_negative_day")
        elif pct_chg_day <= -0.03:
            score += 0.80
            flags.append("negative_day")

        if ret5 <= -0.08:
            score += 0.75
            flags.append("weak_last_5d")
        elif ret5 <= -0.05 and pct_chg_day < 0:
            score += 0.45
            flags.append("weak_last_5d_with_red_day")

        if amplitude1 >= 0.10:
            score += 0.95
            flags.append("extreme_amplitude")
        elif amplitude1 >= 0.08:
            score += 0.55
            flags.append("high_amplitude")

        if upper_shadow_day >= 0.50:
            score += 0.85
            flags.append("long_upper_shadow")
        elif upper_shadow_day >= 0.40:
            score += 0.50
            flags.append("upper_shadow")

        if vol_ratio5 >= 1.30:
            score += 0.35
            flags.append("high_volume")
        if down_days >= 3:
            score += 0.35
            flags.append("multi_down_days")
        if recent_limit_up_count20 >= 2 and upper_shadow_day >= 0.30:
            score += 0.35
            flags.append("blowoff_risk")
        if gap_pct >= 0.04 and upper_shadow_day >= 0.30:
            score += 0.35
            flags.append("gap_up_exhaustion")
        if close_to_ma20 >= 0.08 and vol_ratio5 >= 1.20:
            score += 0.30
            flags.append("extended_with_heat")

        # Research-derived combo rules.
        if pct_chg_day <= -0.03 and upper_shadow_day >= 0.30:
            score += 0.80
            flags.append("combo_red_day_upper_shadow")
        if amplitude1 >= 0.08 and vol_ratio5 >= 1.00:
            score += 0.55
            flags.append("combo_amplitude_volume")
        if pct_chg_day <= -0.03 and vol_ratio5 >= 0.90:
            score += 0.45
            flags.append("combo_red_day_volume")

        hard_block = False
        reason = "pass"
        if pct_chg_day <= -0.05:
            hard_block = True
            reason = "hard_block_deep_negative_day"
        elif pct_chg_day <= -0.03 and upper_shadow_day >= 0.30:
            hard_block = True
            reason = "hard_block_red_day_upper_shadow"
        elif amplitude1 >= 0.10 and quality_score < 82.0:
            hard_block = True
            reason = "hard_block_extreme_amplitude"

        threshold = self._threshold_for_regime(regime_name)
        if regime_name == "trend" and trend_score >= 82.0 and quality_score >= 74.0:
            threshold += 0.35
        if regime_name == "weak" and close_to_ma20 >= 0.04:
            threshold -= 0.15

        blocked = hard_block or score >= threshold
        if blocked and reason == "pass":
            reason = f"risk_score_{score:.2f}_ge_{threshold:.2f}"

        return {
            "blocked": bool(blocked),
            "score": float(score),
            "flags": flags,
            "reason": reason,
        }

    def _threshold_for_regime(self, regime_name: str) -> float:
        if regime_name == "trend":
            return self.trend_block_score
        if regime_name == "weak":
            return self.weak_block_score
        return self.sideways_block_score
