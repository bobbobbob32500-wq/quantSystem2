# true_breakout_selector_v2_2_draft

## Scope
- Only trend-axis repaired from v2.1; universe/hard filters/platform/chip/industry unchanged.

## Hard filters
- `f_strength_rs20_xsec_q >= 0.72` (unchanged)

## Trend axis (repaired)
- Core kept: `f_strength_rs20_xsec_q` (rank-capped upper=0.90).
- Removed from trend main sorting: `f_strength_ret60`, `f_strength_vs_index20`, `f_trend_close_ma60_gap`.
- Remaining trend atoms downgraded to weak auxiliary:
  `f_strength_ret20`, `f_strength_rs60_xsec_q`, `f_trend_close_ma20_gap`,
  `f_trend_ma20_ma60_gap`, `f_trend_ma20_slope5`.
- Trend formula: `0.90*core + 0.10*weak_aux_mean`.

## Other axes (unchanged from v2.1)
- platform axis: compress_ratio(lower-better), range30(lower-better)
- chip axis: winner_rate, low_position120, chip_stability_std10(scoring only)
- industry axis: peer_strong_count + strength_5d auxiliary