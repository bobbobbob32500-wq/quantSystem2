# strong_start breakout-B backtest fields contract

Version: `breakout_b_backtest_fields_contract_v1`

## Required fields for `backtest_trade_record`
1. `ts_code`
2. `signal_trade_date`
3. `execution_trade_date`
4. `trade_signal_class`
5. `execution_mode_candidate`
6. `entry_decision`
7. `exit_reason`
8. `risk_budget_tag`
9. `industry_cap_tag`
10. `validation_status`
11. `explain_summary`

## Recommended linkage fields
- `signal_event_id`
- `execution_candidate_event_id`
- `entry_event_id`
- `exit_event_id`
- `trade_validation_record_id`

## Value semantics
- `entry_decision`: `allow | abandon`
- `exit_reason`: one of fixed exit classes/reasons
- `risk_budget_tag`: `within_budget | daily_cap_hit | undefined`
- `industry_cap_tag`: `within_cap | industry_cap_hit | undefined`
- `validation_status`: `complete | incomplete | rejected_at_entry`

## Forbidden fields in this contract
- any performance field:
  - `pnl`, `return`, `return_pct`, `win_rate`, `sharpe`, `drawdown`
- any future-label field:
  - `mfe`, `mae`, `entry_possible`, forward/fwd return labels

