# -*- coding: utf-8 -*-
"""Tests for single-factor AB helpers."""

from __future__ import annotations

from scripts.run_single_factor_ab import (
    adjust_single_factor_weight,
    build_candidate_grid,
    resolve_factor_name,
)


def test_resolve_factor_name_supports_alias_and_score_name():
    assert resolve_factor_name("pullback") == "pullback_score"
    assert resolve_factor_name("quality_score") == "quality_score"


def test_adjust_single_factor_weight_preserves_sum_and_target_weight():
    base = {
        "trend_score": 0.25,
        "momentum_score": 0.30,
        "volume_score": 0.05,
        "fundamental_score": 0.10,
        "pullback_score": 0.20,
        "quality_score": 0.10,
    }
    adjusted = adjust_single_factor_weight(base, "quality_score", 0.15)

    assert round(sum(adjusted.values()), 6) == 1.0
    assert adjusted["quality_score"] == 0.15
    assert adjusted["pullback_score"] < base["pullback_score"]


def test_build_candidate_grid_contains_current_and_recommended():
    grid = build_candidate_grid(
        factor="quality_score",
        current_weight=0.1389,
        recommended_weight=0.2457,
        grid_points=9,
    )

    assert 0.1389 in grid
    assert 0.2457 in grid
    assert grid == sorted(grid)
