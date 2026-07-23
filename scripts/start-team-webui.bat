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

REM Kill any leftover process on port 8799
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8799" ^| findstr "LISTENING"') do (
    taskkill /F /PID %%a >nul 2>&1
)

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
