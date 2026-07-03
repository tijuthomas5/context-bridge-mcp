# ContextBridge

> **Platform: Windows, Mac, and Linux supported.** Use the scripts in `setup/windows/`, `setup/mac/`, or `setup/linux/` for your OS.

ContextBridge is a local, read-only code context tool built on top of Graphify data.

It supports:

- Normal Search
- Hybrid RAG
- Semantic RAG
- `find_code_locations` for owner file, symbol, line hint, and dependency guidance

## Intended Scope

ContextBridge is a codebase routing and retrieval tool, not a reasoning engine. Setting
this expectation clearly up front helps every user get accurate value from it.

ContextBridge is designed to help with:

- finding the right module
- finding the right file area
- surfacing likely owner files
- surfacing useful symbols and line hints
- providing first-pass related files
- reducing manual repo search effort

ContextBridge is not designed to:

- understand a bug in full by itself
- prove causality
- choose the final fix
- replace reading the actual source
- replace engineering judgment across conditional branches

Two practical limits follow directly from this:

- **Retrieval quality depends on the underlying Graphify data.** ContextBridge routes
  based on what Graphify has recorded. If Graphify's data is missing a file, a function,
  or a connection between files, ContextBridge cannot surface what was never captured.
- **A related file must have a real, recorded connection to be surfaced.** ContextBridge
  can only report a relationship it has evidence for — an import, a call, a shared
  dependency, and so on. It does not infer a connection that was never captured.

In short: ContextBridge gets you to the right place with the right first-pass files,
symbols, and connections — quickly, and with fewer wasted tokens. Understanding the code
you land on, judging correctness, and choosing the fix remain the job of the reader or
the AI acting on the result.

## What It Needs

Before setup, make sure:

- the repo exists locally
- central `graphify-out/` exists
- nested ownership `graphify-out` folders exist where relevant
- Python dependencies can be installed

If Graphify data is missing or stale, ContextBridge results will also be missing or stale.

## Project Rules (Optional)

ContextBridge has two layers:

- Graphify data
- ranking rules

Graphify data is required.

Project rules are optional ranking tuning. They help when repeated retrieval misses appear for a specific project, such as:

- symptom-style queries ranking the wrong files
- UI pages outranking backend owner files
- one module overpowering another in cross-domain queries

Important:

- this is not model fine-tuning
- this is retrieval/ranking tuning
- ContextBridge still works without project rules
- project rules are added only if evals or real usage show repeated misses
- rules can be written manually or with AI help

## The 3 Modes

| Mode | Config | Use when |
| --- | --- | --- |
| Hybrid | `config.hybrid.json` | Default day-to-day investigation |
| Semantic | `config.semantic.json` | Vague workflow/symptom/business questions |
| Keyword | `config.json` | Exact class/file/controller/service names already known |

All modes run via the same server (`mcp_server_hybrid.py`) started with your OS start script. Pick mode at launch time.

## Pipeline (Built-in Analysis Stage)

ContextBridge has a built-in two-stage pipeline — retrieval and analysis. Both run inside ContextBridge, not inside your AI coding tool. The analysis stage uses a local AI model via Ollama (any Ollama-compatible model works) and is optional — ContextBridge works without it.

Full details: [PIPELINE_SETUP.md](./PIPELINE_SETUP.md)

## How Outcome Logging Works

Every `search_context_hybrid()` call writes one immutable record to `usage/events_*.jsonl` at query time — this includes CB's actual retrieved files, confidence, and symbol hits, and it is never changed afterward.

If the AI later calls `record_outcome()`, that writes a separate record to `usage/outcomes_*.jsonl`, linked only by `event_id`. It does not overwrite or edit the original event.

This means CB's own record of what it returned is always preserved as ground truth, separate from whatever the AI reports happened afterward. The dashboard shows both side by side, so a mismatch between them (e.g. AI reports success but CB's own confidence/symbol hits were weak) stays visible for review rather than being lost.

## Important: Who Controls The Mode?

- the **server and config** control the real runtime mode
- the **prompt** only tells the AI which tool to prefer
- the prompt does **not** switch the active MCP runtime by itself

If you change mode:

1. stop the server (Ctrl+C in the terminal)
2. re-run your OS start script and pick a new mode
3. open a new chat

## Quick Start

1. review [1. CONFIG_BEFORE_SETUP.md](./1.%20CONFIG_BEFORE_SETUP.md)
2. run the setup script for your OS:
   - **Windows:** `context_bridge\setup\windows\setup_context_bridge.bat`
   - **Mac:** `context_bridge/setup/mac/setup_context_bridge.sh`
   - **Linux:** `context_bridge/setup/linux/setup_context_bridge.sh`
   - double-click the bat file (Windows) for the normal full setup
   - use terminal only if you want setup options
3. start the server using your OS start script:
   - **Windows:** `context_bridge\setup\windows\1.  start_Context_Bridge.bat`
   - **Mac:** `context_bridge/setup/mac/1. start_Context_Bridge.sh`
   - **Linux:** `context_bridge/setup/linux/1. start_Context_Bridge.sh`

   Keep the terminal open.
4. connect your AI tool to `http://127.0.0.1:8755/sse/`
5. open a new AI chat

See [Quick_mcp_setup.md](./Quick_mcp_setup.md) for per-tool connection examples.

## Prompt Guidance

- all modes use `search_context_hybrid()` — same tool name regardless of mode
- local AI analysis runs automatically — no need to call `analyze_context` manually
- prompt guides tool usage only; it does not switch the active runtime mode
- **writing a good query:** name the feature area + the concrete symptom + any known terms, all as plain keywords — not a full sentence, just the nouns. Shape: `<module/feature> <specific action/symptom> <any known field/status/button name>`

## Read Next

- full setup: [HOW_TO_SETUP_MCP.md](./HOW_TO_SETUP_MCP.md)
- quick MCP usage: [Quick_mcp_setup.md](./Quick_mcp_setup.md)
