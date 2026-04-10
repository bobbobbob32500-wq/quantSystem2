# true_breakout_factor_refinement_report

## Input freeze
- main set: A vs C only
- G: observation only
- N: excluded

## Stability audit
- total features: 43
- stable-direction features: 30
- stability rule: monthly sign consistency >= 70% with at least 6 months

## Redundancy audit
- high-correlation pairs (|spearman|>=0.85): 15

## Layering result (counts)
- hard_filter_candidate: 2
- continuous_scoring_candidate: 12
- downgraded_observation: 29

## Strongest axis
- trend_strength

## Hard filter candidates (top)
- f_strength_rs20_xsec_q
- f_chip_stability_std10

## Continuous scoring candidates (top)
- f_platform_range20
- f_chip_winner_rate
- f_ind_peer_strong_count
- f_chip_low_position120
- f_trend_close_ma60_gap
- f_strength_rs60_xsec_q
- f_trend_close_ma20_gap
- f_k_lower_shadow_ratio
- f_ind_strength_5d
- f_platform_len
- f_chip_secondary_peak_ratio
- f_chip_peak_count_sig

## Downgraded observation (top)
- f_strength_ret20
- f_platform_range_best
- f_strength_vs_index20
- f_platform_range30
- f_breakout_vol_ratio20
- f_trend_ma20_slope5
- f_strength_ret60
- f_chip_peak_dominance
- f_strength_vs_index60
- f_trend_ma20_ma60_gap
- f_chip_single_peak_score
- f_k_pct_chg
- f_atr_ratio
- f_chip_concentration
- f_up_down_vol_ratio20