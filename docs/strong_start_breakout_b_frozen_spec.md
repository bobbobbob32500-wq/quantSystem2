# strong_start breakout-B frozen spec

Version: `breakout_b_freeze1`  
Scope: breakout channel only, mode B only (`T+1 intraday continuation confirm`)  
Status: frozen (no further tuning in this version)

## 1) Timing freeze
- T-day signal confirm time: **after T-day close**.
- T+1 execution judgment window: **T+1 intraday observable range** (open/high/low/close).

## 2) Core state logic freeze
Priority order is fixed:
1. `reject` hard boundaries first.
2. `ready` continuation-confirmed boundaries second.
3. `risk` for unresolved boundary remainder.

Field naming freeze:
- `execution_state` is the tri-state field (`ready | reject | risk`).
- `execution_ready_flag` is boolean and derived from state:
  - `true` iff `execution_state=ready`
  - `false` otherwise

## 3) Reject boundaries (unchanged hard rules)
- `reject_limit_lock_like`
- `reject_high_gap_away`
- `reject_gap_too_large`
- `reject_intraday_breakdown`
- `reject_intraday_confirm_fail`

If any hard reject boundary is hit, output must be:
- `execution_state=reject`
- `execution_ready_flag=false`

## 4) Ready baseline (unchanged)
- Use existing breakout-B continuation-confirmed ready rule from prior frozen implementation.
- No widening/narrowing in this freeze.

## 5) Refined weak-confirmation split (frozen R1/R2)
These two rules only apply to prior weak bucket (`intraday_confirmation_weak`):

- R1 (`risk -> ready`):
  - `close_ret_t1 >= 0.012`
  - `t1_close_pos >= 0.60`
  - `low_break > -0.02`

- R2 (`risk -> reject`):
  - `close_ret_t1 <= 0`
  - OR (`t1_close_pos < 0.25` AND `t1_upper_shadow_ratio >= 0.60`)

## 6) Risk boundary retention
After reject + ready + R1/R2 assignment:
- Remaining unresolved weak-confirmation cases stay as:
  - `execution_state=risk`
  - `execution_ready_flag=false`
  - `execution_risk_tag=intraday_confirmation_weak_refined`

This retained risk zone is intentional and must not be forced into ready/reject in this freeze version.
