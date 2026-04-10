# 命令行构建指南

无需 Android Studio，使用命令行即可完成 Android 应用开发！

## 📋 前置要求

### 1. 安装 JDK
需要安装 JDK 17 或更高版本：
- 下载地址：https://adoptium.net/
- 或使用 Microsoft OpenJDK：https://learn.microsoft.com/zh-cn/java/openjdk/download

安装后配置环境变量：
```powershell
# 临时设置（当前终端）
$env:JAVA_HOME = "C:\Program Files\Eclipse Adoptium\jdk-17.0.9-hotspot"
$env:PATH = "$env:JAVA_HOME\bin;$env:PATH"

# 验证
java -version
```

### 2. 安装 Android SDK Command-line Tools

#### 方法一：使用 Android Studio（推荐首次）
1. 下载 Android Studio：https://developer.android.com/studio
2. 安装后打开 SDK Manager
3. 安装：
   - Android SDK Platform-Tools
   - Android SDK Build-Tools 34.0.0
   - Android 14.0 (API 34) SDK Platform

#### 方法二：仅使用命令行工具
1. 下载 Command line tools only：https://developer.android.com/studio#command-tools
2. 解压到目录，例如：`C:\Android\cmdline-tools\latest`
3. 使用 sdkmanager 安装组件：
```bash
sdkmanager "platform-tools" "platforms;android-34" "build-tools;34.0.0"
```

### 3. 配置 local.properties

复制 `local.properties.example` 为 `local.properties`：
```powershell
Copy-Item local.properties.example local.properties
```

编辑 `local.properties`，设置你的 Android SDK 路径：
```properties
sdk.dir=C\:\\Users\\你的用户名\\AppData\\Local\\Android\\Sdk
```

或者：
```properties
sdk.dir=C\:\\Android\\Sdk
```

## 🚀 快速开始

### 使用 PowerShell 构建脚本（推荐）

#### 1. 快速构建 Debug APK
```powershell
cd android_app
.\quick_build.ps1
```

#### 2. 交互式构建菜单
```powershell
.\build.ps1
```

### 使用 Gradle 直接命令

#### 清理项目
```powershell
.\gradlew.bat clean
```

#### 构建 Debug APK
```powershell
.\gradlew.bat assembleDebug
```
输出位置：`app/build/outputs/apk/debug/app-debug.apk`

#### 构建 Release APK
```powershell
.\gradlew.bat assembleRelease
```
输出位置：`app/build/outputs/apk/release/app-release.apk`

#### 安装到连接的设备
```powershell
.\gradlew.bat installDebug
```

#### 查看可用任务
```powershell
.\gradlew.bat tasks
```

## 📱 安装 APK 到设备

### 方法一：使用 adb（推荐）
```powershell
# 确保设备已连接并开启 USB 调试
adb devices

# 安装 APK
adb install app\build\outputs\apk\debug\app-debug.apk

# 覆盖安装
adb install -r app\build\outputs\apk\debug\app-debug.apk

# 启动应用
adb shell am start -n com.quant.system/.MainActivity
```

### 方法二：直接传输到手机
1. 构建 APK 后，找到 `app-debug.apk`
2. 通过 USB、蓝牙或微信等方式传输到手机
3. 在手机上点击安装

## 🔧 常见问题

### 问题：JAVA_HOME 未设置
```powershell
# 设置 JAVA_HOME 环境变量
$env:JAVA_HOME = "C:\Program Files\Eclipse Adoptium\jdk-17.0.9-hotspot"
```

### 问题：找不到 Android SDK
确保 `local.properties` 中的 `sdk.dir` 路径正确，注意 Windows 路径需要双反斜杠：
```properties
sdk.dir=C\:\\Users\\张三\\AppData\\Local\\Android\\Sdk
```

### 问题：Gradle 下载慢
在 `gradle.properties` 中添加国内镜像：
```properties
systemProp.http.proxyHost=127.0.0.1
systemProp.http.proxyPort=7890
systemProp.https.proxyHost=127.0.0.1
systemProp.https.proxyPort=7890
```

### 问题：首次构建慢
首次构建会下载 Gradle 和依赖，请耐心等待，后续构建会很快。

## 📊 项目结构
```
android_app/
├── gradlew.bat              ← Gradle Wrapper (Windows)
├── build.ps1               ← 交互式构建脚本
├── quick_build.ps1         ← 快速构建脚本
├── local.properties.example ← SDK 配置模板
├── local.properties        ← SDK 配置（需创建）
├── app/
│   ├── build.gradle.kts
│   └── src/main/
│       ├── java/           ← Kotlin 源代码
│       ├── res/            ← 资源文件
│       └── AndroidManifest.xml
└── build/                  ← 构建输出（自动生成）
    └── outputs/
        └── apk/
            └── debug/
                └── app-debug.apk  ← APK 输出位置
```

## 🎯 完整工作流示例

```powershell
# 1. 进入项目目录
cd d:\HuaweiAI\quantSystem2\android_app

# 2. 配置 SDK（首次）
# 编辑 local.properties

# 3. 快速构建
.\quick_build.ps1

# 4. 安装到设备
adb install app\build\outputs\apk\debug\app-debug.apk

# 5. 启动应用
adb shell am start -n com.quant.system/.MainActivity
```

## 📝 提示

- 建议使用 PowerShell 7 或更高版本
- 确保电脑和手机在同一局域网（用于API连接）
- 修改代码后重新运行构建命令即可
- 使用 `.\gradlew.bat clean` 清理后重新构建可以解决很多问题
