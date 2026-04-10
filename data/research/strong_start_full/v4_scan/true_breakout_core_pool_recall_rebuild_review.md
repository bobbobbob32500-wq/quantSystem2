# core_pool 召回优先重建审计

## 结论摘要
- 当前 core_pool 对全年 A_high（n=1260）召回明显不足，属于召回优先问题。
- `not_in_core_pool` 分层漏抓 Top3：step2_fail_pathA_rank_cutoff, step1_fail_dual_path_eligibility, step2_fail_pathB_rank_cutoff
- 候选方向中最优（按 A_high 召回优先）为：`C2_expand_daily_quotas`。

## not_in_core_pool A_high 漏因 Top3
- step2_fail_pathA_rank_cutoff: miss=500, 占A_high总量=39.68%, 占not_in_core_A_high=41.15%
- step1_fail_dual_path_eligibility: miss=309, 占A_high总量=24.52%, 占not_in_core_A_high=25.43%
- step2_fail_pathB_rank_cutoff: miss=205, 占A_high总量=16.27%, 占not_in_core_A_high=16.87%

## A_high in_core vs out_core 中位数快照
- `score_platform_axis_single` median: in=0.6554, out=0.4408
- `score_industry_axis_single` median: in=0.4072, out=0.5306
- `f_platform_compress_ratio` median: in=0.3985, out=0.5827
- `f_chip_winner_rate` median: in=0.9575, out=0.7803

## 召回优先 candidate 结论
- 推荐下一轮落地方向：`C2_expand_daily_quotas`（keep cutoffs, expand day quotas (A:1->2, B:2->3)）
- A_high 召回率：5.48%，A 召回率：4.56%
- 选中样本数：627，A_high/C：0.3013

## 推进判断
- 应先进入“召回优先 core_pool 落地验证”阶段。
- 当前不应继续买点开发，先修复全年召回主矛盾。