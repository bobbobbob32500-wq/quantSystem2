# -*- coding: utf-8 -*-
"""Structural validator for strong_start_research_v4 (no backtest)."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.modules.strong_start_research_v4 import StrongStartResearchV4


def _assert(condition: bool, msg: str) -> None:
    if not condition:
        raise AssertionError(msg)


def _make_minimal_frame() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "trade_date": "20260327",
                "ts_code": "600001.SH",
                "name": "测试样本A",
                "industry": "电子",
                "label_abc": "A",
                "event_type_candidate": "candidate",
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
            },
            {
                "trade_date": "20260327",
                "ts_code": "000001.SZ",
                "name": "测试样本B",
                "industry": "机械",
                "label_abc": "C",
                "event_type_candidate": "candidate",
                "close": 8.2,
                "list_days": 50,
                "amount_ma20": 15000,
                "f_trend_close_ma20_gap": 0.02,
                "f_strength_rs20_xsec_q": 0.40,
                "f_trend_close_ma60_gap": 0.03,
                "f_strength_vs_index20": 0.01,
                "f_strength_ret20": 0.02,
                "f_strength_rs60_xsec_q": 0.45,
                "f_strength_vs_index60": 0.03,
                "f_strength_ret60": 0.02,
                "f_ind_rank_pctchg": 0.55,
                "f_ind_rank_amount": 0.40,
                "f_chip_winner_rate": 0.60,
                "f_chip_stability_std10": 0.001,
                "f_breakout_vol_ratio20": 1.1,
                "f_k_pct_chg": 0.01,
                "f_k_body_to_atr": 0.2,
                "f_up_down_vol_ratio20": 0.9,
                "f_k_upper_shadow_ratio": 0.35,
                "f_platform_range20": 0.25,
                "f_chip_single_peak_score": 0.22,
            },
        ]
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate strong_start_research_v4 structure.")
    parser.add_argument("--config", type=str, default="config/strong_start_research_v4_config.yaml")
    args = parser.parse_args()

    # 1) strategy must be independent from legacy file.
    old_path = Path("src/modules/strong_start_strategy.py")
    new_path = Path("src/modules/strong_start_research_v4.py")
    _assert(old_path.exists(), "legacy strong_start_strategy.py missing")
    _assert(new_path.exists(), "new strong_start_research_v4.py missing")
    _assert(old_path.resolve() != new_path.resolve(), "new strategy unexpectedly points to legacy file")

    strategy = StrongStartResearchV4(config_path=args.config)
    layers = strategy.get_layer_features()

    # 2) no layer mixing + sanity constraints.
    _assert("f_chip_stability_std10" not in layers["hard_filters"], "f_chip_stability_std10 wrongly in hard filters")
    _assert("f_k_pct_chg" in layers["trigger"], "f_k_pct_chg must be in trigger layer")
    _assert("f_ind_rank_pctchg" in layers["scoring"], "f_ind_rank_pctchg must be in scoring layer")
    _assert("f_ind_rank_pctchg" in layers["hard_filters"], "f_ind_rank_pctchg must be in weak hard-filter gate")
    _assert("f_ind_rank_pctchg" in layers["trigger"], "f_ind_rank_pctchg must be in trigger assist")
    overlap = set(layers["hard_filters"]) & set(layers["trigger"])
    allow = set(strategy.config.get("cross_layer_allowlist") or [])
    real_overlap = overlap - allow
    _assert(not real_overlap, f"hard/trigger overlap detected: {sorted(real_overlap)}")

    # 3) run with minimal frame and check output completeness.
    df = _make_minimal_frame()
    out = strategy.run_on_dataframe(df, profile="neutral")
    required_cols = [
        "is_candidate_after_filters",
        "score_total",
        "trigger_status",
        "signal_ready",
        "explain_json",
        "filter_reject_reasons",
        "score_details",
        "trigger_details",
        "downgraded_observations",
    ]
    for c in required_cols:
        _assert(c in out.columns, f"missing output field: {c}")

    # 4) missing config key should raise.
    bad_cfg = strategy.config.copy()
    bad_cfg.pop("trigger", None)
    raised = False
    try:
        StrongStartResearchV4(config=bad_cfg)
    except Exception:
        raised = True
    _assert(raised, "missing config key did not raise")

    # 5) future field should be blocked.
    bad_df = df.copy()
    bad_df["ret_fwd_5"] = 0.1
    raised = False
    try:
        strategy.run_on_dataframe(bad_df, profile="neutral")
    except Exception:
        raised = True
    _assert(raised, "forbidden future field was not blocked")

    print("=" * 72)
    print("strong_start_research_v4 structure validation passed")
    print("=" * 72)
    print("checks:")
    print("- independent module path")
    print("- no layer mixing")
    print("- sanity constraints on key features")
    print("- output completeness")
    print("- config missing-key error")
    print("- forbidden future field guard")


if __name__ == "__main__":
    main()
