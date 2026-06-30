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

echo.
echo Cleaning ContextBridge cache...
echo.

:: Python bytecode cache — covers src/, rules/projects/, mcp_tools/, rag/, analysis/
for /d /r "%CB_ROOT%" %%d in (__pycache__) do (
    if exist "%%d" (
        echo   Removing: %%d
        rd /s /q "%%d"
    )
)

:: LLM prompt/output cache (last_qwen_*.json)
if exist "%CB_ROOT%\usage\last_qwen_prompt.json" (
    echo   Removing: usage\last_qwen_prompt.json
    del /q "%CB_ROOT%\usage\last_qwen_prompt.json"
)
if exist "%CB_ROOT%\usage\last_qwen_output.json" (
    echo   Removing: usage\last_qwen_output.json
    del /q "%CB_ROOT%\usage\last_qwen_output.json"
)

echo.
echo Done. Restart CB now.
echo.
pause
