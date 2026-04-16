# AI本地最终版部署指南（2026-04-16批次）

## 1. 部署目标
- 目标：在本地环境部署并确认 AI 最终版本可上线状态。
- 覆盖：AI服务、AI管家、移动API兼容路由、验证与报告归档。

## 2. 前置检查
1. Python 3.14+ 与依赖已安装。
2. `config/ai_config.yaml` 完成环境配置。
3. 本地模型服务可用（Ollama 或 DeepSeek 服务）。
4. 数据目录具备读写权限：`data/`、`reports/`。

## 3. 部署步骤
1. 安装依赖
```bash
pip install -r requirements.txt
```
2. 启动后台服务
```bash
python run_service.py
```
3. 启动看板/API
```bash
python dashboard.py
```

## 4. 最终版本确认步骤
1. 执行 smoke + 契约回归
```bash
python -m pytest -m smoke tests/test_ai_mobile_api_smoke.py tests/test_mobile_api_contract.py
```
2. 执行四维一键验证
```bash
python tools/run_ai_local_final_validation.py
```
3. 检查报告是否生成：
- `reports/release/ai_local_final_validation_*.md`
- `reports/release/ai_local_final_validation_*.json`
4. 补充真实模型连通性验证（建议上线前执行）
```bash
set RUN_AI_LLM_SMOKE=1
python -m pytest tests/test_ai_mobile_api_smoke.py
```

## 5. 验收清单
1. `/api/ai/status` 返回 200 且字段完整。
2. `/api/butler/status` 返回 200 且状态正确。
3. 兼容别名路由可用：
- `/api/butler/risk-check`
- `/api/butler/signal-analysis`
- `/api/butler/last-briefing`
- `/api/butler/last-review`
4. 一键验证结论为 `overall_passed=True`。

## 6. 回滚策略
1. 停止本轮服务进程。
2. 回退到上一稳定版本代码与配置。
3. 再次执行 smoke 套件确认恢复状态。
4. 记录回滚原因、影响范围、修复计划。

## 7. 运维建议
- 每次部署后归档 `reports/release/` 报告。
- 重点监控 AI 接口延迟、失败率、降级次数。
- 若出现异常，优先检查模型服务状态与 API 配置项。

