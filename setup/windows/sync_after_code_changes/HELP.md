# How updates flow: graphify update -> SAU -> CB reindex

Three separate tools. Each one only does its own job and does NOT trigger the others
automatically. If you skip a step, that step's work simply doesn't happen.

## 1. `graphify update <folder>` (run manually, by you or any AI tool)

- Touches ONE thing: the **native** `graphify-out/graph.json` inside the folder you point
  it at (e.g. `main_service/HMS/Controllers/graphify-out/graph.json`).
- Free, AST-only, offline. Never touches your custom packs.
- After it runs, that folder's `graph.json` is fresh (timestamp = now).

## 2. SAU (`sync_after_code_changes` / `run_scan.bat`)

SAU checks two different data stores and fixes only what's stale:

- **Section B — custom packs** (`graphify-out/<module>/<pack>/`, what CB actually reads
  as your project's main graph). Staleness = content hash of files listed in that pack's
  `source-files.txt` changed since the pack was last built. Option 2 rebuilds these
  automatically.
- **Section C — native folders** (scattered `graphify-out/graph.json` next to your
  source code, e.g. inside `main_service`, `main_ui`). Staleness = a source file's
  last-modified time is newer than `graph.json`'s. Option 2 runs `graphify update`
  automatically for any folder that's stale.
- **Section A — orphaned files** (files not in any pack yet). Reported only, never
  auto-fixed — needs manual/AI review.

**Why SAU sometimes reports "nothing to do":** if you (or another AI tool) already ran
`graphify update` on a folder before SAU scanned it, that folder's `graph.json` is
already fresh — there's nothing left to fix. SAU is a staleness *detector + fixer*, not
a change log. "No changes picked up" = "already in sync," not "SAU missed something."

**What SAU does NOT do:** it does not rebuild CB's search index. Rebuilding graph files
on disk is not the same as making that content searchable.

## 3. CB reindex (`setup_context_bridge.bat` / `context_bridge/scripts/setup_context_bridge.py`)

This is the only step that makes anything searchable in CB. It is a full, from-scratch
rebuild every time — it does not know or care what changed; it just reads everything
currently on disk and rebuilds fresh:

1. **Discovery** — scans `context_bridge/config.json`'s configured roots for indexable
   files: native `graph.json` / `*.enrichment.json` files, custom pack files, and any
   other configured source/doc folders. Writes `context_bridge/data/discovery_report.json`.
2. **Keyword index** — `context_bridge/src/indexer.py` reads all discovered files and
   writes `context_bridge/data/context_index.json` (the document list CB searches over).
3. **Hash vector index** — `context_bridge/rag/build_vector_index.py` embeds every chunk
   with a local, deterministic hash backend. Writes `vector_chunks.jsonl` /
   `vector_index.jsonl` / `vector_meta.json`. Required for hybrid mode.
4. **Semantic vector index** (optional, `--profile semantic` or `all`) — same thing but
   with a real local embedding model (`sentence-transformers`, `all-MiniLM-L6-v2`).
   Writes the `*.semantic.jsonl` / `vector_meta.semantic.json` files.

Every run overwrites these files completely — it does not append, and it does not skip
unchanged chunks. Chunk/document counts you see on the dashboard come from this step,
not from SAU and not from `graphify update`.

## The correct order, every time you change source code or run `graphify update` manually

1. Make/receive code changes (yours, or from `graphify update` run by any AI tool).
2. Run SAU (option 2) — catches any custom-pack drift the code change caused, and
   catches any native folder that still needs `graphify update` if nobody ran it yet.
3. Run `setup_context_bridge.bat` — the only step that updates what CB can actually
   search. Skipping this means the files on disk are correct but CB search still
   returns stale/old results.

## Quick reference — who touches what

| Tool                        | Reads                          | Writes                                          | Makes it searchable in CB? |
|------------------------------|--------------------------------|--------------------------------------------------|------------------------------|
| `graphify update <folder>`  | source files in that folder    | that folder's native `graph.json`                | No |
| SAU option 2                | `source-files.txt`, mtimes     | custom packs, native `graph.json` (via graphify update) | No |
| `setup_context_bridge.bat`  | everything currently on disk   | `context_index.json`, `vector_*.jsonl`, `vector_meta*.json` | Yes |

## Diagram

```
 code changes
      |
      v
+-----------------------+
| graphify update       |  <- you, or any AI tool
| (one native folder)   |
+-----------------------+
      |
      | refreshes that folder's graph.json
      v
+-----------------------+
| SAU (option 2)        |  <- run_scan.bat
| - rebuilds stale       |
|   custom packs (B)    |
| - runs graphify update|
|   on any folder that  |
|   is still stale (C)  |
+-----------------------+
      |
      | graph files on disk are now correct
      v
+-----------------------+
| setup_context_bridge  |  <- only step that updates search
| .bat  (CB reindex)    |
+-----------------------+
      |
      v
 CB search is now up to date
```

## One-line summary

`graphify update` and SAU keep your **graph files** correct. `setup_context_bridge.bat`
is what turns those graph files into something CB can actually **search**. All three
are separate, manual steps — none of them trigger the next one for you.
