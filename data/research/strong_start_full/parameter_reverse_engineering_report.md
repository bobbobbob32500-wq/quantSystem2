# 参数反推报告（研究阶段）

## 1. 输入冻结确认
- 使用文件：`ac_feature_diff_summary.csv`、`ac_feature_rankings.csv`、`ac_feature_missing_audit.csv`、`ac_feature_family_summary.md`、`ac_feature_analysis_report.md`
- 未重跑 A/C 分析，未改样本口径，未进行回测。

## 2. 特征分层结果
- 硬过滤候选: 5 个
- 连续评分候选: 10 个
- 触发确认候选: 7 个
- 降级/弃用项: 21 个

### 硬过滤候选 Top5
- `f_trend_close_ma20_gap`: |delta|=0.3463；missing_max=3.16%；方向=A更高；高区分+低缺失+方向明确
- `f_strength_rs20_xsec_q`: |delta|=0.2717；missing_max=3.23%；方向=A更高；高区分+低缺失+方向明确
- `f_ind_rank_pctchg`: |delta|=0.2553；missing_max=0.00%；方向=A更高；高区分+低缺失+方向明确
- `f_chip_stability_std10`: |delta|=0.2543；missing_max=0.00%；方向=A更高；高区分+低缺失+方向明确
- `f_chip_winner_rate`: |delta|=0.2281；missing_max=0.00%；方向=A更高；高区分+低缺失+方向明确

### 连续评分候选 Top5
- `f_trend_close_ma60_gap`: |delta|=0.2682；missing_max=12.78%；方向=A更高；有区分力，适合连续加分
- `f_strength_vs_index20`: |delta|=0.2551；missing_max=3.23%；方向=A更高；有区分力，适合连续加分；与f_strength_rs20_xsec_q高相关，避免重复约束
- `f_strength_ret20`: |delta|=0.2505；missing_max=3.23%；方向=A更高；有区分力，适合连续加分；与f_strength_vs_index20高相关，避免重复约束
- `f_strength_rs60_xsec_q`: |delta|=0.2325；missing_max=12.78%；方向=A更高；有区分力，适合连续加分
- `f_strength_vs_index60`: |delta|=0.2269；missing_max=12.78%；方向=A更高；有区分力，适合连续加分；与f_strength_rs60_xsec_q高相关，避免重复约束

### 触发确认候选 Top5
- `f_k_pct_chg`: |delta|=0.3163；missing_max=0.00%；方向=A更高；更适合放在触发确认层
- `f_k_body_to_atr`: |delta|=0.1827；missing_max=1.55%；方向=A更高；更适合放在触发确认层
- `f_breakout_vol_ratio20`: |delta|=0.1448；missing_max=3.16%；方向=A更高；更适合放在触发确认层
- `f_up_down_vol_ratio20`: |delta|=0.1134；missing_max=18.70%；方向=A更高；更适合放在触发确认层
- `f_k_upper_shadow_ratio`: |delta|=0.0969；missing_max=0.25%；方向=A更低；更适合放在触发确认层

### 降级/弃用 Top10
- `f_chip_low_position120`: |delta|=0.0869；missing_max=26.03%；方向=A更高；缺失偏高(>20%)
- `f_ind_peer_strong_count`: |delta|=0.0830；missing_max=0.00%；方向=A更高；边际信息有限
- `f_low_vol_days10`: |delta|=0.0798；missing_max=0.00%；方向=A更低；边际信息有限
- `f_platform_compress_ratio`: |delta|=0.0796；missing_max=3.16%；方向=A更高；平台静态特征不宜过度约束
- `f_vol20_vol60`: |delta|=0.0639；missing_max=12.78%；方向=A更高；边际信息有限
- `f_ind_strength_3d`: |delta|=0.0526；missing_max=0.00%；方向=A更高；边际信息有限
- `f_ind_breadth`: |delta|=0.0487；missing_max=0.00%；方向=差异弱；区分力弱
- `f_chip_peak_dominance`: |delta|=0.0481；missing_max=0.13%；方向=差异弱；区分力弱
- `f_chip_secondary_peak_ratio`: |delta|=0.0481；missing_max=0.13%；方向=差异弱；区分力弱；与f_chip_peak_dominance高相关，避免重复约束
- `f_platform_len`: |delta|=0.0458；missing_max=0.00%；方向=差异弱；区分力弱

## 3. 重点特征区间建议（非最终阈值）
- `f_trend_close_ma20_gap` (硬过滤候选): 宽松=[0.056826, +inf)，中性=[0.065266, +inf)，严格=[0.073707, +inf)；过严会错杀可交易A样本，建议先用宽松/中性；过松会放入结构未启动的C样本
- `f_k_pct_chg` (触发确认候选): 宽松=[0.030288, +inf)，中性=[0.036121, +inf)，严格=[0.041954, +inf)；更适合T日/触发层，不宜前置硬卡
- `f_strength_rs20_xsec_q` (硬过滤候选): 宽松=[0.748430, +inf)，中性=[0.777255, +inf)，严格=[0.806079, +inf)；过严会错杀可交易A样本，建议先用宽松/中性；过松会放入结构未启动的C样本
- `f_ind_rank_pctchg` (硬过滤候选): 宽松=[0.889286, +inf)，中性=[0.910714, +inf)，严格=[0.932143, +inf)；过严会错杀可交易A样本，建议先用宽松/中性；过松会放入结构未启动的C样本
- `f_chip_winner_rate` (硬过滤候选): 宽松=[0.860202, +inf)，中性=[0.885035, +inf)，严格=[0.909868, +inf)；过严会错杀可交易A样本，建议先用宽松/中性；过松会放入结构未启动的C样本
- `f_chip_stability_std10` (硬过滤候选): 宽松=[0.002689, +inf)，中性=[0.003102, +inf)，严格=[0.003515, +inf)；过严会错杀可交易A样本，建议先用宽松/中性；过松会放入结构未启动的C样本
- `f_trend_close_ma60_gap` (连续评分候选): 宽松=[0.071012, +inf)，中性=[0.084648, +inf)，严格=[0.098285, +inf)；建议以评分分层为主，避免硬阈值；存在一定缺失，需配合QC
- `f_strength_vs_index20` (连续评分候选): 宽松=[0.045844, +inf)，中性=[0.057350, +inf)，严格=[0.068857, +inf)；建议以评分分层为主，避免硬阈值
- `f_k_body_to_atr` (触发确认候选): 宽松=[0.047884, +inf)，中性=[0.055930, +inf)，严格=[0.063975, +inf)；更适合T日/触发层，不宜前置硬卡
- `f_k_close_pos` (触发确认候选): 宽松=[0.798841, +inf)，中性=[0.806094, +inf)，严格=[0.813347, +inf)；更适合T日/触发层，不宜前置硬卡
- `f_breakout_vol_ratio20` (触发确认候选): 宽松=[1.620811, +inf)，中性=[1.693167, +inf)，严格=[1.765523, +inf)；更适合T日/触发层，不宜前置硬卡
- `f_ind_rank_amount` (连续评分候选): 宽松=[0.729762, +inf)，中性=[0.752976, +inf)，严格=[0.776190, +inf)；建议以评分分层为主，避免硬阈值

## 4. 冗余审计
- `f_platform_range20` vs `f_platform_range_best` corr=1.0000，保留 `f_platform_range20`，降级 `f_platform_range_best`
- `f_near_pivot20` vs `f_k_break_pivot20_pct` corr=1.0000，保留 `f_near_pivot20`，降级 `f_k_break_pivot20_pct`
- `f_chip_secondary_peak_ratio` vs `f_chip_peak_dominance` corr=-1.0000，保留 `f_chip_peak_dominance`，降级 `f_chip_secondary_peak_ratio`
- `f_strength_vs_index60` vs `f_strength_rs60_xsec_q` corr=0.9836，保留 `f_strength_rs60_xsec_q`，降级 `f_strength_vs_index60`
- `f_k_upper_shadow_ratio` vs `f_k_close_pos` corr=-0.9685，保留 `f_k_upper_shadow_ratio`，降级 `f_k_close_pos`
- `f_strength_vs_index20` vs `f_strength_rs20_xsec_q` corr=0.9559，保留 `f_strength_rs20_xsec_q`，降级 `f_strength_vs_index20`
- `f_strength_ret60` vs `f_strength_rs60_xsec_q` corr=0.9494，保留 `f_strength_rs60_xsec_q`，降级 `f_strength_ret60`
- `f_strength_ret60` vs `f_strength_vs_index60` corr=0.9476，保留 `f_strength_vs_index60`，降级 `f_strength_ret60`
- `f_platform_range20` vs `f_platform_range30` corr=0.8958，保留 `f_platform_range30`，降级 `f_platform_range20`
- `f_platform_range30` vs `f_platform_range_best` corr=0.8958，保留 `f_platform_range30`，降级 `f_platform_range_best`
- `f_trend_close_ma60_gap` vs `f_trend_ma20_ma60_gap` corr=0.8882，保留 `f_trend_close_ma60_gap`，降级 `f_trend_ma20_ma60_gap`
- `f_strength_ret20` vs `f_strength_vs_index20` corr=0.8828，保留 `f_strength_vs_index20`，降级 `f_strength_ret20`

## 5. 六个核心问题直答
1. 最适合进入硬过滤候选的前5个：
   - f_trend_close_ma20_gap
   - f_strength_rs20_xsec_q
   - f_ind_rank_pctchg
   - f_chip_stability_std10
   - f_chip_winner_rate
2. 最适合进入连续评分层的前5个：
   - f_trend_close_ma60_gap
   - f_strength_vs_index20
   - f_strength_ret20
   - f_strength_rs60_xsec_q
   - f_strength_vs_index60
3. 最适合进入触发确认层的前5个：
   - f_k_pct_chg
   - f_k_body_to_atr
   - f_breakout_vol_ratio20
   - f_up_down_vol_ratio20
   - f_k_upper_shadow_ratio
4. 平台/收缩类不应再设过严：`f_platform_range20`、`f_platform_range30`、`f_platform_range_best`、`f_near_pivot20`、`f_atr_ratio`。
5. 基础筹码 vs 板块前排：基础筹码均值|delta|≈0.1971，板块前排均值|delta|≈0.2144；建议下一轮权重“板块前排略高，基础筹码紧随”。
6. strong_start 里最该放松的3处：平台静态阈值、峰结构硬卡、把触发类信号前置为过滤条件。

## 6. 说明
- 本报告仅为参数反推与分层草图，不含回测或收益结论。
