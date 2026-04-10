# 二次启动策略流水线报告

## 策略说明
- 策略名称：强势回调缩量二次启动（去集合竞价过滤版）
- 数据口径：仅使用截至 t-1 的日线数据盘前筛选
- 核心改动：移除集合竞价开盘过滤，避免依赖实时竞价数据

## 回测区间
- 样本内：20251201 ~ 20260327
- 样本外：20260301 ~ 20260327
- 持有周期：3 个交易日

## 样本内指标
- 交易笔数：167
- 胜率：56.29%
- 年化收益：9563.38%
- 夏普比率：6.236
- 最大回撤：-30.10%

## 样本外指标
- 交易笔数：40
- 胜率：50.00%
- 年化收益：24.86%
- 夏普比率：0.789
- 最大回撤：-28.92%

## 样本外验证
- 交易样本充足：通过
- 胜率门槛：通过
- 年化收益门槛：通过
- 最大回撤门槛：未通过
- 综合结论：未通过

## 参数优化结果
- 最优参数：{"hold_days": 3, "drawdown_min": 0.02, "drawdown_max": 0.1, "vol_shrink_ratio": 0.85, "last_limit_up_days_min": 1, "last_limit_up_days_max": 6, "limit_up_count_10_min": 1, "limit_up_count_10_max": 1, "picks_per_day": 3}
- Alpha（样本内相对000001.SH）：667.52%

## 产出文件
- `results/secondary_launch_in_sample_trades.csv`
- `results/secondary_launch_oos_trades.csv`
- `results/secondary_launch_grid_search.csv`
- `results/secondary_launch_summary.json`
