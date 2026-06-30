@echo off
echo =============================================
echo  Stopping Ollama
echo =============================================
echo.

:: Check if Ollama is running at all
netstat -ano | findstr ":11434" | findstr "LISTENING" >nul 2>&1
if %errorlevel% neq 0 (
    echo Ollama is not running on port 11434.
    goto :done
)

:: Write temp PowerShell script to unload models from VRAM
set "PS_TMP=%TEMP%\cb_stop_ollama.ps1"

echo try { > "%PS_TMP%"
echo     $ps = Invoke-RestMethod -Uri 'http://localhost:11434/api/ps' -TimeoutSec 3 >> "%PS_TMP%"
echo     if ($ps.models -and $ps.models.Count -gt 0) { >> "%PS_TMP%"
echo         foreach ($m in $ps.models) { >> "%PS_TMP%"
echo             Write-Host ("  Unloading: " + $m.name) >> "%PS_TMP%"
echo             $b = [Text.Encoding]::UTF8.GetBytes('{"model":"' + $m.name + '","keep_alive":0}') >> "%PS_TMP%"
echo             $r = [Net.HttpWebRequest]::Create('http://localhost:11434/api/generate') >> "%PS_TMP%"
echo             $r.Method = 'POST'; $r.ContentType = 'application/json'; $r.Timeout = 10000 >> "%PS_TMP%"
echo             $s = $r.GetRequestStream(); $s.Write($b,0,$b.Length); $s.Close() >> "%PS_TMP%"
echo             try { $r.GetResponse().Close() } catch {} >> "%PS_TMP%"
echo         } >> "%PS_TMP%"
echo     } else { Write-Host "  No models loaded in VRAM." } >> "%PS_TMP%"
echo } catch { Write-Host ("  API error: " + $_.Exception.Message) } >> "%PS_TMP%"

echo Unloading models from VRAM...
powershell -ExecutionPolicy Bypass -File "%PS_TMP%"
del "%PS_TMP%" >nul 2>&1

echo.
echo Killing Ollama tray app first (prevents auto-restart)...
taskkill /F /FI "IMAGENAME eq ollama app.exe" >nul 2>&1
taskkill /F /FI "IMAGENAME eq OllamaSetup.exe" >nul 2>&1

echo Killing Ollama server...
taskkill /F /IM ollama.exe

:: Wait a moment then check if tray app restarted it
timeout /t 3 /nobreak >nul

:: Kill again in case tray app restarted it during the wait
taskkill /F /FI "IMAGENAME eq ollama app.exe" >nul 2>&1
taskkill /F /IM ollama.exe >nul 2>&1

:: Kill by PID on port 11434 as final fallback
echo.
echo Checking port 11434...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":11434" ^| findstr "LISTENING"') do (
    echo   Force killing PID %%a on port 11434
    taskkill /PID %%a /F
)

timeout /t 2 /nobreak >nul

echo.
echo All running Ollama-related processes:
tasklist | findstr /I "ollama"

echo.
netstat -ano | findstr ":11434" | findstr "LISTENING" >nul 2>&1
if %errorlevel% neq 0 (
    echo SUCCESS: Ollama stopped. VRAM released.
) else (
    echo WARNING: Port 11434 still in use.
    echo The Ollama Windows service may be running. Try:
    echo   sc stop ollama
    echo   sc query ollama
    netstat -ano | findstr ":11434"
)

:done
echo.
echo =============================================
pause
