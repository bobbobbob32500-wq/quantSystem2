# true_breakout_regime_mismatch_report

- near window: 20251230 ~ 20260330
- near A/C sample: 4029
- selected_A=151, selected_C=326, missed_A=1275, rejected_C=2277

## Regime drift (year vs near)
- stable_or_stronger: 8
- weakened_near: 5
- direction_flip: 5

family drift counts:
  family        drift_state  n
    chip stable_or_stronger  1
    chip      weakened_near  2
industry     direction_flip  1
industry stable_or_stronger  1
industry      weakened_near  1
platform     direction_flip  1
platform stable_or_stronger  1
platform      weakened_near  1
   trend     direction_flip  3
   trend stable_or_stronger  5
   trend      weakened_near  1

top flipped/weakened factors:
               feature   family  year_gap_a_minus_c  near_gap_a_minus_c    drift_state
      f_strength_ret60    trend            0.021447           -0.010646 direction_flip
f_strength_rs60_xsec_q    trend            0.047513           -0.001875 direction_flip
f_trend_close_ma60_gap    trend            0.011697            0.001189  weakened_near
 f_trend_ma20_ma60_gap    trend            0.006271           -0.000487 direction_flip
    f_platform_range20 platform            0.012526            0.001187  weakened_near
    f_platform_range30 platform            0.010284           -0.000275 direction_flip
    f_chip_winner_rate     chip            0.026247            0.008849  weakened_near
f_chip_stability_std10     chip            0.000517            0.000098  weakened_near
     f_ind_strength_5d industry           -0.000289           -0.000141  weakened_near
     f_ind_rank_pctchg industry            0.009404           -0.018182 direction_flip

## Near A subtypes
                a_subtype  missed_A  selected_A  selected_rate
           chip_support_A        68           1       0.014493
high_momentum_frontline_A        86          74       0.462500
                  mixed_A      1043          75       0.067084
       steady_structure_A        78           1       0.012658

## selected_C failure modes
        c_failure_mode   n
        mixed_pseudo_C 214
platform_false_break_C  44
       industry_heat_C  40
         trend_chase_C  21
     chip_distortion_C   7

axis likely amplifying selected_C:
               axis  selectedC_minus_rejectedC
   score_trend_axis                   0.482596
    score_chip_axis                   0.247585
score_industry_axis                   0.181776
score_platform_axis                  -0.171373

## Repair directions (no new selector version)
1) Split selector into dual-path scoring (momentum-frontline path + steady-structure path) to recover missed_A in non-extreme trend regime. [solve missed A]
2) Add anti-hotness guard on trend/industry joint extremes (cap co-amplification) to block industry_heat_C and trend_chase_C spill-in. [solve selected C]
3) Make platform/chip conditional by subtype (not global linear sum), because near-window A is multi-modal and single-axis additive ranking under-fits subtype diversity. [solve both]