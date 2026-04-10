# -*- coding: utf-8 -*-
"""Tests for named enhanced weight profiles."""

from __future__ import annotations

import math

from src.core.config import ConfigManager
from src.modules.stock_selector import StockSelector


def test_quality_ab_profile_loads_as_active_profile():
    config = ConfigManager()
    config.set("stock_selection.save_factor_values", False, save=False)
    config.set("stock_selection.strategy_profile", "enhanced", save=False)
    config.set("stock_selection.enhanced_weight_profile", "quality_ab_0109", save=False)

    selector = StockSelector(config=config)

    expected = selector.get_enhanced_weight_profiles()["quality_ab_0109"]
    actual = selector._get_default_weights()

    assert selector.strategy_profile == "enhanced"
    assert selector.get_enhanced_weight_profile_name() == "quality_ab_0109"
    assert actual == expected
    assert math.isclose(sum(actual.values()), 1.0, rel_tol=0.0, abs_tol=1e-9)


def test_quality_ab_profile_keeps_progressive_20_available():
    config = ConfigManager()
    config.set("stock_selection.save_factor_values", False, save=False)
    config.set("stock_selection.strategy_profile", "enhanced", save=False)
    config.set("stock_selection.enhanced_weight_profile", "quality_ab_0109", save=False)

    selector = StockSelector(config=config)
    profiles = selector.get_enhanced_weight_profiles()

    assert "progressive_20" in profiles
    assert "quality_ab_0109" in profiles
    assert profiles["progressive_20"] != profiles["quality_ab_0109"]
