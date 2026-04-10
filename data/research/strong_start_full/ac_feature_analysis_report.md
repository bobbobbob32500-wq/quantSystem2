# A/C 特征差异分析报告（阶段：研究）

## 1. 输入冻结
- 主研究集：`ac_main_research_set.parquet`
- 特征快照：`event_feature_snapshot_batch4.parquet`
- 本次样本口径：仅 A/C，不含 B/N，不重抽样
- 合并后样本：A=1487, C=11541, total=13028

## 2. 字段白名单
- 主分析特征（f_*）数量：43
- 分组解释字段：label_abc, event_type_candidate, name, industry, trade_date, ts_code
- 排除字段（QC/元数据/原始辅助列）数量：12
- 未归类 f_* 字段：无
- 未来/交易字段混入检查：未发现

## 3. Top 15 区分特征
- 1. f_trend_close_ma20_gap (strength): |delta|=0.3463, 方向=A更高, p=6.884e-102, 缺失max=3.16%
- 2. f_k_pct_chg (kline): |delta|=0.3163, 方向=A更高, p=5.539e-88, 缺失max=0.00%
- 3. f_strength_rs20_xsec_q (strength): |delta|=0.2717, 方向=A更高, p=2.088e-63, 缺失max=3.23%
- 4. f_trend_close_ma60_gap (strength): |delta|=0.2682, 方向=A更高, p=4.952e-56, 缺失max=12.78%
- 5. f_ind_rank_pctchg (industry): |delta|=0.2553, 方向=A更高, p=2.612e-58, 缺失max=0.00%
- 6. f_strength_vs_index20 (strength): |delta|=0.2551, 方向=A更高, p=4.211e-56, 缺失max=3.23%
- 7. f_chip_stability_std10 (chip): |delta|=0.2543, 方向=A更高, p=1.509e-57, 缺失max=0.00%
- 8. f_strength_ret20 (strength): |delta|=0.2505, 方向=A更高, p=3.566e-54, 缺失max=3.23%
- 9. f_strength_rs60_xsec_q (strength): |delta|=0.2325, 方向=A更高, p=1.510e-42, 缺失max=12.78%
- 10. f_chip_winner_rate (chip): |delta|=0.2281, 方向=A更高, p=1.234e-46, 缺失max=0.00%
- 11. f_strength_vs_index60 (strength): |delta|=0.2269, 方向=A更高, p=1.380e-40, 缺失max=12.78%
- 12. f_strength_ret60 (strength): |delta|=0.2246, 方向=A更高, p=7.976e-40, 缺失max=12.78%
- 13. f_k_body_to_atr (kline): |delta|=0.1827, 方向=A更高, p=4.193e-30, 缺失max=1.55%
- 14. f_ind_rank_amount (industry): |delta|=0.1736, 方向=A更高, p=9.597e-28, 缺失max=0.00%
- 15. f_breakout_vol_ratio20 (volume): |delta|=0.1448, 方向=A更高, p=3.265e-19, 缺失max=3.16%

## 4. Bottom 10 弱特征
- f_vol_stability20 (volume): |delta|=0.0044, 方向=差异弱, 缺失max=7.46%
- f_chip_single_peak_score (chip): |delta|=0.0057, 方向=差异弱, 缺失max=0.13%
- f_atr_ratio (platform): |delta|=0.0174, 方向=差异弱, 缺失max=1.55%
- f_ind_strength_today (industry): |delta|=0.0240, 方向=差异弱, 缺失max=0.00%
- f_near_pivot20 (platform): |delta|=0.0371, 方向=差异弱, 缺失max=7.60%
- f_k_break_pivot20_pct (kline): |delta|=0.0371, 方向=差异弱, 缺失max=7.60%
- f_platform_range_best (platform): |delta|=0.0381, 方向=差异弱, 缺失max=7.60%
- f_platform_range20 (platform): |delta|=0.0381, 方向=差异弱, 缺失max=7.60%
- f_platform_range30 (platform): |delta|=0.0427, 方向=差异弱, 缺失max=10.69%
- f_chip_peak_count_sig (chip): |delta|=0.0446, 方向=差异弱, 缺失max=0.13%

## 5. 冗余/强相关提示（|Spearman|>=0.85）
- f_platform_range20 vs f_platform_range_best: corr=1.0000
- f_near_pivot20 vs f_k_break_pivot20_pct: corr=1.0000
- f_chip_secondary_peak_ratio vs f_chip_peak_dominance: corr=-1.0000
- f_strength_vs_index60 vs f_strength_rs60_xsec_q: corr=0.9836
- f_k_upper_shadow_ratio vs f_k_close_pos: corr=-0.9685
- f_strength_vs_index20 vs f_strength_rs20_xsec_q: corr=0.9559
- f_strength_ret60 vs f_strength_rs60_xsec_q: corr=0.9494
- f_strength_ret60 vs f_strength_vs_index60: corr=0.9476
- f_platform_range20 vs f_platform_range30: corr=0.8958
- f_platform_range30 vs f_platform_range_best: corr=0.8958
- f_trend_close_ma60_gap vs f_trend_ma20_ma60_gap: corr=0.8882
- f_strength_ret20 vs f_strength_vs_index20: corr=0.8828
- f_chip_peak_dominance vs f_chip_single_peak_score: corr=0.8802
- f_chip_secondary_peak_ratio vs f_chip_single_peak_score: corr=-0.8802
- f_chip_peak_count_sig vs f_chip_single_peak_score: corr=-0.8661

## 6. 缺失与稳定性审计
- 高缺失特征：
  - f_chip_low_position120: 缺失max=26.03%, |delta|=0.0869, 稳定性=stable

## 7. 核心问题快答（仅重要性，不给阈值）
- 板块/行业 vs 峰结构：行业Top3 |delta|均值=0.1706；筹码Top3 |delta|均值=0.1971
- K线质量Top3 |delta|均值=0.1986；平台Top3 |delta|均值=0.0561
