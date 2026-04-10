# true_breakout_selector_v3_effectiveness_review

- near window: 20251230 ~ 20260330
- full-sample A share baseline: 0.3539

## Path internal A-share
bucket          top10     top20     top30
path                                     
path_a_full  0.354430  0.341108  0.351816
path_b_full  0.368421  0.341463  0.353407

## Merge compare
                   model  sample_n  a_n  c_n  a_share  a_share_lift_vs_full_pts  a_share_lift_vs_S0_pts
           S0_single_v22       477  151  326 0.316562                 -0.037372                0.000000
          S1_path_a_full       438  152  286 0.347032                 -0.006902                0.030470
          S2_path_b_full       525  178  347 0.339048                 -0.014886                0.022486
     S3_dual_merge_naive       842  293  549 0.347981                 -0.005953                0.031419
S4_dual_merge_controlled       497  172  325 0.346076                 -0.007858                0.029515

## Judgement
- Path A internal ranking effective: yes
- Path B internal ranking effective: yes
- Controlled merge better than naive: no
- Controlled merge above full-sample baseline: no
- Controlled merge above S0: yes

Note: selector-only validation; no entry/exit/execution/backtest returns.