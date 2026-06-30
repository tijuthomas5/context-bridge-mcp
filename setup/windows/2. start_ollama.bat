@echo off
setlocal

set OLLAMA=ollama
set PYTHON=python
:: Locate CB root dynamically — works regardless of where this script is placed
set "_S=%~dp0"
:_FIND_CB
if exist "%_S%mcp_server_hybrid.py" goto _CB_FOUND
for %%P in ("%_S%..") do set "_N=%%~fP\"
if /i "%_N%"=="%_S%" ( echo ERROR: Cannot find ContextBridge root & pause & exit /b 1 )
set "_S=%_N%" & goto _FIND_CB
:_CB_FOUND
set "CB_ROOT=%_S:~0,-1%"
set DEFAULT_MODEL=qwen2.5-coder:7b

echo.

:: Read model from config.hybrid.json (falls back to default if unavailable)
for /f "delims=" %%m in ('"%PYTHON%" -c "import json,sys; c=json.load(open(r'%CB_ROOT%\config.hybrid.json')); print(c['pipeline']['analysis_stage']['model'])" 2^>nul') do set MODEL=%%m
if not defined MODEL set MODEL=%DEFAULT_MODEL%

:: Check if Ollama is already running on port 11434
netstat -ano | findstr ":11434" | findstr "LISTENING" >nul 2>&1
if %errorlevel%==0 (
    echo Ollama is already running on port 11434.
) else (
    echo Starting Ollama...
    start "Ollama" cmd /k "%OLLAMA% serve"
    echo Waiting for Ollama to start...
    timeout /t 4 /nobreak >nul
)

echo Warming up model: %MODEL%
echo (This may take a minute on first load)
echo.
%OLLAMA% run %MODEL% /bye

echo.
echo Ollama is ready.
echo   Model : %MODEL%
echo   API   : http://localhost:11434
echo.
echo You can now run start_Context_Bridge.bat to start ContextBridge.
echo.
timeout /t 3 /nobreak >nul
