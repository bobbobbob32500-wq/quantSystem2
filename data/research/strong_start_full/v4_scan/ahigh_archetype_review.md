# 全年 A_high 类型拆分（C2A 主线）

## 结论摘要
- 全年 A_high 可拆为 5 类（4个主 archetype + 1个混合类）。
- C2A 当前主抓类型：`A2_structure_chip`。
- C2A 当前主漏类型：`A5_mixed_other`。
- 当前问题已从单阈值问题升级为“类型通道覆盖不足”。

## 下一版主线结构方向（仅方向）
1. 保留现有 C2A 主通道用于 momentum_frontline + balanced_highscore，不动主干。
2. 新增一个“early_structure_low_rs20”专用通道（结构/压缩优先，趋势门槛后移），作为第二通道而非阈值微调。