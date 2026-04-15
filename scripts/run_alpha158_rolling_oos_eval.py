# -*- coding: utf-8 -*-
"""
Alpha158 滚动样本外评估

用途：
- 固定当前策略参数，按多个窗口（交易日）做滚动短窗回测；
- 输出每个窗口下 T+3/T+5 的核心指标，检查稳定性与漂移。
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Dict, List


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def run_backtest(signal_days: int, horizons: List[int], out_json: str) -> Dict:
    cmd = [
        sys.executable,
        str(ROOT / "scripts" / "run_alpha158_short_backtest.py"),
        "--signal-days",
        str(signal_days),
        "--horizons",
        *[str(h) for h in horizons],
        "--out-json",
        out_json,
    ]
    subprocess.run(cmd, check=True, cwd=str(ROOT))
    with open(out_json, "r", encoding="utf-8") as f:
        return json.load(f)


def flatten_metrics(payload: Dict) -> Dict:
    out = {
        "signal_start": payload.get("signal_start"),
        "signal_end": payload.get("signal_end"),
        "signal_days": payload.get("signal_days"),
        "days_with_picks": payload.get("days_with_picks"),
        "recommendation_rows": payload.get("recommendation_rows"),
    }
    for item in payload.get("horizons", []):
        h = int(item.get("horizon"))
        out[f"h{h}_win_rate"] = item.get("win_rate")
        out[f"h{h}_mean_return"] = item.get("mean_return")
        out[f"h{h}_median_return"] = item.get("median_return")
        out[f"h{h}_max_drawdown"] = item.get("max_drawdown")
        out[f"h{h}_sharpe"] = item.get("sharpe_ratio")
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="Alpha158 滚动样本外评估")
    parser.add_argument(
        "--windows",
        type=int,
        nargs="+",
        default=[60, 120],
        help="评估窗口（交易日），默认 60 120",
    )
    parser.add_argument(
        "--horizons",
        type=int,
        nargs="+",
        default=[3, 5],
        help="持有期（交易日），默认 3 5",
    )
    parser.add_argument(
        "--out-json",
        default=str(ROOT / "output" / "alpha158_rolling_oos_eval.json"),
        help="汇总输出路径",
    )
    args = parser.parse_args()

    os.makedirs(Path(args.out_json).parent, exist_ok=True)
    results = []
    for window in args.windows:
        tmp_out = str(ROOT / "output" / f"alpha158_short_backtest_{window}d.json")
        payload = run_backtest(signal_days=window, horizons=args.horizons, out_json=tmp_out)
        flat = flatten_metrics(payload)
        flat["window"] = int(window)
        results.append(flat)

    summary = {
        "windows": args.windows,
        "horizons": args.horizons,
        "results": results,
    }
    with open(args.out_json, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    print("=" * 64)
    print("Alpha158 滚动样本外评估结果")
    print("=" * 64)
    for row in results:
        print(
            f"窗口={row['window']:>3}d | 区间={row['signal_start']}~{row['signal_end']} | "
            f"T+3 胜率={row.get('h3_win_rate', 0):.2%} 中位={row.get('h3_median_return', 0):.2%} "
            f"MDD={row.get('h3_max_drawdown', 0):.2%} | "
            f"T+5 胜率={row.get('h5_win_rate', 0):.2%} 中位={row.get('h5_median_return', 0):.2%} "
            f"MDD={row.get('h5_max_drawdown', 0):.2%}"
        )
    print("-" * 64)
    print(f"汇总已保存: {args.out_json}")


if __name__ == "__main__":
    main()
