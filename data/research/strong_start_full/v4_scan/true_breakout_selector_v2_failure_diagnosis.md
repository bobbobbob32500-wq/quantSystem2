# true_breakout_selector_v2_failure_diagnosis

- full-sample A share: 0.3539
- selected-sample A share: 0.3116
- why A share is below baseline: selected_C remains too high while many A are filtered out by combined hard filters and axis mix near the cut line.

## Four quadrants
      quadrant    n  share_in_window  share_within_A_or_C  a_share_full  a_share_selected  selected_n  selected_a  selected_c
    selected_A  129         0.032018             0.090463           NaN               NaN         NaN         NaN         NaN
    selected_C  285         0.070737             0.109489           NaN               NaN         NaN         NaN         NaN
      missed_A 1297         0.321916             0.909537           NaN               NaN         NaN         NaN         NaN
    rejected_C 2318         0.575329             0.890511           NaN               NaN         NaN         NaN         NaN
window_overall 4029         1.000000                  NaN      0.353934          0.311594       414.0       129.0       285.0

## Hard-filter error findings
- most A-killing rule: f_chip_stability_std10 >= 0.0032
- most C-leaking rule: f_strength_rs20_xsec_q >= 0.72

## Axis failure findings
- axis helping A most (selected_A vs missed_A): score_trend_axis
- axis pushing C most (selected_C vs rejected_C): score_trend_axis
- axis suppressing A most: score_platform_axis

## selected_A vs missed_A (top gaps)
                feature  left_n  right_n  left_median  right_median  median_gap_left_minus_right
f_ind_peer_strong_count     129     1297    11.000000      9.000000                     2.000000
       score_trend_axis     129     1297     0.891739      0.461441                     0.430297
 f_strength_rs20_xsec_q     129     1297     0.955547      0.720264                     0.235283
 f_trend_close_ma60_gap      94      986     0.306639      0.072973                     0.233666
       f_strength_ret20     129     1297     0.307958      0.074303                     0.233655
     f_chip_winner_rate     129     1297     0.960261      0.737366                     0.222894
        score_chip_axis     129     1297     0.686523      0.495706                     0.190817
     f_platform_range20     129     1297     0.282679      0.148096                     0.134583
  f_platform_range_best     122     1184     0.283661      0.150080                     0.133581
 f_chip_low_position120      94      986     0.617683      0.498732                     0.118951

## selected_C vs rejected_C (top gaps)
                feature  left_n  right_n  left_median  right_median  median_gap_left_minus_right
f_ind_peer_strong_count     285     2318    12.000000      7.000000                     5.000000
       score_trend_axis     285     2318     0.916824      0.431558                     0.485266
 f_trend_close_ma60_gap     243     1850     0.377344      0.067107                     0.310237
 f_strength_rs20_xsec_q     285     2317     0.970685      0.672781                     0.297905
       f_strength_ret20     285     2317     0.351595      0.060976                     0.290620
     f_chip_winner_rate     285     2318     0.939130      0.721818                     0.217311
  f_platform_range_best     281     2239     0.324011      0.142777                     0.181234
     f_platform_range20     285     2317     0.320939      0.141057                     0.179883
        score_chip_axis     285     2318     0.657275      0.479632                     0.177643
    score_industry_axis     285     2318     0.619074      0.480454                     0.138620

## Repair directions (no new version yet)
1) Re-check hard-filter role split: move one borderline hard rule into scoring if it mainly causes A misses.
2) Constrain C-pushing axis contribution near candidate cut line (reduce false promotion of C).
3) Strengthen A-recovery axis in scoring tie-break (for selected_A vs missed_A positive gaps).