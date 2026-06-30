@echo off
echo Stopping ContextBridge servers...

for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8755"') do (
    taskkill /PID %%a /F >nul 2>&1
)

for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8795"') do (
    taskkill /PID %%a /F >nul 2>&1
)

echo Done. Ports 8755 and 8795 are now free.
timeout /t 2 /nobreak >nul
