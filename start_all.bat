@echo off
setlocal
set "DASHBOARD_URL=http://127.0.0.1:8501"

set "ROOT=%~dp0"
set "FALLBACK_ROOT=D:\HuaweiAI\quantSystem2\"
set "PYTHON=python"

if not exist "%ROOT%run_service.py" (
    if exist "%FALLBACK_ROOT%run_service.py" (
        set "ROOT=%FALLBACK_ROOT%"
    )
)

set "VENV_PYTHON=%ROOT%.venv\Scripts\python.exe"
set "SERVICE_SCRIPT=%ROOT%run_service.py"
set "DASHBOARD_SCRIPT=%ROOT%dashboard.py"

if exist "%VENV_PYTHON%" (
    set "PYTHON=%VENV_PYTHON%"
)

echo ================================================================
echo Start Quant System: service + dashboard
echo ================================================================
echo ROOT=%ROOT%
echo PYTHON=%PYTHON%
echo.

if not exist "%SERVICE_SCRIPT%" (
    echo [ERROR] Missing file: %SERVICE_SCRIPT%
    pause
    exit /b 1
)

if not exist "%DASHBOARD_SCRIPT%" (
    echo [ERROR] Missing file: %DASHBOARD_SCRIPT%
    pause
    exit /b 1
)

"%PYTHON%" -c "import flask, pandas, numpy" 1>nul 2>nul
if errorlevel 1 (
    echo [INFO] Installing missing packages: flask pandas numpy
    "%PYTHON%" -m pip install flask pandas numpy
)

tasklist /V /FI "WINDOWTITLE eq QuantService*" | find /I "QuantService" >nul
if errorlevel 1 (
    echo [1/3] Starting background service...
    start "QuantService" /min "%PYTHON%" "%SERVICE_SCRIPT%"
) else (
    echo [1/3] Background service already running. Skip.
)

tasklist /V /FI "WINDOWTITLE eq QuantDashboard*" | find /I "QuantDashboard" >nul
if errorlevel 1 (
    netstat -ano | find ":8501" >nul
    if errorlevel 1 (
        echo [2/3] Starting web dashboard...
        start "QuantDashboard" "%PYTHON%" "%DASHBOARD_SCRIPT%"
    ) else (
        echo [2/3] Port 8501 is already in use. Skip dashboard start.
    )
) else (
    echo [2/3] Web dashboard already running. Skip.
)

echo [3/3] Opening browser...
start "" "%DASHBOARD_URL%"

echo.
echo Done.
echo Dashboard: %DASHBOARD_URL%
echo To stop everything, run stop_all.bat
echo.
pause
endlocal
