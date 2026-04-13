# Phase 1 结构重构计划（只读审查结论）

> **审查范围**：`main.py`、`src/modules/stock_selector.py`、`src/modules/enhanced_hybrid_system.py`、`src/modules/optimized_buy_signals.py`、`src/modules/risk_controller.py`、`src/modules/realtime_minute_fetcher.py`  
> **审查日期**：2026-04-12  
> **分支**：`refactor/phase1-structure`  
> **说明**：本文为**只读审查**产物，**不含代码改动**；待你确认后再进入步骤 2。

---

## 1. 当前职责耦合点

### 1.1 `main.py`

| 耦合类型 | 说明 |
|---------|------|
| **启动与路径** | `_strip_windows_long_path_prefix`、`sys.path` 注入、`cwd` 修正与 `main()` 入口混在同一文件顶部。 |
| **依赖装配** | `QuantSystem.__init__` / `_init_modules` 集中创建 `ConfigManager`、`DatabaseManager` 及十余个业务模块（数据、选股、风控、推送、日报、计划、评测、二次启动、终端看板等）。 |
| **交互与业务** | 大量 `*_menu` 方法内联 `print` + `input` + 直接调用模块 API；部分子流程还包含推送载荷组装、候选池 JSON 读写、子进程调用自检脚本等。 |
| **可选能力** | P0 因子、回测菜单、突破选股等以 `try/import` 旗标控制，与主类生命周期交织。 |

**结论**：单文件同时承担 **entry/bootstrap**、**DI/装配**、**CLI 菜单路由**、**部分用例编排**，导致 `main.py` 体量过大且难以单测。

### 1.2 `stock_selector.py`

| 耦合类型 | 说明 |
|---------|------|
| **配置与状态** | `__init__` 读取大量 `stock_selection.*` 键，并维护策略档位、增强权重档位、行业/可交易性缓存等多类状态。 |
| **Universe** | `get_stock_list`、`_build_point_in_time_stock_list`、日期解析等与股票池构建紧绑在同一类中。 |
| **过滤与阈值** | `filter_basic` / `_filter_basic_legacy`、`assess_tradeability`、动态/静态阈值、`FeedbackPerformanceGuard` 与选股主循环交织。 |
| **因子与打分** | `calculate_*_factor`、legacy 变体、`_calculate_stock_score_legacy_exact`、`diversify_by_industry`、`_zscore_normalize_scores` 同处一类，行数极多。 |
| **报告与优化** | `generate_report`、`optimize_factor_weights` 与核心选股路径共用同一对象。 |

**结论**：`StockSelector` 是典型 **God Object**：universe、filters、factors、ranking、reporting、guard 逻辑高度内聚在一个类中，阅读与回归成本集中。

### 1.3 `enhanced_hybrid_system.py`

| 耦合类型 | 说明 |
|---------|------|
| **已部分外移** | 大量行为已通过 `enhanced_monitor_*`、`enhanced_trade_control`、`enhanced_signal_*` 等模块以 **函数** 形式委托（`runtime_*` 别名调用）。 |
| **仍集中之处** | `EnhancedHybridSystem` 的 `__init__` 仍组装 `StockSelector`、`RealtimeQuoteFetcher`、`OptimizedBuySignals`、`RealtimeMinuteFetcher`、`PositionController` 等；配置项极多。 |
| **编排与领域** | `run_overnight_selection`、`load_candidate_pool` / `_save_candidate_pool`、`_build_intraday_data`（含模拟序列）、`print_buy_signals` 等与类实例强绑定。 |
| **薄封装层** | `start_realtime_monitor`、`stop_realtime_monitor`、`_fetch_realtime_context` 等多为对 `runtime_*` 的一行转发，**类本身仍作为唯一聚合入口**。 |

**结论**：文件已从「巨石」拆出多个子模块，但 **聚合根 + 初始化 + 部分业务** 仍挤在 `EnhancedHybridSystem`；与 `main.py` 类似，适合再拆 **runtime 分层** 与 **显式接口**，而非继续堆方法。

### 1.4 `optimized_buy_signals.py`

| 耦合类型 | 说明 |
|---------|------|
| **相对独立** | `IntradayData` / `SignalOutput` 与 `signal_pullback` / `breakout` / `consolidation`、`evaluate_time_filter` 等逻辑封装在单类内，依赖少。 |
| **与配置关系** | 当前参数以类内 `self.params` **硬编码**为主，与全局 `ConfigManager` 未在本文件内强耦合。 |

**结论**：结构清晰，适合作为 **SignalDetector 实现** 或委托目标；Phase 1 以 **抽接口 + 保持类行为不变** 为主即可。

### 1.5 `risk_controller.py`

| 耦合类型 | 说明 |
|---------|------|
| **规则与数据** | `check_*` 系列方法内嵌阈值比较、中文文案与业务语义；`get_stock_daily_data` 直接访问 DB。 |
| **可选自动优化** | `FullyAutomaticOptimizationSystem` 与紧急重优化入口与核心检测逻辑同文件。 |

**结论**：风控 **规则表达式** 与 **数据访问**、**可选优化** 混在一起；结构重构时应 **只搬家不改正阈值**，规则块需整段迁移或原样委托。

### 1.6 `realtime_minute_fetcher.py`

| 耦合类型 | 说明 |
|---------|------|
| **I/O 与策略** | 分钟拉取、缓存、线程池、熔断、`akshare` 可用性、Python 3.14 守护等均为基础设施关注点。 |
| **下游契约** | `build_quote_from_minute` / `build_quote_frame` 为行情快照兼容层，与业务策略无直接耦合。 |

**结论**：非常适合作为 **MarketDataProvider** 的具体实现；拆分时不应改动对外返回的 DataFrame/字段语义。

---

## 2. 建议拆出的模块（与目标目录对齐）

以下与你在步骤 2 中的 **A～D** 建议一致，并补充**职责边界**说明。

### 2.1 App / Entry（`src/app/`）

| 文件 | 建议职责 |
|------|----------|
| `bootstrap.py` | 路径修正、`sys.path`、日志初始化入口（从 `main` 顶部迁入）。 |
| `cli.py` | `QuantSystem` 的菜单循环与各 `*_menu` 的 CLI 呈现（或再分子模块按域拆分）。 |
| `service_container.py` | 集中构造 `ConfigManager`、`DatabaseManager`、各业务模块单例/工厂，供 CLI 注入。 |

### 2.2 Selection（`src/selection/`）

| 文件 | 建议从 `stock_selector.py` 迁出的内容（先复制再委托，勿删旧类） |
|------|------|
| `universe.py` | `get_stock_list`、点-in-time 列表、日期解析、与 `stock_basic` 相关的列表构建。 |
| `filters.py` | `filter_basic` / `_filter_basic_legacy`、ST/新股等硬过滤、与可交易性相关的**过滤阶段**（调用 `assess_tradeability` 的编排可放 ranking 或单独 orchestrator）。 |
| `factors.py` | 各 `calculate_*_factor` 及 legacy 变体（保持函数/类签名便于测试）。 |
| `ranking.py` | `_calculate_stock_score_legacy_exact`、`calculate_stock_score`（若仍使用）、`diversify_by_industry`、`_zscore_normalize_scores`、排序与 TOP N。 |
| `reporting.py` | `generate_report` 及纯展示字符串生成。 |

`StockSelector` 保留为 **facade**：对外仍暴露 `run_selection`、`get_tradeability_thresholds` 等现有 public 方法，内部转调新模块。

### 2.3 Runtime（`src/runtime/`）

| 文件 | 建议从 `enhanced_hybrid_system.py` 及周边迁出的内容 |
|------|------|
| `market_runtime.py` | 行情/分钟批量拉取编排、`_fetch_realtime_context`、与 `RealtimeMinuteFetcher` 协同的时序与超时（可与现有 `enhanced_realtime_context` 协同，避免重复造轮子）。 |
| `candidate_monitor.py` | 候选池加载/保存、盘后选股结果分层、与 `candidate_pool.json` 交互。 |
| `signal_router.py` | 策略路由、legacy gap、确认信号、防抖窗口等与「信号合并/优先级」相关的编排（大量逻辑已在 `enhanced_monitor_runtime` 等文件中，此处侧重 **显式类/命名空间**）。 |
| `runtime_guards.py` | 市场门控、`FeedbackGuard` 上下文、交易控制熔断与告警等「运行时护栏」聚合调用。 |

`EnhancedHybridSystem` 保留为 **facade**：`start_realtime_monitor` 等仍对外可用，内部委托新 runtime 模块或现有 `runtime_*` 函数。

### 2.4 Interfaces（`src/interfaces/`）

| 文件 | 契约（Protocol/ABC）建议 |
|------|------|
| `market_data_provider.py` | `get_minute_bars` / `get_batch_minute_bars` 或统一 `fetch_quotes`；返回类型与现有 `pd.DataFrame` 约定一致。 |
| `signal_detector.py` | 输入 `IntradayData`，输出 `SignalOutput`（与 `OptimizedBuySignals` 对齐）。 |
| `strategy_selector.py` | 与盘前选股抽象对应：`run_selection` 类方法，返回 `List[Dict]`（与当前 `StockSelector.run_selection` 一致）。 |
| `notifier.py` | 抽象推送/告警（与 `MessagePusher`、交易控制告警等对齐，先薄封装即可）。 |

**注意**：接口层 **不包含** vnpy/qlib/backtrader/rqalpha；仅为后续替换预留类型与调用点。

---

## 3. 各模块输入输出（摘要）

| 模块 | 主要输入 | 主要输出 |
|------|----------|----------|
| **bootstrap** | 进程环境、`__file__` | 就绪的 `sys.path`、工作目录副作用（与现行为一致） |
| **service_container** | 配置文件路径（可选） | `config`、`db`、各业务模块引用 |
| **cli** | 用户 stdin | 调用各业务 API 的副作用（打印、写缓存、推送） |
| **universe** | `end_date`、配置、`DatabaseManager` | `DataFrame`（股票列表及元数据） |
| **filters** | 股票列表 `DataFrame`、`end_date` | 过滤后 `DataFrame` |
| **factors** | 单票日线/序列数据 | 因子分项得分与 detail 字典 |
| **ranking** | 多票得分列表、配置（top_n、行业上限等） | 排序与截断后的候选列表 |
| **reporting** | 候选列表、权重快照 | 字符串报告 |
| **market_runtime** | 标的列表、配置 | 行情/分钟 `DataFrame` 或映射 |
| **candidate_monitor** | 选股结果、路径配置 | 读写 `candidate_pool.json` |
| **signal_router** | 候选、分钟数据、信号检测器输出 | 统一信号结构供推送/展示 |
| **runtime_guards** | 市场快照、配置 | 是否允许交易、告警上下文 |
| **MarketDataProvider** | symbols、日期 | 标准化行情/分钟数据 |
| **SignalDetector** | `IntradayData` | `SignalOutput` |
| **StrategySelector** | `market_score`、`end_date` | `List[Dict]` 选股结果 |
| **Notifier** | 结构化 payload | 发送结果 bool 或状态码 |

---

## 4. 不可改动的策略逻辑列表（Phase 1 约束）

以下项在 **仅做结构重构** 的前提下，应视为 **行为冻结**（数值、分支条件、返回字段语义均不应因「拆分」而改变）：

### 4.1 选股（`stock_selector.py` 及其迁出函数）

- **Legacy 5 因子合成路径**：`_calculate_stock_score_legacy_exact`、`run_selection` 中循环、**`effective_min_score` / `effective_top_n`（FeedbackGuard）**、`_zscore_normalize_scores`、`diversify_by_industry`、TOP N 截断的相对顺序与字段含义。
- **静态/动态可交易性阈值**：`_resolve_tradeability_thresholds`、`_compute_dynamic_tradeability_thresholds`、`get_tradeability_thresholds` 中使用的分位数、上下限比例等（与配置键绑定）。
- **动态行业热度**：`get_dynamic_industry_strength`、`_prepare_dynamic_industry_strength` 相关缓存与行业惩罚/加成逻辑。
- **增强档位与市场防护**（若代码路径仍可达）：`_evaluate_enhanced_market_guard`、`strategy_profile` / `enhanced_weight_profiles` 解析逻辑。

### 4.2 盘中买点（`optimized_buy_signals.py`）

- `signal_pullback` / `signal_breakout` / `signal_consolidation` 内的 **条件组合、阈值比较、confidence 加权方式**。
- `evaluate_time_filter` / `time_filter` 中 **开盘涨幅、avoid_times、market_score 连续仓位模型**。

### 4.3 风控（`risk_controller.py`）

- `check_volume_sell_signal`、`check_market_bad_clear_signal`、`check_price_profit_signal`、`check_trend_profit_signal`、`check_price_stop_signal`、`check_all_signals` 中的 **数值阈值与触发文案结构**（配置项默认值不变）。

### 4.4 分钟数据（`realtime_minute_fetcher.py`）

- 熔断连续失败次数、恢复秒数、批量超时、`min_valid_rows`、Python 3.14 并发降为 1、`QSYS_FORCE_AKSHARE_MINUTE` 等行为。
- `build_quote_from_minute` 中 **pre_close 近似逻辑** 及 `pre_close_source` 标记语义。

### 4.5 运行时聚合（`enhanced_hybrid_system.py` 及已委托的 `enhanced_*`）

- **不改变** 现有 `runtime_*` 函数默认行为；facade 仅搬迁调用关系时，须保证 **调用顺序与传参** 与当前一致。
- `run_overnight_selection` 中核心池/备选池划分规则、`candidate_pool` 序列化格式（若仍被监控读取）。

> **说明**：若审查中发现某段逻辑存在「模拟数据/随机波动」等非确定性行为（如 `_build_intraday_data` 使用 `np.random`），结构重构阶段 **不改正该问题**，仅可标注 TODO 供后续治理。

---

## 5. 建议迁移顺序（降低风险）

1. **接口桩与类型**：新增 `src/interfaces/*.py`（Protocol/ABC），由现有类 **implements 或适配器包装**，无行为变更。补最小测试：导入与 `isinstance`/`runtime_checkable` 可选。
2. **realtime_minute_fetcher → MarketDataProvider**：让 `RealtimeMinuteFetcher` 显式实现接口（或注册适配器）；行为不变。
3. **optimized_buy_signals → SignalDetector**：接口方法默认委托现有 `OptimizedBuySignals`。
4. **stock_selector 分层**：按 universe → filters → factors → ranking → reporting 顺序，**每步一次提交**；每步 `StockSelector` 仍保留原方法名并转调。
5. **enhanced_hybrid_system runtime 分层**：在已有 `enhanced_*` 函数基础上，将 `EnhancedHybridSystem` 内仍存在的编排迁入 `src/runtime/*`，类作 facade。
6. **main.py 瘦身**：`bootstrap` + `service_container` + `cli`；`main.py` 保留极薄入口 `main()` 调用 `cli.run()` 或等价物。

---

## 6. 风险点

| 风险 | 说明 | 缓解 |
|------|------|------|
| **隐性契约** | `List[Dict]` 选股结果、信号 `dict` 字段名被推送/看板/测试依赖，拆分易漏字段。 | 迁移前后跑全量 `pytest`；对关键 dict 键做 **快照或冻结辅助函数**（仅测试层）。 |
| **配置键分散** | `stock_selection.*`、`monitor.*`、`risk_control.*` 等键名遍布多处。 | 重构不改名；必要时增加 **只读常量模块** 集中字符串（不改变取值）。 |
| **循环导入** | `selection` ↔ `core` ↔ `modules` 易出现环。 | 接口放 `src/interfaces`，实现延迟导入或 dependency-injection。 |
| **Enhanced 已拆分** | 多个 `enhanced_*.py` 已存在，再建 `runtime/` 可能命名重叠。 | 新代码优先 **组合调用** 现有函数，避免复制逻辑；文档中注明「编排层」与「算法层」边界。 |
| **非确定性代码** | `_build_intraday_data` 等含随机性，回归测试可能不稳定。 | Phase 1 不改为确定性；TODO 标记，后续单独 issue。 |

---

## 7. 审查中的待确认项（需你确认或后续标 TODO）

1. **`EnhancedHybridSystem` 中 `self.config` 的类型**：部分代码使用 `self.config['core_pool_size']` 下标访问，需与 `ConfigManager` API 核对，避免重构时误混 `dict` 与包装对象（**不猜测**，实现时对照现有运行路径）。
2. **`main.py` 中 P0 回测对比等方法** 是否仍引用 `self.backtester` / `self.realistic_backtester`：当前片段显示可能依赖未在审查片段中完整展示的初始化逻辑，迁移 CLI 时需 **整段复制** 依赖关系。
3. **候选池 JSON 与 `main.py` 内 `_sync_primary_selection_to_candidate_pool` 的合并策略**：与 `enhanced_hybrid_system` 的候选池是否共享同一文件；拆分后需统一 **单一写入入口**（可在 Phase 1 仅文档化，不动语义）。

---

## 8. 下一步（待你确认后执行）

- 按第 5 节顺序进入 **步骤 2：结构拆分**。  
- 每步配套：**小步提交**、**最小测试**、**迁移说明**（可落在 `docs/` 或 commit message）。  
- **不修改** `master`；当前工作分支继续为 `refactor/phase1-structure`。

---

**文档结束。请确认本计划后，再指令开始步骤 2。**
