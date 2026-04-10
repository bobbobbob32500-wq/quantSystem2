# -*- coding: utf-8 -*-
"""Structure tests for strong_start_research_v4 (no backtest/PNL checks)."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from src.modules.strong_start_research_v4 import StrongStartResearchV4


def _make_df() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "trade_date": "20260327",
                "ts_code": "600001.SH",
                "name": "测试样本A",
                "industry": "电子",
                "close": 10.5,
                "list_days": 500,
                "amount_ma20": 120000,
                "f_trend_close_ma20_gap": 0.08,
                "f_strength_rs20_xsec_q": 0.85,
                "f_trend_close_ma60_gap": 0.11,
                "f_strength_vs_index20": 0.09,
                "f_strength_ret20": 0.10,
                "f_strength_rs60_xsec_q": 0.82,
                "f_strength_vs_index60": 0.12,
                "f_strength_ret60": 0.14,
                "f_ind_rank_pctchg": 0.93,
                "f_ind_rank_amount": 0.88,
                "f_chip_winner_rate": 0.90,
                "f_chip_stability_std10": 0.004,
                "f_breakout_vol_ratio20": 1.9,
                "f_k_pct_chg": 0.05,
                "f_k_body_to_atr": 1.1,
                "f_up_down_vol_ratio20": 1.3,
                "f_k_upper_shadow_ratio": 0.10,
                "f_platform_range20": 0.08,
                "f_chip_single_peak_score": 0.31,
            }
        ]
    )


def test_new_strategy_is_isolated_from_legacy():
    old_path = Path("src/modules/strong_start_strategy.py").resolve()
    new_path = Path("src/modules/strong_start_research_v4.py").resolve()
    assert old_path.exists()
    assert new_path.exists()
    assert old_path != new_path


def test_layer_boundaries_and_sanity_positions():
    strategy = StrongStartResearchV4(config_path="config/strong_start_research_v4_config.yaml")
    layers = strategy.get_layer_features()

    # No accidental hard/trigger overlap except explicitly sanctioned feature.
    hard = set(layers["hard_filters"])
    trigger = set(layers["trigger"])
    overlap = hard & trigger
    assert overlap <= {"f_ind_rank_pctchg"}

    # Sanity constraints from research reconstruction.
    assert "f_chip_stability_std10" not in hard
    assert "f_k_pct_chg" in trigger
    assert "f_ind_rank_pctchg" in set(layers["scoring"])
    assert "f_ind_rank_pctchg" in hard
    assert "f_ind_rank_pctchg" in trigger


def test_output_fields_completeness_and_explainability():
    strategy = StrongStartResearchV4(config_path="config/strong_start_research_v4_config.yaml")
    out = strategy.run_on_dataframe(_make_df(), profile="neutral")
    required = {
        "is_candidate_after_filters",
        "score_total",
        "trigger_status",
        "signal_ready",
        "explain_json",
        "filter_reject_reasons",
        "score_details",
        "trigger_details",
        "downgraded_observations",
    }
    assert required.issubset(set(out.columns))
    assert isinstance(out.iloc[0]["explain_json"], str)
    assert isinstance(out.iloc[0]["score_details"], str)


def test_missing_required_config_key_raises():
    strategy = StrongStartResearchV4(config_path="config/strong_start_research_v4_config.yaml")
    bad = dict(strategy.config)
    bad.pop("trigger", None)
    with pytest.raises(Exception):
        StrongStartResearchV4(config=bad)


def test_future_field_blocked():
    strategy = StrongStartResearchV4(config_path="config/strong_start_research_v4_config.yaml")
    df = _make_df()
    df["foo_fwd_5"] = 0.1
    with pytest.raises(Exception):
        strategy.run_on_dataframe(df, profile="neutral")
