# strong_start_research_v4_output_contract

## Contract Purpose
Define final output schema and usage boundary for `strong_start_research_v4_freeze1`.

## A) Required Scan Output Fields
At minimum, each scan row must include:
- `is_candidate_after_filters`
- `score_total`
- `trigger_status`
- `signal_ready`
- `filter_reject_reasons`
- `score_details`
- `trigger_details`
- `downgraded_observations`
- `explain_json`

## B) Structural Validation Outputs
Used for layer-health checks:
- daily/period funnel counts
- filter reason frequency
- trigger fail reason frequency
- score distribution summary by profile
- profile gradient consistency checks

## C) Research Explainability Outputs
Used for manual review and structural diagnosis:
- event-level explain payload (`explain_json`)
- sampled before/after explain diffs
- layer pass/fail reasons
- feature contribution traces in `score_details`

## D) Misuse Prohibition
The above outputs must **not** be interpreted as:
- trading backtest result
- expected return evidence
- strategy profitability claim
- win-rate / drawdown proof

## E) Interpretation Boundary Tag (Recommended)
All reports should carry a boundary line:
`Structure-only diagnostics. No performance inference allowed.`

