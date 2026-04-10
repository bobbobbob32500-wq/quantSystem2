# true_breakout_selected_quality_diagnosis

- window: 20251230 ~ 20260330
- selected_A: 52
- selected_C: 71
- selected_G: 44

## selected_A quality split
- A_high: 17
- A_mid: 18
- A_low: 17

## C mixed-in drivers (top)
     selected_c_reason  sample_n  share_in_selected_c  mean_ret_t2   win_t2
        mixed_pseudo_C      48.0             0.676056    -0.024343 0.187500
platform_false_break_C      10.0             0.140845    -0.047669 0.200000
       industry_heat_C       7.0             0.098592    -0.051323 0.142857
         trend_chase_C       4.0             0.056338    -0.031552 0.250000
     chip_distortion_C       2.0             0.028169    -0.002434 0.500000

## G observation reasons (top)
          selected_g_reason  sample_n  share_in_selected_g  mean_ret_t2   win_t2
             grey_uncertain      19.0             0.431818     0.023508 0.631579
         path_mixed_unclear      16.0             0.363636     0.001145 0.562500
buypoint_sensitive_recovery       4.0             0.090909     0.026505 1.000000
           early_spike_fade       3.0             0.068182    -0.020334 0.000000
          weak_continuation       2.0             0.045455     0.000310 0.500000

## A_high vs C/G strongest separators
                    factor  A_high_median  selected_C_median  selected_G_median  A_high_minus_C  A_high_minus_G
   f_ind_peer_strong_count      13.000000          12.000000          11.500000        1.000000        1.500000
 f_platform_compress_ratio       0.541299           0.481696           0.475816        0.059604        0.065483
   score_trend_axis_single       0.899194           0.860922           0.770769        0.038272        0.128425
    f_strength_rs20_xsec_q       0.955547           0.931085           0.874456        0.024462        0.081091
    score_chip_axis_single       0.730652           0.741243           0.782053       -0.010591       -0.051401
        f_chip_winner_rate       0.966494           0.984377           0.992108       -0.017882       -0.025614
score_platform_axis_single       0.527255           0.604578           0.674739       -0.077322       -0.147484
score_industry_axis_single       0.489205           0.616963           0.606227       -0.127758       -0.117023

## diagnosis
- Main issue is not only A/C separation; A-high vs A-mid/A-low separation is also insufficient.
- selected_C is dominated by heat/chase-like pseudo-strength modes in this window.
- selected_G contains mixed/uncertain path cases that should stay outside core candidate intent.