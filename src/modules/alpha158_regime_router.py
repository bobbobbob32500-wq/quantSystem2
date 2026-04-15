# -*- coding: utf-8 -*-
"""
Alpha158 市场状态路由器

用途：
1. 基于主板均价序列判断市场状态（趋势/震荡/弱势）。
2. 按市场状态对 Alpha158 分数做轻量重排（双引擎思想的最小实现）。
3. 输出动态阈值与 top_n 调整系数，供上层选股流程使用。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List

import numpy as np
import pandas as pd


@dataclass
class RegimeDecision:
    """状态决策结果"""

    regime: str
    score_threshold_delta: float
    top_n_multiplier: float
    trend_weight: float
    pullback_weight: float
    reason: str


class Alpha158RegimeRouter:
    """Alpha158 状态切换与双引擎路由"""

    def __init__(
        self,
        db,
        lookback: int = 30,
        trend_ret5_threshold: float = 0.015,
        weak_ret5_threshold: float = -0.02,
        ma_deviation_threshold: float = 0.01,
        trend_score_threshold_delta: float = 0.03,
        sideways_score_threshold_delta: float = 0.05,
        weak_score_threshold_delta: float = 0.08,
        trend_top_n_multiplier: float = 1.0,
        sideways_top_n_multiplier: float = 0.8,
        weak_top_n_multiplier: float = 0.6,
        enable: bool = True,
    ):
        self.db = db
        self.lookback = max(20, int(lookback))
        self.trend_ret5_threshold = float(trend_ret5_threshold)
        self.weak_ret5_threshold = float(weak_ret5_threshold)
        self.ma_deviation_threshold = float(ma_deviation_threshold)
        self.trend_score_threshold_delta = float(trend_score_threshold_delta)
        self.sideways_score_threshold_delta = float(sideways_score_threshold_delta)
        self.weak_score_threshold_delta = float(weak_score_threshold_delta)
        self.trend_top_n_multiplier = float(trend_top_n_multiplier)
        self.sideways_top_n_multiplier = float(sideways_top_n_multiplier)
        self.weak_top_n_multiplier = float(weak_top_n_multiplier)
        self.enable = bool(enable)

    def decide(self, end_date: str) -> RegimeDecision:
        """输出当前市场状态与参数调整建议"""
        if not self.enable:
            return RegimeDecision(
                regime="neutral",
                score_threshold_delta=0.0,
                top_n_multiplier=1.0,
                trend_weight=0.5,
                pullback_weight=0.5,
                reason="状态路由关闭",
            )

        closes = self._load_mainboard_avg_close(end_date=end_date, limit=max(self.lookback, 21))
        if len(closes) < 21:
            return RegimeDecision(
                regime="neutral",
                score_threshold_delta=0.0,
                top_n_multiplier=1.0,
                trend_weight=0.5,
                pullback_weight=0.5,
                reason="样本不足",
            )

        close_arr = np.array(closes, dtype=float)
        ma20 = float(np.mean(close_arr[-20:]))
        last_close = float(close_arr[-1])
        ret5 = float(last_close / (close_arr[-6] + 1e-8) - 1.0)
        ma_dev = float(last_close / (ma20 + 1e-8) - 1.0) if ma20 > 0 else 0.0

        # 趋势市：5日涨幅较高且站上20日均线
        if ret5 >= self.trend_ret5_threshold and ma_dev >= self.ma_deviation_threshold:
            return RegimeDecision(
                regime="trend",
                score_threshold_delta=self.trend_score_threshold_delta,
                top_n_multiplier=self.trend_top_n_multiplier,
                trend_weight=0.7,
                pullback_weight=0.3,
                reason=f"ret5={ret5:.2%}, ma_dev={ma_dev:.2%}",
            )

        # 弱势市：5日跌幅较大且跌破20日均线
        if ret5 <= self.weak_ret5_threshold and ma_dev <= -self.ma_deviation_threshold:
            return RegimeDecision(
                regime="weak",
                score_threshold_delta=self.weak_score_threshold_delta,
                top_n_multiplier=self.weak_top_n_multiplier,
                trend_weight=0.25,
                pullback_weight=0.75,
                reason=f"ret5={ret5:.2%}, ma_dev={ma_dev:.2%}",
            )

        # 其余视为震荡
        return RegimeDecision(
            regime="sideways",
            score_threshold_delta=self.sideways_score_threshold_delta,
            top_n_multiplier=self.sideways_top_n_multiplier,
            trend_weight=0.4,
            pullback_weight=0.6,
            reason=f"ret5={ret5:.2%}, ma_dev={ma_dev:.2%}",
        )

    def apply_dual_engine_score(
        self,
        fdf: pd.DataFrame,
        base_score_col: str = "alpha158_score",
        roc5_col: str = "ROC5",
        ma_cross_col: str = "MA_CROSS",
        vol_ratio_col: str = "VOL_RATIO5",
        amp_col: str = "AMP20",
    ) -> pd.Series:
        """按状态融合趋势引擎与回调引擎得分"""
        if base_score_col not in fdf.columns:
            return pd.Series(np.zeros(len(fdf)), index=fdf.index)

        decision = self.decide(str(fdf.get("_end_date", pd.Series([""])).iloc[0]) if not fdf.empty else "")
        base_score = fdf[base_score_col].fillna(0.0).astype(float)

        # 趋势引擎：偏好 MA_CROSS、VOL_RATIO、正向 ROC5
        trend_part = np.zeros(len(fdf), dtype=float)
        if ma_cross_col in fdf.columns:
            trend_part += fdf[ma_cross_col].fillna(0.0).values * 0.40
        if vol_ratio_col in fdf.columns:
            trend_part += fdf[vol_ratio_col].fillna(0.0).values * 0.25
        if roc5_col in fdf.columns:
            trend_part += fdf[roc5_col].fillna(0.0).values * 0.35

        # 回调引擎：偏好轻回调、低振幅
        pullback_part = np.zeros(len(fdf), dtype=float)
        if roc5_col in fdf.columns:
            roc5_vals = fdf[roc5_col].fillna(0.0).values
            pullback_band = np.where((roc5_vals > -0.06) & (roc5_vals < -0.01), 1.0, 0.0)
            pullback_part += pullback_band * 0.60
            pullback_part += np.where(roc5_vals > 0.04, -0.20, 0.0)
        if amp_col in fdf.columns:
            pullback_part += (-fdf[amp_col].fillna(0.0).values) * 0.40

        # 状态加权融合：保留原始分的主体地位，额外加入双引擎增量
        fused = (
            base_score
            + decision.trend_weight * trend_part
            + decision.pullback_weight * pullback_part
        )
        return pd.Series(fused, index=fdf.index)

    def _load_mainboard_avg_close(self, end_date: str, limit: int) -> List[float]:
        rows = self.db.query(
            "SELECT trade_date, AVG(close) AS avg_close FROM stock_daily "
            "WHERE trade_date <= ? AND close > 0 AND (ts_code LIKE '60%.SH') "
            "GROUP BY trade_date ORDER BY trade_date DESC LIMIT ?",
            (end_date, limit),
        )
        if not rows:
            return []
        closes_desc = [float(r["avg_close"]) for r in rows if r.get("avg_close") is not None]
        return list(reversed(closes_desc))
