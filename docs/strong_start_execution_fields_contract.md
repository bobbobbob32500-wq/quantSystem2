# strong_start 执行验证字段合同（设计版）

表名建议：`trade_execution_assumption_table`  
阶段：执行口径验证设计（非回测执行表）。

## 1) 主键
- `ts_code`
- `trade_date`
- `trade_signal_class`

## 2) 信号来源字段（来自阶段A）
- `trade_signal_ready`
- `trade_signal_class`
- `trade_signal_tier`
- `trade_signal_explain`
- `score_total`
- `is_candidate_after_filters`
- `trigger_status`
- `trigger_breakout_pass`
- `trigger_momentum_pass`
- `trigger_quality_pass`

## 3) 执行口径字段（本阶段定义）
- `execution_mode_candidate`  
  示例：`breakout_t1_open` / `breakout_t1_confirm` / `breakout_t1_pullback` / `pullback_p1` / `pullback_p2`
- `execution_ready_flag`  
  含义：是否进入下一步“执行可达性验证”队列。
- `execution_risk_tag`  
  示例：`gap_risk_high` / `intraday_confirmation_required` / `structure_ambiguous`
- `execution_reject_reason`  
  含义：不可执行或执行存疑的结构原因。
- `execution_assumption_note`  
  含义：口径注释与审计说明。

## 4) 分型字段

### breakout 通道字段
- `breakout_mode`（A/B/C）
- `breakout_confirmation_required`（bool）
- `breakout_gap_guard_required`（bool）

### pullback 通道字段
- `pullback_mode`（P1/P2）
- `pullback_structure_check_required`（bool）
- `pullback_pending_validation_flag`（bool）

## 5) 衔接关系
- 来源表：`trade_signal_definition_table`（或等价结果）
- 去向：后续执行可达性验证输入（不是订单表，不是成交表）

## 6) 严格禁止字段
- 任何未来收益字段
- 任何成交后结果字段（成交价、滑点结果、持仓收益）
- `MAE/MFE/entry_possible` 等未来标签

