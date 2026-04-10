# true_breakout_selector_v2_1_draft

## Universe
- Same as v2 draft (main-board-only, minimum listing days, minimum liquidity, risk-name exclusion).

## Hard filters (revised)
- Keep: `f_strength_rs20_xsec_q >= 0.72`
- Removed from hard filter: `f_chip_stability_std10` (moved to chip scoring axis).

## Scoring axes (revised)
- trend axis: core `f_strength_rs20_xsec_q`, aux `f_trend_close_ma20_gap` (de-collinearity by dropping duplicated trend items).
- platform axis: `f_platform_compress_ratio` (lower-better), `f_platform_range30` (lower-better).
- chip axis: `f_chip_winner_rate`, `f_chip_low_position120`, plus downgraded-scoring `f_chip_stability_std10`.
- industry axis: `f_ind_peer_strong_count` + light `f_ind_strength_5d` (auxiliary purifier, reduced amplification).

## Weights (revised)
- trend: 0.50
- platform: 0.10
- chip: 0.25
- industry: 0.15

## Candidate output
- Keep rank-based output framework (top10/top20/top30 buckets for selector validation).