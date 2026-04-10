# true_breakout_feature_family_summary

- A samples: 3817
- C samples: 6992
- G samples (observation): 7163
- N samples (excluded): 519

## family strength
             family  feature_n  mean_abs_effect  median_abs_effect  keep_n  high_missing_n
     trend_strength         10         0.057657           0.053567       2             NaN
 platform_structure          6         0.049972           0.055034       0             NaN
       chip_quality          8         0.048048           0.043525       0             NaN
industry_leadership          7         0.025246           0.016286       0             NaN
      volume_rhythm          4         0.019803           0.013961       0             NaN
     kline_research          6         0.019608           0.016433       0             NaN
              other          2         0.019384           0.019384       0             NaN

- strongest family: trend_strength
- weakest family: other

## strongest features top5
- f_strength_rs20_xsec_q
- f_strength_ret20
- f_platform_range_best
- f_platform_range20
- f_strength_vs_index20

## weakest features
- f_k_close_pos
- f_platform_compress_ratio
- f_ind_rank_amount
- f_vol_stability20
- f_k_body_to_atr

## redundancy (|spearman| >= 0.85 among stronger factors)
no strong redundancy pairs