# Changelog

All notable changes to ContextBridge MCP will be documented in this file.

---

## [1.2.1-beta] - 2026-07-09

### Changed
- Document that stdio transport is also supported in addition to SSE, across the setup and connection guides.

---

## [1.2.0-beta] - 2026-07-09

### Fixed
- Fix the indexer crashing when an enrichment or graph JSON file is shaped as a list instead of the expected object, so one malformed file no longer aborts the whole reindex.

### Added
- Add support for indexing UI-to-backend dependency-edge enrichment files as searchable documents, so previously-inert route-mapping data now contributes to file ranking instead of being silently skipped.
- Add a repo-wide drift scan that inventories real source files against what's already covered by existing packs, flags orphaned/uncovered files, and reports suggested pack placement for manual review.
- Add a companion sync tool that detects stale custom packs via content hashing and rebuilds only what changed.
- Add a hardened pack builder used by the scan/sync tools, with explicit path-traversal guards on every path read from pack file lists and enforced offline-only extraction (network/LLM API keys are cleared from the process before each rebuild).
- Add setup documentation covering how the update/sync/reindex pipeline fits together and when each step is needed.

---

## [1.1.4-beta] - 2026-07-06

### Fixed
- Fix a ranking penalty that punished a file purely for its position in an unrelated list, unfairly crushing the score of a correct answer that happened to be listed later than a less relevant file.
- Fix an explicitly-named file receiving the exact same reward as another explicitly-named but topically different file, letting a same-family decoy occasionally outrank the real target.
- Fix a case-handling bug that broke word-splitting for compound file names, making some filenames score as if they shared no words with the query at all.

### Changed
- Cache a per-file measurement used for dashboard reporting so it isn't recomputed from disk on every dashboard refresh.
- Reduce how often the dashboard's full stats rebuild can be triggered in quick succession.
- Scope the dashboard's "always fetch fresh" response header to its live data endpoint only, so static dashboard assets can be cached normally.
- Load the dashboard's fallback stats script only when needed, instead of unconditionally on every page load.
- Cap several dashboard history lists to a bounded recent window so they stop growing indefinitely over time.

### Added
- Add a rule requiring the indexing step to explicitly connect a frontend API call to its matching backend endpoint (by matching the actual request path and method), instead of treating the two files simply being indexed together as sufficient.

## [1.1.3-beta] - 2026-07-04

### Fixed
- Fix primary-owner selection ignoring a method the query names explicitly, letting a generic method in the same file win instead.
- Fix a type/interface declaration in a `.tsx` file being misclassified as a real component, letting it win primary-owner over the actual decisive symbol.
- Fix a shared file's most useful duplicate chunk being selected by raw edge count instead of actual cross-file dependency coverage.
- Fix the exact-identifier bonus rewarding a method name even when the query explicitly says it is *not* the owner.

### Added
- Add a more reliable check for when a query genuinely names a real file, so more of that file's methods are considered instead of stopping at the usual cap.
- Add a second-pass check over the top primary-owner candidates to catch cases where an unrelated or coincidental match was outranking the real answer, with a conservative threshold so it only steps in on a clear difference.

---

## [1.1.2-beta] - 2026-07-04

### Fixed
- Fix a shared/hub file's most complete cross-file connection getting dropped in favor of a topically-closer but less complete duplicate chunk.
- Fix files named explicitly in a query ranking below the default result cutoff despite being an exact filename match.
- Fix TypeScript `Props`/`State` type-only declarations being picked as the primary symbol over the real component.

### Changed
- `.gitignore`: exclude the `tests/` folder entirely — all test scripts stay local-only.

---

## [1.1.1-beta] - 2026-07-04

### Fixed
- Fix cross-file dependency edges resolving via the wrong graph field, causing missing dependency/related-file data for connected files.
- Fix `inherits`/`imports_from` dependency edges scoring below weaker relation types due to missing ranking weights.
- Fix pin/pack-promoted files reaching the AI with no code snippet, including when the code-block budget was already full.

### Added
- Add regression test coverage for ranking and code-block backfill logic (15 tests).
- Add query-phrasing guidance for AI clients and users.

### Changed
- `.gitignore`: track the two new regression test files instead of excluding the whole `tests/` folder.

---

## [1.1.0-beta] - 2026-07-02

### Fixed
- Fix dashboard incorrectly flagging strong retrieval results as `needs_review` when usage wasn't reported.

### Added
- Add a Ranking Profile switcher to the dashboard Settings panel.
- Document the `chunk_central_graph` config option for more precise cross-module retrieval.
- Document optional outcome-reporting fields for `record_outcome()`.
- Add a "How Outcome Logging Works" section to the overview documentation.

### Changed
- Update profile activation instructions to include the new dashboard switcher.
- Expand the limitations documentation to note dashboard grading depends partly on optional usage-reporting.

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
