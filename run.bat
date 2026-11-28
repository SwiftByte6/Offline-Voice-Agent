@echo off
setlocal
cd /d "%~dp0"
title P.E.K.K.A Launcher

echo Starting P.E.K.K.A setup and desktop app...
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0run.ps1"
if errorlevel 1 (
    echo.
    echo P.E.K.K.A did not start. See the error above.
    pause
    exit /b 1
)

endlocal
