#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
强势回调缩量二次启动策略菜单
"""

from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from pathlib import Path
from datetime import datetime
from typing import Any, Dict

import pandas as pd
import numpy as np

from src.modules.backtest.history_recommendation_db import HistoryRecommendationDB
from src.modules.secondary_launch_intraday import (
    detect_secondary_launch_signal,
    explain_secondary_launch_blocked,
    blocker_tag_to_label,
)
from src.modules.mainboard_secondary_launch_backtester import (
    CostConfig,
    MainboardSecondaryLaunchBacktester,
)
from src.modules.mainboard_secondary_launch_strategy import (
    MainboardSecondaryLaunchStrategy,
    StrategyParams,
)


class SecondaryLaunchMenu:
    """二次启动策略的日常使用入口。"""

    def __init__(self, config, db):
        self.config = config
        self.db = db
        self.root = Path(__file__).resolve().parents[2]
        self.results_dir = self.root / "results"
        self.results_dir.mkdir(parents=True, exist_ok=True)
        self.cache_dir = self.root / "data" / "cache"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.selection_runtime_marker_path = self.cache_dir / "secondary_launch_selection_runtime.json"
        self.history_db = HistoryRecommendationDB(
            db_path=str(self.root / self.config.get("feedback.history_recommendation_db", "data/history_recommendation.db"))
        )
        self.use_selection_history_cache = bool(
            self.config.get("stock_selection.secondary_launch.use_selection_history_cache", True)
        )
        self._ensure_storage()

    def _ensure_storage(self):
        self.db.execute(
            """
            CREATE TABLE IF NOT EXISTS secondary_launch_selection_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                trade_date TEXT NOT NULL,
                ts_code TEXT NOT NULL,
                name TEXT,
                industry TEXT,
                rank INTEGER,
                rs20 REAL,
                drawdown_from_peak REAL,
                days_since_last_limit_up INTEGER,
                strategy_name TEXT NOT NULL,
                strategy_label TEXT,
                extra_json TEXT,
                created_time TEXT DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(trade_date, ts_code, strategy_name)
            )
            """
        )
        self.db.execute(
            "CREATE INDEX IF NOT EXISTS idx_secondary_launch_history_date ON secondary_launch_selection_history(trade_date)"
        )
        self.db.execute(
            "CREATE INDEX IF NOT EXISTS idx_secondary_launch_history_code ON secondary_launch_selection_history(ts_code)"
        )

    def _secondary_launch_tier_threshold_overrides(self) -> Dict[str, float]:
        """二次启动分层阈值：与日报复盘、盘中检测共用配置，避免多处硬编码不一致。"""
        return {
            "direct_score_min": float(self.config.get("stock_selection.secondary_launch.direct_score_min", 76.0) or 76.0),
            "direct_lgb_min": float(self.config.get("stock_selection.secondary_launch.direct_lgb_min", 0.58) or 0.58),
            "semi_score_min": float(self.config.get("stock_selection.secondary_launch.semi_score_min", 70.0) or 70.0),
            "semi_lgb_min": float(self.config.get("stock_selection.secondary_launch.semi_lgb_min", 0.55) or 0.55),
            "direct_conf_min": float(self.config.get("stock_selection.secondary_launch.direct_conf_min", 0.45) or 0.45),
            "semi_conf_min": float(self.config.get("stock_selection.secondary_launch.semi_conf_min", 0.58) or 0.58),
        }

    def _build_intraday_review_for_signal(self, trade_date: str, row: dict) -> dict:
        """基于分钟数据回放单只股票盘中买点触发情况。"""
        symbol = str(row.get("ts_code", "") or "").strip().upper()
        result = {
            "has_buy_signal": False,
            "signal_type": "",
            "trigger_time": "",
            "push_reason": "",
            "not_pushed_reason": "",
            "blocker_tag": "",
            "blocker_label": "",
            "blocker_detail": "",
            "execution_tier": "",
            "execution_note": "",
            "confidence": 0.0,
        }
        if not trade_date or not symbol:
            result["not_pushed_reason"] = "缺少交易日或股票代码"
            return result

        day_text = f"{str(trade_date)[:4]}-{str(trade_date)[4:6]}-{str(trade_date)[6:8]}"
        minute_df = self.history_db.get_intraday_data(symbol)
        if minute_df.empty:
            result["not_pushed_reason"] = "缺少当日分钟数据"
            return result
        minute_df = minute_df.copy()
        minute_df["trade_date_str"] = minute_df["trade_time"].dt.strftime("%Y-%m-%d")
        minute_df = minute_df[minute_df["trade_date_str"] == day_text].copy()
        if minute_df.empty:
            result["not_pushed_reason"] = "缺少当日分钟数据"
            return result

        candidate = {
            "symbol": symbol,
            "name": str(row.get("name", "") or ""),
            "score": float(row.get("signal_score", row.get("total_score", 80.0)) or 80.0),
            "signal_score": float(row.get("signal_score", row.get("total_score", 80.0)) or 80.0),
            "rank": int(row.get("rank", 1) or 1),
            "lgb_prob": row.get("lgb_prob"),
            "pool_type": "core" if int(row.get("rank", 1) or 1) == 1 else "reserve",
            "industry": str(row.get("industry", "") or ""),
            "strategy_profile": "secondary_launch",
        }
        if row.get("lgb_prob") is not None:
            try:
                candidate["lgb_prob"] = float(row.get("lgb_prob"))
            except (TypeError, ValueError):
                pass
        candidate.update(self._secondary_launch_tier_threshold_overrides())
        industry_confirm = {"score": 50.0, "level": "neutral", "industry": candidate["industry"] or "未知"}

        minute_df = minute_df.sort_values("trade_time").reset_index(drop=True)
        for idx in range(len(minute_df)):
            frame = minute_df.iloc[: idx + 1].copy()
            now = frame.iloc[-1]["trade_time"].to_pydatetime()
            current_price = float(frame.iloc[-1]["close"])
            signal = detect_secondary_launch_signal(
                candidate=candidate,
                quote={"price": current_price},
                now=now,
                minute_df=frame,
                industry_confirm=industry_confirm,
            )
            if signal.signal:
                result["has_buy_signal"] = True
                result["signal_type"] = str(signal.signal_type or "")
                result["trigger_time"] = now.strftime("%H:%M:%S")
                result["confidence"] = round(float(signal.confidence or 0.0), 4)
                details = signal.details or {}
                result["execution_tier"] = str(details.get("execution_tier", "") or "")
                result["execution_note"] = str(details.get("execution_note", "") or "")
                result["push_reason"] = str(details.get("entry_trigger", "") or signal.reason or "")
                result["blocker_tag"] = ""
                result["blocker_detail"] = ""
                return result

        blocked = explain_secondary_launch_blocked(
            candidate=candidate,
            minute_df=minute_df,
            industry_confirm=industry_confirm,
            market_confirm=None,
        )
        result["not_pushed_reason"] = str(blocked.get("reason", "") or "未触发有效买点")
        result["blocker_tag"] = str(blocked.get("blocker_tag", "") or "")
        result["blocker_label"] = blocker_tag_to_label(result["blocker_tag"])
        result["blocker_detail"] = str(blocked.get("blocker_detail", "") or "")
        result["trigger_time"] = str(blocked.get("trigger_time", "") or result["trigger_time"])
        result["signal_type"] = str(blocked.get("signal_type", "") or result["signal_type"])
        result["execution_tier"] = str(blocked.get("execution_tier", "") or result["execution_tier"])
        result["execution_note"] = str(blocked.get("execution_note", "") or result["execution_note"])
        result["confidence"] = round(max(float(result.get("confidence", 0.0) or 0.0), float(blocked.get("confidence", 0.0) or 0.0)), 4)
        return result

    def show_menu(self):
        while True:
            print("\n    ================= 二次启动策略 =================")
            print("    |  1. 运行完整流水线      |  2. 查看最新回测摘要  |")
            print("    |  3. 查看历史信号        |  4. 运行盘前选股      |")
            print("    |  5. 查看落库历史        |  6. 一键落库自检      |")
            print("    |  7. 生成近日报表        |  8. 查看最新跟踪报表  |")
            print("    |  0. 返回主菜单                                  |")
            print("    ==================================================")

            choice = input("    请选择: ").strip()

            if choice == "1":
                self.run_pipeline()
            elif choice == "2":
                self.show_latest_summary()
            elif choice == "3":
                self.show_historical_signals()
            elif choice == "4":
                self.run_daily_selection()
            elif choice == "5":
                self.show_persisted_history()
            elif choice == "6":
                self.run_persistence_self_check()
            elif choice == "7":
                self.run_recent_tracking_report()
            elif choice == "8":
                self.show_latest_tracking_report()
            elif choice == "0":
                break
            else:
                print("    无效选择，请重新输入")

    def _build_strategy(self):
        params = StrategyParams(
            min_list_days=int(self.config.get("stock_selection.secondary_launch.min_list_days", 60)),
            limit_up_threshold=float(self.config.get("stock_selection.secondary_launch.limit_up_threshold", 9.7)),
            limit_down_threshold=float(self.config.get("stock_selection.secondary_launch.limit_down_threshold", -9.7)),
            limit_up_count_10_min=int(self.config.get("stock_selection.secondary_launch.limit_up_count_10_min", 1)),
            limit_up_count_10_max=int(self.config.get("stock_selection.secondary_launch.limit_up_count_10_max", 3)),
            last_limit_up_days_min=int(self.config.get("stock_selection.secondary_launch.last_limit_up_days_min", 2)),
            last_limit_up_days_max=int(self.config.get("stock_selection.secondary_launch.last_limit_up_days_max", 10)),
            drawdown_min=float(self.config.get("stock_selection.secondary_launch.drawdown_min", 0.01)),
            drawdown_max=float(self.config.get("stock_selection.secondary_launch.drawdown_max", 0.12)),
            vol_shrink_ratio=float(self.config.get("stock_selection.secondary_launch.vol_shrink_ratio", 0.8)),
            close_ma5_dev_max=float(self.config.get("stock_selection.secondary_launch.close_ma5_dev_max", 0.04)),
            close_ma10_min_ratio=float(self.config.get("stock_selection.secondary_launch.close_ma10_min_ratio", 0.99)),
            min_amt_ma20=float(self.config.get("stock_selection.secondary_launch.min_amt_ma20", 1e5)),
            max_amt_ma20=float(self.config.get("stock_selection.secondary_launch.max_amt_ma20", 5e6)),
            min_price=float(self.config.get("stock_selection.secondary_launch.min_price", 3.0)),
            limit_up_amt_ratio_min=float(self.config.get("stock_selection.secondary_launch.limit_up_amt_ratio_min", 0.6)),
            limit_up_amt_ratio_max=float(self.config.get("stock_selection.secondary_launch.limit_up_amt_ratio_max", 3.5)),
            rs_lookback=int(self.config.get("stock_selection.secondary_launch.rs_lookback", 20)),
            max_candidates=int(self.config.get("stock_selection.secondary_launch.max_candidates", 15)),
            picks_per_day=int(self.config.get("stock_selection.secondary_launch.picks_per_day", 2)),
            min_score=float(self.config.get("stock_selection.secondary_launch.min_score", 60.0)),
            cooldown_days=int(self.config.get("stock_selection.secondary_launch.cooldown_days", 2)),
            weak_market_ret5_threshold=float(self.config.get("stock_selection.secondary_launch.weak_market_ret5_threshold", -0.03)),
            weak_market_min_score_boost=float(self.config.get("stock_selection.secondary_launch.weak_market_min_score_boost", 5.0)),
            weak_market_max_picks=int(self.config.get("stock_selection.secondary_launch.weak_market_max_picks", 1)),
            sideways_market_ret5_low=float(self.config.get("stock_selection.secondary_launch.sideways_market_ret5_low", -0.02)),
            sideways_market_ret5_high=float(self.config.get("stock_selection.secondary_launch.sideways_market_ret5_high", 0.02)),
            sideways_market_min_score_boost=float(self.config.get("stock_selection.secondary_launch.sideways_market_min_score_boost", 12.0)),
            sideways_market_max_picks=int(self.config.get("stock_selection.secondary_launch.sideways_market_max_picks", 0)),
            second_pick_min_score=float(self.config.get("stock_selection.secondary_launch.second_pick_min_score", 64.0)),
            second_pick_score_gap=float(self.config.get("stock_selection.secondary_launch.second_pick_score_gap", 6.0)),
            risk_penalty_weight=float(self.config.get("stock_selection.secondary_launch.risk_penalty_weight", 12.0)),
            upper_shadow_penalty_threshold=float(self.config.get("stock_selection.secondary_launch.upper_shadow_penalty_threshold", 0.60)),
            upper_shadow_penalty_weight=float(self.config.get("stock_selection.secondary_launch.upper_shadow_penalty_weight", 0.35)),
            high_volume_penalty_threshold=float(self.config.get("stock_selection.secondary_launch.high_volume_penalty_threshold", 1.30)),
            high_volume_penalty_weight=float(self.config.get("stock_selection.secondary_launch.high_volume_penalty_weight", 0.35)),
            deep_negative_penalty_low=float(self.config.get("stock_selection.secondary_launch.deep_negative_penalty_low", -5.0)),
            deep_negative_penalty_high=float(self.config.get("stock_selection.secondary_launch.deep_negative_penalty_high", -3.0)),
            deep_negative_penalty_weight=float(self.config.get("stock_selection.secondary_launch.deep_negative_penalty_weight", 0.30)),
            direct_score_min=float(self.config.get("stock_selection.secondary_launch.direct_score_min", 76.0)),
            direct_lgb_min=float(self.config.get("stock_selection.secondary_launch.direct_lgb_min", 0.58)),
            semi_score_min=float(self.config.get("stock_selection.secondary_launch.semi_score_min", 70.0)),
            semi_lgb_min=float(self.config.get("stock_selection.secondary_launch.semi_lgb_min", 0.55)),
            direct_conf_min=float(self.config.get("stock_selection.secondary_launch.direct_conf_min", 0.45) or 0.45),
            semi_conf_min=float(self.config.get("stock_selection.secondary_launch.semi_conf_min", 0.58) or 0.58),
            lgb_enabled=bool(self.config.get("stock_selection.secondary_launch.lgb_enabled", False)),
            lgb_mode=str(self.config.get("stock_selection.secondary_launch.lgb_mode", "blend")),
            lgb_weight=float(self.config.get("stock_selection.secondary_launch.lgb_weight", 0.35)),
            lgb_min_score=float(self.config.get("stock_selection.secondary_launch.lgb_min_score", 0.569)),

            lgb_config_path=str(self.config.get("stock_selection.secondary_launch.lgb_config_path", "models/secondary_launch_lgb_model.json")),
            lgb_model_path=str(self.config.get("stock_selection.secondary_launch.lgb_model_path", "models/secondary_launch_lgb_model.txt")),
        )
        cost = CostConfig(
            buy_fee_rate=float(self.config.get("feedback.buy_fee_rate", 0.0003)),
            sell_fee_rate=float(self.config.get("feedback.sell_fee_rate", 0.0003)),
            stamp_tax_rate=float(self.config.get("feedback.stamp_tax_rate", 0.0005)),
            transfer_fee_rate=float(self.config.get("stock_selection.secondary_launch.transfer_fee_rate", 0.00001)),
            slippage_rate=float(self.config.get("feedback.buy_slippage", 0.001)),
        )
        strategy = MainboardSecondaryLaunchStrategy(params)
        backtester = MainboardSecondaryLaunchBacktester(self.db, strategy, cost)
        return strategy, backtester

    def get_strategy_label(self) -> str:
        ver = str(self.config.get("stock_selection.secondary_launch.strategy_version", "") or "").strip()
        if ver == "v3_final":
            return "二次启动策略（V3 最终版：日线闸门+分时渐进回踩）"
        return "二次启动策略（walk-forward 优化版）"

    def get_selection_meta(self, trade_date: str) -> dict:
        strategy, _ = self._build_strategy()
        return {
            "selection_end_date": trade_date,
            "strategy_name": "secondary_launch_walkforward",
            "strategy_version": str(
                self.config.get("stock_selection.secondary_launch.strategy_version", "")
            ),
            "strategy_label": self.get_strategy_label(),
            "strategy_params": {
                "hold_days": int(self.config.get("stock_selection.secondary_launch.hold_days", 2)),
                "drawdown_min": float(strategy.params.drawdown_min),
                "drawdown_max": float(strategy.params.drawdown_max),
                "vol_shrink_ratio": float(strategy.params.vol_shrink_ratio),
                "close_ma10_min_ratio": float(strategy.params.close_ma10_min_ratio),
                "last_limit_up_days_min": int(strategy.params.last_limit_up_days_min),
                "last_limit_up_days_max": int(strategy.params.last_limit_up_days_max),
                "limit_up_count_10_min": int(strategy.params.limit_up_count_10_min),
                "limit_up_count_10_max": int(strategy.params.limit_up_count_10_max),
                "picks_per_day": int(strategy.params.picks_per_day),
                "min_score": float(strategy.params.min_score),
                "cooldown_days": int(strategy.params.cooldown_days),
                "second_pick_min_score": float(strategy.params.second_pick_min_score),
                "second_pick_score_gap": float(strategy.params.second_pick_score_gap),
                "risk_penalty_weight": float(strategy.params.risk_penalty_weight),
                "direct_score_min": float(strategy.params.direct_score_min),
                "direct_lgb_min": float(strategy.params.direct_lgb_min),
                "semi_score_min": float(strategy.params.semi_score_min),
                "semi_lgb_min": float(strategy.params.semi_lgb_min),
                "direct_conf_min": float(strategy.params.direct_conf_min),
                "semi_conf_min": float(strategy.params.semi_conf_min),
            },
        }

    def _filter_recent_duplicates(self, trade_date: str, candidates: pd.DataFrame, cooldown_days: int) -> pd.DataFrame:
        """盘前选股也遵守连续入选冷却，避免与历史回测逻辑不一致。"""
        if candidates.empty or cooldown_days <= 0:
            return candidates

        history_rows = self.db.query(
            """
            SELECT ts_code
            FROM secondary_launch_selection_history
            WHERE trade_date < ?
              AND strategy_name = ?
            ORDER BY trade_date DESC
            LIMIT ?
            """,
            (trade_date, "secondary_launch_walkforward", int(cooldown_days * 10)),
        )
        if not history_rows:
            return candidates

        recent_trade_dates = self.db.query(
            """
            SELECT DISTINCT trade_date
            FROM secondary_launch_selection_history
            WHERE trade_date < ?
              AND strategy_name = ?
            ORDER BY trade_date DESC
            LIMIT ?
            """,
            (trade_date, "secondary_launch_walkforward", int(cooldown_days)),
        )
        recent_dates = {str(row["trade_date"]) for row in recent_trade_dates}
        if not recent_dates:
            return candidates

        recent_codes = self.db.query(
            """
            SELECT DISTINCT ts_code
            FROM secondary_launch_selection_history
            WHERE trade_date IN ({})
              AND strategy_name = ?
            """.format(",".join(["?"] * len(recent_dates))),
            tuple(sorted(recent_dates)) + ("secondary_launch_walkforward",),
        )
        blocked_codes = {str(row["ts_code"]) for row in recent_codes}
        if not blocked_codes:
            return candidates
        return candidates[~candidates["ts_code"].astype(str).isin(blocked_codes)].copy()

    def get_daily_selection(self, trade_date: str | None = None) -> list[dict]:
        if not trade_date:
            trade_date = self.db.get_latest_trade_date("stock_daily")
        if not trade_date:
            return []
        marker = self._load_runtime_marker()
        marker_row_count = marker.get("row_count", -1)
        try:
            marker_row_count = int(marker_row_count)
        except (TypeError, ValueError):
            marker_row_count = -1
        if marker.get("trade_date") == str(trade_date) and marker_row_count == 0:
            return []
        if self.use_selection_history_cache:
            cached = self._load_persisted_daily_selection(trade_date)
            if cached:
                return cached

        start_date = (pd.Timestamp(trade_date) - pd.Timedelta(days=90)).strftime("%Y%m%d")
        strategy, backtester = self._build_strategy()
        data = backtester.load_data(start_date, trade_date, warmup_days=0, forward_days=0)
        features = strategy.prepare_features(data["daily"], data["basic"])
        signal_frame = strategy.build_signal_frame(features)
        if signal_frame.empty:
            self._save_runtime_marker(str(trade_date), 0)
            return []
        daily_rows = signal_frame[signal_frame["signal_date"] == pd.Timestamp(trade_date)].copy()
        if daily_rows.empty:
            self._save_runtime_marker(str(trade_date), 0)
            return []
        daily_rows = self._filter_recent_duplicates(trade_date, daily_rows, strategy.params.cooldown_days)
        if daily_rows.empty:
            self._save_runtime_marker(str(trade_date), 0)
            return []
        picks = strategy.generate_signals_from_frame(daily_rows)
        if picks.empty:
            self._save_runtime_marker(str(trade_date), 0)
            return []
        feature_map = (
            daily_rows.sort_values(["signal_date", "ts_code"])
            .drop_duplicates(subset=["signal_date", "ts_code"], keep="last")
            .set_index(["signal_date", "ts_code"])
        )
        results = []
        for _, row in picks.iterrows():
            feature_row = feature_map.loc[(pd.Timestamp(trade_date), row["ts_code"])]
            gate = self._compute_v3_daily_gate_fields(feature_row)
            results.append(
                {
                    "ts_code": row["ts_code"],
                    "name": row.get("name", ""),
                    "industry": feature_row.get("industry", "未知"),
                    "total_score": round(float(row.get("signal_score", row.get("rs20", 0.0) * 100)), 2),
                    "level": "二次启动候选",
                    "short_cycle_score": round(float(row.get("rs20", 0.0) * 100), 2),
                    "tradeability_score": round(float((1.0 - feature_row.get("drawdown_from_peak", 0.0)) * 100), 2),
                    "signal_score": round(float(row.get("signal_score", 0.0)), 2),
                    "quality_score": round(float(row.get("quality_score", row.get("signal_score", 0.0)) or 0.0), 2),
                    "risk_penalty_score": round(float(row.get("risk_penalty_score", 0.0) or 0.0), 2),
                    "execution_tier_hint": str(row.get("execution_tier_hint", "confirm") or "confirm"),
                    "rank": int(row.get("rank", 0) or 0),
                    "rs20": round(float(row.get("rs20", 0.0)), 4),
                    "drawdown_from_peak": round(float(feature_row.get("drawdown_from_peak", 0.0)), 4),
                    "days_since_last_limit_up": int(feature_row.get("days_since_last_limit_up", 0) or 0),
                    "lgb_prob": round(float(feature_row.get("lgb_prob", np.nan)), 4) if pd.notna(feature_row.get("lgb_prob", np.nan)) else None,
                    "strategy_name": "secondary_launch_walkforward",
                    "strategy_label": self.get_strategy_label(),
                    **gate,
                }
            )
        return results

    def _load_persisted_daily_selection(self, trade_date: str) -> list[dict]:
        """Load persisted secondary-launch picks for a date to avoid repeated heavy recomputation."""
        try:
            rows = self.db.query(
                """
                SELECT
                    ts_code, name, industry, rank, rs20, drawdown_from_peak,
                    days_since_last_limit_up, strategy_name, strategy_label, extra_json
                FROM secondary_launch_selection_history
                WHERE trade_date = ? AND strategy_name = ?
                ORDER BY rank ASC
                """,
                (str(trade_date), "secondary_launch_walkforward"),
            )
        except Exception:
            return []
        if not rows:
            return []

        results: list[dict] = []
        for row in rows:
            extra_raw = row.get("extra_json")
            extra: dict = {}
            if isinstance(extra_raw, str) and extra_raw.strip():
                try:
                    obj = json.loads(extra_raw)
                    if isinstance(obj, dict):
                        extra = obj
                except Exception:
                    extra = {}
            gate = extra.get("v3_daily_gate", {}) if isinstance(extra.get("v3_daily_gate"), dict) else {}
            results.append(
                {
                    "ts_code": row.get("ts_code"),
                    "name": row.get("name", ""),
                    "industry": row.get("industry", "未知"),
                    "total_score": round(float(extra.get("total_score", 0.0) or 0.0), 2),
                    "level": "二次启动候选",
                    "short_cycle_score": round(float(extra.get("short_cycle_score", 0.0) or 0.0), 2),
                    "tradeability_score": round(float(extra.get("tradeability_score", 0.0) or 0.0), 2),
                    "signal_score": round(float(extra.get("total_score", 0.0) or 0.0), 2),
                    "quality_score": round(float(extra.get("quality_score", 0.0) or 0.0), 2),
                    "risk_penalty_score": round(float(extra.get("risk_penalty_score", 0.0) or 0.0), 2),
                    "execution_tier_hint": str(extra.get("execution_tier_hint", "confirm") or "confirm"),
                    "rank": int(row.get("rank", 0) or 0),
                    "rs20": round(float(row.get("rs20", 0.0) or 0.0), 4),
                    "drawdown_from_peak": round(float(row.get("drawdown_from_peak", 0.0) or 0.0), 4),
                    "days_since_last_limit_up": int(row.get("days_since_last_limit_up", 0) or 0),
                    "lgb_prob": (
                        round(float(extra.get("lgb_prob", 0.0) or 0.0), 4)
                        if extra.get("lgb_prob") is not None
                        else None
                    ),
                    "strategy_name": str(row.get("strategy_name", "secondary_launch_walkforward") or "secondary_launch_walkforward"),
                    "strategy_label": str(row.get("strategy_label", self.get_strategy_label()) or self.get_strategy_label()),
                    "pct_chg": gate.get("pct_chg"),
                    "vol_ratio_5": gate.get("vol_ratio_5"),
                    "upper_shadow_pct": gate.get("upper_shadow_pct"),
                }
            )
        self._save_runtime_marker(str(trade_date), len(results))
        return results

    def _load_runtime_marker(self) -> dict:
        try:
            if not self.selection_runtime_marker_path.exists():
                return {}
            raw = json.loads(self.selection_runtime_marker_path.read_text(encoding="utf-8"))
            return raw if isinstance(raw, dict) else {}
        except Exception:
            return {}

    def _save_runtime_marker(self, trade_date: str, row_count: int) -> None:
        payload = {
            "trade_date": str(trade_date),
            "row_count": int(row_count or 0),
            "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        try:
            self.selection_runtime_marker_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception:
            pass

    @staticmethod
    def _compute_v3_daily_gate_fields(feature_row: Any) -> dict:
        """供盘中日线闸门使用的信号日涨跌幅、量比、上影线比例。"""
        pct = feature_row.get("pct_chg")
        try:
            pct_chg = float(pct) if pct is not None and str(pct) != "nan" else None
        except (TypeError, ValueError):
            pct_chg = None
        vol = float(feature_row.get("vol") or 0)
        vol_ma5 = float(feature_row.get("vol_ma5") or 0)
        vol_ratio_5 = (vol / vol_ma5) if vol_ma5 > 0 else None
        h = float(feature_row.get("high") or 0)
        c = float(feature_row.get("close") or 0)
        o = float(feature_row.get("open") or 0)
        low = float(feature_row.get("low") or 0)
        tr = h - low
        upper_shadow_pct = ((h - max(c, o)) / tr * 100.0) if tr > 0 else None
        return {
            "pct_chg": pct_chg,
            "vol_ratio_5": round(vol_ratio_5, 4) if vol_ratio_5 is not None else None,
            "upper_shadow_pct": round(upper_shadow_pct, 1) if upper_shadow_pct is not None else None,
        }

    def persist_daily_selection(self, trade_date: str | None = None, selections: list[dict] | None = None) -> int:
        if not trade_date:
            trade_date = self.db.get_latest_trade_date("stock_daily")
        if not trade_date:
            return 0
        rows = selections if selections is not None else self.get_daily_selection(trade_date)
        if not rows:
            return 0

        params_list = []
        created_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        for row in rows:
            params_list.append(
                (
                    trade_date,
                    row.get("ts_code"),
                    row.get("name"),
                    row.get("industry"),
                    int(row.get("rank", 0) or 0),
                    float(row.get("rs20", 0.0) or 0.0),
                    float(row.get("drawdown_from_peak", 0.0) or 0.0),
                    int(row.get("days_since_last_limit_up", 0) or 0),
                    str(row.get("strategy_name", "secondary_launch_walkforward")),
                    str(row.get("strategy_label", self.get_strategy_label())),
                    json.dumps(
                        {
                            "total_score": row.get("total_score"),
                            "short_cycle_score": row.get("short_cycle_score"),
                            "tradeability_score": row.get("tradeability_score"),
                            "quality_score": row.get("quality_score"),
                            "risk_penalty_score": row.get("risk_penalty_score"),
                            "execution_tier_hint": row.get("execution_tier_hint"),
                            "lgb_prob": row.get("lgb_prob"),
                            "strategy_version": str(
                                self.config.get("stock_selection.secondary_launch.strategy_version", "")
                            ),
                            "v3_daily_gate": {
                                "pct_chg": row.get("pct_chg"),
                                "vol_ratio_5": row.get("vol_ratio_5"),
                                "upper_shadow_pct": row.get("upper_shadow_pct"),
                            },
                        },
                        ensure_ascii=False,
                    ),
                    created_time,
                )
            )

        self.db.execute_many(
            """
            INSERT OR REPLACE INTO secondary_launch_selection_history (
                trade_date, ts_code, name, industry, rank, rs20, drawdown_from_peak,
                days_since_last_limit_up, strategy_name, strategy_label, extra_json, created_time
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            params_list,
        )

        for row in rows:
            self.history_db.add_recommendation(
                {
                    "symbol": row.get("ts_code"),
                    "name": row.get("name"),
                    "recommendation_date": trade_date,
                    "recommendation_reason": (
                        f"二次启动策略候选 | RS20={float(row.get('rs20', 0.0)):.3f} | "
                        f"回撤={float(row.get('drawdown_from_peak', 0.0)):.2%}"
                    ),
                    "recommendation_score": float(row.get("total_score", 0.0) or 0.0),
                    "strategy_type": str(row.get("strategy_name", "secondary_launch_walkforward")),
                    "hold_days": int(self.config.get('stock_selection.secondary_launch.hold_days', 2)),
                    "status": "active",
                    "created_time": created_time,
                }
            )
        return len(rows)

    def build_push_payload(self, trade_date: str | None = None, market_analysis: dict | None = None) -> dict:
        if not trade_date:
            trade_date = self.db.get_latest_trade_date("stock_daily")
        payload = {
            "report_date": pd.Timestamp.now().strftime("%Y-%m-%d"),
            "report_time": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S"),
            "strategy_label": self.get_strategy_label(),
            "market_analysis": market_analysis or {},
            "stock_selection": self.get_daily_selection(trade_date),
            "stock_selection_meta": self.get_selection_meta(trade_date),
        }
        return payload

    def sync_to_candidate_pool(self, trade_date: str, selections: list[dict]) -> int:
        """把二次启动候选同步到融合监控候选池缓存。"""
        if not trade_date or not selections:
            return 0

        candidates = []
        for row in selections:
            ts_code = str(row.get("ts_code", "") or "").strip()
            if not ts_code:
                continue
            cand = {
                "symbol": ts_code.split(".")[0],
                "name": str(row.get("name", "") or ""),
                "score": float(row.get("signal_score", row.get("total_score", 0.0)) or 0.0),
                "signal_score": float(row.get("signal_score", row.get("total_score", 0.0)) or 0.0),
                "rank": int(row.get("rank", 0) or 0),
                "lgb_prob": row.get("lgb_prob"),
                "level": str(row.get("level", "二次启动候选") or "二次启动候选"),
                "industry": str(row.get("industry", "未知") or "未知"),
                "pool_type": "core" if int(row.get("rank", 0) or 0) == 1 else "reserve",
                "strategy_profile": "secondary_launch",
                "strategy_name": str(row.get("strategy_name", "secondary_launch_walkforward")),
                "source": "secondary_launch_menu",
                "trade_date": str(trade_date),
            }
            for k in ("pct_chg", "vol_ratio_5", "upper_shadow_pct"):
                if k in row and row.get(k) is not None:
                    cand[k] = row[k]
            cand.update(self._secondary_launch_tier_threshold_overrides())
            candidates.append(cand)

        cache_path = self.cache_dir / "candidate_pool.json"
        prev_candidates: list[dict] = []
        if cache_path.exists():
            try:
                payload_old = json.loads(cache_path.read_text(encoding="utf-8")) or {}
                raw = payload_old.get("candidates")
                if isinstance(raw, list):
                    prev_candidates = [row for row in raw if isinstance(row, dict)]
            except Exception as exc:
                logger.warning("读取候选池缓存失败，将覆盖写入: %s", exc)

        merged = [
            row
            for row in prev_candidates
            if str(row.get("strategy_profile", "")).lower() != "secondary_launch"
        ]
        merged.extend(candidates)
        merged = sorted(
            merged,
            key=lambda x: float(x.get("score", 0) or 0),
            reverse=True,
        )[:30]

        payload = {
            "date": str(trade_date),
            "candidates": merged,
            "created_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "strategy_profile": "mixed",
        }
        cache_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return len(candidates)

    def _find_latest_signal_trade_date(self, lookback_days: int = 180) -> str | None:
        latest_trade_date = self.db.get_latest_trade_date("stock_daily")
        if not latest_trade_date:
            return None

        end_ts = pd.Timestamp(latest_trade_date)
        start_date = (end_ts - pd.Timedelta(days=int(lookback_days))).strftime("%Y%m%d")
        strategy, backtester = self._build_strategy()
        data = backtester.load_data(start_date, latest_trade_date, warmup_days=60, forward_days=10)
        features = strategy.prepare_features(data["daily"], data["basic"])
        signals = strategy.generate_signals(features)
        if signals.empty:
            return None

        signals["signal_date"] = pd.to_datetime(signals["signal_date"])
        signals = signals.sort_values(["signal_date", "rank"])
        return signals["signal_date"].iloc[-1].strftime("%Y%m%d")

    def verify_persistence(self, trade_date: str | None = None, lookback_days: int = 180) -> dict:
        if not trade_date:
            trade_date = self._find_latest_signal_trade_date(lookback_days=lookback_days)

        result = {
            "trade_date": trade_date,
            "selection_count": 0,
            "persisted_count": 0,
            "main_db_rows": [],
            "history_db_rows": [],
            "passed": False,
            "report_markdown": "",
            "report_json": "",
        }
        if not trade_date:
            return result

        rows = self.get_daily_selection(trade_date)
        result["selection_count"] = len(rows)
        if not rows:
            return result

        persisted_count = self.persist_daily_selection(trade_date, rows)
        result["persisted_count"] = persisted_count

        main_rows = self.db.query(
            """
            SELECT trade_date, ts_code, strategy_name, rank, rs20, drawdown_from_peak
            FROM secondary_launch_selection_history
            WHERE trade_date = ? AND strategy_name = ?
            ORDER BY rank
            """,
            (trade_date, "secondary_launch_walkforward"),
        )
        result["main_db_rows"] = [dict(row) for row in main_rows]

        conn = sqlite3.connect(self.history_db.db_path)
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT recommendation_date, symbol, strategy_type, recommendation_reason
            FROM recommendations
            WHERE recommendation_date = ? AND strategy_type = ?
            ORDER BY symbol
            """,
            (trade_date, "secondary_launch_walkforward"),
        )
        history_rows = cursor.fetchall()
        conn.close()
        result["history_db_rows"] = [
            {
                "recommendation_date": row[0],
                "symbol": row[1],
                "strategy_type": row[2],
                "recommendation_reason": row[3],
            }
            for row in history_rows
        ]
        result["passed"] = (
            persisted_count > 0
            and len(result["main_db_rows"]) >= persisted_count
            and len(result["history_db_rows"]) >= persisted_count
        )

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        md_path = self.results_dir / f"secondary_launch_persistence_check_{timestamp}.md"
        json_path = self.results_dir / f"secondary_launch_persistence_check_{timestamp}.json"
        markdown = self._format_persistence_report(result)
        md_path.write_text(markdown, encoding="utf-8")
        json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        result["report_markdown"] = str(md_path.relative_to(self.root))
        result["report_json"] = str(json_path.relative_to(self.root))
        return result

    def _format_persistence_report(self, result: dict) -> str:
        lines = [
            "# 二次启动策略落库自检报告",
            "",
            f"- 自检时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"- 验证交易日: {result.get('trade_date') or '未找到'}",
            f"- 候选数量: {result.get('selection_count', 0)}",
            f"- 写入数量: {result.get('persisted_count', 0)}",
            f"- 结论: {'通过' if result.get('passed') else '未通过'}",
            "",
            "## 主库记录",
            "",
        ]
        main_rows = result.get("main_db_rows", [])
        if not main_rows:
            lines.append("- 无记录")
        else:
            for row in main_rows:
                lines.append(
                    f"- {row['trade_date']} | {row['ts_code']} | rank={row['rank']} | "
                    f"RS20={float(row.get('rs20', 0.0)):.3f} | 回撤={float(row.get('drawdown_from_peak', 0.0)):.2%}"
                )

        lines.extend(["", "## 历史推荐库记录", ""])
        history_rows = result.get("history_db_rows", [])
        if not history_rows:
            lines.append("- 无记录")
        else:
            for row in history_rows:
                lines.append(
                    f"- {row['recommendation_date']} | {row['symbol']} | "
                    f"{row['strategy_type']} | {row['recommendation_reason']}"
                )
        return "\n".join(lines) + "\n"

    def run_persistence_self_check(self):
        trade_date = input("    验证交易日(YYYYMMDD，回车自动寻找最近有效信号日): ").strip() or None
        print("    正在执行二次启动策略落库自检...")
        result = self.verify_persistence(trade_date=trade_date)
        if not result.get("trade_date"):
            print("    未找到可用于自检的有效信号日")
            return
        print(f"    验证交易日: {result['trade_date']}")
        print(f"    候选数量: {result['selection_count']}")
        print(f"    写入数量: {result['persisted_count']}")
        print(f"    主库记录: {len(result['main_db_rows'])} 条")
        print(f"    历史推荐库记录: {len(result['history_db_rows'])} 条")
        print(f"    自检结论: {'通过' if result['passed'] else '未通过'}")
        if result.get("report_markdown"):
            print(f"    自检报告(MD): {result['report_markdown']}")
        if result.get("report_json"):
            print(f"    自检结果(JSON): {result['report_json']}")

    def generate_recent_signal_tracking_report(self, trade_days: int = 40) -> dict:
        latest_trade_date = self.db.get_latest_trade_date("stock_daily")
        if not latest_trade_date:
            return {}

        trade_dates = self.db.query(
            """
            SELECT DISTINCT trade_date
            FROM stock_daily
            WHERE trade_date <= ?
            ORDER BY trade_date DESC
            LIMIT ?
            """,
            (latest_trade_date, int(trade_days)),
        )
        if not trade_dates:
            return {}

        recent_dates = sorted([str(row["trade_date"]) for row in trade_dates])
        start_date = recent_dates[0]
        hold_days = int(self.config.get("stock_selection.secondary_launch.hold_days", 2))
        strategy, backtester = self._build_strategy()
        data = backtester.load_data(start_date, latest_trade_date, warmup_days=90, forward_days=max(hold_days + 2, 10))
        features = strategy.prepare_features(data["daily"], data["basic"])
        signal_frame = strategy.build_signal_frame(features)
        optimized_signals = strategy.generate_signals_from_frame(signal_frame)
        feature_map = (
            signal_frame.sort_values(["signal_date", "ts_code"])
            .drop_duplicates(subset=["signal_date", "ts_code"], keep="last")
            .set_index(["signal_date", "ts_code"])
            if not signal_frame.empty
            else pd.DataFrame()
        )

        signal_records = []
        selections_by_date = {trade_date: [] for trade_date in recent_dates}
        if not optimized_signals.empty:
            optimized_signals = optimized_signals.copy()
            optimized_signals["signal_date"] = pd.to_datetime(optimized_signals["signal_date"])
            optimized_signals = optimized_signals[
                optimized_signals["signal_date"].dt.strftime("%Y%m%d").isin(set(recent_dates))
            ].copy()
            for _, row in optimized_signals.iterrows():
                trade_date = pd.Timestamp(row["signal_date"]).strftime("%Y%m%d")
                feature_row = feature_map.loc[(pd.Timestamp(row["signal_date"]), row["ts_code"])]
                payload = {
                    "ts_code": row["ts_code"],
                    "name": row.get("name", ""),
                    "rank": int(row.get("rank", 0) or 0),
                    "rs20": round(float(row.get("rs20", 0.0)), 4),
                    "drawdown_from_peak": round(float(feature_row.get("drawdown_from_peak", 0.0)), 4),
                    "industry": feature_row.get("industry", "未知"),
                    "days_since_last_limit_up": int(feature_row.get("days_since_last_limit_up", 0) or 0),
                    "signal_score": round(float(row.get("signal_score", 0.0)), 4),
                }
                selections_by_date.setdefault(trade_date, []).append(payload)
                signal_records.append(
                    {
                        "signal_date": pd.Timestamp(row["signal_date"]),
                        "ts_code": row["ts_code"],
                        "rank": int(row.get("rank", 0) or 0),
                    }
                )

        signals = pd.DataFrame(signal_records)
        completed = backtester._simulate_trades(features, signals, hold_days) if not signals.empty else pd.DataFrame()
        completed_map = {}
        if not completed.empty:
            for _, row in completed.iterrows():
                completed_map[(row["signal_date"].strftime("%Y%m%d"), row["ts_code"])] = row

        px = features[["ts_code", "trade_date", "open", "close"]].copy()
        px["trade_date"] = pd.to_datetime(px["trade_date"])
        px = px.sort_values(["ts_code", "trade_date"]).reset_index(drop=True)
        price_map = {code: sub.reset_index(drop=True) for code, sub in px.groupby("ts_code")}

        detail_rows = []
        signal_dates = set()
        completed_returns = []
        pending_count = 0
        horizon_returns = {1: [], 2: [], 3: []}

        for trade_date in recent_dates:
            day_rows = selections_by_date.get(trade_date, [])
            if not day_rows:
                detail_rows.append(
                    {
                        "signal_date": trade_date,
                        "ts_code": "",
                        "name": "",
                        "rank": "",
                        "status": "无信号",
                        "observed_return": None,
                        "exit_date": "",
                    }
                )
                continue

            signal_dates.add(trade_date)
            for row in sorted(day_rows, key=lambda item: int(item.get("rank", 0) or 0)):
                key = (trade_date, row["ts_code"])
                trade = completed_map.get(key)
                if trade is not None:
                    observed_return = float(trade["net_ret"])
                    status = "已完成"
                    exit_date = pd.Timestamp(trade["exit_date"]).strftime("%Y%m%d")
                    completed_returns.append(observed_return)
                else:
                    series = price_map.get(row["ts_code"])
                    observed_return = None
                    exit_date = ""
                    status = "跟踪中"
                    if series is not None and not series.empty:
                        future = series[series["trade_date"] >= pd.Timestamp(trade_date)].reset_index(drop=True)
                        if not future.empty:
                            entry_open = float(future.iloc[0]["open"]) * (1.0 + backtester.cost.slippage_rate)
                            latest_close = float(future.iloc[-1]["close"]) * (1.0 - backtester.cost.slippage_rate)
                            observed_return = latest_close / entry_open - 1.0
                            exit_date = pd.Timestamp(future.iloc[-1]["trade_date"]).strftime("%Y%m%d")
                    pending_count += 1

                horizon_map = {}
                series = price_map.get(row["ts_code"])
                if series is not None and not series.empty:
                    future = series[series["trade_date"] >= pd.Timestamp(trade_date)].reset_index(drop=True)
                    if not future.empty:
                        entry_open = float(future.iloc[0]["open"]) * (1.0 + backtester.cost.slippage_rate)
                        for horizon in (1, 2, 3):
                            if len(future) > horizon:
                                horizon_close = float(future.iloc[horizon]["close"]) * (1.0 - backtester.cost.slippage_rate)
                                horizon_ret = horizon_close / entry_open - 1.0
                                horizon_map[f"T+{horizon}"] = horizon_ret
                                horizon_returns[horizon].append(horizon_ret)
                            else:
                                horizon_map[f"T+{horizon}"] = None
                else:
                    for horizon in (1, 2, 3):
                        horizon_map[f"T+{horizon}"] = None

                intraday_review = self._build_intraday_review_for_signal(trade_date, row)

                detail_rows.append(
                    {
                        "signal_date": trade_date,
                        "ts_code": row["ts_code"],
                        "name": row.get("name", ""),
                        "rank": int(row.get("rank", 0) or 0),
                        "status": status,
                        "observed_return": observed_return,
                        "exit_date": exit_date,
                        "horizon_returns": horizon_map,
                        "has_buy_signal": bool(intraday_review.get("has_buy_signal", False)),
                        "signal_type": str(intraday_review.get("signal_type", "") or ""),
                        "trigger_time": str(intraday_review.get("trigger_time", "") or ""),
                        "push_reason": str(intraday_review.get("push_reason", "") or ""),
                        "not_pushed_reason": str(intraday_review.get("not_pushed_reason", "") or ""),
                        "confidence": float(intraday_review.get("confidence", 0.0) or 0.0),
                        "execution_tier": str(intraday_review.get("execution_tier", "") or ""),
                        "execution_note": str(intraday_review.get("execution_note", "") or ""),
                    }
                )

        avg_return = sum(completed_returns) / len(completed_returns) if completed_returns else 0.0
        win_rate = (
            sum(1 for ret in completed_returns if ret > 0) / len(completed_returns)
            if completed_returns
            else 0.0
        )
        signal_date_list = sorted(signal_dates)
        signal_gaps = []
        if len(signal_date_list) >= 2:
            for prev_date, next_date in zip(signal_date_list[:-1], signal_date_list[1:]):
                prev_idx = recent_dates.index(prev_date)
                next_idx = recent_dates.index(next_date)
                signal_gaps.append(
                    {
                        "from_date": prev_date,
                        "to_date": next_date,
                        "gap_trade_days": max(0, next_idx - prev_idx - 1),
                    }
                )

        current_empty_streak = 0
        max_empty_streak = 0
        latest_empty_streak = 0
        for trade_date in recent_dates:
            has_signal = bool(selections_by_date.get(trade_date))
            if has_signal:
                current_empty_streak = 0
            else:
                current_empty_streak += 1
                max_empty_streak = max(max_empty_streak, current_empty_streak)
        for trade_date in reversed(recent_dates):
            if selections_by_date.get(trade_date):
                break
            latest_empty_streak += 1

        weekly_rows = []
        monthly_rows = []
        week_df = pd.DataFrame(
            [
                {
                    "trade_date": trade_date,
                    "week_label": pd.Timestamp(trade_date).strftime("%G-W%V"),
                    "signal_count": len(selections_by_date.get(trade_date, [])),
                }
                for trade_date in recent_dates
            ]
        )
        if not week_df.empty:
            detail_df = pd.DataFrame(detail_rows)
            if not detail_df.empty:
                detail_df = detail_df[detail_df["status"] != "无信号"].copy()
                if not detail_df.empty:
                    detail_df["week_label"] = detail_df["signal_date"].apply(
                        lambda x: pd.Timestamp(x).strftime("%G-W%V")
                    )
            for week_label, sub in week_df.groupby("week_label", sort=True):
                week_dates = sub["trade_date"].tolist()
                week_signal_count = int(sub["signal_count"].sum())
                week_signal_days = int((sub["signal_count"] > 0).sum())
                week_completed = []
                week_pending = 0
                if not detail_df.empty:
                    week_detail = detail_df[detail_df["week_label"] == week_label]
                    for _, item in week_detail.iterrows():
                        if item["status"] == "已完成" and item["observed_return"] is not None:
                            week_completed.append(float(item["observed_return"]))
                        elif item["status"] == "跟踪中":
                            week_pending += 1
                weekly_rows.append(
                    {
                        "week_label": week_label,
                        "start_date": week_dates[0],
                        "end_date": week_dates[-1],
                        "signal_days": week_signal_days,
                        "signal_count": week_signal_count,
                        "completed_count": len(week_completed),
                        "pending_count": week_pending,
                        "avg_return": sum(week_completed) / len(week_completed) if week_completed else 0.0,
                        "win_rate": (
                            sum(1 for ret in week_completed if ret > 0) / len(week_completed)
                            if week_completed
                            else 0.0
                        ),
                    }
                )

        month_df = pd.DataFrame(
            [
                {
                    "trade_date": trade_date,
                    "month_label": pd.Timestamp(trade_date).strftime("%Y-%m"),
                    "signal_count": len(selections_by_date.get(trade_date, [])),
                }
                for trade_date in recent_dates
            ]
        )
        if not month_df.empty:
            detail_df = pd.DataFrame(detail_rows)
            if not detail_df.empty:
                detail_df = detail_df[detail_df["status"] != "无信号"].copy()
                if not detail_df.empty:
                    detail_df["month_label"] = detail_df["signal_date"].apply(
                        lambda x: pd.Timestamp(x).strftime("%Y-%m")
                    )
            for month_label, sub in month_df.groupby("month_label", sort=True):
                month_dates = sub["trade_date"].tolist()
                month_signal_count = int(sub["signal_count"].sum())
                month_signal_days = int((sub["signal_count"] > 0).sum())
                month_completed = []
                month_pending = 0
                if not detail_df.empty:
                    month_detail = detail_df[detail_df["month_label"] == month_label]
                    for _, item in month_detail.iterrows():
                        if item["status"] == "已完成" and item["observed_return"] is not None:
                            month_completed.append(float(item["observed_return"]))
                        elif item["status"] == "跟踪中":
                            month_pending += 1
                monthly_rows.append(
                    {
                        "month_label": month_label,
                        "start_date": month_dates[0],
                        "end_date": month_dates[-1],
                        "signal_days": month_signal_days,
                        "signal_count": month_signal_count,
                        "completed_count": len(month_completed),
                        "pending_count": month_pending,
                        "avg_return": sum(month_completed) / len(month_completed) if month_completed else 0.0,
                        "win_rate": (
                            sum(1 for ret in month_completed if ret > 0) / len(month_completed)
                            if month_completed
                            else 0.0
                        ),
                    }
                )

        horizon_distribution = {}
        for horizon, returns in horizon_returns.items():
            horizon_distribution[f"T+{horizon}"] = {
                "sample_count": len(returns),
                "win_rate": (sum(1 for ret in returns if ret > 0) / len(returns)) if returns else 0.0,
                "avg_return": (sum(returns) / len(returns)) if returns else 0.0,
                "min_return": min(returns) if returns else 0.0,
                "max_return": max(returns) if returns else 0.0,
            }

        signal_review_rows = [row for row in detail_rows if row.get("status") != "无信号"]
        pushed_rows = [row for row in signal_review_rows if row.get("has_buy_signal")]
        not_pushed_rows = [row for row in signal_review_rows if not row.get("has_buy_signal")]
        no_push_reason_counter = {}
        blocker_tag_counter = {}
        for row in not_pushed_rows:
            reason = str(row.get("not_pushed_reason", "") or "未触发有效买点")
            no_push_reason_counter[reason] = no_push_reason_counter.get(reason, 0) + 1
            blocker_tag = str(row.get("blocker_tag", "") or "unclassified")
            blocker_tag_counter[blocker_tag] = blocker_tag_counter.get(blocker_tag, 0) + 1
        no_push_reason_rows = sorted(
            [{"reason": key, "count": value} for key, value in no_push_reason_counter.items()],
            key=lambda item: (-int(item["count"]), item["reason"]),
        )
        blocker_tag_rows = sorted(
            [{"tag": key, "label": blocker_tag_to_label(key), "count": value} for key, value in blocker_tag_counter.items()],
            key=lambda item: (-int(item["count"]), item["label"]),
        )

        report = {
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "latest_trade_date": latest_trade_date,
            "lookback_trade_days": int(trade_days),
            "hold_days": hold_days,
            "trade_dates": recent_dates,
            "signal_days": len(signal_dates),
            "signal_count": sum(1 for row in detail_rows if row["status"] != "无信号"),
            "completed_count": len(completed_returns),
            "pending_count": pending_count,
            "completed_win_rate": win_rate,
            "completed_avg_return": avg_return,
            "weekly_summary": weekly_rows,
            "monthly_summary": monthly_rows,
            "signal_gap_stats": {
                "gap_count": len(signal_gaps),
                "avg_gap_trade_days": (
                    sum(item["gap_trade_days"] for item in signal_gaps) / len(signal_gaps)
                    if signal_gaps
                    else 0.0
                ),
                "max_gap_trade_days": max((item["gap_trade_days"] for item in signal_gaps), default=0),
                "gaps": signal_gaps,
            },
            "empty_streak_stats": {
                "max_empty_trade_days": max_empty_streak,
                "latest_empty_trade_days": latest_empty_streak,
            },
            "horizon_distribution": horizon_distribution,
            "intraday_review_summary": {
                "reviewed_signal_count": len(signal_review_rows),
                "buy_signal_count": len(pushed_rows),
                "buy_signal_ratio": (len(pushed_rows) / len(signal_review_rows)) if signal_review_rows else 0.0,
                "not_pushed_count": len(not_pushed_rows),
                "top_not_pushed_reasons": no_push_reason_rows[:5],
                "top_blocker_tags": blocker_tag_rows[:5],
            },
            "details": detail_rows,
        }

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        md_path = self.results_dir / f"secondary_launch_recent_tracking_{timestamp}.md"
        json_path = self.results_dir / f"secondary_launch_recent_tracking_{timestamp}.json"
        md_path.write_text(self._format_recent_tracking_report(report), encoding="utf-8")
        json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        report["report_markdown"] = str(md_path.relative_to(self.root))
        report["report_json"] = str(json_path.relative_to(self.root))
        return report

    def _format_recent_tracking_report(self, report: dict) -> str:
        lines = [
            "# 二次启动策略近几日真实信号跟踪报表",
            "",
            f"- 生成时间: {report.get('generated_at', '')}",
            f"- 最新交易日: {report.get('latest_trade_date', '')}",
            f"- 回看交易日数: {report.get('lookback_trade_days', 0)}",
            f"- 目标持有天数: {report.get('hold_days', 0)}",
            f"- 出现信号的交易日数: {report.get('signal_days', 0)}",
            f"- 信号总数: {report.get('signal_count', 0)}",
            f"- 已完成跟踪数: {report.get('completed_count', 0)}",
            f"- 跟踪中数量: {report.get('pending_count', 0)}",
            f"- 已完成胜率: {float(report.get('completed_win_rate', 0.0)):.2%}",
            f"- 已完成平均收益: {float(report.get('completed_avg_return', 0.0)):.2%}",
            "",
            "## 按周汇总",
            "",
            "| 周次 | 区间 | 信号日数 | 信号数 | 已完成 | 跟踪中 | 周胜率 | 周均收益 |",
            "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
        weekly_rows = report.get("weekly_summary", [])
        if weekly_rows:
            for row in weekly_rows:
                lines.append(
                    f"| {row.get('week_label', '')} | {row.get('start_date', '')} ~ {row.get('end_date', '')} | "
                    f"{row.get('signal_days', 0)} | {row.get('signal_count', 0)} | "
                    f"{row.get('completed_count', 0)} | {row.get('pending_count', 0)} | "
                    f"{float(row.get('win_rate', 0.0)):.2%} | {float(row.get('avg_return', 0.0)):.2%} |"
                )
        else:
            lines.append("| - | - | 0 | 0 | 0 | 0 | 0.00% | 0.00% |")

        lines.extend(
            [
                "",
                "## 按月汇总",
                "",
                "| 月份 | 区间 | 信号日数 | 信号数 | 已完成 | 跟踪中 | 月胜率 | 月均收益 |",
                "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
            ]
        )
        monthly_rows = report.get("monthly_summary", [])
        if monthly_rows:
            for row in monthly_rows:
                lines.append(
                    f"| {row.get('month_label', '')} | {row.get('start_date', '')} ~ {row.get('end_date', '')} | "
                    f"{row.get('signal_days', 0)} | {row.get('signal_count', 0)} | "
                    f"{row.get('completed_count', 0)} | {row.get('pending_count', 0)} | "
                    f"{float(row.get('win_rate', 0.0)):.2%} | {float(row.get('avg_return', 0.0)):.2%} |"
                )
        else:
            lines.append("| - | - | 0 | 0 | 0 | 0 | 0.00% | 0.00% |")

        gap_stats = report.get("signal_gap_stats", {})
        empty_stats = report.get("empty_streak_stats", {})
        lines.extend(
            [
                "",
                "## 节奏统计",
                "",
                f"- 信号间隔次数: {gap_stats.get('gap_count', 0)}",
                f"- 平均信号间隔(交易日): {float(gap_stats.get('avg_gap_trade_days', 0.0)):.2f}",
                f"- 最长信号间隔(交易日): {gap_stats.get('max_gap_trade_days', 0)}",
                f"- 最长连续空窗(交易日): {empty_stats.get('max_empty_trade_days', 0)}",
                f"- 当前连续空窗(交易日): {empty_stats.get('latest_empty_trade_days', 0)}",
                "",
                "## 信号间隔明细",
                "",
            ]
        )
        gaps = gap_stats.get("gaps", [])
        if gaps:
            for item in gaps:
                lines.append(
                    f"- {item.get('from_date', '')} -> {item.get('to_date', '')}: "
                    f"间隔 {item.get('gap_trade_days', 0)} 个交易日"
                )
        else:
            lines.append("- 当前窗口内不足 2 次信号，暂无间隔样本")

        lines.extend([
            "",
            "## 信号后 T+1 / T+2 / T+3 分布",
            "",
            "| 周期 | 样本数 | 胜率 | 平均收益 | 最小收益 | 最大收益 |",
            "| --- | ---: | ---: | ---: | ---: | ---: |",
        ])
        horizon_distribution = report.get("horizon_distribution", {})
        for horizon_label in ("T+1", "T+2", "T+3"):
            item = horizon_distribution.get(horizon_label, {})
            lines.append(
                f"| {horizon_label} | {item.get('sample_count', 0)} | "
                f"{float(item.get('win_rate', 0.0)):.2%} | "
                f"{float(item.get('avg_return', 0.0)):.2%} | "
                f"{float(item.get('min_return', 0.0)):.2%} | "
                f"{float(item.get('max_return', 0.0)):.2%} |"
            )

        intraday_review_summary = report.get("intraday_review_summary", {}) or {}
        lines.extend([
            "",
            "## 盘中买点复盘统计",
            "",
            f"- 已复盘信号数: {int(intraday_review_summary.get('reviewed_signal_count', 0) or 0)}",
            f"- 出现买点数: {int(intraday_review_summary.get('buy_signal_count', 0) or 0)}",
            f"- 买点触发率: {float(intraday_review_summary.get('buy_signal_ratio', 0.0) or 0.0):.2%}",
            f"- 未触发数: {int(intraday_review_summary.get('not_pushed_count', 0) or 0)}",
            "",
            "### 未推送原因TOP",
            "",
            "| 原因 | 次数 |",
            "| --- | ---: |",
        ])
        top_not_pushed_reasons = intraday_review_summary.get("top_not_pushed_reasons", []) or []
        if top_not_pushed_reasons:
            for item in top_not_pushed_reasons:
                lines.append(f"| {item.get('reason', '-')} | {int(item.get('count', 0) or 0)} |")
        else:
            lines.append("| - | 0 |")

        lines.extend([
            "",
            "### 拦截标签TOP",
            "",
            "| 标签 | 次数 |",
            "| --- | ---: |",
        ])
        top_blocker_tags = intraday_review_summary.get("top_blocker_tags", []) or []
        if top_blocker_tags:
            for item in top_blocker_tags:
                lines.append(f"| {item.get('label', item.get('tag', '-'))} | {int(item.get('count', 0) or 0)} |")
        else:
            lines.append("| - | 0 |")

        lines.extend([
            "",
            "## 明细",
            "",
            "| 信号日 | 股票 | 名称 | 排名 | 状态 | 是否买点 | 类型 | 触发时间 | 推送原因 | 未推送原因 | 拦截标签 | 拦截说明 | 置信度 | 观察收益 | T+1 | T+2 | T+3 | 观察截止日 |",
            "| --- | --- | --- | ---: | --- | --- | --- | --- | --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | --- |",
        ])
        for row in report.get("details", []):
            ret = row.get("observed_return")
            ret_text = "-" if ret is None else f"{float(ret):.2%}"
            horizon_map = row.get("horizon_returns", {}) or {}
            t1 = horizon_map.get("T+1")
            t2 = horizon_map.get("T+2")
            t3 = horizon_map.get("T+3")
            t1_text = "-" if t1 is None else f"{float(t1):.2%}"
            t2_text = "-" if t2 is None else f"{float(t2):.2%}"
            t3_text = "-" if t3 is None else f"{float(t3):.2%}"
            buy_signal_text = "是" if row.get("has_buy_signal") else ("-" if row.get("status") == "无信号" else "否")
            confidence_text = "-" if row.get("status") == "无信号" else f"{float(row.get('confidence', 0.0) or 0.0):.2f}"
            lines.append(
                f"| {row.get('signal_date', '')} | {row.get('ts_code', '-') or '-'} | "
                f"{row.get('name', '-') or '-'} | {row.get('rank', '-') or '-'} | "
                f"{row.get('status', '')} | {buy_signal_text} | {row.get('signal_type', '-') or '-'} | "
                f"{row.get('trigger_time', '-') or '-'} | {row.get('push_reason', '-') or '-'} | "
                f"{row.get('not_pushed_reason', '-') or '-'} | {row.get('blocker_label', row.get('blocker_tag', '-')) or '-'} | "
                f"{row.get('blocker_detail', '-') or '-'} | {confidence_text} | "
                f"{ret_text} | {t1_text} | {t2_text} | {t3_text} | "
                f"{row.get('exit_date', '-') or '-'} |"
            )
        return "\n".join(lines) + "\n"

    def run_recent_tracking_report(self):
        trade_days_input = input("    回看最近多少个交易日(默认40): ").strip()
        trade_days = int(trade_days_input) if trade_days_input.isdigit() else 40
        print("    正在生成近几日真实信号跟踪报表...")
        report = self.generate_recent_signal_tracking_report(trade_days=trade_days)
        if not report:
            print("    未能生成跟踪报表，请先检查行情数据是否完整")
            return
        print(f"    回看区间交易日数: {report['lookback_trade_days']}")
        print(f"    出现信号交易日: {report['signal_days']}")
        print(f"    信号总数: {report['signal_count']}")
        print(f"    已完成: {report['completed_count']}")
        print(f"    跟踪中: {report['pending_count']}")
        print(f"    已完成胜率: {float(report['completed_win_rate']):.2%}")
        print(f"    已完成平均收益: {float(report['completed_avg_return']):.2%}")
        print(f"    跟踪报表(MD): {report['report_markdown']}")
        print(f"    跟踪数据(JSON): {report['report_json']}")

    def show_latest_tracking_report(self):
        reports = sorted(self.results_dir.glob("secondary_launch_recent_tracking_*.md"), reverse=True)
        if not reports:
            print("    暂无近几日真实信号跟踪报表，请先生成")
            return
        latest = reports[0]
        print(f"    最新跟踪报表: results/{latest.name}")
        print("    --------------------------------------------------")
        content = latest.read_text(encoding="utf-8").splitlines()
        for line in content[:40]:
            print(f"    {line}")
        if len(content) > 40:
            print("    ...")

    def show_persisted_history(self, limit: int = 20):
        rows = self.db.query(
            """
            SELECT trade_date, ts_code, name, rank, rs20, drawdown_from_peak, strategy_label
            FROM secondary_launch_selection_history
            ORDER BY trade_date DESC, rank ASC
            LIMIT ?
            """,
            (int(limit),),
        )
        if not rows:
            print("    暂无二次启动策略落库历史")
            return
        print(f"\n    最近 {len(rows)} 条二次启动策略落库记录:")
        for row in rows:
            print(
                f"    {row['trade_date']} #{int(row.get('rank', 0) or 0)} "
                f"{row.get('ts_code', '')} {row.get('name', '')} "
                f"RS20={float(row.get('rs20', 0.0) or 0.0):.3f} "
                f"回撤={float(row.get('drawdown_from_peak', 0.0) or 0.0):.2%}"
            )

    def run_pipeline(self):
        print("\n    正在运行完整流水线...")
        script = self.root / "tools" / "run_secondary_launch_pipeline.py"
        result = subprocess.run(
            [sys.executable, str(script)],
            cwd=str(self.root),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="ignore",
        )
        if result.returncode != 0:
            print("    流水线运行失败")
            if result.stderr.strip():
                print(f"    错误信息: {result.stderr.strip()}")
            return

        print("    流水线运行完成")
        if result.stdout.strip():
            for line in result.stdout.strip().splitlines()[-6:]:
                print(f"    {line}")
        print("    报告文件: results/secondary_launch_pipeline_report.md")

    def show_latest_summary(self):
        summary_path = self.results_dir / "secondary_launch_summary.json"
        if not summary_path.exists():
            print("    尚无回测摘要，请先运行完整流水线")
            return

        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        in_sample = summary.get("in_sample_metrics", {})
        oos = summary.get("oos_metrics", {})
        validation = summary.get("validation", {})

        print("\n    ================= 最新回测摘要 =================")
        print(f"    策略: {summary.get('strategy', '')}")
        print(f"    样本内: {' ~ '.join(summary.get('in_sample_period', []))}")
        print(f"    样本外: {' ~ '.join(summary.get('oos_period', []))}")
        print(f"    样本内交易数: {in_sample.get('total_trades', 0)}")
        print(f"    样本内胜率: {float(in_sample.get('win_rate', 0.0)):.2%}")
        print(f"    样本内年化: {float(in_sample.get('annual_return', 0.0)):.2%}")
        print(f"    样本外交易数: {oos.get('total_trades', 0)}")
        print(f"    样本外胜率: {float(oos.get('win_rate', 0.0)):.2%}")
        print(f"    样本外年化: {float(oos.get('annual_return', 0.0)):.2%}")
        print(f"    样本外最大回撤: {float(oos.get('max_drawdown', 0.0)):.2%}")
        print(f"    验证结论: {'通过' if validation.get('passed') else '未通过'}")
        print("    =================================================")

    def show_historical_signals(self):
        default_start = str(self.config.get("stock_selection.secondary_launch.backtest_oos_start", "20260301"))
        default_end = str(self.config.get("stock_selection.secondary_launch.backtest_oos_end", "20260327"))
        start_date = input(f"    开始日期(YYYYMMDD，默认{default_start}): ").strip() or default_start
        end_date = input(f"    结束日期(YYYYMMDD，默认{default_end}): ").strip() or default_end

        _, backtester = self._build_strategy()
        data = backtester.load_data(start_date, end_date, warmup_days=60, forward_days=10)
        features = backtester.strategy.prepare_features(data["daily"], data["basic"])
        signals = backtester.strategy.generate_signals(features)
        if signals.empty:
            print("    指定区间无历史信号")
            return

        signals["signal_date"] = pd.to_datetime(signals["signal_date"])
        signals = signals[
            (signals["signal_date"] >= pd.Timestamp(start_date))
            & (signals["signal_date"] <= pd.Timestamp(end_date))
        ].copy()
        if signals.empty:
            print("    指定区间无历史信号")
            return

        print(f"\n    区间内共 {len(signals)} 条信号，展示最近10条:")
        for _, row in signals.tail(10).iterrows():
            print(
                f"    {row['signal_date'].strftime('%Y-%m-%d')} "
                f"{row['ts_code']} {row['name']} "
                f"Rank={int(row['rank'])} RS20={float(row['rs20']):.3f}"
            )

    def run_daily_selection(self):
        trade_date = input("    交易日(YYYYMMDD，回车默认最新交易日): ").strip()
        if not trade_date:
            trade_date = self.db.get_latest_trade_date("stock_daily")
        if not trade_date:
            print("    未找到有效交易日")
            return

        results = self.get_daily_selection(trade_date)
        if not results:
            print("    当日无候选股票")
            return

        self.persist_daily_selection(trade_date, results)
        synced_count = self.sync_to_candidate_pool(trade_date, results)

        print(f"\n    {trade_date} 候选股票（前{len(results)}只）:")
        for idx, row in enumerate(results, 1):
            print(
                f"    {idx}. {row['ts_code']} {row['name']} "
                f"RS20={float(row['rs20']):.3f} "
                f"回撤={float(row['drawdown_from_peak']):.2%}"
            )
        print(f"    已同步到候选池: {synced_count}只")
