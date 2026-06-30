# ContextBridge — Debug Commands

## Check Running Servers

Get-NetTCPConnection -ErrorAction SilentlyContinue | Where-Object { $_.LocalPort -in 8755,8795 -and $_.State -eq 'Listen' } | Select-Object LocalPort, State, OwningProcess, @{N='Process';E={(Get-Process -Id $_.OwningProcess).Name}}


### Is the MCP server running?
```powershell
Get-NetTCPConnection -LocalPort 8755 -ErrorAction SilentlyContinue
```

### Is the dashboard running?
```powershell
Get-NetTCPConnection -LocalPort 8795 -ErrorAction SilentlyContinue
```

### Check all Python processes
```powershell
Get-Process python | Select-Object Id, CPU, StartTime, MainWindowTitle
```

### Which process is on a specific port?
```powershell
Get-NetTCPConnection -LocalPort 8755 | Select-Object LocalPort, OwningProcess
```

### See full command line of each Python process (shows which script is running)
```powershell
Get-WmiObject Win32_Process | Where-Object { $_.Name -like "*python*" } | Select-Object ProcessId, CommandLine
```

---

## Stop a Process

### Stop by port (clean way)
```powershell
Stop-Process -Id (Get-NetTCPConnection -LocalPort 8755).OwningProcess -Force
```

### Stop dashboard by port
```powershell
Stop-Process -Id (Get-NetTCPConnection -LocalPort 8795).OwningProcess -Force
```

### Stop by process ID
```powershell
Stop-Process -Id <PID> -Force
```

### Kill ALL Python processes (nuclear option)
```powershell
Get-Process python | Stop-Process -Force
```

---

## Check Server Health

### Ping the MCP server (is it accepting connections?)
```powershell
Invoke-WebRequest -Uri "http://127.0.0.1:8755/sse/" -Method Get -TimeoutSec 3 -ErrorAction SilentlyContinue | Select-Object StatusCode
```

### Ping the dashboard
```powershell
Invoke-WebRequest -Uri "http://127.0.0.1:8795" -TimeoutSec 3 -ErrorAction SilentlyContinue | Select-Object StatusCode
```

---

## Restart Everything Clean

```powershell
# 1. Kill MCP server
Stop-Process -Id (Get-NetTCPConnection -LocalPort 8755 -ErrorAction SilentlyContinue).OwningProcess -Force -ErrorAction SilentlyContinue

# 2. Kill dashboard
Stop-Process -Id (Get-NetTCPConnection -LocalPort 8795 -ErrorAction SilentlyContinue).OwningProcess -Force -ErrorAction SilentlyContinue

# 3. Start fresh (use your OS-specific script)
# Windows:  context_bridge\setup\windows\1.  start_Context_Bridge.bat
# Mac:      context_bridge/setup/mac/1. start_Context_Bridge.sh
# Linux:    context_bridge/setup/linux/1. start_Context_Bridge.sh
```

---

## Logs & Usage

### View live usage log (last 50 events)
```powershell
Get-Content "context_bridge\usage\events.jsonl" -Tail 50
```

### View outcome log
```powershell
Get-Content "context_bridge\usage\outcomes.jsonl" -Tail 20
```

### Watch logs live (streaming)
```powershell
Get-Content "context_bridge\usage\events.jsonl" -Wait -Tail 10
```

### Count total events
```powershell
(Get-Content "context_bridge\usage\events.jsonl" | Measure-Object -Line).Lines
```

---

## Port Reference

| Port | Service |
|---|---|
| 8755 | ContextBridge MCP server (SSE) |
| 8795 | ContextBridge dashboard |

---

## Common Problems

### Port already in use
```powershell
# Find what's using it
Get-NetTCPConnection -LocalPort 8755 | Select-Object LocalPort, State, OwningProcess
Get-Process -Id <OwningProcess>

# Kill it
Stop-Process -Id <OwningProcess> -Force
```

### Multiple Python processes running
```powershell
# See all of them
Get-WmiObject Win32_Process | Where-Object { $_.Name -like "*python*" } | Select-Object ProcessId, CommandLine

# Kill all (then restart via your OS-specific start script in setup/)
Get-Process python | Stop-Process -Force
```

### MCP server started but tools not showing in AI tool
- Check the server is actually on port 8755: `Get-NetTCPConnection -LocalPort 8755`
- Restart the AI tool session (Claude Code, Codex, Antigravity)
- Verify client config points to `http://127.0.0.1:8755/sse/`

### Qwen analysis not running (analysis field missing)
- Check config has `pipeline.analysis_stage.enabled: true` and `auto_analyze: true`
- Check Ollama is running: `Get-Process ollama -ErrorAction SilentlyContinue`
- Start Ollama if needed: `ollama serve`
- Check model is pulled: `ollama list`

---

## Ollama & Pipeline Debug

### Is Ollama running?
```powershell
Get-Process ollama -ErrorAction SilentlyContinue
```

### What models are pulled?
```powershell
ollama list
```

### Is Ollama API responding?
```powershell
Invoke-WebRequest -Uri "http://localhost:11434" -TimeoutSec 3 | Select-Object StatusCode
```

### Which models are currently loaded in memory?
```powershell
Invoke-RestMethod -Uri "http://localhost:11434/api/ps"
```

### Warm up a model manually
```powershell
ollama run qwen2.5-coder:7b /bye
```

### Stop Ollama (also unloads all models)
```powershell
taskkill /IM ollama.exe /F
```

### Port reference (Ollama)
| Port | Service |
|---|---|
| 11434 | Ollama API |
