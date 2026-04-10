# strong_start_research_v4_frozen_spec

## 1) Frozen Baseline Identity
- Baseline name: `strong_start_research_v4_freeze1`
- Strategy module name: `strong_start_research_v4`
- Frozen default profile: `neutral`
- `loose/strict` usage: sensitivity reference only

## 2) Strategy Main Axes
- Axis A: trend/strength continuity
- Axis B: industry front-rank participation
- Axis C: base chip quality
- Trigger confirmation: breakout + momentum + quality

This baseline is designed for **research structural screening and explainability**, not for return claims.

## 3) Final Four-Layer Structure

### Layer 1: Base Filter
Purpose:
- Remove clearly unsuitable events
- Keep filter set small to avoid old chain-overkill

Frozen scope:
- universe constraints (mainboard / listing days / liquidity / risk-name exclusion)
- light hard prefilter on:
  - `f_trend_close_ma20_gap`
  - `f_strength_rs20_xsec_q`
  - weak gate on `f_ind_rank_pctchg`

### Layer 2: Continuous Scoring
Purpose:
- Add evidence by degree, not binary veto

Frozen scoring axes:
- strength axis
- industry-front axis
- chip-base axis

Frozen sanity placements:
- `f_chip_stability_std10`: scoring observation only
- `f_chip_winner_rate`: range scoring only
- `f_ind_rank_pctchg`: scoring core item retained

### Layer 3: Trigger Confirmation
Purpose:
- Confirm “just-started” behavior near event timing

Frozen trigger groups:
- breakout
- momentum
- quality

Key trigger features include:
- `f_k_pct_chg`
- `f_k_body_to_atr`
- `f_breakout_vol_ratio20`
- `f_up_down_vol_ratio20`
- `f_k_upper_shadow_ratio`

### Layer 4: Downgraded Observation
Purpose:
- Keep weak/high-missing/redundant features visible but non-decisive

Typical frozen downgraded families:
- static platform weak features
- weak peak-structure features
- high-missing or low incremental explanatory features

## 4) Differences vs Legacy strong_start
- Kept:
  - strong-start directionality and event-level discipline
- Relaxed:
  - over-tight chain hard gates (especially by tune1 weak-gate easing)
- Moved:
  - many “would-be hard veto” factors into scoring or trigger
- Downgraded:
  - weak static platform and weak peak-structure conditions

## 5) Known Boundaries (Frozen, Not Further Tuned in freeze1)
- strict profile remains relatively tighter
- `quality:k_body_to_atr` is still the top trigger fail source
- `f_ind_rank_pctchg` trigger assist may still be somewhat strong and can be weakened in next version

These are known boundaries of `freeze1`, not in-scope for more edits in this freeze cycle.

## 6) What This Baseline Is / Is Not
- Is:
  - runnable structural research baseline
  - auditable with layer-level diagnostics
  - explainable at event-level
- Is not:
  - backtest-validated trading strategy
  - performance-certified signal system

