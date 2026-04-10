# true_breakout_selector_v3_dualpath_draft

## Why dual-path
- Single-path linear ranking under-fits near-window multi-modal A and over-amplifies hot C under trend×industry resonance.
- Path A captures high-momentum frontline A; Path B recovers steady-structure / chip-support A.

## Universe
- Same as current selector baseline (main-board scope, list-days/liquidity/risk-name base filters unchanged).

## Path A: high_momentum_frontline
- Hard filters: rs20_xsec_q >= 0.72; close_ma20_gap >= 0.02.
- Scoring: 0.65*trend_core + 0.20*industry_frontline + 0.15*chip_quality.
- Heat-cap: trend & industry both extreme -> capped + penalty.
- Main target A subtype: high_momentum_frontline_A.
- Main C firewall: industry_heat_C / trend_chase_C.

## Path B: steady_structure
- Hard filters: rs20_xsec_q >= 0.60; close_ma20_gap >= 0.00 (trend floor only).
- Scoring: 0.50*platform + 0.40*chip + 0.10*trend_floor.
- Main target A subtype: steady_structure_A + chip_support_A + part of mixed_A.
- Main C firewall: platform_false_break_C.

## Output framework
- Path A and Path B ranked independently.
- Merge: candidate = selected_path_a OR selected_path_b.
- No entry/sell/execution assumptions in this stage.