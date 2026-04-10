# strong_start_trade_signal_definition_spec

阶段：A（交易版信号定义验证）  
基线：`strong_start_research_v4_freeze1`（默认 `neutral` 档）  
边界：仅使用 T 日可见信息；禁止任何未来字段/执行结果字段。

## 1) 输入与禁止项

允许输入（研究版输出）：
- `is_candidate_after_filters`
- `score_total`
- `trigger_status`
- `signal_ready`（仅作研究参考）
- `trigger_breakout_pass`
- `trigger_momentum_pass`
- `trigger_quality_pass`
- `filter_reject_reasons`
- `score_details`
- `trigger_details`
- `explain_json`

禁止混入：
- 任何 `*_fwd_*`
- `entry_*`
- `MAE/MFE`
- `entry_possible`
- 任何 T+1 及以后执行/收益字段

## 2) 交易候选池与观察池边界

### A. 可进入交易候选池
定义：`trade_signal_class in {breakout, pullback_candidate}`

准入基础：
1. `is_candidate_after_filters=True`
2. `score_total >= score_candidate_line`
3. 再按触发结构分型（breakout / pullback_candidate）

`score_candidate_line`（freeze1-neutral）：`52`

### B. 仅研究观察（不进入交易候选池）
定义：`trade_signal_class=observe`

典型情形：
- 过滤未通过
- 评分未达候选线
- 触发结构不足（不构成候选）

## 3) 三类信号定义（正式）

### 3.1 breakout
必要条件：
1. 过滤通过
2. 评分达线
3. `trigger_status=True`
4. `trigger_breakout_pass=True`

辅助增强项（非必要）：
- `trigger_momentum_pass`
- `trigger_quality_pass`

就绪定义：
- `trade_signal_ready=True`

### 3.2 pullback_candidate（待执行验证候选）
必要条件：
1. 过滤通过
2. 评分达线
3. breakout 条件未满足
4. `trigger_momentum_pass OR trigger_quality_pass`（至少一项）

本阶段定位：
- 仅定义为“待执行验证候选”
- `trade_signal_ready=False`

### 3.3 observe
定义：
- 不满足交易候选池准入

用途：
- 研究观察与解释复核
- 不进入下一步执行口径验证的主候选集

## 4) 候选分层（tier）

### breakout
- `high_confidence`：`score_total>=85` 且 `momentum+quality` 同时通过
- `normal`：其余 breakout

### pullback_candidate
- `normal`：`score_total>=80`
- `watchlist`：其余 pullback_candidate

### observe
- `watchlist/observe`：仅观察，不作交易候选

## 5) 为什么不能只用 `signal_ready=True`

`signal_ready` 是研究版综合就绪标签，但交易版需要补充：
- 交易信号分型（breakout / pullback_candidate / observe）
- 候选层级（high_confidence / normal / watchlist）
- 拒绝原因与解释摘要

因此交易版候选定义必须是二次结构化映射，不可直接等价于研究标签。

