# true_breakout_selector_v3_output_mechanism_review

## Frozen facts
1) Path A internal ranking effective
2) Path B internal ranking effective
3) Naive merge amplifies C
4) Winner-take-all path selection suppresses Path B expression
5) Core bottleneck is output mechanism, not factor list

- near window: 20251230 ~ 20260330
- full-sample A baseline: 0.3539

## Model compare
                   model  sample_n  a_n  c_n  a_share  a_share_lift_vs_baseline_pts  a_share_lift_vs_S0_pts  a_share_lift_vs_S3_pts
           S0_single_v22       477  151  326 0.316562                     -0.037338                0.000000               -0.031419
     S3_dual_merge_naive       842  293  549 0.347981                     -0.005919                0.031419                0.000000
S4_dual_merge_controlled       497  172  325 0.346076                     -0.007824                0.029515               -0.001905
       S5_path_selection       247   80  167 0.323887                     -0.030013                0.007325               -0.024094
          M1_quota_merge       209   87  122 0.416268                      0.062368                0.099706                0.068287
   M2_primary_supplement       160   64   96 0.400000                      0.046100                0.083438                0.052019
M3_rank_normalized_merge       227   92  135 0.405286                      0.051386                0.088724                0.057305

## Path contribution
                   model  selected_n  path_a_only_n  path_b_only_n  path_both_n  path_a_any_share  path_b_any_share
           S0_single_v22         477            183             71          118          0.631027          0.396226
     S3_dual_merge_naive         842            317            404          121          0.520190          0.623515
S4_dual_merge_controlled         497            174            220          103          0.557344          0.649899
       S5_path_selection         247            174              0           73          1.000000          0.295547
          M1_quota_merge         209             75             78           56          0.626794          0.641148
   M2_primary_supplement         160             75             39           46          0.756250          0.531250
M3_rank_normalized_merge         227             80            118           29          0.480176          0.647577

## C failure-mode control
                   model                 c_mode  total_c_n  selected_c_n  selected_rate_in_mode
           S0_single_v22        industry_heat_C        317           172               0.542587
           S0_single_v22          trend_chase_C         47             1               0.021277
           S0_single_v22 platform_false_break_C        430            86               0.200000
           S0_single_v22      chip_distortion_C         90             0               0.000000
           S0_single_v22         mixed_pseudo_C       1719            67               0.038976
     S3_dual_merge_naive        industry_heat_C        317           197               0.621451
     S3_dual_merge_naive          trend_chase_C         47             2               0.042553
     S3_dual_merge_naive platform_false_break_C        430            79               0.183721
     S3_dual_merge_naive      chip_distortion_C         90            36               0.400000
     S3_dual_merge_naive         mixed_pseudo_C       1719           235               0.136707
S4_dual_merge_controlled        industry_heat_C        317           127               0.400631
S4_dual_merge_controlled          trend_chase_C         47             0               0.000000
S4_dual_merge_controlled platform_false_break_C        430            39               0.090698
S4_dual_merge_controlled      chip_distortion_C         90            24               0.266667
S4_dual_merge_controlled         mixed_pseudo_C       1719           135               0.078534
       S5_path_selection        industry_heat_C        317           105               0.331230
       S5_path_selection          trend_chase_C         47             0               0.000000
       S5_path_selection platform_false_break_C        430            37               0.086047
       S5_path_selection      chip_distortion_C         90             0               0.000000
       S5_path_selection         mixed_pseudo_C       1719            25               0.014543
          M1_quota_merge        industry_heat_C        317            58               0.182965
          M1_quota_merge          trend_chase_C         47             0               0.000000
          M1_quota_merge platform_false_break_C        430            13               0.030233
          M1_quota_merge      chip_distortion_C         90             9               0.100000
          M1_quota_merge         mixed_pseudo_C       1719            42               0.024433
   M2_primary_supplement        industry_heat_C        317            55               0.173502
   M2_primary_supplement          trend_chase_C         47             0               0.000000
   M2_primary_supplement platform_false_break_C        430            13               0.030233
   M2_primary_supplement      chip_distortion_C         90             6               0.066667
   M2_primary_supplement         mixed_pseudo_C       1719            22               0.012798
M3_rank_normalized_merge        industry_heat_C        317            36               0.113565
M3_rank_normalized_merge          trend_chase_C         47             0               0.000000
M3_rank_normalized_merge platform_false_break_C        430            10               0.023256
M3_rank_normalized_merge      chip_distortion_C         90            14               0.155556
M3_rank_normalized_merge         mixed_pseudo_C       1719            75               0.043630

## Monthly stability (A share)
 month                    model  sample_n  a_share
202512      S3_dual_merge_naive        24 0.750000
202601      S3_dual_merge_naive       317 0.406940
202602      S3_dual_merge_naive       167 0.485030
202603      S3_dual_merge_naive       334 0.194611
202512           M1_quota_merge         7 0.857143
202601           M1_quota_merge        79 0.405063
202602           M1_quota_merge        50 0.560000
202603           M1_quota_merge        73 0.287671
202512    M2_primary_supplement         5 0.800000
202601    M2_primary_supplement        60 0.383333
202602    M2_primary_supplement        39 0.589744
202603    M2_primary_supplement        56 0.250000
202512 M3_rank_normalized_merge         8 0.625000
202601 M3_rank_normalized_merge        80 0.437500
202602 M3_rank_normalized_merge        56 0.517857
202603 M3_rank_normalized_merge        83 0.277108
202512        S5_path_selection         9 0.666667
202601        S5_path_selection        97 0.350515
202602        S5_path_selection        52 0.557692
202603        S5_path_selection        89 0.123596

## Key judgement
- best by A-share: M1_quota_merge (0.4163)
- above baseline? yes
Note: selector-only structure validation; no buy/sell/exec/backtest return metrics.