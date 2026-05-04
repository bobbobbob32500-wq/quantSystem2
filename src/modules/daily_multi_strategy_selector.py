# -*- coding: utf-8 -*-
"""Daily-only multi-strategy collaboration selector.

This module intentionally avoids minute-level confirmation. It combines
pre-market/daily-bar candidate sleeves into a single ranked list so we can
validate multi-strategy collaboration before re-introducing intraday routing.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List

import numpy as np
import pandas as pd

from src.core.config import ConfigManager
from src.core.database import DatabaseManager
from src.core.logger import get_logger
from src.modules.alpha158_regime_router import Alpha158RegimeRouter
from src.modules.breakout_strategy import (
    build_breakout_strategy_from_config,
    build_wide_breakout_strategy_from_config,
)
from src.modules.mainboard_secondary_launch_strategy import (
    MainboardSecondaryLaunchStrategy,
    StrategyParams,
)

logger = get_logger("daily_multi_strategy")


class DailyMultiStrategySelector:
    """Combine multiple daily-bar sleeves into one collaboration profile."""

    def __init__(
        self,
        config: ConfigManager,
        db: DatabaseManager,
        regime_router: Alpha158RegimeRouter,
    ) -> None:
        self.config = config
        self.db = db
        self.regime_router = regime_router
        prefix = "stock_selection.multi_strategy_daily"

        self.enabled = bool(config.get(f"{prefix}.enabled", True))
        self.lookback_days = int(config.get(f"{prefix}.lookback_days", 140))
        self.max_per_sleeve = int(config.get(f"{prefix}.max_per_sleeve", 4))
        self.top_n = int(config.get(f"{prefix}.top_n", 5))
        self.allow_breakout_in_sideways = bool(
            config.get(f"{prefix}.allow_breakout_in_sideways", False)
        )
        self.min_combined_score = float(
            config.get(f"{prefix}.min_combined_score", 58.0)
        )
        self.alpha_base_keep_ratio = float(
            config.get(f"{prefix}.alpha_base_keep_ratio", 0.8)
        )
        self.min_alpha_core_slots = int(
            config.get(f"{prefix}.min_alpha_core_slots", 3)
        )
        self.breakout_direct_slots = int(
            config.get(f"{prefix}.breakout_direct_slots", 1)
        )
        self.secondary_direct_slots = int(
            config.get(f"{prefix}.secondary_direct_slots", 0)
        )
        self.max_satellite_replacements = int(
            config.get(f"{prefix}.max_satellite_replacements", 1)
        )
        self.breakout_overlay_bonus = float(
            config.get(f"{prefix}.breakout_overlay_bonus", 6.0)
        )
        self.secondary_overlay_bonus = float(
            config.get(f"{prefix}.secondary_overlay_bonus", 4.0)
        )
        self.wide_breakout_overlay_bonus = float(
            config.get(f"{prefix}.wide_breakout_overlay_bonus", 5.0)
        )
        self.enable_secondary_overlay = bool(
            config.get(f"{prefix}.enable_secondary_overlay", False)
        )
        self.enable_wide_breakout_overlay = bool(
            config.get(f"{prefix}.enable_wide_breakout_overlay", False)
        )
        self.enable_satellite_fill = bool(
            config.get(f"{prefix}.enable_satellite_fill", False)
        )
        self.breakout_replace_threshold = float(
            config.get(f"{prefix}.breakout_replace_threshold", 88.0)
        )
        self.secondary_replace_threshold = float(
            config.get(f"{prefix}.secondary_replace_threshold", 90.0)
        )
        self.wide_breakout_replace_threshold = float(
            config.get(f"{prefix}.wide_breakout_replace_threshold", 90.0)
        )
        self.alpha_edge_threshold = float(
            config.get(f"{prefix}.alpha_edge_threshold", 62.0)
        )

        self.regime_sleeve_weights = {
            "trend": self._normalize_weight_map(
                config.get(
                    f"{prefix}.regime_sleeve_weights.trend",
                    {"alpha158": 0.58, "breakout": 0.32, "secondary_launch": 0.10},
                )
            ),
            "sideways": self._normalize_weight_map(
                config.get(
                    f"{prefix}.regime_sleeve_weights.sideways",
                    {"alpha158": 0.70, "breakout": 0.00, "secondary_launch": 0.30},
                )
            ),
            "weak": self._normalize_weight_map(
                config.get(
                    f"{prefix}.regime_sleeve_weights.weak",
                    {"alpha158": 0.85, "breakout": 0.00, "secondary_launch": 0.15},
                )
            ),
        }
        self._breakout_feature_cache: Dict[str, tuple[Any, pd.DataFrame]] = {}
        self._secondary_signal_cache: pd.DataFrame | None = None
        self._secondary_feature_cache: pd.DataFrame | None = None
        self._cache_dir = Path("data/cache")

    @staticmethod
    def _normalize_weight_map(raw: Any) -> Dict[str, float]:
        if not isinstance(raw, dict):
            raw = {}
        clean = {
            str(k).strip().lower(): max(0.0, float(v or 0.0))
            for k, v in raw.items()
            if str(k).strip()
        }
        total = float(sum(clean.values()))
        if total <= 1e-9:
            return {"alpha158": 1.0}
        return {k: v / total for k, v in clean.items()}

    def _build_secondary_params(self) -> StrategyParams:
        prefix = "stock_selection.secondary_launch"
        return StrategyParams(
            min_list_days=int(self.config.get(f"{prefix}.min_list_days", 60)),
            limit_up_threshold=float(self.config.get(f"{prefix}.limit_up_threshold", 9.7)),
            limit_down_threshold=float(self.config.get(f"{prefix}.limit_down_threshold", -9.7)),
            limit_up_count_10_min=int(self.config.get(f"{prefix}.limit_up_count_10_min", 1)),
            limit_up_count_10_max=int(self.config.get(f"{prefix}.limit_up_count_10_max", 2)),
            last_limit_up_days_min=int(self.config.get(f"{prefix}.last_limit_up_days_min", 1)),
            last_limit_up_days_max=int(self.config.get(f"{prefix}.last_limit_up_days_max", 6)),
            drawdown_min=float(self.config.get(f"{prefix}.drawdown_min", 0.02)),
            drawdown_max=float(self.config.get(f"{prefix}.drawdown_max", 0.12)),
            vol_shrink_ratio=float(self.config.get(f"{prefix}.vol_shrink_ratio", 0.95)),
            close_ma5_dev_max=float(self.config.get(f"{prefix}.close_ma5_dev_max", 0.04)),
            close_ma10_min_ratio=float(self.config.get(f"{prefix}.close_ma10_min_ratio", 0.99)),
            min_amt_ma20=float(self.config.get(f"{prefix}.min_amt_ma20", 1e5)),
            max_amt_ma20=float(self.config.get(f"{prefix}.max_amt_ma20", 5e6)),
            min_price=float(self.config.get(f"{prefix}.min_price", 3.0)),
            limit_up_amt_ratio_min=float(self.config.get(f"{prefix}.limit_up_amt_ratio_min", 0.6)),
            limit_up_amt_ratio_max=float(self.config.get(f"{prefix}.limit_up_amt_ratio_max", 3.5)),
            rs_lookback=int(self.config.get(f"{prefix}.rs_lookback", 20)),
            max_candidates=int(self.config.get(f"{prefix}.max_candidates", 20)),
            picks_per_day=int(self.config.get(f"{prefix}.picks_per_day", 2)),
            min_score=float(self.config.get(f"{prefix}.min_score", 58.0)),
            cooldown_days=int(self.config.get(f"{prefix}.cooldown_days", 2)),
            weak_market_ret5_threshold=float(
                self.config.get(f"{prefix}.weak_market_ret5_threshold", -0.02)
            ),
            weak_market_min_score_boost=float(
                self.config.get(f"{prefix}.weak_market_min_score_boost", 6.0)
            ),
            weak_market_max_picks=int(
                self.config.get(f"{prefix}.weak_market_max_picks", 1)
            ),
            sideways_market_ret5_low=float(
                self.config.get(f"{prefix}.sideways_market_ret5_low", -0.02)
            ),
            sideways_market_ret5_high=float(
                self.config.get(f"{prefix}.sideways_market_ret5_high", 0.02)
            ),
            sideways_market_min_score_boost=float(
                self.config.get(f"{prefix}.sideways_market_min_score_boost", 4.0)
            ),
            sideways_market_max_picks=int(
                self.config.get(f"{prefix}.sideways_market_max_picks", 1)
            ),
            second_pick_min_score=float(
                self.config.get(f"{prefix}.second_pick_min_score", 72.0)
            ),
            second_pick_score_gap=float(
                self.config.get(f"{prefix}.second_pick_score_gap", 4.0)
            ),
            risk_penalty_weight=float(self.config.get(f"{prefix}.risk_penalty_weight", 12.0)),
            upper_shadow_penalty_threshold=float(
                self.config.get(f"{prefix}.upper_shadow_penalty_threshold", 0.60)
            ),
            upper_shadow_penalty_weight=float(
                self.config.get(f"{prefix}.upper_shadow_penalty_weight", 0.35)
            ),
            high_volume_penalty_threshold=float(
                self.config.get(f"{prefix}.high_volume_penalty_threshold", 1.30)
            ),
            high_volume_penalty_weight=float(
                self.config.get(f"{prefix}.high_volume_penalty_weight", 0.35)
            ),
            deep_negative_penalty_low=float(
                self.config.get(f"{prefix}.deep_negative_penalty_low", -5.0)
            ),
            deep_negative_penalty_high=float(
                self.config.get(f"{prefix}.deep_negative_penalty_high", -3.0)
            ),
            deep_negative_penalty_weight=float(
                self.config.get(f"{prefix}.deep_negative_penalty_weight", 0.30)
            ),
            direct_score_min=float(self.config.get(f"{prefix}.direct_score_min", 76.0)),
            direct_lgb_min=float(self.config.get(f"{prefix}.direct_lgb_min", 0.58)),
            semi_score_min=float(self.config.get(f"{prefix}.semi_score_min", 70.0)),
            semi_lgb_min=float(self.config.get(f"{prefix}.semi_lgb_min", 0.55)),
            direct_conf_min=float(self.config.get(f"{prefix}.direct_conf_min", 0.45)),
            semi_conf_min=float(self.config.get(f"{prefix}.semi_conf_min", 0.58)),
            lgb_enabled=False,
        )

    def _normalize_native_scores(
        self,
        rows: List[Dict[str, Any]],
        score_key: str,
        fallback: float = 60.0,
    ) -> List[Dict[str, Any]]:
        if not rows:
            return []
        values: List[float] = []
        for row in rows:
            try:
                values.append(float(row.get(score_key, fallback) or fallback))
            except Exception:
                values.append(fallback)
        low = min(values)
        high = max(values)
        span = high - low
        normalized_rows: List[Dict[str, Any]] = []
        for row, value in zip(rows, values):
            new_row = dict(row)
            if span <= 1e-9:
                normalized = 70.0
            else:
                normalized = 55.0 + (value - low) / span * 40.0
            new_row["native_score"] = float(value)
            new_row["normalized_native_score"] = round(float(normalized), 4)
            normalized_rows.append(new_row)
        return normalized_rows

    def _run_breakout_watchlist(self, end_date: str) -> List[Dict[str, Any]]:
        cached_rows = self._load_watchlist_cache("breakout", end_date)
        if cached_rows is not None:
            return cached_rows

        strategy = build_breakout_strategy_from_config(self.db, self.config)
        features = self._get_breakout_features("breakout", strategy, end_date=end_date)
        watch_items = strategy.select_watchlist_from_features(features, str(end_date)) if not features.empty else []
        rows: List[Dict[str, Any]] = []
        for item in watch_items[: self.max_per_sleeve]:
            rows.append(
                {
                    "ts_code": str(item.ts_code),
                    "name": str(item.name or ""),
                    "industry": str(getattr(item, "industry", "") or ""),
                    "total_score": float(item.signal_score),
                    "breakout_signal_score": float(item.signal_score),
                    "pivot": float(item.pivot),
                    "trigger_price": float(item.trigger_price),
                    "stop_loss": float(item.stop_loss),
                    "level": "strong" if float(item.signal_score) >= 75 else "medium",
                    "risk_flags": [],
                    "metrics": {
                        "pivot": round(float(item.pivot), 4),
                        "trigger_price": round(float(item.trigger_price), 4),
                        "stop_loss": round(float(item.stop_loss), 4),
                    },
                }
            )
        normalized = self._normalize_native_scores(rows, "breakout_signal_score")
        self._save_watchlist_cache("breakout", end_date, normalized)
        return normalized

    def _run_wide_breakout_watchlist(self, end_date: str) -> List[Dict[str, Any]]:
        cached_rows = self._load_watchlist_cache("wide_breakout", end_date)
        if cached_rows is not None:
            return cached_rows

        strategy = build_wide_breakout_strategy_from_config(self.db, self.config)
        features = self._get_breakout_features("wide_breakout", strategy, end_date=end_date)
        watch_items = strategy.select_watchlist_from_features(features, str(end_date)) if not features.empty else []
        rows: List[Dict[str, Any]] = []
        for item in watch_items[: self.max_per_sleeve]:
            rows.append(
                {
                    "ts_code": str(item.ts_code),
                    "name": str(item.name or ""),
                    "industry": str(getattr(item, "industry", "") or ""),
                    "total_score": float(item.signal_score),
                    "wide_breakout_signal_score": float(item.signal_score),
                    "pivot": float(item.pivot),
                    "trigger_price": float(item.trigger_price),
                    "stop_loss": float(item.stop_loss),
                    "level": "strong" if float(item.signal_score) >= 75 else "medium",
                    "risk_flags": [],
                    "metrics": {
                        "pivot": round(float(item.pivot), 4),
                        "trigger_price": round(float(item.trigger_price), 4),
                        "stop_loss": round(float(item.stop_loss), 4),
                    },
                }
            )
        normalized = self._normalize_native_scores(rows, "wide_breakout_signal_score")
        self._save_watchlist_cache("wide_breakout", end_date, normalized)
        return normalized

    def _watchlist_cache_path(self, sleeve: str, end_date: str) -> Path:
        return self._cache_dir / f"daily_multi_{sleeve}_watchlist_v1_{str(end_date)}.json"

    def _load_watchlist_cache(self, sleeve: str, end_date: str) -> List[Dict[str, Any]] | None:
        path = self._watchlist_cache_path(sleeve, end_date)
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            rows = payload.get("rows", [])
            if isinstance(rows, list):
                return [dict(row) for row in rows if isinstance(row, dict)]
        except Exception as e:
            logger.debug("读取%s观察池缓存失败 %s: %s", sleeve, path, e)
        return None

    def _save_watchlist_cache(self, sleeve: str, end_date: str, rows: List[Dict[str, Any]]) -> None:
        path = self._watchlist_cache_path(sleeve, end_date)
        try:
            self._cache_dir.mkdir(parents=True, exist_ok=True)
            payload = {
                "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "sleeve": sleeve,
                "end_date": str(end_date),
                "rows": rows,
            }
            path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as e:
            logger.debug("写入%s观察池缓存失败 %s: %s", sleeve, path, e)

    def _get_breakout_features(self, cache_key: str, strategy: Any, end_date: str) -> pd.DataFrame:
        if cache_key == "wide_breakout" and "breakout" in self._breakout_feature_cache:
            _, cached_features = self._breakout_feature_cache["breakout"]
            self._breakout_feature_cache[cache_key] = (strategy, cached_features)
            return cached_features

        cached = self._breakout_feature_cache.get(cache_key)
        if cached is not None:
            cached_strategy, cached_features = cached
            return cached_features

        prefix = "stock_selection.multi_strategy_daily"
        cache_end_date = str(self.config.get(f"{prefix}.feature_cache_end_date", "") or "")
        max_date = max(str(end_date or ""), cache_end_date)
        cache_dir = Path("data/cache")
        cache_path = cache_dir / f"daily_multi_breakout_features_v2_{max_date}.pkl"
        if cache_path.exists():
            try:
                features = pd.read_pickle(cache_path)
                self._breakout_feature_cache[cache_key] = (strategy, features)
                return features
            except Exception as e:
                logger.debug("读取突破特征缓存失败 %s: %s", cache_path, e)

        raw_daily, raw_basic = strategy._load_data(max_date)
        if raw_daily.empty or raw_basic.empty:
            features = pd.DataFrame()
        else:
            features = strategy._compute_features(raw_daily, raw_basic, max_date)
        if not features.empty:
            try:
                cache_dir.mkdir(parents=True, exist_ok=True)
                features.to_pickle(cache_path)
            except Exception as e:
                logger.debug("写入突破特征缓存失败 %s: %s", cache_path, e)
        self._breakout_feature_cache[cache_key] = (strategy, features)
        return features

    def _run_secondary_daily(self, end_date: str) -> List[Dict[str, Any]]:
        cached_rows = self._load_watchlist_cache("secondary_launch", end_date)
        if cached_rows is not None:
            return cached_rows

        candidates = self._get_secondary_signals_for_date(end_date)
        if candidates.empty:
            return []
        rows: List[Dict[str, Any]] = []
        for _, row in candidates.head(self.max_per_sleeve).iterrows():
            score_val = float(row.get("signal_score", 0.0) or 0.0)
            risk_penalty = float(row.get("risk_penalty_score", 0.0) or 0.0)
            risk_flags: List[str] = []
            if risk_penalty >= 6.0:
                risk_flags.append("secondary_risk_penalty")
            if float(row.get("upper_shadow_ratio", 0.0) or 0.0) >= 0.35:
                risk_flags.append("upper_shadow")
            if float(row.get("vol_ratio_5", 1.0) or 1.0) >= 1.3:
                risk_flags.append("volume_spike")
            rows.append(
                {
                    "ts_code": str(row.get("ts_code", "")),
                    "name": str(row.get("name", "") or ""),
                    "industry": str(row.get("industry", "") or ""),
                    "total_score": score_val,
                    "secondary_signal_score": score_val,
                    "level": "strong" if score_val >= 76 else "medium",
                    "risk_flags": risk_flags,
                    "metrics": {
                        "rs20": round(float(row.get("rs20", 0.0) or 0.0), 4),
                        "quality_score": round(float(row.get("quality_score", 0.0) or 0.0), 4),
                        "risk_penalty_score": round(risk_penalty, 4),
                    },
                    "secondary_execution_tier_hint": str(
                        row.get("execution_tier_hint", "confirm") or "confirm"
                    ),
                }
            )
        normalized = self._normalize_native_scores(rows, "secondary_signal_score")
        self._save_watchlist_cache("secondary_launch", end_date, normalized)
        return normalized

    def _get_secondary_signals_for_date(self, end_date: str) -> pd.DataFrame:
        params = self._build_secondary_params()
        strategy = MainboardSecondaryLaunchStrategy(params)
        features = self._get_secondary_features(end_date=end_date)
        if features.empty:
            return pd.DataFrame()
        signal_frame = strategy.build_signal_frame(features)
        if signal_frame.empty:
            return pd.DataFrame()
        target = pd.Timestamp(str(end_date))
        signal_dates = pd.to_datetime(signal_frame["signal_date"], errors="coerce")
        signal_frame = signal_frame[signal_dates.dt.strftime("%Y%m%d") == target.strftime("%Y%m%d")].copy()
        if signal_frame.empty:
            return pd.DataFrame()
        return strategy.generate_signals_from_frame(signal_frame)

    def _get_secondary_signals(self) -> pd.DataFrame:
        if self._secondary_signal_cache is not None:
            return self._secondary_signal_cache

        features = self._get_secondary_features()
        if features.empty:
            self._secondary_signal_cache = pd.DataFrame()
            return self._secondary_signal_cache
        params = self._build_secondary_params()
        strategy = MainboardSecondaryLaunchStrategy(params)
        self._secondary_signal_cache = strategy.generate_signals(features)
        return self._secondary_signal_cache

    def _get_secondary_features(self, end_date: str | None = None) -> pd.DataFrame:
        if self._secondary_feature_cache is not None:
            return self._secondary_feature_cache

        params = self._build_secondary_params()
        strategy = MainboardSecondaryLaunchStrategy(params)
        prefix = "stock_selection.multi_strategy_daily"
        cache_end_date = str(self.config.get(f"{prefix}.feature_cache_end_date", "") or "")
        latest = str(end_date or cache_end_date or "")
        try:
            if not latest:
                latest = str(self.db.get_latest_trade_date("stock_daily") or "")
        except Exception:
            latest = datetime.now().strftime("%Y%m%d")
        end_ts = datetime.strptime(str(latest), "%Y%m%d")
        query_start = (end_ts - timedelta(days=max(self.lookback_days * 2, 240))).strftime("%Y%m%d")
        daily = pd.DataFrame(
            self.db.query(
                """
                SELECT ts_code, trade_date, open, close, high, low, vol, amount, pct_chg
                FROM stock_daily
                WHERE trade_date >= ? AND trade_date <= ?
                ORDER BY ts_code, trade_date
                """,
                (query_start, latest),
            )
        )
        basic = pd.DataFrame(
            self.db.query(
                "SELECT ts_code, name, industry, list_date FROM stock_basic"
            )
        )
        if daily.empty or basic.empty:
            self._secondary_feature_cache = pd.DataFrame()
            return self._secondary_feature_cache
        self._secondary_feature_cache = strategy.prepare_features(daily, basic)
        return self._secondary_feature_cache

    @staticmethod
    def _merge_metrics(base: Dict[str, Any], extra: Dict[str, Any]) -> Dict[str, Any]:
        merged = dict(base or {})
        for key, value in (extra or {}).items():
            if key not in merged:
                merged[key] = value
        return merged

    def run(
        self,
        end_date: str,
        alpha158_results: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        if not self.enabled:
            return alpha158_results[: self.top_n]

        regime_decision = self.regime_router.decide(end_date=end_date)
        regime_name = str(regime_decision.regime or "sideways").strip().lower() or "sideways"
        regime_weights = dict(
            self.regime_sleeve_weights.get(regime_name) or self.regime_sleeve_weights["sideways"]
        )
        alpha_rows = self._normalize_native_scores(
            [dict(item) for item in alpha158_results[: max(self.top_n * 2, self.max_per_sleeve)]],
            "total_score",
        )
        breakout_rows = self._run_breakout_watchlist(end_date=end_date)
        wide_breakout_rows = (
            self._run_wide_breakout_watchlist(end_date=end_date)
            if self.enable_wide_breakout_overlay
            else []
        )
        secondary_rows = self._run_secondary_daily(end_date=end_date) if self.enable_secondary_overlay else []

        final_rows: List[Dict[str, Any]] = []
        by_code: Dict[str, Dict[str, Any]] = {}

        def _init_alpha_row(row: Dict[str, Any]) -> Dict[str, Any]:
            out = dict(row)
            out["strategy_profile"] = "daily_multi_strategy"
            out["strategy_sleeves"] = ["alpha158"]
            out["strategy_contributions"] = {
                "alpha158": {
                    "normalized_score": round(float(row.get("normalized_native_score", row.get("total_score", 0.0)) or 0.0), 4),
                    "base_role": "core",
                }
            }
            out["collaboration_label"] = "alpha158"
            out["abstain_score"] = float(row.get("total_score", row.get("native_score", 0.0)) or 0.0)
            return out

        def _apply_overlay(target: Dict[str, Any], overlay: Dict[str, Any], sleeve: str, bonus: float) -> None:
            code = str(target.get("ts_code", ""))
            if sleeve not in target["strategy_sleeves"]:
                target["strategy_sleeves"] = sorted(set(list(target.get("strategy_sleeves") or []) + [sleeve]))
            target["strategy_contributions"][sleeve] = {
                "normalized_score": round(float(overlay.get("normalized_native_score", overlay.get("total_score", 0.0)) or 0.0), 4),
                "bonus": round(float(bonus), 4),
                "overlay_role": "confirm",
            }
            target["total_score"] = round(min(100.0, float(target.get("total_score", 0.0) or 0.0) + float(bonus)), 4)
            target["collaboration_label"] = "+".join(target["strategy_sleeves"])
            target["abstain_score"] = max(
                float(target.get("abstain_score", 0.0) or 0.0),
                float(target.get("total_score", 0.0) or 0.0),
            )
            target["metrics"] = self._merge_metrics(target.get("metrics", {}), overlay.get("metrics", {}))
            target["risk_flags"] = sorted(set(list(target.get("risk_flags") or []) + list(overlay.get("risk_flags") or [])))
            if sleeve == "breakout":
                target["breakout_signal_score"] = float(overlay.get("breakout_signal_score", 0.0) or 0.0)
                target["breakout_trigger_price"] = float(overlay.get("trigger_price", 0.0) or 0.0)
                target["breakout_pivot"] = float(overlay.get("pivot", 0.0) or 0.0)
            elif sleeve == "wide_breakout":
                target["wide_breakout_signal_score"] = float(overlay.get("wide_breakout_signal_score", 0.0) or 0.0)
                target["wide_breakout_trigger_price"] = float(overlay.get("trigger_price", 0.0) or 0.0)
                target["wide_breakout_pivot"] = float(overlay.get("pivot", 0.0) or 0.0)
            elif sleeve == "secondary_launch":
                target["secondary_signal_score"] = float(overlay.get("secondary_signal_score", 0.0) or 0.0)
                target["secondary_execution_tier_hint"] = str(
                    overlay.get("secondary_execution_tier_hint", "confirm") or "confirm"
                )
            by_code[code] = target

        for row in breakout_rows:
            code = str(row.get("ts_code", ""))
            if code in by_code:
                _apply_overlay(by_code[code], row, "breakout", self.breakout_overlay_bonus)
        for row in wide_breakout_rows:
            code = str(row.get("ts_code", ""))
            if code in by_code:
                _apply_overlay(
                    by_code[code],
                    row,
                    "wide_breakout",
                    self.wide_breakout_overlay_bonus,
                )
        if self.enable_secondary_overlay:
            for row in secondary_rows:
                code = str(row.get("ts_code", ""))
                if code in by_code:
                    _apply_overlay(by_code[code], row, "secondary_launch", self.secondary_overlay_bonus)

        def _can_use_breakout() -> bool:
            return regime_name == "trend" or (regime_name == "sideways" and self.allow_breakout_in_sideways)

        def _sleeve_weight(sleeve: str) -> float:
            if sleeve == "wide_breakout":
                sleeve = "breakout"
            return float(regime_weights.get(sleeve, 0.0) or 0.0)

        breakout_unlimited = bool(
            self.config.get("stock_selection.multi_strategy_daily.breakout_unlimited_slots", True)
        )
        breakout_slot_budget = 0
        if _can_use_breakout() and _sleeve_weight("breakout") > 0.0:
            breakout_slot_budget = max(0, self.top_n)
            if not breakout_unlimited:
                breakout_slot_budget = max(0, int(self.breakout_direct_slots))
        secondary_slot_budget = 0
        if self.enable_secondary_overlay and _sleeve_weight("secondary_launch") > 0.0:
            secondary_slot_budget = max(0, int(self.secondary_direct_slots))

        min_alpha_slots = max(1, int(self.min_alpha_core_slots))
        max_satellite_budget = max(0, self.top_n - min_alpha_slots)
        direct_satellite_budget = min(max_satellite_budget, breakout_slot_budget + secondary_slot_budget)
        breakout_slot_budget = min(breakout_slot_budget, direct_satellite_budget)
        secondary_slot_budget = min(
            secondary_slot_budget,
            max(0, direct_satellite_budget - breakout_slot_budget),
        )
        alpha_target = max(min_alpha_slots, self.top_n - direct_satellite_budget)
        alpha_target = min(self.top_n, alpha_target)

        base_keep = max(
            1,
            min(
                alpha_target,
                max(alpha_target, int(np.ceil(self.top_n * self.alpha_base_keep_ratio))),
            ),
        )
        alpha_base = [dict(row) for row in alpha_rows[:base_keep]]
        alpha_reserve = [dict(row) for row in alpha_rows[base_keep : max(self.top_n * 2, base_keep)]]

        for row in alpha_base:
            init_row = _init_alpha_row(row)
            final_rows.append(init_row)
            by_code[str(init_row.get("ts_code", ""))] = init_row

        def _satellite_threshold(sleeve: str) -> float:
            return {
                "breakout": self.breakout_replace_threshold,
                "wide_breakout": self.wide_breakout_replace_threshold,
                "secondary_launch": self.secondary_replace_threshold,
            }.get(sleeve, 100.0)

        satellites: List[Dict[str, Any]] = []
        direct_breakout_candidates: List[Dict[str, Any]] = []
        direct_secondary_candidates: List[Dict[str, Any]] = []
        if self.enable_satellite_fill:
            if _can_use_breakout() and _sleeve_weight("breakout") > 0.0:
                for row in breakout_rows:
                    if str(row.get("ts_code", "")) not in by_code:
                        sat = dict(row)
                        sat["satellite_type"] = "breakout"
                        sat["satellite_priority_score"] = float(row.get("normalized_native_score", row.get("total_score", 0.0)) or 0.0) * _sleeve_weight("breakout")
                        sat["satellite_threshold_score"] = float(row.get("normalized_native_score", row.get("total_score", 0.0)) or 0.0)
                        satellites.append(sat)
                        direct_breakout_candidates.append(sat)
                for row in wide_breakout_rows:
                    if str(row.get("ts_code", "")) not in by_code:
                        sat = dict(row)
                        sat["satellite_type"] = "wide_breakout"
                        sat["satellite_priority_score"] = float(row.get("normalized_native_score", row.get("total_score", 0.0)) or 0.0) * _sleeve_weight("breakout")
                        sat["satellite_threshold_score"] = float(row.get("normalized_native_score", row.get("total_score", 0.0)) or 0.0)
                        satellites.append(sat)
                        direct_breakout_candidates.append(sat)
            if self.enable_secondary_overlay and _sleeve_weight("secondary_launch") > 0.0:
                for row in secondary_rows:
                    if str(row.get("ts_code", "")) not in by_code:
                        sat = dict(row)
                        sat["satellite_type"] = "secondary_launch"
                        sat["satellite_priority_score"] = float(row.get("normalized_native_score", row.get("total_score", 0.0)) or 0.0) * _sleeve_weight("secondary_launch")
                        sat["satellite_threshold_score"] = float(row.get("normalized_native_score", row.get("total_score", 0.0)) or 0.0)
                        satellites.append(sat)
                        direct_secondary_candidates.append(sat)
            satellites.sort(key=lambda item: float(item.get("satellite_priority_score", 0.0) or 0.0), reverse=True)
            direct_breakout_candidates.sort(
                key=lambda item: (
                    float(item.get("satellite_threshold_score", 0.0) or 0.0),
                    float(item.get("satellite_priority_score", 0.0) or 0.0),
                ),
                reverse=True,
            )
            direct_secondary_candidates.sort(
                key=lambda item: (
                    float(item.get("satellite_threshold_score", 0.0) or 0.0),
                    float(item.get("satellite_priority_score", 0.0) or 0.0),
                ),
                reverse=True,
            )

        def _wrap_satellite(row: Dict[str, Any], sleeve: str) -> Dict[str, Any]:
            base_score = 68.0 if sleeve in {"breakout", "wide_breakout"} else 66.0
            bonus_map = {
                "breakout": self.breakout_overlay_bonus,
                "wide_breakout": self.wide_breakout_overlay_bonus,
                "secondary_launch": self.secondary_overlay_bonus,
            }
            bonus = float(bonus_map.get(sleeve, 0.0))
            raw_score = float(row.get("satellite_threshold_score", row.get("normalized_native_score", row.get("total_score", 0.0))) or 0.0)
            total_score = min(100.0, base_score + bonus + raw_score * 0.1)
            wrapped = {
                "ts_code": str(row.get("ts_code", "")),
                "name": str(row.get("name", "") or ""),
                "industry": str(row.get("industry", "") or ""),
                "total_score": round(total_score, 4),
                "abstain_score": round(total_score, 4),
                "level": "strong" if total_score >= 72 else "medium",
                "risk_flags": list(row.get("risk_flags") or []),
                "metrics": dict(row.get("metrics") or {}),
                "strategy_sleeves": [sleeve],
                "strategy_contributions": {
                    sleeve: {
                        "normalized_score": round(float(row.get("satellite_priority_score", 0.0) or 0.0), 4),
                        "base_role": "satellite_fill",
                    }
                },
                "strategy_profile": "daily_multi_strategy",
                "regime_name": regime_name,
                "alpha158_regime": regime_name,
                "alpha158_regime_reason": regime_decision.reason,
                "regime_top_n_multiplier": regime_decision.top_n_multiplier,
                "market_below_ma20": False,
                "collaboration_label": sleeve,
            }
            if sleeve in {"breakout", "wide_breakout"}:
                wrapped["breakout_signal_score"] = float(row.get("breakout_signal_score", 0.0) or 0.0)
                wrapped["breakout_trigger_price"] = float(row.get("trigger_price", 0.0) or 0.0)
                wrapped["breakout_pivot"] = float(row.get("pivot", 0.0) or 0.0)
                if sleeve == "wide_breakout":
                    wrapped["wide_breakout_signal_score"] = float(row.get("wide_breakout_signal_score", 0.0) or 0.0)
            else:
                wrapped["secondary_signal_score"] = float(row.get("secondary_signal_score", 0.0) or 0.0)
                wrapped["secondary_execution_tier_hint"] = str(
                    row.get("secondary_execution_tier_hint", "confirm") or "confirm"
                )
            return wrapped

        used_satellite_codes = set()
        for slot_budget, direct_candidates in (
            (breakout_slot_budget, direct_breakout_candidates),
            (secondary_slot_budget, direct_secondary_candidates),
        ):
            remaining = int(slot_budget)
            for sat in direct_candidates:
                if remaining <= 0 or len(final_rows) >= self.top_n:
                    break
                sleeve = str(sat.get("satellite_type", "") or "")
                if float(sat.get("satellite_threshold_score", 0.0) or 0.0) < _satellite_threshold(sleeve):
                    continue
                code = str(sat.get("ts_code", ""))
                if code in used_satellite_codes or code in {str(item.get("ts_code", "")) for item in final_rows}:
                    continue
                final_rows.append(_wrap_satellite(sat, sleeve))
                used_satellite_codes.add(code)
                remaining -= 1

        if len(final_rows) < self.top_n:
            available_slots = min(
                max(0, self.top_n - len(final_rows)),
                max(0, self.max_satellite_replacements),
            )
            for sat in satellites:
                if available_slots <= 0:
                    break
                sleeve = str(sat.get("satellite_type", "") or "")
                threshold = _satellite_threshold(sleeve)
                if float(sat.get("satellite_threshold_score", 0.0) or 0.0) < threshold:
                    continue
                code = str(sat.get("ts_code", ""))
                if code in used_satellite_codes or code in {str(item.get("ts_code", "")) for item in final_rows}:
                    continue
                final_rows.append(_wrap_satellite(sat, sleeve))
                used_satellite_codes.add(code)
                available_slots -= 1

        if len(final_rows) < self.top_n:
            for row in alpha_reserve:
                code = str(row.get("ts_code", ""))
                if code in {str(item.get("ts_code", "")) for item in final_rows}:
                    continue
                final_rows.append(_init_alpha_row(row))
                if len(final_rows) >= self.top_n:
                    break

        merged_rows: List[Dict[str, Any]] = []
        for row in final_rows:
            if float(row.get("total_score", 0.0) or 0.0) < self.min_combined_score:
                continue
            merged_rows.append(row)

        merged_rows.sort(
            key=lambda item: (
                float(item.get("total_score", 0.0) or 0.0),
                len(item.get("strategy_sleeves") or []),
            ),
            reverse=True,
        )
        logger.info(
            "日线多策略主从协同完成: regime=%s alpha_base=%d alpha_reserve=%d breakout=%d wide_breakout=%d secondary=%d satellite=%d final=%d",
            regime_name,
            len(alpha_base),
            len(alpha_reserve),
            len(breakout_rows),
            len(wide_breakout_rows),
            len(secondary_rows),
            len(used_satellite_codes),
            len(merged_rows),
        )
        return merged_rows[: self.top_n * 2]
