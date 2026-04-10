@echo off
chcp 65001 >nul 2>&1
echo ================================================================
echo   A股量化交易辅助系统 - 停止后台服务
echo ================================================================
echo.
echo 正在查找并停止服务...
taskkill /FI "WINDOWTITLE eq QuantService*" /F 2>nul
if %errorlevel%==0 (
    echo 服务已停止
) else (
    echo 未找到运行中的服务
)
echo.
pause
