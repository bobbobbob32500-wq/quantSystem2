# strong_start_trade_signal_fields_contract

表名建议：`trade_signal_definition_table`  
用途：阶段A信号定义验证的数据契约（非交易执行表）。

## 1) 主键字段
- `ts_code`
- `trade_date`

## 2) 研究版来源字段（只读映射）
- `is_candidate_after_filters`
- `score_total`
- `trigger_status`
- `signal_ready_research`（由研究版 `signal_ready` 映射）
- `trigger_breakout_pass`
- `trigger_momentum_pass`
- `trigger_quality_pass`
- `filter_reject_reasons`
- `score_details`
- `trigger_details`
- `explain_json`

## 3) 交易版定义字段（阶段A新增）
- `score_gate_pass`  
  含义：过滤通过且评分达候选线。
- `trade_signal_class`  
  枚举：`breakout` / `pullback_candidate` / `observe`。
- `trade_signal_tier`  
  枚举：`high_confidence` / `normal` / `watchlist` / `observe`。
- `trade_signal_ready`  
  含义：是否进入下一步执行口径验证主队列（当前主要 breakout）。
- `trade_signal_reject_reason`  
  含义：未进入候选或未就绪的结构原因。
- `trade_signal_explain`  
  含义：关键解释摘要（来源于过滤/触发/评分解释链）。
- `key_reason_1`, `key_reason_2`, `key_reason_3`  
  含义：结构解释的前三条原因。

## 4) 解释辅助字段（可选）
- `industry`
- `name`
- `score_axis_strength`
- `score_axis_industry`
- `score_axis_chip`

## 5) 字段约束
- 所有定义字段必须只依赖 T 日可见信息。
- 严禁引入执行结果字段（成交、持仓、收益、未来价格）。
- 严禁用未来标签字段（`*_fwd_*`, `entry_*`, `MFE/MAE`）。

## 6) 输出边界声明
- 本表用于“交易候选定义验证”，不是交易绩效结论表。
- `trade_signal_ready=True` 仅表示进入下一阶段执行口径验证，不表示可盈利。

