# true_breakout_selector_v2_1_validation_review

- window: 20251230 ~ 20260330
- sample_n(A/C): 4029

## Core compare (v2 vs v2.1)
     model  window_a_share_full  a_total  c_total  a_hard_pass_rate  c_hard_pass_rate  candidate_n  candidate_a_n  candidate_c_n  candidate_a_share  candidate_c_share  a_share_top10  a_share_top20  a_share_top30  a_share_lift_pts_vs_full_top10  a_share_lift_pts_vs_full_top20  a_share_lift_pts_vs_full_top30  sample_n_top10  sample_n_top20  sample_n_top30  missed_A  rejected_C  selected_A  selected_C
  v2_draft             0.353934     1426     2603          0.372370          0.359201          414            129            285           0.311594           0.688406       0.260504       0.277778       0.311594                       -0.093430                       -0.076156                       -0.042340           119.0           270.0           414.0      1297        2318         129         285
v2.1_draft             0.353934     1426     2603          0.546283          0.494045          477            143            334           0.299790           0.700210       0.251748       0.293930       0.299790                       -0.102186                       -0.060004                       -0.054144           143.0           313.0           477.0      1283        2269         143         334

## Rule health
     model  hard_filter_elimination_rate  candidate_rate  score_total_unique  score_continuous implicit_hard_filter_risk axis_dominance_proxy  axis_dominance_share axis_imbalance_risk
  v2_draft                      0.636138        0.102755                4029              True                  moderate     score_trend_axis              0.310648                 low
v2.1_draft                      0.487466        0.118392                3173              True                  moderate     score_trend_axis              0.291509                 low

## Axis review
     model                axis  a_median  c_median  a_minus_c  selected_a_median  selected_c_median  selected_a_minus_c
  v2_draft    score_trend_axis  0.493537  0.474050   0.019487           0.891739           0.916824           -0.025085
  v2_draft score_platform_axis  0.515620  0.520755  -0.005135           0.544411           0.563335           -0.018924
  v2_draft     score_chip_axis  0.510883  0.496835   0.014048           0.686523           0.657275            0.029247
  v2_draft score_industry_axis  0.518181  0.494105   0.024075           0.599653           0.619074           -0.019422
v2.1_draft    score_trend_axis  0.509084  0.476299   0.032785           0.861253           0.914106           -0.052853
v2.1_draft score_platform_axis  0.505293  0.506652  -0.001359           0.444825           0.336030            0.108795
v2.1_draft     score_chip_axis  0.521514  0.507817   0.013697           0.740659           0.713338            0.027321
v2.1_draft score_industry_axis  0.530591  0.494322   0.036268           0.641878           0.629716            0.012162

## Direct answers
- candidate A share fixed? v2=0.3116, v2.1=0.2998, delta=-0.0118
- missed_A improved? v2=1297, v2.1=1283, delta=-14
- selected_C reduced? v2=285, v2.1=334, delta=+49
- platform axis selected_A-selected_C (v2.1): +0.1088
- ready for candidate-freeze gate? no

Note: research-layer validation only; no entry/exit/execution/return backtest.