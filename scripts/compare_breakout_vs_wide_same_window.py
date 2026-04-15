# -*- coding: utf-8 -*-
"""
突破策略（config 中 params_preset）与宽进突破（wide_pool_strict_entry_v2）
在同一信号日窗口下的日线回测对比。

口径与 scripts/run_unified_halfyear_strategy_comparison.py 中突破类一致：
  T 日盘后选股 → 仅当 T+1 突破+量能确认后以触发价买入 → 统计 ret_t1~t5。
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Tuple

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    sys.stdout.reconfigure(line_buffering=True)
except Exception:
    pass

FORWARD_RESERVE = 6


def _load_qfp():
    path = ROOT / "scripts" / "qlib_full_optimize_pipeline.py"
    spec = importlib.util.spec_from_file_location("qfp_cmp_br", path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def _stats_series(s: pd.Series) -> Dict[str, float]:
    v = pd.to_numeric(s, errors="coerce").dropna()
    if v.empty:
        return {
            "n": 0,
            "win_rate": float("nan"),
            "mean": float("nan"),
            "median": float("nan"),
            "std": float("nan"),
            "pf": float("nan"),
        }
    n = int(len(v))
    win_rate = float((v > 0).mean())
    mean = float(v.mean())
    median = float(v.median())
    std = float(v.std())
    gw = float(v[v > 0].sum())
    gl = float(-v[v < 0].sum())
    pf = gw / gl if gl > 1e-12 else 0.0
    return {"n": n, "win_rate": win_rate, "mean": mean, "median": median, "std": std, "pf": pf}


def _resolve_signal_window(
    all_dates: List[str], warmup_skip: int, trading_days: int, forward_reserve: int
) -> Tuple[List[str], str, str]:
    if len(all_dates) <= warmup_skip + forward_reserve + 10:
        return [], "", ""
    capable = all_dates[warmup_skip : -forward_reserve]
    if len(capable) < trading_days:
        trading_days = len(capable)
    if trading_days <= 0:
        return [], "", ""
    signal_dates = capable[-trading_days:]
    note = (
        f"取可回测段最后 {len(signal_dates)} 个交易日；"
        f"全库日线自 {all_dates[0]} 至 {all_dates[-1]}"
    )
    return signal_dates, note, f"{signal_dates[0]}_{signal_dates[-1]}"


def main() -> None:
    parser = argparse.ArgumentParser(description="突破 vs 宽进突破 同窗口对比回测")
    parser.add_argument(
        "--trading-days",
        type=int,
        default=126,
        help="信号日窗口长度（交易日），默认 126",
    )
    args = parser.parse_args()

    from src.core.config import ConfigManager
    from src.core.database import DatabaseManager
    from src.modules.breakout_backtest_runner import run_breakout_backtest_loop, summarize_ret_column
    from src.modules.breakout_strategy import (
        BreakoutStrategy,
        build_breakout_strategy_from_config,
        get_breakout_params_for_backtest,
        resolve_breakout_preset_from_config,
    )

    qfp = _load_qfp()
    config = ConfigManager()
    db = DatabaseManager(config)
    all_dates = qfp.load_trade_dates(db)

    if len(all_dates) >= 180:
        warmup_skip = 125
        use_ma120 = True
    elif len(all_dates) >= 75:
        warmup_skip = 65
        use_ma120 = False
    else:
        print("数据库交易日不足，无法回测", flush=True)
        sys.exit(1)

    signal_dates, window_note, window_tag = _resolve_signal_window(
        all_dates, warmup_skip, args.trading_days, FORWARD_RESERVE
    )
    if not signal_dates:
        print("无法构造信号窗口", flush=True)
        sys.exit(1)

    w0, w1 = signal_dates[0], signal_dates[-1]
    preset_std = resolve_breakout_preset_from_config(config)
    max_d = all_dates[-1]

    print("=" * 72, flush=True)
    print("  突破 vs 宽进突破 — 同窗口对比", flush=True)
    print("=" * 72, flush=True)
    print(f"  信号日: {w0} ~ {w1} （{len(signal_dates)} 日）", flush=True)
    print(f"  {window_note}", flush=True)
    print(f"  标准突破预设: {preset_std}；宽进: wide_pool_strict_entry_v2", flush=True)
    print(f"  MA120: {'开启' if use_ma120 else '降级'}", flush=True)

    strategy_std = build_breakout_strategy_from_config(db, config)
    raw, basic = strategy_std._load_data(max_d)
    # 两档预设下均线周期一致，特征表可共用，避免重复全市场因子计算
    feats = strategy_std._compute_features(raw, basic, max_d)

    df_std, _funnel_std, gate_std = run_breakout_backtest_loop(
        strategy_std, feats, all_dates, signal_dates, use_ma120, progress_every=0
    )

    params_wide = get_breakout_params_for_backtest("wide_pool_strict_entry_v2", use_ma120)
    strategy_wide = BreakoutStrategy(db=db, params=params_wide)
    df_wide, _funnel_wide, gate_wide = run_breakout_backtest_loop(
        strategy_wide, feats, all_dates, signal_dates, use_ma120, progress_every=0
    )

    horizons = [1, 2, 3, 4, 5]
    out: Dict[str, Any] = {
        "meta": {
            "generated_at": datetime.now().strftime("%Y%m%d_%H%M%S"),
            "signal_start": w0,
            "signal_end": w1,
            "signal_days": len(signal_dates),
            "breakout_preset": preset_std,
            "wide_preset": "wide_pool_strict_entry_v2",
            "use_ma120": use_ma120,
        },
        "breakout": {"gate": gate_std, "n_trades": int(len(df_std))},
        "wide_breakout": {"gate": gate_wide, "n_trades": int(len(df_wide))},
    }

    print("\n--- 成交笔数 / 闸门 ---", flush=True)
    print(f"  突破: {len(df_std)} 笔 | gate={gate_std}", flush=True)
    print(f"  宽进: {len(df_wide)} 笔 | gate={gate_wide}", flush=True)

    print("\n--- 单笔收益率（触发价，毛收益）---", flush=True)
    hdr = "| 持有 | 突破 n | 胜率 | 均值 | 中位数 | 标准差 | 盈亏比PF | 宽进 n | 胜率 | 均值 | 中位数 | 标准差 | 盈亏比PF |"
    sep = "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"
    print(hdr, flush=True)
    print(sep, flush=True)
    out["per_horizon"] = {}
    for h in horizons:
        col = f"ret_t{h}"
        s_std = _stats_series(df_std[col]) if not df_std.empty and col in df_std else _stats_series(pd.Series(dtype=float))
        s_wide = _stats_series(df_wide[col]) if not df_wide.empty and col in df_wide else _stats_series(pd.Series(dtype=float))
        out["per_horizon"][col] = {"breakout": s_std, "wide_breakout": s_wide}
        print(
            f"| T+{h} | {s_std['n']} | {s_std['win_rate']:.2%} | {s_std['mean']:.4%} | "
            f"{s_std['median']:.4%} | {s_std['std']:.4%} | {s_std['pf']:.3f} | "
            f"{s_wide['n']} | {s_wide['win_rate']:.2%} | {s_wide['mean']:.4%} | "
            f"{s_wide['median']:.4%} | {s_wide['std']:.4%} | {s_wide['pf']:.3f} |",
            flush=True,
        )

    print("\n--- 等权按 signal_date 组合（复利累计、最大回撤、日夏普年化）---", flush=True)
    print("| 策略 | T+3累计 | T+3回撤 | T+3夏普 | T+5累计 | T+5回撤 | T+5夏普 |", flush=True)
    print("| --- | ---: | ---: | ---: | ---: | ---: | ---: |", flush=True)
    for name, df in [("突破", df_std), ("宽进突破", df_wide)]:
        p3 = summarize_ret_column(df, "ret_t3")
        p5 = summarize_ret_column(df, "ret_t5")
        key = "breakout" if name == "突破" else "wide_breakout"
        out[key]["portfolio_ret_t3"] = p3
        out[key]["portfolio_ret_t5"] = p5
        print(
            f"| {name} | {p3.get('port_total_ret', float('nan')):.4%} | {p3.get('port_mdd', float('nan')):.4%} | "
            f"{p3.get('port_sharpe', float('nan')):.2f} | {p5.get('port_total_ret', float('nan')):.4%} | "
            f"{p5.get('port_mdd', float('nan')):.4%} | {p5.get('port_sharpe', float('nan')):.2f} |",
            flush=True,
        )

    rep_dir = ROOT / "data" / "reports"
    rep_dir.mkdir(parents=True, exist_ok=True)
    stamp = out["meta"]["generated_at"]
    json_path = rep_dir / f"breakout_vs_wide_breakout_{window_tag}_{stamp}.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2, default=str)
    print(f"\n  已写 JSON: {json_path}", flush=True)


if __name__ == "__main__":
    main()
