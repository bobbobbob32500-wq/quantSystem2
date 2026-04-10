# true_breakout_selector_tune21_review

Only one change vs freeze1: output-layer candidate pool from top30% -> daily top3.
Top2 is reference only.

## Window
- 20250925 ~ 20260327 (118 trading days)

## Key compare
                    group  sample_n  a_share  avg_ret_t1  med_ret_t1   win_t1  avg_ret_t2  med_ret_t2   win_t2
freeze1_original_top30pct       703 0.230441    0.002311   -0.004301 0.458037    0.001342   -0.005783 0.446657
              tune21_top3       354 0.242938    0.004190   -0.003295 0.466102    0.006497   -0.003510 0.460452
           reference_top2       236 0.245763    0.005105   -0.002768 0.470339    0.010390   -0.000055 0.495763

## 4 direct answers
1) Top3 vs Top30 more reasonable: True
2) Top3 vs Top2 for formal pool: top3_if_balance_priority
3) Main issue is pool too wide: True
4) tune2.1 worth as next baseline candidate: True