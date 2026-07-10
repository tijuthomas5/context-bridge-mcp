@echo off
setlocal enabledelayedexpansion
:: Locate CB root dynamically — works regardless of where this script is placed
set "_S=%~dp0"
:_FIND_CB
if exist "%_S%mcp_server_hybrid.py" goto _CB_FOUND
for %%P in ("%_S%..") do set "_N=%%~fP\"
if /i "%_N%"=="%_S%" ( echo ERROR: Cannot find ContextBridge root & pause & exit /b 1 )
set "_S=%_N%" & goto _FIND_CB
:_CB_FOUND
set "CB_ROOT=%_S:~0,-1%"

set /a CLEARED_COUNT=0
set /a SKIPPED_COUNT=0

echo.
echo Cleaning ContextBridge cache...
echo.

:: Python bytecode cache — covers src/, rules/projects/, mcp_tools/, rag/, analysis/
set /a PYCACHE_FOUND=0
for /d /r "%CB_ROOT%" %%d in (__pycache__) do (
    if exist "%%d" (
        echo   [CLEARED] %%d
        rd /s /q "%%d"
        set /a PYCACHE_FOUND+=1
        set /a CLEARED_COUNT+=1
    )
)
if !PYCACHE_FOUND! EQU 0 (
    echo   [SKIPPED] __pycache__ folders - none found under %CB_ROOT%
    set /a SKIPPED_COUNT+=1
)

:: LLM prompt/output cache (last_qwen_*.json)
if exist "%CB_ROOT%\usage\last_qwen_prompt.json" (
    echo   [CLEARED] usage\last_qwen_prompt.json
    del /q "%CB_ROOT%\usage\last_qwen_prompt.json"
    set /a CLEARED_COUNT+=1
) else (
    echo   [SKIPPED] usage\last_qwen_prompt.json - file does not exist
    set /a SKIPPED_COUNT+=1
)
if exist "%CB_ROOT%\usage\last_qwen_output.json" (
    echo   [CLEARED] usage\last_qwen_output.json
    del /q "%CB_ROOT%\usage\last_qwen_output.json"
    set /a CLEARED_COUNT+=1
) else (
    echo   [SKIPPED] usage\last_qwen_output.json - file does not exist
    set /a SKIPPED_COUNT+=1
)

:: Analysis-stage response cache (SQLite) — stores cached analysis output per
:: query. A stale entry here can keep replaying an old answer even after
:: reindexing and clearing __pycache__.
if exist "%CB_ROOT%\cache\analysis\cache.db" (
    echo   [CLEARED] cache\analysis\cache.db
    del /q "%CB_ROOT%\cache\analysis\cache.db"
    set /a CLEARED_COUNT+=1
) else (
    echo   [SKIPPED] cache\analysis\cache.db - file does not exist
    set /a SKIPPED_COUNT+=1
)
if exist "%CB_ROOT%\cache\analysis\cache.db-shm" (
    echo   [CLEARED] cache\analysis\cache.db-shm
    del /q "%CB_ROOT%\cache\analysis\cache.db-shm"
    set /a CLEARED_COUNT+=1
) else (
    echo   [SKIPPED] cache\analysis\cache.db-shm - file does not exist
    set /a SKIPPED_COUNT+=1
)
if exist "%CB_ROOT%\cache\analysis\cache.db-wal" (
    echo   [CLEARED] cache\analysis\cache.db-wal
    del /q "%CB_ROOT%\cache\analysis\cache.db-wal"
    set /a CLEARED_COUNT+=1
) else (
    echo   [SKIPPED] cache\analysis\cache.db-wal - file does not exist
    set /a SKIPPED_COUNT+=1
)

:: Ranking-profile cache (rag/rules_loader.py _rules_cache, in-memory, 5-min
:: TTL). It only self-invalidates early if this sentinel's mtime is newer than
:: the cached entry, so bump it here instead of waiting out the TTL.
if exist "%CB_ROOT%\usage\rules_cache_reset.sentinel" (
    python -c "import time,pathlib; pathlib.Path(r'%CB_ROOT%\usage\rules_cache_reset.sentinel').write_text(str(time.time()))" 2>nul
    if !errorlevel! EQU 0 (
        echo   [CLEARED] usage\rules_cache_reset.sentinel - timestamp reset to now
        set /a CLEARED_COUNT+=1
    ) else (
        echo   [SKIPPED] usage\rules_cache_reset.sentinel - found but could not reset ^(python not on PATH?^)
        set /a SKIPPED_COUNT+=1
    )
) else (
    echo   [SKIPPED] usage\rules_cache_reset.sentinel - file does not exist
    set /a SKIPPED_COUNT+=1
)

echo.
echo Summary: !CLEARED_COUNT! item(s) cleared, !SKIPPED_COUNT! item(s) skipped ^(not found^).
echo.
echo Not touched by this script ^(in-memory only, cleared by restart, not by files^):
echo   - search.py _PROFILE_CACHE (project ranking profile)
echo   - hybrid_tools.py _load_runtime_config cache (runtime config)
echo Not touched by this script (not cache - left alone on purpose):
echo   - data\context_index.json and context_index_old.json
echo   - data\vector_*.jsonl / vector_meta*.json
echo.
echo Done. Restart CB now for the in-memory caches above to clear too.
echo.
pause
