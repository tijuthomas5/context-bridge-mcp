# Changelog

All notable changes to ContextBridge MCP will be documented in this file.

---

## [1.1.1-beta] - 2026-07-04

### Fixed
- **Cross-file dependency resolution** (`src/graphify_loader.py`): `load_graph_chunks()` was matching graph edges to owner files by node *label* instead of node *id* — the wrong field per the standard node-link graph JSON format edges actually use. This caused `edge_count: 0` and empty `dependency_hints`/`related_files` for files with real cross-file connections. Fixed by resolving both endpoints via `id_to_file` (falling back to `label_to_file`), and by passing the full node list (not just a single file's own nodes) into `collect_dependency_hints()` so cross-file targets can resolve. Verified against a real indexed graph: a previously-broken file's `edge_count` went from 0 to 232, with its true dependency correctly surfaced.
- **Dependency-relation ranking gap** (`src/search.py`): `DEPENDENCY_RELATION_WEIGHT` had no entries for `inherits`/`imports_from`, so both silently fell back to the generic default (250.0) — scoring *below* generic relations like `contains` (300.0) and `defines` (280.0), even though an inheritance or import edge is a much stronger relevance signal. Added explicit weights (`inherits: 520.0`, `imports_from: 480.0`), matching their sibling relations `uses`/`imports`.
- **Pin-promoted files missing code blocks** (`mcp_tools/hybrid_tools.py`): a file promoted to `files[0]` by the post-fusion pin/pack reorder could reach the AI with no code snippet, because `code_blocks` is built from the pre-fusion keyword pass and never knew about the promotion. Extracted the previously-inline pin-reorder logic into `reorder_candidates_by_pins()` and added a new `backfill_missing_code_blocks()` that reuses `enrich_symbol_hits()` to fill in the gap within the existing `code_block_max_blocks` budget.
  - Follow-up fix (same area, found in a second review pass): the initial fix only covered files with *zero* prior symbol hits, and did nothing when the code-block budget was already full — both common cases in practice. Broadened eligibility to the full top-ranked window regardless of prior symbol-hit status, and added an opt-in `priority_paths` eviction path: when the budget is full, lower-priority blocks (outside the current top-ranked window) are evicted — no more than needed, and never a block that belongs to a priority file — to make room for the promoted file. Disabled by default (`priority_paths=None`) to keep any other caller's behavior unchanged.

### Added
- **Regression test coverage** for previously-untested ranking/backfill logic: `tests/test_ranking_functions.py` (`reserve_top_file_code_block_slots`, `extract_related_files` anchor-based dependency expansion, `reorder_candidates_by_pins`) and `tests/test_backfill_missing_code_blocks.py` (`backfill_missing_code_blocks`, including the eviction path). 15 tests total, all passing.
- **CB query-phrasing guidance** — `skill/SKILL.md`'s "Usage Rules" (AI-facing: use concrete module/symptom/field keywords, not a full sentence; narrow the query on a weak first result) and `docs/OVERVIEW.md`'s "Prompt Guidance" section (user-facing, same shape: `<module/feature> <specific action/symptom> <any known field/status/button name>`).

### Changed
- **`.gitignore`**: `tests/` was a directory-anchor pattern, which blanket-ignores the whole folder and silently drops any file inside it from version control — including the new permanent regression tests above. Changed to `tests/*` (glob, not directory-anchor) with explicit `!tests/test_ranking_functions.py` / `!tests/test_backfill_missing_code_blocks.py` exceptions, so those two are tracked while ad-hoc/benchmark scripts in the same folder remain ignored.

---

## [1.1.0-beta] - 2026-07-02

### Fixed
- **Dashboard risk classifier** (`scripts/build_dashboard_stats.py`): the `likely_good` result no longer gets automatically disqualified just because usage wasn't reported (`logged_success_but_zero_usage`). Previously this caused effectively all results to fall into `needs_review` even when retrieval quality (confidence, symbol/location/dependency coverage) was strong. CB now falls back to judging the result on its own retrieval-quality signals when usage isn't reported, instead of penalizing it.

### Added
- **Ranking Profile switcher** in the dashboard Settings panel — lets you view available project profiles and switch the active one from a dropdown (`Apply & Restart CB`), instead of manually editing config files or start scripts (`dashboard_server.py`, `dashboard/dashboard.js`, `dashboard/index.html`).
- **`chunk_central_graph` guidance** in `docs/1. CONFIG_BEFORE_SETUP.md` — documents enabling per-source-file chunking for more precise symbol/cross-module retrieval.
- **Outcome-reporting documentation** — `record_outcome()`'s optional `used_suggested_files` / `extra_files_read` fields, and the exact method for computing them (compare CB's `top_files` list against files actually opened/edited), are now documented in `skill/SKILL.md` and `docs/AI_ROUTING_RULES.md`. Reporting these is explicitly optional and left to the user/AI's discretion.
- **`docs/OVERVIEW.md`** — new "How Outcome Logging Works" section explaining that CB's own event record is immutable ground truth, separate from the AI's self-reported outcome.

### Changed
- `1. IMP_Prompts_First/2.GENERATE_PROJECT_PROFILE.md` — profile activation instructions updated to include the new dashboard switcher as the recommended option, alongside the existing manual config-file method.
- `docs/LIMITATIONS.md` — item 9 expanded to note that dashboard grading partly depends on optional AI usage-reporting, and that CB falls back to its own signals when that reporting is skipped.

---

## [1.0.0-beta] - 2026-06-30

### Initial Beta Release

This is the first public beta release of **ContextBridge MCP** — a local-first code retrieval engine that exposes your codebase to AI coding agents via the Model Context Protocol (MCP).

---

### What is ContextBridge?

ContextBridge sits between your codebase and your AI coding agent. Instead of giving your AI raw source files (which wastes tokens and context window), CB indexes your Graphify-generated codebase knowledge graph and returns only the most relevant ranked files, symbols, and dependency chains — grounded in your actual project structure.

```
Your prompt ─► ContextBridge (keyword + vector retrieval)
            ─► Local AI (optional: validates, re-ranks, fills gaps)
            ─► Your AI agent (implements, grounded in real files)
```

---

### Features in v1.0.0

#### Token Efficiency
- CB returns a compact ranked result (owner file, related files, symbols, dependency summary) instead of raw source files
- Typically reduces input tokens from tens of thousands of lines of source to a few hundred tokens of grounded context
- Optional local AI analysis stage compresses results further before they reach your cloud AI
- Grounded results eliminate hallucinated file paths and method names

#### Retrieval Engine
- **Hybrid mode** — keyword-first retrieval with guarded vector assist (recommended for most projects)
- **Semantic mode** — vector-only retrieval using `sentence-transformers` for vague/workflow queries
- **Keyword mode** — pure keyword search for exact class/file/method lookups
- All three modes run on the same MCP server — switch at startup with no code changes

#### MCP Tools (exposed to AI clients)
- `search_context_hybrid()` — primary broad file + context discovery with automatic analysis
- `find_code_locations()` — exact owner file, symbol name, and line number for a method or class
- `get_module_summary()` — full overview of a module or service
- `get_graphify_pack()` — all files belonging to a feature area / Graphify pack
- `record_outcome()` — log whether a retrieval result was useful (for quality tracking)
- `health_check()` — server liveness and status check
- `get_usage_summary()` — usage statistics summary
- `search_context()` — basic keyword search (legacy)
- `find_related_files()` — files related to a query

#### Local AI Analysis Pipeline (optional)
- Built-in two-stage pipeline: retrieval → analysis
- Analysis runs inside CB before results reach your cloud AI
- Supports local models via **Ollama** (default) and cloud providers: **Anthropic**, **OpenAI**, **OpenRouter**
- Automatically validates and re-ranks retrieval results
- Decomposes multi-topic prompts and triggers gap re-searches
- Fully model-agnostic — swap models by changing one config field

#### Domain-Aware Ranking (Profile System)
- Swappable **profile plugin** system for project-specific ranking
- 14 profile hooks covering: intent detection, token expansion, file pinning, score adjustment, noise suppression, gap queries, pack injection, and analysis prompt override
- Ships with a complete `example_profile.py` as a reference template
- AI-assisted profile generation prompts included in `1. IMP_Prompts_First/`
- Ranking rules JSON file support for simple boost/penalty corrections alongside profiles

#### Cross-Platform Support
- **Windows** — full setup, start, stop, dashboard, Ollama, semantic index scripts
- **Mac** — equivalent shell scripts for all Windows bat files
- **Linux** — equivalent shell scripts for all Windows bat files
- Dynamic root-finding in all scripts — scripts work from any location inside the project

#### Dashboard
- Built-in web dashboard at `http://127.0.0.1:8795`
- Real-time usage stats and retrieval event log
- Visual overview of indexed packs and modules

#### Setup & Configuration
- One-command setup: installs dependencies, scaffolds config files, builds the index
- Safe to rerun — never overwrites existing config edits
- `--force` flag to reset configs back to templates
- Config templates (`*.example.json`) shipped for all three retrieval modes
- Auto-detection prompt for Graphify discovery paths included

#### CB Gauge (Evaluation Tool)
- Built-in quality evaluation tool to benchmark retrieval accuracy
- CLI and UI modes
- Custom question set support via `questions.json`
- Cross-platform scripts for Windows, Mac, and Linux

#### Documentation
- `docs/` folder with 13 guides covering setup, pipeline, profile creation, MCP connection, debug commands, limitations, and more
- Indexed by `docs/0. README.md` — start here
- AI-assisted prompt files for generating profiles and ranking rules
- Prompt routing rules for any AI client

---

### Supported AI Clients
Any MCP-compatible AI client works with ContextBridge via SSE at `http://127.0.0.1:8755/sse`.

Tested with:
- Claude Code
- Cursor
- Codex
- Antigravity (Gemini)

### Requirements
- Python 3.9+
- [Graphify](https://github.com/safishamsi/graphify) output for your codebase
- Ollama (optional, for local AI analysis)

---

### Notes
- This is a local-first tool — no telemetry, no cloud calls unless you configure a cloud analysis provider
- API keys stay on your machine in local config files (gitignored)
- The MCP server runs on `127.0.0.1` — not exposed to external networks by default
