# -*- coding: utf-8 -*-
"""Sample-mining workflow for strong-start event research."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import yaml

from src.core.config import ConfigManager
from src.core.database import DatabaseManager

try:
    from sklearn.metrics import roc_auc_score
except Exception:  # pragma: no cover
    roc_auc_score = None


def _safe_ratio(num: pd.Series, den: pd.Series) -> pd.Series:
    return num / den.replace(0, np.nan)


def _date_minus(ymd: str, days: int) -> str:
    base = datetime.strptime(str(ymd), "%Y%m%d")
    return (base - timedelta(days=max(int(days), 0))).strftime("%Y%m%d")


def _date_plus(ymd: str, days: int) -> str:
    base = datetime.strptime(str(ymd), "%Y%m%d")
    return (base + timedelta(days=max(int(days), 0))).strftime("%Y%m%d")


def _fmt_ymd(v: object) -> str:
    if isinstance(v, pd.Timestamp):
        return v.strftime("%Y%m%d")
    s = str(v or "").strip()
    if len(s) == 8 and s.isdigit():
        return s
    return s.replace("-", "")


def _ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


@dataclass
class SampleMiningConfig:
    index_code: str = "000001.SH"
    output_dir: str = "data/research/strong_start"

    min_list_days: int = 120
    min_amt_ma20: float = 5e4
    min_price: float = 4.0
    max_price: float = 120.0

    candidate_pct_chg_min: float = 3.0
    candidate_vol_ratio_min: float = 1.2
    candidate_min_conditions: int = 3
    event_cooldown_days: int = 12

    hold_days: int = 5
    entry_max_gap_pct: float = 0.06
    entry_limit_up_pct: float = 0.095
    structure_break_pct: float = 0.01
    structure_check_days: int = 3

    label_a_mfe_min: float = 0.10
    label_a_mae_max: float = 0.05
    label_b_mfe_min: float = 0.06
    label_b_mae_max: float = 0.06

    chip_stability_days: int = 10
    chip_platform_tolerance: float = 0.03

    sh_prefixes: Tuple[str, ...] = ("600", "601", "603", "605")
    sz_prefixes: Tuple[str, ...] = ("000", "001", "002", "003")


class StrongStartSampleMiner:
    def __init__(self, db: DatabaseManager, cfg: Optional[SampleMiningConfig] = None):
        self.db = db
        self.cfg = cfg or SampleMiningConfig()

    def _mainboard_cond(self) -> str:
        sh_likes = " OR ".join(f"ts_code LIKE '{p}%.SH'" for p in self.cfg.sh_prefixes)
        sz_likes = " OR ".join(f"ts_code LIKE '{p}%.SZ'" for p in self.cfg.sz_prefixes)
        return f"({sh_likes} OR {sz_likes})"

    def _save_parquet(self, df: pd.DataFrame, path: Path) -> Path:
        _ensure_parent(path)
        df.to_parquet(path, index=False)
        return path

    def _save_text(self, text: str, path: Path) -> Path:
        _ensure_parent(path)
        path.write_text(text, encoding="utf-8")
        return path

    def _load_panel(self, start_date: str, end_date: str, forward_days: int = 0) -> pd.DataFrame:
        cond = self._mainboard_cond()
        sql_daily = f"""
            SELECT ts_code, trade_date, open, high, low, close, vol, amount, pct_chg
            FROM stock_daily
            WHERE trade_date >= ? AND trade_date <= ?
              AND ({cond} OR ts_code = ?)
            ORDER BY ts_code ASC, trade_date ASC
        """
        sql_basic = "SELECT ts_code, name, industry, list_date FROM stock_basic"

        daily_rows = self.db.query(sql_daily, (start_date, end_date, self.cfg.index_code))
        basic_rows = self.db.query(sql_basic)
        daily = pd.DataFrame(daily_rows) if daily_rows else pd.DataFrame()
        basic = pd.DataFrame(basic_rows) if basic_rows else pd.DataFrame()
        if daily.empty:
            return daily

        for col in ["open", "high", "low", "close", "vol", "amount", "pct_chg"]:
            daily[col] = pd.to_numeric(daily[col], errors="coerce")
        daily["trade_date"] = pd.to_datetime(daily["trade_date"].astype(str), format="%Y%m%d", errors="coerce")
        daily = daily.dropna(subset=["ts_code", "trade_date", "close", "high", "low"]).copy()
        daily = daily.sort_values(["ts_code", "trade_date"]).reset_index(drop=True)

        if not basic.empty:
            basic = basic[["ts_code", "name", "industry", "list_date"]].copy()
            basic["industry"] = basic["industry"].fillna("UNKNOWN").replace("", "UNKNOWN")
            basic["list_date"] = pd.to_datetime(
                basic["list_date"].astype(str).str[:8], format="%Y%m%d", errors="coerce"
            )
            daily = daily.merge(basic, on="ts_code", how="left")
        else:
            daily["name"] = ""
            daily["industry"] = "UNKNOWN"
            daily["list_date"] = pd.NaT

        g = daily.groupby("ts_code", group_keys=False)
        daily["bar_index"] = g.cumcount()
        for w in [5, 10, 20, 30, 40, 60]:
            daily[f"ma{w}"] = g["close"].transform(
                lambda s, n=w: s.rolling(n, min_periods=max(3, n // 2)).mean()
            )
        daily["ma20_slope_5"] = daily["ma20"] / g["ma20"].shift(5) - 1.0
        daily["list_days"] = (daily["trade_date"] - daily["list_date"]).dt.days

        daily["ret1"] = g["close"].pct_change()
        daily["ret3"] = g["close"].transform(lambda s: s / s.shift(3) - 1.0)
        daily["ret5"] = g["close"].transform(lambda s: s / s.shift(5) - 1.0)
        daily["ret20"] = g["close"].transform(lambda s: s / s.shift(20) - 1.0)
        daily["ret60"] = g["close"].transform(lambda s: s / s.shift(60) - 1.0)

        daily["vol_ma20"] = g["vol"].transform(lambda s: s.rolling(20, min_periods=10).mean())
        daily["vol_ma60"] = g["vol"].transform(lambda s: s.rolling(60, min_periods=20).mean())
        daily["amount_ma20"] = g["amount"].transform(lambda s: s.rolling(20, min_periods=10).mean())
        daily["vol_ratio20"] = _safe_ratio(daily["vol"], daily["vol_ma20"])
        daily["vol_ratio60"] = _safe_ratio(daily["vol"], daily["vol_ma60"])
        daily["vol20_vol60"] = _safe_ratio(daily["vol_ma20"], daily["vol_ma60"])
        daily["below_vol60_flag"] = (daily["vol"] < daily["vol_ma60"]).astype(float)
        daily["low_vol_days10"] = g["below_vol60_flag"].transform(lambda s: s.rolling(10, min_periods=5).sum())

        prev_close = g["close"].shift(1)
        tr = pd.concat(
            [
                daily["high"] - daily["low"],
                (daily["high"] - prev_close).abs(),
                (daily["low"] - prev_close).abs(),
            ],
            axis=1,
        ).max(axis=1)
        daily["tr"] = tr
        daily["atr14"] = g["tr"].transform(lambda s: s.rolling(14, min_periods=5).mean())
        daily["atr_ratio"] = _safe_ratio(daily["atr14"], daily["close"])

        for w in [20, 30]:
            daily[f"pivot_{w}"] = g["high"].transform(
                lambda s, n=w: s.shift(1).rolling(n, min_periods=max(5, n // 2)).max()
            )
            daily[f"platform_low_{w}"] = g["low"].transform(
                lambda s, n=w: s.shift(1).rolling(n, min_periods=max(5, n // 2)).min()
            )
            daily[f"platform_range_{w}"] = _safe_ratio(
                daily[f"pivot_{w}"] - daily[f"platform_low_{w}"],
                daily[f"pivot_{w}"],
            )
            daily[f"close_new_high_{w}"] = daily["close"] >= g["close"].transform(
                lambda s, n=w: s.shift(1).rolling(n, min_periods=max(5, n // 2)).max()
            )
        daily["close_new_high_40"] = daily["close"] >= g["close"].transform(
            lambda s: s.shift(1).rolling(40, min_periods=20).max()
        )
        daily["platform_range_best"] = daily[["platform_range_20", "platform_range_30"]].min(axis=1)
        daily["range_low_120"] = g["low"].transform(lambda s: s.rolling(120, min_periods=40).min())
        daily["range_high_120"] = g["high"].transform(lambda s: s.rolling(120, min_periods=40).max())

        bar_range = (daily["high"] - daily["low"]).replace(0, np.nan)
        daily["close_pos"] = _safe_ratio(daily["close"] - daily["low"], bar_range).fillna(0.5)
        daily["body_to_atr"] = _safe_ratio((daily["close"] - daily["open"]).abs(), daily["atr14"])
        daily["upper_shadow_ratio"] = _safe_ratio(
            daily["high"] - daily[["open", "close"]].max(axis=1),
            bar_range,
        ).fillna(0.0)
        daily["lower_shadow_ratio"] = _safe_ratio(
            daily[["open", "close"]].min(axis=1) - daily["low"],
            bar_range,
        ).fillna(0.0)

        stock_mask = daily["ts_code"] != self.cfg.index_code
        daily["rs20_xsec_q"] = np.nan
        daily["rs60_xsec_q"] = np.nan
        rs_base = daily.loc[stock_mask & daily["list_days"].fillna(0).ge(self.cfg.min_list_days)]
        if not rs_base.empty:
            daily.loc[rs_base.index, "rs20_xsec_q"] = rs_base.groupby("trade_date")["ret20"].rank(
                pct=True, method="average"
            ).values
            daily.loc[rs_base.index, "rs60_xsec_q"] = rs_base.groupby("trade_date")["ret60"].rank(
                pct=True, method="average"
            ).values

        if stock_mask.any():
            x = daily.loc[stock_mask].copy()
            x["up_flag"] = (x["pct_chg"].fillna(0.0) > 0).astype(float)
            x["peer_strong"] = (
                x["pct_chg"].fillna(0.0).ge(self.cfg.candidate_pct_chg_min)
                & x["vol_ratio20"].fillna(0.0).ge(self.cfg.candidate_vol_ratio_min)
            ).astype(float)
            ind = (
                x.groupby(["trade_date", "industry"])
                .agg(
                    industry_avg_pct=("pct_chg", "mean"),
                    industry_amount=("amount", "sum"),
                    industry_breadth=("up_flag", "mean"),
                    industry_peer_strong_count=("peer_strong", "sum"),
                )
                .reset_index()
            )
            if not ind.empty:
                ind["industry_ret3"] = ind.groupby("industry")["industry_avg_pct"].transform(
                    lambda s: s.rolling(3, min_periods=1).mean()
                )
                ind["industry_ret5"] = ind.groupby("industry")["industry_avg_pct"].transform(
                    lambda s: s.rolling(5, min_periods=1).mean()
                )
                for src, out in [
                    ("industry_avg_pct", "industry_rank_pct"),
                    ("industry_amount", "industry_amount_rank_pct"),
                    ("industry_breadth", "industry_breadth_rank_pct"),
                    ("industry_ret3", "industry_ret3_rank_pct"),
                    ("industry_ret5", "industry_ret5_rank_pct"),
                ]:
                    ind[out] = ind.groupby("trade_date")[src].rank(pct=True, method="average")
                ind["industry_strength_score"] = (
                    0.30 * ind["industry_rank_pct"]
                    + 0.25 * ind["industry_ret3_rank_pct"]
                    + 0.20 * ind["industry_ret5_rank_pct"]
                    + 0.15 * ind["industry_breadth_rank_pct"]
                    + 0.10 * ind["industry_amount_rank_pct"]
                )
                daily = daily.merge(
                    ind[
                        [
                            "trade_date",
                            "industry",
                            "industry_avg_pct",
                            "industry_ret3",
                            "industry_ret5",
                            "industry_breadth",
                            "industry_strength_score",
                            "industry_rank_pct",
                            "industry_amount_rank_pct",
                            "industry_peer_strong_count",
                        ]
                    ],
                    on=["trade_date", "industry"],
                    how="left",
                )
                daily["stock_rank_pctchg_in_industry"] = daily.groupby(["trade_date", "industry"])["pct_chg"].rank(
                    pct=True, method="average"
                )
                daily["stock_rank_amount_in_industry"] = daily.groupby(["trade_date", "industry"])["amount"].rank(
                    pct=True, method="average"
                )

        if forward_days > 0:
            for i in range(1, forward_days + 1):
                for col in ["trade_date", "open", "high", "low", "close", "pct_chg"]:
                    daily[f"{col}_fwd_{i}"] = g[col].shift(-i)
            daily["next_trade_date"] = daily["trade_date_fwd_1"]

        return daily

    def build_candidates(self, start_date: str, end_date: str) -> pd.DataFrame:
        panel = self._load_panel(_date_minus(start_date, 420), end_date, forward_days=0)
        if panel.empty:
            return panel

        snap = panel.loc[
            (panel["trade_date"] >= pd.Timestamp(start_date))
            & (panel["trade_date"] <= pd.Timestamp(end_date))
            & (panel["ts_code"] != self.cfg.index_code)
        ].copy()
        if snap.empty:
            return snap

        c1 = snap[["close_new_high_20", "close_new_high_30", "close_new_high_40"]].fillna(False).any(axis=1)
        c2 = snap["pct_chg"].fillna(0.0) >= self.cfg.candidate_pct_chg_min
        c3 = snap["vol_ratio20"].fillna(0.0) >= self.cfg.candidate_vol_ratio_min
        c4 = snap["close"].fillna(0.0) >= snap["pivot_20"].fillna(np.inf)
        c5 = snap["close"].fillna(0.0) >= snap["ma20"].fillna(np.inf)
        c6 = snap["ma20_slope_5"].fillna(-1.0) >= 0.0
        cond_count = c1.astype(int) + c2.astype(int) + c3.astype(int) + c4.astype(int) + c5.astype(int) + c6.astype(int)

        not_st = ~snap["name"].fillna("").astype(str).str.upper().str.contains(r"ST|退", regex=True)
        base = (
            snap["list_days"].fillna(0).ge(self.cfg.min_list_days)
            & snap["amount_ma20"].fillna(0.0).ge(self.cfg.min_amt_ma20)
            & snap["close"].fillna(0.0).between(self.cfg.min_price, self.cfg.max_price)
            & not_st
        )
        selected = base & cond_count.ge(self.cfg.candidate_min_conditions) & (c1 | c4)
        event_type = np.select(
            [
                selected & c4 & c3 & snap["close_pos"].fillna(0).ge(0.67),
                selected & c4 & c3,
                selected & c1,
            ],
            ["breakout_strong", "breakout_like", "trend_high_like"],
            default="momentum_like",
        )
        event_type_s = pd.Series(event_type, index=snap.index)

        events = snap.loc[selected].copy()
        if events.empty:
            return events
        events["candidate_condition_count"] = cond_count.loc[events.index]
        events["event_type_candidate"] = event_type_s.loc[events.index].values

        events = events.sort_values(["ts_code", "trade_date"]).reset_index(drop=True)
        keep = np.zeros(len(events), dtype=bool)
        for _, idx in events.groupby("ts_code").groups.items():
            last_bar = -10**9
            for k in idx:
                bar_i = int(events.loc[k, "bar_index"])
                if bar_i - last_bar > self.cfg.event_cooldown_days:
                    keep[k] = True
                    last_bar = bar_i
        events = events.loc[keep].copy()
        events["trade_date"] = events["trade_date"].dt.strftime("%Y%m%d")
        cols = [
            "trade_date",
            "ts_code",
            "name",
            "industry",
            "open",
            "high",
            "low",
            "close",
            "vol",
            "amount",
            "pct_chg",
            "list_days",
            "candidate_condition_count",
            "event_type_candidate",
            "pivot_20",
            "platform_low_20",
            "platform_range_20",
            "close_pos",
            "vol_ratio20",
        ]
        return events[cols].sort_values(["trade_date", "ts_code"]).reset_index(drop=True)

    def label_candidates(self, events: pd.DataFrame) -> pd.DataFrame:
        if events is None or events.empty:
            return pd.DataFrame()

        start = str(events["trade_date"].min())
        end = str(events["trade_date"].max())
        panel = self._load_panel(_date_minus(start, 30), _date_plus(end, 40), forward_days=self.cfg.hold_days)
        if panel.empty:
            return pd.DataFrame()
        panel = panel.loc[panel["ts_code"] != self.cfg.index_code].copy()
        panel["trade_date"] = panel["trade_date"].dt.strftime("%Y%m%d")

        cols = ["ts_code", "trade_date", "next_trade_date", "open_fwd_1", "pct_chg_fwd_1"]
        cols += [f"high_fwd_{i}" for i in range(1, self.cfg.hold_days + 1)]
        cols += [f"low_fwd_{i}" for i in range(1, self.cfg.hold_days + 1)]
        cols += [f"close_fwd_{i}" for i in range(1, self.cfg.hold_days + 1)]
        out = events.merge(panel[cols], on=["ts_code", "trade_date"], how="left")
        if out.empty:
            return out

        close_cols = [f"close_fwd_{i}" for i in range(1, self.cfg.hold_days + 1)]
        high_cols = [f"high_fwd_{i}" for i in range(1, self.cfg.hold_days + 1)]
        low_cols = [f"low_fwd_{i}" for i in range(1, self.cfg.hold_days + 1)]
        out["has_full_forward_window"] = out[close_cols].notna().all(axis=1)
        out["entry_date"] = out["next_trade_date"].map(_fmt_ymd)
        out["entry_price_assumed"] = out["open_fwd_1"]
        out["entry_gap_pct"] = out["open_fwd_1"] / out["close"].replace(0, np.nan) - 1.0

        one_price_limit = (
            out["pct_chg_fwd_1"].fillna(0.0).ge(self.cfg.entry_limit_up_pct * 100.0)
            & np.isclose(out["open_fwd_1"], out["high_fwd_1"], equal_nan=False)
            & np.isclose(out["open_fwd_1"], out["low_fwd_1"], equal_nan=False)
            & np.isclose(out["open_fwd_1"], out["close_fwd_1"], equal_nan=False)
        )
        out["entry_limit_up_blocked"] = one_price_limit
        out["entry_possible"] = (
            out["has_full_forward_window"]
            & out["entry_price_assumed"].fillna(0).gt(0)
            & (~out["entry_limit_up_blocked"])
            & out["entry_gap_pct"].fillna(np.inf).le(self.cfg.entry_max_gap_pct)
        )
        out["entry_block_reason"] = np.select(
            [
                ~out["has_full_forward_window"],
                out["entry_limit_up_blocked"],
                out["entry_gap_pct"].fillna(np.inf).gt(self.cfg.entry_max_gap_pct),
            ],
            ["forward_window_incomplete", "one_price_limit_up", "gap_too_large"],
            default="tradable",
        )

        entry = out["entry_price_assumed"].replace(0, np.nan)
        out["max_favorable_excursion"] = out[high_cols].max(axis=1, skipna=True) / entry - 1.0
        out["max_adverse_excursion"] = out[low_cols].min(axis=1, skipna=True) / entry - 1.0
        mae_abs = (-out["max_adverse_excursion"]).clip(lower=0.0)

        floor = out["pivot_20"].fillna(out["close"])
        structure_break = np.zeros(len(out), dtype=bool)
        for i in range(1, min(self.cfg.hold_days, self.cfg.structure_check_days) + 1):
            structure_break |= out[f"close_fwd_{i}"] < floor * (1.0 - self.cfg.structure_break_pct)
        out["structure_break"] = structure_break

        label_a = (
            out["entry_possible"]
            & out["max_favorable_excursion"].fillna(-np.inf).ge(self.cfg.label_a_mfe_min)
            & mae_abs.fillna(np.inf).le(self.cfg.label_a_mae_max)
            & (~out["structure_break"])
        )
        label_b = (
            out["entry_possible"]
            & out["max_favorable_excursion"].fillna(-np.inf).ge(self.cfg.label_b_mfe_min)
            & mae_abs.fillna(np.inf).le(self.cfg.label_b_mae_max)
            & (~out["structure_break"])
        )
        out["label_abc"] = np.select(
            [~out["has_full_forward_window"], label_a, label_b],
            ["N", "A", "B"],
            default="C",
        )
        out["analysis_ready"] = out["label_abc"].isin(["A", "B", "C"])
        return out

    def _load_chip_features(self, key_df: pd.DataFrame) -> pd.DataFrame:
        if key_df is None or key_df.empty:
            return pd.DataFrame()
        min_date = str(key_df["trade_date"].min())
        max_date = str(key_df["trade_date"].max())
        sql = f"""
            SELECT ts_code, trade_date, cost_5pct, cost_15pct, cost_50pct, cost_85pct, cost_95pct, winner_rate
            FROM stock_chip_perf
            WHERE trade_date >= ? AND trade_date <= ?
              AND ({self._mainboard_cond()})
            ORDER BY ts_code ASC, trade_date ASC
        """
        rows = self.db.query(sql, (_date_minus(min_date, 120), max_date))
        chip = pd.DataFrame(rows) if rows else pd.DataFrame()
        if chip.empty:
            return chip

        for col in ["cost_5pct", "cost_15pct", "cost_50pct", "cost_85pct", "cost_95pct", "winner_rate"]:
            chip[col] = pd.to_numeric(chip[col], errors="coerce")
        chip["trade_date"] = chip["trade_date"].astype(str)
        chip = chip.sort_values(["ts_code", "trade_date"]).reset_index(drop=True)
        chip["chip_concentration"] = _safe_ratio(
            chip["cost_95pct"] - chip["cost_5pct"],
            chip["cost_95pct"] + chip["cost_5pct"],
        )
        chip["chip_center"] = (chip["cost_95pct"] + chip["cost_5pct"]) / 2.0
        g = chip.groupby("ts_code", group_keys=False)
        chip["chip_stability_std"] = g["chip_concentration"].transform(
            lambda s: s.rolling(self.cfg.chip_stability_days, min_periods=max(3, self.cfg.chip_stability_days // 2)).std()
        )
        chip["chip_available_days"] = g["chip_concentration"].transform(
            lambda s: s.rolling(self.cfg.chip_stability_days, min_periods=1).count()
        )

        out = key_df.merge(chip, on=["ts_code", "trade_date"], how="left")
        span = (out["range_high_120"] - out["range_low_120"]).replace(0, np.nan)
        out["chip_low_position"] = _safe_ratio(out["chip_center"] - out["range_low_120"], span)
        out["chip_matches_platform20"] = (
            out["cost_5pct"].fillna(np.inf).ge(
                out["platform_low_20"].fillna(-np.inf) * (1.0 - self.cfg.chip_platform_tolerance)
            )
            & out["cost_95pct"].fillna(-np.inf).le(
                out["pivot_20"].fillna(np.inf) * (1.0 + self.cfg.chip_platform_tolerance)
            )
        ).astype(float)
        keep = [
            "ts_code",
            "trade_date",
            "winner_rate",
            "chip_concentration",
            "chip_center",
            "chip_stability_std",
            "chip_available_days",
            "chip_low_position",
            "chip_matches_platform20",
        ]
        return out[keep].drop_duplicates(subset=["ts_code", "trade_date"])

    def extract_features(self, labeled_df: pd.DataFrame) -> pd.DataFrame:
        if labeled_df is None or labeled_df.empty:
            return pd.DataFrame()
        start = str(labeled_df["trade_date"].min())
        end = str(labeled_df["trade_date"].max())
        panel = self._load_panel(_date_minus(start, 420), end, forward_days=0)
        if panel.empty:
            return pd.DataFrame()
        panel = panel.loc[panel["ts_code"] != self.cfg.index_code].copy()
        panel["trade_date"] = panel["trade_date"].dt.strftime("%Y%m%d")

        feat_cols = [
            "ts_code",
            "trade_date",
            "ret20",
            "ret60",
            "rs20_xsec_q",
            "rs60_xsec_q",
            "ma20_slope_5",
            "close",
            "ma20",
            "ma60",
            "close_pos",
            "body_to_atr",
            "upper_shadow_ratio",
            "lower_shadow_ratio",
            "vol_ratio20",
            "vol_ratio60",
            "vol20_vol60",
            "low_vol_days10",
            "atr_ratio",
            "pivot_20",
            "platform_low_20",
            "platform_range_20",
            "platform_range_30",
            "platform_range_best",
            "range_low_120",
            "range_high_120",
            "industry_avg_pct",
            "industry_ret3",
            "industry_ret5",
            "industry_breadth",
            "industry_strength_score",
            "industry_rank_pct",
            "industry_amount_rank_pct",
            "industry_peer_strong_count",
            "stock_rank_pctchg_in_industry",
            "stock_rank_amount_in_industry",
        ]
        base = labeled_df.drop(
            columns=[
                c
                for c in [
                    "pivot_20",
                    "platform_low_20",
                    "platform_range_20",
                    "close_pos",
                    "vol_ratio20",
                ]
                if c in labeled_df.columns
            ],
            errors="ignore",
        )
        out = base.merge(panel[feat_cols], on=["ts_code", "trade_date"], how="left")
        chip_keys = out[["ts_code", "trade_date", "pivot_20", "platform_low_20", "range_low_120", "range_high_120"]].drop_duplicates()
        chip = self._load_chip_features(chip_keys)
        if not chip.empty:
            out = out.merge(chip, on=["ts_code", "trade_date"], how="left")
        return out

    def analyze_features(self, df: pd.DataFrame) -> Tuple[pd.DataFrame, Dict[str, object], str]:
        if df is None or df.empty:
            return pd.DataFrame(), {}, "# Strong Start Sample Analysis\n\nNo data."
        x = df.loc[df["label_abc"].isin(["A", "B", "C"])].copy()
        if x.empty:
            return pd.DataFrame(), {}, "# Strong Start Sample Analysis\n\nNo A/B/C samples."

        exclude = {
            "trade_date",
            "ts_code",
            "name",
            "industry",
            "event_type_candidate",
            "entry_date",
            "entry_block_reason",
            "label_abc",
            "analysis_ready",
            "entry_price_assumed",
            "entry_gap_pct",
            "entry_limit_up_blocked",
            "entry_possible",
            "has_full_forward_window",
            "structure_break",
            "max_favorable_excursion",
            "max_adverse_excursion",
        }
        exclude_prefixes = ("open_fwd_", "high_fwd_", "low_fwd_", "close_fwd_", "pct_chg_fwd_")
        numeric_cols = [
            c
            for c in x.columns
            if c not in exclude
            and not any(c.startswith(prefix) for prefix in exclude_prefixes)
            and pd.api.types.is_numeric_dtype(x[c])
            and (not pd.api.types.is_bool_dtype(x[c]))
        ]
        a = x["label_abc"] == "A"
        c = x["label_abc"] == "C"

        rows: List[Dict[str, object]] = []
        for col in numeric_cols:
            a_vals = pd.to_numeric(x.loc[a, col], errors="coerce").dropna()
            c_vals = pd.to_numeric(x.loc[c, col], errors="coerce").dropna()
            if len(a_vals) < 10 or len(c_vals) < 10:
                continue
            direction = "higher_better" if a_vals.median() >= c_vals.median() else "lower_better"
            auc = np.nan
            sep = np.nan
            if roc_auc_score is not None:
                pair = pd.DataFrame(
                    {"f": pd.concat([a_vals, c_vals], ignore_index=True), "y": [1] * len(a_vals) + [0] * len(c_vals)}
                ).dropna()
                if pair["y"].nunique() == 2 and len(pair) >= 20:
                    auc = float(roc_auc_score(pair["y"], pair["f"]))
                    sep = max(auc, 1.0 - auc)
            role = "weak"
            if pd.notna(sep):
                if sep >= 0.72:
                    role = "hard_filter"
                elif sep >= 0.60:
                    role = "score"
            q25_a = float(a_vals.quantile(0.25))
            q75_a = float(a_vals.quantile(0.75))
            rows.append(
                {
                    "feature": col,
                    "valid_count": int(pd.to_numeric(x[col], errors="coerce").notna().sum()),
                    "median_A": float(a_vals.median()),
                    "median_C": float(c_vals.median()),
                    "q25_A": q25_a,
                    "q75_A": q75_a,
                    "auc_A_vs_C": auc,
                    "separability": sep,
                    "direction": direction,
                    "suggested_role": role,
                    "suggested_min": q25_a if direction == "higher_better" and role != "weak" else np.nan,
                    "suggested_max": q75_a if direction == "lower_better" and role != "weak" else np.nan,
                }
            )

        summary = pd.DataFrame(rows)
        if not summary.empty:
            summary = summary.sort_values(["separability", "valid_count"], ascending=[False, False]).reset_index(drop=True)

        counts = x["label_abc"].value_counts().to_dict()
        threshold_items: List[Dict[str, object]] = []
        if not summary.empty:
            for _, r in summary.head(12).iterrows():
                threshold_items.append(
                    {
                        "feature": str(r["feature"]),
                        "direction": str(r["direction"]),
                        "suggested_role": str(r["suggested_role"]),
                        "suggested_min": None if pd.isna(r["suggested_min"]) else float(r["suggested_min"]),
                        "suggested_max": None if pd.isna(r["suggested_max"]) else float(r["suggested_max"]),
                        "separability": None if pd.isna(r["separability"]) else float(r["separability"]),
                    }
                )
        payload = {
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "sample_counts": {k: int(v) for k, v in counts.items()},
            "threshold_candidates": threshold_items,
        }

        lines = [
            "# Strong Start Sample Analysis",
            "",
            "## Sample Counts",
            "",
            f"- A: {int(counts.get('A', 0))}",
            f"- B: {int(counts.get('B', 0))}",
            f"- C: {int(counts.get('C', 0))}",
            "",
            "## Top Features (A vs C)",
            "",
            "| Feature | Sep | Direction | Median A | Median C | Role | Suggested Min | Suggested Max |",
            "| --- | ---: | --- | ---: | ---: | --- | ---: | ---: |",
        ]
        if summary.empty:
            lines.append("| N/A | N/A | N/A | N/A | N/A | N/A | N/A | N/A |")
        else:
            for _, r in summary.head(15).iterrows():
                lines.append(
                    "| {f} | {s} | {d} | {a:.4f} | {c:.4f} | {r} | {mn} | {mx} |".format(
                        f=r["feature"],
                        s="N/A" if pd.isna(r["separability"]) else f"{float(r['separability']):.3f}",
                        d=r["direction"],
                        a=float(r["median_A"]),
                        c=float(r["median_C"]),
                        r=r["suggested_role"],
                        mn="N/A" if pd.isna(r["suggested_min"]) else f"{float(r['suggested_min']):.4f}",
                        mx="N/A" if pd.isna(r["suggested_max"]) else f"{float(r['suggested_max']):.4f}",
                    )
                )
        lines.extend(
            [
                "",
                "## Notes",
                "",
                "- Event-level sample analysis only.",
                "- All feature values are based on T-day visible information.",
                "- Industry strength is aggregated from stock_daily + stock_basic.industry.",
            ]
        )
        return summary, payload, "\n".join(lines)

    def save_candidate_outputs(self, events: pd.DataFrame, out_dir: Optional[str] = None) -> Dict[str, Path]:
        root = Path(out_dir or self.cfg.output_dir)
        root.mkdir(parents=True, exist_ok=True)
        outputs = {"candidate_events": self._save_parquet(events, root / "candidate_events.parquet")}
        if events is not None and not events.empty:
            stat = events.groupby("event_type_candidate")["ts_code"].count().sort_values(ascending=False)
            lines = ["# Candidate Summary", "", f"- Total events: {len(events)}", "", "| Event Type | Count |", "| --- | ---: |"]
            for event_type, count in stat.items():
                lines.append(f"| {event_type} | {int(count)} |")
            outputs["candidate_summary"] = self._save_text("\n".join(lines), root / "candidate_summary.md")
        return outputs

    def save_labeled_outputs(self, labeled: pd.DataFrame, out_dir: Optional[str] = None) -> Dict[str, Path]:
        root = Path(out_dir or self.cfg.output_dir)
        root.mkdir(parents=True, exist_ok=True)
        outputs = {"labeled_events": self._save_parquet(labeled, root / "labeled_events.parquet")}
        if labeled is not None and not labeled.empty:
            cnt = labeled["label_abc"].value_counts().to_dict()
            lines = [
                "# Label Summary",
                "",
                f"- Total rows: {len(labeled)}",
                f"- A: {int(cnt.get('A', 0))}",
                f"- B: {int(cnt.get('B', 0))}",
                f"- C: {int(cnt.get('C', 0))}",
                f"- N: {int(cnt.get('N', 0))}",
            ]
            outputs["label_summary"] = self._save_text("\n".join(lines), root / "label_summary.md")
        return outputs

    def save_feature_outputs(
        self,
        event_features: pd.DataFrame,
        summary: pd.DataFrame,
        thresholds: Dict[str, object],
        report: str,
        out_dir: Optional[str] = None,
    ) -> Dict[str, Path]:
        root = Path(out_dir or self.cfg.output_dir)
        root.mkdir(parents=True, exist_ok=True)
        outputs = {
            "event_features": self._save_parquet(event_features, root / "event_features.parquet"),
            "feature_summary": root / "feature_summary.csv",
            "candidate_thresholds": root / "candidate_thresholds.yaml",
            "sample_analysis_report": root / "sample_analysis_report.md",
        }
        summary.to_csv(outputs["feature_summary"], index=False, encoding="utf-8-sig")
        _ensure_parent(outputs["candidate_thresholds"])
        outputs["candidate_thresholds"].write_text(
            yaml.safe_dump(thresholds, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
        self._save_text(report, outputs["sample_analysis_report"])
        return outputs


def make_miner(cfg: Optional[SampleMiningConfig] = None) -> StrongStartSampleMiner:
    return StrongStartSampleMiner(DatabaseManager(ConfigManager()), cfg)
