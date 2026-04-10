# 量化交易系统 - Android移动端

## 项目结构

```
android_app/
├── app/
│   ├── src/
│   │   ├── main/
│   │   │   ├── java/com/quant/system/
│   │   │   │   ├── data/           # 数据层
│   │   │   │   │   ├── api/        # API接口
│   │   │   │   │   ├── model/      # 数据模型
│   │   │   │   │   └── repository/ # 数据仓库
│   │   │   │   ├── domain/         # 领域层
│   │   │   │   │   └── usecase/    # 用例
│   │   │   │   ├── ui/             # UI层
│   │   │   │   │   ├── theme/      # 主题
│   │   │   │   │   ├── screen/     # 页面
│   │   │   │   │   └── component/  # 组件
│   │   │   │   └── di/             # 依赖注入
│   │   │   └── res/                 # 资源文件
│   │   └── test/                     # 测试
│   └── build.gradle.kts
├── gradle/
├── build.gradle.kts
└── settings.gradle.kts
```

## 技术栈

- **语言**: Kotlin
- **UI框架**: Jetpack Compose
- **架构**: MVVM + Clean Architecture
- **网络**: Retrofit + OkHttp
- **依赖注入**: Hilt
- **异步**: Coroutines + Flow
- **数据存储**: DataStore

## 快速开始

### 1. 使用Android Studio打开项目

### 2. 配置后端API地址

在 `app/src/main/java/com/quant/system/data/api/ApiService.kt` 中配置：

```kotlin
private const val BASE_URL = "http://192.168.1.100:8000"
```

### 3. 启动后端API服务

```bash
# 在项目根目录执行
pip install -r requirements_api.txt
python -m src.api.app
```

### 4. 构建并运行Android应用

## 功能模块

- 🏠 概览页面
- 🎯 选股页面
- 📡 信号页面
- 💰 交易页面
- ⚡ 操作页面
- 📋 历史记录
- ⚙️ 设置页面
