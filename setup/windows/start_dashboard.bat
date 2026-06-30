@echo off
setlocal
:: Locate CB root dynamically — works regardless of where this script is placed
set "_S=%~dp0"
:_FIND_CB
if exist "%_S%mcp_server_hybrid.py" goto _CB_FOUND
for %%P in ("%_S%..") do set "_N=%%~fP\"
if /i "%_N%"=="%_S%" ( echo ERROR: Cannot find ContextBridge root & pause & exit /b 1 )
set "_S=%_N%" & goto _FIND_CB
:_CB_FOUND
set "CB_ROOT=%_S:~0,-1%"
for %%P in ("%CB_ROOT%\..") do set "ROOT=%%~fP"
cd /d "%ROOT%"
start "ContextBridge Dashboard Server" cmd /k python context_bridge\dashboard_server.py
timeout /t 2 /nobreak >nul
start "" http://127.0.0.1:8795
