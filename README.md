# ContextBridge

> **💡 New here?** Don't want to read everything? Ask your AI assistant (Claude, ChatGPT, Gemini, etc.) to read the [`docs/`](docs/0.%20README.md) folder and guide you through setup for your OS and project.

A local-first code retrieval layer for AI coding agents. ContextBridge indexes your
codebase (via [Graphify](#indexing) output), then exposes MCP tools that any AI client
(Claude Code, Codex, Cursor, Antigravity, …) can call to get **ranked files, symbols,
and dependency chains** — optionally validated and re-ranked by a local LLM before the
answer reaches your cloud AI.

```
Your prompt ─► ContextBridge (keyword + vector retrieval)
            ─► Local AI (optional: validates, re-ranks, fills gaps)
            ─► Your AI agent (implements, grounded in real files)
```

The engine is **generic**. All project-specific ranking lives in a swappable
**profile plugin**, so the same tool works for any codebase.

---

> **📖 Before you start — read the docs.**
> The [`docs/`](docs/0.%20README.md) folder contains everything you need for full setup, configuration, pipeline, and profile creation. Start with [`docs/0. README.md`](docs/0.%20README.md) for a guided index of all documentation.

---

## Quick start

```bat
:: 1. Install deps + build the index + scaffold config files
context_bridge\setup\windows\setup_context_bridge.bat

:: 2. Point the config at YOUR source folders
::    edit config.hybrid.json  ->  settings.discovery.*  (replace your_backend / your_frontend)

:: 3. Re-run setup to index your code
context_bridge\setup\windows\setup_context_bridge.bat

:: 4. Start the server + dashboard (pick Hybrid / Semantic / Keyword)
context_bridge\setup\windows\1.  start_Context_Bridge.bat
```

**Mac/Linux:** use `context_bridge/setup/mac/` or `context_bridge/setup/linux/` equivalents.

Setup is **rerunnable and safe**: it creates config/start files from the `*.example`
templates only if missing (never overwrites your edits), and rebuilds the index each run.
Run `setup_context_bridge.bat --force` to reset configs back to the templates.

The MCP server is SSE-based at `http://127.0.0.1:8755/sse`. Point your AI client there.
Dashboard: `http://127.0.0.1:8795`.

---

## Retrieval modes

Chosen at startup (the start script picks the matching config file):

| Mode | Config | What it does |
|---|---|---|
| **Hybrid** | `config.hybrid.json` | Keyword-first + guarded vector assist (recommended) |
| **Semantic** | `config.semantic.json` | Vector-only (needs `sentence-transformers`) |
| **Keyword** | `config.json` | Pure keyword, no vectors |

---

## MCP tools

| Tool | Use |
|---|---|
| `search_context_hybrid()` | **Primary** — broad file + context discovery (runs analysis automatically) |
| `find_code_locations()` | Exact owner file / symbol / line for a method or class |
| `get_module_summary()` | Overview of a module/service |
| `get_graphify_pack()` | All files in a feature pack |
| `record_outcome()` | Log whether a result helped |
| `health_check()`, `get_usage_summary()`, `search_context()`, `find_related_files()` | Utility |

Which tools appear is controlled by config — if a tool is registered, it is safe to call.

---

## Writing your own profile

The generic engine asks a **profile** for project-specific ranking at every step.
With no profile (`project_profile: "default"`) you get pure generic scoring.

1. Copy `rules/projects/example_profile.py` → `rules/projects/<yourapp>_profile.py`
2. Implement the hooks you need (every hook is optional — skipped hooks fall back to no-op)
3. Activate it: set `CONTEXT_BRIDGE_PROFILE=<yourapp>` in your start script,
   or `project_profile: "<yourapp>"` in your config

### Profile hooks (all optional)

| Hook | Purpose |
|---|---|
| `expand_query_tokens(query, tokens)` | Add extra search tokens |
| `module_intent_tokens()` | Map module name → vocabulary |
| `pinned_owner_files(query_tokens)` | Force specific files to the top |
| `adjust_document_score(...)` | Boost/penalize a candidate document |
| `adjust_owner_score(...)` | Boost/penalize an owner file by name |
| `adjust_primary_owner_score(...)` | Nudge the single primary owner |
| `adjust_scoped_score(...)` | Prefer files under the dominant module/pack |
| `extra_owner_file_patterns()` | Extra high-priority filename patterns |
| `infer_module_from_path(path)` | Path → module name (fusion scoping) |
| `low_signal_terms()` | Module/domain words to treat as low-signal |
| `noise_files()` | Filenames to de-prioritize (ui/support/root) |
| `gap_queries()` | Trigger words → clean re-search query |
| `analysis_prompt_override()` | Full system prompt for the local AI |
| `pack_files_for_intents(...)` | Map intents → Graphify pack files (advanced) |

See [`docs/`](docs/0.%20README.md) for extended guides on setup, pipeline, profile creation, and debug commands.

---

## Indexing

ContextBridge indexes **Graphify output** (`graph.json`, `GRAPH_REPORT.md`,
`source-files.txt`, `scope-summary.md`, `manifest.json`) plus `/behavior/` docs — not raw
source. Generate Graphify for your project, point `settings.discovery.*` at those folders,
and run setup. Re-run setup after each Graphify update to refresh the index.

---

## Local AI (optional)

Configure a local model under `pipeline.analysis_stage` (provider `ollama` by default,
or `anthropic`/`openai`/`openrouter`). When enabled, it validates and re-ranks CB results,
decomposes multi-topic prompts, and triggers gap re-searches — then passes a compact,
grounded result to your cloud AI. Swap models by changing `model` only; the prompts are
model-agnostic.

---

## License

Copyright 2026 Tiju Thomas

Licensed under the [Apache License, Version 2.0](LICENSE).
