# ContextBridge Limitations

This file lists the practical limits of ContextBridge so users do not overclaim what it can do.

## 1. Retrieval quality depends on Graphify data

ContextBridge can only rank what exists in the indexed Graphify data.

If Graphify is missing:

- owner files
- bridge files
- runtime consumers
- dependency edges
- fresh source coverage

then ContextBridge can miss the real fixing path even if the code exists in the repo.

## 2. New projects may need project-specific profile tuning

The engine is generic, but good retrieval on a real project often depends on project rules such as:

- owner-file boosting
- module routing
- keyword aliases
- noise suppression
- pack selection

Without that tuning, repeated symptom-style questions may drift to the wrong module or under-rank the true owner files.

## 3. Broad or multi-module questions can increase drift

ContextBridge works best when the question describes:

- one workflow
- one symptom
- one expected vs actual behavior

Very broad narratives, mixed symptoms, or multi-module incident descriptions can pull in adjacent modules and reduce owner precision.

## 4. Local AI helps rerank, but it does not replace retrieval quality

The local AI analysis stage summarizes and reranks retrieved files.

It does not fix:

- missing Graphify coverage
- weak project rules
- stale indexes
- wrong-domain initial retrieval

If the right files were not retrieved strongly enough, the local AI may still produce a weak result.

## 5. Semantic and hybrid quality depends on setup

Semantic and hybrid performance depends on:

- semantic dependencies being installed
- semantic indexes being built
- the active server mode
- the local model quality and speed

If semantic setup is incomplete, results may fall back toward keyword-heavy behavior.

## 6. Returned files are guidance, not a guarantee of completeness

A returned result can be useful without being complete.

Developers should still verify whether the result includes:

- the main owner file
- the execution/runtime file
- the controller or entrypoint
- the main bridge file if frontend and backend are both involved

## 7. Cross-domain and runtime issues are harder than single-owner issues

Questions involving config-to-runtime behavior, scheduler jobs, notifications, workflow bridges, or frontend/backend handoffs are harder than direct owner-file lookups.

These cases usually need stronger Graphify dependency coverage and better project routing rules.

## 8. ContextBridge is not plug-and-perfect for every repo shape

If a project uses unusual structure, weak naming, thin service layers, or inconsistent Graphify packs, ContextBridge may still work but usually needs:

- better Graphify pack design
- better ownership edges
- project aliases
- routing rules matched to that repo

## 9. Dashboard metrics are only as honest as the grading rules

A retrieval hit should not automatically be treated as a full success.

Pass/fail reporting is meaningful only when the grading rules check for:

- true owner presence
- affected module coverage
- missing bridge/runtime files
- wrong-domain drift

The `needs_review` / `likely_good` split also depends partly on whether the calling AI reports real usage via `record_outcome`'s optional `used_suggested_files`/`extra_files_read` fields. This reporting is optional and left to the user/AI's discretion — if the user decides not to have the AI record this, CB evaluates the result using its own retrieval-quality signals instead.

## 10. Best-use recommendation

ContextBridge is strongest as a repository retrieval and narrowing system for real engineering work.

It should be presented as:

- retrieval + ranking + developer guidance

not as:

- guaranteed root-cause detection
- guaranteed complete file coverage
- zero-tuning universal repository intelligence
