# true_breakout_selector_v3_dualpath_structure_review

- near window: 20251230 ~ 20260330
- A/C sample: 4029

## A/C selected counts (structure only)
- single_v22: A=151, C=326
- path_a: A=152, C=286
- path_b: A=180, C=345
- dual_merge: A=295, C=546

## A subtype coverage (selected_rate)
model                      dual_merge    path_a    path_b  single_v22
group_name                                                           
chip_support_A               0.173913  0.000000  0.173913    0.014493
high_momentum_frontline_A    0.650000  0.568750  0.206250    0.462500
mixed_A                      0.121646  0.054562  0.082290    0.067084
steady_structure_A           0.544304  0.000000  0.544304    0.012658

## C failure-mode selection rate
model                   dual_merge    path_a    path_b  single_v22
group_name                                                        
chip_distortion_C         0.388889  0.011111  0.377778    0.000000
industry_heat_C           0.624606  0.501577  0.268139    0.542587
mixed_pseudo_C            0.136126  0.030250  0.122164    0.038976
platform_false_break_C    0.181395  0.172093  0.034884    0.200000
trend_chase_C             0.021277  0.000000  0.021277    0.021277

## Structural judgement
- Path A concentrates on momentum-frontline A, while Path B increases coverage on non-extreme A subtypes.
- Heat-cap reduces theoretical trend×industry co-resonance risk in Path A.
- Dual merge is structurally closer to observed near-window subtype mix than single-path ranking.

Note: structure validation only; no trade execution / no return backtest.