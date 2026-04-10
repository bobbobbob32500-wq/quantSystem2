# strong_start breakout-B event flow spec

Version: `breakout_b_event_flow_spec_v1`

## 1) Event sequence (minimal)
1. `signal_event` (time: T close)
2. `execution_candidate_event` (time: T+1 intraday window)
3. `entry_event` (time: within T+1 execution window)
4. `exit_event` (time: future bars under frozen exit-rule framework)
5. `trade_validation_record` (time: trade lifecycle close for validation logging)

## 2) Event contracts

### signal_event (T close)
- Allowed fields:
  - frozen signal outputs (`is_candidate_after_filters`, `score_total`, trigger states, explain fields)
- Forbidden:
  - any T+1 or future outcome fields.

### execution_candidate_event (T+1 intraday)
- Allowed fields:
  - T signal fields
  - T+1 boundary-observable fields only (intraday confirm boundaries)
- Forbidden:
  - future return labels, MAE/MFE, any post-hoc performance fields.

### entry_event
- Generated only from execution candidate event:
  - `entry_decision=allow` only for `execution_state=ready`.

### exit_event
- Rule-class trigger only:
  - `structural_stop`
  - `time_stop`
  - `max_hold_or_momentum_decay`
- No performance scoring in this spec.

### trade_validation_record
- Purpose:
  - keep full lifecycle auditable and reproducible.
- Contains:
  - linked signal/execution/entry/exit event ids and reason fields.

## 3) Anti-misalignment guard (T vs T+1)
- T-phase and T+1-phase fields must be physically separated in pipeline steps.
- No event may read fields from a later phase.
- Any missing phase data -> explicit reject/risk logging, never silent fallback.

