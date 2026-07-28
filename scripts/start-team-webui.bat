@echo off
chcp 437 >nul
title WDP Team Hermes - Web UI (port 8799, multiuser)

echo ============================================================
echo   WDP Team Hermes - Web UI (multiuser mode)
echo ============================================================
echo.
echo   Local URL:   http://127.0.0.1:8799
echo   Model:       moonshotai/kimi-k3 (OpenRouter)
echo   HERMES_HOME: E:\wdp-team-hermes\hermes-home
echo   Multi-user:  ENABLED (HERMES_WEBUI_MULTIUSER=1)
echo.
echo   To stop: close this window
echo ============================================================
echo.

REM ===== Kill leftover processes (retry until port 8799 is free) =====
echo Cleaning up old processes on port 8799 ...
setlocal enabledelayedexpansion
set /a _try=0
:killloop
set _found=0
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8799" ^| findstr "LISTENING"') do (
    set _found=1
    taskkill /F /PID %%a >nul 2>&1
)
REM Fallback: kill any python.exe running server.py from this project (in case netstat missed a PID)
for /f "tokens=2 delims=," %%p in ('wmic process where "name='python.exe' and commandline like '%%server.py%%'" get processid^,commandline /format:csv 2^>nul ^| findstr /i "wdp-team-hermes"') do (
    taskkill /F /PID %%p >nul 2>&1
)
REM Wait a moment for the port to release, then re-check
ping -n 2 127.0.0.1 >nul
netstat -ano | findstr ":8799" | findstr "LISTENING" >nul 2>&1
if not errorlevel 1 (
    set /a _try+=1
    if !_try! lss 5 (
        echo   Port still busy, retrying kill ... [!_try!/5]
        goto killloop
    ) else (
        echo   WARNING: port 8799 still has a listener after 5 tries.
        echo   Close any leftover Hermes windows manually, then restart this launcher.
        echo.
    )
) else (
    echo   Port 8799 is now free.
)
endlocal
echo.

cd /d E:\wdp-team-hermes\web-ui

set HERMES_HOME=E:\wdp-team-hermes\hermes-home
set HERMES_WEBUI_AGENT_DIR=E:\wdp-team-hermes\agent-src
set HERMES_WEBUI_PYTHON=E:\wdp-team-hermes\agent-src\.venv\Scripts\python.exe
set HERMES_WEBUI_STATE_DIR=E:\wdp-team-hermes\hermes-home\webui
set HERMES_WEBUI_HOST=127.0.0.1
set HERMES_WEBUI_PORT=8799
set HERMES_WEBUI_MULTIUSER=1
set HERMES_KNOWLEDGE_DIR=E:\wdp-team-hermes\knowledge

REM Open browser after a short delay (give server time to boot)
start "" /min cmd /c "timeout /t 4 /nobreak >nul & start http://127.0.0.1:8799"

E:\wdp-team-hermes\agent-src\.venv\Scripts\python.exe server.py
