# Alpha158 IC 加权策略：因子与配置说明

本文描述 `stock_selection.strategy_profile: alpha158` 时的选股逻辑：因子定义、IC 权重、硬过滤、`config.yaml` 配置项及与 Qlib 的关系。

**说明**：权重来自研究阶段的 IC 归一化思路；实现上使用本地 `stock_daily` 手算因子，**运行时未调用** Microsoft Qlib 的 `Alpha158` handler。

---

## 一、参与打分的 15 个因子

对信号日截面上，每个因子先做 **Z-score**，再按 `ALPHA158_WEIGHTS` **加权求和**得到 `alpha158_score`（代码：`src/modules/stock_selector.py` 中 `ALPHA158_WEIGHTS`、`_compute_alpha158_factors`）。

| 因子名 | 权重 | 含义（实现要点） |
|--------|------|------------------|
| MA30 | +0.2335 | 收盘价相对 30 日均价的偏离度 |
| MA60 | +0.2452 | 相对 60 日均线偏离度 |
| ROC30 | +0.2331 | 约 30 日收益率 |
| ROC60 | +0.1983 | 约 60 日收益率 |
| QTLU60 | +0.2318 | 当日收盘在过去 60 日价格序列中的高位分位统计 |
| QTLD60 | +0.2178 | 低位分位相关统计 |
| SUMN30 | +0.1762 | 30 日内负的日收益之和 |
| SUMN60 | +0.1732 | 60 日内负收益之和 |
| CNTN30 | +0.1042 | 30 日内下跌日占比 |
| VSTD30 | +0.0395 | 30 日成交量相对均值的波动 |
| RSV60 | **-0.1723** | 60 日类似随机指标（**反向**，权重为负） |
| RANK60 | **-0.2007** | 60 日收盘价排名（**反向**） |
| MA5 | +0.15 | 短期均线偏离 |
| ROC5 | +0.12 | 约 5 日收益率 |
| QTLU20 | +0.10 | 20 日分位类 |

---

## 二、硬过滤（先于打分）

股票池：`get_stock_list` 后保留 **沪深主板**（60/00/001 等规则，见代码中 `main_board_mask`）。

当 `exclude_st: true` 时，剔除名称含 **ST / st / 退** 的标的（与 `filter_basic` 一致）。

对每只股票，在 `end_date` 截止取 **至少 61 根**日线，并满足：

1. **流动性**：`amount ≥ alpha158_min_amount`（TuShare `amount` 为**千元**，默认 `100000` ≈ 1 亿元日成交额）。
2. **波动**：30 日年化波动 `_vol30 ≤ alpha158_vol_max`（默认 `0.6`）。
3. **趋势**：`MA5 > MA20`（用 `_MA5`、`_MA20` 辅助字段）。
4. **短期动量**：`_ROC5 ≥ alpha158_roc5_min`（默认 `-0.02`）。

---

## 三、打分与输出流程

1. 对 `ALPHA158_WEIGHTS` 中出现的列做截面 **Z-score**。
2. 加权求和 → `alpha158_score`。
3. 保留 `alpha158_score > alpha158_score_threshold`（默认 `0.5`），按分数降序。
4. `total_score`：将复合 z 分映射为 `50 + raw×10` 并截断到 [0,100]；`alpha158_raw` 为加权后的复合分。
5. `run_selection` 中：`FeedbackGuard` 可能调整 `effective_top_n` → `_zscore_normalize_scores`（`score_normalized`）→ `diversify_by_industry`（`max_per_industry`）→ 取前 `top_n` 只。

---

## 四、`config.yaml` 中与 Alpha158 强相关项

在 `stock_selection` 下（示例值以仓库当前配置为准）：

| 键 | 典型值 | 含义 |
|----|--------|------|
| `strategy_profile` | `alpha158` | 启用本策略 |
| `alpha158_min_amount` | `100000` | 最低日成交额（**千元**） |
| `alpha158_vol_max` | `0.6` | 30 日年化波动上限 |
| `alpha158_roc5_min` | `-0.02` | 近 5 日收益下限 |
| `alpha158_score_threshold` | `0.5` | 复合 z 分阈值 |
| `exclude_st` | `true` | 是否排除 ST/*ST/退市 |
| `top_n` | `5` | 最终输出最多 N 只 |
| `max_per_industry` | `3` | 行业分散：每行业最多只数 |

`feedback_guard_*`、`min_score` 等会影响 **有效 top_n / 最低分**，与 Alpha158 并行生效，详见 `StockSelector._get_feedback_guard_profile`。

---

## 五、与 Qlib 官方 Alpha158 的差异

- **一致点**：因子命名与 IC 加权思路对齐研究用的高 IC 子集。
- **差异点**：本仓库为 **SQLite 日线 + 自写公式**；若需与 Qlib 表达式逐列一致，需接入 Qlib 数据与表达式引擎。

---

## 六、相关文件

- 核心实现：`src/modules/stock_selector.py`（`ALPHA158_WEIGHTS`、`_compute_alpha158_factors`、`_run_alpha158_selection`、`run_selection`）
- 配置：`src/config/config.yaml` → `stock_selection`
- 本地回测参考：`output/local_alpha158_backtest_v2.py`（参数口径可对照）
