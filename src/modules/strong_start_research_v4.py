# -*- coding: utf-8 -*-
"""Research-version strong-start strategy (v4).

This module is intentionally isolated from legacy `strong_start_strategy`.
It implements a four-layer structure:
1) base filters
2) continuous scoring
3) trigger confirmation
4) downgraded observation

No backtest/PNL logic is included.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import yaml

from src.core.logger import get_logger

logger = get_logger("strong_start_research_v4")


DEFAULT_CONFIG_PATH = Path("config/strong_start_research_v4_config.yaml")


def _norm_code(ts_code: str) -> str:
    return str(ts_code or "").split(".", 1)[0]


def _safe_float(v: Any) -> float:
    try:
        return float(v)
    except Exception:
        return float("nan")


def _clamp01(v: float) -> float:
    if np.isnan(v):
        return 0.0
    return float(min(max(v, 0.0), 1.0))


def _json_dumps(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, separators=(",", ":"))


@dataclass
class RuleEval:
    passed: bool
    raw_value: float
    normalized: float
    reason: str


class StrongStartResearchV4:
    """Research strategy runner for feature snapshots."""

    def __init__(
        self,
        config_path: Optional[str | Path] = None,
        config: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.config_path = Path(config_path) if config_path else DEFAULT_CONFIG_PATH
        if config is not None:
            self.config = config
        else:
            self.config = self._load_config(self.config_path)
        self._validate_config(self.config)
        self._cached_layer_features = self._build_layer_feature_index()

    @staticmethod
    def _load_config(path: Path) -> Dict[str, Any]:
        if not path.exists():
            raise FileNotFoundError(f"strategy config not found: {path}")
        payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if not isinstance(payload, dict):
            raise ValueError("strategy config must be a mapping")
        return payload

    @staticmethod
    def _validate_required_keys(cfg: Dict[str, Any], keys: List[str]) -> None:
        miss = [k for k in keys if k not in cfg]
        if miss:
            raise ValueError(f"missing required config keys: {miss}")

    def _validate_config(self, cfg: Dict[str, Any]) -> None:
        self._validate_required_keys(
            cfg,
            [
                "version",
                "profiles",
                "forbidden_field_patterns",
                "universe",
                "hard_filters",
                "scoring",
                "trigger",
                "downgraded_features",
                "output",
            ],
        )
        if "neutral" not in list(cfg.get("profiles") or []):
            raise ValueError("profiles must include 'neutral'")

        hard_feats = {
            str(r.get("feature"))
            for r in (cfg.get("hard_filters", {}).get("rules", []) or [])
            if isinstance(r, dict)
        }
        trigger_feats = set()
        for g in (cfg.get("trigger", {}).get("groups", {}) or {}).values():
            for r in (g.get("rules", []) or []):
                trigger_feats.add(str(r.get("feature")))
        allow_cross = set(str(x) for x in (cfg.get("cross_layer_allowlist") or []))
        real_overlap = (hard_feats & trigger_feats) - allow_cross
        if real_overlap:
            overlap = sorted(real_overlap)
            raise ValueError(f"layer-mix error: hard_filters overlaps trigger features: {overlap}")

        # Research sanity constraints
        if "f_chip_stability_std10" in hard_feats:
            raise ValueError("sanity violation: f_chip_stability_std10 must NOT be in hard_filters")
        if "f_k_pct_chg" not in trigger_feats:
            raise ValueError("sanity violation: f_k_pct_chg must be in trigger rules")

        scoring_feats = set()
        for axis in (cfg.get("scoring", {}).get("axes", {}) or {}).values():
            for item in (axis.get("items", []) or []):
                scoring_feats.add(str(item.get("feature")))
        if "f_ind_rank_pctchg" not in scoring_feats:
            raise ValueError("sanity violation: f_ind_rank_pctchg must be included in scoring")

    def _build_layer_feature_index(self) -> Dict[str, List[str]]:
        hard = [
            str(r.get("feature"))
            for r in self.config.get("hard_filters", {}).get("rules", []) or []
            if isinstance(r, dict)
        ]
        scoring = []
        for axis in (self.config.get("scoring", {}).get("axes", {}) or {}).values():
            for item in (axis.get("items", []) or []):
                scoring.append(str(item.get("feature")))
        trigger = []
        for g in (self.config.get("trigger", {}).get("groups", {}) or {}).values():
            for item in (g.get("rules", []) or []):
                trigger.append(str(item.get("feature")))
        downgraded = list(self.config.get("downgraded_features", {}).get("features", []) or [])
        return {
            "hard_filters": sorted(set(hard)),
            "scoring": sorted(set(scoring)),
            "trigger": sorted(set(trigger)),
            "downgraded": sorted(set(downgraded)),
        }

    def get_layer_features(self) -> Dict[str, List[str]]:
        return dict(self._cached_layer_features)

    def run_on_dataframe(self, df: pd.DataFrame, profile: str = "neutral") -> pd.DataFrame:
        if profile not in list(self.config.get("profiles") or []):
            raise ValueError(f"unknown profile: {profile}")
        if df is None or df.empty:
            return pd.DataFrame()
        work = df.copy()
        work["trade_date"] = work["trade_date"].astype(str)
        for key in ["ts_code", "trade_date", "name", "industry"]:
            if key not in work.columns:
                raise ValueError(f"missing required input column: {key}")
        self._guard_forbidden_fields(work.columns.tolist())

        # normalize numeric feature columns
        for c in [c for c in work.columns if c.startswith("f_")]:
            work[c] = pd.to_numeric(work[c], errors="coerce")
        if "amount_ma20" in work.columns:
            work["amount_ma20"] = pd.to_numeric(work["amount_ma20"], errors="coerce")
        if "list_days" in work.columns:
            work["list_days"] = pd.to_numeric(work["list_days"], errors="coerce")
        if "close" in work.columns:
            work["close"] = pd.to_numeric(work["close"], errors="coerce")

        filter_rows = [self._eval_filter_row(row, profile) for _, row in work.iterrows()]
        filter_df = pd.DataFrame(filter_rows, index=work.index)
        work = pd.concat([work, filter_df], axis=1)

        score_rows = [self._eval_scoring_row(row, profile) for _, row in work.iterrows()]
        score_df = pd.DataFrame(score_rows, index=work.index)
        work = pd.concat([work, score_df], axis=1)

        trigger_rows = [self._eval_trigger_row(row, profile) for _, row in work.iterrows()]
        trigger_df = pd.DataFrame(trigger_rows, index=work.index)
        work = pd.concat([work, trigger_df], axis=1)

        work["downgraded_observations"] = work.apply(self._build_downgraded_observations, axis=1)

        output_cfg = self.config.get("output", {}) or {}
        min_score = _safe_float((self.config.get("scoring", {}).get("min_total_score", {}) or {}).get(profile, 50.0))
        require_trigger = bool(output_cfg.get("require_trigger_for_ready", True))
        work["signal_ready"] = (
            work["is_candidate_after_filters"].fillna(False)
            & (pd.to_numeric(work["score_total"], errors="coerce") >= min_score)
            & (work["trigger_status"].fillna(False) if require_trigger else True)
        )

        work["explain_json"] = work.apply(self._build_explain_json, axis=1)
        return work

    def _guard_forbidden_fields(self, cols: List[str]) -> None:
        pats = list(self.config.get("forbidden_field_patterns") or [])
        bad = [c for c in cols if any(p in c for p in pats)]
        if bad:
            raise ValueError(f"forbidden fields detected: {bad}")

    def _pick_threshold(self, node: Dict[str, Any], profile: str) -> float:
        if not isinstance(node, dict):
            return _safe_float(node)
        return _safe_float(node.get(profile))

    def _eval_rule(
        self,
        row: pd.Series,
        rule: Dict[str, Any],
        profile: str,
        layer: str,
    ) -> RuleEval:
        feat = str(rule.get("feature") or "")
        if feat not in row.index:
            return RuleEval(False, np.nan, 0.0, f"{layer}:{feat}:missing_feature")
        raw = _safe_float(row.get(feat))
        if np.isnan(raw):
            return RuleEval(False, np.nan, 0.0, f"{layer}:{feat}:nan")

        direction = str(rule.get("direction", "higher_better"))
        if direction in {"higher_better", "lower_better"}:
            ths = rule.get("thresholds", {}) or {}
            loose = _safe_float(ths.get("loose"))
            neutral = _safe_float(ths.get("neutral"))
            strict = _safe_float(ths.get("strict"))
            if any(np.isnan(x) for x in [loose, neutral, strict]):
                return RuleEval(False, raw, 0.0, f"{layer}:{feat}:bad_thresholds")

            if direction == "higher_better":
                passed = raw >= self._pick_threshold(ths, profile)
                if raw < loose:
                    norm = 0.0
                elif raw < neutral:
                    norm = 0.5 * (raw - loose) / max(neutral - loose, 1e-9)
                elif raw < strict:
                    norm = 0.5 + 0.4 * (raw - neutral) / max(strict - neutral, 1e-9)
                else:
                    norm = 1.0
            else:
                passed = raw <= self._pick_threshold(ths, profile)
                if raw > loose:
                    norm = 0.0
                elif raw > neutral:
                    norm = 0.5 * (loose - raw) / max(loose - neutral, 1e-9)
                elif raw > strict:
                    norm = 0.5 + 0.4 * (neutral - raw) / max(neutral - strict, 1e-9)
                else:
                    norm = 1.0
            return RuleEval(bool(passed), raw, _clamp01(norm), f"{layer}:{feat}:{'pass' if passed else 'fail'}")

        if direction == "range":
            ranges = rule.get("ranges", {}) or {}
            current = ranges.get(profile)
            if not isinstance(current, (list, tuple)) or len(current) != 2:
                return RuleEval(False, raw, 0.0, f"{layer}:{feat}:bad_range")
            lo, hi = _safe_float(current[0]), _safe_float(current[1])
            if np.isnan(lo) or np.isnan(hi) or hi <= lo:
                return RuleEval(False, raw, 0.0, f"{layer}:{feat}:bad_range")
            passed = (raw >= lo) and (raw <= hi)
            if passed:
                norm = 1.0
            else:
                dist = min(abs(raw - lo), abs(raw - hi))
                width = hi - lo
                norm = max(0.0, 1.0 - dist / max(width, 1e-9))
            return RuleEval(bool(passed), raw, _clamp01(norm), f"{layer}:{feat}:{'pass' if passed else 'fail'}")

        return RuleEval(False, raw, 0.0, f"{layer}:{feat}:unsupported_direction")

    def _eval_filter_row(self, row: pd.Series, profile: str) -> Dict[str, Any]:
        failures: List[str] = []
        hits: List[str] = []
        univ = self.config.get("universe", {}) or {}

        ts_code = str(row.get("ts_code") or "")
        name = str(row.get("name") or "")
        code = _norm_code(ts_code)
        prefixes = list(univ.get("mainboard_prefixes") or [])
        if prefixes and not any(code.startswith(p) for p in prefixes):
            failures.append("universe:not_mainboard")
        else:
            hits.append("universe:mainboard_ok")

        min_list_days = self._pick_threshold(univ.get("min_list_days", {}), profile)
        if not np.isnan(min_list_days):
            list_days = _safe_float(row.get("list_days"))
            if np.isnan(list_days):
                failures.append("universe:list_days_missing")
            elif list_days < min_list_days:
                failures.append("universe:list_days_too_short")
            else:
                hits.append("universe:list_days_ok")

        min_amt_ma20 = self._pick_threshold(univ.get("min_amount_ma20", {}), profile)
        if not np.isnan(min_amt_ma20):
            amt_ma20 = _safe_float(row.get("amount_ma20"))
            if np.isnan(amt_ma20):
                failures.append("universe:amount_ma20_missing")
            elif amt_ma20 < min_amt_ma20:
                failures.append("universe:amount_ma20_too_low")
            else:
                hits.append("universe:amount_ma20_ok")

        min_price = self._pick_threshold(univ.get("min_price", {}), profile)
        max_price = self._pick_threshold(univ.get("max_price", {}), profile)
        px = _safe_float(row.get("close"))
        if not np.isnan(min_price) and not np.isnan(px) and px < min_price:
            failures.append("universe:price_too_low")
        if not np.isnan(max_price) and not np.isnan(px) and px > max_price:
            failures.append("universe:price_too_high")
        if not np.isnan(px) and (
            (np.isnan(min_price) or px >= min_price) and (np.isnan(max_price) or px <= max_price)
        ):
            hits.append("universe:price_ok")

        if bool(univ.get("exclude_st", True)):
            patterns = [str(x) for x in (univ.get("risk_name_patterns") or [])]
            if any(p in name for p in patterns if p):
                failures.append("universe:risk_name")
            else:
                hits.append("universe:risk_name_ok")

        for rule in (self.config.get("hard_filters", {}).get("rules", []) or []):
            if not isinstance(rule, dict) or not bool(rule.get("enabled", True)):
                continue
            ev = self._eval_rule(row, rule, profile, "hard")
            rid = str(rule.get("id") or rule.get("feature"))
            if ev.passed:
                hits.append(f"hard:{rid}:pass")
            else:
                failures.append(f"hard:{rid}:fail")

        passed = len(failures) == 0
        return {
            "is_candidate_after_filters": bool(passed),
            "filter_failed_count": int(len(failures)),
            "filter_hit_count": int(len(hits)),
            "filter_reject_reasons": _json_dumps(failures),
            "filter_hit_details": _json_dumps(hits),
        }

    def _eval_scoring_row(self, row: pd.Series, profile: str) -> Dict[str, Any]:
        if not bool(row.get("is_candidate_after_filters", False)):
            return {
                "score_axis_strength": 0.0,
                "score_axis_industry": 0.0,
                "score_axis_chip": 0.0,
                "score_total": 0.0,
                "score_details": _json_dumps({"skipped": "failed_filters"}),
            }

        cfg_sc = self.config.get("scoring", {}) or {}
        axes = cfg_sc.get("axes", {}) or {}
        redundancy = cfg_sc.get("redundancy_groups", []) or []
        total_scale = _safe_float(cfg_sc.get("total_score_scale", 100.0))
        if np.isnan(total_scale) or total_scale <= 0:
            total_scale = 100.0

        # Calculate item normalized values first (for redundancy processing).
        item_cache: Dict[str, Dict[str, Any]] = {}
        for axis_name, axis_cfg in axes.items():
            for item in (axis_cfg.get("items", []) or []):
                if not isinstance(item, dict) or not bool(item.get("enabled", True)):
                    continue
                feat = str(item.get("feature"))
                ev = self._eval_rule(row, item, profile, f"score:{axis_name}")
                item_cache[feat] = {
                    "axis": axis_name,
                    "weight": _safe_float(item.get("weight", 1.0)),
                    "raw_value": ev.raw_value,
                    "normalized": ev.normalized,
                    "reason": ev.reason,
                    "feature": feat,
                }

        # Redundancy control: max-only group.
        for grp in redundancy:
            if not isinstance(grp, dict):
                continue
            members = [str(x) for x in (grp.get("members") or []) if str(x) in item_cache]
            if len(members) <= 1:
                continue
            mode = str(grp.get("mode", "max_only"))
            if mode != "max_only":
                continue
            best = max(members, key=lambda x: item_cache[x]["normalized"])
            for m in members:
                if m == best:
                    continue
                item_cache[m]["normalized"] = 0.0
                item_cache[m]["reason"] = f"{item_cache[m]['reason']}|redundancy_zeroed_by:{best}"

        axis_scores: Dict[str, float] = {}
        axis_payload: Dict[str, Any] = {}
        axis_weight_total = 0.0
        weighted_sum = 0.0
        for axis_name, axis_cfg in axes.items():
            axis_w = _safe_float(axis_cfg.get("axis_weight", 1.0))
            if np.isnan(axis_w) or axis_w <= 0:
                axis_w = 1.0
            items = [v for v in item_cache.values() if v["axis"] == axis_name]
            denom = sum(max(_safe_float(x["weight"]), 0.0) for x in items)
            if denom <= 0:
                axis_score = 0.0
            else:
                axis_score = sum(max(_safe_float(x["weight"]), 0.0) * x["normalized"] for x in items) / denom
            axis_score_scaled = axis_score * total_scale
            axis_scores[axis_name] = float(axis_score_scaled)
            axis_payload[axis_name] = {
                "axis_weight": axis_w,
                "axis_score": float(axis_score_scaled),
                "features": {
                    x["feature"]: {
                        "raw_value": None if np.isnan(x["raw_value"]) else float(x["raw_value"]),
                        "normalized": float(x["normalized"]),
                        "item_weight": float(x["weight"]),
                        "contribution": float(x["normalized"] * x["weight"]),
                        "reason": x["reason"],
                    }
                    for x in items
                },
            }
            weighted_sum += axis_score_scaled * axis_w
            axis_weight_total += axis_w

        total = weighted_sum / max(axis_weight_total, 1e-9)
        return {
            "score_axis_strength": float(axis_scores.get("strength_axis", 0.0)),
            "score_axis_industry": float(axis_scores.get("industry_front_axis", 0.0)),
            "score_axis_chip": float(axis_scores.get("chip_base_axis", 0.0)),
            "score_total": float(total),
            "score_details": _json_dumps(axis_payload),
        }

    def _eval_trigger_row(self, row: pd.Series, profile: str) -> Dict[str, Any]:
        if not bool(row.get("is_candidate_after_filters", False)):
            return {
                "trigger_breakout_pass": False,
                "trigger_momentum_pass": False,
                "trigger_quality_pass": False,
                "trigger_groups_passed": 0,
                "trigger_rules_passed": 0,
                "trigger_status": False,
                "trigger_details": _json_dumps({"skipped": "failed_filters"}),
            }

        trig_cfg = self.config.get("trigger", {}) or {}
        groups = trig_cfg.get("groups", {}) or {}
        group_result: Dict[str, Dict[str, Any]] = {}
        groups_passed = 0
        rules_passed = 0

        for gname, gcfg in groups.items():
            g_rules = [r for r in (gcfg.get("rules", []) or []) if isinstance(r, dict) and bool(r.get("enabled", True))]
            passed_list = []
            failed_list = []
            detail_rules = []
            for rule in g_rules:
                rid = str(rule.get("id") or rule.get("feature"))
                ev = self._eval_rule(row, rule, profile, f"trigger:{gname}")
                if ev.passed:
                    passed_list.append(rid)
                    rules_passed += 1
                else:
                    failed_list.append(rid)
                detail_rules.append(
                    {
                        "id": rid,
                        "feature": str(rule.get("feature")),
                        "passed": bool(ev.passed),
                        "raw_value": None if np.isnan(ev.raw_value) else float(ev.raw_value),
                        "normalized": float(ev.normalized),
                        "reason": ev.reason,
                    }
                )
            min_pass = int(gcfg.get("min_pass", 1))
            g_pass = len(passed_list) >= max(min_pass, 0)
            if g_pass:
                groups_passed += 1
            group_result[gname] = {
                "pass": bool(g_pass),
                "min_pass": min_pass,
                "passed_rules": passed_list,
                "failed_rules": failed_list,
                "rules": detail_rules,
            }

        min_groups = int(trig_cfg.get("min_groups_pass", 1))
        min_rules = int(trig_cfg.get("min_total_rules_pass", 1))
        trigger_ok = groups_passed >= min_groups and rules_passed >= min_rules
        return {
            "trigger_breakout_pass": bool(group_result.get("breakout", {}).get("pass", False)),
            "trigger_momentum_pass": bool(group_result.get("momentum", {}).get("pass", False)),
            "trigger_quality_pass": bool(group_result.get("quality", {}).get("pass", False)),
            "trigger_groups_passed": int(groups_passed),
            "trigger_rules_passed": int(rules_passed),
            "trigger_status": bool(trigger_ok),
            "trigger_details": _json_dumps(group_result),
        }

    def _build_downgraded_observations(self, row: pd.Series) -> str:
        obs = {}
        for feat in list(self.config.get("downgraded_features", {}).get("features", []) or []):
            if feat in row.index:
                v = row.get(feat)
                if pd.isna(v):
                    obs[feat] = None
                else:
                    try:
                        obs[feat] = float(v)
                    except Exception:
                        obs[feat] = str(v)
        return _json_dumps(obs)

    def _build_explain_json(self, row: pd.Series) -> str:
        payload = {
            "layers": {
                "filters": {
                    "passed": bool(row.get("is_candidate_after_filters", False)),
                    "failed_count": int(row.get("filter_failed_count", 0)),
                    "reject_reasons": json.loads(str(row.get("filter_reject_reasons", "[]") or "[]")),
                    "hit_details": json.loads(str(row.get("filter_hit_details", "[]") or "[]")),
                },
                "scoring": {
                    "score_total": _safe_float(row.get("score_total")),
                    "axis_strength": _safe_float(row.get("score_axis_strength")),
                    "axis_industry": _safe_float(row.get("score_axis_industry")),
                    "axis_chip": _safe_float(row.get("score_axis_chip")),
                    "details": json.loads(str(row.get("score_details", "{}") or "{}")),
                },
                "trigger": {
                    "status": bool(row.get("trigger_status", False)),
                    "groups_passed": int(row.get("trigger_groups_passed", 0)),
                    "rules_passed": int(row.get("trigger_rules_passed", 0)),
                    "breakout_pass": bool(row.get("trigger_breakout_pass", False)),
                    "momentum_pass": bool(row.get("trigger_momentum_pass", False)),
                    "quality_pass": bool(row.get("trigger_quality_pass", False)),
                    "details": json.loads(str(row.get("trigger_details", "{}") or "{}")),
                },
                "downgraded_observation": json.loads(str(row.get("downgraded_observations", "{}") or "{}")),
            },
            "final": {
                "is_candidate_after_filters": bool(row.get("is_candidate_after_filters", False)),
                "score_total": _safe_float(row.get("score_total")),
                "trigger_status": bool(row.get("trigger_status", False)),
                "signal_ready": bool(row.get("signal_ready", False)),
            },
        }
        return _json_dumps(payload)
