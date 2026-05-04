# -*- coding: utf-8 -*-
"""
Alpha158 市场状态路由器

用途：
1. 基于主板均价序列判断市场状态（趋势/震荡/弱势）。
2. 结合主板广度指标进行状态确认（上涨占比/中位涨跌幅/20日新高占比）。
3. 按市场状态对 Alpha158 分数做轻量重排（双引擎思想的最小实现）。
4. 输出动态阈值与 top_n 调整系数，供上层选股流程使用。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Tuple

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
    breadth_up_ratio: float = float("nan")
    breadth_median_return: float = float("nan")
    breadth_new_high_ratio: float = float("nan")
    breadth_state: str = "unknown"
    regime_downgraded: bool = False


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
        trend_breadth_min_up_ratio: float = 0.52,
        trend_breadth_min_median_ret: float = 0.0,
        trend_breadth_min_new_high_ratio: float = 0.08,
        weak_breadth_max_up_ratio: float = 0.42,
        weak_breadth_max_median_ret: float = -0.003,
        weak_breadth_max_new_high_ratio: float = 0.05,
        weak_extra_score_threshold_delta: float = 0.03,
        weak_extra_top_n_multiplier: float = 0.85,
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
        self.trend_breadth_min_up_ratio = float(trend_breadth_min_up_ratio)
        self.trend_breadth_min_median_ret = float(trend_breadth_min_median_ret)
        self.trend_breadth_min_new_high_ratio = float(trend_breadth_min_new_high_ratio)
        self.weak_breadth_max_up_ratio = float(weak_breadth_max_up_ratio)
        self.weak_breadth_max_median_ret = float(weak_breadth_max_median_ret)
        self.weak_breadth_max_new_high_ratio = float(weak_breadth_max_new_high_ratio)
        self.weak_extra_score_threshold_delta = float(weak_extra_score_threshold_delta)
        self.weak_extra_top_n_multiplier = float(weak_extra_top_n_multiplier)
        self.enable = bool(enable)

    def decide(self, end_date: str) -> RegimeDecision:
        """输出当前市场状态与参数调整建议"""
        if not self.enable:
            return self._decision_with_breadth(
                regime="neutral",
                reason="状态路由关闭",
            )

        closes = self._load_mainboard_avg_close(end_date=end_date, limit=max(self.lookback, 21))
        if len(closes) < 21:
            return self._decision_with_breadth(
                regime="neutral",
                reason="样本不足",
                end_date=end_date,
            )

        close_arr = np.array(closes, dtype=float)
        ma20 = float(np.mean(close_arr[-20:]))
        last_close = float(close_arr[-1])
        ret5 = float(last_close / (close_arr[-6] + 1e-8) - 1.0)
        ma_dev = float(last_close / (ma20 + 1e-8) - 1.0) if ma20 > 0 else 0.0

        base_regime = self._infer_base_regime(ret5=ret5, ma_dev=ma_dev)
        breadth_metrics = self._load_mainboard_breadth_metrics(end_date=end_date)
        breadth_state = self._classify_breadth_state(
            up_ratio=breadth_metrics["up_ratio"],
            median_ret=breadth_metrics["median_ret"],
            new_high_ratio=breadth_metrics["new_high_ratio"],
        )
        regime = base_regime
        regime_downgraded = False
        reason_suffix = (
            f"ret5={ret5:.2%}, ma_dev={ma_dev:.2%}, "
            f"up_ratio={breadth_metrics['up_ratio']:.2%}, "
            f"median={breadth_metrics['median_ret']:.2%}, "
            f"new_high={breadth_metrics['new_high_ratio']:.2%}"
        )

        if base_regime == "trend" and breadth_state == "weak":
            regime = "sideways"
            regime_downgraded = True
            reason_suffix += ", breadth弱化触发 trend->sideways"

        decision = self._decision_with_breadth(
            regime=regime,
            reason=reason_suffix,
            breadth_metrics=breadth_metrics,
            breadth_state=breadth_state,
            regime_downgraded=regime_downgraded,
        )

        if decision.regime == "weak" and breadth_state == "weak":
            decision.score_threshold_delta = float(
                decision.score_threshold_delta + self.weak_extra_score_threshold_delta
            )
            decision.top_n_multiplier = float(
                max(0.05, decision.top_n_multiplier * self.weak_extra_top_n_multiplier)
            )
            decision.reason = (
                f"{decision.reason}, weak广度恶化增强(score_delta+={self.weak_extra_score_threshold_delta:.2f}, "
                f"top_n*={self.weak_extra_top_n_multiplier:.2f})"
            )

        return decision

    def _infer_base_regime(self, ret5: float, ma_dev: float) -> str:
        if ret5 >= self.trend_ret5_threshold and ma_dev >= self.ma_deviation_threshold:
            return "trend"
        if ret5 <= self.weak_ret5_threshold and ma_dev <= -self.ma_deviation_threshold:
            return "weak"
        return "sideways"

    def _decision_with_breadth(
        self,
        regime: str,
        reason: str,
        end_date: str = "",
        breadth_metrics: Dict[str, float] | None = None,
        breadth_state: str = "unknown",
        regime_downgraded: bool = False,
    ) -> RegimeDecision:
        regime_key = str(regime or "sideways").strip().lower()
        if regime_key == "trend":
            base = {
                "score_threshold_delta": self.trend_score_threshold_delta,
                "top_n_multiplier": self.trend_top_n_multiplier,
                "trend_weight": 0.7,
                "pullback_weight": 0.3,
            }
        elif regime_key == "weak":
            base = {
                "score_threshold_delta": self.weak_score_threshold_delta,
                "top_n_multiplier": self.weak_top_n_multiplier,
                "trend_weight": 0.25,
                "pullback_weight": 0.75,
            }
        elif regime_key == "neutral":
            base = {
                "score_threshold_delta": 0.0,
                "top_n_multiplier": 1.0,
                "trend_weight": 0.5,
                "pullback_weight": 0.5,
            }
        else:
            base = {
                "score_threshold_delta": self.sideways_score_threshold_delta,
                "top_n_multiplier": self.sideways_top_n_multiplier,
                "trend_weight": 0.4,
                "pullback_weight": 0.6,
            }

        metrics = breadth_metrics or self._load_mainboard_breadth_metrics(end_date=end_date)
        return RegimeDecision(
            regime=regime_key,
            score_threshold_delta=float(base["score_threshold_delta"]),
            top_n_multiplier=float(base["top_n_multiplier"]),
            trend_weight=float(base["trend_weight"]),
            pullback_weight=float(base["pullback_weight"]),
            reason=str(reason or ""),
            breadth_up_ratio=float(metrics.get("up_ratio", float("nan"))),
            breadth_median_return=float(metrics.get("median_ret", float("nan"))),
            breadth_new_high_ratio=float(metrics.get("new_high_ratio", float("nan"))),
            breadth_state=str(breadth_state or "unknown"),
            regime_downgraded=bool(regime_downgraded),
        )

    def _classify_breadth_state(self, up_ratio: float, median_ret: float, new_high_ratio: float) -> str:
        if not np.isfinite(up_ratio) or not np.isfinite(median_ret) or not np.isfinite(new_high_ratio):
            return "unknown"
        if (
            up_ratio >= self.trend_breadth_min_up_ratio
            and median_ret >= self.trend_breadth_min_median_ret
            and new_high_ratio >= self.trend_breadth_min_new_high_ratio
        ):
            return "strong"
        if (
            up_ratio <= self.weak_breadth_max_up_ratio
            or median_ret <= self.weak_breadth_max_median_ret
            or new_high_ratio <= self.weak_breadth_max_new_high_ratio
        ):
            return "weak"
        return "neutral"

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

    def _load_mainboard_breadth_metrics(self, end_date: str) -> Dict[str, float]:
        default_metrics = {
            "up_ratio": float("nan"),
            "median_ret": float("nan"),
            "new_high_ratio": float("nan"),
        }
        dates = self.db.query(
            "SELECT DISTINCT trade_date FROM stock_daily WHERE trade_date <= ? ORDER BY trade_date DESC LIMIT 25",
            (end_date,),
        )
        if not dates:
            return default_metrics

        recent_dates_desc = [str(row["trade_date"]) for row in dates if row.get("trade_date")]
        if not recent_dates_desc:
            return default_metrics
        recent_dates = list(reversed(recent_dates_desc))
        latest_date = recent_dates[-1]
        start_date = recent_dates[0] if len(recent_dates) < 21 else recent_dates[-21]

        rows = self.db.query(
            "SELECT ts_code, trade_date, close, pct_chg FROM stock_daily "
            "WHERE trade_date >= ? AND trade_date <= ? AND close > 0 "
            "AND (ts_code LIKE '60%.SH' OR ts_code LIKE '00%.SZ' OR ts_code LIKE '001%.SZ')",
            (start_date, latest_date),
        )
        if not rows:
            return default_metrics

        df = pd.DataFrame(rows)
        if df.empty:
            return default_metrics
        df["trade_date"] = df["trade_date"].astype(str)
        for col in ("close", "pct_chg"):
            df[col] = pd.to_numeric(df[col], errors="coerce")
        df = df.dropna(subset=["close"])
        if df.empty:
            return default_metrics

        latest_df = df[df["trade_date"] == latest_date].copy()
        if latest_df.empty:
            return default_metrics

        latest_rets = pd.to_numeric(latest_df["pct_chg"], errors="coerce").fillna(0.0) / 100.0
        up_ratio = float((latest_rets > 0).mean()) if len(latest_rets) > 0 else float("nan")
        median_ret = float(latest_rets.median()) if len(latest_rets) > 0 else float("nan")

        eligible = 0
        new_high_count = 0
        grouped = df.sort_values(["ts_code", "trade_date"]).groupby("ts_code", sort=False)
        for _, g in grouped:
            if str(g["trade_date"].iloc[-1]) != latest_date:
                continue
            closes = pd.to_numeric(g["close"], errors="coerce").dropna().to_numpy(dtype=float)
            if closes.size < 20:
                continue
            eligible += 1
            trailing20 = closes[-20:]
            if closes[-1] >= np.max(trailing20) - 1e-8:
                new_high_count += 1

        new_high_ratio = float(new_high_count / eligible) if eligible > 0 else float("nan")
        return {
            "up_ratio": up_ratio,
            "median_ret": median_ret,
            "new_high_ratio": new_high_ratio,
        }
