# true_breakout_selector_v1_draft

Version: `selector_v1_draft`
Scope: selector only (no entry/exit execution design)

## A) Universe
- Main board only (SH/SZ mainboard)
- minimum listing days
- minimum liquidity floor
- risk-name exclusion (`ST/*ST` etc.)

## B) Hard filters (minimal, non-extreme)
- trend baseline pass: `f_trend_close_ma20_gap` above weak floor
- relative leadership pass: `f_strength_rs20_xsec_q` above weak floor
- industry front-rank weak gate: `f_ind_rank_pctchg` in acceptable top band (not overly strict)

## C) Scoring axes (selector core)
1. Strength axis
- `f_strength_ret20`, `f_strength_ret60`, `f_trend_ma20_ma60_gap`
2. Industry leadership axis
- `f_ind_strength_3d`, `f_ind_strength_5d`, `f_ind_rank_pctchg`
3. Chip quality axis
- `f_chip_concentration`, `f_chip_winner_rate`, `f_chip_stability_std10` (observe-weighted)
4. Auxiliary structure axis (low weight)
- `f_platform_range_best`, `f_platform_compress_ratio`

## D) Downgraded observations (not selector core)
- peak-structure family:
  - `f_chip_peak_count_sig`
  - `f_chip_secondary_peak_ratio`
  - `f_chip_peak_dominance`
  - `f_chip_single_peak_score`
- keep for monitoring only, not primary selection logic

## E) Explicit exclusions in this phase
- entry-trigger dominant fields are not selector core:
  - `f_k_pct_chg`
  - `f_k_body_to_atr`
  - `f_breakout_vol_ratio20`
  - `f_k_upper_shadow_ratio`
  - `f_up_down_vol_ratio20`

