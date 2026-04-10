# true_breakout_selector_v1_output_contract

Frozen output contract for `true_breakout_selector_v1_freeze1`.

## Required fields
- `ts_code`
- `trade_date`
- `pass_hard_filters`
- `score_total`
- `score_strength_axis`
- `score_industry_axis`
- `score_chip_axis`
- `score_platform_axis`
- `is_candidate`
- `rank_pct`
- `rank_bucket`
- `selector_reject_reason`
- `selector_explain`

## Purpose boundary
- For selector validation and candidate-list quality control only
- Not for entry/exit execution
- Not for trading performance interpretation

## Explicitly forbidden in this contract
- Buy-point/entry trigger fields
- Execution fields (`execution_*`, `entry_*`, `exit_*`)
- Any return/performance fields (`pnl`, `return`, `win_rate`, `drawdown`, `sharpe`, `PF`)

