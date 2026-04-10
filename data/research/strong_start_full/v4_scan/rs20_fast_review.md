# rs20 eligibility 最短路径快审

## 结论摘要
- rs20 漏抓 A_high 特征：rs20中位数 miss=0.4394 vs in_core=0.9166；platform中位数 miss=0.6381 vs in_core=0.6351。
- 推荐候选：`C2A`
- 当前不应恢复买点开发。

## R1 vs R2 对比
- C2A: n=636, A_high_recall=5.48%, A_high/C=0.2987, mean_t2=0.4632%, win_t2=50.16%
- R1: n=638, A_high_recall=5.40%, A_high/C=0.2944, mean_t2=0.4350%, win_t2=50.00%
- R2: n=637, A_high_recall=5.40%, A_high/C=0.2918, mean_t2=0.4513%, win_t2=50.24%

## 4 个问题直接回答
1. rs20漏抓A_high是否可挽救：是，存在“rs20略低但平台/筹码不差”的样本。
2. R1/R2更值得落地：C2A
3. 是否实质优于C2A：否
4. 现在是否继续买点开发：不应该