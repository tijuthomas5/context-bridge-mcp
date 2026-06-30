# Quick MCP Setup

## Architecture (SSE Single-Server)

One server process, all AI clients share it via HTTP.

```
start_mcp_server.ps1
       ↓
mcp_server_hybrid.py  (port 8755, SSE transport)
       ↓
http://127.0.0.1:8755/sse/   ← all clients connect here
```

No more per-client spawning. One process, any number of tools (Claude Code, Cursor, Codex, Gemini, etc.) connect to the same URL.

---

## Step 1 — Start the Server

Run once from PowerShell (keep this window open):

```powershell
context_bridge\start_mcp_server.ps1
```

You will be prompted to pick a mode:

```
Select ContextBridge mode:
  1. Hybrid   (keyword + vector)  [recommended]
  2. Semantic (vector only)
  3. Keyword  (keyword only)

Enter 1, 2 or 3 (default: 1):
```

The server starts on `http://127.0.0.1:8755/sse/`. Keep the terminal open — Ctrl+C stops it.

### Mode guide

| Mode | Best for |
|---|---|
| Hybrid | Default — exact names + meaning, best overall |
| Semantic | Vague/workflow questions ("how does X work") |
| Keyword | Exact symbol names, fast lookups |

---

## Step 2 — Connect Your AI Tool

### Claude Code (VSCode Extension)

Edit `C:\Users\<YourUser>\.claude\claude.json` and add:

```json
{
  "mcpServers": {
    "context_bridge": {
      "url": "http://127.0.0.1:8755/sse/"
    }
  }
}
```

> Remove any old `"command"/"args"` entry for context_bridge — those spawn a separate process (stdio). Use `"url"` only.

Restart the Claude Code session after editing.

### Codex

```toml
[mcp_servers.context_bridge]
url = "http://127.0.0.1:8755/sse/"
startup_timeout_sec = 10
```

### Cursor / other tools

Add an MCP server entry pointing to `http://127.0.0.1:8755/sse/`. Exact config location varies per tool — look for "MCP servers" in settings.

---

## Step 3 — Use the Tool

Only one tool call needed:

```
search_context_hybrid("your question here")
```

That call does everything:
1. Hybrid retrieval (keyword + vector)
2. Qwen analysis (automatic — no second call needed)
3. Returns slim response + embedded `analysis` block

### What comes back

```json
{
  "event_id": "...",
  "confidence": 0.91,
  "primary_owner": "OrderFormsService",
  "facts": ["..."],
  "modules": ["orders", "checkout"],
  "packs": ["orders-backend"],
  "analysis": {
    "summary": "2-3 sentence plain-English overview with exact method/file names",
    "ranked_files": [...],
    "selected_symbols": [...],
    "dependencies": [...],
    "risks": [...],
    "recommended_code_blocks": [...]
  }
}
```

Response size: ~4-8 KB (was 118 KB before — 96% reduction).

---

## Pipeline (Analysis Stage)

Analysis runs automatically inside `search_context_hybrid()` when `auto_analyze: true` in config. It uses a local AI model via Ollama — runs on your machine, no external API calls.

Full pipeline setup, model swapping, and troubleshooting: [PIPELINE_SETUP.md](./PIPELINE_SETUP.md)

---

## Prompt Guidance

All three modes use the same tool name. Do **not** call `analyze_context` manually — it runs automatically.

```
Use search_context_hybrid() to find context for this task.
```

---

## Important Notes

- **Keep the server terminal open** — Ctrl+C stops the server and disconnects all clients
- **One mode per session** — to switch modes, stop the server, re-run `start_mcp_server.ps1`, pick a new mode, then start a new chat
- **No per-client setup needed** — any tool that supports MCP over SSE connects with just the URL
- **Auto-start on login** — set up Windows Task Scheduler to run `start_mcp_server.ps1` at login so you don't need to start it manually each time

---

## Troubleshooting

| Problem | Fix |
|---|---|
| Port 8755 already in use | Run: `Stop-Process -Id (Get-NetTCPConnection -LocalPort 8755).OwningProcess -Force` |
| Multiple server processes running | Kill all, restart via `start_mcp_server.ps1` — only one should run |
| `analysis` field missing from response | Check `config.hybrid.json` has `pipeline.analysis_stage.enabled: true` and `auto_analyze: true` |
| Qwen timeout | Increase `auto_analyze_timeout_seconds` in config (default 60s) |
| `url` key not supported in claude.json | Update Claude Code — older versions only support stdio. Use `.mcp.json` in project root instead (see below) |

### Fallback: `.mcp.json` in project root (Claude Code only)

If `claude.json` SSE doesn't work, create `.mcp.json` in the project root:

```json
{
  "mcpServers": {
    "context_bridge": {
      "url": "http://127.0.0.1:8755/sse/"
    }
  }
}
```

Full guide: [HOW_TO_SETUP_MCP.md](./HOW_TO_SETUP_MCP.md)

---

## Antigravity (Gemini) Setup

Antigravity stores its MCP config in a separate file from `GEMINI.md`.

### Config file location

```
C:\Users\<YourUser>\.gemini\config\mcp_config.json
```

### Add ContextBridge

Create or edit that file:

```json
{
  "mcpServers": {
    "context_bridge": {
      "url": "http://127.0.0.1:8755/sse/"
    }
  }
}
```

Restart the Antigravity session after saving.

### Tool cache (important)

Antigravity caches tool schemas in:

```
C:\Users\<YourUser>\.gemini\antigravity\mcp\
```

If you see stale tools or connection errors after a config change, delete any subfolders that don't match your current server name:

```powershell
# List what's there
Get-ChildItem "C:\Users\<YourUser>\.gemini\antigravity\mcp"

# Delete stale folders (keep only context_bridge_hybrid if using Hybrid mode)
Remove-Item -Recurse -Force "C:\Users\<YourUser>\.gemini\antigravity\mcp\context_bridge_normal"
Remove-Item -Recurse -Force "C:\Users\<YourUser>\.gemini\antigravity\mcp\context_bridge_semantic"
```

Then restart the Antigravity session.

---

### If the port changes

If you run `change_port.bat` to switch ports, it updates `mcp_config.json` automatically. But you must also:

1. Delete all Antigravity tool cache folders so it re-fetches schemas on the new port:
   ```powershell
   Remove-Item -Recurse -Force "C:\Users\<YourUser>\.gemini\antigravity\mcp\context_bridge_hybrid" -ErrorAction SilentlyContinue
   Remove-Item -Recurse -Force "C:\Users\<YourUser>\.gemini\antigravity\mcp\context_bridge_normal" -ErrorAction SilentlyContinue
   Remove-Item -Recurse -Force "C:\Users\<YourUser>\.gemini\antigravity\mcp\context_bridge_semantic" -ErrorAction SilentlyContinue
   ```
2. Restart the Antigravity session.

> `change_port.bat` handles the file update. The cache delete and session restart are manual steps.
