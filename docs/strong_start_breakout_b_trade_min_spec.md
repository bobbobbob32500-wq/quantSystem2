# strong_start breakout-B trade min spec

Version: `breakout_b_trade_min_spec_v1`  
Scope: breakout-B only, non-performance design

## 1) Minimal entry spec
- Signal confirmation time: T-day close (from frozen breakout-B signal output).
- Order-eligibility judgment time: T+1 intraday boundary window.
- Entry event definition:
  - `trade_signal_class=breakout`
  - `execution_mode_candidate=breakout_b_t1_intraday_confirm`
  - `execution_state=ready`
  - `execution_ready_flag=true`
- Allow-entry:
  - all hard reject boundaries not hit
  - weak-confirmation refinement resolved to ready (or baseline ready)
- Entry-abandon:
  - any reject boundary hit
  - unresolved risk boundary kept as `execution_state=risk`

## 2) Minimal exit spec (framework only)
- Structural stop exit:
  - trigger when post-entry structure break condition is true.
- Time stop exit:
  - trigger when max holding bars reached without continuation confirmation.
- Max-hold / momentum-decay exit:
  - trigger when fixed holding cap reached OR momentum-decay condition true.

Note: no optimization, no performance claims in this version.

## 3) Minimal risk spec
- Single-name risk cap: fixed per-trade risk budget (config-driven, no optimization).
- Max candidates per day: fixed cap to prevent over-expansion.
- Sector concentration cap: max simultaneous names in same industry bucket.
- Candidate ranking: use existing research outputs only:
  - primary: `score_total`
  - secondary: trigger explain quality (breakout/momentum/quality consistency).

## 4) Minimal event-flow binding
- `signal_event(T)` -> `execution_candidate_event(T+1)` -> `entry_event` -> `exit_event` -> `trade_validation_record`
- Strict anti-leakage:
  - signal phase: T-visible fields only
  - execution phase: T+1 boundary-observable fields only
  - no future-return fields at any stage

