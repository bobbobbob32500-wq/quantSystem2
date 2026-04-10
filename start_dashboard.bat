@echo off
setlocal
chcp 65001 >nul

set "ROOT=%~dp0"
set "PYTHON=python"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"

if exist "%ROOT%\.venv\Scripts\python.exe" (
    set "PYTHON=%ROOT%\.venv\Scripts\python.exe"
)

echo ================================================================================
echo 启动 Web 可视化看板
echo ================================================================================
echo.
echo 看板地址: http://127.0.0.1:8501
echo 按 Ctrl+C 停止看板
echo.

"%PYTHON%" -c "import flask, pandas, numpy" 1>nul 2>nul
if errorlevel 1 (
    echo [提示] 缺少依赖，正在安装 flask pandas numpy ...
    "%PYTHON%" -m pip install flask pandas numpy
)

"%PYTHON%" "%ROOT%start_dashboard.py"

endlocal
