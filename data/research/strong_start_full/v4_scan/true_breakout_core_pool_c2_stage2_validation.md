# C2 第二阶段：PathA rank cutoff + dual eligibility 验证

## 结论摘要
- 单刀对召回提升贡献更大的是：`PathA rank cutoff`。
- 当前性价比最高单刀候选：`C2A_rank_relax`。
- 组合候选 `C2AB_combo` 是否值得进第三阶段：可作为候选，但非最优。
- 当前仍不应恢复买点开发。

## 全年关键数值（A_high召回率 / A_high/C / win_t2）
- C2: 5.48% / 0.3013 / 49.44%
- C2A_rank_relax: 5.48% / 0.2987 / 50.16%
- C2B_eligibility_relax: 5.40% / 0.2931 / 49.76%
- C2AB_combo: 5.40% / 0.2931 / 50.00%

## 210 子集方向一致性
- C2: n=208, A_high/C=0.3875, win_t2=54.81%, mean_t2=0.9377%
- C2A_rank_relax: n=208, A_high/C=0.3875, win_t2=54.81%, mean_t2=0.9377%
- C2B_eligibility_relax: n=208, A_high/C=0.3875, win_t2=54.81%, mean_t2=0.9377%
- C2AB_combo: n=208, A_high/C=0.3875, win_t2=54.81%, mean_t2=0.9377%

## 推进判断
- 第三阶段优先候选：`C2`
- 当前应继续召回主线验证，不应恢复买点开发。