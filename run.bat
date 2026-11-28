@echo off
setlocal
title PEKKA Floating Pill Launcher
cd /d "%~dp0"

echo [1/3] Checking ports 3000 and 8000...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":3000 " ^| findstr "LISTENING"') do (
    echo Stopping existing process on port 3000 - PID %%a
    taskkill /PID %%a /F >nul 2>&1
)
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8000 " ^| findstr "LISTENING"') do (
    echo Stopping existing process on port 8000 - PID %%a
    taskkill /PID %%a /F >nul 2>&1
)

echo [2/3] Starting speech backend on port 8000...
if exist "engine\.venv\Scripts\python.exe" (
    start "PEKKA Speech Engine" /min "engine\.venv\Scripts\python.exe" -m uvicorn engine.main:app --host 127.0.0.1 --port 8000
) else (
    echo Warning: engine\.venv not found; launching UI only.
)

echo [3/3] Launching Tauri floating window...
call pnpm exec tauri dev
if errorlevel 1 (
    echo.
    echo Tauri launch failed. Check errors above.
    pause
)
