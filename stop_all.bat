@echo off
echo ================================================================
echo Stop Quant System: service + dashboard
echo ================================================================
echo.

echo [1/2] Stopping background service...
taskkill /FI "WINDOWTITLE eq QuantService*" /F 2>nul
if %errorlevel%==0 (
    echo Background service stopped.
) else (
    echo Background service not found.
)

echo.
echo [2/2] Stopping web dashboard...
taskkill /FI "WINDOWTITLE eq QuantDashboard*" /F 2>nul
if %errorlevel%==0 (
    echo Web dashboard stopped.
) else (
    echo Web dashboard not found.
)

echo.
pause
