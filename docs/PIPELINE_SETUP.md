# ContextBridge — Pipeline Setup

## What the pipeline is

ContextBridge has two stages. Both run inside the ContextBridge server — not inside your AI coding tool.

```
User prompt
    │
    ▼
[Stage 1 — Retrieval]
  Keyword + vector search against the indexed codebase (always runs)
    │
    ▼
[Stage 2 — Analysis]   ← this is the pipeline
  A local AI model reads the retrieval results and produces:
  ranked files, extracted symbols, dependency map, risks, code block recommendations
    │
    ▼
Compressed result (~4-8 KB) sent back to your AI coding tool
```

The AI coding tool (Claude, Codex, Antigravity etc.) receives the final result and implements. It does not run retrieval or analysis — that is all done inside ContextBridge before the result reaches it.

---

## Prerequisites

### 1. Install Ollama

Download from https://ollama.com and install. Ollama is a local model runner — it keeps all inference on your machine.

Verify it is running:
```powershell
Get-Process ollama -ErrorAction SilentlyContinue
```

If not running, start it:
```powershell
ollama serve
```

### 2. Pull a model

The default model is `qwen2.5-coder:7b`:
```powershell
ollama pull qwen2.5-coder:7b
```

Same pattern for any model:
```powershell
ollama pull <model-name>
```

Check what models you have:
```powershell
ollama list
```

### 3. Load your model into memory

Ollama loads a model on the first request — meaning the first ContextBridge call will be slow while the model warms up. To pre-load it before use:

```powershell
ollama run qwen2.5-coder:7b
```

Once the prompt appears, type `/bye` to exit. The model stays loaded in memory and all subsequent ContextBridge calls will be fast.

Same pattern for any model:
```powershell
ollama run <model-name>
```

### Startup order

1. `start_ollama.bat` — starts Ollama and warms up the model (run once when machine starts)
2. start ContextBridge + dashboard (OS-specific):
   - **Windows:** `setup\windows\1.  start_Context_Bridge.bat`
   - **Mac:** `setup/mac/1. start_Context_Bridge.sh`
   - **Linux:** `setup/linux/1. start_Context_Bridge.sh`

---

## Configuration

The pipeline block lives inside each mode's config file:

| Mode | Config file |
|---|---|
| Hybrid (default) | `context_bridge/config.hybrid.json` |
| Semantic | `context_bridge/config.semantic.json` |
| Keyword | `context_bridge/config.json` |

### Full pipeline block

```json
"pipeline": {
  "analysis_stage": {
    "enabled": true,
    "auto_analyze": true,
    "auto_analyze_timeout_seconds": 60,
    "provider": "ollama",
    "model": "qwen2.5-coder:7b",
    "endpoint": "http://localhost:11434/api/generate",
    "timeout_seconds": 120,
    "temperature": 0.1
  }
}
```

### What each field does

| Field | What it controls |
|---|---|
| `enabled` | Master switch — `false` disables the pipeline entirely |
| `auto_analyze` | Run analysis automatically on every `search_context_hybrid()` call |
| `auto_analyze_timeout_seconds` | How long to wait for analysis before giving up and returning retrieval-only result |
| `provider` | Model runner — currently only `ollama` is supported |
| `model` | The model Ollama will use for analysis |
| `endpoint` | Ollama API endpoint — leave as default unless you changed Ollama's port |
| `timeout_seconds` | Hard timeout for the Ollama API call |
| `temperature` | Lower = more deterministic output. Keep at 0.1 for code analysis |

---

## Swapping the model

You can use any model available in Ollama. Change the `"model"` field in the config:

```json
"model": "codellama:7b"
```

or

```json
"model": "deepseek-coder:6.7b"
```

Pull the model first with `ollama pull <model-name>`, then restart the ContextBridge server for the change to take effect.

**Recommended models for code analysis:**

| Model | Size | Good for |
|---|---|---|
| `qwen2.5-coder:7b` | ~4 GB | Default — best balance of speed and quality |
| `qwen2.5-coder:14b` | ~8 GB | Better quality, slower |
| `deepseek-coder:6.7b` | ~4 GB | Alternative if Qwen is slow on your machine |
| `codellama:7b` | ~4 GB | Fallback option |

---

## Enabling and disabling

### Disable analysis (retrieval only, faster)
```json
"auto_analyze": false
```
ContextBridge still runs retrieval and returns results — just without the ranked/analysed output.

### Disable pipeline entirely
```json
"enabled": false
```

### Re-enable
Set both back to `true` and restart the server.

> Changes to config files take effect on next server start. Restart via your OS stop/start scripts in `setup/windows|mac|linux/`.

---

## What the analysis result contains

When analysis runs, the `search_context_hybrid()` response includes an `analysis` block:

```json
"analysis": {
  "summary": "2-3 sentence plain-English overview with exact method and file names",
  "ranked_files": [
    { "file": "...", "role": "owner", "symbols": [...], "reason": "..." }
  ],
  "selected_symbols": [
    { "symbol": "MethodName", "file": "...", "reason": "..." }
  ],
  "dependencies": [
    { "from": "FileA", "to": "FileB", "type": "calls" }
  ],
  "risks": [
    { "description": "...", "severity": "medium", "file": "..." }
  ],
  "recommended_code_blocks": [
    { "file": "...", "symbol": "...", "reason": "..." }
  ]
}
```

---

## Troubleshooting

### Analysis field is missing or empty

1. Check `auto_analyze: true` and `enabled: true` in the active config
2. Check Ollama is running:
   ```powershell
   Get-Process ollama -ErrorAction SilentlyContinue
   ```
3. Start Ollama if needed:
   ```powershell
   ollama serve
   ```
4. Check the model is pulled:
   ```powershell
   ollama list
   ```
5. Restart the ContextBridge server after any config change

### Analysis times out

Increase `auto_analyze_timeout_seconds` (default 60) and `timeout_seconds` (default 120) in config. On first run after a cold start, Ollama loads the model into memory which takes longer.

### summary field is empty

Restart the server — this was a bug in `analysis/stage.py` (summary was parsed but not included in the return value). Fixed. Restart using your OS stop/start scripts in `setup/windows|mac|linux/` to pick up the fix.

### Want to test analysis manually

Use `analyze_context` as a debug tool to re-run analysis for a specific event without re-running retrieval:

```
analyze_context(query="...", event_id="<event_id from a previous search_context_hybrid call>")
```

The `event_id` is in every `search_context_hybrid` response. Retrieval results are cached server-side for 10 minutes.
