# ContextBridge MCP — AI Skill

Copy this file into your project root and rename it to match your AI tool:
- Claude Code → `CLAUDE.md`
- Cursor, Codex, Copilot, Windsurf, Gemini CLI, Zed → `AGENTS.md`

Then fill in `## Your Project Stack` at the bottom.

---

## Connection

ContextBridge MCP runs as a single SSE server: `http://127.0.0.1:8755/sse`

**Before using CB:**
1. Start the server using your OS start script in `context_bridge/setup/`
2. Connect your AI tool to `http://127.0.0.1:8755/sse` — see `docs/HOW_TO_SETUP_MCP.md` for per-tool instructions
3. Open a new chat — CB tools are only available after connecting

If CB tools are unavailable, skip CB, answer directly, and warn: "CB is offline — answer is not grounded in codebase context."

---

## Prompt Tags

CB is NOT called automatically. It only fires when the user includes `>>SEARCH:` in their message.

| Tag | What it does |
|---|---|
| `>>SEARCH: <text>` | Triggers CB. Call `search_context_hybrid()` with this exact text. |
| `>>TASK: <text>` | What to do after CB returns. Answer this using the CB result. |
| No tag | Skip CB entirely. Answer from your own knowledge. |

**Rules:**
- `>>SEARCH:` present → call `search_context_hybrid()` with the exact value, never rephrase or shorten it
- `>>SEARCH:` + `>>TASK:` present → send only the `>>SEARCH:` value to CB, then answer `>>TASK:` using the result
- No tag → skip CB, answer directly

**Example:**
```
>>SEARCH: user login session token validation
>>TASK: why does the session expire too early, trace the full flow
```

---

## Tool Notes

Tool names and descriptions are loaded automatically from the MCP server. Two exceptions the server does not state:
- `analyze_context()` — do NOT call manually. It runs automatically inside `search_context_hybrid()`.
- `find_code_locations()` — only available when `enable_code_locations: true` in config.

`record_outcome(event_id, outcome)` — `outcome` must be one of: `"success"`, `"partial"`, `"failed"`. Optional `failure_reason`: `"none"`, `"bad_ranking"`, `"stale_graph"`, `"missing_graph_data"`, `"unclear_query"`, `"too_few_results"`, `"ai_did_not_use_context"`.

---

## Tool Sequence

1. `>>SEARCH:` fires `search_context_hybrid()` — always first
2. `find_code_locations()` — if exact file / line / symbol is needed after step 1
3. `get_module_summary()` — if a module needs deeper context before editing
4. `record_outcome(event_id, outcome)` — always after task. `outcome`: `"success"` / `"partial"` / `"failed"`

---

## Usage Rules

- Use only the files CB suggests — do not read entire source files
- Do not call CB again unless the first result was clearly about the wrong module
- Do not call `analyze_context()` manually — it runs automatically inside `search_context_hybrid()`
- If `analysis.skipped: true` in the response, use the retrieval results directly — ranked files and symbol hits are still valid
- If `is_stale: true` in the response, the index is outdated — tell the user to re-run the setup script to rebuild it
- If CB misses required files, follow up with `find_code_locations()` or `get_graphify_pack()` for targeted lookup, then record the miss using `record_outcome()`
- Code blocks in results are the source of truth — do not infer method names from file names
- Prefer uncertainty over hallucination
- After completing the task, always call `record_outcome()` with the `event_id`

---

## Your Project Stack
- Backend:
- Frontend:
- Database:
- AI pipeline: ContextBridge (retrieval) → analysis stage → your AI (implementation)
