# -*- coding: utf-8 -*-
"""Secondary-launch LightGBM scorer with model auto-repair guards."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

import numpy as np
import pandas as pd

try:
    import lightgbm as lgb
    LGB_AVAILABLE = True
except ImportError:
    LGB_AVAILABLE = False

from src.core.logger import get_logger

logger = get_logger("secondary_launch_lgb_scorer")


@dataclass
class SecondaryLaunchLGBScorerConfig:
    """Config for secondary-launch LGB scorer."""

    model_path: str = "models/secondary_launch_lgb_model.txt"
    config_path: str = "models/secondary_launch_lgb_model.json"
    enabled: bool = True
    mode: str = "blend"
    blend_weight: float = 0.35
    min_probability: float = 0.569
    default_feature_value: float = 0.0


class SecondaryLaunchLGBScorer:
    """Second-stage ML scorer for secondary-launch strategy."""

    def __init__(self, config: Optional[SecondaryLaunchLGBScorerConfig] = None):
        self.config = config or SecondaryLaunchLGBScorerConfig()
        self.model = None
        self.feature_cols: List[str] = []
        self.is_loaded = False
        if self.config.enabled and LGB_AVAILABLE:
            self._load_model()

    @staticmethod
    def _is_valid_lgb_text_model(text: str) -> bool:
        if not text.startswith("tree\n"):
            return False
        if "feature_names=" not in text or "tree_sizes=" not in text:
            return False
        tree_match = re.search(r"tree_sizes=([0-9\s]+)", text)
        expected_trees = (
            len([x for x in tree_match.group(1).split() if x.strip()])
            if tree_match
            else 0
        )
        actual_trees = text.count("\nTree=")
        if actual_trees <= 0:
            return False
        if expected_trees > 0 and actual_trees != expected_trees:
            return False
        return text.rstrip().endswith("pandas_categorical:[]")

    def _prepare_model_file(self, model_path: str) -> str:
        path = Path(model_path)
        text = path.read_text(encoding="utf-8", errors="replace")
        if self._is_valid_lgb_text_model(text):
            return str(path)

        fixed = text.replace("\r\n", "\n").replace("\r", "\n")
        if fixed != text and self._is_valid_lgb_text_model(fixed):
            backup = path.with_name(path.name + ".auto_repair_backup")
            try:
                if not backup.exists():
                    backup.write_text(text, encoding="utf-8", newline="\n")
            except Exception:
                logger.warning("secondary-launch LGB backup failed: %s", backup)
            path.write_text(fixed, encoding="utf-8", newline="\n")
            logger.warning("secondary-launch LGB model auto-repaired: %s", path)
            return str(path)

        raise ValueError(f"invalid secondary launch lgb model format: {model_path}")

    def _load_model(self) -> None:
        if not os.path.exists(self.config.model_path) or not os.path.exists(self.config.config_path):
            logger.info("secondary-launch LGB model/config not found, skip load")
            return
        try:
            model_file = self._prepare_model_file(self.config.model_path)
            self.model = lgb.Booster(model_file=model_file)
            with open(self.config.config_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.feature_cols = list(data.get("feature_cols") or [])
            self.is_loaded = bool(self.feature_cols)
            if self.is_loaded:
                logger.info("secondary-launch LGB loaded, feature_count=%s", len(self.feature_cols))
        except Exception as e:
            logger.warning("secondary-launch LGB load failed: %s", e)
            self.model = None
            self.feature_cols = []
            self.is_loaded = False

    def is_available(self) -> bool:
        return self.config.enabled and self.is_loaded and self.model is not None

    @staticmethod
    def _safe_ratio(a: pd.Series, b: pd.Series) -> pd.Series:
        return (a / b.replace(0, np.nan)).replace([np.inf, -np.inf], np.nan)

    def prepare_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """Build model features from current candidate rows."""
        feat = pd.DataFrame(index=df.index)
        feat["rs20"] = pd.to_numeric(df.get("rs20"), errors="coerce")
        feat["rs20_rank"] = feat["rs20"].rank(pct=True, method="average")
        feat["drawdown_from_peak"] = pd.to_numeric(df.get("drawdown_from_peak"), errors="coerce")
        feat["days_since_last_limit_up"] = pd.to_numeric(df.get("days_since_last_limit_up"), errors="coerce")
        feat["limit_up_count_10"] = pd.to_numeric(df.get("limit_up_count_10"), errors="coerce")
        feat["close_ma5_dev"] = (
            pd.to_numeric(df.get("close"), errors="coerce")
            / pd.to_numeric(df.get("ma5"), errors="coerce")
            - 1.0
        ).abs()
        feat["close_ma10_ratio"] = self._safe_ratio(
            pd.to_numeric(df.get("close"), errors="coerce"),
            pd.to_numeric(df.get("ma10"), errors="coerce"),
        )
        feat["ma5_ma10_ratio"] = self._safe_ratio(
            pd.to_numeric(df.get("ma5"), errors="coerce"),
            pd.to_numeric(df.get("ma10"), errors="coerce"),
        )
        feat["volume_ratio_5"] = self._safe_ratio(
            pd.to_numeric(df.get("vol"), errors="coerce"),
            pd.to_numeric(df.get("vol_ma5"), errors="coerce"),
        )
        feat["volume_trend_ratio"] = self._safe_ratio(
            pd.to_numeric(df.get("vol_ma5"), errors="coerce"),
            pd.to_numeric(df.get("vol_ma20"), errors="coerce"),
        )
        feat["amt_ma20_log"] = np.log1p(
            pd.to_numeric(df.get("amt_ma20"), errors="coerce").clip(lower=0)
        )
        feat["limit_up_amt_ratio"] = pd.to_numeric(df.get("limit_up_amt_ratio"), errors="coerce")
        feat["next_ret_after_limit_up"] = pd.to_numeric(df.get("next_ret_after_limit_up"), errors="coerce")
        feat["ret5"] = pd.to_numeric(df.get("ret5"), errors="coerce")
        feat["is_above_ma10"] = (
            pd.to_numeric(df.get("close"), errors="coerce")
            >= pd.to_numeric(df.get("ma10"), errors="coerce")
        ).astype(float)
        feat["is_ma5_above_ma10"] = (
            pd.to_numeric(df.get("ma5"), errors="coerce")
            >= pd.to_numeric(df.get("ma10"), errors="coerce")
        ).astype(float)

        X = pd.DataFrame(index=df.index)
        for col in self.feature_cols:
            if col in feat.columns:
                X[col] = pd.to_numeric(feat[col], errors="coerce").fillna(self.config.default_feature_value)
            else:
                X[col] = self.config.default_feature_value
        return X

    def predict_proba(self, df: pd.DataFrame) -> np.ndarray:
        if not self.is_available():
            return np.full(len(df), np.nan, dtype=float)
        X = self.prepare_features(df)
        try:
            prob = self.model.predict(X)
            return np.clip(np.asarray(prob, dtype=float), 0.0, 1.0)
        except Exception as e:
            logger.warning("secondary-launch LGB predict failed: %s", e)
            return np.full(len(df), np.nan, dtype=float)

    def apply(self, df: pd.DataFrame, score_col: str = "signal_score") -> pd.DataFrame:
        """Blend LGB probabilities into rule score and filter very weak samples."""
        out = df.copy()
        prob = self.predict_proba(out)
        out["lgb_prob"] = prob
        if np.isnan(prob).all():
            return out

        valid = ~np.isnan(prob)
        prob_score = np.where(valid, prob * 100.0, np.nan)
        if self.config.mode == "replace":
            out.loc[valid, score_col] = prob_score[valid]
        else:
            w = float(self.config.blend_weight)
            out.loc[valid, score_col] = (
                out.loc[valid, score_col].astype(float) * (1.0 - w)
                + prob_score[valid] * w
            )

        out = out[(out["lgb_prob"].isna()) | (out["lgb_prob"] >= float(self.config.min_probability))].copy()
        return out
