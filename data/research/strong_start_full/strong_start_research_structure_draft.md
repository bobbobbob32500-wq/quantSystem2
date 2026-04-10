# strong_start 研究版结构草图（参数反推阶段）

## 第一层：硬过滤候选
- `f_trend_close_ma20_gap` (strength, |delta|=0.3463)：|delta|=0.3463；missing_max=3.16%；方向=A更高；高区分+低缺失+方向明确
- `f_strength_rs20_xsec_q` (strength, |delta|=0.2717)：|delta|=0.2717；missing_max=3.23%；方向=A更高；高区分+低缺失+方向明确
- `f_ind_rank_pctchg` (industry, |delta|=0.2553)：|delta|=0.2553；missing_max=0.00%；方向=A更高；高区分+低缺失+方向明确
- `f_chip_stability_std10` (chip, |delta|=0.2543)：|delta|=0.2543；missing_max=0.00%；方向=A更高；高区分+低缺失+方向明确
- `f_chip_winner_rate` (chip, |delta|=0.2281)：|delta|=0.2281；missing_max=0.00%；方向=A更高；高区分+低缺失+方向明确

## 第二层：连续评分候选
- `f_trend_close_ma60_gap` (strength, |delta|=0.2682)：|delta|=0.2682；missing_max=12.78%；方向=A更高；有区分力，适合连续加分
- `f_strength_vs_index20` (strength, |delta|=0.2551)：|delta|=0.2551；missing_max=3.23%；方向=A更高；有区分力，适合连续加分；与f_strength_rs20_xsec_q高相关，避免重复约束
- `f_strength_ret20` (strength, |delta|=0.2505)：|delta|=0.2505；missing_max=3.23%；方向=A更高；有区分力，适合连续加分；与f_strength_vs_index20高相关，避免重复约束
- `f_strength_rs60_xsec_q` (strength, |delta|=0.2325)：|delta|=0.2325；missing_max=12.78%；方向=A更高；有区分力，适合连续加分
- `f_strength_vs_index60` (strength, |delta|=0.2269)：|delta|=0.2269；missing_max=12.78%；方向=A更高；有区分力，适合连续加分；与f_strength_rs60_xsec_q高相关，避免重复约束
- `f_strength_ret60` (strength, |delta|=0.2246)：|delta|=0.2246；missing_max=12.78%；方向=A更高；有区分力，适合连续加分；与f_strength_vs_index60高相关，避免重复约束
- `f_ind_rank_amount` (industry, |delta|=0.1736)：|delta|=0.1736；missing_max=0.00%；方向=A更高；有区分力，适合连续加分
- `f_trend_ma20_ma60_gap` (strength, |delta|=0.1389)：|delta|=0.1389；missing_max=12.78%；方向=A更高；有区分力，适合连续加分；与f_trend_close_ma60_gap高相关，避免重复约束
- `f_trend_ma20_slope5` (strength, |delta|=0.1221)：|delta|=0.1221；missing_max=5.04%；方向=A更高；有区分力，适合连续加分
- `f_chip_concentration` (chip, |delta|=0.1087)：|delta|=0.1087；missing_max=0.00%；方向=A更高；有区分力，适合连续加分

## 第三层：触发确认候选
- `f_k_pct_chg` (kline, |delta|=0.3163)：|delta|=0.3163；missing_max=0.00%；方向=A更高；更适合放在触发确认层
- `f_k_body_to_atr` (kline, |delta|=0.1827)：|delta|=0.1827；missing_max=1.55%；方向=A更高；更适合放在触发确认层
- `f_breakout_vol_ratio20` (volume, |delta|=0.1448)：|delta|=0.1448；missing_max=3.16%；方向=A更高；更适合放在触发确认层
- `f_up_down_vol_ratio20` (volume, |delta|=0.1134)：|delta|=0.1134；missing_max=18.70%；方向=A更高；更适合放在触发确认层
- `f_k_upper_shadow_ratio` (kline, |delta|=0.0969)：|delta|=0.0969；missing_max=0.25%；方向=A更低；更适合放在触发确认层
- `f_k_close_pos` (kline, |delta|=0.0961)：|delta|=0.0961；missing_max=0.25%；方向=A更高；更适合放在触发确认层；与f_k_upper_shadow_ratio高相关，避免重复约束
- `f_k_lower_shadow_ratio` (kline, |delta|=0.0840)：|delta|=0.0840；missing_max=0.25%；方向=A更低；更适合放在触发确认层

## 第四层：降级/弃用项
- `f_chip_low_position120` (chip, |delta|=0.0869)：|delta|=0.0869；missing_max=26.03%；方向=A更高；缺失偏高(>20%)
- `f_ind_peer_strong_count` (industry, |delta|=0.0830)：|delta|=0.0830；missing_max=0.00%；方向=A更高；边际信息有限
- `f_low_vol_days10` (volume, |delta|=0.0798)：|delta|=0.0798；missing_max=0.00%；方向=A更低；边际信息有限
- `f_platform_compress_ratio` (platform, |delta|=0.0796)：|delta|=0.0796；missing_max=3.16%；方向=A更高；平台静态特征不宜过度约束
- `f_vol20_vol60` (volume, |delta|=0.0639)：|delta|=0.0639；missing_max=12.78%；方向=A更高；边际信息有限
- `f_ind_strength_3d` (industry, |delta|=0.0526)：|delta|=0.0526；missing_max=0.00%；方向=A更高；边际信息有限
- `f_ind_breadth` (industry, |delta|=0.0487)：|delta|=0.0487；missing_max=0.00%；方向=差异弱；区分力弱
- `f_chip_peak_dominance` (chip, |delta|=0.0481)：|delta|=0.0481；missing_max=0.13%；方向=差异弱；区分力弱
- `f_chip_secondary_peak_ratio` (chip, |delta|=0.0481)：|delta|=0.0481；missing_max=0.13%；方向=差异弱；区分力弱；与f_chip_peak_dominance高相关，避免重复约束
- `f_platform_len` (platform, |delta|=0.0458)：|delta|=0.0458；missing_max=0.00%；方向=差异弱；区分力弱
- `f_ind_strength_5d` (industry, |delta|=0.0456)：|delta|=0.0456；missing_max=0.00%；方向=差异弱；区分力弱
- `f_chip_peak_count_sig` (chip, |delta|=0.0446)：|delta|=0.0446；missing_max=0.13%；方向=差异弱；区分力弱
- `f_platform_range30` (platform, |delta|=0.0427)：|delta|=0.0427；missing_max=10.69%；方向=差异弱；区分力弱
- `f_platform_range_best` (platform, |delta|=0.0381)：|delta|=0.0381；missing_max=7.60%；方向=差异弱；区分力弱；与f_platform_range30高相关，避免重复约束
- `f_platform_range20` (platform, |delta|=0.0381)：|delta|=0.0381；missing_max=7.60%；方向=差异弱；区分力弱；与f_platform_range30高相关，避免重复约束
- `f_near_pivot20` (platform, |delta|=0.0371)：|delta|=0.0371；missing_max=7.60%；方向=差异弱；区分力弱
- `f_k_break_pivot20_pct` (kline, |delta|=0.0371)：|delta|=0.0371；missing_max=7.60%；方向=差异弱；区分力弱；与f_near_pivot20高相关，避免重复约束
- `f_ind_strength_today` (industry, |delta|=0.0240)：|delta|=0.0240；missing_max=0.00%；方向=差异弱；区分力弱
- `f_atr_ratio` (platform, |delta|=0.0174)：|delta|=0.0174；missing_max=1.55%；方向=差异弱；区分力弱
- `f_chip_single_peak_score` (chip, |delta|=0.0057)：|delta|=0.0057；missing_max=0.13%；方向=差异弱；区分力弱；与f_chip_peak_count_sig高相关，避免重复约束

## 区间建议说明
- 采用 A/C 中位数差构造宽松/中性/严格三档，仅用于下一轮规则讨论。
- 本文不输出最终精确阈值，不涉及回测。
