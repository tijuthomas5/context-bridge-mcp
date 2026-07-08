# SAU vs. Manual `graphify update`

## What SAU is

SAU (Sync After Update) is a sub-tool of ContextBridge (CB). Not a separate product —
its only job is to keep CB's data from going stale. CB is what actually answers your
AI's code questions; SAU just keeps its data fresh.

CB's data has two kinds, and SAU covers both:

- **Custom packs** at repo-root `graphify-out/<module>/<pack>/` — what CB itself reads.
- **Native `graphify-out` folders** — Graphify's own per-folder output, which can
  exist anywhere in your source tree (`main_service/graphify-out`,
  `main_service/HMS/Controllers/graphify-out`, `main_ui/src/modules/hms/api/graphify-out`,
  etc.). CB reads these too, as secondary context.

## What SAU does

Run `run_scan.bat`, pick option 2. It automatically, across your whole repo:

- Finds every stale custom pack and rebuilds it.
- **Scans your entire source tree for `graphify-out` folders wherever they exist**
  (not one fixed location) and runs `graphify update` on every stale one it finds.
- Finds files not yet in any pack and writes them to `orphan_review.json` for
  you/an AI to review (never applied automatically).

No folder names needed — it scans and finds all of this itself, wherever it is.

## What any AI running `graphify update` manually does

Refreshes native `graphify-out` data for one folder — whichever one you or the
AI points it at. That's the whole scope of that command, no matter who runs it.

It does **not**:
- know which folders are stale (you have to target it yourself)
- touch custom packs at all (CB never sees the result)
- find orphaned files

## When to use which

| Situation | Use |
|---|---|
| You changed code and want CB caught up | SAU, option 2 |
| You only want one specific native folder refreshed, right now | Manual `graphify update` on that folder |
| Before reindexing CB | SAU, option 2 (covers everything manual update doesn't) |
| Deciding which pack an orphaned file belongs to | Neither — needs human/AI judgment via `orphan_review.json` |

## Bottom line

Manual `graphify update` is a narrow, one-folder action anyone can run. SAU is the
only thing that finds staleness repo-wide, rebuilds custom packs, and surfaces
orphaned files. Running manual updates never replaces running SAU.

## Offline behavior — what's actually enforced, not just claimed

`build_pack.py` calls `graphify.extract.extract()` -- the local AST-parsing function
(unrelated to the separate `graphify extract` CLI command, which is Graphify's
paid/LLM semantic pass and is never invoked by SAU at all). To make the "no network
calls" behavior a real guarantee instead of just a doc claim, `build_pack.py` also
strips `GEMINI_API_KEY` / `GOOGLE_API_KEY` from its own process environment before
every rebuild -- those are the vars that would let graphify's extract() attempt a
networked semantic call. This was added after a code review flagged that the offline
claim wasn't enforced in code.

Also hardened: every path read from `source-files.txt` is checked to make sure it
stays inside the repo root before it's read, hashed, or copied. A tampered or
corrupted entry (e.g. `../../secret.txt`) is refused with a clear error instead of
being silently read.
