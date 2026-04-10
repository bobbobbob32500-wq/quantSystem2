# true_breakout_selector_v3_release_note

## Release type
Selector main-structure freeze candidate (`freeze_candidate_1`).

## What is frozen
- Dual-path selector architecture (Path A + Path B).
- Output mechanism: `M1_quota_merge`.
- Selector output contract and audit boundaries.

## Why this candidate is accepted
- Solves prior bottleneck: output mechanism, not factor list.
- Keeps both paths active (avoids Path B silence).
- Improves candidate A-share above full-sample baseline in near-window structural validation.

## What is explicitly not included
- Entry timing design.
- Exit design.
- Execution assumptions.
- Trading backtest and performance claims.

## Next correct stage
- Parameter phase (coarse tuning) within frozen structure scope.
