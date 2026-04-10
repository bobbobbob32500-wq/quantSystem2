# strong_start 执行口径验证设计报告（阶段）

## 0. 约束确认
- breakout / pullback_candidate / observe 信号定义保持不变。
- 当前仅设计执行口径，不重定义信号。
- 仅基于 T 日可见信息，不引入未来字段。
- 不做回测，不做收益统计，不做执行绩效结论。

## 1. 执行口径框架结论
- 信号确认时点：T 日收盘后。
- 可执行时点：最早 T+1（开盘/盘中确认/回落确认三类）。
- 成交假设对象：breakout 与 pullback_candidate 分通道设计，observe 不进执行通道。
- 执行验证边界：当前只做口径与字段合同，执行可达性留到后续阶段。

## 2. breakout 执行口径设计结论
- A：T+1 开盘执行（最简、可审计）
- B：T+1 盘中继续确认后执行（优先建议）
- C：T+1 回落不破结构后执行（更稳健但接近 pullback 通道）

优先建议：先细化 **B 通道**，因为它最直接修复 T 日确认与 T+1 执行错位。

## 3. pullback_candidate 执行口径设计结论
- pullback_candidate 当前应维持“待执行验证对象”定位。
- 不直接升级为交易就绪信号。
- 先准备两条口径：P1 开盘承接型、P2 结构回踩确认型。

## 4. 不可执行边界结论
应直接定义并纳入执行规范的边界：
- 高开脱离
- 一字/近一字不可合理参与
- gap 过大
- 盘中确认依赖过强（日线不可安全映射）
- breakout/pullback 结构模糊
- 解释强但触发不完整

## 5. 执行字段合同结论
- 中间表建议：`trade_execution_assumption_table`
- 主键：`ts_code + trade_date + trade_signal_class`
- 关键字段：`execution_mode_candidate`、`execution_ready_flag`、`execution_risk_tag`、`execution_reject_reason`、`execution_assumption_note`
- 严禁字段：任何未来收益与成交后结果字段

## 6. 六个执行口径问题直接回答
1. breakout 最适合先验证的口径：**T+1 盘中继续确认后执行（B）**。  
2. 最大错位：T 日信号成立但 T+1 出现高开脱离或结构转弱，导致“研究强、执行弱”。  
3. 最易“研究强但买不到”的 breakout：高开跳空过大、流动性受限、盘中快速冲回落类型。  
4. pullback_candidate 当前定位：**待执行验证对象**，不是交易就绪信号。  
5. 当前应优先定义的不可执行边界：**高开脱离 + 一字/近一字不可参与边界**。  
6. 若下一阶段只验证一条通道：先做 **breakout**，因定义更清晰、信号闭环更完整。

## 7. 下一步阶段建议
- 进入“breakout 执行口径验证设计细化（A1）”阶段。
- 仍不进入回测与收益评价阶段。

