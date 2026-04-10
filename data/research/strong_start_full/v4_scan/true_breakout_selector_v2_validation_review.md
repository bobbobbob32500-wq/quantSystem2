# true_breakout_selector_v2_validation_review

- window: 20251230 ~ 20260330 (57 trading days)
- A/C sample: 4029

## Purity and coverage
- v1 candidate A share: 0.2883
- v2 candidate A share: 0.3116
- v1 candidate size: 274
- v2 candidate size: 414

## Top-bucket A share
- Top10: v1 0.2639 -> v2 0.2605
- Top20: v1 0.2674 -> v2 0.2778
- Top30: v1 0.2883 -> v2 0.3116

## Rule health
     model  hard_filter_elimination_rate  score_total_unique  score_continuous  candidate_rate implicit_hard_filter_risk axis_dominance_proxy
v1_freeze1                      0.738397                3826              True        0.068007                  moderate  score_strength_axis
  v2_draft                      0.636138                4029              True        0.102755                  moderate     score_trend_axis

## Axis review (v2)
               axis  a_median  c_median  median_gap_a_minus_c       direction
score_industry_axis  0.518181  0.494105              0.024075        A_higher
   score_trend_axis  0.493537  0.474050              0.019487        A_higher
    score_chip_axis  0.510883  0.496835              0.014048        A_higher
score_platform_axis  0.515620  0.520755             -0.005135 A_lower_or_flat

- strongest axis: score_industry_axis
- weakest axis: score_platform_axis

Conclusion: selector-only validation; no entry/exit/execution assumptions.