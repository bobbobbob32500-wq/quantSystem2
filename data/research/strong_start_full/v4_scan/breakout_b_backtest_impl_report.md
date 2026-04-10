# breakout-B backtest impl report

## Scope
- breakout-B only
- minimal backtest chain implementation only
- no performance metrics, no parameter search

## Window
- trade_date range: 20260309 ~ 20260327
- days: 15

## Chain counts
- signal: 124
- execution_candidate: 124
- entry allow: 23
- exit generated: 23
- backtest_trade_record: 124

## QC
- each_allow_has_one_exit: True
- no_exit_before_entry: True
- missing_key_rows: 0
- daily_cap_effective: True
- industry_cap_effective: True
- reject_risk_mis_entered_count: 0
- forbidden_field_hits: []

## Top not-entry reasons
- not_ready_state: 97
- risk_cap_daily_limit: 4

## Top exit reasons
- structural_stop: 17
- time_stop: 5
- max_hold_or_momentum_decay: 1