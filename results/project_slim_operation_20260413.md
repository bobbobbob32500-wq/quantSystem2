# 项目瘦身操作报告（2026-04-13）

## 一、备份说明

| 项目 | 说明 |
|------|------|
| 备份文件 | `d:\HuaweiAI\backups\quantSystem2_full_20260413.bundle` |
| 备份方式 | `git bundle create ... --all`（包含全部分支与提交历史） |
| 恢复示例 | `git clone quantSystem2_full_20260413.bundle quantSystem2_restored` |

**说明**：在删除任何文件前已生成上述 bundle。若需工作区快照级备份，可再对仓库根目录做压缩归档（体积较大）。

---

## 二、本次删除清单（已执行）

### 1. `src/modules/` 下零引用或已废弃的孤立模块（8 个）

| 文件 | 删除依据 |
|------|----------|
| `unified_validation_system.py` | 全仓库无 `import`；仅自包含 `UnifiedValidationSystem` |
| `unified_pattern_mining.py` | 仅被已删除的 `pattern_mining_integration` 引用 |
| `pattern_mining_integration.py` | 全仓库无外部引用 |
| `wide_entry_strict_selection.py` | 「宽进严选」实验框架，无任何模块引用 |
| `intraday_monitor.py` | 无外部引用；且依赖 `src.modules.intraday_monitor.monitor_engine`（子包不存在），属无法运行的死代码 |
| `selection_cache.py` | 无外部引用 |
| `signal_statistics.py` | 无外部引用（与 DAO 中 `get_signal_statistics` 方法名相近但非同一模块） |
| `strategy_report_generator.py` | 无外部引用 |

**保留说明**：`pattern_mining.py`、`ml_pattern_mining.py`、`validation_engine.py`、`complete_strategy_system.py` 仍被 `scheduled_reoptimizer` 与测试引用，**未删除**。

### 2. 临时输出与一次性结果（4 个）

| 文件 | 说明 |
|------|------|
| `output/qq.txt` | 临时文本，约 69KB |
| `output/alpha158_short_backtest.json` | 实验回测输出，可重跑生成 |
| `results/secondary_launch_persistence_check_20260413_142712.json` | 一次性检查输出 |
| `results/secondary_launch_persistence_check_20260413_142712.md` | 同上 |

**保留**：`output/.gitkeep`（目录占位）。

---

## 三、策略与配置：未删改项及原因

以下内容经审查后**未删除、未改配置**，否则将破坏核心功能或需另做迁移与全量回归：

1. **`EnhancedHybridSystem`（`enhanced_hybrid_system.py` 及 `enhanced_*` 辅助模块）**  
   名称含「增强」，实为当前**主监控与盘中信号链路**，被 `main.py`、`run_service.py`、`system_self_check.py` 及大量测试引用。**不是废弃策略**，不可移除。

2. **`config.yaml` 中 `monitor.legacy_*` 等**  
   与 `enhanced_legacy_entry_runtime` 等逻辑绑定，用于**盘中 legacy 路由与参数**。删除需同步改代码与测试，本次仅作瘦身，未动配置。

3. **`FinalStrategy`（`final_strategy.py`）**  
   仍被 `strategy_adapters.FinalStrategyAdapter`、`run_daily_selection.py`、`real_trading_guide.py` 使用。**未删除**。

4. **`strategy_profile: alpha158`（`stock_selector` 等）**  
   当前业务默认配置；未在未经业务确认的情况下修改。

5. **Git 状态中已标记删除（`D`）的历史脚本**（如 `debug_*.py`、`final_strategy_fixed.py` 等）  
   已在仓库变更中体现为删除；本次操作**额外**清理了上述 8 个孤立模块与临时文件。

---

## 四、验证与已知问题

- 已执行：`python -c` 导入 `CompleteStrategySystem`、`register_default_strategies`、`FinalStrategy` — **通过**。
- 抽样运行：`pytest tests/test_system_integrity_guards.py tests/test_strong_start_strategy.py`  
  - **1 失败**：`EnhancedHybridSystem` 缺少属性 `allow_quote_fallback_when_minute_missing`（与本次删除文件无关，属既有问题）。

---

## 五、后续建议（可选）

1. 修复 `allow_quote_fallback_when_minute_missing` 初始化与 `config.yaml` 中 `allow_quote_fallback_when_minute_missing` 对齐，避免监控测试失败。  
2. 将 `scripts/` 下大量一次性研究脚本纳入 `.gitignore` 子目录或单独 `research/` 仓库，进一步减小主仓体积。  
3. 定期清理 `output/`、`results/` 下可再生的 JSON/日志（保留 `.gitkeep`）。

---

*报告生成：自动化瘦身流程；备份路径：`d:\HuaweiAI\backups\quantSystem2_full_20260413.bundle`。*
