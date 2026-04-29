# -*- coding: utf-8 -*-
"""Position allocation helpers for buy candidates."""

from __future__ import annotations

from typing import Dict, List

import numpy as np

from .config import BacktestConfig


def allocate_buy_weights(candidates: List[Dict], config: BacktestConfig) -> Dict[str, float]:
    """Allocate target weights for current buy candidates."""
    if not candidates:
        return {}

    mode = str(getattr(config, "allocator_mode", "fixed") or "fixed").strip().lower()
    if mode == "skfolio":
        return _allocate_skfolio(candidates, config) or _allocate_score(candidates, config)
    if mode == "score":
        return _allocate_score(candidates, config)
    return _allocate_fixed(candidates, config)


def _portfolio_budget(config: BacktestConfig) -> float:
    explicit = float(getattr(config, "position_budget", 1.0) or 1.0)
    implicit = float(config.max_positions) * float(config.position_size)
    return max(0.0, min(1.0, min(explicit, implicit if implicit > 0 else explicit)))


def _allocate_fixed(candidates: List[Dict], config: BacktestConfig) -> Dict[str, float]:
    weight = max(0.0, min(1.0, float(config.position_size)))
    return {str(item["symbol"]): weight for item in candidates}


def _allocate_score(candidates: List[Dict], config: BacktestConfig) -> Dict[str, float]:
    budget = _portfolio_budget(config)
    max_weight = max(0.0, min(1.0, float(getattr(config, "skfolio_max_weight", 0.35) or 0.35)))
    scores = np.asarray([max(0.0, float(item.get("score", 0.0))) for item in candidates], dtype=float)
    if float(scores.sum()) <= 0.0:
        return _allocate_fixed(candidates, config)
    raw = scores / scores.sum() * budget
    clipped = np.minimum(raw, max_weight)
    if float(clipped.sum()) <= 0.0:
        return _allocate_fixed(candidates, config)
    if clipped.sum() > 0:
        clipped = clipped / clipped.sum() * min(budget, clipped.sum())
    return {str(item["symbol"]): float(weight) for item, weight in zip(candidates, clipped)}


def _allocate_skfolio(candidates: List[Dict], config: BacktestConfig) -> Dict[str, float]:
    try:
        from skfolio.optimization import MeanRisk
    except Exception:
        return {}

    returns_matrix = _build_returns_matrix(candidates, min_history=max(5, int(config.skfolio_min_history)))
    if returns_matrix is None:
        return {}

    budget = _portfolio_budget(config)
    max_weight = max(0.0, min(1.0, float(config.skfolio_max_weight)))
    max_drawdown = max(0.01, min(0.99, float(getattr(config, "skfolio_max_drawdown", 0.12) or 0.12)))
    max_turnover = max(0.01, min(2.0, float(getattr(config, "skfolio_max_turnover", 0.60) or 0.60)))
    previous_weights = np.asarray(
        [max(0.0, float(item.get("current_weight", 0.0) or 0.0)) for item in candidates],
        dtype=float,
    )
    if previous_weights.sum() > 0:
        previous_weights = previous_weights / previous_weights.sum() * min(budget, previous_weights.sum())
    else:
        previous_weights = np.zeros(len(candidates), dtype=float)
    try:
        model = MeanRisk(
            min_weights=0.0,
            max_weights=max_weight,
            budget=budget,
            risk_aversion=float(config.skfolio_risk_aversion),
            previous_weights=previous_weights,
            max_turnover=max_turnover,
            max_max_drawdown=max_drawdown,
            raise_on_failure=False,
        )
        model.fit(returns_matrix)
        portfolio = model.predict(returns_matrix)
        weights = np.asarray(getattr(portfolio, "weights", []), dtype=float)
        if weights.size != len(candidates):
            return {}
        weights = np.clip(weights, 0.0, max_weight)
        total = float(weights.sum())
        if total <= 0.0:
            return {}
        weights = weights / total * min(budget, total)
        return {str(item["symbol"]): float(weight) for item, weight in zip(candidates, weights)}
    except Exception:
        return {}


def _build_returns_matrix(candidates: List[Dict], min_history: int) -> np.ndarray | None:
    series_list: List[np.ndarray] = []
    min_len = None
    for item in candidates:
        hist = item.get("recent_returns") or []
        arr = np.asarray(hist, dtype=float)
        arr = arr[np.isfinite(arr)]
        if arr.size < min_history:
            return None
        if min_len is None:
            min_len = arr.size
        else:
            min_len = min(min_len, arr.size)
        series_list.append(arr)

    if not series_list or min_len is None or min_len < min_history:
        return None

    trimmed = [arr[-min_len:] for arr in series_list]
    matrix = np.column_stack(trimmed)
    if matrix.ndim != 2 or matrix.shape[0] < min_history:
        return None
    return matrix
