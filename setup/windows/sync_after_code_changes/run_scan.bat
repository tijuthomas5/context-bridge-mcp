@echo off
setlocal

set SCRIPT_DIR=%~dp0
set PROJECT_ROOT=%SCRIPT_DIR%..\..\..\..
pushd "%PROJECT_ROOT%"

echo == ContextBridge: Repo Scan ==
echo.
echo What do you want to do?
echo   1. Scan and report only (nothing changes on disk)
echo   2. Scan, then rebuild stale packs
echo.
set /p CHOICE=Enter 1 or 2:

if "%CHOICE%"=="1" (
    set ARGS=
) else if "%CHOICE%"=="2" (
    set ARGS=--rebuild
) else (
    echo Invalid choice. Please run again and enter 1 or 2.
    pause >nul
    exit /b 1
)

echo.
echo Running...
echo.

python context_bridge\setup\windows\sync_after_code_changes\scan_repo.py %ARGS%

set EXITCODE=%ERRORLEVEL%
popd

echo.
if "%EXITCODE%"=="0" (
    echo == Done. Exit code 0 ==
) else (
    echo == Finished with errors. Exit code %EXITCODE% ==
)
echo Close this window when you're done reviewing the output above.
pause >nul
exit /b %EXITCODE%
