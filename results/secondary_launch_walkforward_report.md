# 二次启动策略 Walk-Forward 优化报告

## 数据范围
- 全样本：20250901 ~ 20260331
- 验证方式：4 折滚动样本外验证

## 最优参数
- hold_days: 2
- drawdown: 3.00% ~ 8.00%
- vol_shrink_ratio: 0.60
- last_limit_up_days: 2 ~ 4
- limit_up_count_10: 1 ~ 1
- picks_per_day: 2

## Walk-Forward 汇总
- 有效样本外折数: 4
- 样本外总交易数: 21
- 平均样本外胜率: 68.01%
- 平均样本外日胜率: 85.00%
- 平均样本外单笔收益: 3.09%
- 平均样本外最大回撤: -0.66%

## 全样本结果
- 交易数: 21
- 胜率: 61.90%
- 日胜率: 78.57%
- 平均单笔收益: 2.27%
- 最大回撤: -2.56%

## 输出文件
- `results/secondary_launch_walkforward_candidates.csv`
- `results/secondary_launch_walkforward_summary.json`
