# AI管家使用指南

## 概述

AI管家是量化交易系统的智能运营助手，能够主动监控、智能预警、提供决策建议，让您的量化交易更加轻松高效。

## 管家职责

### 盘前 (8:00-9:15)
- ✅ 检查数据更新状态，提醒缺失数据
- ✅ 分析昨日复盘，生成今日策略建议
- ✅ 解读选股结果，标注重点关注标的
- ✅ 分析隔夜新闻，预警潜在风险机会

### 盘中 (9:30-15:00)
- ✅ 实时监控持仓，异常波动预警
- ✅ 解读盘中信号，给出操作建议
- ✅ 监控市场环境，提示系统性风险
- ✅ 跟踪关注标的，提醒关键价位

### 盘后 (15:00-18:00)
- ✅ 自动生成复盘报告
- ✅ 评估今日操作，总结得失
- ✅ 分析信号有效性，优化建议
- ✅ 规划明日策略

### 全天候
- ✅ 回答用户问题，提供专业建议
- ✅ 生成策略代码，辅助量化开发
- ✅ 系统健康监控，异常告警
- ✅ 个性化学习，适应交易风格

## 安装部署

### 1. 安装Ollama
```bash
# Windows: 访问 https://ollama.com/download
# 或使用winget
winget install Ollama.Ollama
```

### 2. 下载模型
```bash
# 运行安装脚本
setup_ai.bat

# 或手动下载
ollama pull qwen2.5:7b    # 中文主力模型 (~4.7GB)
ollama pull mistral:7b    # 代码生成模型 (~4.1GB)
```

### 3. 启动服务
```bash
# 启动Ollama
ollama serve

# 启动量化系统
python dashboard.py
```

## API接口

### 管家服务控制

| 接口 | 方法 | 说明 |
|------|------|------|
| `/api/butler/status` | GET | 获取管家状态 |
| `/api/butler/start` | POST | 启动管家服务 |
| `/api/butler/stop` | POST | 停止管家服务 |

### 核心功能

| 接口 | 方法 | 说明 |
|------|------|------|
| `/api/butler/briefing` | POST | 生成盘前简报 |
| `/api/butler/monitor` | POST | 执行盘中监控 |
| `/api/butler/review` | POST | 生成盘后复盘 |
| `/api/butler/risk-check` | POST | 执行风险检查 |
| `/api/butler/signal-analysis` | POST | 信号实时分析 |

### 查询接口

| 接口 | 方法 | 说明 |
|------|------|------|
| `/api/butler/last-briefing` | GET | 获取最近盘前简报 |
| `/api/butler/last-review` | GET | 获取最近盘后复盘 |

## 使用示例

### 1. 启动管家服务
```bash
curl -X POST http://localhost:8501/api/butler/start
```

### 2. 生成盘前简报
```bash
curl -X POST http://localhost:8501/api/butler/briefing \
  -H "Content-Type: application/json" \
  -d '{
    "today_selection": [
      {"code": "000001.SZ", "name": "平安银行", "score": 85.5},
      {"code": "600036.SH", "name": "招商银行", "score": 82.3}
    ]
  }'
```

### 3. 执行风险检查
```bash
curl -X POST http://localhost:8501/api/butler/risk-check \
  -H "Content-Type: application/json" \
  -d '{
    "holdings": [
      {"code": "000001.SZ", "name": "平安银行", "position": 0.3, "pnl_pct": -2.5}
    ],
    "market_data": {"regime": "NORMAL"}
  }'
```

### 4. 信号实时分析
```bash
curl -X POST http://localhost:8501/api/butler/signal-analysis \
  -H "Content-Type: application/json" \
  -d '{
    "signal": {"type": "突破信号", "time": "10:30:00"},
    "stock_info": {"code": "000001.SZ", "name": "平安银行", "price": 12.5}
  }'
```

## 定时任务

管家服务启动后，会自动执行以下定时任务：

| 任务 | 时间 | 说明 |
|------|------|------|
| 盘前简报 | 每交易日 8:15 | 生成今日作战计划 |
| 盘中监控 | 交易时段每30分钟 | 监控持仓和信号 |
| 盘后复盘 | 每交易日 15:30 | 总结今日得失 |
| 风险检查 | 每15分钟 | 检查风险敞口 |

## Web看板使用

1. 启动看板: `python dashboard.py`
2. 访问: http://localhost:8501
3. 点击侧边栏 "AI助手"
4. 开始与管家对话

### 快速问答
- **市场分析**: 分析当前市场环境
- **选股逻辑**: 解释系统选股逻辑
- **风控策略**: 介绍风控方法
- **策略优化**: 提供优化建议

## 配置文件

配置文件位于 `config/ai_config.yaml`：

```yaml
ai:
  enabled: true
  ollama:
    base_url: "http://localhost:11434"
  models:
    default: "qwen2.5:7b"
    code: "mistral:7b"
  generation:
    temperature: 0.7
    max_tokens: 2048
```

## 注意事项

1. **数据隐私**: 所有数据本地处理，不上传云端
2. **降级机制**: Ollama不可用时自动降级，不影响系统运行
3. **仅供参考**: AI建议仅供参考，不构成投资建议
4. **风险提示**: 交易有风险，投资需谨慎

## 故障排除

### Ollama服务无法启动
```bash
# 检查端口占用
netstat -ano | findstr 11434

# 重启服务
ollama serve
```

### 模型下载慢
```bash
# 使用镜像（如果有）
# 或耐心等待，模型较大
```

### AI响应慢
- 正常现象，7B模型推理需要1-3秒
- 可以调低 `max_tokens` 加快响应
- 或使用更小的模型（如 qwen2.5:3b）

## 进阶用法

### 自定义管家行为
修改 `src/modules/ai_integration/ai_butler.py` 中的提示词模板。

### 对接系统模块
在 `src/services/ai_butler_service.py` 中实现数据获取方法：
- `_get_yesterday_review()`
- `_get_today_selection()`
- `_get_current_holdings()`
- 等等

### 添加消息推送
```python
def push_callback(title, content):
    # 对接企业微信/钉钉
    pass

butler_service = AIButlerService(push_callback=push_callback)
```
