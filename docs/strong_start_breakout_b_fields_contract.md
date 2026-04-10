# strong_start breakout-B fields contract

Version: `breakout_b_freeze1`  
Table name: `trade_execution_assumption_table_breakout_b_sample` (or same schema successor)

## Required columns
1. `ts_code`  
2. `trade_date`  
3. `trade_signal_class`  
4. `execution_mode_candidate`  
5. `execution_state`  
6. `execution_ready_flag`  
7. `execution_risk_tag`  
8. `execution_reject_reason`  
9. `execution_assumption_note`  
10. `key_reason_1`  
11. `key_reason_2`  
12. `key_reason_3`  

## Value constraints
- `trade_signal_class`: fixed to `breakout` for this spec.
- `execution_mode_candidate`: fixed to `breakout_b_t1_intraday_confirm`.
- `execution_state`: only `ready | reject | risk`.
- `execution_ready_flag`: boolean; `true` iff `execution_state=ready`, else `false`.
- `execution_reject_reason`: required when `execution_state=reject`, else empty allowed.
- `execution_risk_tag`: required when `execution_state=risk`, else `none` recommended.
- `key_reason_1/2/3`: must be short, human-readable, and explain the final state assignment.

## Data boundary constraints
- Use only T-day signal fields and T+1 observable execution boundary fields.
- No future return or performance fields are allowed.
