# strong_start 执行口径总框架（阶段：设计）

基线版本：`strong_start_research_v4_freeze1`  
信号来源：`strong_start_trade_signal_definition_spec.md`  
边界：仅执行口径设计，不含回测、不含收益统计、不含执行绩效结论。

## 1. 范围冻结
- breakout / pullback_candidate / observe 定义保持不变
- 不重定义研究信号，只定义“如何进入执行验证”
- 不引入未来字段（禁止 T+1 收益、MAE/MFE、entry_possible 等）

## 2. 四个执行口径对象

### A. 信号确认时点（Signal Confirmation Time）
- 当前研究版信号在 **T 日收盘后** 才成立（事件日口径）。
- 所有交易候选定义必须建立在 T 日收盘可见信息上。
- 不做盘中“事后补确认”来重写研究信号。

### B. 可执行时点（Executable Time）
- 候选信号最早进入执行判断的时点是 **T+1**。
- 可执行时点分三类口径（仅设计）：
  1. T+1 开盘执行口径
  2. T+1 盘中继续确认后执行口径
  3. T+1 回落不破结构后执行口径

### C. 成交假设对象（Execution Assumption Objects）
- breakout 候选：重点验证“延续确认与追价边界”
- pullback_candidate：重点验证“承接确认与结构回踩确认”
- observe：不进入执行通道，只保留观察

### D. 执行验证边界（What can/cannot be done now）
- 当前可做：
  - 执行口径与不可执行边界定义
  - 执行验证中间表字段合同
  - 后续验证顺序设计
- 当前不可做：
  - 任何执行效果比较
  - 任何成交后收益判断
  - 任何回测或实盘结论

## 3. 口径设计目标
1. 解决 T 日确认与 T+1 执行错位  
2. 避免“研究强 -> 交易假强”误判  
3. 为下一步 breakout 执行口径细化提供可审计规范

