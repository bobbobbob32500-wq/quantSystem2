@echo off
echo ================================================================
echo   A股量化交易辅助系统 - 启动后台服务
echo ================================================================
echo.
echo   启动方式: 
echo     1. 前台运行 (可看到输出，关闭窗口则停止)
echo     2. 后台运行 (最小化到后台持续运行)
echo.
set /p mode=请选择 (1/2): 

if "%mode%"=="1" (
    echo.
    echo 正在启动服务...
    python run_service.py
) else if "%mode%"=="2" (
    echo.
    echo 正在启动后台服务...
    start "QuantService" /min python run_service.py
    echo 服务已在后台启动！
    echo.
    echo 查看日志: type data\logs\quant_service.log
    echo 停止服务: 关闭 QuantService 窗口
    pause
) else (
    echo 无效选择
    pause
)
