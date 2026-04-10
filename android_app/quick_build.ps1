# 快速构建脚本 - 一键构建 Debug APK
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  快速构建 Debug APK" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

$gradlew = Join-Path $PSScriptRoot "gradlew.bat"

Write-Host "正在构建..." -ForegroundColor Yellow
& $gradlew clean assembleDebug

if ($LASTEXITCODE -eq 0) {
    $apkPath = Join-Path $PSScriptRoot "app\build\outputs\apk\debug\app-debug.apk"
    Write-Host ""
    Write-Host "========================================" -ForegroundColor Green
    Write-Host "  ✓ 构建成功!" -ForegroundColor Green
    Write-Host "========================================" -ForegroundColor Green
    Write-Host ""
    Write-Host "APK 位置:" -ForegroundColor Cyan
    Write-Host $apkPath -ForegroundColor White
    Write-Host ""
    
    if (Test-Path $apkPath) {
        $apkSize = (Get-Item $apkPath).Length / 1MB
        Write-Host "文件大小: $([math]::Round($apkSize, 2)) MB" -ForegroundColor Gray
        
        $confirm = Read-Host "是否打开 APK 所在目录? (y/n)"
        if ($confirm -eq "y") {
            explorer.exe (Split-Path $apkPath -Parent)
        }
    }
} else {
    Write-Host ""
    Write-Host "========================================" -ForegroundColor Red
    Write-Host "  ✗ 构建失败!" -ForegroundColor Red
    Write-Host "========================================" -ForegroundColor Red
    Write-Host ""
    Write-Host "请查看上面的错误信息" -ForegroundColor Yellow
}
