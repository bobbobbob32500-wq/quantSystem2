# 量化交易系统 - 全栈开发指南

## 📋 项目概述

已完成全栈开发基础框架搭建：
- ✅ FastAPI后端API服务
- ✅ Android项目基础结构
- ✅ 数据模型和API接口定义
- ✅ 概览页面UI实现

## 📁 项目结构

```
quantSystem2/
├── src/
│   └── api/
│       └── app.py                    # FastAPI后端服务
├── android_app/                      # Android项目根目录
│   ├── app/
│   │   ├── src/main/
│   │   │   ├── java/com/quant/system/
│   │   │   │   ├── data/
│   │   │   │   │   ├── api/          # API接口
│   │   │   │   │   ├── model/        # 数据模型
│   │   │   │   │   └── repository/   # 数据仓库
│   │   │   │   ├── ui/
│   │   │   │   │   ├── screen/       # 页面
│   │   │   │   │   └── theme/        # 主题
│   │   │   │   ├── di/                # 依赖注入
│   │   │   │   └── MainActivity.kt
│   │   │   ├── res/                   # 资源文件
│   │   │   └── AndroidManifest.xml
│   │   └── build.gradle.kts
│   ├── build.gradle.kts
│   ├── settings.gradle.kts
│   └── README.md
├── requirements_api.txt                # API服务依赖
└── mobile_demo.html                  # HTML演示页面
```

## 🚀 快速开始

### 1. 启动后端API服务

```bash
# 安装依赖
pip install -r requirements_api.txt

# 启动API服务
python -m src.api.app
```

API服务将在 `http://0.0.0.0:8000` 启动

访问 `http://localhost:8000/docs` 查看API文档

### 2. 配置Android项目

#### 使用Android Studio打开项目：
1. 打开 Android Studio
2. 选择 `Open an Existing Project`
3. 选择 `d:\HuaweiAI\quantSystem2\android_app` 目录
4. 等待Gradle同步完成

#### 配置API地址：
修改 `android_app/app/src/main/java/com/quant/system/data/api/RetrofitClient.kt`：

```kotlin
private const val BASE_URL = "http://你的电脑IP:8000"
```

### 3. 运行Android应用

1. 连接Android设备或启动模拟器
2. 点击 Android Studio 的 Run 按钮
3. 选择目标设备并运行

## 📡 API接口说明

### 数据接口

| 接口 | 方法 | 说明 |
|------|------|------|
| `/api/dashboard` | GET | 获取完整仪表盘数据 |
| `/api/dashboard/overview` | GET | 获取概览数据 |
| `/api/candidate_pool` | GET | 获取候选池 |
| `/api/signals` | GET | 获取信号 |
| `/api/virtual_trades` | GET | 获取虚拟交易 |
| `/api/history` | GET | 获取历史记录 |

### 操作接口

| 接口 | 方法 | 说明 |
|------|------|------|
| `/api/action` | POST | 执行操作 |

支持的操作：
- `generate_plan` - 生成今日计划
- `run_stock_selection` - 运行选股
- `push_selection_wecom` - 推送选股
- `start_intraday_watch` - 开始盘中监控
- `start_monitor_runtime` - 启动监控服务
- `stop_monitor_runtime` - 停止监控服务
- `generate_post_market_review` - 生成盘后回顾
- `update_stock_data` - 更新股票数据
- `clear_candidate_pool` - 清空候选池
- `clear_history_records` - 清理历史记录

## 🎯 后续开发任务

### 后端优化
- [ ] 添加用户认证
- [ ] 添加WebSocket实时推送
- [ ] 优化API响应速度
- [ ] 添加请求日志

### Android开发
- [ ] 实现ViewModel和状态管理
- [ ] 连接真实API数据
- [ ] 完成选股页面
- [ ] 完成信号页面
- [ ] 完成交易页面
- [ ] 完成操作页面
- [ ] 完成历史记录页面
- [ ] 完成设置页面
- [ ] 添加数据缓存
- [ ] 添加离线支持
- [ ] 添加推送通知

## 🔧 技术栈

### 后端
- FastAPI - Web框架
- Python 3.x - 编程语言
- Uvicorn - ASGI服务器

### Android
- Kotlin - 编程语言
- Jetpack Compose - UI框架
- Retrofit - 网络请求
- Kotlinx Serialization - JSON序列化
- Coroutines + Flow - 异步处理
- MVVM + Clean Architecture - 架构模式

## 📱 功能页面

1. **🏠 概览页** - 已完成UI框架
2. **🎯 选股页** - 待开发
3. **📡 信号页** - 待开发
4. **💰 交易页** - 待开发
5. **⚡ 操作页** - 待开发
6. **📋 历史页** - 待开发
7. **⚙️ 设置页** - 待开发

## 📝 注意事项

1. **网络权限**：确保AndroidManifest.xml中已添加INTERNET权限
2. **明文流量**：开发阶段可以使用明文HTTP，正式发布需要HTTPS
3. **IP地址**：手机和电脑需要在同一局域网，使用电脑的局域网IP
4. **防火墙**：确保电脑防火墙允许8000端口访问

## 🎉 开发进度

- ✅ 后端API服务框架
- ✅ Android项目结构
- ✅ 数据模型定义
- ✅ API接口定义
- ✅ Repository层
- ✅ UI主题配置
- ✅ 概览页面UI框架
- 🔄 持续开发中...
