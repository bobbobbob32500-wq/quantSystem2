# 二次启动盘中最佳买点回放报告

- 生成时间: 2026-04-02 00:01:27
- 信号样本数: 80
- 有效盘中入场数: 19
- 未触发盘中入场数: 61
- 分钟数据来源: `D:\HuaweiAI\quantSystem2\data\history_recommendation.db`

## 买点子类型对比

| 子类型 | 样本数 | 胜率 | 平均收益 | 中位收益 | 最佳 | 最差 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| secondary_launch_pullback | 19 | 63.16% | 0.78% | 0.77% | 6.02% | -1.27% |

## 分钟窗口胜率对比

| 子类型 | 窗口 | 样本数 | 胜率 | 平均收益 | 中位收益 |
| --- | ---: | ---: | ---: | ---: | ---: |
| secondary_launch_pullback | 15m | 19 | 68.42% | 0.86% | 0.80% |
| secondary_launch_pullback | 30m | 19 | 63.16% | 0.78% | 0.77% |
| secondary_launch_pullback | 5m | 19 | 47.37% | 0.20% | 0.00% |
| secondary_launch_pullback | 60m | 17 | 70.59% | 1.46% | 1.04% |

## 最优卖点 / 止损规则

| 适用范围 | 规则 | 样本数 | 胜率 | 平均收益 | 中位收益 |
| --- | --- | ---: | ---: | ---: | ---: |
| all | SL -4.0% | TP 8.0% | TR none | HOLD 240m | 19 | 73.68% | 1.89% | 1.78% |
| secondary_launch_pullback | SL -4.0% | TP 8.0% | TR none | HOLD 240m | 19 | 73.68% | 1.89% | 1.78% |

## 观察结论

- 当前分钟级回放中，`secondary_launch_pullback` 表现最佳，样本 `19` 条，平均收益 `0.78%`。
- 最佳观察窗口为 `secondary_launch_pullback / 60m`，平均收益 `1.46%`。
- 当前全样本最优卖点规则为 `SL -4.0% | TP 8.0% | TR none | HOLD 240m`，平均收益 `1.89%`，胜率 `73.68%`。