# strong_start breakout-B backtest min spec

Version: `breakout_b_backtest_min_spec_v1`  
Scope: breakout-B only, spec-only (no run, no performance output)

## 1) Backtest unit and fixed event order
Backtest unit: one `backtest_trade_record` mapped from one signal lifecycle.

Fixed order:
1. `signal_event` (T close)
2. `execution_candidate_event` (T+1 intraday)
3. `entry_event`
4. `exit_event`
5. `backtest_trade_record`

## 2) Field boundary by stage
- `signal_event`:
  - Allowed: T-day signal fields (filters/scores/trigger/explain).
  - Forbidden: any T+1+ result or forward labels.
- `execution_candidate_event`:
  - Allowed: T-day signal + T+1 boundary-observable execution fields.
  - Forbidden: any post-entry/post-exit results.
- `entry_event`:
  - Allowed: execution state + risk constraints + ranking result.
  - Forbidden: any exit/outcome/performance fields.
- `exit_event`:
  - Allowed: post-entry observable rule triggers only.
  - Forbidden: any optimization/performance target field.
- `backtest_trade_record`:
  - Allowed: lifecycle decisions/labels/reasons only.
  - Forbidden: PnL/return/sharpe/drawdown and any performance metric.

## 3) Minimal entry backtest spec (definition only)
- Entry eligible only when:
  - `trade_signal_class=breakout`
  - `execution_mode_candidate=breakout_b_t1_intraday_confirm`
  - `execution_state=ready` and `execution_ready_flag=true`
- If same-day candidates exceed cap:
  - sort by `score_total` desc
  - tie-break by trigger consistency score/flags
  - apply `max_new_entries_per_day`
  - apply `max_entries_per_industry_per_day`
- If cap hit:
  - keep `entry_decision=abandon`
  - reason = `risk_cap_daily_limit` or `risk_cap_industry_limit`
- If `execution_state != ready`:
  - `entry_decision=abandon`
  - reason = `not_ready_state`
- If `execution_state = risk`:
  - always excluded from backtest entry in this min spec.

## 4) Minimal exit backtest spec (definition only)
- Exit rule classes:
  1. `structural_stop`
  2. `time_stop`
  3. `max_hold_or_momentum_decay`
- Same-day multi-trigger priority (fixed):
  1. `structural_stop`
  2. `max_hold_or_momentum_decay`
  3. `time_stop`
- Conflict rule:
  - one trade can have only one final exit event.
  - apply first-hit-by-priority; lower-priority triggers are dropped.

