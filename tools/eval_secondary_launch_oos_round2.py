# -*- coding: utf-8 -*-
"""
二次启动策略：开展一轮样本外（OOS）评估

目标：
- 用“当前系统配置（含已集成的最优阈值/参数）”直接跑一段样本外区间
- 同时输出样本内（IS）与样本外（OOS）指标，便于观察泛化与漂移

说明：
- 这里使用日线回测器 `MainboardSecondaryLaunchBacktester` 的口径（开盘买入、T+N收盘卖出、含滑点与费率）
- 该评估不替代盘中分钟确认回测；它主要验证“选股侧参数/闸门”的样本外稳定性
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
import sys

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.core.config import ConfigManager
from src.core.database import DatabaseManager
from src.modules.mainboard_secondary_launch_strategy import StrategyParams, MainboardSecondaryLaunchStrategy
from src.modules.mainboard_secondary_launch_backtester import MainboardSecondaryLaunchBacktester, CostConfig


def _load_params_from_config(cfg: ConfigManager) -> StrategyParams:
    """尽量从配置加载参数，缺失则使用 StrategyParams 默认值。"""
    # 只显式覆盖配置里存在的字段，避免未来 StrategyParams 扩字段时漏配报错
    keys = [
        # 基础约束
        "min_list_days",
        "limit_up_threshold",
        "limit_down_threshold",
        "limit_up_count_10_min",
        "limit_up_count_10_max",
        "last_limit_up_days_min",
        "last_limit_up_days_max",
        "drawdown_min",
        "drawdown_max",
        "vol_shrink_ratio",
        "close_ma5_dev_max",
        "close_ma10_min_ratio",
        "min_amt_ma20",
        "max_amt_ma20",
        "min_price",
        "limit_up_amt_ratio_min",
        "limit_up_amt_ratio_max",
        "rs_lookback",
        "max_candidates",
        "picks_per_day",
        "min_score",
        "cooldown_days",
        # V4增强（若存在则覆盖）
        "risk_penalty_weight",
        "upper_shadow_penalty_threshold",
        "upper_shadow_penalty_weight",
        "high_volume_penalty_threshold",
        "high_volume_penalty_weight",
        "deep_negative_penalty_low",
        "deep_negative_penalty_high",
        "deep_negative_penalty_weight",
        # 分层阈值（用于提示与盘中分层一致）
        "direct_score_min",
        "direct_lgb_min",
        "semi_score_min",
        "semi_lgb_min",
        "direct_conf_min",
        "semi_conf_min",
        # 其它
        "second_pick_min_score",
        "second_pick_score_gap",
        "weak_market_ret5_threshold",
        "weak_market_min_score_boost",
        "weak_market_max_picks",
        "sideways_market_ret5_low",
        "sideways_market_ret5_high",
        "sideways_market_min_score_boost",
        "sideways_market_max_picks",
    ]
    base = StrategyParams()
    payload = {}
    for k in keys:
        v = cfg.get(f"stock_selection.secondary_launch.{k}", None)
        if v is None:
            continue
        payload[k] = v
    # 类型归一：StrategyParams 自身会校验/转换部分字段，这里保持轻量
    base_dict = base.__dict__.copy()
    base_dict.update(payload)
    return StrategyParams(**base_dict)


def _build_cost(cfg: ConfigManager) -> CostConfig:
    return CostConfig(
        buy_fee_rate=float(cfg.get("feedback.buy_fee_rate", 0.0003)),
        sell_fee_rate=float(cfg.get("feedback.sell_fee_rate", 0.0003)),
        stamp_tax_rate=float(cfg.get("feedback.stamp_tax_rate", 0.0005)),
        transfer_fee_rate=float(cfg.get("stock_selection.secondary_launch.transfer_fee_rate", 0.00001)),
        slippage_rate=float(cfg.get("feedback.buy_slippage", 0.001)),
    )


def _fmt_pct(x: float) -> str:
    try:
        return f"{float(x) * 100:.2f}%"
    except Exception:
        return "nan"


def _regime_bucket(ret5: float) -> str:
    try:
        v = float(ret5)
    except Exception:
        return "unknown"
    if v >= 0.02:
        return "bull"
    if v <= -0.02:
        return "bear"
    return "sideways"


def _group_metrics(df: pd.DataFrame, group_col: str) -> list[dict]:
    if df is None or df.empty or group_col not in df.columns or "net_ret" not in df.columns:
        return []

    rows = []
    for key, g in df.groupby(group_col, dropna=False):
        v = pd.to_numeric(g["net_ret"], errors="coerce").dropna()
        if v.empty:
            continue
        gross_profit = float(v[v > 0].sum())
        gross_loss = float(-v[v < 0].sum())
        rows.append(
            {
                group_col: str(key),
                "trades": int(len(v)),
                "win_rate": float((v > 0).mean()),
                "avg_return": float(v.mean()),
                "median_return": float(v.median()),
                "profit_factor": (gross_profit / gross_loss) if gross_loss > 1e-12 else 0.0,
                "total_return": float((1.0 + v).prod() - 1.0),
            }
        )
    rows = sorted(rows, key=lambda x: x["trades"], reverse=True)
    return rows


def _build_oos_group_tables(oos_signals: pd.DataFrame, oos_trades: pd.DataFrame, oos_features: pd.DataFrame) -> dict:
    if oos_trades is None or oos_trades.empty:
        return {"by_tier": [], "by_regime": [], "by_tier_regime": []}

    sig = oos_signals.copy() if oos_signals is not None else pd.DataFrame()
    trd = oos_trades.copy()
    trd["signal_date"] = pd.to_datetime(trd["signal_date"], errors="coerce")
    trd["ts_code"] = trd["ts_code"].astype(str)

    if not sig.empty:
        sig["signal_date"] = pd.to_datetime(sig["signal_date"], errors="coerce")
        sig["ts_code"] = sig["ts_code"].astype(str)
        keep_cols = ["signal_date", "ts_code"]
        if "execution_tier_hint" in sig.columns:
            keep_cols.append("execution_tier_hint")
        else:
            sig["execution_tier_hint"] = "confirm"
            keep_cols.append("execution_tier_hint")
        merged = trd.merge(sig[keep_cols], on=["signal_date", "ts_code"], how="left")
    else:
        merged = trd.copy()
        merged["execution_tier_hint"] = "unknown"

    idx = pd.DataFrame()
    if oos_features is not None and not oos_features.empty:
        idx = oos_features[oos_features["ts_code"] == "000001.SH"][["trade_date", "close"]].copy()
        if not idx.empty:
            idx = idx.sort_values("trade_date")
            idx["trade_date"] = pd.to_datetime(idx["trade_date"], errors="coerce")
            idx["ret5"] = pd.to_numeric(idx["close"], errors="coerce") / pd.to_numeric(idx["close"], errors="coerce").shift(5) - 1.0

    if not idx.empty:
        merged = merged.merge(idx[["trade_date", "ret5"]], left_on="signal_date", right_on="trade_date", how="left")
        merged["market_regime"] = merged["ret5"].map(_regime_bucket)
    else:
        merged["market_regime"] = "unknown"

    merged["execution_tier_hint"] = merged["execution_tier_hint"].fillna("unknown").astype(str)
    merged["tier_regime"] = merged["execution_tier_hint"].astype(str) + "|" + merged["market_regime"].astype(str)
    return {
        "by_tier": _group_metrics(merged, "execution_tier_hint"),
        "by_regime": _group_metrics(merged, "market_regime"),
        "by_tier_regime": _group_metrics(merged, "tier_regime"),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--is-start", default="20250901")
    ap.add_argument("--is-end", default="20260331")
    ap.add_argument("--oos-start", default="20260401")
    ap.add_argument("--oos-end", default="20260414")
    ap.add_argument("--hold-days", default=None, help="覆盖持有天数；留空则读配置 stock_selection.secondary_launch.hold_days")
    args = ap.parse_args()

    cfg = ConfigManager()
    db = DatabaseManager(cfg)
    params = _load_params_from_config(cfg)
    cost = _build_cost(cfg)

    hold_days = int(args.hold_days) if args.hold_days is not None else int(cfg.get("stock_selection.secondary_launch.hold_days", 2))
    strat = MainboardSecondaryLaunchStrategy(params)
    bt = MainboardSecondaryLaunchBacktester(db=db, strategy=strat, cost=cost)

    oos_data = bt.load_data(
        start_date=args.oos_start,
        end_date=args.oos_end,
        warmup_days=max(60, hold_days * 3),
        forward_days=max(10, hold_days * 3),
    )
    oos_features = strat.prepare_features(oos_data["daily"], oos_data["basic"]) if not oos_data["daily"].empty else pd.DataFrame()
    is_out = bt.run_backtest(args.is_start, args.is_end, hold_days=hold_days)
    oos_out = bt.run_backtest(args.oos_start, args.oos_end, hold_days=hold_days)
    oos_groups = _build_oos_group_tables(
        oos_signals=oos_out.get("signals", pd.DataFrame()),
        oos_trades=oos_out.get("trades", pd.DataFrame()),
        oos_features=oos_features,
    )

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = ROOT / "data" / "reports"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_json = out_dir / f"secondary_launch_oos_eval_round2_{stamp}.json"
    out_md = out_dir / f"secondary_launch_oos_eval_round2_{stamp}.md"

    payload = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "is_range": [args.is_start, args.is_end],
        "oos_range": [args.oos_start, args.oos_end],
        "hold_days": hold_days,
        "strategy_params": params.__dict__,
        "metrics": {
            "is": is_out.get("metrics", {}),
            "oos": oos_out.get("metrics", {}),
        },
        "oos_group_tables": oos_groups,
    }
    out_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    m_is = payload["metrics"]["is"] or {}
    m_oos = payload["metrics"]["oos"] or {}
    lines = [
        "# 二次启动策略：样本外（OOS）评估 Round2",
        "",
        f"- 生成时间：{payload['generated_at']}",
        f"- 样本内（IS）：{args.is_start} ~ {args.is_end}",
        f"- 样本外（OOS）：{args.oos_start} ~ {args.oos_end}",
        f"- 持有天数：{hold_days}",
        "",
        "## 关键指标对比（日线回测口径）",
        "",
        "| 区间 | 交易数 | 信号日数 | 胜率 | 日胜率 | 平均单笔收益 | 盈亏比 | 最大回撤 | 总收益 | 年化 | 夏普 |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        f"| IS | {m_is.get('total_trades', 0)} | {m_is.get('total_signal_days', 0)} | {_fmt_pct(m_is.get('win_rate', 0.0))} | {_fmt_pct(m_is.get('day_win_rate', 0.0))} | {_fmt_pct(m_is.get('avg_return', 0.0))} | {float(m_is.get('profit_factor', 0.0) or 0.0):.2f} | {_fmt_pct(m_is.get('max_drawdown', 0.0))} | {_fmt_pct(m_is.get('total_return', 0.0))} | {_fmt_pct(m_is.get('annual_return', 0.0))} | {float(m_is.get('sharpe_ratio', 0.0) or 0.0):.2f} |",
        f"| OOS | {m_oos.get('total_trades', 0)} | {m_oos.get('total_signal_days', 0)} | {_fmt_pct(m_oos.get('win_rate', 0.0))} | {_fmt_pct(m_oos.get('day_win_rate', 0.0))} | {_fmt_pct(m_oos.get('avg_return', 0.0))} | {float(m_oos.get('profit_factor', 0.0) or 0.0):.2f} | {_fmt_pct(m_oos.get('max_drawdown', 0.0))} | {_fmt_pct(m_oos.get('total_return', 0.0))} | {_fmt_pct(m_oos.get('annual_return', 0.0))} | {float(m_oos.get('sharpe_ratio', 0.0) or 0.0):.2f} |",
        "",
        "## OOS 分组表：按档次（execution_tier_hint）",
        "",
        "| 档次 | 交易数 | 胜率 | 平均收益 | 中位收益 | 盈亏比 | 总收益 |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for r in oos_groups.get("by_tier", []):
        lines.append(
            f"| {r.get('execution_tier_hint','unknown')} | {int(r.get('trades',0))} | {_fmt_pct(r.get('win_rate',0.0))} | {_fmt_pct(r.get('avg_return',0.0))} | {_fmt_pct(r.get('median_return',0.0))} | {float(r.get('profit_factor',0.0) or 0.0):.2f} | {_fmt_pct(r.get('total_return',0.0))} |"
        )
    lines.extend(
        [
            "",
            "## OOS 分组表：按市场状态（market_regime）",
            "",
            "| 市场状态 | 交易数 | 胜率 | 平均收益 | 中位收益 | 盈亏比 | 总收益 |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for r in oos_groups.get("by_regime", []):
        lines.append(
            f"| {r.get('market_regime','unknown')} | {int(r.get('trades',0))} | {_fmt_pct(r.get('win_rate',0.0))} | {_fmt_pct(r.get('avg_return',0.0))} | {_fmt_pct(r.get('median_return',0.0))} | {float(r.get('profit_factor',0.0) or 0.0):.2f} | {_fmt_pct(r.get('total_return',0.0))} |"
        )
    lines.extend(
        [
            "",
            "## OOS 分组表：档次 × 市场状态",
            "",
            "| 分组 | 交易数 | 胜率 | 平均收益 | 中位收益 | 盈亏比 | 总收益 |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for r in oos_groups.get("by_tier_regime", []):
        lines.append(
            f"| {r.get('tier_regime','unknown')} | {int(r.get('trades',0))} | {_fmt_pct(r.get('win_rate',0.0))} | {_fmt_pct(r.get('avg_return',0.0))} | {_fmt_pct(r.get('median_return',0.0))} | {float(r.get('profit_factor',0.0) or 0.0):.2f} | {_fmt_pct(r.get('total_return',0.0))} |"
        )
    lines.extend(
        [
            "",
        "## 市场状态切片（OOS）",
        "",
        f"- 牛市样本平均收益（ret5≥2%）：{_fmt_pct(m_oos.get('regime_bull_avg', 0.0))}",
        f"- 震荡样本平均收益（-2%<ret5<2%）：{_fmt_pct(m_oos.get('regime_sideways_avg', 0.0))}",
        f"- 弱市样本平均收益（ret5≤-2%）：{_fmt_pct(m_oos.get('regime_bear_avg', 0.0))}",
        "",
        "## 输出文件",
        f"- `{out_json.as_posix()}`",
        f"- `{out_md.as_posix()}`",
        "",
        "## 备注",
        "- 本评估使用“当前配置参数”直接跑 OOS，不做再寻优。",
        "- 若 OOS 交易数偏少，建议拉长 OOS 区间或采用多折滚动 OOS（按月/按季度）。",
    ])
    out_md.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

