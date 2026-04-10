# 双通道主线快审

## 结论摘要
- ECH 对 A3/A5 的覆盖改善：A3 recall C2A=0.84%, 最佳双通道=18.57%
- 当前最优候选：`C2A+ECH1`
- 是否明显优于单通道 C2A：是

## ECH1 vs ECH2 对比
- C2A: n=636, A_high_recall=5.48%, A_high/C=0.2987, mean_t2=0.4632%, win_t2=50.16%
- C2A+ECH1: n=1696, A_high_recall=10.71%, A_high/C=0.2167, mean_t2=0.3325%, win_t2=47.94%
- C2A+ECH2: n=835, A_high_recall=6.59%, A_high/C=0.2748, mean_t2=0.3911%, win_t2=49.22%

## 单通道 vs 双通道覆盖对比（A_high archetype）
- A2_structure_chip: C2A=34.04%, best=56.38%
- A3_early_structure_low_rs20: C2A=0.84%, best=18.57%
- A5_mixed_other: C2A=2.70%, best=3.07%

## 4 个问题的直接回答
1. 双通道是否优于单通道微调：是
2. ECH1 / ECH2 更适合作为早启动通道：ECH1
3. C2A+最优 ECH 是否明显优于 C2A：是
4. 当前是否继续买点开发：不应该