# true_breakout_selector_v2_draft

## A. Universe
- main-board only
- list_days >= 180
- liquidity floor (amount >= 1e5, DB scale)
- ST/*ST excluded

## B. Hard filters (small and necessary)
- principle: only stable + low-missing + non-entry-like factors
- f_strength_rs20_xsec_q
- f_chip_stability_std10

## C. Scoring axes
- trend-strength axis:
  - f_trend_close_ma60_gap
  - f_strength_rs60_xsec_q
  - f_trend_close_ma20_gap
- platform-structure axis:
  - f_platform_range20
  - f_platform_len
- chip-quality axis:
  - f_chip_winner_rate
  - f_chip_low_position120
  - f_chip_secondary_peak_ratio
  - f_chip_peak_count_sig
- industry-leadership axis:
  - f_ind_peer_strong_count
  - f_ind_strength_5d
- volume-rhythm axis (auxiliary):

## D. Downgraded observation items
- all trigger-like K-line set (research only, not selector core):
  - f_k_pct_chg, f_k_body_to_atr, f_breakout_vol_ratio20, f_k_upper_shadow_ratio, f_up_down_vol_ratio20
- high-redundancy items from redundancy audit

## E. Candidate output framework
- daily ranking output from score_total (no fixed TopN target at this stage)
- candidate count/rank cut to be validated in next selector-only validation stage

Note: this is a selector draft, not a trading strategy.