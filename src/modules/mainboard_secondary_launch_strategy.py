# -*- coding: utf-8 -*-
"""
沪深主板小资金短线盘前选股策略（去除集合竞价过滤）

策略核心：强势回调缩量二次启动
- 仅使用截至 t-1 的日线数据进行盘前筛选
- 不依赖集合竞价实时开盘价（按用户要求移除）
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd


@dataclass
class StrategyParams:
    """策略参数"""
    min_list_days: int = 60
    limit_up_threshold: float = 9.7
    limit_down_threshold: float = -9.7

    limit_up_count_10_min: int = 1
    limit_up_count_10_max: int = 3

    last_limit_up_days_min: int = 1
    last_limit_up_days_max: int = 8

    drawdown_min: float = 0.01
    drawdown_max: float = 0.12

    vol_shrink_ratio: float = 0.95
    close_ma5_dev_max: float = 0.035
    close_ma10_min_ratio: float = 0.99

    min_amt_ma20: float = 1e5
    max_amt_ma20: float = 5e6
    min_price: float = 3.0

    # 可用 amount 近似替代涨停日换手区间过滤
    limit_up_amt_ratio_min: float = 0.6
    limit_up_amt_ratio_max: float = 3.5

    rs_lookback: int = 20
    max_candidates: int = 20
    picks_per_day: int = 2
    min_score: float = 55.0
    cooldown_days: int = 2
    weak_market_ret5_threshold: float = -0.02
    weak_market_min_score_boost: float = 6.0
    weak_market_max_picks: int = 1
    second_pick_min_score: float = 72.0
    second_pick_score_gap: float = 4.0


class MainboardSecondaryLaunchStrategy:
    """强势回调缩量二次启动策略（日线版）"""

    MAINBOARD_PREFIX = ("600", "601", "603", "605", "000", "001", "002")

    def __init__(self, params: StrategyParams | None = None):
        self.params = params or StrategyParams()

    @staticmethod
    def _is_mainboard(code: str) -> bool:
        return str(code).startswith(MainboardSecondaryLaunchStrategy.MAINBOARD_PREFIX)

    @staticmethod
    def _is_risk_name(name: str) -> bool:
        if not isinstance(name, str):
            return False
        n = name.upper()
        return ("ST" in n) or ("*ST" in n) or ("退" in n)

    def prepare_features(self, daily_df: pd.DataFrame, basic_df: pd.DataFrame) -> pd.DataFrame:
        """构建策略所需特征"""
        p = self.params
        df = daily_df.copy()
        df["trade_date"] = pd.to_datetime(df["trade_date"].astype(str), format="%Y%m%d", errors="coerce")
        df = df.dropna(subset=["trade_date", "ts_code", "close", "open", "high", "low", "vol", "amount"]).copy()
        df = df.sort_values(["ts_code", "trade_date"]).reset_index(drop=True)

        basic = basic_df[["ts_code", "name", "list_date"]].copy()
        basic["list_date"] = pd.to_datetime(basic["list_date"].astype(str), format="%Y%m%d", errors="coerce")
        df = df.merge(basic, on="ts_code", how="left")

        g = df.groupby("ts_code", group_keys=False)

        # 基础特征
        df["ret_1d"] = g["close"].pct_change()
        df["ma5"] = g["close"].transform(lambda s: s.rolling(5).mean())
        df["ma10"] = g["close"].transform(lambda s: s.rolling(10).mean())
        df["vol_ma5"] = g["vol"].transform(lambda s: s.rolling(5).mean())
        df["vol_ma20"] = g["vol"].transform(lambda s: s.rolling(20).mean())
        df["amt_ma20"] = g["amount"].transform(lambda s: s.rolling(20).mean())
        df["rs20"] = g["close"].transform(lambda s: s / s.shift(p.rs_lookback) - 1.0)
        df["ret5"] = g["close"].transform(lambda s: s / s.shift(5) - 1.0)

        # 涨跌停近似识别（主板）
        df["is_limit_up"] = (df["pct_chg"] >= p.limit_up_threshold) & (df["close"] >= df["high"] * 0.999)
        df["is_limit_down"] = (df["pct_chg"] <= p.limit_down_threshold) & (df["close"] <= df["low"] * 1.001)

        df["limit_up_count_10"] = g["is_limit_up"].transform(lambda s: s.rolling(10).sum())
        df["limit_down_count_20"] = g["is_limit_down"].transform(lambda s: s.rolling(20).sum())

        # 最近涨停日期与天数
        def _last_limit_up_days(sub: pd.DataFrame) -> pd.Series:
            days = np.full(len(sub), np.nan)
            last_idx = None
            dates = sub["trade_date"].values
            is_up = sub["is_limit_up"].values
            for i in range(len(sub)):
                if last_idx is not None:
                    days[i] = (dates[i] - dates[last_idx]).astype("timedelta64[D]").astype(int)
                if is_up[i]:
                    last_idx = i
            return pd.Series(days, index=sub.index)

        df["days_since_last_limit_up"] = g.apply(_last_limit_up_days).reset_index(level=0, drop=True)

        # 最近涨停索引对应的量能比例与次日涨跌
        df["limit_up_amt_ratio"] = np.nan
        df["next_ret_after_limit_up"] = np.nan

        for code, sub in df.groupby("ts_code"):
            idx = sub.index.to_list()
            is_up = sub["is_limit_up"].values
            amt = sub["amount"].values
            amt20 = sub["amt_ma20"].values
            close = sub["close"].values

            last_up_i = None
            for i in range(len(sub)):
                if last_up_i is not None:
                    base = amt20[last_up_i]
                    df.loc[idx[i], "limit_up_amt_ratio"] = float(amt[last_up_i] / base) if base and base > 0 else np.nan
                    if last_up_i + 1 < len(sub):
                        next_ret = close[last_up_i + 1] / close[last_up_i] - 1.0
                        df.loc[idx[i], "next_ret_after_limit_up"] = float(next_ret)
                if is_up[i]:
                    last_up_i = i

        # 涨停后峰值回撤（从最近涨停到t-1期间最高收盘）
        df["drawdown_from_peak"] = np.nan
        for code, sub in df.groupby("ts_code"):
            idx = sub.index.to_list()
            close = sub["close"].values
            is_up = sub["is_limit_up"].values
            last_up_i = None
            for i in range(len(sub)):
                if is_up[i]:
                    last_up_i = i
                if last_up_i is not None and i > last_up_i:
                    peak = float(np.max(close[last_up_i:i+1]))
                    if peak > 0:
                        df.loc[idx[i], "drawdown_from_peak"] = 1.0 - float(close[i] / peak)

        # 上市天数
        df["list_days"] = (df["trade_date"] - df["list_date"]).dt.days

        # 仅保留主板
        df["is_mainboard"] = df["ts_code"].map(self._is_mainboard)

        # 风险简称
        df["is_risk_name"] = df["name"].map(self._is_risk_name)

        return df

    def generate_daily_candidates(self, feature_df: pd.DataFrame, trade_date: pd.Timestamp) -> pd.DataFrame:
        """生成某一交易日的候选股票（盘前：仅用t-1）"""
        p = self.params
        d = pd.Timestamp(trade_date)
        prev = feature_df[feature_df["trade_date"] < d].copy()
        if prev.empty:
            return pd.DataFrame()

        prev = prev.sort_values(["ts_code", "trade_date"]).groupby("ts_code").tail(1).copy()
        cands = self._select_candidates(prev)
        if cands.empty:
            return cands

        cands = cands.head(p.max_candidates)
        return cands

    def _base_filter(self, df: pd.DataFrame) -> pd.DataFrame:
        """先做底线过滤，避免过早把形态变量写死。"""
        p = self.params
        cond = (
            (df["is_mainboard"]) &
            (~df["is_risk_name"]) &
            (df["list_days"] >= p.min_list_days) &
            (df["vol"] > 0) &
            (df["close"] >= p.min_price) &
            (df["amt_ma20"] >= p.min_amt_ma20) &
            (df["amt_ma20"] <= p.max_amt_ma20) &
            (df["limit_down_count_20"] <= 1) &
            (df["limit_up_count_10"] >= 1) &
            (df["days_since_last_limit_up"] >= p.last_limit_up_days_min) &
            (df["days_since_last_limit_up"] <= p.last_limit_up_days_max) &
            (df["drawdown_from_peak"] >= p.drawdown_min) &
            (df["drawdown_from_peak"] <= p.drawdown_max) &
            (df["close"] >= df["ma10"] * p.close_ma10_min_ratio) &
            (df["ma5"] >= df["ma10"] * 0.998) &
            (~df["is_limit_up"])
        )
        return df.loc[cond].copy()

    @staticmethod
    def _bounded_score(series: pd.Series, target_min: float, target_max: float) -> pd.Series:
        """区间内给满分，区间外按偏离度线性衰减。"""
        values = series.astype(float)
        score = pd.Series(1.0, index=values.index, dtype=float)
        score = score.mask(values < target_min, 1.0 - (target_min - values).clip(lower=0.0) / max(target_min, 1e-6))
        score = score.mask(values > target_max, 1.0 - (values - target_max).clip(lower=0.0) / max(target_max, 1e-6))
        return score.clip(lower=0.0, upper=1.0)

    def _score_candidates(self, df: pd.DataFrame) -> pd.DataFrame:
        """把原来的硬条件改为形态评分，提升信号覆盖率。"""
        p = self.params
        scored = df.copy()

        rs_raw = scored["rs20"].fillna(0.0)
        rs_rank = rs_raw.rank(pct=True, method="average").fillna(0.0)

        limit_up_count_score = self._bounded_score(
            scored["limit_up_count_10"].fillna(0.0),
            float(p.limit_up_count_10_min),
            float(p.limit_up_count_10_max),
        )
        last_limit_up_score = self._bounded_score(
            scored["days_since_last_limit_up"].fillna(99.0),
            float(p.last_limit_up_days_min),
            float(p.last_limit_up_days_max),
        )
        drawdown_score = self._bounded_score(
            scored["drawdown_from_peak"].fillna(1.0),
            float(p.drawdown_min),
            float(p.drawdown_max),
        )

        volume_ratio = (scored["vol"] / scored["vol_ma5"].replace(0, np.nan)).replace([np.inf, -np.inf], np.nan)
        shrink_target = float(p.vol_shrink_ratio)
        volume_shrink_score = (1.0 - ((volume_ratio.fillna(1.5) - shrink_target).clip(lower=0.0) / max(1.0 - shrink_target, 1e-6))).clip(0.0, 1.0)

        ma5_dev = ((scored["close"] / scored["ma5"]) - 1.0).abs().replace([np.inf, -np.inf], np.nan)
        ma5_dev_score = (1.0 - (ma5_dev.fillna(1.0) / max(float(p.close_ma5_dev_max), 1e-6))).clip(0.0, 1.0)

        trend_score = (
            0.6 * (scored["ma5"] > scored["ma10"]).fillna(False).astype(float)
            + 0.4 * (scored["close"] >= scored["ma10"]).fillna(False).astype(float)
        )
        volume_trend_score = (scored["vol_ma5"] / scored["vol_ma20"].replace(0, np.nan)).replace([np.inf, -np.inf], np.nan)
        volume_trend_score = ((volume_trend_score.fillna(0.0) - 0.8) / 0.4).clip(0.0, 1.0)

        limit_up_amt_score = self._bounded_score(
            scored["limit_up_amt_ratio"].fillna(0.0),
            float(p.limit_up_amt_ratio_min),
            float(p.limit_up_amt_ratio_max),
        )
        next_ret_score = (scored["next_ret_after_limit_up"].fillna(0.0).clip(lower=-0.06, upper=0.10) + 0.06) / 0.16
        next_ret_score = next_ret_score.clip(0.0, 1.0)

        scored["signal_score"] = (
            rs_rank * 24.0
            + limit_up_count_score * 10.0
            + last_limit_up_score * 16.0
            + drawdown_score * 18.0
            + volume_shrink_score * 8.0
            + ma5_dev_score * 12.0
            + trend_score * 6.0
            + volume_trend_score * 3.0
            + limit_up_amt_score * 2.0
            + next_ret_score * 5.0
        )
        scored["volume_ratio"] = volume_ratio.fillna(0.0)
        scored["score_breakdown"] = (
            "RS="
            + (rs_rank * 24.0).round(1).astype(str)
            + "|涨停次数="
            + (limit_up_count_score * 10.0).round(1).astype(str)
            + "|涨停间隔="
            + (last_limit_up_score * 16.0).round(1).astype(str)
            + "|回撤="
            + (drawdown_score * 18.0).round(1).astype(str)
            + "|缩量="
            + (volume_shrink_score * 8.0).round(1).astype(str)
        )
        return scored

    def _get_market_gate(self, candidate_df: pd.DataFrame) -> Tuple[float, int]:
        """根据指数近5日涨幅做轻量级市场闸门。"""
        p = self.params
        if candidate_df.empty:
            return float(p.min_score), int(p.picks_per_day)

        index_row = candidate_df[candidate_df["ts_code"] == "000001.SH"]
        if index_row.empty:
            return float(p.min_score), int(p.picks_per_day)

        ret5 = float(index_row.iloc[-1].get("ret5", 0.0) or 0.0)
        effective_min_score = float(p.min_score)
        effective_picks = int(p.picks_per_day)
        if ret5 <= float(p.weak_market_ret5_threshold):
            effective_min_score += float(p.weak_market_min_score_boost)
            effective_picks = min(effective_picks, int(p.weak_market_max_picks))
        return effective_min_score, effective_picks

    def _select_candidates(self, df: pd.DataFrame) -> pd.DataFrame:
        """底线过滤后按形态综合评分挑选候选。"""
        filtered = self._base_filter(df)
        if filtered.empty:
            return filtered

        scored = self._score_candidates(filtered)
        effective_min_score, _ = self._get_market_gate(df)
        scored = scored[scored["signal_score"] >= effective_min_score].copy()
        if scored.empty:
            return scored

        scored = scored.sort_values(["signal_score", "rs20"], ascending=[False, False]).reset_index(drop=True)
        return scored

    def _apply_cooldown(self, eval_df: pd.DataFrame) -> pd.DataFrame:
        """避免同一只股票连续多日重复入选。"""
        cooldown_days = int(self.params.cooldown_days)
        if eval_df.empty or cooldown_days <= 0:
            return eval_df

        selected_rows = []
        recent_selected_dates: Dict[str, pd.Timestamp] = {}

        for signal_date, group in eval_df.groupby("signal_date", sort=True):
            signal_ts = pd.Timestamp(signal_date)
            eligible_rows = []
            for _, row in group.iterrows():
                ts_code = str(row["ts_code"])
                last_selected = recent_selected_dates.get(ts_code)
                if last_selected is None:
                    eligible_rows.append(row)
                    continue
                gap_days = int((signal_ts - last_selected).days)
                if gap_days > cooldown_days:
                    eligible_rows.append(row)

            if not eligible_rows:
                continue

            eligible_df = pd.DataFrame(eligible_rows).sort_values(
                ["signal_score", "rs20"], ascending=[False, False]
            )
            _, effective_picks = self._get_market_gate(group)
            day_selected = eligible_df.head(effective_picks).copy()
            for _, row in day_selected.iterrows():
                recent_selected_dates[str(row["ts_code"])] = signal_ts
            selected_rows.append(day_selected)

        if not selected_rows:
            return eval_df.iloc[0:0].copy()
        return pd.concat(selected_rows, ignore_index=True)

    def _refine_daily_picks(self, eval_df: pd.DataFrame) -> pd.DataFrame:
        """进一步压缩边缘票，尤其是第二名质量不足的情况。"""
        if eval_df.empty:
            return eval_df

        refined_rows = []
        for _, group in eval_df.groupby("signal_date", sort=True):
            day_df = group.sort_values(["signal_score", "rs20"], ascending=[False, False]).copy()
            if len(day_df) <= 1:
                refined_rows.append(day_df)
                continue

            first_row = day_df.iloc[0]
            keep_rows = [first_row]
            for idx in range(1, len(day_df)):
                row = day_df.iloc[idx]
                score_gap = float(first_row["signal_score"]) - float(row["signal_score"])
                if float(row["signal_score"]) < float(self.params.second_pick_min_score):
                    continue
                if score_gap > float(self.params.second_pick_score_gap):
                    continue
                keep_rows.append(row)

            refined_rows.append(pd.DataFrame(keep_rows))

        if not refined_rows:
            return eval_df.iloc[0:0].copy()
        return pd.concat(refined_rows, ignore_index=True)

    @staticmethod
    def build_signal_frame(feature_df: pd.DataFrame) -> pd.DataFrame:
        """把 t-1 特征映射到下一交易日信号日期。"""
        dates = sorted(pd.Series(feature_df["trade_date"].dropna().unique()).tolist())
        if len(dates) < 2:
            return pd.DataFrame()
        next_date_map = {dates[i]: pd.Timestamp(dates[i + 1]) for i in range(len(dates) - 1)}
        eval_df = feature_df.copy()
        eval_df["signal_date"] = eval_df["trade_date"].map(next_date_map)
        return eval_df.dropna(subset=["signal_date"]).copy()

    def generate_signals_from_frame(self, signal_frame: pd.DataFrame) -> pd.DataFrame:
        """基于已构造好的信号帧生成每日信号。"""
        if signal_frame.empty:
            return pd.DataFrame(columns=["signal_date", "ts_code", "name", "rank", "rs20", "signal_score"])

        eval_df = self._select_candidates(signal_frame)
        if eval_df.empty:
            return pd.DataFrame(columns=["signal_date", "ts_code", "name", "rank", "rs20", "signal_score"])

        eval_df = eval_df.sort_values(["signal_date", "signal_score", "rs20"], ascending=[True, False, False])
        eval_df = eval_df.groupby("signal_date", group_keys=False).head(self.params.max_candidates)
        eval_df = self._apply_cooldown(eval_df)
        if eval_df.empty:
            return pd.DataFrame(columns=["signal_date", "ts_code", "name", "rank", "rs20", "signal_score"])
        eval_df = self._refine_daily_picks(eval_df)
        if eval_df.empty:
            return pd.DataFrame(columns=["signal_date", "ts_code", "name", "rank", "rs20", "signal_score"])
        eval_df["rank"] = eval_df.groupby("signal_date").cumcount() + 1
        return eval_df[["signal_date", "ts_code", "name", "rank", "rs20", "signal_score"]].reset_index(drop=True)

    def generate_signals(self, feature_df: pd.DataFrame) -> pd.DataFrame:
        """对全样本生成每日信号"""
        signal_frame = self.build_signal_frame(feature_df)
        return self.generate_signals_from_frame(signal_frame)
