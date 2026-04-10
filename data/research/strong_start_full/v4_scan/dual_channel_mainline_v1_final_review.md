# dual_channel_mainline_v1 正式落地验证

## 版本冻结
- main_channel = C2A_rank_relax
- early_structure_channel = ECH2
- dual_channel_mainline_v1 = C2A OR ECH2

## 结论摘要
- 双通道是否值得正式替代单通道：是
- 全年 A_high 召回：5.48% -> 6.59% (Δ +1.11%)
- 全年 A_high/C：0.2987 -> 0.2748 (Δ -0.0239)
- 全年 A_low+C 占比：43.87% -> 44.43% (Δ +0.56%)
- 全年 win_t2：50.16% -> 49.22% (Δ -0.94%)
- 当前不应恢复买点开发。

## archetype 覆盖变化（A_high）
- A2_structure_chip: 34.04% -> 39.36%
- A3_early_structure_low_rs20: 0.84% -> 3.80%
- A4_balanced_highscore: 25.00% -> 25.00%
- A5_mixed_other: 2.70% -> 2.94%

## 推进判断
- 建议正式替代 C2A（进入新主线）
- 当前是否继续买点开发：不应该

## 窗口快照
- 主窗口 A_high/C: 0.2778 -> 0.2593；win_t2: 48.45% -> 47.77%
- 确认窗口 A_high/C: 0.3559 -> 0.2917；win_t2: 56.47% -> 55.50%