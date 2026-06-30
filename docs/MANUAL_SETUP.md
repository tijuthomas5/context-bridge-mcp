# Manual Setup

This guide is for users who want to install, configure, and run ContextBridge manually without depending on the one-click setup bat file.

## 1. Prerequisites

Make sure these exist first:

- Python is installed and available in terminal
- the repository exists locally
- central `graphify-out/` exists
- nested ownership `graphify-out` folders exist where relevant

If Graphify data is missing or stale, ContextBridge will still run, but retrieval quality will be incomplete or weak.

Before continuing, review:

- [1. CONFIG_BEFORE_SETUP.md](./1.%20CONFIG_BEFORE_SETUP.md)

## 2. Choose What You Want To Install

### Base only

Use this if you want:

- Normal Search
- dashboard
- keyword index
- normal MCP server

Install:

```powershell
python -m pip install -r context_bridge\requirements-base.txt
```

### Semantic-capable

Use this if you also want:

- Semantic RAG
- semantic vector index build
- local embeddings

Install:

```powershell
python -m pip install -r context_bridge\requirements-semantic.txt
```

### Full install

Use this if you want the full local setup in one dependency install:

```powershell
python -m pip install -r context_bridge\requirements-all.txt
```

## 3. Validate Semantic Dependencies

Run this only if you want semantic mode:

```powershell
python context_bridge\scripts\check_rag_dependencies.py
```

Expected result should include:

- `ready_for_semantic_embeddings: true`

## 4. Review Config Files

ContextBridge uses these config files:

- `config.json`
- `config.hybrid.json`
- `config.semantic.json`

### What they control

- required Graphify roots
- optional docs/knowledge roots
- discovery parent folders
- ownership graph roots
- code-location feature flags
- RAG default mode

### Which file is used where

- `config.json`
  - general/local base config
- `config.hybrid.json`
  - hybrid MCP runtime
- `config.semantic.json`
  - semantic MCP runtime

If your repo layout differs, update the workspace-relative paths before indexing.

## 5. Build The Keyword Index

Run:

```powershell
python context_bridge\src\indexer.py
```

This builds:

- `context_bridge\data\context_index.json`
- `context_bridge\data\discovery_report.json`

What to check:

- no missing required roots
- discovered ownership roots are listed
- index file is created

## 6. Build The Semantic Vector Index

Run this only if you want semantic mode:

```text
context_bridge\build_semantic_vector_index.bat
```

This builds:

- `context_bridge\data\vector_index.semantic.jsonl`
- `context_bridge\data\vector_meta.semantic.json`
- `context_bridge\data\vector_chunks.semantic.jsonl`

## 7. Start The Correct Server

## Normal Search

Manual command:

```powershell
python context_bridge\mcp_server.py
```

Tool exposed:

- `search_context()`

## Hybrid RAG

Manual command:

```powershell
$env:CONTEXT_BRIDGE_CONFIG="config.hybrid.json"
python context_bridge\mcp_server_hybrid.py
```

Tool exposed:

- `search_context_hybrid()`

## Semantic RAG

Manual command:

```powershell
$env:CONTEXT_BRIDGE_CONFIG="config.semantic.json"
$env:CONTEXT_BRIDGE_VECTOR_INDEX="<workspace>\context_bridge\data\vector_index.semantic.jsonl"
$env:CONTEXT_BRIDGE_VECTOR_META="<workspace>\context_bridge\data\vector_meta.semantic.json"
$env:HF_HUB_DISABLE_PROGRESS_BARS="1"
$env:TOKENIZERS_PARALLELISM="false"
$env:TRANSFORMERS_VERBOSITY="error"
python context_bridge\mcp_server_hybrid.py
```

Tool exposed:

- `search_context_hybrid()`

## 8. Important Mode Rule

The real runtime mode is controlled by:

- server
- config
- environment variables
- MCP session startup

The prompt does **not** switch the active runtime mode by itself.

If you change mode:

1. stop the current server
2. start the new one
3. restart the AI client/session if needed
4. open a new chat

## 9. Manual MCP Client Configuration

### Normal

```toml
[mcp_servers.context_bridge]
command = "python"
args = ["<workspace>/context_bridge/mcp_server.py"]
startup_timeout_sec = 60
```

### Hybrid

```toml
[mcp_servers.context_bridge]
command = "python"
args = ["<workspace>/context_bridge/mcp_server_hybrid.py"]
startup_timeout_sec = 90
```

### Semantic

```toml
[mcp_servers.context_bridge]
command = "python"
args = ["<workspace>/context_bridge/mcp_server_hybrid.py"]
startup_timeout_sec = 180

[mcp_servers.context_bridge.env]
CONTEXT_BRIDGE_CONFIG = "config.semantic.json"
CONTEXT_BRIDGE_VECTOR_INDEX = "<workspace>/context_bridge/data/vector_index.semantic.jsonl"
CONTEXT_BRIDGE_VECTOR_META = "<workspace>/context_bridge/data/vector_meta.semantic.json"
HF_HUB_DISABLE_PROGRESS_BARS = "1"
TOKENIZERS_PARALLELISM = "false"
TRANSFORMERS_VERBOSITY = "error"
```

## 10. Verify Each Step

### Verify keyword MCP

```powershell
python context_bridge\scripts\smoke_test_mcp.py
```

### Verify hybrid MCP

```powershell
python context_bridge\scripts\smoke_test_mcp_hybrid.py
```

### Verify semantic MCP

```powershell
python context_bridge\scripts\smoke_test_mcp_hybrid_semantic.py
```

### Verify code-location quality

```powershell
python context_bridge\evals\run_code_location_eval.py
```

## 11. Dashboard

Start:

```text
context_bridge\start_dashboard.bat
```

Or manually:

```powershell
python context_bridge\dashboard_server.py
```

Open:

```text
http://127.0.0.1:8795
```

Logs:

- `context_bridge\usage\events.jsonl`
- `context_bridge\usage\outcomes.jsonl`

## 12. Practical Manual Setup Paths

### Fastest full manual path

1. install `requirements-all.txt`
2. run semantic dependency check
3. review config files
4. build keyword index
5. build semantic vector index
6. start the desired MCP server
7. configure the AI client
8. run smoke tests

### Smallest manual path for Normal Search only

1. install `requirements-base.txt`
2. review config
3. build keyword index
4. start `mcp_server.py`
5. configure MCP client for normal mode

## 13. Related Docs

- overview: [README.md](./README.md)
- full MCP setup: [HOW_TO_SETUP_MCP.md](./HOW_TO_SETUP_MCP.md)
- quick start: [Quick_mcp_setup.md](./Quick_mcp_setup.md)
