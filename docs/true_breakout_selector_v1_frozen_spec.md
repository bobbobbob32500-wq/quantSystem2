# true_breakout_selector_v1_frozen_spec

Frozen baseline: `true_breakout_selector_v1_freeze1`  
Source: `true_breakout_selector_v1_draft` + small-range historical validation + tune1 comparison  
Decision: keep original v1, do **not** absorb tune1.

## 1) Universe (frozen)
- Main-board stocks only
- Minimum listing days constraint
- Minimum liquidity constraint
- Risk-name exclusion (`ST/*ST` class)

## 2) Hard filters (frozen)
- `f_trend_close_ma20_gap >= 0.02`
- `f_strength_rs20_xsec_q >= 0.70`
- `f_ind_rank_pctchg >= 0.80`

Design intent:
- keep necessary structural constraints
- avoid over-tight chaining

## 3) Scoring axes (frozen)
- Strength axis (`score_strength_axis`), weight `0.40`
- Industry leadership axis (`score_industry_axis`), weight `0.35`
- Chip quality axis (`score_chip_axis`), weight `0.20`
- Platform/structure auxiliary axis (`score_platform_axis`), weight `0.05`

## 4) Candidate threshold (frozen)
- Candidate shortlist: top `30%` within hard-filter-pass set (`rank_pct <= 0.30`)

## 5) Downgraded observations (frozen)
- Peak-structure family remains observation-only:
  - `f_chip_peak_count_sig`
  - `f_chip_secondary_peak_ratio`
  - `f_chip_peak_dominance`
  - `f_chip_single_peak_score`
- Entry-like trigger features are excluded from selector core:
  - `f_k_pct_chg`
  - `f_k_body_to_atr`
  - `f_breakout_vol_ratio20`
  - `f_k_upper_shadow_ratio`
  - `f_up_down_vol_ratio20`

## 6) Why tune1 not adopted
- tune1 gave only marginal candidate A-share lift
- but reduced A coverage and slightly weakened Top20 quality
- baseline v1 kept better overall balance (coverage/purity/health)

## 7) Freeze rule
- No in-place edits on `true_breakout_selector_v1_freeze1`
- Any future change must use a new version tag

