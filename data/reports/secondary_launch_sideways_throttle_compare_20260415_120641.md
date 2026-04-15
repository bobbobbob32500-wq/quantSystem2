# 二次启动策略：震荡市限流参数对比

- 生成时间：2026-04-15 12:06:41
- IS：20250901 ~ 20260228
- OOS：20260301 ~ 20260414
- 持有天数：2

## OOS 核心对比

| 方案 | 交易数 | 信号日数 | 胜率 | 平均单笔收益 | 盈亏比 | 总收益 | 最大回撤 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 基线（无震荡限流） | 34 | 21 | 38.24% | -0.13% | 0.97 | -29.37% | -50.77% |
| 震荡限流方案 | 32 | 21 | 37.50% | 0.24% | 1.06 | -32.17% | -51.12% |

## 震荡市（sideways）分组对比（OOS）

| 方案 | 交易数 | 胜率 | 平均收益 | 中位收益 | 盈亏比 | 总收益 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 基线（无震荡限流） | 19 | 26.32% | -3.39% | -3.38% | 0.28 | -50.21% |
| 震荡限流方案 | 18 | 27.78% | -2.81% | -3.34% | 0.33 | -42.21% |

## 限流方案参数（当前配置）
- sideways_market_ret5_low: -0.02
- sideways_market_ret5_high: 0.02
- sideways_market_min_score_boost: 8.0
- sideways_market_max_picks: 1

## 输出文件
- `D:/HuaweiAI/quantSystem2/data/reports/secondary_launch_sideways_throttle_compare_20260415_120641.json`
- `D:/HuaweiAI/quantSystem2/data/reports/secondary_launch_sideways_throttle_compare_20260415_120641.md`
