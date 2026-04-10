# strong_start breakout-B release note

Release: `breakout_b_freeze1`  
Type: execution-assumption freeze (non-performance)

## Included
- Frozen breakout-B execution timing and state priority.
- Frozen field naming:
  - `execution_state` as tri-state (`ready/reject/risk`)
  - `execution_ready_flag` as boolean derived flag
- Frozen weak-confirmation refinement rules:
  - R1 (`risk -> ready`)
  - R2 (`risk -> reject`)
- Frozen three-state boundary:
  - `ready`
  - `reject`
  - `risk`
- Frozen minimal fields contract and acceptance checklist.

## Explicitly excluded
- No pullback logic.
- No backtest.
- No performance statistics.
- No parameter search.

## Freeze decision
- This version is closed for further tuning.
- Any future rule change must use a new version tag, not in-place edits to `breakout_b_freeze1`.
