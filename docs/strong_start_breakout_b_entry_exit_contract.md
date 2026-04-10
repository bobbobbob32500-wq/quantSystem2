# strong_start breakout-B entry-exit contract

Version: `breakout_b_entry_exit_contract_v1`

## A) Entry event minimal fields
- `ts_code`
- `trade_date`
- `trade_signal_class`
- `execution_mode_candidate`
- `execution_state`
- `execution_ready_flag`
- `execution_risk_tag`
- `execution_reject_reason`
- `execution_assumption_note`
- `key_reason_1`
- `key_reason_2`
- `key_reason_3`
- `entry_decision` (`allow` / `abandon`)
- `entry_decision_reason`
- `entry_decision_time_tag` (`T1_intraday_window`)

## B) Entry decision rules
- `allow` iff:
  - `execution_state=ready`
  - `execution_ready_flag=true`
- `abandon` iff:
  - `execution_state in {reject, risk}`

## C) Exit event minimal fields (design only)
- `ts_code`
- `entry_trade_date`
- `exit_event_date`
- `exit_rule_class` (`structural_stop` / `time_stop` / `max_hold_or_momentum_decay`)
- `exit_trigger_flag`
- `exit_trigger_reason`
- `exit_decision_note`

## D) Boundary constraints
- No future-return/performance fields in entry decision layer.
- Exit schema frozen as rule-framework only; performance evaluation is out of scope.

