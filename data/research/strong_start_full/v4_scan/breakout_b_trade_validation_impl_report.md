# breakout-B trade validation impl report

## Scope
- breakout-B only
- no backtest / no performance stats / no parameter search

## Tables generated
- trade_signal_event_breakout_b.parquet: 124 rows
- execution_candidate_event_breakout_b.parquet: 124 rows
- entry_event_breakout_b.parquet: 124 rows
- exit_event_breakout_b.parquet: 23 rows
- trade_validation_record_breakout_b.parquet: 124 rows

## Minimal field contracts
- trade_signal_event_breakout_b:
  - signal_event_id, ts_code, trade_date, trade_signal_class, score_total, trigger_status, trigger_groups_passed, explain_json
- execution_candidate_event_breakout_b:
  - execution_candidate_event_id, signal_event_id, execution_mode_candidate, execution_state, execution_ready_flag, execution_reject_reason, execution_risk_tag, key_reason_1/2/3
- entry_event_breakout_b:
  - entry_event_id, signal_event_id, entry_decision, entry_decision_reason, entry_decision_time_tag, risk_per_trade_budget
- exit_event_breakout_b:
  - exit_event_id, trade_id, entry_trade_date, exit_event_date, exit_rule_class, exit_trigger_reason
- trade_validation_record_breakout_b:
  - trade_validation_record_id, signal_event_id, execution_candidate_event_id, entry_event_id, exit_event_id, validation_chain_complete

## Chain integrity
- signal -> execution matched: 124
- execution -> entry matched: 124
- entry -> exit matched: 23
- complete validation chain rows: 124

## Top not-entry reasons
- not_ready_state: 97
- risk_cap_daily_limit: 4

## Top exit event types
- structural_stop: 17
- time_stop: 5
- max_hold_or_momentum_decay: 1

## Data leakage guard
- No future performance fields read into signal/execution/entry decisions.