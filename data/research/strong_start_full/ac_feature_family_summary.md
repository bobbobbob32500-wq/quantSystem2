# A/C 六大维度差异汇总

- 样本量：A=1487，C=11541
- 主分析特征数：43

## strength
- 维度中位区分强度（|Cliff's delta| 中位数）：0.2415
- Top 特征：
  - f_trend_close_ma20_gap: |delta|=0.3463, 方向=A更高, A-C中位数差=0.028135
  - f_strength_rs20_xsec_q: |delta|=0.2717, 方向=A更高, A-C中位数差=0.096082
  - f_trend_close_ma60_gap: |delta|=0.2682, 方向=A更高, A-C中位数差=0.045455
  - f_strength_vs_index20: |delta|=0.2551, 方向=A更高, A-C中位数差=0.038354
  - f_strength_ret20: |delta|=0.2505, 方向=A更高, A-C中位数差=0.034867
- 弱特征：
  - f_trend_ma20_slope5: |delta|=0.1221, 方向=A更高
  - f_trend_ma20_ma60_gap: |delta|=0.1389, 方向=A更高
  - f_strength_ret60: |delta|=0.2246, 方向=A更高

## platform
- 维度中位区分强度（|Cliff's delta| 中位数）：0.0381
- Top 特征：
  - f_platform_compress_ratio: |delta|=0.0796, 方向=A更高, A-C中位数差=0.018703
  - f_platform_len: |delta|=0.0458, 方向=差异弱, A-C中位数差=-6.000000
  - f_platform_range30: |delta|=0.0427, 方向=差异弱, A-C中位数差=0.006615
  - f_platform_range_best: |delta|=0.0381, 方向=差异弱, A-C中位数差=0.004609
  - f_platform_range20: |delta|=0.0381, 方向=差异弱, A-C中位数差=0.004609
- 弱特征：
  - f_atr_ratio: |delta|=0.0174, 方向=差异弱
  - f_near_pivot20: |delta|=0.0371, 方向=差异弱
  - f_platform_range_best: |delta|=0.0381, 方向=差异弱

## volume
- 维度中位区分强度（|Cliff's delta| 中位数）：0.0798
- Top 特征：
  - f_breakout_vol_ratio20: |delta|=0.1448, 方向=A更高, A-C中位数差=0.241187
  - f_up_down_vol_ratio20: |delta|=0.1134, 方向=A更高, A-C中位数差=0.053928
  - f_low_vol_days10: |delta|=0.0798, 方向=A更低, A-C中位数差=-1.000000
  - f_vol20_vol60: |delta|=0.0639, 方向=A更高, A-C中位数差=0.029183
  - f_vol_stability20: |delta|=0.0044, 方向=差异弱, A-C中位数差=0.005592
- 弱特征：
  - f_vol_stability20: |delta|=0.0044, 方向=差异弱
  - f_vol20_vol60: |delta|=0.0639, 方向=A更高
  - f_low_vol_days10: |delta|=0.0798, 方向=A更低

## chip
- 维度中位区分强度（|Cliff's delta| 中位数）：0.0675
- Top 特征：
  - f_chip_stability_std10: |delta|=0.2543, 方向=A更高, A-C中位数差=0.001376
  - f_chip_winner_rate: |delta|=0.2281, 方向=A更高, A-C中位数差=0.082778
  - f_chip_concentration: |delta|=0.1087, 方向=A更高, A-C中位数差=0.009615
  - f_chip_low_position120: |delta|=0.0869, 方向=A更高, A-C中位数差=0.020747
  - f_chip_peak_dominance: |delta|=0.0481, 方向=差异弱, A-C中位数差=0.017701
- 弱特征：
  - f_chip_single_peak_score: |delta|=0.0057, 方向=差异弱
  - f_chip_peak_count_sig: |delta|=0.0446, 方向=差异弱
  - f_chip_secondary_peak_ratio: |delta|=0.0481, 方向=差异弱

## kline
- 维度中位区分强度（|Cliff's delta| 中位数）：0.0965
- Top 特征：
  - f_k_pct_chg: |delta|=0.3163, 方向=A更高, A-C中位数差=0.019442
  - f_k_body_to_atr: |delta|=0.1827, 方向=A更高, A-C中位数差=0.026818
  - f_k_upper_shadow_ratio: |delta|=0.0969, 方向=A更低, A-C中位数差=-0.024230
  - f_k_close_pos: |delta|=0.0961, 方向=A更高, A-C中位数差=0.024176
  - f_k_lower_shadow_ratio: |delta|=0.0840, 方向=A更低, A-C中位数差=-0.021514
- 弱特征：
  - f_k_break_pivot20_pct: |delta|=0.0371, 方向=差异弱
  - f_k_lower_shadow_ratio: |delta|=0.0840, 方向=A更低
  - f_k_close_pos: |delta|=0.0961, 方向=A更高

## industry
- 维度中位区分强度（|Cliff's delta| 中位数）：0.0526
- Top 特征：
  - f_ind_rank_pctchg: |delta|=0.2553, 方向=A更高, A-C中位数差=0.071429
  - f_ind_rank_amount: |delta|=0.1736, 方向=A更高, A-C中位数差=0.077381
  - f_ind_peer_strong_count: |delta|=0.0830, 方向=A更高, A-C中位数差=0.000000
  - f_ind_strength_3d: |delta|=0.0526, 方向=A更高, A-C中位数差=0.033825
  - f_ind_breadth: |delta|=0.0487, 方向=差异弱, A-C中位数差=-0.023529
- 弱特征：
  - f_ind_strength_today: |delta|=0.0240, 方向=差异弱
  - f_ind_strength_5d: |delta|=0.0456, 方向=差异弱
  - f_ind_breadth: |delta|=0.0487, 方向=差异弱
