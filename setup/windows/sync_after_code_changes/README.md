# SAU (Sync After Update)

Run this whenever you've added/changed code, before ContextBridge (CB) is re-indexed.

## Why

CB only reads the custom packs in repo-root `graphify-out/<module>/<pack>/`. Those don't
update automatically when code changes — SAU detects and fixes that drift.

**Two kinds of `graphify-out` data:** "custom" = your main `graphify-out` at repo root
(what CB reads). "native" = the small `graphify-out` folders scattered inside
individual source folders (Graphify's own per-folder output). Option 2 fully
automates both. Only orphaned files (Section A) need manual/AI review.

## How to run

Double-click `run_scan.bat`. Choose:

1. **Scan and report only** — nothing changes on disk. Shows new/orphaned files, stale
   custom packs, and stale native `graphify-out` folders.
2. **Scan, then rebuild** — rebuilds stale custom packs, and runs `graphify update`
   (free, AST-only) on stale native folders. Never runs `graphify extract` (paid/LLM) —
   that stays manual.

## What Section A / B / C means, and what's automated

Both options 1 and 2 always scan and report all three sections. The difference is
only whether anything gets fixed.

- **Section A — New / Orphaned Files.** Real files not yet in any pack.
  Option 1: reported + written to `orphan_review.json`. Option 2: same — **never
  auto-fixed by either option**. Needs a human (or an AI, e.g. CB/Claude) to fill in
  `"decision"` per file and apply it as a separate step.
- **Section B — Stale Custom Packs.** Packs whose source changed since last build.
  Option 1: reported only. Option 2: rebuilt automatically, no review needed.
- **Section C — Native Graphify Folders.** The per-folder `graphify-out` data
  (e.g. inside `main_service`, `main_ui`). Option 1: reported only. Option 2:
  runs `graphify update` (free, AST-only) automatically. `graphify extract`
  (paid/LLM) is never run by either option — that stays a manual, deliberate step.

## Files

- `run_scan.bat` — entry point, use this.
- `scan_repo.py` — the scanner/rebuilder.
- `build_pack.py` — rebuilds a single custom pack (called by scan_repo.py).
- `sync_custom_packs.py` — narrower variant, custom packs only (no orphan/native checks).
- `project_map.json` — your real config (roots, extensions, excluded modules).
- `project_map.example.json` — template/reference, no project-specific data.
- `orphan_review.json` — generated each run. Lists files not yet in any pack, with a
  best-guess pack per file. Never applied automatically — review and act on it yourself.

## After running — 2 manual steps, always

1. **Orphans:** SAU/AI only suggests a pack per orphaned file. You still have to apply
   it yourself — add the file to that pack's `source-files.txt` (or create a new pack
   for `UNASSIGNED` ones), then rebuild.
2. **Reindex:** run CB's normal reindex step (`setup_context_bridge.bat`) so the
   rebuilt packs actually get picked up by CB.

## Security notes (from a code review)

- **Path containment.** Every path in `source-files.txt` is validated to stay inside
  the repo root before it's read, hashed, or copied. A tampered or corrupted entry
  (e.g. `../../secret.txt`) is refused with a clear error, not silently read.
- **Offline extraction.** `build_pack.py` strips `GEMINI_API_KEY` / `GOOGLE_API_KEY`
  from its own environment before every rebuild, so the AST-only extraction it runs
  can't accidentally go online even if your shell has those set. See `WHEN_TO_USE.md`
  for the full explanation (including the `extract()` naming collision with the
  separate, never-invoked `graphify extract` CLI command).
- **Known, not yet hardened:** this is built for trusted internal/local use, not a
  hostile multi-tenant environment. `graphify` and `python` are resolved via PATH
  (no pinned path), and large monorepos will see real (not catastrophic, but
  noticeable) scan/hash cost since each run walks the source tree a few times and
  hashes full file contents. Fine for this repo's size; worth revisiting if this
  tool is reused on a much bigger codebase.
