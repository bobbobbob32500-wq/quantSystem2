# Strong Start 样本挖掘开发任务清单

目标：先完成事件级样本研究，再反推交易参数，最后重构交易版策略。

---

## 模块 1：研究框架治理

### 子任务 1.1：拆分研究系统与交易系统
- 输入
  - 现有 `strong_start` 交易代码
  - 研究目标（样本挖掘优先）
- 输出
  - 研究系统脚本链路（候选、标签、特征、分析）
  - 交易系统保持独立，不与研究流程耦合
- 验收标准
  - 研究流程可单独运行，不依赖交易回测脚本
  - 交易脚本不直接参与样本标签生成

### 子任务 1.2：锁定研究范围与口径
- 输入
  - 交易市场范围（沪深主板）
  - 时间区间（建议 2-3 年）
  - 数据频率（日线）
- 输出
  - 固定口径的研究配置（主板、窗口、频率）
- 验收标准
  - 所有研究脚本统一使用同一口径
  - 报告中明确写出口径信息

---

## 模块 2：事件样本构建

### 子任务 2.1：宽松候选事件扫描
- 输入
  - `stock_daily`、`stock_basic`
  - 宽松触发条件（价格、量能、趋势）
- 输出
  - `candidate_events.parquet`
- 验收标准
  - 候选数量充足（非个位数/极小样本）
  - 每条样本是 `ts_code + trade_date` 事件

对应脚本：
- [build_start_event_candidates.py](D:/HuaweiAI/quantSystem2/scripts/build_start_event_candidates.py)

### 子任务 2.2：事件去重（波段冷却）
- 输入
  - 候选事件
  - `event_cooldown_days`
- 输出
  - 去重后的独立事件池
- 验收标准
  - 同一股票在冷却窗口内只保留第一个事件
  - 不出现连续多天重复事件污染

对应实现：
- [strong_start_sample_mining.py](D:/HuaweiAI/quantSystem2/src/modules/strong_start_sample_mining.py) `build_candidates`

### 子任务 2.3：可交易性与结果标签
- 输入
  - 候选事件
  - 前瞻窗口（3-5 天）
  - 可交易规则（次日可成交、一字板过滤、开盘跳空约束）
- 输出
  - `labeled_events.parquet`（A/B/C/N）
- 验收标准
  - 标签字段齐全：`entry_possible`、`entry_block_reason`、`label_abc`
  - `A/B/C/N` 分布合理，非单一标签

对应脚本：
- [label_start_events.py](D:/HuaweiAI/quantSystem2/scripts/label_start_events.py)

---

## 模块 3：特征快照工程（T 日锁定）

### 子任务 3.1：特征快照规则约束
- 输入
  - 已标注事件样本
  - T 日及以前行情数据
- 输出
  - 明确的“仅 T 日可见信息”特征集
- 验收标准
  - 特征不含 `T+1` 及以后信息
  - 无前视字段泄漏到分析表

### 子任务 3.2：六大特征组提取
- 输入
  - 行情、行业、筹码数据
- 输出
  - `event_features.parquet`
- 验收标准
  - 特征覆盖 6 组：强势、平台、量能、筹码、K 线质量、板块/龙头代理
  - 空值比例可控，并在报告中可解释

对应脚本：
- [extract_start_event_features.py](D:/HuaweiAI/quantSystem2/scripts/extract_start_event_features.py)
- [strong_start_sample_mining.py](D:/HuaweiAI/quantSystem2/src/modules/strong_start_sample_mining.py) `extract_features`

---

## 模块 4：样本差异分析与参数反推

### 子任务 4.1：A/B/C 分布差异分析
- 输入
  - `event_features.parquet`
- 输出
  - `sample_analysis_report.md`
  - `feature_summary.csv`
- 验收标准
  - 每个特征给出 A/C 差异与方向
  - 能识别强区分、中区分、弱区分特征

### 子任务 4.2：参数候选反推
- 输入
  - `feature_summary.csv`
- 输出
  - `candidate_thresholds.yaml`
- 验收标准
  - 输出是“区间/方向/角色”，而不是拍脑袋定点值
  - 特征分层：`hard_filter` / `score` / `weak`

对应脚本：
- [analyze_start_samples.py](D:/HuaweiAI/quantSystem2/scripts/analyze_start_samples.py)

---

## 模块 5：板块强弱数据层

### 子任务 5.1：Tushare 板块历史拉取（优先）
- 输入
  - Tushare token
  - 时间窗口
- 输出
  - `block_data` 中板块历史涨跌幅记录
- 验收标准
  - 有权限时可写入 `block_type=ths_index_daily`
  - 日志输出成功写入行数

### 子任务 5.2：权限/网络失败自动回退
- 输入
  - Tushare 权限不足或接口失败
- 输出
  - 本地行业聚合写入 `block_data`
- 验收标准
  - 脚本不中断
  - 自动回退到 `block_type=industry_agg_daily`

对应脚本：
- [download_industry_history_tushare.py](D:/HuaweiAI/quantSystem2/scripts/download_industry_history_tushare.py)

---

## 模块 6：研究结论落地到交易版

### 子任务 6.1：结论文档化
- 输入
  - 样本分析结果
- 输出
  - 研究结论：有效因子、无效因子、触发类型占比、候选参数区间
- 验收标准
  - 明确回答：
    - breakout 与 pullback 占比
    - 板块/龙头与筹码的相对价值
    - 当前过严阈值清单

### 子任务 6.2：交易版策略重构（后置）
- 输入
  - 研究结论
- 输出
  - 新版 `strong_start` 交易参数与规则
- 验收标准
  - 先通过“样本排序能力”验证，再做收益验证
  - 不再出现“过严串联导致几乎无交易”的结构性问题

---

## 运行清单（执行顺序）

```powershell
python scripts/build_start_event_candidates.py --start-date 20250403 --end-date 20260403
python scripts/label_start_events.py
python scripts/extract_start_event_features.py
python scripts/analyze_start_samples.py
```

板块数据（Tushare 优先 + 自动回退）：

```powershell
python scripts/download_industry_history_tushare.py --start-date 20250403 --end-date 20260403 --mode auto --mainboard-only
```

---

## 当前状态标记

- 已完成
  - 研究脚本链路与小窗口烟测跑通
  - Tushare 板块历史脚本（含自动回退）已落地
- 待执行
  - 全年窗口正式跑数
  - 训练/验证/留出切分
  - 基于研究结论重构交易版

