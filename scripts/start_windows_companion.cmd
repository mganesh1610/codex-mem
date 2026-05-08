@echo off
setlocal
cd /d "%~dp0\.."
set "DASHBOARD_URL=%~1"
if "%DASHBOARD_URL%"=="" set "DASHBOARD_URL=http://127.0.0.1:37801"
python .\scripts\windows_companion.py --dashboard-url "%DASHBOARD_URL%"
