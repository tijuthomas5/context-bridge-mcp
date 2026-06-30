from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any
from datetime import datetime, timezone

from graphify_loader import load_config
from graphify_loader import iter_indexable_files
from models import ContextDocument
from search import load_index, project_root_from_here, search
from search import RANKING_PROFILE
from mcp_tools.usage import record_outcome as save_outcome
from mcp_tools.usage import timed_call

MAX_QUERY_CHARS = 8000


def _project_root() -> Path:
    return project_root_from_here()


def graph_hint_guardrails(tool_name: str) -> dict[str, Any]:
    return {
        "graph_hint": True,
        "verification_required": True,
        "source_of_truth": [
            "read the actual source files",
            "verify runtime behavior separately when debugging production issues",
        ],
        "verification_guidance": [
            "Treat Graphify and ContextBridge as a routing hint, not proof.",
            "Open the suggested owner file and verify the symbol or line hint in source.",
            "If the suggested symbol is incomplete, inspect related files and dependency links next.",
            "If the flow still looks incomplete or inconsistent, fall back to normal repo search.",
        ],
        "fallback_guidance": {
            "when_to_expand": [
                "owner file does not contain the expected logic",
                "symbol hint exists but runtime flow continues elsewhere",
                "cross-module behavior is only partially explained",
            ],
            "next_steps": [
                "read related_files first",
                "follow dependency_chain next",
                "then run broader file search if needed",
            ],
        },
        "tool": tool_name,
    }


_cached_docs: tuple[Path, dict[str, Any], list[ContextDocument]] | None = None
_stale_cache: dict[str, object] = {"is_stale": False, "checked_at": 0.0}
_STALE_TTL = 60.0


def _get_stale_status() -> bool:
    now = time.monotonic()
    if now - float(_stale_cache["checked_at"]) < _STALE_TTL:
        return bool(_stale_cache["is_stale"])
    try:
        root = _project_root()
        config = load_config(root)
        index_rel = Path("context_bridge") / config.get("index_path", "data/context_index.json")
        index_path = root / index_rel
        if not index_path.exists():
            result = True
        else:
            payload = json.loads(index_path.read_text(encoding="utf-8"))
            indexed_files = [path for path, _ in iter_indexable_files(root, config)]
            latest_src = max((p.stat().st_mtime for p in indexed_files), default=0.0)
            index_src = float(payload.get("latest_source_mtime") or 0.0)
            result = latest_src > index_src + 1
    except Exception:
        result = False
    _stale_cache.update({"is_stale": result, "checked_at": now})
    return result


def _load_docs() -> tuple[Path, dict[str, Any], list[ContextDocument]]:
    global _cached_docs
    if _cached_docs is None:
        root = _project_root()
        config = load_config(root)
        docs = load_index(root, config)
        _cached_docs = (root, config, docs)
    return _cached_docs


def health_check() -> dict[str, Any]:
    root = _project_root()
    config = load_config(root)
    index_rel = Path("context_bridge") / config.get("index_path", "data/context_index.json")
    index_path = root / index_rel
    if not index_path.exists():
        return {
            "status": "missing_index",
            "index_path": str(index_path),
            "message": "Run: python context_bridge/src/indexer.py",
        }
    payload = json.loads(index_path.read_text(encoding="utf-8"))
    indexed_files = [path for path, _ in iter_indexable_files(root, config)]
    latest_source_mtime = max((path.stat().st_mtime for path in indexed_files), default=0.0)
    index_latest_mtime = float(payload.get("latest_source_mtime") or 0.0)
    is_stale = latest_source_mtime > index_latest_mtime + 1
    return {
        "status": "stale" if is_stale else "ok",
        "document_count": payload.get("document_count", 0),
        "source_file_count": payload.get("source_file_count", 0),
        "created_at": payload.get("created_at"),
        "latest_source_mtime": latest_source_mtime,
        "latest_source_time": datetime.fromtimestamp(latest_source_mtime, timezone.utc).isoformat() if latest_source_mtime else None,
        "is_stale": is_stale,
        "index_path": str(index_path),
        "workspace_root": payload.get("workspace_root"),
        "ranking_profile": RANKING_PROFILE,
    }


def search_context(query: str, max_results: int = 8) -> dict[str, Any]:
    result = search(query, max_results=max_results)
    return {
        "query": result.get("query"),
        "confidence": result.get("confidence"),
        "modules": result.get("modules", []),
        "packs": result.get("packs", []),
        "files": result.get("files", []),
        "facts": result.get("facts", []),
        "primary_owner": result.get("primary_owner"),
        "symbol_hits": result.get("symbol_hits", []),
        "location_hints": result.get("location_hints", []),
        "dependency_chain": result.get("dependency_chain", []),
        "related_files": result.get("related_files", []),
        "code_blocks": result.get("code_blocks", []),
        "results": result.get("results", []),
        "ranking_profile": result.get("ranking_profile"),
        **graph_hint_guardrails("search_context"),
    }


def find_related_files(query: str, max_results: int = 20) -> dict[str, Any]:
    search_docs = max(10, min(50, max_results * 2))
    result = search(query, max_results=search_docs, max_files=max_results)
    return {
        "query": query,
        "confidence": result.get("confidence"),
        "files": result.get("files", [])[:max_results],
        "primary_owner": result.get("primary_owner"),
        "symbol_hits": result.get("symbol_hits", [])[: min(max_results, 12)],
        "location_hints": result.get("location_hints", [])[: min(max_results, 12)],
        "dependency_chain": result.get("dependency_chain", [])[: min(max_results, 12)],
        "related_files": result.get("related_files", [])[:max_results],
        "code_blocks": result.get("code_blocks", [])[: min(max_results, 6)],
        "modules": result.get("modules", [])[:5],
        "packs": result.get("packs", [])[:8],
        "searched_documents": search_docs,
        "files_returned": len(result.get("files", [])[:max_results]),
        "ranking_profile": result.get("ranking_profile"),
        **graph_hint_guardrails("find_related_files"),
    }


def find_code_locations(query: str, max_results: int = 8) -> dict[str, Any]:
    result = search(query, max_results=max_results, max_files=max(max_results * 2, max_results))
    files = result.get("files", [])[:max_results]
    symbol_hits = result.get("symbol_hits", [])[: max_results * 2]
    location_hints = result.get("location_hints", [])[: max_results * 2]
    dependency_chain = result.get("dependency_chain", [])[: max_results * 2]
    related_files = result.get("related_files", [])[: max_results * 2]
    primary_owner = result.get("primary_owner")
    return {
        "query": query,
        "confidence": result.get("confidence"),
        "primary_owner": primary_owner,
        "owner_files": files,
        "symbol_hits": symbol_hits,
        "location_hints": location_hints,
        "dependency_chain": dependency_chain,
        "related_files": related_files,
        "code_blocks": result.get("code_blocks", [])[: min(max_results, 6)],
        "modules": result.get("modules", [])[:5],
        "packs": result.get("packs", [])[:8],
        "ranking_profile": result.get("ranking_profile"),
        **graph_hint_guardrails("find_code_locations"),
    }


def get_module_summary(module: str, pack: str | None = None, max_results: int = 12) -> dict[str, Any]:
    _, _, docs = _load_docs()
    module_lower = module.lower().strip()
    pack_lower = pack.lower().strip() if pack else None
    matches: list[ContextDocument] = []
    for doc in docs:
        if (doc.module or "").lower() != module_lower:
            continue
        if pack_lower and (doc.pack or "").lower() != pack_lower:
            continue
        matches.append(doc)

    if not matches and not pack_lower:
        # Fall back to substring module matches for mixed casing and assistant paths.
        for doc in docs:
            if module_lower in (doc.path or "").lower():
                matches.append(doc)

    ranked = sorted(matches, key=lambda d: source_priority(d.source_type), reverse=True)[:max_results]
    summary = summarize_docs(module=module, pack=pack, docs=ranked)
    summary.update(graph_hint_guardrails("get_module_summary"))
    return summary


def get_graphify_pack(pack_name: str, module: str | None = None, max_results: int = 20) -> dict[str, Any]:
    _, _, docs = _load_docs()
    pack_lower = pack_name.lower().strip()
    module_lower = module.lower().strip() if module else None
    matches: list[ContextDocument] = []
    for doc in docs:
        doc_pack = (doc.pack or "").lower()
        doc_module = (doc.module or "").lower()
        if doc_pack != pack_lower and pack_lower not in doc.path.lower():
            continue
        if module_lower and doc_module != module_lower:
            continue
        matches.append(doc)

    ranked = sorted(matches, key=lambda d: source_priority(d.source_type), reverse=True)[:max_results]
    summary = summarize_docs(module=module, pack=pack_name, docs=ranked)
    summary.update(graph_hint_guardrails("get_graphify_pack"))
    return summary


def get_usage_summary() -> dict[str, Any]:
    try:
        from scripts.build_dashboard_stats import build_stats
    except ModuleNotFoundError:
        import sys

        scripts_path = _project_root() / "context_bridge" / "scripts"
        sys.path.insert(0, str(scripts_path))
        from build_dashboard_stats import build_stats

    return build_stats()


def source_priority(source_type: str) -> int:
    priorities = {
        "GRAPH_REPORT.md": 100,
        "index.md": 90,
        "scope-summary.md": 80,
        "source-files.txt": 75,
        "behavior pack": 70,
        "graph.json": 60,
        "manifest.json": 40,
    }
    return priorities.get(source_type, 20)


def summarize_docs(module: str | None, pack: str | None, docs: list[ContextDocument]) -> dict[str, Any]:
    files: list[dict[str, Any]] = []
    facts: list[dict[str, Any]] = []
    sources: list[dict[str, Any]] = []
    seen_files: set[str] = set()
    seen_facts: set[str] = set()

    for doc in docs:
        sources.append({
            "source": doc.source,
            "source_type": doc.source_type,
            "module": doc.module,
            "pack": doc.pack,
        })
        for file_path in doc.files:
            key = file_path.lower()
            if key in seen_files:
                continue
            seen_files.add(key)
            files.append({
                "path": file_path,
                "source": doc.source,
                "source_type": doc.source_type,
            })
        for fact in doc.facts:
            key = fact.lower()
            if key in seen_facts:
                continue
            seen_facts.add(key)
            facts.append({
                "fact": fact,
                "source": doc.source,
                "source_type": doc.source_type,
            })

    summary = []
    for doc in docs:
        if doc.source_type in {"GRAPH_REPORT.md", "index.md", "scope-summary.md", "behavior pack"}:
            snippet = first_useful_lines(doc.text, limit=4)
            if snippet:
                summary.append({
                    "text": snippet,
                    "source": doc.source,
                    "source_type": doc.source_type,
                })
        if len(summary) >= 5:
            break

    return {
        "module": module,
        "pack": pack,
        "document_count": len(docs),
        "summary": summary,
        "source_files": files[:80],
        "facts": facts[:40],
        "sources": sources,
    }


def first_useful_lines(text: str, limit: int = 4) -> str:
    lines: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith(("```", "|")):
            continue
        if line.startswith("#"):
            continue
        lines.append(line)
        if len(lines) >= limit:
            break
    return "\n".join(lines)


def clean_query(value: Any, field: str = "query") -> str:
    query = str(value or "").strip()
    if not query:
        raise ValueError(f"{field} is required.")
    if len(query) > MAX_QUERY_CHARS:
        raise ValueError(f"{field} must be {MAX_QUERY_CHARS} characters or fewer.")
    return query


def clamp_int(value: Any, default: int, minimum: int, maximum: int, field: str) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = default
    return max(minimum, min(maximum, number))


def tool_error(message: str, name: str) -> dict[str, Any]:
    return {
        "error": message,
        "tool": name,
        "results": [],
        "files": [],
        "facts": [],
        "confidence": 0.0,
    }


TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "name": "health_check",
        "description": "Check whether the ContextBridge index exists and is ready.",
        "inputSchema": {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
    },
    {
        "name": "search_context",
        "description": "Search Graphify and curated assistant context for relevant modules, packs, files, facts, and source provenance.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "max_results": {"type": "integer", "minimum": 1, "maximum": 25, "default": 8},
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    },
    {
        "name": "find_related_files",
        "description": "Return a compact list of likely relevant source files for a query.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "max_results": {"type": "integer", "minimum": 1, "maximum": 80, "default": 20},
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    },
    {
        "name": "find_code_locations",
        "description": "Return likely owner files, symbols, line hints, and dependency links for implementation tracing.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "max_results": {"type": "integer", "minimum": 1, "maximum": 25, "default": 8},
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    },
    {
        "name": "get_module_summary",
        "description": "Return summary, source files, facts, and sources for a known module, optionally scoped to a pack.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "module": {"type": "string"},
                "pack": {"type": "string"},
                "max_results": {"type": "integer", "minimum": 1, "maximum": 50, "default": 12},
            },
            "required": ["module"],
            "additionalProperties": False,
        },
    },
    {
        "name": "get_graphify_pack",
        "description": "Return summary, source manifest, facts, and provenance for a known Graphify pack.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "pack_name": {"type": "string"},
                "module": {"type": "string"},
                "max_results": {"type": "integer", "minimum": 1, "maximum": 80, "default": 20},
            },
            "required": ["pack_name"],
            "additionalProperties": False,
        },
    },
    {
        "name": "record_outcome",
        "description": "Record whether a prior ContextBridge result helped, failed, or required extra file reads.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "event_id": {"type": "string"},
                "outcome": {"type": "string", "enum": ["success", "partial", "failed"]},
                "used_suggested_files": {"type": "integer", "minimum": 0, "default": 0},
                "extra_files_read": {"type": "integer", "minimum": 0, "default": 0},
                "needed_extra_search": {"type": "boolean", "default": False},
                "missed_files": {"type": "array", "items": {"type": "string"}, "default": []},
                "failure_reason": {
                    "type": "string",
                    "enum": [
                        "none",
                        "bad_ranking",
                        "stale_graph",
                        "missing_graph_data",
                        "unclear_query",
                        "too_few_results",
                        "ai_did_not_use_context"
                    ],
                    "default": "none"
                },
                "notes": {"type": "string", "default": ""},
            },
            "required": ["event_id", "outcome"],
            "additionalProperties": False,
        },
    },
    {
        "name": "get_usage_summary",
        "description": "Return dashboard-style usage and quality statistics from ContextBridge logs.",
        "inputSchema": {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
    },
]


def call_tool(name: str, arguments: dict[str, Any] | None) -> dict[str, Any]:
    args = arguments or {}
    try:
        if name == "health_check":
            return timed_call(name, args, health_check)
        if name == "search_context":
            query = clean_query(args.get("query"))
            max_results = clamp_int(args.get("max_results"), 8, 1, 25, "max_results")
            return timed_call(name, args, lambda: search_context(query, max_results))
        if name == "find_related_files":
            query = clean_query(args.get("query"))
            max_results = clamp_int(args.get("max_results"), 20, 1, 80, "max_results")
            return timed_call(name, args, lambda: find_related_files(query, max_results))
        if name == "find_code_locations":
            query = clean_query(args.get("query"))
            max_results = clamp_int(args.get("max_results"), 8, 1, 25, "max_results")
            return timed_call(name, args, lambda: find_code_locations(query, max_results))
        if name == "get_module_summary":
            module = clean_query(args.get("module"), "module")
            max_results = clamp_int(args.get("max_results"), 12, 1, 50, "max_results")
            return timed_call(name, args, lambda: get_module_summary(
                module=module,
                pack=str(args["pack"]).strip() if args.get("pack") else None,
                max_results=max_results,
            ))
        if name == "get_graphify_pack":
            pack_name = clean_query(args.get("pack_name"), "pack_name")
            max_results = clamp_int(args.get("max_results"), 20, 1, 80, "max_results")
            return timed_call(name, args, lambda: get_graphify_pack(
                pack_name=pack_name,
                module=str(args["module"]).strip() if args.get("module") else None,
                max_results=max_results,
            ))
        if name == "record_outcome":
            return save_outcome(
                event_id=clean_query(args.get("event_id"), "event_id"),
                outcome=clean_query(args.get("outcome"), "outcome"),
                used_suggested_files=clamp_int(args.get("used_suggested_files"), 0, 0, 1000, "used_suggested_files"),
                extra_files_read=clamp_int(args.get("extra_files_read"), 0, 0, 1000, "extra_files_read"),
                needed_extra_search=bool(args.get("needed_extra_search", False)),
                missed_files=list(args.get("missed_files") or [])[:100],
                failure_reason=str(args.get("failure_reason", "none")),
                notes=str(args.get("notes", ""))[:1000],
            )
        if name == "get_usage_summary":
            return get_usage_summary()
        raise ValueError(f"Unknown tool: {name}")
    except Exception as exc:
        import sys
        import traceback
        print(f"[ContextBridge] tool error in {name}: {type(exc).__name__}: {exc}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        return tool_error(f"{type(exc).__name__}: {exc}", name)
