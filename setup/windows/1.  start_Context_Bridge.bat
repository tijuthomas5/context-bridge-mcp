@echo off
setlocal

:: Detect Python from PATH (requires Python 3.10+ in system/user PATH)
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
for %%P in ("%CB_ROOT%\..") do set "ROOT=%%~fP"
set PORT=8755

echo.
echo Select ContextBridge mode:
echo   1. Hybrid   (keyword + vector)  [recommended]
echo   2. Semantic (vector only)
echo   3. Keyword  (keyword only)
echo.
set /p CHOICE=Enter 1, 2 or 3 (default: 1):

:: Hybrid = keyword + HASH vector (deterministic hash-384 index)
set CONTEXT_BRIDGE_CONFIG=config.hybrid.json
set MODE=Hybrid
set CB_VECTOR_INDEX=%ROOT%\context_bridge\data\vector_index.jsonl
set CB_VECTOR_META=%ROOT%\context_bridge\data\vector_meta.json

if "%CHOICE%"=="2" (
    :: Semantic = SEMANTIC vector only (no keyword)
    set CONTEXT_BRIDGE_CONFIG=config.semantic.json
    set CB_VECTOR_INDEX=%ROOT%\context_bridge\data\vector_index.semantic.jsonl
    set CB_VECTOR_META=%ROOT%\context_bridge\data\vector_meta.semantic.json
    set MODE=Semantic
) else if "%CHOICE%"=="3" (
    :: Keyword = keyword only (no vector)
    set CONTEXT_BRIDGE_CONFIG=config.json
    set CB_VECTOR_INDEX=
    set CB_VECTOR_META=
    set MODE=Keyword
)

:: Read profile from config.hybrid.json — falls back to "default" if config not found
for /f "delims=" %%p in ('%PYTHON% -c "import json,sys; c=json.load(open(r'%CB_ROOT%\config.hybrid.json')); print(c.get('runtime',{}).get('project_profile','default'))" 2^>nul') do set CONTEXT_BRIDGE_PROFILE=%%p
if not defined CONTEXT_BRIDGE_PROFILE set CONTEXT_BRIDGE_PROFILE=default
set CONTEXT_BRIDGE_TRANSPORT=sse
set CONTEXT_BRIDGE_PORT=%PORT%

:: Required for Anthropic analysis provider — set your key here or in Windows system env vars
if not defined ANTHROPIC_API_KEY set ANTHROPIC_API_KEY=YOUR_API_KEY_HERE

:: Build the MCP server env block — only include vector paths when non-empty
set _MCP_ENV=set CONTEXT_BRIDGE_CONFIG=%CONTEXT_BRIDGE_CONFIG% ^&^& set CONTEXT_BRIDGE_PROFILE=%CONTEXT_BRIDGE_PROFILE% ^&^& set CONTEXT_BRIDGE_TRANSPORT=sse ^&^& set CONTEXT_BRIDGE_PORT=%PORT% ^&^& set ANTHROPIC_API_KEY=%ANTHROPIC_API_KEY%
if defined CB_VECTOR_INDEX (
    set _MCP_ENV=%_MCP_ENV% ^&^& set CONTEXT_BRIDGE_VECTOR_INDEX=%CB_VECTOR_INDEX%
)
if defined CB_VECTOR_META (
    set _MCP_ENV=%_MCP_ENV% ^&^& set CONTEXT_BRIDGE_VECTOR_META=%CB_VECTOR_META%
)

echo.
echo Starting ContextBridge [%MODE%] on http://127.0.0.1:%PORT%/sse ...
start "ContextBridge MCP [%MODE%]" cmd /k "cd /d %ROOT%\context_bridge && %_MCP_ENV% && %PYTHON% %ROOT%\context_bridge\mcp_server_hybrid.py"

echo Starting dashboard on http://127.0.0.1:8795 ...
start "ContextBridge Dashboard" cmd /k "set CONTEXT_BRIDGE_CONFIG=%CONTEXT_BRIDGE_CONFIG% && set CONTEXT_BRIDGE_PROFILE=%CONTEXT_BRIDGE_PROFILE% && set CONTEXT_BRIDGE_PORT=%PORT% && %PYTHON% %ROOT%\context_bridge\dashboard_server.py"

timeout /t 2 /nobreak >nul
start "" http://127.0.0.1:8795

echo.
echo Both servers started.
echo   MCP server : http://127.0.0.1:%PORT%/sse
echo   Dashboard  : http://127.0.0.1:8795
echo.
