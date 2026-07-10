@echo off
setlocal enabledelayedexpansion

:: --------------------------------------------------------------------
:: Bulletproof "stay open" guard: if this .bat was double-clicked,
:: Explorer launches it as "cmd /c script.bat", and that cmd window
:: closes the INSTANT the script ends OR hits a fatal parse error --
:: even before a later `pause` line is reached. Relaunch ourselves once
:: inside "cmd /k" so the window survives no matter what happens below.
:: --------------------------------------------------------------------
if "%~1"=="_RELAUNCHED" goto :AFTER_RELAUNCH_GUARD
start "ContextBridge Cache Cleanup" cmd /k call "%~f0" _RELAUNCHED
exit /b 0
:AFTER_RELAUNCH_GUARD

:: Same cleanup as clean_cache.bat, but REFUSES to run while CB is still
:: LISTENING on its ports (8755 = MCP SSE server, 8795 = dashboard).
:: Deleting cache.db/etc. out from under a live process can corrupt the
:: SQLite cache file or leave the running server's in-memory state out of
:: sync with what's on disk, so always stop CB first.
::
:: NOTE: only "LISTENING" rows count as running. A stopped process can
:: leave TIME_WAIT rows on the same port for a minute or two -- those are
:: NOT a live listener and must not block cleanup.

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
echo Checking whether ContextBridge is still running...
echo.

:: Dump netstat once to a temp file, then filter with two separate plain
:: findstr calls. Avoids fragile nested-quote/pipe escaping inside a
:: single for /f command substitution, which is the most likely cause
:: of a silent parse failure closing the window before any pause.
set "_NETSTAT_TMP=%TEMP%\cb_netstat_check_%RANDOM%.tmp"
netstat -ano > "%_NETSTAT_TMP%" 2>nul

set "CB_RUNNING=0"

findstr /c:"LISTENING" "%_NETSTAT_TMP%" | findstr /c:":8755 " >nul 2>&1
if not errorlevel 1 set "CB_RUNNING=1"

findstr /c:"LISTENING" "%_NETSTAT_TMP%" | findstr /c:":8795 " >nul 2>&1
if not errorlevel 1 set "CB_RUNNING=1"

if "!CB_RUNNING!"=="1" (
    echo   [BLOCKED] ContextBridge is still LISTENING on port 8755 and/or 8795.
    echo.
    echo   Matching netstat line^(s^):
    findstr /c:"LISTENING" "%_NETSTAT_TMP%" | findstr /c:":8755 " 2>nul
    findstr /c:"LISTENING" "%_NETSTAT_TMP%" | findstr /c:":8795 " 2>nul
    echo.
    echo   Deleting cache files while the server is live can corrupt the
    echo   analysis cache.db ^(WAL/SHM files^) and leave the running process's
    echo   in-memory state out of sync with disk.
    echo.
    echo   Stop CB first, e.g. run: stop_mcp_servers.bat
    echo   Then run this script again.
    echo.
    del /q "%_NETSTAT_TMP%" >nul 2>&1
    echo Press any key to close this window . . .
    pause >nul
    exit /b 1
)

del /q "%_NETSTAT_TMP%" >nul 2>&1

echo   [OK] No LISTENING process found on port 8755 or 8795. Safe to clean.
echo.
echo Cleaning ContextBridge cache...
echo.

set /a CLEARED_COUNT=0
set /a SKIPPED_COUNT=0
set /a ERROR_COUNT=0

:: Python bytecode cache — covers src/, rules/projects/, mcp_tools/, rag/, analysis/
set /a PYCACHE_FOUND=0
for /d /r "%CB_ROOT%" %%d in (__pycache__) do (
    if exist "%%d" (
        rd /s /q "%%d" 2>nul
        if exist "%%d" (
            echo   [ERROR] could not delete %%d ^(in use or permission denied^)
            set /a ERROR_COUNT+=1
        ) else (
            echo   [CLEARED] %%d
            set /a CLEARED_COUNT+=1
        )
        set /a PYCACHE_FOUND+=1
    )
)
if !PYCACHE_FOUND! EQU 0 (
    echo   [SKIPPED] __pycache__ folders - none found under %CB_ROOT%
    set /a SKIPPED_COUNT+=1
)

:: LLM prompt/output cache (last_qwen_*.json)
call :DELETE_FILE "%CB_ROOT%\usage\last_qwen_prompt.json" "usage\last_qwen_prompt.json"
call :DELETE_FILE "%CB_ROOT%\usage\last_qwen_output.json" "usage\last_qwen_output.json"

:: Analysis-stage response cache (SQLite) — safe to delete outright now
:: since we already confirmed no process has it open.
call :DELETE_FILE "%CB_ROOT%\cache\analysis\cache.db" "cache\analysis\cache.db"
call :DELETE_FILE "%CB_ROOT%\cache\analysis\cache.db-shm" "cache\analysis\cache.db-shm"
call :DELETE_FILE "%CB_ROOT%\cache\analysis\cache.db-wal" "cache\analysis\cache.db-wal"

:: Ranking-profile cache sentinel (rag/rules_loader.py _rules_cache TTL bump)
if exist "%CB_ROOT%\usage\rules_cache_reset.sentinel" (
    python -c "import time,pathlib; pathlib.Path(r'%CB_ROOT%\usage\rules_cache_reset.sentinel').write_text(str(time.time()))" 2>nul
    