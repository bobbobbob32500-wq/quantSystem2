# AI本地最终版部署指南（模板）

## 1. 部署目标
- 部署对象：
- 目标环境：
- 负责人：

## 2. 前置检查
1. Python 与依赖已安装。
2. `config/ai_config.yaml` 已按环境配置。
3. 本地模型服务（如 Ollama / DeepSeek）可用。
4. 数据目录读写权限正常。

## 3. 部署步骤
1. 安装依赖
```bash
pip install -r requirements.txt
```
2. 启动后端服务
```bash
python run_service.py
```
3. 启动看板/API
```bash
python dashboard.py
```
4. 启动前执行最终验证
```bash
python tools/run_ai_local_final_validation.py
```

## 4. 验收步骤
1. 检查 `/api/ai/status` 与 `/api/butler/status`。
2. 验证关键链路：chat、quick_ask、risk_check、signal_analysis。
3. 检查报告输出目录 `reports/release/`。

## 5. 回滚步骤
1. 停止服务并恢复上一稳定配置/版本。
2. 回滚后再次执行 smoke 验证。
3. 记录回滚原因和影响范围。

## 6. 运维监控建议
- 关注响应延迟、失败率、降级次数。
- 每日归档验证报告与关键日志。

