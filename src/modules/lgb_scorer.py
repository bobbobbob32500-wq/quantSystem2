"""
LightGBM评分器 - 供突破策略使用
替代或融合原有的线性评分
"""
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

logger = get_logger("lgb_scorer")


@dataclass
class LGBScorerConfig:
    """LightGBM评分器配置"""
    model_path: str = "models/breakout_lgb_model.txt"
    config_path: str = "models/breakout_lgb_model.json"
    enabled: bool = True
    # 融合模式: "replace"=完全替代线性评分, "blend"=加权融合
    mode: str = "blend"
    # 融合权重 (LGB权重, 线性权重)
    blend_weights: tuple = (0.6, 0.4)
    # 特征缺失时的默认值
    default_feature_value: float = 0.0


class LGBScorer:
    """LightGBM评分器"""
    
    def __init__(self, config: Optional[LGBScorerConfig] = None):
        self.config = config or LGBScorerConfig()
        self.model = None
        self.feature_cols: List[str] = []
        self.lgb_params: Dict = {}
        self.is_loaded = False
        
        if self.config.enabled and LGB_AVAILABLE:
            self._load_model()
    
    def _load_model(self):
        """加载模型"""
        # 尝试加载模型文件
        if os.path.exists(self.config.model_path):
            try:
                self.model = lgb.Booster(model_file=self.config.model_path)
                self.is_loaded = True
                logger.info(f"LightGBM模型已加载: {self.config.model_path}")
            except Exception as e:
                logger.warning(f"加载模型文件失败: {e}")
        
        # 加载模型配置
        if os.path.exists(self.config.config_path):
            try:
                with open(self.config.config_path, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
                self.feature_cols = cfg.get("feature_cols", [])
                self.lgb_params = cfg.get("lgb_params", {})
                logger.info(f"模型配置已加载: {len(self.feature_cols)}个特征")
            except Exception as e:
                logger.warning(f"加载模型配置失败: {e}")
    
    def is_available(self) -> bool:
        """检查评分器是否可用"""
        return self.config.enabled and self.is_loaded and len(self.feature_cols) > 0
    
    def prepare_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """准备特征矩阵"""
        X = pd.DataFrame(index=df.index)
        
        for col in self.feature_cols:
            if col in df.columns:
                X[col] = df[col].fillna(self.config.default_feature_value)
            else:
                X[col] = self.config.default_feature_value
                logger.debug(f"特征缺失，使用默认值: {col}")
        
        return X
    
    def predict_proba(self, df: pd.DataFrame) -> np.ndarray:
        """预测概率"""
        if not self.is_available():
            return np.ones(len(df)) * 0.5  # 返回中性概率
        
        X = self.prepare_features(df)
        try:
            probs = self.model.predict(X)
            return np.clip(probs, 0.0, 1.0)
        except Exception as e:
            logger.error(f"预测失败: {e}")
            return np.ones(len(df)) * 0.5
    
    def compute_scores(
        self, 
        df: pd.DataFrame, 
        linear_scores: Optional[np.ndarray] = None
    ) -> np.ndarray:
        """
        计算综合评分
        
        Args:
            df: 包含特征的DataFrame
            linear_scores: 原有线性评分（用于融合模式）
        
        Returns:
            评分数组 (0-100)
        """
        if not self.is_available():
            if linear_scores is not None:
                return linear_scores
            return np.zeros(len(df))
        
        # 获取LGB概率
        probs = self.predict_proba(df)
        
        # 转换为0-100评分
        lgb_scores = probs * 100
        
        if self.config.mode == "replace":
            return lgb_scores
        
        elif self.config.mode == "blend" and linear_scores is not None:
            # 加权融合
            w_lgb, w_linear = self.config.blend_weights
            blended = w_lgb * lgb_scores + w_linear * linear_scores
            return blended / (w_lgb + w_linear)
        
        return lgb_scores
    
    def get_feature_importance(self) -> Dict[str, float]:
        """获取特征重要性"""
        if not self.is_available():
            return {}
        
        try:
            importance = self.model.feature_importance(importance_type="gain")
            return dict(zip(self.feature_cols, importance))
        except Exception as e:
            logger.error(f"获取特征重要性失败: {e}")
            return {}


def create_lgb_scorer(
    enabled: bool = True,
    mode: str = "blend",
    blend_weights: tuple = (0.6, 0.4)
) -> LGBScorer:
    """创建LightGBM评分器"""
    config = LGBScorerConfig(
        enabled=enabled,
        mode=mode,
        blend_weights=blend_weights
    )
    return LGBScorer(config)
