# How To Set Up ContextBridge MCP

This is the main setup guide for using ContextBridge with Codex or any AI client that supports local MCP servers.

## 1. Before Setup

Check:

- Python is available
- the repo exists locally
- central `graphify-out/` exists
- nested ownership `graphify-out` folders exist where needed

Review:

- [1. CONFIG_BEFORE_SETUP.md](./1.%20CONFIG_BEFORE_SETUP.md)

## 2. Install Dependencies

Base only:

```powershell
python -m pip install -r context_bridge\requirements-base.txt
```

Full local install:

```powershell
python -m pip install -r context_bridge\requirements-all.txt
```

Semantic-capable install:

```powershell
python -m pip install -r context_bridge\requirements-semantic.txt
```

Validate semantic dependencies:

```powershell
python context_bridge\scripts\check_rag_dependencies.py
```

## 3. Run Setup

Normal full setup (run for your OS):

```text
Windows: context_bridge\setup\windows\setup_context_bridge.bat
Mac:     context_bridge/setup/mac/setup_context_bridge.sh
Linux:   context_bridge/setup/linux/setup_context_bridge.sh
```

Use this when you want the standard full setup.

- double-clicking the bat file (Windows) runs this default behavior
- terminal is only needed when you want to pass setup options

Optional terminal examples (Windows shown — same flags apply on Mac/Linux):

```text
context_bridge\setup\windows\setup_context_bridge.bat --profile base
context_bridge\setup\windows\setup_context_bridge.bat --profile all
context_bridge\setup\windows\setup_context_bridge.bat --profile all --skip-semantic-index
```

Meaning:

- `setup_context_bridge.bat`
  - normal full setup
- `--profile all`
  - full dependency profile
- `--skip-semantic-index`
  - install full dependencies but skip semantic index build for that run

This setup:

- installs dependencies
- checks Graphify roots
- auto-discovers nested `graphify-out` folders
- builds the keyword index
- optionally builds the semantic index
- prints found and missing paths

## 4. Choose The Correct Mode

Run once from PowerShell:

```powershell
context_bridge\start_mcp_server.ps1
```

Pick a mode when prompted:

| Choice | Mode | Config | Use when |
| --- | --- | --- | --- |
| 1 (default) | Hybrid | `config.hybrid.json` | default investigation mode |
| 2 | Semantic | `config.semantic.json` | vague workflow/symptom/business questions |
| 3 | Keyword | `config.json` | exact class/file/controller/service names already known |

The server starts on `http://127.0.0.1:8755/sse/`. Keep the terminal open. All AI clients connect to that URL — no per-client Python path setup needed.

## 5. Project Rules (Optional)

ContextBridge setup gives you the engine, indexes, and MCP runtime.

It does not automatically know every project's symptom vocabulary or ranking behavior.

Project rules are optional ranking tuning used when:

- repeated symptom-style queries rank the wrong files
- UI pages keep outranking backend owner files
- cross-module searches keep favoring the wrong module
- evals or real usage show recurring misses

These rules are:

- not model fine-tuning
- not required for setup
- only added later if retrieval misses are observed

Rule file example:

- `context_bridge/rules/projects/<project>_rules.json`

Example:

- `context_bridge/rules/projects/example_rules.json`

## 6. Important: What Controls The Mode?

This is the key rule:

- the **server + config + MCP session** control the real runtime mode
- the **prompt** only tells the AI which tool to prefer

The prompt does **not** switch the active mode by itself.

Examples:

- if you loaded normal mode, AI can call `search_context()`
- if you loaded hybrid mode, AI can call `search_context_hybrid()`
- if you loaded semantic mode, AI still calls `search_context_hybrid()`, but the runtime is semantic because of the loaded config and vector env

If config is hybrid and the prompt says "use semantic", the session still runs in hybrid mode.

## 7. If You Change Mode

Do this:

1. press Ctrl+C in the server terminal to stop
2. re-run `start_mcp_server.ps1` and pick the new mode
3. restart VS Code / Codex / AI client if needed
4. open a new chat

Do **not** assume changing config in the middle of a chat will switch the current session.

## 8. MCP Config Examples

The server runs as a single SSE process. All tools connect via URL — no per-client command/args needed.

### Claude Code (`claude.json`)

```json
{
  "mcpServers": {
    "context_bridge": {
      "url": "http://127.0.0.1:8755/sse/"
    }
  }
}
```

### Codex (`%USERPROFILE%\.codex\config.toml`)

```toml
[mcp_servers.context_bridge]
url = "http://127.0.0.1:8755/sse/"
startup_timeout_sec = 10
```

### Cursor / other tools

Add an MCP server entry with URL `http://127.0.0.1:8755/sse/`. Location varies per tool.

> The mode (Hybrid/Semantic/Keyword) is selected when you start the server via `start_mcp_server.ps1`, not in the client config.

## 9. Which Tool The AI Should Use

Use:

- `search_context_hybrid()` — works in all modes (Hybrid, Semantic, Keyword)
- `find_code_locations()` — when you need owner file, symbol, line hint, or dependency chain
- `search_context()` — keyword-only fallback (normal mode only)

`search_context_hybrid()` automatically runs Qwen analysis and returns a `summary`, `ranked_files`, `selected_symbols`, `dependencies`, `risks`, and `recommended_code_blocks` alongside the retrieval results. No second tool call needed.

Recommended AI behavior:

- default to Hybrid
- use Keyword when exact identifiers are already known
- use Semantic for vague questions
- split very large cross-module bugs into smaller searches

## 10. Smoke Tests

Normal:

```powershell
python context_bridge\scripts\smoke_test_mcp.py
```

Hybrid:

```powershell
python context_bridge\scripts\smoke_test_mcp_hybrid.py
```

Semantic:

```powershell
python context_bridge\scripts\smoke_test_mcp_hybrid_semantic.py
```

## 11. Dashboard And Logs

Start dashboard:

```text
context_bridge\start_dashboard.bat
```

Open:

```text
http://127.0.0.1:8795
```

Logs:

- `context_bridge\usage\events.jsonl`
- `context_bridge\usage\outcomes.jsonl`

## 12. What Setup Does Not Do

Setup does:

- install dependencies
- build indexes
- discover Graphify roots
- prepare the MCP runtime

Setup does not:

- know the project's symptom vocabulary
- auto-create project ranking rules
- auto-tune repeated retrieval misses

Project rules are added later only if retrieval misses are observed.

## 13. How To Build Project Rules

Use project rules only when repeated misses are observed.

Simple process:

1. run evals or real searches
2. identify a repeated failure pattern
3. note:
   - the exact query
   - the correct owner files
   - the noisy files that ranked too high
4. create or update:
   - `context_bridge/rules/projects/<project>_rules.json`
5. add a rule that:
   - boosts the correct owner files
   - penalizes the noisy files
   - applies only for the matching query terms and query profile
6. rerun evals and confirm the ranking improved

Typical use cases:

- backend owner files are pushed down by UI pages
- one module dominates a cross-module query
- symptom words keep drifting into the wrong domain

Rule structure is simple:

- `name`
- `query_profiles`
- `terms_any` or `terms_all`
- `path_boosts`
- `path_penalties`

Example shape:

```json
{
  "name": "order_approval_safety",
  "query_profiles": ["code_debug"],
  "terms_any": ["order", "approval", "reopen", "manager"],
  "path_boosts": [
    { "suffix": "orderservice.cs", "score": 10.0 }
  ],
  "path_penalties": [
    { "suffix": "approvalstab.tsx", "score": 8.0 }
  ]
}
```

These rules are ranking hints only. They do not change Graphify data and they do not train a model.

## 14. Practical Recommendation

For most developer work:

1. use Hybrid as default
2. use Normal for exact code-name lookups
3. use Semantic only for vague workflow questions
4. after any mode change, start a new chat
