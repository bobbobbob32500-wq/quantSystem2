# Rule Robustness Audit

## Key Findings
- keep: ['R2_R3', 'R3', 'BASELINE']
- candidate_keep: ['R1_R2', 'R1_R2_R3', 'R2']
- drop: ['R1', 'R1_R3']

## Most stable single rule candidates
 rule_candidate                                                          candidate_expr  main_sample_n  main_Ahigh_over_C  main_C_pct  main_mean_ret_t2  confirm_sample_n  confirm_Ahigh_over_C  confirm_C_pct  confirm_mean_ret_t2 robust_label
R1_conservative                      score_total>=q55 & score_platform_axis_single>=q45             21           0.285714    0.333333         -0.000600                27              0.166667       0.444444            -0.009748         drop
     R1_relaxed score_total>=q50(~q55 proxied by q45) & score_platform_axis_single>=q40             39           0.250000    0.410256          0.000902                44              0.250000       0.454545            -0.001721         drop
     R3_relaxed                                      NOT(platform<=q35 & compress>=q65)            116           0.250000    0.379310          0.004692               121              0.295455       0.363636             0.010748         drop
R3_conservative                                      NOT(platform<=q45 & compress>=q60)            105           0.236842    0.361905          0.004406               112              0.261905       0.375000             0.009878         drop
     R2_relaxed                                          NOT(industry>=q70 & chip>=q75)            143           0.305085    0.412587          0.006698               158              0.262295       0.386076             0.010208         keep
R2_conservative                                          NOT(industry>=q60 & chip>=q65)            131           0.303571    0.427481          0.006967               149              0.285714       0.375839             0.010281         keep

## Draft decision
- Preserve baseline structure, keep only cross-window-consistent rule combinations.
- Convert precise constants to percentile-band candidates before selector upgrade.