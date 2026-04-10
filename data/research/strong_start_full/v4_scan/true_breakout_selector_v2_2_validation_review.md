# true_breakout_selector_v2_2_validation_review

- window: 20251230 ~ 20260330
- sample_n(A/C): 4029

## Core compare (v2.2 vs v2.1)
     model  window_a_share_full  candidate_n  candidate_a_n  candidate_c_n  candidate_a_share  candidate_c_share  selected_A  selected_C  missed_A  rejected_C  a_share_top10  a_share_top20  a_share_top30  a_share_lift_pts_vs_full_top10  a_share_lift_pts_vs_full_top20  a_share_lift_pts_vs_full_top30  sample_n_top10  sample_n_top20  sample_n_top30
v2.1_draft             0.353934          477            143            334           0.299790           0.700210         143         334      1283        2269       0.251748        0.29393       0.299790                       -0.102186                       -0.060004                       -0.054144           143.0           313.0           477.0
v2.2_draft             0.353934          477            151            326           0.316562           0.683438         151         326      1275        2277       0.251748        0.29393       0.316562                       -0.102186                       -0.060004                       -0.037372           143.0           313.0           477.0

## Rule health
     model  hard_filter_elimination_rate  score_total_unique  score_continuous axis_dominance_proxy  axis_dominance_share axis_imbalance_risk  trend_selectedA_minus_selectedC trend_wrong_ranking_risk
v2.1_draft                      0.487466                3173              True     score_trend_axis              0.291509                 low                        -0.052853                     high
v2.2_draft                      0.487466                3173              True     score_trend_axis              0.298173                 low                        -0.031082                     high

## Direct checks
- candidate A share: v2.1=0.2998, v2.2=0.3166
- selected_C: v2.1=334, v2.2=326
- selected_A: v2.1=143, v2.2=151
- trend_selectedA_minus_selectedC: v2.1=-0.0529, v2.2=-0.0311

Note: selector-only research validation; no entry/exit/execution/return backtest.