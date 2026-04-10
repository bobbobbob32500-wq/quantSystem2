# true_breakout_ahigh_refine_failure_report

## Quadrant counts
- kept_Ahigh: 8
- dropped_Ahigh: 9
- kept_C: 31
- dropped_C: 40
- Ahigh_keep_rate: 0.4706
- C_drop_rate: 0.5634

## Why Ahigh refine failed (summary)
- It raised Ahigh share mainly by shrinking pool size, but C retention stayed high.
- Kept C still dominated by mixed_pseudo / platform_false_break / industry_heat patterns.
- Ahigh retention is incomplete, especially non-dominant Ahigh subtypes.

## kept_Ahigh vs dropped_Ahigh
             group                     factor  kept_n  dropped_n  kept_median  dropped_median  kept_minus_dropped
Ahigh_keep_vs_drop    score_trend_axis_single       8          9     0.904884        0.878453            0.026431
Ahigh_keep_vs_drop score_platform_axis_single       8          9     0.339679        0.573511           -0.233831
Ahigh_keep_vs_drop     score_chip_axis_single       8          9     0.811855        0.691685            0.120171
Ahigh_keep_vs_drop score_industry_axis_single       8          9     0.619106        0.278556            0.340550
Ahigh_keep_vs_drop     f_strength_rs20_xsec_q       8          9     0.967307        0.944322            0.022985
Ahigh_keep_vs_drop  f_platform_compress_ratio       8          9     0.609506        0.429688            0.179819
Ahigh_keep_vs_drop         f_chip_winner_rate       8          9     0.989134        0.950204            0.038930
Ahigh_keep_vs_drop    f_ind_peer_strong_count       8          9    18.500000        3.000000           15.500000
Ahigh_keep_vs_drop                score_total       8          9     0.862099        0.757324            0.104775

## Ahigh subtype keep/drop
 core_keep             ahigh_subtype  n
     False high_momentum_frontline_A  3
     False               mixed_Ahigh  5
     False   steady_structure_chip_A  1
      True high_momentum_frontline_A  8

## kept_C vs dropped_C
         group                     factor  kept_n  dropped_n  kept_median  dropped_median  kept_minus_dropped
C_keep_vs_drop    score_trend_axis_single      31         40     0.890736        0.701342            0.189394
C_keep_vs_drop score_platform_axis_single      31         40     0.335560        0.705739           -0.370178
C_keep_vs_drop     score_chip_axis_single      31         40     0.808155        0.699891            0.108264
C_keep_vs_drop score_industry_axis_single      31         40     0.695408        0.476226            0.219182
C_keep_vs_drop     f_strength_rs20_xsec_q      31         40     0.954895        0.832935            0.121960
C_keep_vs_drop  f_platform_compress_ratio      31         40     0.651899        0.417192            0.234707
C_keep_vs_drop         f_chip_winner_rate      31         40     0.989864        0.977145            0.012719
C_keep_vs_drop    f_ind_peer_strong_count      31         40    20.000000        6.000000           14.000000
C_keep_vs_drop                score_total      31         40     0.849304        0.764296            0.085007

## C reasons among kept_C (hard-to-kill C)
 core_keep      selected_c_reason  n
      True         mixed_pseudo_C 11
      True platform_false_break_C 10
      True        industry_heat_C  6

## Keep-Ahigh / Kill-C conflict audit
                    factor  gain_Ahigh_keep_minus_drop  gain_C_keep_minus_drop                     tag
   score_trend_axis_single                    0.026431                0.189394 conflict_same_direction
    score_chip_axis_single                    0.120171                0.108264 conflict_same_direction
score_industry_axis_single                    0.340550                0.219182 conflict_same_direction
    f_strength_rs20_xsec_q                    0.022985                0.121960 conflict_same_direction
 f_platform_compress_ratio                    0.179819                0.234707 conflict_same_direction
        f_chip_winner_rate                    0.038930                0.012719 conflict_same_direction
   f_ind_peer_strong_count                   15.500000               14.000000 conflict_same_direction
               score_total                    0.104775                0.085007 conflict_same_direction
score_platform_axis_single                   -0.233831               -0.370178        weak_global_down

## Directional fix suggestions (no new version yet)
1. Add Ahigh retention guard by subtype (prevent over-pruning steady/mixed Ahigh).
2. Replace global shrink with C-mode targeted blockers (mixed/platform_false/industry_heat).
3. Prefer net-separator factors; downweight conflict_same_direction factors in purifier stage.