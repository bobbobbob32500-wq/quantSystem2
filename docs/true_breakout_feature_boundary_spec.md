# true_breakout_feature_boundary_spec

## A. 特征边界总原则
1. 仅使用 `T` 日及以前可见信息。
2. 事件级一行一快照（`ts_code + trade_date`）。
3. 禁止未来字段、执行字段、交易结果字段混入。

## B. 特征维度（研究可用）
- 趋势强势：相对强度、均线位置与斜率。
- 板块/行业前排：行业强度、行业内排名。
- 量能节奏：量比、量能收缩/放大结构。
- 平台/结构：区间振幅、压缩度、平台位置。
- 基础筹码：集中度、稳定性、获利盘类。
- 启动日K线：实体、影线、收盘位置（仅研究特征，不等于买点信号）。

## C. 字段分类

### 1) 特征字段（可入模）
- `f_strength_*`
- `f_ind_*`
- `f_vol_*`
- `f_platform_*`
- `f_chip_*`
- `f_k_*`（仅研究层使用）

### 2) 标签字段（仅监督分组）
- `label_abc`
- 任意未来窗表现字段（`*_fwd_*`）

### 3) 元数据字段
- `ts_code`, `trade_date`, `name`, `industry`, `data_version`

### 4) 必剔除字段
- 执行/交易字段（entry/exit/execution）
- 绩效字段（pnl/return/sharpe/drawdown）
- 任何未来可见性不成立字段

## D. 易混淆字段提示
- `f_k_pct_chg`, `f_k_body_to_atr`, `f_breakout_vol_ratio20`, `f_k_upper_shadow_ratio`, `f_up_down_vol_ratio20`
  - 当前可作为研究特征；
  - 禁止直接升级为买点/执行规则输入（后续单独研究）。

