# 二次启动策略：逻辑、评分与配置说明

本文描述菜单中的 **强势回调缩量二次启动**（`SecondaryLaunchMenu` + `MainboardSecondaryLaunchStrategy`）：数据口径、底线过滤、综合分 `signal_score` 构成、`stock_selection.secondary_launch` 配置项，以及 **V3 最终版** 标签含义。

**核心思想**：在沪深主板中，寻找 **前期有涨停强势、随后缩量回调、仍站回均线之上** 的标的，用日线特征做盘前候选；**仅用截至 signal 日前一交易日（t-1）的日线**，避免未来函数。

---

## 一、策略入口与版本标签

| 项目 | 说明 |
|------|------|
| 代码入口 | `src/modules/secondary_launch_menu.py`（`get_daily_selection`） |
| 日线核心 | `src/modules/mainboard_secondary_launch_strategy.py`（`MainboardSecondaryLaunchStrategy`、`StrategyParams`） |
| 配置节 | `src/config/config.yaml` → `stock_selection.secondary_launch` |
| `strategy_version: v3_final` | 展示标签为「V3 最终版：日线闸门+分时渐进回踩」；日线闸门相关字段由 `_compute_v3_daily_gate_fields` 写入（涨跌幅、量比、上影线比例等），**盘中**逻辑见 `secondary_launch_intraday.py` |

---

## 二、股票池与特征工程（概要）

- **板块**：代码前缀属于主板 `600/601/603/605/000/001/002`（见 `MAINBOARD_PREFIX`）。  
- **风险名称**：名称含 ST、*ST、退 等剔除（`_is_risk_name`）。  
- **特征**（`prepare_features`）：含 `ma5/ma10`、`vol_ma5/vol_ma20`、`amt_ma20`、**相对强弱 `rs20`**（`rs_lookback` 默认 20 日）、涨停识别、**近 10 日涨停次数**、**距最近涨停交易日天数**、**自涨停后峰值回撤 `drawdown_from_peak`**、涨停日量能比等。

信号日映射：`build_signal_frame` 将每个交易日的特征映射到 **下一交易日** 作为 `signal_date`（盘前选股用 t-1 特征决策当日信号）。

---

## 三、底线过滤（`_base_filter`）

在评分前必须同时满足（具体阈值见第四节配置）：

| 条件类型 | 含义 |
|----------|------|
| 主板 + 非风险简称 | 见上 |
| 上市天数 | `list_days >= min_list_days` |
| 价格与量能 | `close >= min_price`，`vol>0`，`min_amt_ma20 <= amt_ma20 <= max_amt_ma20` |
| 跌停记录 | 近 20 日跌停次数不过多（`limit_down_count_20 <= 1`） |
| 涨停形态 | 近 10 日至少有涨停（`limit_up_count_10` 在 `[min,max]` 内由评分细化，底线为 `>=1`） |
| 时间距离 | 距最近涨停天数在 `[last_limit_up_days_min, last_limit_up_days_max]` |
| 回撤区间 | `drawdown_from_peak` 在 `[drawdown_min, drawdown_max]`（涨停后峰值回撤比例） |
| 均线位置 | `close >= ma10 * close_ma10_min_ratio`，且 `ma5 >= ma10 * 0.998` |
| 当日非涨停 | `~is_limit_up`（避免已涨停再追） |

---

## 四、综合分 `signal_score`（满分约 100 分档）

在通过底线过滤的样本上计算（`_score_candidates`），主要项为：

| 组成部分 | 权重系数 | 含义 |
|----------|----------|------|
| RS 排名 | **×24** | `rs20` 在全体现货中的分位 `rs_rank`（0~1），强势股相对排名 |
| 涨停次数得分 | **×10** | `limit_up_count_10` 在 `[limit_up_count_10_min, max]` 内越理想分越高 |
| 涨停间隔得分 | **×16** | `days_since_last_limit_up` 在允许区间内越理想分越高 |
| 回撤得分 | **×18** | `drawdown_from_peak` 在 `[drawdown_min, drawdown_max]` 内越理想分越高 |
| 缩量得分 | **×8** | 当日量相对 5 日均量，贴近 `vol_shrink_ratio` 越好 |
| MA5 偏离得分 | **×12** | 收盘价与 MA5 偏离不超过 `close_ma5_dev_max` |
| 趋势得分 | **×6** | MA5>MA10、收盘在 MA10 之上等 |
| 量能趋势得分 | **×3** | 短期均量相对中期均量 |
| 涨停日量能比得分 | **×2** | `limit_up_amt_ratio` 在配置区间内 |
| 涨停次日收益得分 | **×5** | 最近涨停次日涨跌在合理区间 |

字符串 `score_breakdown` 中会拼接 RS、涨停次数、间隔、回撤、缩量等分项，便于排查。

---

## 五、市场闸门与输出控制

- **`_get_market_gate`**：用 **上证指数 `000001.SH` 的 `ret5`**；若 `ret5 <= weak_market_ret5_threshold`，则 **最低分提高** `weak_market_min_score_boost`，且每日最多 **`weak_market_max_picks`** 只。  
- **最低分**：`signal_score >= effective_min_score`（默认来自 `min_score`，弱市时抬高）。  
- **排序**：先按 `signal_score`，再按 `rs20` 降序。  
- **冷却**：`_apply_cooldown` — 同一标的在 `cooldown_days` 个交易日内不重复入选（与历史落库结合时见 `_filter_recent_duplicates`）。  
- **第二名精筛**：`_refine_daily_picks` — 第二名需 `>= second_pick_min_score`，且与第一名的分差不超过 `second_pick_score_gap`，否则只保留第一名。

每日最多 **`picks_per_day`** 只，且经过 `max_candidates` 上限截断。

---

## 六、`config.yaml` 中 `stock_selection.secondary_launch` 项说明

以下为 **策略与文档对齐的主要键**（以仓库当前 `config.yaml` 为准；若与代码内 `StrategyParams` 默认值不一致，**以 YAML 为准**，因 `_build_strategy` 从配置读取）。

| 键 | 含义 |
|----|------|
| `strategy_version` | 如 `v3_final`，影响展示标签与元数据 |
| `enabled` | 是否启用（供其他模块判断） |
| `min_list_days` | 最少上市天数 |
| `limit_up_threshold` / `limit_down_threshold` | 涨跌停识别阈值（%） |
| `limit_up_count_10_min` / `limit_up_count_10_max` | 近 10 日涨停次数理想区间 |
| `last_limit_up_days_min` / `last_limit_up_days_max` | 距最近涨停天数允许区间 |
| `drawdown_min` / `drawdown_max` | 峰值回撤比例允许区间 |
| `vol_shrink_ratio` | 缩量目标（与量比分结合） |
| `close_ma5_dev_max` | 收盘相对 MA5 最大偏离 |
| `close_ma10_min_ratio` | 收盘相对 MA10 最低比例 |
| `min_amt_ma20` / `max_amt_ma20` | 20 日成交额均值上下限（与数据源单位一致，通常为千元） |
| `min_price` | 最低股价过滤 |
| `limit_up_amt_ratio_min` / `max` | 涨停日成交额相对 20 日均额比例区间 |
| `rs_lookback` | RS 计算回望天数（如 20 → `rs20`） |
| `max_candidates` | 每日进入候选池上限 |
| `picks_per_day` | 每日最多输出只数 |
| `min_score` | 综合分及格线（弱市会再加） |
| `cooldown_days` | 同股冷却天数 |
| `weak_market_ret5_threshold` | 弱市判定：指数 5 日收益阈值 |
| `weak_market_min_score_boost` | 弱市下最低分加成 |
| `weak_market_max_picks` | 弱市下每日最多只数 |
| `second_pick_min_score` / `second_pick_score_gap` | 第二名质量门槛及与头名分差 |
| `hold_days` | 回测/持仓参考（菜单元数据） |
| `transfer_fee_rate` | 过户费等（回测成本） |
| `daily_profile_gate_enabled` / `intraday_pullback_version` | V3 日线闸门与分时回踩版本（与盘中模块协同） |

回测窗口、优化冻结日期等键（如 `backtest_*`、`last_optimized_*`）用于 **报告与流水线**，不改变当日 `get_daily_selection` 核心公式，除非另行读取。

---

## 七、输出字段（菜单选股结果）

典型字段包括：`ts_code`、`name`、`industry`、`signal_score`、`rank`、`rs20`、`drawdown_from_peak`、`days_since_last_limit_up`；V3 下还有 `pct_chg`、`vol_ratio_5`、`upper_shadow_pct` 等供盘中闸门使用。

---

## 八、相关文件

| 文件 | 作用 |
|------|------|
| `src/modules/mainboard_secondary_launch_strategy.py` | 特征、过滤、评分、信号生成 |
| `src/modules/secondary_launch_menu.py` | 菜单、盘前选股、落库、推送 |
| `src/modules/secondary_launch_intraday.py` | 盘中买点与阻断说明 |
| `src/modules/mainboard_secondary_launch_backtester.py` | 回测与数据加载 |
| `src/config/config.yaml` | `stock_selection.secondary_launch` |
