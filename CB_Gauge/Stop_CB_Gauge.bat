@echo off
title CB Gauge - Cleanup
echo ====================================================
echo Shutting down orphaned CB Gauge servers...
echo ====================================================

echo Killing server on old port 8080...
FOR /F "tokens=5" %%T IN ('netstat -a -n -o ^| findstr "0.0.0.0:8080 127.0.0.1:8080"') DO (
    TaskKill.exe /PID %%T /F >nul 2>&1
)

echo Killing server on new port 9856...
FOR /F "tokens=5" %%T IN ('netstat -a -n -o ^| findstr "0.0.0.0:9856 127.0.0.1:9856"') DO (
    TaskKill.exe /PID %%T /F >nul 2>&1
)

echo.
echo ----------------------------------------------------
echo Successfully closed orphaned servers!
echo ----------------------------------------------------
echo This window will close automatically in 5 seconds...

timeout /t 5 /nobreak > nul
exit
