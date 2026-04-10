# dual path eligibility 快速审计（C2A 基线）

## 结论摘要
- step1 最大漏抓子条件：`fail_pathA_rs20_min`（302）
- 推荐候选：`C2A`
- A_high 召回：C2A 5.48% -> C2A 5.48%
- 当前不应恢复买点开发。

## D1 vs D2
- D1: n=637, A_high_recall=5.48%, A_high/C=0.2974, mean_t2=0.4590%, win_t2=50.08%
- D2: n=640, A_high_recall=5.40%, A_high/C=0.2931, mean_t2=0.4324%, win_t2=50.00%

## 4 个问题直接回答
1. 最大漏抓点：fail_pathA_rs20_min
2. 更值得落地：C2A
3. 召回是否还有提升空间：有限
4. 现在是否继续买点开发：不应该