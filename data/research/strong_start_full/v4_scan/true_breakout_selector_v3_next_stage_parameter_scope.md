# true_breakout_selector_v3_next_stage_parameter_scope

## Stage boundary
This document defines what can be tuned next, and what is structural (frozen).

## Tunable in next stage (coarse only)
- Path A / Path B quota allocation in `M1_quota_merge`.
- Path-internal cutoff levels (front-segment depth).
- Heat-cap intensity (cap level / penalty magnitude) in Path A.
- Small set of hard-filter thresholds (within current factors only).
- Axis weight coarse adjustments (within existing axes only).

## Not tunable (structural)
- Single-path vs dual-path decision.
- Path A / Path B role definitions.
- Output mechanism family (`M1_quota_merge` as base mechanism).
- Feature universe expansion / replacement.
- Introduction of entry/exit/execution logic.

## Parameter-stage objective
- Improve selector purity/coverage trade-off while preserving:
  - dual-path expression balance,
  - pseudo-C suppression,
  - boundary cleanliness (no trading fields).

## Explicitly not allowed in parameter stage
- Buy-point research.
- Sell-point research.
- Execution-path design.
- Full trading backtest optimization.
