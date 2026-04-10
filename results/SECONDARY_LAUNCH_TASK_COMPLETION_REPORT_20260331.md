# 二次启动策略任务完成报告

## 任务目标

本轮任务围绕以下 4 个目标展开：

1. 移除集合竞价过滤，改为纯日线盘前筛选
2. 运行完整流水线，获取真实回测与优化结果
3. 完成样本外验证，并据结果评估稳健性
4. 集成到主菜单，支持日常使用

## 已完成事项

### 1. 策略实现与规则调整

- 已确认并保留“去集合竞价过滤”方案
- 策略仅使用截至 `t-1` 的日线数据生成次日候选
- 配置中 `stock_selection.secondary_launch.use_auction_filter` 保持为 `false`

### 2. 回测与流水线修复

已修复以下关键问题：

- 回测窗口缺少预热历史，导致样本外曾出现 `0` 笔交易
- 参数优化重复计算特征，导致流水线耗时过长
- 信号生成逐日全表扫描，影响回测性能
- 参数搜索时重复按股票代码切片价格表，影响优化速度

修复后：

- 单次回测耗时从约 `128s` 降至约 `81s`
- 参数网格搜索可在约 `91s` 内完成
- 完整流水线已成功跑通并产出结果文件

### 3. 样本外验证结果

实际流水线输出如下：

- 样本内交易数：`253`
- 样本内胜率：`47.83%`
- 样本内年化收益：`37.90%`
- 样本外交易数：`55`
- 样本外胜率：`29.09%`
- 样本外年化收益：`-79.24%`
- 样本外最大回撤：`-92.11%`

验证门槛结果：

- 交易样本数：通过
- 胜率门槛：未通过
- 年化收益门槛：未通过
- 最大回撤门槛：未通过
- 综合结论：`未通过`

### 4. 参数优化结果

当前最优参数组合为：

- `drawdown_min = 0.025`
- `drawdown_max = 0.09`
- `vol_shrink_ratio = 0.75`
- `last_limit_up_days_min = 2`
- `last_limit_up_days_max = 6`

该参数已自动写回配置文件。

### 5. 主菜单集成

已在主菜单新增入口：

- `17. 二次启动策略`

子菜单功能包括：

- 运行完整流水线
- 查看最新回测摘要
- 查看历史信号
- 运行盘前选股

## 本次新增/更新文件

### 新增

- `src/modules/secondary_launch_menu.py`
- `tests/test_mainboard_secondary_launch_backtester.py`
- `results/SECONDARY_LAUNCH_TASK_COMPLETION_REPORT_20260331.md`

### 更新

- `src/modules/mainboard_secondary_launch_strategy.py`
- `src/modules/mainboard_secondary_launch_backtester.py`
- `tools/run_secondary_launch_pipeline.py`
- `src/modules/__init__.py`
- `main.py`

## 产出结果文件

- `results/secondary_launch_in_sample_trades.csv`
- `results/secondary_launch_oos_trades.csv`
- `results/secondary_launch_grid_search.csv`
- `results/secondary_launch_summary.json`
- `results/secondary_launch_pipeline_report.md`

## 风险与结论

本轮任务的“系统开发与集成”已经完成，但“策略可直接上线使用”的结论暂时不能给出，原因如下：

- 样本外胜率明显低于预期门槛
- 样本外收益为负，且回撤极大
- 当前参数虽然在样本内更优，但没有表现出足够稳健的泛化能力

因此，更准确的结论是：

`开发完成，验证未通过，暂不建议直接实盘使用。`

## 建议的后续方向

1. 优先检查收益/回撤统计口径，确认是否需要引入资金曲线与持仓并发约束
2. 缩小参数空间，重点回测 `vol_shrink_ratio` 和持有期组合
3. 增加分市场环境统计，区分强势、震荡、弱势阶段表现
4. 如用于日常观察，可先作为候选池策略，不建议直接作为实盘执行策略
