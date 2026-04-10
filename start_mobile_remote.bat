@echo off
setlocal
chcp 65001 >nul

set "ROOT=%~dp0"
set "ROOT_DIR=%ROOT%"
if "%ROOT_DIR:~-1%"=="\" set "ROOT_DIR=%ROOT_DIR:~0,-1%"
set "API_PORT=8000"
set "PYTHON=python"
set "NGROK_EXE="
set "DRY_RUN=0"

if /i "%~1"=="--dry-run" (
    set "DRY_RUN=1"
)

if exist "%ROOT_DIR%\.venv\Scripts\python.exe" (
    set "PYTHON=%ROOT_DIR%\.venv\Scripts\python.exe"
)

if not "%PYTHON%"=="python" (
    "%PYTHON%" -c "import fastapi" 1>nul 2>nul
    if errorlevel 1 (
        python -c "import fastapi" 1>nul 2>nul
        if not errorlevel 1 (
            set "PYTHON=python"
        )
    )
)

if not defined NGROK_EXE (
    if defined NGROK_PATH (
        if exist "%NGROK_PATH%" (
            set "NGROK_EXE=%NGROK_PATH%"
        )
    )
)

if not defined NGROK_EXE (
    if exist "%ROOT_DIR%\tools\ngrok.exe" (
        set "NGROK_EXE=%ROOT_DIR%\tools\ngrok.exe"
    )
)

if not defined NGROK_EXE (
    for /f "usebackq delims=" %%i in (`powershell -NoProfile -Command "$items=Get-ChildItem 'C:\Program Files\WindowsApps\ngrok.ngrok_*_x64__*\ngrok.exe' -ErrorAction SilentlyContinue; if($items){$latest=$items[0]; foreach($x in $items){ if($x.LastWriteTime -gt $latest.LastWriteTime){$latest=$x} }; $latest.FullName }"`) do (
        set "NGROK_EXE=%%i"
    )
)

echo ================================================================
echo Start Mobile Debug Service
echo ================================================================
echo Project: %ROOT_DIR%
echo Python : %PYTHON%
echo Port   : %API_PORT%
echo Ngrok  : %NGROK_EXE%
echo.

if not exist "%ROOT_DIR%\src\api\app.py" (
    echo [ERROR] Missing file: %ROOT_DIR%\src\api\app.py
    pause
    exit /b 1
)

if not defined NGROK_EXE (
    echo [ERROR] ngrok.exe not found.
    echo You can set env NGROK_PATH or install ngrok Desktop/MSIX first.
    pause
    exit /b 1
)

if "%DRY_RUN%"=="1" (
    echo [DRY RUN] API   : cmd /k "cd /d %ROOT_DIR% ^&^& %PYTHON% -m src.api.app"
    echo [DRY RUN] NGROK : cmd /k ""%NGROK_EXE%" http %API_PORT%"
    exit /b 0
)

start "QuantMobileAPI" cmd /k "cd /d %ROOT_DIR% && %PYTHON% -m src.api.app"
timeout /t 2 /nobreak >nul
start "QuantNgrok" cmd /k ""%NGROK_EXE%" http %API_PORT%"

echo Started:
echo 1) QuantMobileAPI window: backend server
echo 2) QuantNgrok window: tunnel URL
echo.
echo After ngrok is ready, copy HTTPS Forwarding URL to app API base URL.
echo Example: https://xxxx.ngrok-free.dev/
echo.
echo You can also open local inspector: http://127.0.0.1:4040
echo.
pause
endlocal
