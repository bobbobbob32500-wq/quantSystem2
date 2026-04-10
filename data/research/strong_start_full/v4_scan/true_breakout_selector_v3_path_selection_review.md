# true_breakout_selector_v3_path_selection_review

- near window: 20251230 ~ 20260330
- baseline A share: 0.3539

## Path internal
       path bucket  sample_n  a_n  c_n  a_share
path_a_full  top10       158   56  102 0.354430
path_a_full  top20       343  117  226 0.341108
path_a_full  top30       523  184  339 0.351816
path_b_full  top10       190   70  120 0.368421
path_b_full  top20       410  140  270 0.341463
path_b_full  top30       631  223  408 0.353407

## S0/S3/S4/S5 compare
                   model  sample_n  a_n  c_n  a_share  a_share_lift_vs_baseline_pts  a_share_lift_vs_S0_pts
           S0_single_v22       477  151  326 0.316562                     -0.037338                0.000000
          S1_path_a_full       438  152  286 0.347032                     -0.006868                0.030470
          S2_path_b_full       525  178  347 0.339048                     -0.014852                0.022486
     S3_dual_merge_naive       842  293  549 0.347981                     -0.005919                0.031419
S4_dual_merge_controlled       497  172  325 0.346076                     -0.007824                0.029515
       S5_path_selection       247   80  167 0.323887                     -0.030013                0.007325

## Monthly A-share (S3 vs S5)
 month  sample_n_s0  a_share_s0  sample_n_s3  a_share_s3  sample_n_s5  a_share_s5 stability_source
202512           13    0.615385           24    0.750000            9    0.666667  monthly_a_share
202601          144    0.368056          317    0.406940           97    0.350515  monthly_a_share
202602           92    0.532609          167    0.485030           52    0.557692  monthly_a_share
202603          228    0.179825          334    0.194611           89    0.123596  monthly_a_share

## Key answers
- path_selection > naive? no
- path_selection >= baseline? no
- path_selection reduces C vs naive? yes
- path_selection better than S0? yes
- path_selection better than S4? no

Note: selector-only validation; no entry/exit/execution/backtest returns.