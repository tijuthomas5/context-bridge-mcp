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
echo.
echo ContextBridge setup started...
echo Workspace: %CD%
echo Please wait. Index and semantic build steps can take a few minutes.
echo Do not close this window unless you see a failure message.
echo.
python context_bridge\scripts\setup_context_bridge.py %*
set "EXITCODE=%ERRORLEVEL%"
echo.
if "%EXITCODE%"=="0" (
  echo ContextBridge setup completed successfully.
) else (
  echo ContextBridge setup failed with exit code %EXITCODE%.
)
echo.
pause
exit /b %EXITCODE%
