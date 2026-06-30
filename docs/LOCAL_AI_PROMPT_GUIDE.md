# Local AI Prompt Guide — How to Control Qwen (or Any Local Model)

## Intended Pipeline Flow (Do Not Change)

```
User prompt (with >>SEARCH: tag)
    → ContextBridge (keyword + vector search)
    → CB results → Qwen/Local AI (validates, re-ranks, analyzes, decomposes topics)
    → Qwen output ONLY → Claude/any AI (implements the task)

User prompt (no tag)
    → Claude/any AI answers directly — CB and Qwen are skipped
```

**Key design rules:**
- CB only fires when `>>SEARCH:` tag is present — no tag = no CB, AI answers directly
- When Qwen succeeds → AI receives ONLY Qwen's output (`source: "qwen"`). CB raw data is dropped.
- When Qwen fails/times out → AI receives CB's raw output as fallback (`source: "cb_fallback"`).
- Qwen is the single source of truth for the AI. CB raw facts never reach the AI when Qwen is working.

**This is synchronous by design.** The AI waits for Qwen to finish before receiving anything.
Qwen's full analysis — relevance check, topic decomposition, file re-ranking, gap re-searches,
confidence scoring — must complete before the AI acts.

Typical Qwen latency: 90–130 seconds for complex multi-topic prompts.

---

## The One File That Controls Everything

> `SYSTEM_PROMPT` is NOT a separate file.
> Everything is inside one file: `context_bridge/analysis/prompt.py`

---

## Full Map of What You Can Control from prompt.py

```
context_bridge/analysis/prompt.py
│
├── CONSTANTS (top of file, lines 4-6)
│   ├── _MAX_PROMPT_CHARS = 80,000        ← total size of what Qwen receives
│   ├── _MAX_CODE_BLOCK_CHARS = 6,000     ← max chars per individual code block
│   └── _MAX_CODE_BLOCKS = 20             ← how many code blocks Qwen sees
│
├── SYSTEM_PROMPT (line 8)  ← controls HOW Qwen behaves
│   ├── Qwen's role definition            ← "you are a repository analyst..."
│   ├── Strict rules (what NOT to do)     ← no code generation, preserve identifiers
│   ├── Step 1: Relevance check           ← PASSED / PARTIAL / FAILED decision
│   │           └── uses Graphify modules/packs/facts to validate domain
│   ├── Step 2: Independent reasoning     ← Qwen's authority to re-rank CB results
│   │           ├── re-rank candidate files
│   │           ├── ignore wrong CB files
│   │           └── infer missing files from dependency chain
│   ├── Step 3: Confidence level          ← high / medium / low signal to Claude
│   └── Output JSON schema                ← exact fields Qwen must return
│       ├── relevance_check
│       ├── confidence
│       ├── ignored_files
│       ├── summary  (MANDATORY)
│       ├── current_implementation
│       ├── workflow
│       ├── ranked_files (with source field: cb_retrieved / inferred_from_deps / inferred_from_graphify)
│       ├── selected_symbols
│       ├── selected_code_block_ids
│       ├── dependencies
│       ├── impacted_files
│       └── risks
│
└── build_user_prompt() (line 100) ← controls WHAT Qwen sees
    ├── ## Task                           ← your original query
    ├── ## Primary Owner                  ← top file CB identified
    ├── ## Candidate Files (up to 20)     ← files + CB relevance scores
    ├── ## Symbol Hits (up to 30)         ← matched function/class names
    ├── ## Dependency Chain (up to 30)    ← which files call which
    ├── ## Location Hints (up to 20)      ← file + line number pointers
    ├── ## Facts (up to 15)               ← from Graphify, for domain validation
    ├── ## Modules (up to 10)             ← from Graphify, codebase domain map
    ├── ## Packs (up to 10)               ← from Graphify, feature groupings
    └── ## Code Blocks (up to 20 blocks)  ← actual code, 6000 chars each
```

---

## How the Pipeline Flows

```
User prompt
    → ContextBridge (keyword + vector search)
    → CB returns: ranked files, symbols, code blocks, dependency chain
    → build_user_prompt() packages query + CB results into one text block
    → SYSTEM_PROMPT + user prompt sent to local AI (Qwen/Ollama)
    → Qwen: Step 1 relevance check → Step 2 re-rank → Step 3 confidence
    → Qwen returns structured JSON
    → Claude receives compressed JSON (not raw files)
```

Qwen never reads files directly. It only sees what CB extracts and passes to it.

---

## What Each Constant Controls

| Constant | Current Value | Effect of increasing | Effect of decreasing |
|---|---|---|---|
| `_MAX_PROMPT_CHARS` | 80,000 | Qwen gets more context | Qwen gets truncated input |
| `_MAX_CODE_BLOCK_CHARS` | 6,000 | Qwen sees fuller methods | Qwen sees truncated snippets |
| `_MAX_CODE_BLOCKS` | 20 | Qwen sees more files' code | Qwen sees fewer files |

> These were previously set low (12,000 / 600 / 8) to protect Claude's paid token budget.
> Since Qwen runs locally, tokens to Qwen are free — set these as high as your Qwen model's context window allows.
> Qwen 7B: ~32K context. Qwen 14B+: ~128K context.

---

## What SYSTEM_PROMPT Controls

| Section in SYSTEM_PROMPT | What it does |
|---|---|
| Role definition | Tells Qwen it has independent reasoning authority, not just passive processing |
| Strict rules 1-6 | Prevents Qwen from generating code, hallucinating, or summarizing away identifiers |
| Step 1 — Relevance check | Forces Qwen to validate CB results before analyzing. PASSED / PARTIAL / FAILED |
| Step 2 — Independent reasoning | Gives Qwen authority to re-rank, ignore wrong files, infer missing files |
| Step 3 — Confidence | Forces Qwen to declare how sure it is (high/medium/low) |
| Output JSON schema | Exact structure Qwen must return — adding/removing fields here changes what Claude receives |

---

## What build_user_prompt() Controls

| Section | Count limit | What Qwen uses it for |
|---|---|---|
| Task | Full query | The question being asked |
| Primary Owner | 1 file | CB's top match |
| Candidate Files | 20 | Re-ranking and relevance check |
| Symbol Hits | 30 | Identifying relevant methods/classes |
| Dependency Chain | 30 | Inferring files CB missed |
| Location Hints | 20 | Pinpointing exact line numbers |
| Facts | 15 | Validating domain correctness |
| Modules | 10 | Checking files belong to right module |
| Packs | 10 | Checking files belong to right feature |
| Code Blocks | 20 × 6000 chars | Deep code understanding |

---

## Relevance Check Outcomes

| Outcome | What Qwen does | What Claude receives |
|---|---|---|
| `PASSED` | Full analysis | Complete ranked files, symbols, workflow |
| `PARTIAL` | Analyzes only matching files, ignores rest | Analysis + list of ignored files with reasons |
| `FAILED` | Stops immediately | Error JSON — CB retrieved wrong domain, re-query needed |

---

## Quick Reference — What to Edit for Common Changes

| I want to... | Edit this | Location |
|---|---|---|
| Give Qwen more code to read | `_MAX_CODE_BLOCK_CHARS` | Line 5 |
| Give Qwen more files' code | `_MAX_CODE_BLOCKS` | Line 6 |
| Change Qwen's total context size | `_MAX_PROMPT_CHARS` | Line 4 |
| Change Qwen's role or rules | `SYSTEM_PROMPT` role + rules section | Line 8 |
| Change relevance check behavior | Step 1 in `SYSTEM_PROMPT` | Line 23 |
| Change what Qwen can do independently | Step 2 in `SYSTEM_PROMPT` | Line 34 |
| Add/remove output fields | JSON schema in `SYSTEM_PROMPT` | Line 54 |
| Add extra context to every query | New section in `build_user_prompt()` | Line 100 |
| Change how many files Qwen sees | `files[:20]` in `build_user_prompt()` | Line 115 |
| Change how many symbols Qwen sees | `symbols[:30]` in `build_user_prompt()` | Line 119 |
| Swap local model | `analysis/config.py` | model name only — prompt.py unchanged |

---

## Topic Decomposition + Gap Re-Search (Auto)

When a prompt mentions multiple issues or modules, Qwen automatically decomposes it into individual topics — one per symptom/module. This is built into `SYSTEM_PROMPT` (Step 1.5).

**How it works:**
1. Qwen reads the prompt body and identifies every distinct symptom (orders blocked, payment stuck, checkout rejected, etc.)
2. For each topic, Qwen assigns the best matching file from CB's Candidate Files list
3. Qwen sets `file_match: true` or `false` per topic using a two-step check:
   - **Step A** — Is the file in the Candidate Files list? If NO → `file_match: false` immediately
   - **Step B** — Does the file domain match the topic? If NO → `file_match: false`
4. Any topic with `file_match: false` triggers a **gap re-search** automatically

**Gap re-search:**
- Fires in `hybrid_tools.py` → `_run_gap_searches()`
- Query is built from the active profile's `gap_queries()` table — pure Python, no Qwen involvement
- Domain mappings (example): `"orders"` → `"order checkout cart service"`, `"payment"` → `"payment invoice refund service"`, etc.
- Max 3 gap re-searches per query
- Found files are injected into `ranked_files` and passed to the AI

**Anti-hallucination rules in effect:**
- Qwen must ONLY use file paths from the Candidate Files list — never invent paths
- Qwen must ONLY use method/symbol names from Symbol Hits or Code Blocks — never infer from prompt text
- If no real method found → `entry_method: "unknown"`, `symbols: []`
- Gap queries come from the Python lookup table, never from Qwen

---

## Qwen Timeout Settings

Both timeouts are in `context_bridge/config.hybrid.json`:

| Setting | Value | Purpose |
|---|---|---|
| `auto_analyze_timeout_seconds` | 360 | How long the pipeline waits for Qwen before falling back to CB raw output |
| `timeout_seconds` | 360 | HTTP timeout for the Ollama request itself |

If Qwen takes longer than `auto_analyze_timeout_seconds`, the pipeline returns CB raw output directly to the AI (`source: "cb_fallback"`). Raise these values if your machine is slow.

---

## Swapping the Local Model

The prompts in `prompt.py` are model-agnostic — plain text, no model-specific syntax.

1. Install new model: `ollama pull <model-name>`
2. Update model name in `context_bridge/analysis/config.py`
3. Adjust `_MAX_PROMPT_CHARS` to match the new model's context window
4. `prompt.py` behavior stays identical
