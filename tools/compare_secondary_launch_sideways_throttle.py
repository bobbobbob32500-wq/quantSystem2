# -*- coding: utf-8 -*-
"""
二次启动策略：震荡市限流方案对比脚本

输出：
- 基线（关闭震荡市限流）vs 限流方案（使用配置）在同一区间的核心指标
- OOS 按档次 / 市场状态分组结果
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, replace
from datetime import datetime
from pathlib import Path
import sys

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.core.config import ConfigManager
from src.core.database import DatabaseManager
from src.modules.mainboard_secondary_launch_strategy import MainboardSecondaryLaunchStrategy
from src.modules.mainboard_secondary_launch_backtester import MainboardSecondaryLaunchBacktester
from tools.eval_secondary_launch_oos_round2 import (
    _load_params_from_config,
    _build_cost,
    _build_oos_group_tables,
    _fmt_pct,
)


def _run_case(
    cfg: ConfigManager,
    db: DatabaseManager,
    hold_days: int,
    is_start: str,
    is_end: str,
    oos_start: str,
    oos_end: str,
    throttle_on: bool,
    throttle_low: float,
    throttle_high: float,
    throttle_boost: float,
    throttle_max_picks: int,
):
    params = _load_params_from_config(cfg)
    if not throttle_on:
        # 基线：关闭“震荡市额外限流”，仅保留原弱市闸门
        params = replace(
            params,
            sideways_market_min_score_boost=0.0,
            sideways_market_max_picks=int(params.picks_per_day),
        )
    else:
        params = replace(
            params,
            sideways_market_ret5_low=float(throttle_low),
            sideways_market_ret5_high=float(throttle_high),
            sideways_market_min_score_boost=float(throttle_boost),
            sideways_market_max_picks=int(throttle_max_picks),
        )
    strat = MainboardSecondaryLaunchStrategy(params)
    bt = MainboardSecondaryLaunchBacktester(db=db, strategy=strat, cost=_build_cost(cfg))

    is_out = bt.run_backtest(is_start, is_end, hold_days=hold_days)
    oos_out = bt.run_backtest(oos_start, oos_end, hold_days=hold_days)
    oos_data = bt.load_data(
        start_date=oos_start,
        end_date=oos_end,
        warmup_days=max(60, hold_days * 3),
        forward_days=max(10, hold_days * 3),
    )
    oos_features = strat.prepare_features(oos_data["daily"], oos_data["basic"]) if not oos_data["daily"].empty else pd.DataFrame()
    groups = _build_oos_group_tables(
        oos_signals=oos_out.get("signals", pd.DataFrame()),
        oos_trades=oos_out.get("trades", pd.DataFrame()),
        oos_features=oos_features,
    )
    return {
        "params": asdict(params),
        "is_metrics": is_out.get("metrics", {}),
        "oos_metrics": oos_out.get("metrics", {}),
        "oos_groups": groups,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--is-start", default="20250901")
    ap.add_argument("--is-end", default="20260228")
    ap.add_argument("--oos-start", default="20260301")
    ap.add_argument("--oos-end", default="20260414")
    ap.add_argument("--hold-days", default=None)
    ap.add_argument("--throttle-low", type=float, default=-0.015)
    ap.add_argument("--throttle-high", type=float, default=0.015)
    ap.add_argument("--throttle-boost", type=float, default=10.0)
    ap.add_argument("--throttle-max-picks", type=int, default=1)
    args = ap.parse_args()

    cfg = ConfigManager()
    db = DatabaseManager(cfg)
    hold_days = int(args.hold_days) if args.hold_days is not None else int(cfg.get("stock_selection.secondary_launch.hold_days", 2))

    baseline = _run_case(
        cfg, db, hold_days, args.is_start, args.is_end, args.oos_start, args.oos_end, False,
        args.throttle_low, args.throttle_high, args.throttle_boost, args.throttle_max_picks
    )
    throttle = _run_case(
        cfg, db, hold_days, args.is_start, args.is_end, args.oos_start, args.oos_end, True,
        args.throttle_low, args.throttle_high, args.throttle_boost, args.throttle_max_picks
    )

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = ROOT / "data" / "reports"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_json = out_dir / f"secondary_launch_sideways_throttle_compare_{ts}.json"
    out_md = out_dir / f"secondary_launch_sideways_throttle_compare_{ts}.md"

    payload = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "is_range": [args.is_start, args.is_end],
        "oos_range": [args.oos_start, args.oos_end],
        "hold_days": hold_days,
        "baseline": baseline,
        "throttle": throttle,
    }
    out_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    b = baseline["oos_metrics"]
    t = throttle["oos_metrics"]
    lines = [
        "# 二次启动策略：震荡市限流参数对比",
        "",
        f"- 生成时间：{payload['generated_at']}",
        f"- IS：{args.is_start} ~ {args.is_end}",
        f"- OOS：{args.oos_start} ~ {args.oos_end}",
        f"- 持有天数：{hold_days}",
        "",
        "## OOS 核心对比",
        "",
        "| 方案 | 交易数 | 信号日数 | 胜率 | 平均单笔收益 | 盈亏比 | 总收益 | 最大回撤 |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        f"| 基线（无震荡限流） | {b.get('total_trades', 0)} | {b.get('total_signal_days', 0)} | {_fmt_pct(b.get('win_rate', 0.0))} | {_fmt_pct(b.get('avg_return', 0.0))} | {float(b.get('profit_factor', 0.0) or 0.0):.2f} | {_fmt_pct(b.get('total_return', 0.0))} | {_fmt_pct(b.get('max_drawdown', 0.0))} |",
        f"| 震荡限流方案 | {t.get('total_trades', 0)} | {t.get('total_signal_days', 0)} | {_fmt_pct(t.get('win_rate', 0.0))} | {_fmt_pct(t.get('avg_return', 0.0))} | {float(t.get('profit_factor', 0.0) or 0.0):.2f} | {_fmt_pct(t.get('total_return', 0.0))} | {_fmt_pct(t.get('max_drawdown', 0.0))} |",
        "",
        "## 震荡市（sideways）分组对比（OOS）",
        "",
        "| 方案 | 交易数 | 胜率 | 平均收益 | 中位收益 | 盈亏比 | 总收益 |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    def _pick_sideways(rows: list[dict]) -> dict:
        for r in rows:
            if str(r.get("market_regime", "")) == "sideways":
                return r
        return {}
    bs = _pick_sideways(baseline["oos_groups"].get("by_regime", []))
    tsw = _pick_sideways(throttle["oos_groups"].get("by_regime", []))
    lines.append(
        f"| 基线（无震荡限流） | {int(bs.get('trades', 0))} | {_fmt_pct(bs.get('win_rate', 0.0))} | {_fmt_pct(bs.get('avg_return', 0.0))} | {_fmt_pct(bs.get('median_return', 0.0))} | {float(bs.get('profit_factor', 0.0) or 0.0):.2f} | {_fmt_pct(bs.get('total_return', 0.0))} |"
    )
    lines.append(
        f"| 震荡限流方案 | {int(tsw.get('trades', 0))} | {_fmt_pct(tsw.get('win_rate', 0.0))} | {_fmt_pct(tsw.get('avg_return', 0.0))} | {_fmt_pct(tsw.get('median_return', 0.0))} | {float(tsw.get('profit_factor', 0.0) or 0.0):.2f} | {_fmt_pct(tsw.get('total_return', 0.0))} |"
    )

    lines.extend(
        [
            "",
            "## 限流方案参数（当前配置）",
            f"- sideways_market_ret5_low: {throttle['params'].get('sideways_market_ret5_low')}",
            f"- sideways_market_ret5_high: {throttle['params'].get('sideways_market_ret5_high')}",
            f"- sideways_market_min_score_boost: {throttle['params'].get('sideways_market_min_score_boost')}",
            f"- sideways_market_max_picks: {throttle['params'].get('sideways_market_max_picks')}",
            "",
            "## 输出文件",
            f"- `{out_json.as_posix()}`",
            f"- `{out_md.as_posix()}`",
        ]
    )
    out_md.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

