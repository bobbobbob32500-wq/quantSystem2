# true_breakout_selector_v3_freeze_candidate_2

## Positioning
- Coarse-parameter candidate on frozen v3 structure (no structure change).

## Fixed structure
- Dual-path remains unchanged.
- Output mechanism remains `M1_quota_merge`.

## Coarse parameters (winner)
- quota_a: 1
- quota_b: 2
- heat_cap: high
- path_a_cutoff_pct: 10
- path_b_cutoff_pct: 20

## Validation snapshot
- Main window A-share: 0.4410
- Main window sample n: 161
- Baseline A-share: 0.3539
- Confirm window A-share: 0.4074
- Confirm window sample n: 162

## Scope boundary
- This file freezes only coarse selector parameters.
- It does NOT include buy-point/sell-point/execution/backtest optimization.