# -*- coding: utf-8 -*-
"""
二次启动策略专用 LightGBM 二级评分器。

设计原则：
1. 只对规则策略已经筛出的候选做二级排序，不替代原有规则闸门；
2. 优先使用日线已存在特征，降低接入复杂度；
3. 若模型文件不存在或 LightGBM 不可用，则自动失效，不影响主流程。
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Dict, List, Optional

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
    """二次启动 LGB 评分器配置"""
    model_path: str = "models/secondary_launch_lgb_model.txt"
    config_path: str = "models/secondary_launch_lgb_model.json"
    enabled: bool = True
    mode: str = "blend"
    blend_weight: float = 0.35
    min_probability: float = 0.569
    default_feature_value: float = 0.0


class SecondaryLaunchLGBScorer:
    """二次启动策略的机器学习二级评分器"""

    def __init__(self, config: Optional[SecondaryLaunchLGBScorerConfig] = None):
        self.config = config or SecondaryLaunchLGBScorerConfig()
        self.model = None
        self.feature_cols: List[str] = []
        self.is_loaded = False
        if self.config.enabled and LGB_AVAILABLE:
            self._load_model()

    def _load_model(self) -> None:
        if not os.path.exists(self.config.model_path) or not os.path.exists(self.config.config_path):
            logger.info("二次启动 LGB 模型文件不存在，跳过加载")
            return
        try:
            self.model = lgb.Booster(model_file=self.config.model_path)
            with open(self.config.config_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.feature_cols = list(data.get("feature_cols") or [])
            self.is_loaded = bool(self.feature_cols)
            if self.is_loaded:
                logger.info("二次启动 LGB 模型加载成功，特征数=%s", len(self.feature_cols))
        except Exception as e:
            logger.warning("二次启动 LGB 模型加载失败: %s", e)
            self.model = None
            self.feature_cols = []
            self.is_loaded = False

    def is_available(self) -> bool:
        return self.config.enabled and self.is_loaded and self.model is not None

    @staticmethod
    def _safe_ratio(a: pd.Series, b: pd.Series) -> pd.Series:
        return (a / b.replace(0, np.nan)).replace([np.inf, -np.inf], np.nan)

    def prepare_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """从当前候选集中构造模型输入特征。"""
        feat = pd.DataFrame(index=df.index)
        feat["rs20"] = pd.to_numeric(df.get("rs20"), errors="coerce")
        feat["rs20_rank"] = feat["rs20"].rank(pct=True, method="average")
        feat["drawdown_from_peak"] = pd.to_numeric(df.get("drawdown_from_peak"), errors="coerce")
        feat["days_since_last_limit_up"] = pd.to_numeric(df.get("days_since_last_limit_up"), errors="coerce")
        feat["limit_up_count_10"] = pd.to_numeric(df.get("limit_up_count_10"), errors="coerce")
        feat["close_ma5_dev"] = (pd.to_numeric(df.get("close"), errors="coerce") / pd.to_numeric(df.get("ma5"), errors="coerce") - 1.0).abs()
        feat["close_ma10_ratio"] = self._safe_ratio(pd.to_numeric(df.get("close"), errors="coerce"), pd.to_numeric(df.get("ma10"), errors="coerce"))
        feat["ma5_ma10_ratio"] = self._safe_ratio(pd.to_numeric(df.get("ma5"), errors="coerce"), pd.to_numeric(df.get("ma10"), errors="coerce"))
        feat["volume_ratio_5"] = self._safe_ratio(pd.to_numeric(df.get("vol"), errors="coerce"), pd.to_numeric(df.get("vol_ma5"), errors="coerce"))
        feat["volume_trend_ratio"] = self._safe_ratio(pd.to_numeric(df.get("vol_ma5"), errors="coerce"), pd.to_numeric(df.get("vol_ma20"), errors="coerce"))
        feat["amt_ma20_log"] = np.log1p(pd.to_numeric(df.get("amt_ma20"), errors="coerce").clip(lower=0))
        feat["limit_up_amt_ratio"] = pd.to_numeric(df.get("limit_up_amt_ratio"), errors="coerce")
        feat["next_ret_after_limit_up"] = pd.to_numeric(df.get("next_ret_after_limit_up"), errors="coerce")
        feat["ret5"] = pd.to_numeric(df.get("ret5"), errors="coerce")
        feat["is_above_ma10"] = (pd.to_numeric(df.get("close"), errors="coerce") >= pd.to_numeric(df.get("ma10"), errors="coerce")).astype(float)
        feat["is_ma5_above_ma10"] = (pd.to_numeric(df.get("ma5"), errors="coerce") >= pd.to_numeric(df.get("ma10"), errors="coerce")).astype(float)

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
            logger.warning("二次启动 LGB 预测失败: %s", e)
            return np.full(len(df), np.nan, dtype=float)

    def apply(self, df: pd.DataFrame, score_col: str = "signal_score") -> pd.DataFrame:
        """将 LGB 概率融合到原有信号分数，并过滤明显低质量候选。"""
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

        # 对极弱承接样本直接剔除，避免规则高分但经验上胜率较差的假二启。
        out = out[(out["lgb_prob"].isna()) | (out["lgb_prob"] >= float(self.config.min_probability))].copy()
        return out
