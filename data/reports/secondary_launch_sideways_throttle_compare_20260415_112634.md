# 二次启动策略：震荡市限流参数对比

- 生成时间：2026-04-15 11:26:34
- IS：20250901 ~ 20260228
- OOS：20260301 ~ 20260414
- 持有天数：2

## OOS 核心对比

| 方案 | 交易数 | 信号日数 | 胜率 | 平均单笔收益 | 盈亏比 | 总收益 | 最大回撤 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 基线（无震荡限流） | 34 | 21 | 38.24% | -0.13% | 0.97 | -29.37% | -50.77% |
| 震荡限流方案 | 34 | 21 | 38.24% | -0.13% | 0.97 | -29.37% | -50.77% |

## 震荡市（sideways）分组对比（OOS）

| 方案 | 交易数 | 胜率 | 平均收益 | 中位收益 | 盈亏比 | 总收益 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 基线（无震荡限流） | 19 | 26.32% | -3.39% | -3.38% | 0.28 | -50.21% |
| 震荡限流方案 | 19 | 26.32% | -3.39% | -3.38% | 0.28 | -50.21% |

## 限流方案参数（当前配置）
- sideways_market_ret5_low: -0.015
- sideways_market_ret5_high: 0.015
- sideways_market_min_score_boost: 10.0
- sideways_market_max_picks: 1

## 输出文件
- `D:/HuaweiAI/quantSystem2/data/reports/secondary_launch_sideways_throttle_compare_20260415_112634.json`
- `D:/HuaweiAI/quantSystem2/data/reports/secondary_launch_sideways_throttle_compare_20260415_112634.md`
