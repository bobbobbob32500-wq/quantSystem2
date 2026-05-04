# -*- coding: utf-8 -*-
"""
行业周期检测与动态调整模块

核心思路：
- 不对行业一刀切，而是检测行业当前所处的周期阶段
- 周期阶段基于近期行业相对大盘的表现动态计算
- 上升期行业加权，下降期行业降权，震荡期中性

周期检测方法：
1. 计算行业近N日相对大盘的超额收益
2. 用超额收益的趋势（一阶差分）判断周期方向
3. 用超额收益的波动率判断周期稳定性
4. 综合给出行业状态: rising / falling / oscillating / recovery
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

from src.core.logger import get_logger

logger = get_logger("industry_cycle")


class IndustryCycleDetector:
    """行业周期检测器"""

    # 周期状态
    RISING = "rising"          # 上升期：超额收益为正且趋势向上
    FALLING = "falling"        # 下降期：超额收益为负且趋势向下
    OSCILLATING = "oscillating"  # 震荡期：超额收益波动大，无明确方向
    RECOVERY = "recovery"      # 恢复期：超额收益从负转正，趋势向上

    def __init__(
        self,
        db,
        lookback: int = 20,       # 回看天数（计算超额收益）
        trend_window: int = 5,    # 趋势判断窗口
        vol_threshold: float = 0.03,  # 波动率阈值（日超额收益标准差）
        min_stocks: int = 3,      # 行业最少股票数
    ):
        self.db = db
        self.lookback = lookback
        self.trend_window = trend_window
        self.vol_threshold = vol_threshold
        self.min_stocks = min_stocks

        # 缓存
        self._cache_date = None
        self._cache_result = None

    def _get_industry_returns(
        self, end_date: str, trade_dates: List[str]
    ) -> Tuple[Dict[str, np.ndarray], np.ndarray]:
        """计算各行业每日收益和大盘每日收益"""
        # 确定日期范围
        end_idx = trade_dates.index(end_date) if end_date in trade_dates else len(trade_dates) - 1
        start_idx = max(0, end_idx - self.lookback)
        dates = trade_dates[start_idx:end_idx + 1]

        if len(dates) < self.trend_window + 2:
            return {}, np.array([])

        # 获取股票行业映射
        stock_industry = {}
        for r in self.db.query("SELECT ts_code, industry FROM stock_basic WHERE industry IS NOT NULL"):
            stock_industry[r["ts_code"]] = r["industry"]

        # 批量获取日线
        date_min, date_max = dates[0], dates[-1]
        rows = self.db.query(
            "SELECT ts_code, trade_date, close, open FROM stock_daily "
            "WHERE trade_date >= ? AND trade_date <= ? AND close > 0",
            (date_min, date_max),
        )

        # 按日期+行业聚合收益
        date_ind_ret = {}  # (date, industry) -> [ret1, ret2, ...]
        date_all_ret = {}  # date -> [ret1, ret2, ...]

        for r in rows:
            ts = r["ts_code"]
            td = r["trade_date"].strftime("%Y%m%d") if hasattr(r["trade_date"], "strftime") else str(r["trade_date"])
            if td not in dates:
                continue
            close = float(r["close"])
            open_ = float(r["open"])
            if open_ <= 0:
                continue
            ret = (close - open_) / open_  # 日内收益

            ind = stock_industry.get(ts)
            if ind:
                key = (td, ind)
                if key not in date_ind_ret:
                    date_ind_ret[key] = []
                date_ind_ret[key].append(ret)

            if td not in date_all_ret:
                date_all_ret[td] = []
            date_all_ret[td].append(ret)

        # 计算各行业每日平均收益
        all_industries = set(ind for _, ind in date_ind_ret.keys())
        industry_daily_ret = {}
        for ind in all_industries:
            rets = []
            for d in dates:
                key = (d, ind)
                if key in date_ind_ret and len(date_ind_ret[key]) >= self.min_stocks:
                    rets.append(np.mean(date_ind_ret[key]))
                else:
                    rets.append(np.nan)
            industry_daily_ret[ind] = np.array(rets)

        # 大盘每日平均收益
        market_ret = []
        for d in dates:
            if d in date_all_ret and len(date_all_ret[d]) > 0:
                market_ret.append(np.mean(date_all_ret[d]))
            else:
                market_ret.append(np.nan)
        market_ret = np.array(market_ret)

        return industry_daily_ret, market_ret

    def detect(
        self, end_date: str, trade_dates: List[str]
    ) -> Dict[str, Dict]:
        """
        检测各行业周期状态

        Returns:
            {industry: {
                "state": "rising"/"falling"/"oscillating"/"recovery",
                "excess_ret": float,      # 近期平均超额收益
                "trend": float,           # 超额收益趋势（正=向上）
                "volatility": float,      # 超额收益波动率
                "weight": float,          # 建议权重 (0.5~1.5)
                "confidence": float,      # 置信度 (0~1)
            }}
        """
        # 缓存
        if self._cache_date == end_date:
            return self._cache_result

        industry_daily_ret, market_ret = self._get_industry_returns(end_date, trade_dates)

        if not industry_daily_ret or len(market_ret) < self.trend_window + 2:
            self._cache_date = end_date
            self._cache_result = {}
            return {}

        results = {}
        for ind, ind_ret in industry_daily_ret.items():
            # 计算超额收益
            excess = ind_ret - market_ret
            valid_mask = ~np.isnan(excess)
            valid_excess = excess[valid_mask]

            if len(valid_excess) < self.trend_window + 2:
                continue

            # 近期平均超额收益
            mean_excess = np.mean(valid_excess[-self.lookback:]) if len(valid_excess) >= self.lookback else np.mean(valid_excess)

            # 趋势：超额收益的一阶差分均值
            diff = np.diff(valid_excess)
            trend = np.mean(diff[-self.trend_window:]) if len(diff) >= self.trend_window else np.mean(diff)

            # 波动率
            vol = np.std(valid_excess)

            # 判断周期状态
            if vol > self.vol_threshold:
                # 高波动 -> 震荡
                if abs(mean_excess) < vol * 0.5:
                    state = self.OSCILLATING
                elif mean_excess > 0 and trend > 0:
                    state = self.RISING
                elif mean_excess < 0 and trend < 0:
                    state = self.FALLING
                elif mean_excess < 0 and trend > 0:
                    state = self.RECOVERY
                else:
                    state = self.OSCILLATING
            else:
                # 低波动
                if mean_excess > 0.002 and trend >= 0:
                    state = self.RISING
                elif mean_excess < -0.002 and trend <= 0:
                    state = self.FALLING
                elif mean_excess < -0.002 and trend > 0:
                    state = self.RECOVERY
                else:
                    state = self.OSCILLATING

            # 计算权重
            weight = self._compute_weight(state, mean_excess, trend, vol)

            # 置信度
            confidence = self._compute_confidence(state, mean_excess, vol)

            results[ind] = {
                "state": state,
                "excess_ret": float(mean_excess),
                "trend": float(trend),
                "volatility": float(vol),
                "weight": float(weight),
                "confidence": float(confidence),
            }

        self._cache_date = end_date
        self._cache_result = results
        return results

    def _compute_weight(
        self, state: str, mean_excess: float, trend: float, vol: float
    ) -> float:
        """
        计算行业权重

        权重范围: 0.3 ~ 1.5
        - rising: 1.0 + 超额收益放大
        - recovery: 0.8 + 趋势放大
        - oscillating: 0.7 ~ 1.0（根据超额收益微调）
        - falling: 0.3 ~ 0.6
        """
        if state == self.RISING:
            # 超额收益越大，权重越高
            w = 1.0 + min(0.5, max(0, mean_excess * 20))
        elif state == self.RECOVERY:
            # 恢复期给中等偏上权重，趋势越强越高
            w = 0.8 + min(0.4, max(0, trend * 50))
        elif state == self.FALLING:
            # 下降期大幅降权
            w = max(0.3, 0.6 + max(-0.3, mean_excess * 10))
        else:
            # 震荡期：根据超额收益微调
            w = 0.7 + min(0.3, max(-0.2, mean_excess * 10))

        return max(0.3, min(1.5, w))

    def _compute_confidence(
        self, state: str, mean_excess: float, vol: float
    ) -> float:
        """计算置信度：信号越强、波动越低，置信度越高"""
        signal_strength = abs(mean_excess) / (vol + 1e-8)
        if state in (self.RISING, self.FALLING):
            conf = min(1.0, 0.5 + signal_strength * 0.1)
        elif state == self.RECOVERY:
            conf = min(0.8, 0.3 + signal_strength * 0.1)
        else:
            conf = min(0.5, 0.2 + signal_strength * 0.05)
        return conf

    def get_industry_weights(
        self, end_date: str, trade_dates: List[str]
    ) -> Dict[str, float]:
        """获取行业权重字典（供选股使用）"""
        result = self.detect(end_date, trade_dates)
        return {ind: info["weight"] for ind, info in result.items()}

    def get_industry_states(
        self, end_date: str, trade_dates: List[str]
    ) -> Dict[str, str]:
        """获取行业状态字典"""
        result = self.detect(end_date, trade_dates)
        return {ind: info["state"] for ind, info in result.items()}

    def print_summary(
        self, end_date: str, trade_dates: List[str], top_n: int = 15
    ):
        """打印行业周期摘要"""
        result = self.detect(end_date, trade_dates)
        if not result:
            print("无行业数据")
            return

        # 按权重排序
        sorted_ind = sorted(result.items(), key=lambda x: -x[1]["weight"])

        print(f"行业周期检测 (截至{end_date}, 回看{self.lookback}日)")
        print(f"{'行业':<12} {'状态':<10} {'超额':>7} {'趋势':>7} {'波动':>7} {'权重':>5} {'置信':>5}")
        print("-" * 65)

        for ind, info in sorted_ind[:top_n]:
            state_cn = {
                self.RISING: "↑上升",
                self.FALLING: "↓下降",
                self.OSCILLATING: "~震荡",
                self.RECOVERY: "↗恢复",
            }.get(info["state"], "?")
            print(
                f"{ind:<12} {state_cn:<10} "
                f"{info['excess_ret']:>7.3%} {info['trend']:>7.4%} "
                f"{info['volatility']:>7.3%} {info['weight']:>5.2f} {info['confidence']:>5.2f}"
            )
