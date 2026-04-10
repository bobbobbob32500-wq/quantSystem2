# 环境检查脚本 - 检测 Android 开发环境

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Android 开发环境检查" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

$allPassed = $true

# 1. 检查 Java
Write-Host "[1/5] 检查 Java..." -ForegroundColor Yellow
try {
    $javaVersion = java -version 2>&1 | Select-Object -First 1
    if ($javaVersion -match "version ""(\d+)") {
        $majorVersion = [int]$matches[1]
        Write-Host "✓ Java 版本: $javaVersion" -ForegroundColor Green
        if ($majorVersion -ge 17) {
            Write-Host "  ✓ Java 版本符合要求 (>=17)" -ForegroundColor Green
        } else {
            Write-Host "  ⚠ Java 版本过低，建议使用 17 或更高" -ForegroundColor Yellow
        }
    } else {
        Write-Host "✓ Java 已安装: $javaVersion" -ForegroundColor Green
    }
} catch {
    Write-Host "✗ Java 未找到" -ForegroundColor Red
    Write-Host "  请安装 JDK 17+ 并配置到 PATH" -ForegroundColor Gray
    $allPassed = $false
}

Write-Host ""

# 2. 检查 JAVA_HOME
Write-Host "[2/5] 检查 JAVA_HOME..." -ForegroundColor Yellow
if ($env:JAVA_HOME) {
    Write-Host "✓ JAVA_HOME: $env:JAVA_HOME" -ForegroundColor Green
    if (Test-Path "$env:JAVA_HOME\bin\java.exe") {
        Write-Host "  ✓ java.exe 存在" -ForegroundColor Green
    } else {
        Write-Host "  ⚠ java.exe 未找到在 JAVA_HOME 中" -ForegroundColor Yellow
    }
} else {
    Write-Host "⚠ JAVA_HOME 未设置" -ForegroundColor Yellow
    Write-Host "  构建仍可能工作，但建议设置 JAVA_HOME" -ForegroundColor Gray
}

Write-Host ""

# 3. 检查 Android SDK
Write-Host "[3/5] 检查 Android SDK..." -ForegroundColor Yellow
$localProps = Join-Path $PSScriptRoot "local.properties"
if (Test-Path $localProps) {
    Write-Host "✓ local.properties 存在" -ForegroundColor Green
    $sdkDirLine = Get-Content $localProps | Where-Object { $_ -match "^sdk.dir=(.+)" }
    if ($sdkDirLine) {
        $sdkDir = $matches[1] -replace '\\', '\\' -replace '\\\\', '\'
        Write-Host "  SDK 路径: $sdkDir" -ForegroundColor Gray
        
        if (Test-Path $sdkDir) {
            Write-Host "  ✓ SDK 目录存在" -ForegroundColor Green
            
            $platformTools = Join-Path $sdkDir "platform-tools"
            if (Test-Path $platformTools) {
                Write-Host "  ✓ platform-tools 存在" -ForegroundColor Green
                
                $adb = Join-Path $platformTools "adb.exe"
                if (Test-Path $adb) {
                    Write-Host "  ✓ adb.exe 存在" -ForegroundColor Green
                }
            } else {
                Write-Host "  ⚠ platform-tools 未找到" -ForegroundColor Yellow
            }
            
            $platforms = Join-Path $sdkDir "platforms"
            if (Test-Path $platforms) {
                $api34 = Join-Path $platforms "android-34"
                if (Test-Path $api34) {
                    Write-Host "  ✓ android-34 平台存在" -ForegroundColor Green
                } else {
                    Write-Host "  ⚠ android-34 平台未找到" -ForegroundColor Yellow
                }
            }
        } else {
            Write-Host "  ✗ SDK 目录不存在" -ForegroundColor Red
            $allPassed = $false
        }
    }
} else {
    Write-Host "✗ local.properties 未找到" -ForegroundColor Red
    Write-Host "  请复制 local.properties.example 为 local.properties" -ForegroundColor Gray
    Write-Host "  并配置 sdk.dir 路径" -ForegroundColor Gray
    $allPassed = $false
}

Write-Host ""

# 4. 检查 Gradle Wrapper
Write-Host "[4/5] 检查 Gradle Wrapper..." -ForegroundColor Yellow
$gradlew = Join-Path $PSScriptRoot "gradlew.bat"
if (Test-Path $gradlew) {
    Write-Host "✓ gradlew.bat 存在" -ForegroundColor Green
} else {
    Write-Host "✗ gradlew.bat 未找到" -ForegroundColor Red
    $allPassed = $false
}

$wrapperProps = Join-Path $PSScriptRoot "gradle\wrapper\gradle-wrapper.properties"
if (Test-Path $wrapperProps) {
    Write-Host "✓ gradle-wrapper.properties 存在" -ForegroundColor Green
} else {
    Write-Host "✗ gradle-wrapper.properties 未找到" -ForegroundColor Red
    $allPassed = $false
}

Write-Host ""

# 5. 检查项目结构
Write-Host "[5/5] 检查项目结构..." -ForegroundColor Yellow
$appBuildGradle = Join-Path $PSScriptRoot "app\build.gradle.kts"
if (Test-Path $appBuildGradle) {
    Write-Host "✓ app/build.gradle.kts 存在" -ForegroundColor Green
} else {
    Write-Host "✗ app/build.gradle.kts 未找到" -ForegroundColor Red
    $allPassed = $false
}

$androidManifest = Join-Path $PSScriptRoot "app\src\main\AndroidManifest.xml"
if (Test-Path $androidManifest) {
    Write-Host "✓ AndroidManifest.xml 存在" -ForegroundColor Green
} else {
    Write-Host "✗ AndroidManifest.xml 未找到" -ForegroundColor Red
    $allPassed = $false
}

$mainActivity = Join-Path $PSScriptRoot "app\src\main\java\com\quant\system\MainActivity.kt"
if (Test-Path $mainActivity) {
    Write-Host "✓ MainActivity.kt 存在" -ForegroundColor Green
} else {
    Write-Host "✗ MainActivity.kt 未找到" -ForegroundColor Red
    $allPassed = $false
}

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  检查完成" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

if ($allPassed) {
    Write-Host "✓ 所有检查通过！可以开始构建了" -ForegroundColor Green
    Write-Host ""
    Write-Host "快速构建命令:" -ForegroundColor Cyan
    Write-Host "  .\quick_build.ps1" -ForegroundColor White
    Write-Host ""
    Write-Host "或使用交互式菜单:" -ForegroundColor Cyan
    Write-Host "  .\build.ps1" -ForegroundColor White
} else {
    Write-Host "⚠ 部分检查未通过，请修复上面的问题" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "详细文档请查看:" -ForegroundColor Cyan
    Write-Host "  README_CLI.md" -ForegroundColor White
}

Write-Host ""
