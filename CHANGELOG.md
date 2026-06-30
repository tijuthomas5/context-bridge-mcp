# Changelog

All notable changes to ContextBridge MCP will be documented in this file.

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
