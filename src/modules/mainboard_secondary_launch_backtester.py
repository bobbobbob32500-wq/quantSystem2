# -*- coding: utf-8 -*-
"""
沪深主板强势回调缩量二次启动策略回测器（去集合竞价过滤版）
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, List

import numpy as np
import pandas as pd

from src.core.database import DatabaseManager
from src.modules.mainboard_secondary_launch_strategy import (
    MainboardSecondaryLaunchStrategy,
    StrategyParams,
)


@dataclass
class CostConfig:
    buy_fee_rate: float = 0.0003
    sell_fee_rate: float = 0.0003
    stamp_tax_rate: float = 0.0005
    transfer_fee_rate: float = 0.00001
    slippage_rate: float = 0.001


class MainboardSecondaryLaunchBacktester:
    """策略开发全流程中的回测与验证模块"""

    def __init__(
        self,
        db: DatabaseManager,
        strategy: MainboardSecondaryLaunchStrategy,
        cost: CostConfig | None = None,
    ):
        self.db = db
        self.strategy = strategy
        self.cost = cost or CostConfig()

    @staticmethod
    def _shift_date(date_str: str, days: int) -> str:
        base = datetime.strptime(str(date_str), "%Y%m%d")
        return (base + timedelta(days=days)).strftime("%Y%m%d")

    def load_data(
        self,
        start_date: str,
        end_date: str,
        warmup_days: int = 60,
        forward_days: int = 10,
    ) -> Dict[str, pd.DataFrame]:
        query_start = self._shift_date(start_date, -warmup_days)
        query_end = self._shift_date(end_date, forward_days)
        sql_daily = """
        SELECT ts_code, trade_date, open, close, high, low, vol, amount, pct_chg
        FROM stock_daily
        WHERE trade_date >= ? AND trade_date <= ?
        ORDER BY ts_code, trade_date
        """
        sql_basic = """
        SELECT ts_code, name, industry, list_date
        FROM stock_basic
        """
        daily = pd.DataFrame(self.db.query(sql_daily, (query_start, query_end)))
        basic = pd.DataFrame(self.db.query(sql_basic))
        return {"daily": daily, "basic": basic}

    def run_backtest(self, start_date: str, end_date: str, hold_days: int = 5) -> Dict:
        data = self.load_data(
            start_date=start_date,
            end_date=end_date,
            warmup_days=max(60, hold_days * 3),
            forward_days=max(10, hold_days * 3),
        )
        daily, basic = data["daily"], data["basic"]
        if daily.empty or basic.empty:
            return {"error": "insufficient_data"}

        features = self.strategy.prepare_features(daily, basic)
        signals = self.strategy.generate_signals(features)
        return self._build_backtest_result(features, signals, start_date, end_date, hold_days)

    def _build_backtest_result(
        self,
        features: pd.DataFrame,
        signals: pd.DataFrame,
        start_date: str,
        end_date: str,
        hold_days: int,
    ) -> Dict:
        window_start = pd.Timestamp(datetime.strptime(str(start_date), "%Y%m%d"))
        window_end = pd.Timestamp(datetime.strptime(str(end_date), "%Y%m%d"))
        if not signals.empty:
            signals["signal_date"] = pd.to_datetime(signals["signal_date"])
            signals = signals[
                (signals["signal_date"] >= window_start)
                & (signals["signal_date"] <= window_end)
            ].copy()
        if signals.empty:
            return {
                "signals": signals,
                "trades": pd.DataFrame(),
                "metrics": {
                    "total_trades": 0,
                    "win_rate": 0.0,
                    "annual_return": 0.0,
                    "sharpe_ratio": 0.0,
                    "max_drawdown": 0.0,
                    "total_return": 0.0,
                },
            }

        trade_df = self._simulate_trades(features, signals, hold_days)
        metrics = self._compute_metrics(trade_df)

        # 风险评估：按市场状态切片（用上证指数5日收益区分）
        regime = self._evaluate_regime_performance(features, trade_df)
        metrics.update(regime)

        return {
            "signals": signals,
            "trades": trade_df,
            "metrics": metrics,
        }

    def _simulate_trades(
        self,
        features: pd.DataFrame,
        signals: pd.DataFrame,
        hold_days: int,
    ) -> pd.DataFrame:
        px = features[["ts_code", "trade_date", "open", "close"]].copy()
        px["trade_date"] = pd.to_datetime(px["trade_date"])
        px = px.sort_values(["ts_code", "trade_date"]).reset_index(drop=True)
        price_map = {code: sub.reset_index(drop=True) for code, sub in px.groupby("ts_code")}

        trades: List[Dict] = []
        cost_rate = (
            self.cost.buy_fee_rate
            + self.cost.sell_fee_rate
            + self.cost.transfer_fee_rate * 2
            + self.cost.stamp_tax_rate
        )
        for _, sig in signals.iterrows():
            code = sig["ts_code"]
            sdate = pd.Timestamp(sig["signal_date"])
            s = price_map.get(code)
            if s is None or s.empty:
                continue
            s = s[s["trade_date"] >= sdate]
            if len(s) < hold_days + 1:
                continue

            entry = s.iloc[0]
            exit_ = s.iloc[hold_days]

            buy_price = float(entry["open"]) * (1.0 + self.cost.slippage_rate)
            sell_price = float(exit_["close"]) * (1.0 - self.cost.slippage_rate)
            gross_ret = sell_price / buy_price - 1.0
            net_ret = gross_ret - cost_rate

            trades.append(
                {
                    "signal_date": sdate,
                    "ts_code": code,
                    "entry_date": entry["trade_date"],
                    "exit_date": exit_["trade_date"],
                    "entry_price": buy_price,
                    "exit_price": sell_price,
                    "gross_ret": gross_ret,
                    "net_ret": net_ret,
                    "hold_days": hold_days,
                }
            )
        return pd.DataFrame(trades)

    def _compute_metrics(self, trade_df: pd.DataFrame) -> Dict[str, float]:
        if trade_df.empty:
            return {
                "total_trades": 0,
                "total_signal_days": 0,
                "win_rate": 0.0,
                "day_win_rate": 0.0,
                "annual_return": 0.0,
                "sharpe_ratio": 0.0,
                "max_drawdown": 0.0,
                "total_return": 0.0,
                "profit_factor": 0.0,
            }

        ret = trade_df["net_ret"].astype(float)
        win_rate = float((ret > 0).mean())
        avg = float(ret.mean())
        std = float(ret.std(ddof=1)) if len(ret) > 1 else 0.0

        day_ret = (
            trade_df.groupby("signal_date", as_index=True)["net_ret"]
            .mean()
            .sort_index()
            .astype(float)
        )
        day_win_rate = float((day_ret > 0).mean()) if len(day_ret) else 0.0
        day_avg = float(day_ret.mean()) if len(day_ret) else 0.0
        day_std = float(day_ret.std(ddof=1)) if len(day_ret) > 1 else 0.0

        signal_days = len(day_ret)
        if signal_days <= 1:
            annual = float(day_ret.iloc[0]) if signal_days == 1 else 0.0
        else:
            span_days = max(1, int((day_ret.index.max() - day_ret.index.min()).days))
            annual = (1.0 + float((1.0 + day_ret).cumprod().iloc[-1] - 1.0)) ** (252.0 / span_days) - 1.0
        sharpe = (day_avg / day_std * np.sqrt(252.0)) if day_std > 1e-12 else 0.0

        curve = (1.0 + day_ret).cumprod()
        running_max = curve.cummax()
        dd = (curve / running_max - 1.0).min()
        total = float(curve.iloc[-1] - 1.0)
        gross_profit = float(ret[ret > 0].sum())
        gross_loss = float(-ret[ret < 0].sum())
        profit_factor = (gross_profit / gross_loss) if gross_loss > 1e-12 else 0.0

        return {
            "total_trades": int(len(ret)),
            "total_signal_days": int(len(day_ret)),
            "win_rate": win_rate,
            "day_win_rate": day_win_rate,
            "annual_return": float(annual),
            "sharpe_ratio": float(sharpe),
            "max_drawdown": float(dd),
            "total_return": total,
            "avg_return": avg,
            "std_return": std,
            "avg_day_return": day_avg,
            "std_day_return": day_std,
            "profit_factor": float(profit_factor),
        }

    def _evaluate_regime_performance(self, features: pd.DataFrame, trade_df: pd.DataFrame) -> Dict[str, float]:
        """简单风险评估：按指数5日动量划分牛/震荡/弱势环境"""
        if trade_df.empty:
            return {
                "regime_bull_avg": 0.0,
                "regime_sideways_avg": 0.0,
                "regime_bear_avg": 0.0,
            }

        idx = features[features["ts_code"] == "000001.SH"][["trade_date", "close"]].copy()
        if idx.empty:
            return {
                "regime_bull_avg": 0.0,
                "regime_sideways_avg": 0.0,
                "regime_bear_avg": 0.0,
            }

        idx = idx.sort_values("trade_date")
        idx["trade_date"] = pd.to_datetime(idx["trade_date"])
        idx["ret5"] = idx["close"] / idx["close"].shift(5) - 1.0

        m = trade_df.merge(idx[["trade_date", "ret5"]], left_on="signal_date", right_on="trade_date", how="left")
        bull = m[m["ret5"] >= 0.02]["net_ret"]
        side = m[(m["ret5"] > -0.02) & (m["ret5"] < 0.02)]["net_ret"]
        bear = m[m["ret5"] <= -0.02]["net_ret"]

        return {
            "regime_bull_avg": float(bull.mean()) if len(bull) else 0.0,
            "regime_sideways_avg": float(side.mean()) if len(side) else 0.0,
            "regime_bear_avg": float(bear.mean()) if len(bear) else 0.0,
        }

    def grid_search(self, start_date: str, end_date: str, hold_days: int = 5) -> pd.DataFrame:
        """参数网格优化"""
        data = self.load_data(
            start_date=start_date,
            end_date=end_date,
            warmup_days=max(60, hold_days * 3),
            forward_days=max(10, hold_days * 3),
        )
        if data["daily"].empty or data["basic"].empty:
            return pd.DataFrame()

        base_features = self.strategy.prepare_features(data["daily"], data["basic"])
        signal_frame = self.strategy.build_signal_frame(base_features)
        results = []
        drawdown_ranges = [(0.02, 0.06), (0.02, 0.08), (0.03, 0.08), (0.03, 0.10)]
        vol_ratios = [0.60, 0.70, 0.75, 0.80]
        day_windows = [(2, 4), (2, 5), (2, 6), (3, 5)]
        hold_days_list = [2, 3, 4, 5]
        limit_up_windows = [(1, 1), (1, 2)]
        picks_per_day_list = [2, 3, 4]

        for hold_days_candidate in hold_days_list:
            for dd_min, dd_max in drawdown_ranges:
                for vr in vol_ratios:
                    for dmin, dmax in day_windows:
                        for up_min, up_max in limit_up_windows:
                            for picks_per_day in picks_per_day_list:
                                p = StrategyParams(
                                    drawdown_min=dd_min,
                                    drawdown_max=dd_max,
                                    vol_shrink_ratio=vr,
                                    last_limit_up_days_min=dmin,
                                    last_limit_up_days_max=dmax,
                                    limit_up_count_10_min=up_min,
                                    limit_up_count_10_max=up_max,
                                    picks_per_day=picks_per_day,
                                    max_candidates=max(10, picks_per_day * 3),
                                )
                                strat = MainboardSecondaryLaunchStrategy(p)
                                signals = strat.generate_signals_from_frame(signal_frame)
                                out = self._build_backtest_result(
                                    base_features,
                                    signals,
                                    start_date,
                                    end_date,
                                    hold_days_candidate,
                                )
                                m = out["metrics"]
                                results.append(
                                    {
                                        "hold_days": hold_days_candidate,
                                        "drawdown_min": dd_min,
                                        "drawdown_max": dd_max,
                                        "vol_shrink_ratio": vr,
                                        "days_min": dmin,
                                        "days_max": dmax,
                                        "limit_up_count_10_min": up_min,
                                        "limit_up_count_10_max": up_max,
                                        "picks_per_day": picks_per_day,
                                        "total_trades": m.get("total_trades", 0),
                                        "total_signal_days": m.get("total_signal_days", 0),
                                        "win_rate": m.get("win_rate", 0.0),
                                        "day_win_rate": m.get("day_win_rate", 0.0),
                                        "annual_return": m.get("annual_return", 0.0),
                                        "sharpe_ratio": m.get("sharpe_ratio", 0.0),
                                        "max_drawdown": m.get("max_drawdown", 0.0),
                                        "total_return": m.get("total_return", 0.0),
                                        "avg_return": m.get("avg_return", 0.0),
                                        "profit_factor": m.get("profit_factor", 0.0),
                                    }
                                )

        df = pd.DataFrame(results)
        if not df.empty:
            df["score"] = (
                df["win_rate"] * 0.40
                + df["day_win_rate"] * 0.25
                + df["avg_return"] * 1.50
                + df["profit_factor"].clip(upper=3.0) * 0.08
                + df["sharpe_ratio"] * 0.05
                - df["max_drawdown"].abs() * 0.12
            )
            df = df[df["total_trades"] >= 20].copy()
            df = df.sort_values(
                ["score", "win_rate", "day_win_rate", "avg_return", "total_trades"],
                ascending=[False, False, False, False, False],
            ).reset_index(drop=True)
        return df
