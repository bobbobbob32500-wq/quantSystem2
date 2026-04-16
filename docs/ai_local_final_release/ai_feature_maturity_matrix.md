# AI功能分级矩阵（稳定性分层）

## 分级标准
- `Stable`：已纳入自动化回归且作为发布门禁。
- `Beta`：可用但验证覆盖不完整，建议受控使用。
- `Experimental`：探索能力，默认不作为发布阻塞项。

## 能力分层（当前）
| 功能 | 接口/模块 | 级别 | 说明 |
|---|---|---|---|
| AI状态查询 | `/api/ai/status` | Stable | 已纳入性能与可用性探针 |
| AI对话/快捷问答 | `/api/ai/chat`, `/api/ai/quick_ask` | Stable | smoke覆盖，真实LLM门禁可单独执行 |
| 管家状态与启停 | `/api/butler/status`, `/start`, `/stop` | Stable | smoke覆盖 |
| 管家风险检查 | `/api/butler/risk-check` | Stable | 金标结构回归覆盖 |
| 管家信号分析 | `/api/butler/signal-analysis` | Stable | 金标结构回归覆盖 |
| 管家历史查询 | `/api/butler/last-briefing`, `/last-review` | Stable | 兼容别名回归覆盖 |
| 预警系统 | `/api/alerts/*` | Beta | 有接口，未纳入发布门禁套件 |
| 执行助手 | `/api/execution/*` | Beta | 有接口，建议补契约与性能测试 |
| 深度复盘/周期报告 | `/api/review/deep`, `/api/reports/generate` | Beta | 有接口，建议补金标样例 |
| 风格学习/上下文问答/知识库 | `/api/style/*`, `/api/ai/context_qa`, `/api/knowledge/*` | Experimental | 能力探索期，暂不阻塞发布 |

## 使用建议
1. 前端默认展示 `Stable` 能力，`Beta/Experimental` 显式标注“实验能力”。
2. 每个迭代至少将 1 个 `Beta` 能力升级到 `Stable`（需补自动化门禁）。
3. 对 `Experimental` 能力启用独立开关，避免对主链路造成影响。

