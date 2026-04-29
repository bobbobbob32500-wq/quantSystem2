# 云服务器AI部署指南

> 说明：本文件最初基于旧部署形态编写。当前真实运行环境已经切到 `/opt/quant-system`，移动 API 由 supervisor 中的 `quant-api` 管理。若你的目标是做“可迁移备份并在新环境直接恢复”，请优先使用 [docs/portable_baseline_package.md](./portable_baseline_package.md)。

## 你的服务器信息

```
实例ID: 87ef6cc21634401da83ae98b81ffb1cf
公网IP: 101.133.149.141
配置: 2vCPU / 4GB内存 / 50GB存储 / 无GPU
系统: 宝塔Linux面板
```

## 部署方案：云API服务

**推荐使用云API，原因：**
- ✅ 你的服务器配置足够（无需GPU）
- ✅ 成本极低（每月¥1-2）
- ✅ 性能优秀（响应快）
- ✅ 部署简单（5分钟完成）

---

## 快速部署步骤

### 步骤1: 连接服务器

```bash
# SSH连接
ssh root@101.133.149.141

# 或使用宝塔面板终端
```

### 步骤2: 进入项目目录

```bash
# 假设项目在 /www/wwwroot/quantSystem2
cd /www/wwwroot/quantSystem2

# 如果项目不存在，先克隆
git clone https://your-repo/quantSystem2.git
cd quantSystem2
```

### 步骤3: 运行部署脚本

```bash
# 添加执行权限
chmod +x deploy_cloud_api.sh

# 运行脚本
./deploy_cloud_api.sh
```

按提示选择云服务商（推荐DeepSeek），输入API密钥。

### 步骤4: 手动配置（如果脚本失败）

#### 4.1 获取API密钥

**推荐：DeepSeek（最便宜）**
1. 访问 https://platform.deepseek.com/
2. 注册账号
3. 创建API Key
4. 复制密钥

**备选：通义千问**
1. 访问 https://dashscope.console.aliyun.com/
2. 开通服务
3. 创建API Key

#### 4.2 配置环境变量

```bash
# 编辑 .env 文件
nano .env

# 添加以下内容（选择一个）
DEEPSEEK_API_KEY=your_api_key_here
# 或
QWEN_API_KEY=your_api_key_here
```

#### 4.3 更新AI配置

```bash
# 使用云API配置
cp config/ai_config.cloud_api.yaml config/ai_config.yaml

# 编辑配置（可选）
nano config/ai_config.yaml
```

修改 `provider` 字段：
```yaml
provider: "deepseek"  # 或 "qwen"
```

### 步骤5: 重启服务

```bash
# 方式1: 使用systemd（推荐）
systemctl restart quant-system

# 方式2: 使用supervisor
supervisorctl restart quant-system

# 方式3: 直接运行
pkill -f dashboard.py
nohup python3 dashboard.py > logs/system.log 2>&1 &
```

### 步骤6: 验证部署

```bash
# 检查服务状态
curl http://localhost:8501/api/ai/status

# 测试AI对话
curl -X POST http://localhost:8501/api/ai/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "你好"}'

# 启动AI管家
curl -X POST http://localhost:8501/api/butler/start
```

---

## 宝塔面板配置

### 使用宝塔面板部署

#### 1. 安装Python项目管理器

在宝塔面板：
1. 软件商店 → 搜索 "Python项目管理器"
2. 点击安装

#### 2. 创建项目

1. 网站 → Python项目 → 添加项目
2. 配置：
   - 项目名称: quantSystem2
   - 项目路径: /www/wwwroot/quantSystem2
   - Python版本: 3.9+
   - 启动文件: dashboard.py
   - 端口: 8501

#### 3. 配置环境变量

在项目设置中添加环境变量：
```
DEEPSEEK_API_KEY=your_api_key_here
```

#### 4. 启动项目

点击"启动"按钮

---

## 成本估算

### DeepSeek（推荐）

| 使用场景 | 每日消耗 | 每日费用 | 每月费用 |
|---------|---------|---------|---------|
| 盘前简报 | 2000 tokens | ¥0.002 | ¥0.06 |
| 盘中监控 | 12000 tokens | ¥0.012 | ¥0.36 |
| 盘后复盘 | 3000 tokens | ¥0.003 | ¥0.09 |
| 其他交互 | 10000 tokens | ¥0.01 | ¥0.30 |
| **合计** | **27000 tokens** | **¥0.027** | **¥0.81** |

**每月AI成本：约 ¥1**

### 通义千问

**每月AI成本：约 ¥2**

---

## 监控与优化

### 查看API使用情况

```bash
# 查看日志
tail -f logs/ai.log

# 查看API调用统计
curl http://localhost:8501/api/ai/stats
```

### 优化建议

1. **启用缓存**（已配置）
   - 相同问题不重复调用API
   - 缓存时间：2小时

2. **设置限流**（已配置）
   - 每分钟最多20次请求
   - 每日最多50000 tokens

3. **降级保护**
   - API不可用时自动降级
   - 不影响系统其他功能

---

## 常见问题

### Q1: API密钥配置后不生效？

```bash
# 检查环境变量
echo $DEEPSEEK_API_KEY

# 如果为空，手动加载
source .env
export DEEPSEEK_API_KEY=your_key
```

### Q2: API调用失败？

```bash
# 测试API连接
curl -X POST https://api.deepseek.com/v1/chat/completions \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"model":"deepseek-chat","messages":[{"role":"user","content":"你好"}]}'
```

### Q3: 如何切换云服务商？

```bash
# 编辑配置文件
nano config/ai_config.yaml

# 修改provider
provider: "qwen"  # 从deepseek切换到qwen

# 重启服务
systemctl restart quant-system
```

### Q4: 如何查看费用？

- DeepSeek: https://platform.deepseek.com/usage
- 通义千问: https://dashscope.console.aliyun.com/billing

---

## 下次更新流程

```bash
# 1. 拉取最新代码
git pull origin main

# 2. 更新依赖
pip3 install -r requirements.txt --upgrade

# 3. 检查AI配置
cat config/ai_config.yaml

# 4. 重启服务
systemctl restart quant-system

# 5. 验证
curl http://localhost:8501/api/ai/status
```

---

## 总结

✅ **你的服务器完全适合使用云API方案**

| 项目 | 状态 |
|------|------|
| 服务器配置 | ✅ 满足要求 |
| 部署方案 | 云API（DeepSeek/通义千问） |
| 预估成本 | ¥1-2/月 |
| 部署时间 | 5-10分钟 |
| 性能 | 优秀（响应快） |

**推荐：使用DeepSeek，性价比最高！**
