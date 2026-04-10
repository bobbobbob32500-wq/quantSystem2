# true_breakout_ahigh_refine_review

## Objective shift
- old: maximize A share
- new: maximize A_high share, suppress selected_C, demote selected_G

## Core quality compare
                 variant  sample_n  A_high_n  A_mid_n  A_low_n  C_n  G_n  A_high_share  A_mid_share  A_low_share  C_share  G_share
old_selector_core_with_G       167        17       18       17   71   44      0.101796     0.107784     0.101796 0.425150 0.263473
  old_selector_core_no_G       123        17       18       17   71    0      0.138211     0.146341     0.138211 0.577236 0.000000
       ahigh_refine_core        45         8        4        2   31    0      0.177778     0.088889     0.044444 0.688889 0.000000

## Fixed return lens (T day select -> T+1 open -> T+1/T+2/T+3 close)
                 variant  sample_n  mean_ret_t1  mean_ret_t2  mean_ret_t3  median_ret_t1  median_ret_t2  median_ret_t3   win_t1   win_t2   win_t3
old_selector_core_with_G       167     0.005348     0.004228     0.004556       0.003301       0.000000       0.000244 0.550898 0.491018 0.502994
  old_selector_core_no_G       123     0.003684     0.001589     0.003530       0.003301      -0.001519      -0.003505 0.560976 0.455285 0.487805
       ahigh_refine_core        45     0.001126    -0.005382    -0.001473       0.001958      -0.007831      -0.006485 0.533333 0.466667 0.444444

## G demotion effect
           step  sample_n  g_n  g_share  ahigh_share
before_demotion       167   44 0.263473     0.101796
 after_demotion       123    0 0.000000     0.138211

## C firewall effect
            firewall_reason  hit_total_n  hit_c_n  hit_c_share  c_share_before  c_share_after
     industry_heat_firewall            0        0          NaN             1.0            1.0
platform_integrity_firewall           31       13     0.419355             1.0            1.0
      mixed_pseudo_firewall            9        7     0.777778             1.0            1.0
                    overall           40       20     0.500000             1.0            1.0

## Verdict
- Check whether A_high share rises and C share falls after refine.
- Keep this as selector-layer validation only (not execution/buy-point strategy).