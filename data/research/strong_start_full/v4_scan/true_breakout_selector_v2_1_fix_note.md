# true_breakout_selector_v2_1_fix_note

1) Fix-1: `f_chip_stability_std10` removed from hard filter, moved into chip scoring axis.
2) Fix-2: trend/industry de-collinearity: trend kept one core + one aux; industry stays auxiliary and not co-amplified.
3) Fix-3: platform axis rebuilt with sign-consistent, stable positive-separation factors only.