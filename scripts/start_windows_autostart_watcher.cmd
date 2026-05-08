@echo off
setlocal
cd /d "%~dp0\.."
pythonw .\scripts\windows_autostart_watcher.py --repo-root "%cd%" --dashboard-url http://127.0.0.1:37801 --port 37801
