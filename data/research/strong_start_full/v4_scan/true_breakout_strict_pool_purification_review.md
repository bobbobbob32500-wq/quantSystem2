# Strict Pool Purification Review

## Summary
- strict_pool size: 12 (A_high=5, C=5, A_low=2)
- Focus: priority_tag=1 & path_source=A only.

## Stable vs unstable hints
- all findings: {'score_platform_axis_single': {'A_high_median': 0.5898925385239254, 'C_median': 0.6245640713706406, 'median_gap_A_minus_C': -0.0346715328467152}, 'score_industry_axis_single': {'A_high_median': 0.5727633477633478, 'C_median': 0.5697691197691197, 'median_gap_A_minus_C': 0.0029942279942281047}, 'score_chip_axis_single': {'A_high_median': 0.7262731039164955, 'C_median': 0.8007075205204882, 'median_gap_A_minus_C': -0.07443441660399275}, 'f_chip_winner_rate': {'A_high_median': 0.9758907324152879, 'C_median': 0.9838066163956888, 'median_gap_A_minus_C': -0.007915883980400884}, 'f_platform_compress_ratio': {'A_high_median': 0.44751381215469593, 'C_median': 0.425824175824176, 'median_gap_A_minus_C': 0.021689636330519957}}
- main findings: {'score_platform_axis_single': {'A_high_median': 0.6101378751013787, 'C_median': 0.5886303730738036, 'median_gap_A_minus_C': 0.02150750202757512}, 'score_industry_axis_single': {'A_high_median': 0.618867243867244, 'C_median': 0.698003848003848, 'median_gap_A_minus_C': -0.07913660413660395}, 'score_chip_axis_single': {'A_high_median': 0.7262731039164955, 'C_median': 0.751822739927478, 'median_gap_A_minus_C': -0.02554963601098248}, 'f_chip_winner_rate': {'A_high_median': 0.9760319576907811, 'C_median': 0.9865957182869596, 'median_gap_A_minus_C': -0.010563760596178473}, 'f_platform_compress_ratio': {'A_high_median': 0.44047619047619047, 'C_median': 0.4556960657155209, 'median_gap_A_minus_C': -0.015219875239330438}}
- confirm findings: {'score_platform_axis_single': {'A_high_median': 0.5573296836982968, 'C_median': 0.6677514193025141, 'median_gap_A_minus_C': -0.11042173560421731}, 'score_industry_axis_single': {'A_high_median': 0.5274651274651274, 'C_median': 0.5697691197691197, 'median_gap_A_minus_C': -0.04230399230399229}, 'score_chip_axis_single': {'A_high_median': 0.8134708682838359, 'C_median': 0.8007075205204882, 'median_gap_A_minus_C': 0.012763347763347643}, 'f_chip_winner_rate': {'A_high_median': 0.9711182399039282, 'C_median': 0.9838066163956888, 'median_gap_A_minus_C': -0.012688376491760578}, 'f_platform_compress_ratio': {'A_high_median': 0.4805136628341047, 'C_median': 0.425824175824176, 'median_gap_A_minus_C': 0.054689487009928706}}

## Candidate filters (simulation only)
- F3_combo_platform_industry_compress: A_high_keep=100.00%, C_remove=60.00%, A_high_share_after=71.43%, C_share_after=28.57%
- F1_platform_cap: A_high_keep=100.00%, C_remove=40.00%, A_high_share_after=62.50%, C_share_after=37.50%
- F2_industry_overheat_cap: A_high_keep=100.00%, C_remove=20.00%, A_high_share_after=45.45%, C_share_after=36.36%

## Window stability note
- F1_platform_cap: stable_windows=2/3 (criterion: A_high_keep>=60% and C_remove>=20%)
- F2_industry_overheat_cap: stable_windows=2/3 (criterion: A_high_keep>=60% and C_remove>=20%)
- F3_combo_platform_industry_compress: stable_windows=3/3 (criterion: A_high_keep>=60% and C_remove>=20%)

## Candidate directions (not landed)
1. Add a light platform-axis cap within strict_pool candidate layer.
2. Add an industry-overheat cap to reduce Path-A pseudo-strength C contamination.
3. Add a light combo gate (platform+industry+compress) only inside strict_pool final gate.

## Direct answers
1. 是，当前主战场已经明确为 priority_tag=1 & path_source=A。
2. 是，strict_pool 内部 A_high 与 C 在平台轴、行业轴、筹码/压缩字段上存在可见差异。
3. 部分稳定：平台轴与行业轴差异在双窗口方向基本同向，但样本较小，幅度有波动。
4. 是，已找到最小改动候选方向（平台轴上限、行业过热上限、平台+行业+压缩组合门）。
5. 是，具备进入 strict_pool 纯化落地验证阶段条件。
6. 不应该。当前仍应先做 strict_pool 纯化，不应继续买点开发。