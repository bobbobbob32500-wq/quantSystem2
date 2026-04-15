# -*- coding: utf-8 -*-
"""
Qlib Alpha158 + LightGBM 基线 vs Optuna 超参搜索对比

思路：
- 使用 Qlib DatasetH（Alpha158、csi300）与固定时间切分：train / valid / test；
- 基线：项目内沿用的一组 LightGBM 默认超参；
- Optuna：在验证集截面 IC 均值上最大化，搜索学习率、树复杂度、正则等；
- 最终：用各自策略在测试集上报告 IC 均值、ICIR（仅作研究对比，非实盘承诺）。

依赖：conda activate qlib_env 后执行；需已安装 pyqlib、optuna 与本机 cn_data。

用法：
  python scripts/run_qlib_optuna_alpha_optimize.py
  python scripts/run_qlib_optuna_alpha_optimize.py --n-trials 15 --seed 42
"""

from __future__ import annotations

import argparse
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


def _daily_cross_sectional_ic(
    pred: pd.Series,
    label: pd.Series,
    min_names: int = 10,
) -> Tuple[float, float, float, int]:
    """按交易日计算截面 Spearman IC，返回 (均值, 标准差, ICIR, 有效天数)。"""
    from scipy.stats import spearmanr

    common = pred.index.intersection(label.index)
    if len(common) < min_names * 2:
        return float("nan"), float("nan"), float("nan"), 0
    pred = pred.loc[common]
    lab = label.loc[common]
    if isinstance(lab, pd.DataFrame):
        lab = lab.iloc[:, 0]

    ic_vals: List[float] = []
    for dt in pred.index.get_level_values("datetime").unique():
        try:
            p_d = pred.xs(dt, level="datetime")
            l_d = lab.xs(dt, level="datetime")
        except Exception:
            continue
        idx = p_d.index.intersection(l_d.index)
        if len(idx) < min_names:
            continue
        try:
            ic, _ = spearmanr(p_d.loc[idx], l_d.loc[idx])
            if ic == ic and not np.isnan(ic):
                ic_vals.append(float(ic))
        except Exception:
            continue

    if not ic_vals:
        return float("nan"), float("nan"), float("nan"), 0
    m = float(np.mean(ic_vals))
    s = float(np.std(ic_vals))
    ir = m / s if s > 1e-12 else float("nan")
    return m, s, ir, len(ic_vals)


def _make_dataset(
    train: Tuple[str, str],
    valid: Tuple[str, str],
    test: Tuple[str, str],
    instruments: str = "csi300",
) -> Any:
    from qlib.data.dataset import DatasetH

    start_time = train[0]
    end_time = test[1]
    fit_end = train[1]

    return DatasetH(
        handler={
            "class": "Alpha158",
            "module_path": "qlib.contrib.data.handler",
            "kwargs": {
                "start_time": start_time,
                "end_time": end_time,
                "fit_start_time": start_time,
                "fit_end_time": fit_end,
                "instruments": instruments,
            },
        },
        segments={
            "train": train,
            "valid": valid,
            "test": test,
        },
    )


def _fit_and_ic(
    dataset: Any,
    params: Dict[str, Any],
    num_boost_round: int,
    early_stopping_rounds: int,
    verbose_eval: int,
) -> Tuple[Any, Dict[str, float], Dict[str, float]]:
    """训练模型并返回 (model, valid_metrics, test_metrics)。"""
    from qlib.contrib.model.gbdt import LGBModel

    model = LGBModel(
        early_stopping_rounds=early_stopping_rounds,
        num_boost_round=num_boost_round,
        **params,
    )
    model.fit(dataset, verbose_eval=verbose_eval)

    pred_v = model.predict(dataset, segment="valid")
    lab_v = dataset.prepare("valid", col_set="label")
    if isinstance(lab_v, pd.DataFrame) and lab_v.shape[1] == 1:
        lab_v_s = lab_v.iloc[:, 0]
    else:
        lab_v_s = lab_v

    pred_t = model.predict(dataset, segment="test")
    lab_t = dataset.prepare("test", col_set="label")
    if isinstance(lab_t, pd.DataFrame) and lab_t.shape[1] == 1:
        lab_t_s = lab_t.iloc[:, 0]
    else:
        lab_t_s = lab_t

    vm = _ic_dict(pred_v.dropna(), lab_v_s)
    tm = _ic_dict(pred_t.dropna(), lab_t_s)
    return model, vm, tm


def _ic_dict(pred: pd.Series, lab) -> Dict[str, float]:
    m, s, ir, n = _daily_cross_sectional_ic(pred, lab)
    return {
        "ic_mean": m,
        "ic_std": s,
        "ic_ir": ir,
        "n_days": float(n),
    }


def run(
    provider_uri: str,
    n_trials: int,
    seed: int,
    num_boost_round: int,
    early_stopping_rounds: int,
    trial_fast_round: int,
    trial_fast_es: int,
) -> Dict[str, Any]:
    import optuna
    import qlib
    from qlib.contrib.model.gbdt import LGBModel

    qlib.init(provider_uri=provider_uri)

    train = ("2015-01-01", "2018-12-31")
    valid = ("2019-01-01", "2019-12-31")
    test = ("2020-01-01", "2020-09-25")

    dataset = _make_dataset(train, valid, test)

    # ---------- 基线 ----------
    base_p = baseline_alpha158_lgb_params()
    _, base_valid, base_test = _fit_and_ic(
        dataset,
        base_p,
        num_boost_round=num_boost_round,
        early_stopping_rounds=early_stopping_rounds,
        verbose_eval=0,
    )

    # ---------- Optuna：仅最大化验证集 IC 均值 ----------
    def objective(trial: optuna.Trial) -> float:
        p = {
            "loss": "mse",
            "learning_rate": trial.suggest_float("learning_rate", 0.02, 0.12, log=True),
            "num_leaves": trial.suggest_int("num_leaves", 48, 256),
            "max_depth": trial.suggest_int("max_depth", 4, 12),
            "subsample": trial.suggest_float("subsample", 0.65, 1.0),
            "colsample_bytree": trial.suggest_float("colsample_bytree", 0.65, 1.0),
            "lambda_l1": trial.suggest_float("lambda_l1", 1e-4, 200.0, log=True),
            "lambda_l2": trial.suggest_float("lambda_l2", 1e-4, 800.0, log=True),
            "num_threads": 4,
        }
        try:
            model = LGBModel(
                early_stopping_rounds=trial_fast_es,
                num_boost_round=trial_fast_round,
                **p,
            )
            model.fit(dataset, verbose_eval=0)
            pred_v = model.predict(dataset, segment="valid").dropna()
            lab_v = dataset.prepare("valid", col_set="label")
            if isinstance(lab_v, pd.DataFrame) and lab_v.shape[1] == 1:
                lab_v = lab_v.iloc[:, 0]
            m, _, _, n = _daily_cross_sectional_ic(pred_v, lab_v)
            if n < 5 or m != m:
                return -1e9
            return float(m)
        except Exception:
            return -1e9

    sampler = optuna.samplers.TPESampler(seed=seed)
    study = optuna.create_study(direction="maximize", sampler=sampler)
    study.optimize(objective, n_trials=n_trials, show_progress_bar=True)

    best_params = dict(study.best_params)
    best_params["loss"] = "mse"
    best_params["num_threads"] = 4

    # 用最优超参完整轮数重新训练，得到测试集指标
    _, opt_valid, opt_test = _fit_and_ic(
        dataset,
        best_params,
        num_boost_round=num_boost_round,
        early_stopping_rounds=early_stopping_rounds,
        verbose_eval=0,
    )

    # 用户可读的「最佳 trial 参数」不含 loss/threads
    trial_only = {k: v for k, v in study.best_params.items()}

    return {
        "meta": {
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "provider_uri": provider_uri,
            "segments": {"train": train, "valid": valid, "test": test},
            "instruments": "csi300",
            "handler": "Alpha158",
            "n_trials": n_trials,
            "seed": seed,
            "optuna_best_value_valid_ic_mean": study.best_value,
        },
        "baseline_lgb_params": base_p,
        "optuna_best_trial_params": trial_only,
        "metrics": {
            "baseline": {"valid": base_valid, "test": base_test},
            "optimized": {"valid": opt_valid, "test": opt_test},
        },
    }


def _write_reports(result: Dict[str, Any], out_dir: str) -> None:
    os.makedirs(out_dir, exist_ok=True)
    json_path = os.path.join(out_dir, "qlib_optuna_alpha_comparison.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    b = result["metrics"]["baseline"]
    o = result["metrics"]["optimized"]

    def fmt(d: Dict[str, float], key: str) -> str:
        v = d.get(key)
        if v is None or (isinstance(v, float) and (v != v)):
            return "N/A"
        if key == "n_days":
            return str(int(v))
        return f"{v:.6f}"

    md = f"""# Qlib Alpha158 + Optuna 优化对比报告

## 说明

- **数据**：Qlib 内置 `csi300` + Alpha158；时间切分为 train / valid / test（见 JSON）。
- **基线**：仓库内固定 LightGBM 超参。
- **Optuna**：在 **验证集截面 IC 均值** 上最大化；展示最优 trial 参数经完整训练后在 **测试集** 上的表现。
- **风险**：指标仅为历史样本内/样本外研究用途，**不**代表实盘收益；请避免仅根据 IC 调参而忽略交易成本与过拟合。

## 指标对比

| 指标 | 基线-验证集 | **Optuna-验证集** | 基线-测试集 | **Optuna-测试集** |
|------|------------|------------------|------------|------------------|
| IC 均值 | {fmt(b['valid'], 'ic_mean')} | {fmt(o['valid'], 'ic_mean')} | {fmt(b['test'], 'ic_mean')} | {fmt(o['test'], 'ic_mean')} |
| ICIR | {fmt(b['valid'], 'ic_ir')} | {fmt(o['valid'], 'ic_ir')} | {fmt(b['test'], 'ic_ir')} | {fmt(o['test'], 'ic_ir')} |
| 有效交易日数 | {fmt(b['valid'], 'n_days')} | {fmt(o['valid'], 'n_days')} | {fmt(b['test'], 'n_days')} | {fmt(o['test'], 'n_days')} |

## Optuna 最优 trial 参数（不含 loss）

```json
{json.dumps(result.get("optuna_best_trial_params", {}), ensure_ascii=False, indent=2)}
```

## 生成文件

- `{json_path}`

---
生成时间（UTC）：{result['meta']['generated_at_utc']}
"""

    md_path = os.path.join(out_dir, "qlib_optuna_alpha_comparison.md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(md)

    print(f"\n已写入: {json_path}")
    print(f"已写入: {md_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Qlib Alpha + Optuna 对比")
    parser.add_argument(
        "--provider-uri",
        type=str,
        default=None,
        help="Qlib 数据目录，默认 ~/.qlib/qlib_data/cn_data",
    )
    parser.add_argument("--n-trials", type=int, default=20, help="Optuna 试验次数")
    parser.add_argument("--seed", type=int, default=42, help="随机种子")
    parser.add_argument("--num-boost-round", type=int, default=1000, help="最终训练最大轮数")
    parser.add_argument("--early-stopping", type=int, default=50, help="早停轮数")
    parser.add_argument("--trial-round", type=int, default=400, help="单次 trial 内最大轮数（加速）")
    parser.add_argument("--trial-es", type=int, default=30, help="单次 trial 内早停轮数")
    args = parser.parse_args()

    provider_uri = args.provider_uri or os.path.expanduser("~/.qlib/qlib_data/cn_data")
    if not os.path.isdir(provider_uri):
        print(f"错误：数据目录不存在: {provider_uri}")
        sys.exit(1)

    print("=" * 60)
    print("Qlib Alpha158 + LightGBM 基线 vs Optuna")
    print("=" * 60)
    print(f"数据目录: {provider_uri}")
    print(f"Optuna trials: {args.n_trials}, seed={args.seed}")

    result = run(
        provider_uri=provider_uri,
        n_trials=args.n_trials,
        seed=args.seed,
        num_boost_round=args.num_boost_round,
        early_stopping_rounds=args.early_stopping,
        trial_fast_round=args.trial_round,
        trial_fast_es=args.trial_es,
    )

    out_dir = os.path.join(ROOT, "output")
    _write_reports(result, out_dir)

    m = result["metrics"]
    print("\n摘要（验证集 / 测试集 IC 均值）")
    print(
        f"  基线:   valid={m['baseline']['valid']['ic_mean']:.6f}  test={m['baseline']['test']['ic_mean']:.6f}"
    )
    print(
        f"  优化后: valid={m['optimized']['valid']['ic_mean']:.6f}  test={m['optimized']['test']['ic_mean']:.6f}"
    )


if __name__ == "__main__":
    main()
