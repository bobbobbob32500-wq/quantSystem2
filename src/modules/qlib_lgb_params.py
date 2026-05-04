# -*- coding: utf-8 -*-
"""
全系统共用的 Qlib Alpha158 LightGBM 超参加载。

说明：
- 日常选股（StockSelector）仍以六类因子加权为主，本模块主要供 Qlib 训练/回测脚本
  与 LGBModel 构造时复用同一套超参；
- 开启 use_optuna_alpha_lgb_params 后，从 Optuna 对比 JSON 合并 optuna_best_trial_params，
  与 run_qlib_optuna_alpha_optimize.py 产出对齐。
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, Optional

from src.core.logger import get_logger

logger = get_logger("qlib_lgb_params")


def _project_root() -> str:
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def baseline_alpha158_lgb_params() -> Dict[str, Any]:
    """与仓库内 Qlib 脚本历史默认一致的基线超参（未启用 Optuna 合并时使用）。"""
    return {
        "loss": "mse",
        "colsample_bytree": 0.8879,
        "learning_rate": 0.0421,
        "subsample": 0.8789,
        "lambda_l1": 205.6999,
        "lambda_l2": 580.5258,
        "max_depth": 8,
        "num_leaves": 210,
        "num_threads": 4,
    }


def resolve_optuna_json_path(rel_or_abs: str) -> str:
    """将配置中的路径解析为绝对路径（相对路径相对项目根目录）。"""
    p = str(rel_or_abs or "").strip()
    if not p:
        return os.path.join(_project_root(), "output", "qlib_optuna_alpha_comparison.json")
    if os.path.isabs(p):
        return p
    return os.path.normpath(os.path.join(_project_root(), p))


def load_optuna_best_trial_params_from_json(json_path: str) -> Optional[Dict[str, Any]]:
    """从 Optuna 对比 JSON 读取 optuna_best_trial_params；失败返回 None。"""
    try:
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        logger.warning("无法读取 Optuna 对比 JSON: %s — %s", json_path, e)
        return None
    trial = data.get("optuna_best_trial_params")
    if not isinstance(trial, dict) or not trial:
        logger.warning("JSON 中缺少有效的 optuna_best_trial_params: %s", json_path)
        return None
    return dict(trial)


def get_lgb_params_for_qlib(config: Optional[Any] = None) -> Dict[str, Any]:
    """
    返回传给 qlib.contrib.model.gbdt.LGBModel 的固定超参（不含 num_boost_round、early_stopping_rounds）。

    配置项（config.yaml 的 qlib 段）：
    - use_optuna_alpha_lgb_params: 是否合并 Optuna 最优 trial 中的树与正则参数
    - optuna_alpha_comparison_json: 对比结果 JSON 相对项目根或绝对路径
    - lgb_num_threads: 可选，覆盖线程数（用于本机调优）
    """
    if config is None:
        from src.core.config import ConfigManager

        config = ConfigManager()

    base = baseline_alpha158_lgb_params().copy()
    use_opt = bool(config.get("qlib.use_optuna_alpha_lgb_params", False))
    if not use_opt:
        nt = config.get("qlib.lgb_num_threads")
        if nt is not None:
            base["num_threads"] = int(nt)
        return base

    rel = config.get("qlib.optuna_alpha_comparison_json", "output/qlib_optuna_alpha_comparison.json")
    abs_path = resolve_optuna_json_path(str(rel))
    if not os.path.isfile(abs_path):
        logger.warning("Optuna 对比文件不存在，使用基线 LGB 超参: %s", abs_path)
        nt = config.get("qlib.lgb_num_threads")
        if nt is not None:
            base["num_threads"] = int(nt)
        return base

    trial = load_optuna_best_trial_params_from_json(abs_path)
    if not trial:
        nt = config.get("qlib.lgb_num_threads")
        if nt is not None:
            base["num_threads"] = int(nt)
        return base

    merged = base.copy()
    merged.update(trial)
    nt = config.get("qlib.lgb_num_threads")
    if nt is not None:
        merged["num_threads"] = int(nt)
    return merged
