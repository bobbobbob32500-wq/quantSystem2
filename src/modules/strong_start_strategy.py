# -*- coding: utf-8 -*-
"""Strong-start strategy based on chip concentration plus breakout structure."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from src.core.database import DatabaseManager
from src.core.logger import get_logger
from src.modules.breakout_strategy import BreakoutStrategy

logger = get_logger("strong_start_strategy")


@dataclass
class StrongStartParams:
    min_list_days: int = 120
    min_amt_ma20: float = 8e4
    min_price: float = 5.0
    max_price: float = 80.0

    rs_lookback: int = 20
    rs_quantile_min: float = 0.75
    rs_quantile_max: float = 1.0

    atr_period: int = 14
    atr_quantile_window: int = 60
    atr_squeeze_quantile_max: float = 0.45

    platform_windows: Tuple[int, ...] = field(default_factory=lambda: (15, 20, 25, 30))
    platform_pivot_days: int = 20
    platform_max_range: float = 0.15
    platform_chip_tolerance: float = 0.02

    vol_contraction_ratio: float = 0.70
    low_vol_days_window: int = 10
    low_vol_days_required: int = 7

    breakout_buffer: float = 0.002
    breakout_volume_ratio: float = 1.4
    breakout_close_pos_min: float = 0.55
    breakout_stop_buffer: float = 0.01

    pullback_window_days: int = 5
    pullback_max_break_pct: float = 0.01
    pullback_volume_shrink_ratio: float = 0.90
    pullback_stop_buffer: float = 0.02

    chip_concentration_max: float = 0.12
    chip_stability_days: int = 10
    chip_stability_std_max: float = 0.015
    chip_low_position_max: float = 0.55
    winner_rate_min: float = 0.15
    winner_rate_max: float = 0.90
    chip_dist_min_rows: int = 10
    chip_peak_significant_ratio: float = 0.35
    chip_peak_count_max: int = 2
    chip_peak_secondary_ratio_max: float = 0.60
    chip_peak_dominance_min: float = 0.15
    chip_peak_band_pct: float = 0.03
    chip_single_peak_score_min: float = 0.55

    min_signal_score: float = 60.0
    top_k: int = 15
    save_factor_values: bool = True
    factor_name_prefix: str = "strong_start"

    index_code: str = "000001.SH"
    market_index_above_ma20: bool = True
    market_ret3_caution: float = -0.01
    market_ret5_caution: float = -0.02
    market_ret3_stop: float = -0.025
    market_ret5_stop: float = -0.04
    market_breadth_caution: float = 0.40
    market_breadth_stop: float = 0.30
    caution_score_boost: float = 8.0
    caution_topk_ratio: float = 0.4
    allow_breakout_setup: bool = True
    allow_pullback_setup: bool = True
    chip_factor_profile_key: str = ""
    chip_factor_strict_mode: bool = False

    mainboard_sh_prefixes: Tuple[str, ...] = field(
        default_factory=lambda: ("600", "601", "603", "605")
    )
    mainboard_sz_prefixes: Tuple[str, ...] = field(
        default_factory=lambda: ("000", "001", "002", "003")
    )

    @classmethod
    def tradeable_v1(cls) -> "StrongStartParams":
        """
        A relaxed but still structured preset for producing enough samples
        to run daily-level validation before finer entry optimization.
        """
        return cls(
            min_amt_ma20=4e4,
            rs_quantile_min=0.55,
            atr_squeeze_quantile_max=0.85,
            platform_max_range=0.28,
            vol_contraction_ratio=1.0,
            low_vol_days_required=3,
            breakout_volume_ratio=1.05,
            breakout_close_pos_min=0.40,
            chip_concentration_max=0.22,
            chip_stability_std_max=0.04,
            chip_low_position_max=0.85,
            winner_rate_min=0.03,
            winner_rate_max=0.97,
            chip_peak_significant_ratio=0.75,
            chip_peak_count_max=8,
            chip_peak_secondary_ratio_max=1.0,
            chip_peak_dominance_min=0.0,
            chip_single_peak_score_min=0.08,
            min_signal_score=40.0,
            top_k=20,
            chip_factor_profile_key="tradeable_v1",
        )

    @classmethod
    def tradeable_v2(cls) -> "StrongStartParams":
        """
        Conservative preset focused on reducing false starts:
        tighter structure/chip filters, pullback-first entries, and lower daily turnover.
        """
        return cls(
            min_amt_ma20=5e4,
            rs_quantile_min=0.60,
            atr_squeeze_quantile_max=0.70,
            platform_max_range=0.10,
            vol_contraction_ratio=0.80,
            low_vol_days_required=5,
            breakout_volume_ratio=1.20,
            breakout_close_pos_min=0.50,
            pullback_volume_shrink_ratio=0.80,
            chip_concentration_max=0.12,
            chip_stability_std_max=0.025,
            chip_low_position_max=0.75,
            winner_rate_min=0.05,
            winner_rate_max=0.95,
            chip_peak_significant_ratio=0.60,
            chip_peak_count_max=3,
            chip_peak_secondary_ratio_max=0.75,
            chip_peak_dominance_min=0.05,
            chip_single_peak_score_min=0.45,
            min_signal_score=55.0,
            top_k=1,
            allow_breakout_setup=False,
            allow_pullback_setup=True,
            chip_factor_profile_key="tradeable_v2",
        )

    @classmethod
    def tradeable_v3_research(cls) -> "StrongStartParams":
        """
        Research-derived preset from event-level sample mining.
        Compared with v2, this preset relaxes hard filters, restores dual-channel
        (breakout + pullback), and keeps selection broad enough for validation.
        """
        return cls(
            min_amt_ma20=5e4,
            rs_quantile_min=0.69,
            atr_squeeze_quantile_max=0.85,
            platform_max_range=0.24,
            vol_contraction_ratio=1.10,
            low_vol_days_required=2,
            breakout_volume_ratio=1.26,
            breakout_close_pos_min=0.65,
            pullback_volume_shrink_ratio=0.95,
            chip_concentration_max=0.24,
            chip_stability_std_max=0.05,
            chip_low_position_max=0.88,
            winner_rate_min=0.77,
            winner_rate_max=0.985,
            chip_peak_significant_ratio=0.75,
            chip_peak_count_max=8,
            chip_peak_secondary_ratio_max=1.0,
            chip_peak_dominance_min=0.0,
            chip_single_peak_score_min=0.10,
            min_signal_score=42.0,
            top_k=12,
            allow_breakout_setup=True,
            allow_pullback_setup=True,
            chip_factor_profile_key="tradeable_v3_research",
        )

    @classmethod
    def tradeable_v4_parameter_reverse_loose(cls) -> "StrongStartParams":
        """
        将「参数反推报告」宽松档映射为可交易字段（在 v3 研究预设上增量收紧/对齐）。

        依据：`data/research/strong_start_full/parameter_reverse_engineering_report.md` 第 3 节宽松下界。
        显式映射（研究 f_* → StrongStartParams）：
          - f_strength_rs20_xsec_q 宽松 [0.748430, +∞) → rs_quantile_min = 0.7484
          - f_chip_winner_rate 宽松 [0.860202, +∞) → winner_rate_min = 0.8602
          - f_breakout_vol_ratio20 宽松 [1.620811, +∞) → breakout_volume_ratio = 1.62
          - f_k_close_pos 宽松 [0.798841, +∞) → breakout_close_pos_min = 0.80

        未逐字段对齐的 f_*（如 f_trend_close_ma20_gap、f_ind_rank_pctchg、f_chip_stability_std10）：
        交易端已有 close≥MA20、筹码集中度 std 上限等约束，与研究侧特征定义不完全相同，
        后续若需一致，应在特征层增加列再挂参。

        chip_factor_profile_key 沿用 v3 研究物化键，避免新建 profile 尚未入库导致选股为空。
        """
        base = cls.tradeable_v3_research()
        return replace(
            base,
            rs_quantile_min=0.7484,
            winner_rate_min=0.8602,
            breakout_volume_ratio=1.62,
            breakout_close_pos_min=0.80,
            min_signal_score=45.0,
            top_k=10,
            chip_factor_profile_key="tradeable_v3_research",
        )


@dataclass
class StrongStartCandidate:
    ts_code: str
    name: str
    watch_date: str
    setup_type: str
    close: float
    pivot: float
    trigger_price: float
    stop_loss: float
    signal_score: float
    volume_ratio: float
    platform_range: float
    chip_concentration: float
    chip_low_position: float
    rs20: float
    rs20_xsec_q: float
    single_peak_dense_score: float = 0.0
    breakout_date: str = ""
    winner_rate: float = 0.0
    industry: str = ""
    score_detail: str = ""


class StrongStartStrategy(BreakoutStrategy):
    """V1 implementation of the 'strong stock just starting' daily selector."""

    def __init__(
        self,
        db: DatabaseManager,
        params: Optional[StrongStartParams] = None,
    ):
        self.db = db
        self.params = params or StrongStartParams()

    def run(self, end_date: str = None) -> List[StrongStartCandidate]:
        resolved = self._resolve_end_date(end_date)
        logger.info("=" * 60)
        logger.info("Run strong-start selection [%s]", resolved)

        daily, basic, chip, chip_dist_factor = self._load_data(resolved)
        if daily.empty or basic.empty:
            logger.warning("strong_start: insufficient daily/basic data")
            return []
        if chip.empty:
            logger.warning("strong_start: chip summary table is empty")
            return []
        if chip_dist_factor.empty:
            logger.warning("strong_start: chip distribution factor table is empty")
            return []

        features = self._compute_features(daily, basic, chip, chip_dist_factor)
        if features.empty:
            logger.warning("strong_start: feature frame is empty")
            return []
        if self.params.save_factor_values:
            self._persist_factor_values(features, resolved)

        return self.select_candidates_from_features(features, resolved)

    def _load_data(
        self,
        end_date: str,
    ) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
        p = self.params
        end_dt = datetime.strptime(end_date, "%Y%m%d")
        start_date = (end_dt - timedelta(days=420)).strftime("%Y%m%d")
        # Keep chip windows aligned with the backtest feature window, otherwise
        # earlier dates in the backtest period lose chip factors and become untradeable.
        chip_start = start_date

        sh_likes = " OR ".join(f"ts_code LIKE '{prefix}%.SH'" for prefix in p.mainboard_sh_prefixes)
        sz_likes = " OR ".join(f"ts_code LIKE '{prefix}%.SZ'" for prefix in p.mainboard_sz_prefixes)
        mainboard_cond = f"({sh_likes} OR {sz_likes})"

        sql_daily = f"""
            SELECT ts_code, trade_date, open, high, low, close, vol, amount, pct_chg
            FROM stock_daily
            WHERE trade_date >= ? AND trade_date <= ?
              AND ({mainboard_cond})
            ORDER BY ts_code ASC, trade_date ASC
        """
        sql_index = """
            SELECT ts_code, trade_date, open, high, low, close, vol, amount, pct_chg
            FROM stock_daily
            WHERE trade_date >= ? AND trade_date <= ?
              AND ts_code = ?
            ORDER BY trade_date ASC
        """
        sql_basic = """
            SELECT ts_code, name, industry, list_date
            FROM stock_basic
        """
        sql_chip = f"""
            SELECT ts_code, trade_date, cost_5pct, cost_15pct, cost_50pct,
                   cost_85pct, cost_95pct, weight_avg, winner_rate
            FROM stock_chip_perf
            WHERE trade_date >= ? AND trade_date <= ?
              AND ({mainboard_cond})
            ORDER BY ts_code ASC, trade_date ASC
        """
        sql_chip_dist_factor = f"""
            SELECT ts_code, trade_date,
                   chip_peak_count_sig, chip_primary_peak_weight, chip_secondary_peak_ratio,
                   chip_peak_dominance, chip_main_band_weight, chip_dist_points,
                   single_peak_dense_score, chip_single_peak_dense
            FROM stock_chip_dist_factor
            WHERE trade_date >= ? AND trade_date <= ?
              AND ({mainboard_cond})
            ORDER BY ts_code ASC, trade_date ASC
        """
        sql_chip_dist_factor_profile = f"""
            SELECT ts_code, trade_date,
                   chip_peak_count_sig, chip_primary_peak_weight, chip_secondary_peak_ratio,
                   chip_peak_dominance, chip_main_band_weight, chip_dist_points,
                   single_peak_dense_score, chip_single_peak_dense
            FROM stock_chip_dist_factor_profile
            WHERE profile_key = ?
              AND trade_date >= ? AND trade_date <= ?
              AND ({mainboard_cond})
            ORDER BY ts_code ASC, trade_date ASC
        """
        sql_chip_dist = f"""
            SELECT ts_code, trade_date, price, weight
            FROM stock_chip_dist
            WHERE trade_date >= ? AND trade_date <= ?
              AND ({mainboard_cond})
            ORDER BY ts_code ASC, trade_date ASC, price ASC
        """

        daily_rows = self.db.query(sql_daily, (start_date, end_date))
        index_rows = self.db.query(sql_index, (start_date, end_date, p.index_code))
        basic_rows = self.db.query(sql_basic)
        chip_rows = self.db.query(sql_chip, (chip_start, end_date))
        chip_factor_source = "none"
        profile_key = self._chip_factor_profile_key()
        try:
            chip_dist_factor_rows = self.db.query(
                sql_chip_dist_factor_profile, (profile_key, chip_start, end_date)
            )
            if chip_dist_factor_rows:
                chip_factor_source = f"profile:{profile_key}"
        except Exception:
            chip_dist_factor_rows = []
        if not chip_dist_factor_rows and not p.chip_factor_strict_mode:
            try:
                chip_dist_factor_rows = self.db.query(sql_chip_dist_factor, (chip_start, end_date))
                if chip_dist_factor_rows:
                    chip_factor_source = "legacy_table"
            except Exception:
                chip_dist_factor_rows = []
        if not chip_dist_factor_rows and not p.chip_factor_strict_mode:
            try:
                chip_dist_factor_rows = self.db.query(sql_chip_dist, (chip_start, end_date))
                if chip_dist_factor_rows:
                    chip_factor_source = "raw_dist"
            except Exception:
                chip_dist_factor_rows = []
        if not chip_dist_factor_rows and p.chip_factor_strict_mode:
            try:
                chip_dist_factor_rows = self.db.query(sql_chip_dist, (chip_start, end_date))
                if chip_dist_factor_rows:
                    chip_factor_source = "raw_dist_strict"
            except Exception:
                chip_dist_factor_rows = []

        daily = pd.DataFrame(daily_rows) if daily_rows else pd.DataFrame()
        if index_rows:
            daily = pd.concat([daily, pd.DataFrame(index_rows)], ignore_index=True)
            daily = daily.drop_duplicates(subset=["ts_code", "trade_date"], keep="last")

        basic = pd.DataFrame(basic_rows) if basic_rows else pd.DataFrame()
        if not basic.empty and p.index_code not in basic["ts_code"].astype(str).values:
            basic = pd.concat(
                [
                    basic,
                    pd.DataFrame(
                        [
                            {
                                "ts_code": p.index_code,
                                "name": "BenchmarkIndex",
                                "industry": "index",
                                "list_date": "19901219",
                            }
                        ]
                    ),
                ],
                ignore_index=True,
            )
        chip = pd.DataFrame(chip_rows) if chip_rows else pd.DataFrame()
        chip_dist_factor = pd.DataFrame(chip_dist_factor_rows) if chip_dist_factor_rows else pd.DataFrame()
        logger.info(
            "strong_start load complete: daily=%d basic=%d chip=%d chip_dist_factor=%d source=%s",
            len(daily),
            len(basic),
            len(chip),
            len(chip_dist_factor),
            chip_factor_source,
        )
        return daily, basic, chip, chip_dist_factor

    def _chip_factor_profile_key(self) -> str:
        p = self.params
        if str(p.chip_factor_profile_key or "").strip():
            return str(p.chip_factor_profile_key).strip()
        return (
            "sig{sig:.3f}_sec{sec:.3f}_dom{dom:.3f}_band{band:.3f}_score{score:.3f}_rows{rows}"
        ).format(
            sig=float(p.chip_peak_significant_ratio),
            sec=float(p.chip_peak_secondary_ratio_max),
            dom=float(p.chip_peak_dominance_min),
            band=float(p.chip_peak_band_pct),
            score=float(p.chip_single_peak_score_min),
            rows=int(p.chip_dist_min_rows),
        ).replace(".", "p")

    def _compute_features(
        self,
        daily: pd.DataFrame,
        basic: pd.DataFrame,
        chip: pd.DataFrame,
        chip_dist_factor: pd.DataFrame,
    ) -> pd.DataFrame:
        p = self.params

        df = daily.copy()
        for col in ["open", "high", "low", "close", "vol", "amount", "pct_chg"]:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        df["trade_date"] = pd.to_datetime(df["trade_date"].astype(str), format="%Y%m%d", errors="coerce")
        df = df.dropna(subset=["trade_date", "ts_code", "close", "high", "low"]).copy()
        df = df.sort_values(["ts_code", "trade_date"]).reset_index(drop=True)

        basic_df = basic[["ts_code", "name", "industry", "list_date"]].copy()
        basic_df["list_date"] = pd.to_datetime(
            basic_df["list_date"].astype(str).str[:8], format="%Y%m%d", errors="coerce"
        )
        df = df.merge(basic_df, on="ts_code", how="left")

        grouped = df.groupby("ts_code", group_keys=False)
        for win, col in [(5, "ma5"), (10, "ma10"), (20, "ma20"), (60, "ma60")]:
            df[col] = grouped["close"].transform(lambda s, w=win: s.rolling(w, min_periods=w).mean())

        df["ma20_slope"] = grouped["ma20"].transform(lambda s: s / s.shift(5) - 1.0)
        df["ret_1d"] = grouped["close"].pct_change()
        df["rs20"] = grouped["close"].transform(lambda s: s / s.shift(p.rs_lookback) - 1.0)
        df["ret3"] = grouped["close"].transform(lambda s: s / s.shift(3) - 1.0)
        df["ret5"] = grouped["close"].transform(lambda s: s / s.shift(5) - 1.0)

        df["vol_ma20"] = grouped["vol"].transform(lambda s: s.rolling(20, min_periods=20).mean())
        df["vol_ma50"] = grouped["vol"].transform(lambda s: s.rolling(50, min_periods=30).mean())
        df["vol_ma60"] = grouped["vol"].transform(lambda s: s.rolling(60, min_periods=40).mean())
        df["amt_ma20"] = grouped["amount"].transform(lambda s: s.rolling(20, min_periods=20).mean())
        df["vol20_vol60"] = df["vol_ma20"] / df["vol_ma60"].replace(0, np.nan)

        df["below_vol60_flag"] = (df["vol"].fillna(0) < df["vol_ma60"].fillna(np.inf)).astype(float)
        df["below_vol60_days"] = grouped["below_vol60_flag"].transform(
            lambda s: s.rolling(p.low_vol_days_window, min_periods=p.low_vol_days_window).sum()
        )

        df["atr14"] = (
            df.groupby("ts_code")[["high", "low", "close"]]
            .apply(lambda sub: self._calc_atr(sub["high"], sub["low"], sub["close"], p.atr_period))
            .reset_index(level=0, drop=True)
        )
        df["atr_ratio"] = df["atr14"] / df["close"].replace(0, np.nan)
        df["atr_ratio_q60"] = grouped["atr_ratio"].transform(
            lambda s: s.rolling(p.atr_quantile_window, min_periods=20).rank(pct=True)
        )

        platform_ranges: List[str] = []
        for window in p.platform_windows:
            high_col = f"platform_high_{window}"
            low_col = f"platform_low_{window}"
            range_col = f"platform_range_{window}"
            df[high_col] = grouped["high"].transform(lambda s, w=window: s.shift(1).rolling(w, min_periods=w).max())
            df[low_col] = grouped["low"].transform(lambda s, w=window: s.shift(1).rolling(w, min_periods=w).min())
            df[range_col] = (df[high_col] - df[low_col]) / df[high_col].replace(0, np.nan)
            platform_ranges.append(range_col)
        df["platform_range_best"] = df[platform_ranges].min(axis=1)

        df["pivot"] = grouped["high"].transform(
            lambda s: s.shift(1).rolling(p.platform_pivot_days, min_periods=p.platform_pivot_days).max()
        )
        df["platform_low_ref"] = grouped["low"].transform(
            lambda s: s.shift(1).rolling(p.platform_pivot_days, min_periods=p.platform_pivot_days).min()
        )

        df["range_low_120"] = grouped["low"].transform(lambda s: s.rolling(120, min_periods=60).min())
        df["range_high_120"] = grouped["high"].transform(lambda s: s.rolling(120, min_periods=60).max())
        df["close_pos"] = np.where(
            (df["high"] - df["low"]).abs() < 1e-9,
            0.5,
            (df["close"] - df["low"]) / (df["high"] - df["low"]),
        )
        df["list_days"] = (df["trade_date"] - df["list_date"]).dt.days

        df["rs20_xsec_q"] = np.nan
        rank_mask = (
            df["rs20"].notna()
            & (df["ts_code"].astype(str) != str(p.index_code))
            & df["list_days"].fillna(0).ge(p.min_list_days)
        )
        for _, idx in df[rank_mask].groupby("trade_date").groups.items():
            rs_vals = df.loc[idx, "rs20"]
            df.loc[idx, "rs20_xsec_q"] = rs_vals.rank(pct=True, method="average")

        chip_df = chip.copy()
        if chip_df.empty:
            return pd.DataFrame()
        for col in [
            "cost_5pct",
            "cost_15pct",
            "cost_50pct",
            "cost_85pct",
            "cost_95pct",
            "weight_avg",
            "winner_rate",
        ]:
            chip_df[col] = pd.to_numeric(chip_df[col], errors="coerce")
        chip_df["trade_date"] = pd.to_datetime(
            chip_df["trade_date"].astype(str), format="%Y%m%d", errors="coerce"
        )
        chip_df = chip_df.dropna(subset=["trade_date", "ts_code"]).copy()
        chip_df = chip_df.sort_values(["ts_code", "trade_date"]).reset_index(drop=True)
        chip_df["chip_concentration"] = (
            (chip_df["cost_95pct"] - chip_df["cost_5pct"])
            / (chip_df["cost_95pct"] + chip_df["cost_5pct"]).replace(0, np.nan)
        )
        chip_df["chip_center"] = (chip_df["cost_95pct"] + chip_df["cost_5pct"]) / 2.0
        chip_grouped = chip_df.groupby("ts_code", group_keys=False)
        min_chip_periods = max(3, p.chip_stability_days // 2)
        chip_df["chip_concentration_ma"] = chip_grouped["chip_concentration"].transform(
            lambda s: s.rolling(p.chip_stability_days, min_periods=min_chip_periods).mean()
        )
        chip_df["chip_concentration_std"] = chip_grouped["chip_concentration"].transform(
            lambda s: s.rolling(p.chip_stability_days, min_periods=min_chip_periods).std()
        )
        chip_df["chip_available_days"] = chip_grouped["chip_concentration"].transform(
            lambda s: s.rolling(p.chip_stability_days, min_periods=1).count()
        )
        if chip_dist_factor is None or chip_dist_factor.empty:
            return pd.DataFrame()
        if {"price", "weight"}.issubset(set(chip_dist_factor.columns)):
            chip_dist_factors = self._build_chip_dist_factors(chip_dist_factor)
        else:
            chip_dist_factors = chip_dist_factor.copy()
            chip_dist_factors["trade_date"] = pd.to_datetime(
                chip_dist_factors["trade_date"].astype(str), format="%Y%m%d", errors="coerce"
            )
            if "chip_single_peak_dense" in chip_dist_factors.columns:
                chip_dist_factors["chip_single_peak_dense"] = (
                    pd.to_numeric(chip_dist_factors["chip_single_peak_dense"], errors="coerce")
                    .fillna(0.0)
                    .astype(float)
                    .ge(0.5)
                )
        if chip_dist_factors.empty:
            return pd.DataFrame()
        chip_df = chip_df.merge(chip_dist_factors, on=["ts_code", "trade_date"], how="left")

        df = df.merge(
            chip_df[
                [
                    "ts_code",
                    "trade_date",
                    "cost_5pct",
                    "cost_15pct",
                    "cost_50pct",
                    "cost_85pct",
                    "cost_95pct",
                    "weight_avg",
                    "winner_rate",
                    "chip_concentration",
                    "chip_center",
                    "chip_concentration_ma",
                    "chip_concentration_std",
                    "chip_available_days",
                    "chip_peak_count_sig",
                    "chip_primary_peak_weight",
                    "chip_secondary_peak_ratio",
                    "chip_peak_dominance",
                    "chip_main_band_weight",
                    "chip_dist_points",
                    "single_peak_dense_score",
                    "chip_single_peak_dense",
                ]
            ],
            on=["ts_code", "trade_date"],
            how="left",
        )

        band_span = (df["range_high_120"] - df["range_low_120"]).replace(0, np.nan)
        df["chip_low_position"] = (df["chip_center"] - df["range_low_120"]) / band_span
        df["chip_matches_platform"] = (
            (df["cost_5pct"] >= df["platform_low_ref"] * (1.0 - p.platform_chip_tolerance))
            & (df["cost_95pct"] <= df["pivot"] * (1.0 + p.platform_chip_tolerance))
        )

        breakout_trigger = df["pivot"] * (1.0 + p.breakout_buffer)
        df["breakout_volume_ratio"] = df["vol"] / df["vol_ma50"].replace(0, np.nan)
        df["breakout_day"] = (
            df["pivot"].notna()
            & (df["high"] >= breakout_trigger)
            & (df["close"] >= df["pivot"])
            & (df["breakout_volume_ratio"] >= p.breakout_volume_ratio)
            & (df["close_pos"] >= p.breakout_close_pos_min)
        )

        logger.info("strong_start features ready: %d rows", len(df))
        return df

    def select_candidates_from_features(
        self,
        features: pd.DataFrame,
        resolved: str,
    ) -> List[StrongStartCandidate]:
        snapshot = self._build_snapshot(features, resolved)
        if snapshot.empty:
            return []

        snapshot = self._base_filter(snapshot)
        if snapshot.empty:
            logger.info("strong_start: no rows passed base filter [%s]", resolved)
            return []

        min_score, top_k = self._market_gate(features, resolved)
        target = pd.Timestamp(resolved)
        histories = {
            ts_code: sub.loc[sub["trade_date"] <= target].sort_values("trade_date").reset_index(drop=True)
            for ts_code, sub in features.groupby("ts_code")
        }

        candidates: List[StrongStartCandidate] = []
        for _, row in snapshot.iterrows():
            ts_code = str(row.get("ts_code") or "")
            history = histories.get(ts_code)
            if history is None or len(history) < 30:
                continue
            current = history.iloc[-1]
            is_breakout = bool(current.get("breakout_day", False))
            if is_breakout and self.params.allow_breakout_setup:
                candidate = self._build_candidate(
                    row=current,
                    breakout_row=current,
                    watch_date=resolved,
                    setup_type="breakout",
                )
            else:
                if is_breakout and not self.params.allow_breakout_setup:
                    continue
                if not self.params.allow_pullback_setup:
                    continue
                breakout_row = self._find_recent_breakout(history)
                if breakout_row is None:
                    continue
                if not self._is_pullback_candidate(current, breakout_row):
                    continue
                candidate = self._build_candidate(
                    row=current,
                    breakout_row=breakout_row,
                    watch_date=resolved,
                    setup_type="pullback",
                )
            if candidate.signal_score >= min_score:
                candidates.append(candidate)

        candidates = sorted(candidates, key=lambda item: item.signal_score, reverse=True)[:top_k]
        logger.info("strong_start: selected %d candidates [%s]", len(candidates), resolved)
        return candidates

    def _market_gate(self, features: pd.DataFrame, end_date: str) -> Tuple[float, int]:
        min_score, top_k = super()._market_gate(features, end_date)
        # For this strategy, caution mode should never expand candidate count.
        top_k = min(max(int(top_k), 0), max(int(self.params.top_k), 0))
        return min_score, top_k

    def _base_filter(self, df: pd.DataFrame) -> pd.DataFrame:
        p = self.params
        cond = (
            df["close"].between(p.min_price, p.max_price)
            & df["amt_ma20"].fillna(0).ge(p.min_amt_ma20)
            & df["list_days"].fillna(0).ge(p.min_list_days)
            & df["pivot"].notna()
            & df["ma20"].notna()
            & df["ma60"].notna()
            & df["close"].ge(df["ma20"])
            & df["ma20"].ge(df["ma60"] * 0.97)
            & df["ma20_slope"].fillna(-1).gt(-0.005)
            & df["rs20_xsec_q"].fillna(0).between(p.rs_quantile_min, p.rs_quantile_max)
            & df["platform_range_best"].fillna(np.inf).le(p.platform_max_range)
            & (
                df["vol20_vol60"].fillna(np.inf).le(p.vol_contraction_ratio)
                | df["below_vol60_days"].fillna(0).ge(p.low_vol_days_required)
                | df["atr_ratio_q60"].fillna(np.inf).le(p.atr_squeeze_quantile_max)
            )
            & df["chip_concentration"].fillna(np.inf).le(p.chip_concentration_max)
            & df["chip_available_days"].fillna(0).ge(max(3, p.chip_stability_days // 2))
            & df["chip_concentration_std"].fillna(np.inf).le(p.chip_stability_std_max)
            & df["chip_low_position"].fillna(np.inf).le(p.chip_low_position_max)
            & df["chip_matches_platform"].fillna(False)
            & df["winner_rate"].fillna(0).between(p.winner_rate_min, p.winner_rate_max)
            & df["chip_dist_points"].fillna(0).ge(p.chip_dist_min_rows)
            & df["chip_peak_count_sig"].fillna(np.inf).le(p.chip_peak_count_max)
            & df["chip_secondary_peak_ratio"].fillna(np.inf).le(p.chip_peak_secondary_ratio_max)
            & df["chip_peak_dominance"].fillna(0).ge(p.chip_peak_dominance_min)
            & df["single_peak_dense_score"].fillna(0).ge(p.chip_single_peak_score_min)
            & df["close"].le(df["pivot"] * 1.12)
        )

        if "name" in df.columns:
            name_mask = ~df["name"].fillna("").str.upper().str.contains(r"ST|退", regex=True)
            cond = cond & name_mask

        return df.loc[cond].copy()

    def _find_recent_breakout(self, history: pd.DataFrame) -> Optional[pd.Series]:
        p = self.params
        if history.empty:
            return None
        recent = history.tail(p.pullback_window_days + 1)
        if len(recent) <= 1:
            return None
        candidates = recent.iloc[:-1]
        hits = candidates.loc[candidates["breakout_day"].fillna(False)]
        if hits.empty:
            return None
        return hits.iloc[-1]

    def _is_pullback_candidate(self, current: pd.Series, breakout_row: pd.Series) -> bool:
        p = self.params
        pivot = float(breakout_row.get("pivot", 0.0) or 0.0)
        if pivot <= 0:
            return False

        current_vol_ratio = float(current.get("vol", 0.0) or 0.0) / max(
            float(current.get("vol_ma20", 0.0) or 0.0), 1e-9
        )
        close_ok = float(current.get("close", 0.0) or 0.0) >= pivot
        low_ok = float(current.get("low", 0.0) or 0.0) >= pivot * (1.0 - p.pullback_max_break_pct)
        vol_ok = (
            current_vol_ratio <= p.pullback_volume_shrink_ratio
            or float(current.get("vol", 0.0) or 0.0) < float(breakout_row.get("vol", 0.0) or 0.0)
        )
        candle_ok = (
            float(current.get("close_pos", 0.0) or 0.0) >= 0.40
            or float(current.get("close", 0.0) or 0.0) >= float(current.get("open", 0.0) or 0.0)
        )
        ma_ok = float(current.get("close", 0.0) or 0.0) >= float(current.get("ma10", 0.0) or 0.0)
        return bool(close_ok and low_ok and vol_ok and candle_ok and ma_ok)

    def _build_candidate(
        self,
        row: pd.Series,
        breakout_row: pd.Series,
        watch_date: str,
        setup_type: str,
    ) -> StrongStartCandidate:
        p = self.params

        pivot = float(breakout_row.get("pivot", row.get("pivot", 0.0)) or 0.0)
        close = float(row.get("close", 0.0) or 0.0)
        body_low = min(float(row.get("open", close) or close), close)

        if setup_type == "breakout":
            trigger_price = max(close, pivot * (1.0 + p.breakout_buffer))
            stop_loss = max(pivot * (1.0 - p.breakout_stop_buffer), body_low)
            volume_ratio = float(breakout_row.get("breakout_volume_ratio", 0.0) or 0.0)
        else:
            trigger_price = max(close, pivot)
            stop_loss = max(pivot * (1.0 - p.pullback_stop_buffer), float(row.get("low", 0.0) or 0.0))
            volume_ratio = float(row.get("vol", 0.0) or 0.0) / max(
                float(row.get("vol_ma20", 0.0) or 0.0), 1e-9
            )

        if stop_loss >= trigger_price:
            stop_loss = trigger_price * 0.97

        score, detail = self._score_candidate(row=row, breakout_row=breakout_row, setup_type=setup_type)
        breakout_date = self._trade_date_to_text(breakout_row.get("trade_date"))

        return StrongStartCandidate(
            ts_code=str(row.get("ts_code") or ""),
            name=str(row.get("name") or ""),
            watch_date=str(watch_date),
            setup_type=setup_type,
            close=round(close, 2),
            pivot=round(pivot, 2),
            trigger_price=round(trigger_price, 2),
            stop_loss=round(stop_loss, 2),
            signal_score=score,
            volume_ratio=round(float(volume_ratio or 0.0), 2),
            platform_range=round(float(row.get("platform_range_best", 0.0) or 0.0) * 100.0, 2),
            chip_concentration=round(float(row.get("chip_concentration", 0.0) or 0.0) * 100.0, 2),
            chip_low_position=round(float(row.get("chip_low_position", 0.0) or 0.0) * 100.0, 2),
            rs20=round(float(row.get("rs20", 0.0) or 0.0) * 100.0, 2),
            rs20_xsec_q=round(float(row.get("rs20_xsec_q", 0.0) or 0.0), 4),
            single_peak_dense_score=round(float(row.get("single_peak_dense_score", 0.0) or 0.0), 4),
            breakout_date=breakout_date,
            winner_rate=round(float(row.get("winner_rate", 0.0) or 0.0), 4),
            industry=str(row.get("industry") or ""),
            score_detail=detail,
        )

    def _score_candidate(
        self,
        row: pd.Series,
        breakout_row: pd.Series,
        setup_type: str,
    ) -> Tuple[float, str]:
        p = self.params

        chip_conc = float(row.get("chip_concentration", 0.0) or 0.0)
        chip_std = float(row.get("chip_concentration_std", 0.0) or 0.0)
        chip_low = float(row.get("chip_low_position", 0.0) or 0.0)
        chip_platform = 1.0 if bool(row.get("chip_matches_platform", False)) else 0.0
        single_peak_dense = min(max(float(row.get("single_peak_dense_score", 0.0) or 0.0), 0.0), 1.0)
        peak_dom = float(row.get("chip_peak_dominance", 0.0) or 0.0)
        peak_dom_score = min(
            max(
                (peak_dom - p.chip_peak_dominance_min) / max(1.0 - p.chip_peak_dominance_min, 1e-9),
                0.0,
            ),
            1.0,
        )

        chip_narrow = 1.0 - min(chip_conc / max(p.chip_concentration_max, 1e-9), 1.0)
        chip_stable = 1.0 - min(chip_std / max(p.chip_stability_std_max, 1e-9), 1.0)
        chip_low_score = 1.0 - min(chip_low / max(p.chip_low_position_max, 1e-9), 1.0)
        chip_score = (
            0.28 * chip_narrow
            + 0.15 * chip_stable
            + 0.18 * chip_low_score
            + 0.12 * chip_platform
            + 0.17 * single_peak_dense
            + 0.10 * peak_dom_score
        ) * 30.0

        platform_tight = 1.0 - min(
            float(row.get("platform_range_best", p.platform_max_range) or p.platform_max_range)
            / max(p.platform_max_range, 1e-9),
            1.0,
        )
        vol_shrink = 1.0 - min(
            float(row.get("vol20_vol60", p.vol_contraction_ratio) or p.vol_contraction_ratio)
            / max(p.vol_contraction_ratio * 1.35, 1e-9),
            1.0,
        )
        low_vol = min(
            float(row.get("below_vol60_days", 0.0) or 0.0) / max(float(p.low_vol_days_window), 1.0),
            1.0,
        )
        atr_tight = 1.0 - min(
            float(row.get("atr_ratio_q60", p.atr_squeeze_quantile_max) or p.atr_squeeze_quantile_max)
            / max(p.atr_squeeze_quantile_max, 1e-9),
            1.0,
        )
        contraction_score = (
            0.40 * platform_tight
            + 0.25 * vol_shrink
            + 0.20 * low_vol
            + 0.15 * atr_tight
        ) * 25.0

        rs_score = min(max(float(row.get("rs20_xsec_q", 0.0) or 0.0), 0.0), 1.0)
        slope_score = min(max(float(row.get("ma20_slope", 0.0) or 0.0) / 0.03, 0.0), 1.0)
        ma_align = 1.0 if float(row.get("ma10", 0.0) or 0.0) >= float(row.get("ma20", 0.0) or 0.0) else 0.6
        strength_score = (0.50 * rs_score + 0.30 * slope_score + 0.20 * ma_align) * 20.0

        if setup_type == "breakout":
            vol_ratio = float(breakout_row.get("breakout_volume_ratio", 0.0) or 0.0)
            vol_score = min(
                max((vol_ratio - 1.0) / max(p.breakout_volume_ratio - 1.0, 0.1), 0.0),
                1.0,
            )
            close_score = min(
                max(
                    (float(breakout_row.get("close_pos", 0.0) or 0.0) - p.breakout_close_pos_min)
                    / max(1.0 - p.breakout_close_pos_min, 0.1),
                    0.0,
                ),
                1.0,
            )
            hold_score = 1.0 if float(row.get("close", 0.0) or 0.0) >= float(breakout_row.get("pivot", 0.0) or 0.0) else 0.0
            trigger_score = (0.45 * vol_score + 0.35 * close_score + 0.20 * hold_score) * 15.0
            setup_bonus = 10.0 if float(breakout_row.get("close", 0.0) or 0.0) >= float(breakout_row.get("pivot", 0.0) or 0.0) * 1.01 else 8.0
        else:
            pivot = float(breakout_row.get("pivot", 0.0) or 0.0)
            stay_above = min(
                max(
                    (float(row.get("close", 0.0) or 0.0) - pivot * (1.0 - p.pullback_max_break_pct))
                    / max(pivot * p.pullback_max_break_pct, 1e-9),
                    0.0,
                ),
                1.0,
            )
            current_vol_ratio = float(row.get("vol", 0.0) or 0.0) / max(float(row.get("vol_ma20", 0.0) or 0.0), 1e-9)
            shrink_score = 1.0 - min(
                current_vol_ratio / max(p.pullback_volume_shrink_ratio * 1.20, 1e-9),
                1.0,
            )
            close_score = min(max((float(row.get("close_pos", 0.0) or 0.0) - 0.40) / 0.60, 0.0), 1.0)
            trigger_score = (0.40 * stay_above + 0.35 * shrink_score + 0.25 * close_score) * 15.0
            setup_bonus = 10.0

        total_score = round(
            min(chip_score + contraction_score + strength_score + trigger_score + setup_bonus, 100.0),
            2,
        )
        detail = (
            f"chip={chip_score:.1f} contraction={contraction_score:.1f} "
            f"strength={strength_score:.1f} trigger={trigger_score:.1f} "
            f"peak={single_peak_dense:.2f} setup={setup_bonus:.1f}"
        )
        return total_score, detail

    def _build_chip_dist_factors(self, chip_dist: pd.DataFrame) -> pd.DataFrame:
        p = self.params
        out_cols = [
            "ts_code",
            "trade_date",
            "chip_peak_count_sig",
            "chip_primary_peak_weight",
            "chip_secondary_peak_ratio",
            "chip_peak_dominance",
            "chip_main_band_weight",
            "chip_dist_points",
            "single_peak_dense_score",
            "chip_single_peak_dense",
        ]
        if chip_dist is None or chip_dist.empty:
            return pd.DataFrame(columns=out_cols)

        dist = chip_dist.copy()
        dist["price"] = pd.to_numeric(dist["price"], errors="coerce")
        dist["weight"] = pd.to_numeric(dist["weight"], errors="coerce")
        dist["trade_date"] = pd.to_datetime(
            dist["trade_date"].astype(str), format="%Y%m%d", errors="coerce"
        )
        dist = dist.dropna(subset=["ts_code", "trade_date", "price", "weight"]).copy()
        if dist.empty:
            return pd.DataFrame(columns=out_cols)

        rows: List[Dict[str, object]] = []
        for (ts_code, trade_date), sub in dist.groupby(["ts_code", "trade_date"]):
            row = self._calc_single_peak_for_group(ts_code, trade_date, sub)
            if row:
                rows.append(row)
        if not rows:
            return pd.DataFrame(columns=out_cols)
        return pd.DataFrame(rows, columns=out_cols)

    def _calc_single_peak_for_group(
        self,
        ts_code: str,
        trade_date: pd.Timestamp,
        sub: pd.DataFrame,
    ) -> Optional[Dict[str, object]]:
        p = self.params
        block = sub.sort_values("price")[["price", "weight"]].copy()
        if len(block) < max(p.chip_dist_min_rows, 3):
            return None
        w = block["weight"].to_numpy(dtype=float)
        w = np.nan_to_num(w, nan=0.0, posinf=0.0, neginf=0.0)
        w = np.maximum(w, 0.0)
        weight_sum = float(w.sum())
        if weight_sum <= 0:
            return None
        w = w / weight_sum
        px = block["price"].to_numpy(dtype=float)
        peak_indexes = self._find_local_peak_indexes(w)
        if peak_indexes.size == 0:
            peak_indexes = np.array([int(np.argmax(w))], dtype=int)
        peak_weights = w[peak_indexes]
        peak_prices = px[peak_indexes]
        order = np.argsort(-peak_weights)
        peak_weights = peak_weights[order]
        peak_prices = peak_prices[order]

        primary_weight = float(peak_weights[0]) if len(peak_weights) >= 1 else 0.0
        secondary_weight = float(peak_weights[1]) if len(peak_weights) >= 2 else 0.0
        secondary_ratio = secondary_weight / max(primary_weight, 1e-9)
        # Use relative dominance in [0, 1] to match threshold semantics.
        dominance = max(1.0 - secondary_ratio, 0.0)
        dominant_price = float(peak_prices[0]) if len(peak_prices) >= 1 else float(px[np.argmax(w)])

        significant_count = int(np.sum(peak_weights >= primary_weight * p.chip_peak_significant_ratio))
        band_mask = np.abs(px - dominant_price) <= max(dominant_price, 1e-9) * p.chip_peak_band_pct
        main_band_weight = float(w[band_mask].sum())

        dist_std = float(np.sqrt(np.sum(w * np.square(px - dominant_price))))
        norm_std = dist_std / max(dominant_price, 1e-9)
        spread_penalty = min(norm_std / max(p.chip_peak_band_pct * 1.5, 1e-9), 1.0)
        density_score = max(main_band_weight * (1.0 - 0.6 * spread_penalty), 0.0)
        secondary_score = 1.0 - min(secondary_ratio / max(p.chip_peak_secondary_ratio_max, 1e-9), 1.0)
        peak_count_score = max(1.0 - max(significant_count - 1, 0) / 3.0, 0.0)

        single_peak_dense_score = min(
            max(
                0.40 * secondary_score
                + 0.30 * main_band_weight
                + 0.20 * density_score
                + 0.10 * peak_count_score,
                0.0,
            ),
            1.0,
        )
        is_single_peak_dense = (
            significant_count <= 1
            and secondary_ratio <= p.chip_peak_secondary_ratio_max
            and dominance >= p.chip_peak_dominance_min
            and single_peak_dense_score >= p.chip_single_peak_score_min
        )

        return {
            "ts_code": str(ts_code),
            "trade_date": trade_date,
            "chip_peak_count_sig": significant_count,
            "chip_primary_peak_weight": primary_weight,
            "chip_secondary_peak_ratio": secondary_ratio,
            "chip_peak_dominance": dominance,
            "chip_main_band_weight": main_band_weight,
            "chip_dist_points": int(len(block)),
            "single_peak_dense_score": single_peak_dense_score,
            "chip_single_peak_dense": bool(is_single_peak_dense),
        }

    @staticmethod
    def _find_local_peak_indexes(weights: np.ndarray) -> np.ndarray:
        if weights.size == 0:
            return np.array([], dtype=int)
        if weights.size == 1:
            return np.array([0], dtype=int)
        peaks: List[int] = []
        for i in range(weights.size):
            left = weights[i - 1] if i > 0 else -np.inf
            right = weights[i + 1] if i < weights.size - 1 else -np.inf
            if weights[i] >= left and weights[i] >= right:
                peaks.append(i)
        return np.array(peaks, dtype=int)

    @staticmethod
    def _trade_date_to_text(value: object) -> str:
        if isinstance(value, pd.Timestamp):
            return value.strftime("%Y%m%d")
        text = str(value or "").strip()
        if not text:
            return ""
        if len(text) == 8 and text.isdigit():
            return text
        if "-" in text:
            return text.replace("-", "")
        return text

    def _persist_factor_values(self, features: pd.DataFrame, trade_date: str) -> None:
        if features is None or features.empty:
            return
        p = self.params
        target = pd.Timestamp(trade_date)
        snapshot = features.loc[
            (features["trade_date"] == target)
            & (features["ts_code"].astype(str) != str(p.index_code))
        ].copy()
        if snapshot.empty:
            return

        factor_columns = {
            f"{p.factor_name_prefix}_single_peak_dense_score": "single_peak_dense_score",
            f"{p.factor_name_prefix}_chip_peak_count_sig": "chip_peak_count_sig",
            f"{p.factor_name_prefix}_chip_secondary_peak_ratio": "chip_secondary_peak_ratio",
            f"{p.factor_name_prefix}_chip_peak_dominance": "chip_peak_dominance",
            f"{p.factor_name_prefix}_chip_main_band_weight": "chip_main_band_weight",
            f"{p.factor_name_prefix}_chip_dist_points": "chip_dist_points",
            f"{p.factor_name_prefix}_chip_single_peak_dense": "chip_single_peak_dense",
        }
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        td_text = target.strftime("%Y%m%d")
        params_list: List[Tuple[str, str, str, float, str]] = []

        for _, row in snapshot.iterrows():
            ts_code = str(row.get("ts_code") or "").strip()
            if not ts_code:
                continue
            for factor_name, col in factor_columns.items():
                value = row.get(col)
                if pd.isna(value):
                    continue
                if isinstance(value, (bool, np.bool_)):
                    numeric = 1.0 if bool(value) else 0.0
                else:
                    try:
                        numeric = float(value)
                    except (TypeError, ValueError):
                        continue
                params_list.append((ts_code, td_text, factor_name, numeric, current_time))

        if not params_list:
            return

        sql = """
            INSERT OR REPLACE INTO factor_values
            (ts_code, trade_date, factor_name, factor_value, create_time)
            VALUES (?, ?, ?, ?, ?)
        """
        try:
            self.db.execute_many(sql, params_list)
            logger.info(
                "strong_start factor_values persisted: trade_date=%s rows=%d",
                td_text,
                len(params_list),
            )
        except Exception as exc:
            logger.warning("strong_start factor persistence failed: %s", exc)
