@echo off
title Bybit Short-DTE Income Dashboard

cd /d "%~dp0"

echo Starting Bybit Short-DTE Income Dashboard...
echo.

REM Open the browser after a short delay so the server is ready
start "" /b cmd /c "timeout /t 2 >nul && start http://localhost:8000"

REM Start the server (stays open in this window)
.venv\Scripts\python.exe -m uvicorn backend.app:app --port 8000

echo.
echo Server stopped. Press any key to close.
pause >nul
