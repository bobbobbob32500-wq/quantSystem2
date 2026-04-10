# 量化交易系统 Android 应用构建脚本
# 使用命令行构建，无需 Android Studio

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  量化交易系统 - Android 构建工具" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# 检查 Java 是否安装
Write-Host "[1/5] 检查 Java 环境..." -ForegroundColor Yellow
try {
    $javaVersion = java -version 2>&1 | Select-Object -First 1
    Write-Host "✓ Java: $javaVersion" -ForegroundColor Green
} catch {
    Write-Host "✗ Java 未安装或未配置到 PATH" -ForegroundColor Red
    Write-Host "请先安装 JDK 17 或更高版本" -ForegroundColor Red
    exit 1
}

# 检查 Android SDK
Write-Host "[2/5] 检查 Android SDK..." -ForegroundColor Yellow
$localProps = Join-Path $PSScriptRoot "local.properties"
if (Test-Path $localProps) {
    Write-Host "✓ 找到 local.properties" -ForegroundColor Green
    $sdkDir = Get-Content $localProps | Where-Object { $_ -match "^sdk.dir=" }
    if ($sdkDir) {
        Write-Host "  SDK 路径: $($sdkDir -replace 'sdk.dir=', '')" -ForegroundColor Gray
    }
} else {
    Write-Host "⚠ local.properties 未找到" -ForegroundColor Yellow
    Write-Host "  请复制 local.properties.example 为 local.properties" -ForegroundColor Gray
    Write-Host "  并配置 sdk.dir 路径" -ForegroundColor Gray
    Write-Host ""
    $confirm = Read-Host "是否继续尝试构建? (y/n)"
    if ($confirm -ne "y") {
        exit 0
    }
}

# 检查 Gradle Wrapper
Write-Host "[3/5] 检查 Gradle Wrapper..." -ForegroundColor Yellow
$gradlew = Join-Path $PSScriptRoot "gradlew.bat"
if (Test-Path $gradlew) {
    Write-Host "✓ Gradle Wrapper 就绪" -ForegroundColor Green
} else {
    Write-Host "✗ Gradle Wrapper 未找到" -ForegroundColor Red
    exit 1
}

# 显示构建选项
Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  选择构建操作:" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "1. 清理构建 (clean)" -ForegroundColor White
Write-Host "2. 构建 Debug APK (assembleDebug)" -ForegroundColor White
Write-Host "3. 构建 Release APK (assembleRelease)" -ForegroundColor White
Write-Host "4. 安装到设备 (installDebug)" -ForegroundColor White
Write-Host "5. 完整构建 (clean + assembleDebug)" -ForegroundColor White
Write-Host "0. 退出" -ForegroundColor White
Write-Host ""

$choice = Read-Host "请输入选项 (0-5)"

switch ($choice) {
    "1" {
        Write-Host ""
        Write-Host "执行清理..." -ForegroundColor Cyan
        & $gradlew clean
    }
    "2" {
        Write-Host ""
        Write-Host "构建 Debug APK..." -ForegroundColor Cyan
        & $gradlew assembleDebug
        if ($LASTEXITCODE -eq 0) {
            $apkPath = Join-Path $PSScriptRoot "app\build\outputs\apk\debug\app-debug.apk"
            Write-Host ""
            Write-Host "✓ 构建成功!" -ForegroundColor Green
            Write-Host "APK 位置: $apkPath" -ForegroundColor Cyan
        }
    }
    "3" {
        Write-Host ""
        Write-Host "构建 Release APK..." -ForegroundColor Cyan
        & $gradlew assembleRelease
        if ($LASTEXITCODE -eq 0) {
            $apkPath = Join-Path $PSScriptRoot "app\build\outputs\apk\release\app-release.apk"
            Write-Host ""
            Write-Host "✓ 构建成功!" -ForegroundColor Green
            Write-Host "APK 位置: $apkPath" -ForegroundColor Cyan
        }
    }
    "4" {
        Write-Host ""
        Write-Host "安装到设备..." -ForegroundColor Cyan
        & $gradlew installDebug
        if ($LASTEXITCODE -eq 0) {
            Write-Host ""
            Write-Host "✓ 安装成功!" -ForegroundColor Green
        }
    }
    "5" {
        Write-Host ""
        Write-Host "执行完整构建..." -ForegroundColor Cyan
        & $gradlew clean assembleDebug
        if ($LASTEXITCODE -eq 0) {
            $apkPath = Join-Path $PSScriptRoot "app\build\outputs\apk\debug\app-debug.apk"
            Write-Host ""
            Write-Host "✓ 构建成功!" -ForegroundColor Green
            Write-Host "APK 位置: $apkPath" -ForegroundColor Cyan
        }
    }
    "0" {
        Write-Host "退出" -ForegroundColor Gray
        exit 0
    }
    default {
        Write-Host "无效选项" -ForegroundColor Red
    }
}

Write-Host ""
Write-Host "完成!" -ForegroundColor Cyan
