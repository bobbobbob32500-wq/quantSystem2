# -*- coding: utf-8 -*-
"""
在「与 qlib_optuna_alpha_comparison 相同」的测试窗口上，对基线 vs Optuna 优化后的
LightGBM 打分做 Top-K 等权组合日度回测，输出净值与胜率、夏普、回撤等改进对比。

规则：
- 每个交易日按预测值取前 top_k 只成分股，组合收益 = 当日这 k 只股票标签（Qlib Alpha158 默认标签）的均值；
- 标签为研究用远期收益 proxy，不含手续费；与实盘存在偏差。

依赖：conda activate qlib_env

用法：
  python scripts/run_qlib_optuna_backtest_compare.py
  python scripts/run_qlib_optuna_backtest_compare.py --comparison-json output/qlib_optuna_alpha_comparison.json --top-k 20

自定义回测窗口（与 baseline / 优化版同一口径：Top-K + Qlib 标签）：
  python scripts/run_qlib_optuna_backtest_compare.py --test-start 20250901 --test-end 20260401
  # 日期可为 YYYY-MM-DD 或 YYYYMMDD；默认 train 至 2023、valid 为 2024 全年，与测试窗（如 2025H2+）错开
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List, Tuple

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from src.modules.qlib_lgb_params import baseline_alpha158_lgb_params


def _normalize_date(s: str) -> str:
    """支持 YYYY-MM-DD 或 YYYYMMDD。"""
    s = str(s).strip().replace("/", "-")
    if len(s) == 8 and s.isdigit():
        return f"{s[:4]}-{s[4:6]}-{s[6:8]}"
    return s


def _load_optuna_alpha_module():
    path = os.path.join(ROOT, "scripts", "run_qlib_optuna_alpha_optimize.py")
    spec = importlib.util.spec_from_file_location("run_qlib_optuna_alpha_optimize", path)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def _topk_daily_returns(
    pred: pd.Series,
    label: pd.Series,
    top_k: int,
    min_universe: int,
) -> pd.Series:
    """按日取预测 Top-K，组合收益为当日选中股票标签均值。"""
    if isinstance(label, pd.DataFrame) and label.shape[1] == 1:
        label = label.iloc[:, 0]
    pred = pred.dropna()
    common = pred.index.intersection(label.index)
    pred = pred.loc[common]
    label = label.loc[common]

    daily_rets: List[float] = []
    idx_dates: List[pd.Timestamp] = []

    for dt in pred.index.get_level_values("datetime").unique().sort_values():
        try:
            p_d = pred.xs(dt, level="datetime")
            l_d = label.xs(dt, level="datetime")
        except Exception:
            continue
        ix = p_d.index.intersection(l_d.index)
        if len(ix) < max(min_universe, top_k):
            continue
        p_d = p_d.loc[ix]
        l_d = l_d.loc[ix]
        top_ix = p_d.nlargest(top_k).index
        r = float(l_d.loc[top_ix].mean())
        if np.isfinite(r):
            daily_rets.append(r)
            idx_dates.append(pd.Timestamp(dt))

    if not daily_rets:
        return pd.Series(dtype=float)
    return pd.Series(daily_rets, index=pd.DatetimeIndex(idx_dates))


def _equity_metrics(daily: pd.Series) -> Dict[str, float]:
    """由日度组合收益序列计算统计量。"""
    if daily.empty or len(daily) < 2:
        return {
            "trading_days": float(len(daily)),
            "total_return": float("nan"),
            "mean_daily": float("nan"),
            "std_daily": float("nan"),
            "sharpe_ann": float("nan"),
            "win_rate": float("nan"),
            "max_drawdown": float("nan"),
            "profit_factor": float("nan"),
        }

    s = daily.astype(float)
    curve = (1.0 + s).cumprod()
    total_return = float(curve.iloc[-1] - 1.0)
    mean_d = float(s.mean())
    std_d = float(s.std(ddof=1)) if len(s) > 1 else 0.0
    sharpe = (mean_d / std_d) * np.sqrt(252.0) if std_d > 1e-12 else float("nan")
    win_rate = float((s > 0).mean())

    peak = curve.cummax()
    dd = float(((curve / peak) - 1.0).min())
    gains = s[s > 0].sum()
    losses = -s[s < 0].sum()
    pf = float(gains / losses) if losses > 1e-12 else float("inf") if gains > 0 else float("nan")

    return {
        "trading_days": float(len(s)),
        "total_return": total_return,
        "mean_daily": mean_d,
        "std_daily": std_d,
        "sharpe_ann": float(sharpe),
        "win_rate": win_rate,
        "max_drawdown": dd,
        "profit_factor": pf,
    }


def _improvement(b: Dict[str, float], o: Dict[str, float]) -> Dict[str, Any]:
    """优化相对基线的绝对差与相对变化（百分比）。"""
    out: Dict[str, Any] = {}
    for k in [
        "total_return",
        "mean_daily",
        "sharpe_ann",
        "win_rate",
        "max_drawdown",
        "profit_factor",
    ]:
        vb, vo = b.get(k), o.get(k)
        if isinstance(vb, float) and isinstance(vo, float) and vb == vb and vo == vo:
            out[f"{k}_delta"] = vo - vb
            if abs(vb) > 1e-12 and k != "max_drawdown":
                out[f"{k}_pct_vs_baseline"] = (vo - vb) / abs(vb) * 100.0
            elif k == "max_drawdown" and vb != 0:
                # 回撤为负，改善意味着更接近 0（绝对值变小）
                out[f"{k}_delta"] = vo - vb
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="Qlib Optuna 同窗 Top-K 回测对比")
    parser.add_argument(
        "--comparison-json",
        type=str,
        default=os.path.join(ROOT, "output", "qlib_optuna_alpha_comparison.json"),
        help="Optuna 对比结果 JSON（含 optuna_best_trial_params）",
    )
    parser.add_argument(
        "--provider-uri",
        type=str,
        default=None,
        help="Qlib 数据目录，默认 ~/.qlib/qlib_data/cn_data",
    )
    parser.add_argument(
        "--test-start",
        type=str,
        default=None,
        help="回测窗口开始（YYYY-MM-DD 或 YYYYMMDD）；与 --test-end 同时给出则启用自定义窗",
    )
    parser.add_argument(
        "--test-end",
        type=str,
        default=None,
        help="回测窗口结束",
    )
    parser.add_argument("--train-start", type=str, default="2015-01-01", help="自定义窗时训练段开始")
    parser.add_argument(
        "--train-end",
        type=str,
        default="2023-12-31",
        help="自定义窗时训练段结束（与 valid 错开，避免 LightGBM 段内无样本）",
    )
    parser.add_argument(
        "--valid-start",
        type=str,
        default="2024-01-01",
        help="验证段开始（早停用，须早于测试窗；默认用 2024 全年）",
    )
    parser.add_argument("--valid-end", type=str, default="2024-12-31", help="验证段结束")
    parser.add_argument("--top-k", type=int, default=20, help="每日持仓只数（等权）")
    parser.add_argument("--min-universe", type=int, default=30, help="当日至少多少只有效股票才交易")
    parser.add_argument("--num-boost-round", type=int, default=1000)
    parser.add_argument("--early-stopping", type=int, default=50)
    args = parser.parse_args()

    provider_uri = args.provider_uri or os.path.expanduser("~/.qlib/qlib_data/cn_data")
    if not os.path.isfile(args.comparison_json):
        print(f"错误：找不到对比文件: {args.comparison_json}")
        print("请先运行: python scripts/run_qlib_optuna_alpha_optimize.py")
        sys.exit(1)

    with open(args.comparison_json, "r", encoding="utf-8") as f:
        cmp_data = json.load(f)

    mod = _load_optuna_alpha_module()
    import qlib
    from qlib.config import C
    from qlib.data import D

    # Windows 下 loky/多进程在部分环境会异常，线程后端更稳
    C.joblib_backend = "threading"

    qlib.init(provider_uri=provider_uri)

    cal = D.calendar()
    cal_first = pd.Timestamp(cal[0]).strftime("%Y-%m-%d")
    cal_last = pd.Timestamp(cal[-1]).strftime("%Y-%m-%d")

    custom_window = args.test_start is not None and args.test_end is not None
    if custom_window:
        ts = _normalize_date(args.test_start)
        te = _normalize_date(args.test_end)
        train = (_normalize_date(args.train_start), _normalize_date(args.train_end))
        valid = (_normalize_date(args.valid_start), _normalize_date(args.valid_end))
        test = (ts, te)
        if valid[1] >= test[0]:
            print(
                f"错误：验证段须早于测试段。当前 valid 结束={valid[1]}，test 开始={test[0]}。"
                "请调整 --valid-end 或 --test-start。"
            )
            sys.exit(1)
        # 本地 Qlib 日历覆盖检查（cn_data 未更新时无法做未来区间回测）
        if test[0] > cal_last:
            print(
                f"错误：本地 Qlib 数据日历为 {cal_first}～{cal_last}，"
                f"无法覆盖请求的测试段 {test[0]}～{test[1]}。\n"
                "请先更新数据（例如官方 get_data 或 scripts/download_qlib_data.py），再重跑本脚本。"
            )
            sys.exit(1)
        if test[1] > cal_last:
            print(
                f"警告：请求测试结束日 {test[1]} 超出本地数据最后交易日 {cal_last}，"
                f"已截断为 {cal_last}。"
            )
            test = (test[0], cal_last)
    else:
        train = tuple(cmp_data["meta"]["segments"]["train"])
        valid = tuple(cmp_data["meta"]["segments"]["valid"])
        test = tuple(cmp_data["meta"]["segments"]["test"])

    dataset = mod._make_dataset(train, valid, test)
    lab_test = dataset.prepare("test", col_set="label")

    base_p = cmp_data.get("baseline_lgb_params") or baseline_alpha158_lgb_params()
    opt_p = dict(cmp_data["optuna_best_trial_params"])
    opt_p["loss"] = "mse"
    opt_p["num_threads"] = 4

    from qlib.contrib.model.gbdt import LGBModel

    print("训练基线模型…")
    m_base = LGBModel(
        early_stopping_rounds=args.early_stopping,
        num_boost_round=args.num_boost_round,
        **base_p,
    )
    m_base.fit(dataset, verbose_eval=0)
    pred_b = m_base.predict(dataset, segment="test").dropna()

    print("训练 Optuna 最优超参模型…")
    m_opt = LGBModel(
        early_stopping_rounds=args.early_stopping,
        num_boost_round=args.num_boost_round,
        **opt_p,
    )
    m_opt.fit(dataset, verbose_eval=0)
    pred_o = m_opt.predict(dataset, segment="test").dropna()

    daily_b = _topk_daily_returns(pred_b, lab_test, args.top_k, args.min_universe)
    daily_o = _topk_daily_returns(pred_o, lab_test, args.top_k, args.min_universe)

    met_b = _equity_metrics(daily_b)
    met_o = _equity_metrics(daily_o)
    imp = _improvement(met_b, met_o)

    if isinstance(lab_test, pd.DataFrame) and lab_test.shape[1] == 1:
        lab_ic = lab_test.iloc[:, 0]
    else:
        lab_ic = lab_test

    ic_b = mod._ic_dict(pred_b.dropna(), lab_ic)
    ic_o = mod._ic_dict(pred_o.dropna(), lab_ic)

    if custom_window:
        ic_block_note = "IC 在**本测试段**上现算，与组合回测同一标签与区间。"
        ic_from_json = None
    else:
        ic_block_note = (
            "下表 IC 为脚本在测试段现算；可与 `qlib_optuna_alpha_comparison.json` 中测试 IC 对照。"
        )
        ic_from_json = {
            "baseline_ic_mean_json": cmp_data["metrics"]["baseline"]["test"]["ic_mean"],
            "optimized_ic_mean_json": cmp_data["metrics"]["optimized"]["test"]["ic_mean"],
        }

    result: Dict[str, Any] = {
        "meta": {
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "qlib_calendar_range": {"first": cal_first, "last": cal_last},
            "comparison_json": os.path.abspath(args.comparison_json),
            "custom_window": custom_window,
            "segments": {"train": list(train), "valid": list(valid), "test": list(test)},
            "test_segment": {"start": test[0], "end": test[1]},
            "top_k": args.top_k,
            "min_universe": args.min_universe,
            "note": "日度组合收益为 Top-K 标签均值；不含交易成本；baseline 与优化版同一划分与 Top-K 口径。",
        },
        "ic_computed_on_test_segment": {"baseline": ic_b, "optimized": ic_o},
        "baseline_backtest": met_b,
        "optimized_backtest": met_o,
        "improvement": imp,
    }
    if ic_from_json is not None:
        result["ic_reference_from_optimization_json"] = ic_from_json

    out_dir = os.path.join(ROOT, "output")
    os.makedirs(out_dir, exist_ok=True)
    if custom_window:
        tag = f"{test[0].replace('-', '')}_{test[1].replace('-', '')}"
        base_name = f"qlib_optuna_backtest_improvement_{tag}"
    else:
        base_name = "qlib_optuna_backtest_improvement"
    json_path = os.path.join(out_dir, f"{base_name}.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    def fmt(x: float) -> str:
        if x != x:
            return "N/A"
        return f"{x:.6f}"

    seg_line = f"训练 {train[0]}~{train[1]}，验证 {valid[0]}~{valid[1]}，**测试（回测）** {test[0]}~{test[1]}。"
    md = f"""# Qlib Alpha Optuna — Top-{args.top_k} 回测对比

## 说明

- **划分**：{seg_line}
- **规则**（同一口径）：每日按预测取前 **{args.top_k}** 只（csi300），组合日收益 = 选中股票 **Qlib Alpha158 标签**均值；**不含手续费**。
- {ic_block_note}

## IC（测试段截面 IC）

| 项目 | IC 均值 | ICIR | 有效交易日 |
|------|---------|------|------------|
| 基线 | {fmt(ic_b['ic_mean'])} | {fmt(ic_b['ic_ir'])} | {int(ic_b['n_days'])} |
| 优化后 | {fmt(ic_o['ic_mean'])} | {fmt(ic_o['ic_ir'])} | {int(ic_o['n_days'])} |

## 组合回测（测试窗，Top-{args.top_k}）

| 指标 | 基线 | 优化后 | 差值（优化 − 基线） |
|------|------|--------|---------------------|
| 累计收益 | {fmt(met_b['total_return'])} | {fmt(met_o['total_return'])} | {fmt(imp.get('total_return_delta', float('nan')))} |
| 日均收益 | {fmt(met_b['mean_daily'])} | {fmt(met_o['mean_daily'])} | {fmt(imp.get('mean_daily_delta', float('nan')))} |
| 年化夏普（日频×√252） | {fmt(met_b['sharpe_ann'])} | {fmt(met_o['sharpe_ann'])} | {fmt(imp.get('sharpe_ann_delta', float('nan')))} |
| 日胜率 | {fmt(met_b['win_rate'])} | {fmt(met_o['win_rate'])} | {fmt(imp.get('win_rate_delta', float('nan')))} |
| 最大回撤 | {fmt(met_b['max_drawdown'])} | {fmt(met_o['max_drawdown'])} | {fmt(imp.get('max_drawdown_delta', float('nan')))} |
| 盈亏比 proxy | {fmt(met_b['profit_factor'])} | {fmt(met_o['profit_factor'])} | {fmt(imp.get('profit_factor_delta', float('nan')))} |
| 有效交易日 | {int(met_b['trading_days'])} | {int(met_o['trading_days'])} | — |

## 生成文件

- `{json_path}`

---
UTC：{result['meta']['generated_at_utc']}
"""

    md_path = os.path.join(out_dir, f"{base_name}.md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(md)

    print("\n摘要（测试窗 Top-%d）" % args.top_k)
    print(f"  基线   累计收益={fmt(met_b['total_return'])} 夏普={fmt(met_b['sharpe_ann'])} 胜率={fmt(met_b['win_rate'])}")
    print(f"  优化后 累计收益={fmt(met_o['total_return'])} 夏普={fmt(met_o['sharpe_ann'])} 胜率={fmt(met_o['win_rate'])}")
    print(f"\n已写入: {json_path}")
    print(f"已写入: {md_path}")


if __name__ == "__main__":
    main()
