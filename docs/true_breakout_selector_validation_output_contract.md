# true_breakout_selector validation output contract

Version: `selector_validation_output_contract_v1`

## 1) true_breakout_selector_validation_set
Row grain: event-day (`ts_code`, `trade_date`)

Required fields:
- `ts_code`
- `trade_date`
- `label_abc` (A/C used in this phase)
- `pass_universe`
- `pass_hard_filters`
- `hard_filter_reasons`
- `score_total`
- `score_axis_strength`
- `score_axis_industry`
- `score_axis_chip`
- `score_axis_aux_platform` (optional if used)
- `is_selector_candidate`
- `rank_pct` (within-day or global spec-fixed)
- `rank_bucket` (Top10/20/30/Other)

## 2) true_breakout_selector_coverage_summary
Required fields:
- `sample_scope`
- `a_total`, `a_retained`, `a_coverage_rate`
- `c_total`, `c_retained`, `c_coverage_rate`
- `candidate_count`, `candidate_ratio`
- `candidate_a_share`

## 3) true_breakout_selector_ranking_summary
Required fields:
- `bucket_name`
- `event_count`
- `a_count`
- `a_share`
- `a_share_lift_vs_full`
- `median_score_total`

## 4) true_breakout_selector_rule_health_summary
Required fields:
- `hard_filter_elimination_rate`
- `score_bucket_density`
- `axis_contribution_rank`
- `downgraded_exclusion_impact_note`
- `risk_flag` (over-tight / over-loose / balanced)

## Forbidden fields
- any trading fields (`entry_*`, `exit_*`, `execution_*`)
- any performance fields (`return/pnl/winrate/sharpe/drawdown/PF`)

