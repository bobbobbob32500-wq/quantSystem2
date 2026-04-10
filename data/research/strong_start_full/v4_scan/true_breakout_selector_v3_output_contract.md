# true_breakout_selector_v3_output_contract

## Scope
Selector-layer output contract only.

## Required fields
- `ts_code`
- `trade_date`
- `path_source` (`A` / `B`)
- `pass_hard_filters`
- `score_total`
- `score_trend_axis`
- `score_platform_axis`
- `score_chip_axis`
- `score_industry_axis`
- `is_candidate`
- `rank_in_path`
- `rank_global_after_merge`
- `selector_reject_reason`
- `selector_explain`

## Field boundary rules
### Allowed
- T-day visible selector features and path-level ranking outputs.

### Forbidden
- Any entry/exit/execution fields.
- Any buy/sell signal fields.
- Any future-window or forward-looking fields.
- Any return/PnL/performance fields.

## Contract notes
- `path_source` is mandatory for dual-path auditability.
- `selector_explain` must remain human-readable and include path reason + reject reason when rejected.
