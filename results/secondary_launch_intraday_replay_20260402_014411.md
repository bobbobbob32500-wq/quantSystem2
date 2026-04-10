# 二次启动盘中最佳买点回放报告

- 生成时间: 2026-04-02 01:44:11
- 信号样本数: 66
- 有效盘中入场数: 18
- 未触发盘中入场数: 44
- 分钟数据来源: `D:\HuaweiAI\quantSystem2\data\history_recommendation.db`

## 买点子类型对比

| 子类型 | 样本数 | 胜率 | 平均收益 | 中位收益 | 最佳 | 最差 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| secondary_launch_pullback | 18 | 61.11% | 0.78% | 0.40% | 6.02% | -1.76% |

## 分钟窗口胜率对比

| 子类型 | 窗口 | 样本数 | 胜率 | 平均收益 | 中位收益 |
| --- | ---: | ---: | ---: | ---: | ---: |
| secondary_launch_pullback | 15m | 18 | 50.00% | 0.89% | 0.24% |
| secondary_launch_pullback | 30m | 18 | 61.11% | 0.78% | 0.40% |
| secondary_launch_pullback | 5m | 18 | 50.00% | 0.12% | 0.04% |
| secondary_launch_pullback | 60m | 16 | 68.75% | 1.20% | 0.80% |

## 最优卖点 / 止损规则

| 适用范围 | 规则 | 样本数 | 胜率 | 平均收益 | 中位收益 |
| --- | --- | ---: | ---: | ---: | ---: |
| all | SL -2.0% | TP 5.0% | TR none | HOLD 120m | 18 | 61.11% | 1.22% | 0.54% |
| secondary_launch_pullback | SL -2.0% | TP 5.0% | TR none | HOLD 120m | 18 | 61.11% | 1.22% | 0.54% |

## 观察结论

- 当前分钟级回放中，`secondary_launch_pullback` 表现最佳，样本 `18` 条，平均收益 `0.78%`。
- 最佳观察窗口为 `secondary_launch_pullback / 60m`，平均收益 `1.20%`。
- 当前全样本最优卖点规则为 `SL -2.0% | TP 5.0% | TR none | HOLD 120m`，平均收益 `1.22%`，胜率 `61.11%`。