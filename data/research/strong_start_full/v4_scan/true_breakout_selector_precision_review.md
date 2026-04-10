# true_breakout_selector_precision_review

Scope: selector-layer internal purification only (no entry/exit/execution branch).

## Compare
           scenario  sample_n   win_t2  avg_ret_t2  med_ret_t2   win_t1  avg_ret_t1  med_ret_t1  a_share  daily_output_avg  active_days  blank_days
            S0_top3       354 0.460452    0.006497   -0.003510 0.466102    0.004190   -0.003295 0.242938          3.000000          118           0
            S1_top2       236 0.495763    0.010390   -0.000055 0.470339    0.005105   -0.002768 0.245763          2.000000          118           0
            S2_top1       118 0.500000    0.011644    0.000183 0.508475    0.008733    0.001452 0.262712          1.000000          118           0
S3_conditional_top2       102 0.450980    0.003833   -0.012197 0.460784    0.004908   -0.001705 0.196078          0.864407           51          67

## Monthly win_t2 stability
  month  sample_n  avg_ret_t2   win_t2            scenario
2025-09        12    0.000303 0.416667             S0_top3
2025-10        51    0.015669 0.490196             S0_top3
2025-11        60   -0.001925 0.466667             S0_top3
2025-12        69    0.017623 0.449275             S0_top3
2026-01        60    0.010364 0.516667             S0_top3
2026-02        42    0.008819 0.452381             S0_top3
2026-03        60   -0.009924 0.400000             S0_top3
2025-09         8    0.008255 0.500000             S1_top2
2025-10        34    0.019104 0.500000             S1_top2
2025-11        40    0.003025 0.500000             S1_top2
2025-12        46    0.018017 0.456522             S1_top2
2026-01        40    0.014324 0.525000             S1_top2
2026-02        28    0.005180 0.500000             S1_top2
2026-03        40    0.001714 0.500000             S1_top2
2025-09         4    0.048896 0.750000             S2_top1
2025-10        17    0.021876 0.411765             S2_top1
2025-11        20    0.024816 0.650000             S2_top1
2025-12        23   -0.002645 0.347826             S2_top1
2026-01        20    0.013019 0.500000             S2_top1
2026-02        14    0.015982 0.571429             S2_top1
2026-03        20   -0.005654 0.500000             S2_top1
2025-09         2   -0.103325 0.000000 S3_conditional_top2
2025-10        12    0.015637 0.500000 S3_conditional_top2
2025-11        14   -0.040260 0.214286 S3_conditional_top2
2025-12        24    0.030197 0.500000 S3_conditional_top2
2026-01        14    0.001296 0.500000 S3_conditional_top2
2026-02         8   -0.011251 0.375000 S3_conditional_top2
2026-03        28    0.011456 0.535714 S3_conditional_top2

## Direct answers
- best under win_t2 priority: S2_top1
- best win_t2 level: 0.5000
- recommended formal high-purity pool: S2_top1