# 二次启动盘中最佳买点回放报告

- 生成时间: 2026-04-01 11:14:02
- 信号样本数: 80
- 有效盘中入场数: 22
- 未触发盘中入场数: 58
- 分钟数据来源: `D:\HuaweiAI\quantSystem2\data\history_recommendation.db`

## 买点子类型对比

| 子类型 | 样本数 | 胜率 | 平均收益 | 中位收益 | 最佳 | 最差 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| secondary_launch_pullback | 22 | 59.09% | 0.50% | 0.42% | 6.02% | -3.03% |

## 分钟窗口胜率对比

| 子类型 | 窗口 | 样本数 | 胜率 | 平均收益 | 中位收益 |
| --- | ---: | ---: | ---: | ---: | ---: |
| secondary_launch_pullback | 15m | 22 | 63.64% | 0.56% | 0.49% |
| secondary_launch_pullback | 30m | 22 | 59.09% | 0.50% | 0.42% |
| secondary_launch_pullback | 5m | 22 | 40.91% | 0.15% | 0.00% |
| secondary_launch_pullback | 60m | 19 | 57.89% | 1.06% | 0.75% |

## 最优卖点 / 止损规则

| 适用范围 | 规则 | 样本数 | 胜率 | 平均收益 | 中位收益 |
| --- | --- | ---: | ---: | ---: | ---: |
| all | SL -1.5% | TP 8.0% | TR none | HOLD 240m | 22 | 63.64% | 1.42% | 0.99% |
| secondary_launch_pullback | SL -1.5% | TP 8.0% | TR none | HOLD 240m | 22 | 63.64% | 1.42% | 0.99% |

## 观察结论

- 当前分钟级回放中，`secondary_launch_pullback` 表现最佳，样本 `22` 条，平均收益 `0.50%`。
- 最佳观察窗口为 `secondary_launch_pullback / 60m`，平均收益 `1.06%`。
- 当前全样本最优卖点规则为 `SL -1.5% | TP 8.0% | TR none | HOLD 240m`，平均收益 `1.42%`，胜率 `63.64%`。