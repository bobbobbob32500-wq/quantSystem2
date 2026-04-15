# Alpha158 重构技术方案（路线A：双引擎状态切换）

## 1. 目标与结论

当前 `alpha158` 的核心问题不是单点参数，而是策略链路缺失“状态切换”。  
本方案采用最小重构路径：**在不推翻现有选股框架的前提下，引入市场状态路由 + 双引擎融合评分 + 动态阈值/仓位约束**。

预期收益不是“暴增收益率”，而是：
- 提升样本外稳定性；
- 降低震荡/弱市的无效交易；
- 让回撤与交易频率更可控。

---

## 2. 架构重构（最小改动）

### 2.1 新增模块

- 文件：`src/modules/alpha158_regime_router.py`
- 作用：
  - 判定市场状态：`trend / sideways / weak / neutral`
  - 输出动态参数：`score_threshold_delta`、`top_n_multiplier`
  - 执行双引擎融合：趋势引擎 + 回调引擎

### 2.2 现有模块接入点

- 文件：`src/modules/stock_selector.py`
- 接入位置：
  - `__init__`：初始化状态路由参数与路由器实例
  - `_run_alpha158_selection`：在基础评分后做状态融合并使用动态阈值过滤
  - `run_selection`：按状态输出的 `top_n_multiplier` 调整当日有效选股数

### 2.3 配置新增

- 文件：`src/config/config.yaml`
- 新增键：
  - `alpha158_regime_router_enabled`
  - `alpha158_regime_lookback`
  - `alpha158_regime_trend_ret5_threshold`
  - `alpha158_regime_weak_ret5_threshold`
  - `alpha158_regime_ma_deviation_threshold`

---

## 3. 双引擎定义（当前实现）

## 3.1 市场状态判定

基于主板均价序列（`60*.SH`）：
- `ret5`：最近 5 日收益
- `ma_dev`：当前价相对 MA20 偏离

规则：
- `trend`：`ret5` 较高且站上 MA20
- `weak`：`ret5` 较低且跌破 MA20
- 其他：`sideways`

## 3.2 评分融合

在原始 `alpha158_score` 基础上加入增量项：
- 趋势引擎：`MA_CROSS`、`VOL_RATIO5`、`ROC5`
- 回调引擎：回调区间奖励（`ROC5`）+ 低振幅偏好（`AMP20` 反向）

最终分数：
- `fused_score = base_score + w_trend * trend_part + w_pullback * pullback_part`

权重按状态变化：
- 趋势市：趋势引擎权重更高
- 弱势市：回调引擎权重更高
- 震荡市：中间值

## 3.3 动态约束

- 动态阈值：`alpha158_score_threshold + score_threshold_delta`
- 动态数量：`effective_top_n * top_n_multiplier`

目的：
- 趋势市保证机会覆盖；
- 震荡/弱市主动收缩交易频率，优先控回撤。

---

## 4. 目录级改造方案（下一步建议）

本次是“最小接入”，后续建议按以下目录拆分，降低 `stock_selector.py` 复杂度：

- `src/modules/alpha158/`
  - `regime_router.py`（状态判定）
  - `engines.py`（趋势/回调引擎特征组合）
  - `score_fusion.py`（融合与分数校准）
  - `risk_budget.py`（状态化 top_n 与行业暴露约束）
  - `labeling.py`（训练标签定义）

重构原则：
- 单文件只做一类决策；
- 训练、回测、实盘必须共用同一套状态定义和阈值口径；
- 配置统一从 `config.yaml` 读取，禁止脚本硬编码口径漂移。

---

## 5. 验收指标（必须看样本外）

建议固定滚动样本外窗口（如最近 6 个月），至少比较以下指标：

- 交易级：
  - `win_rate`
  - `median_return`
  - `profit_factor`
- 组合级：
  - `max_drawdown`
  - `day_win_rate`
  - `sharpe_ratio`
- 稳定性：
  - 按状态分组后的收益与回撤
  - 月度漂移（最近 3 个月 vs 前 3 个月）

验收建议阈值（可按你资金属性调整）：
- 在不显著牺牲均值收益的前提下，`max_drawdown` 明显下降；
- `median_return` 由负转接近 0 或转正；
- 弱势/震荡状态的交易次数下降且亏损收敛。

---

## 6. 风险与注意事项

- 本方案是“结构优化”，不是收益承诺，必须继续做样本外验证。
- 回测仍需纳入滑点、不可成交、涨跌停约束，否则会高估效果。
- 状态机阈值不要高频手调，建议按月或按季度评估后再调整。

---

## 7. 本次已落地清单

- 已新增：`src/modules/alpha158_regime_router.py`
- 已接入：`src/modules/stock_selector.py`
  - 状态判定 + 双引擎融合评分
  - 动态阈值过滤
  - 动态 `top_n` 调整
- 已新增配置：`src/config/config.yaml` 中 `alpha158_regime_*` 参数

---

## 8. 执行与对比命令（建议）

1) 重训（已接入状态特征）：

```bash
python scripts/alpha158_lgb_train_v3.py
```

2) 短窗回测（已输出按状态分组统计）：

```bash
python scripts/run_alpha158_short_backtest.py --signal-days 60 --horizons 3 5
```

3) 对比重点（重构前 vs 重构后）：
- `max_drawdown`
- `median_return`
- `regime_stats` 中 `weak / sideways` 的 `mean_return` 与 `profit_factor`

