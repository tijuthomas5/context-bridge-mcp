from __future__ import annotations

import json
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


OUTCOMES = {"success", "partial", "failed"}
FAILURE_REASONS = {
    "none",
    "bad_ranking",
    "stale_graph",
    "missing_graph_data",
    "unclear_query",
    "too_few_results",
    "ai_did_not_use_context",
}


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def usage_dir() -> Path:
    path = project_root() / "context_bridge" / "usage"
    if os.environ.get("CONTEXT_BRIDGE_TEST_MODE") == "1":
        path = path / "test"
    path.mkdir(parents=True, exist_ok=True)
    return path


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def monthly_suffix() -> str:
    now = datetime.now(timezone.utc)
    return f"{now.year}_{now.month:02d}"


def append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n")


def summarize_result(tool: str, result: dict[str, Any]) -> dict[str, Any]:
    if tool == "health_check":
        return {
            "status": result.get("status"),
            "document_count": result.get("document_count", 0),
            "ranking_profile": result.get("ranking_profile"),
        }

    files = result.get("files", []) or result.get("source_files", []) or []
    top_files = [
        item.get("path") if isinstance(item, dict) else str(item)
        for item in files[:10]
    ]
    top_files = [item for item in top_files if item]

    retrieval_mode = result.get("retrieval_mode") or infer_retrieval_mode(tool, result)
    symbol_hits = result.get("symbol_hits", []) or []
    location_hints = result.get("location_hints", []) or []
    dependency_chain = result.get("dependency_chain", []) or []
    related_files = result.get("related_files", []) or []
    analysis = result.get("analysis") if isinstance(result.get("analysis"), dict) else {}
    # Measured context size CB actually delivered to the model (chars). Cheap, no
    # file I/O — used by the dashboard to compute real token savings (char ratio).
    context_chars = _delivered_context_chars(result, symbol_hits, location_hints, dependency_chain, top_files)
    return {
        "confidence": result.get("confidence"),
        "analysis_relevance_check": analysis.get("relevance_check") or result.get("relevance_check"),
        "analysis_confidence": analysis.get("confidence") or result.get("analysis_confidence"),
        "analysis_parse_incomplete": bool(analysis.get("parse_incomplete") or result.get("analysis_parse_incomplete")),
        "analysis_parse_error": bool(analysis.get("parse_error") or result.get("analysis_parse_error")),
        "retrieval_mode": retrieval_mode,
        "rag_used": bool(result.get("used_vector", False)),
        "hybrid_profile": result.get("hybrid_profile"),
        "embedding_backend": result.get("embedding_backend"),
        "embedding_model": result.get("embedding_model"),
        "vector_candidate_count": result.get("vector_candidate_count"),
        "suppressed_vector_count": result.get("suppressed_vector_count"),
        "modules_returned": len(result.get("modules", []) or []),
        "packs_returned": len(result.get("packs", []) or []),
        "files_returned": len(files),
        "top_files": top_files,
        "primary_owner_present": bool(result.get("primary_owner")),
        "symbol_hits_returned": len(symbol_hits),
        "location_hints_returned": len(location_hints),
        "dependency_chain_returned": len(dependency_chain),
        "related_files_returned": len(related_files),
        "code_blocks_returned": len(result.get("code_blocks", []) or []),
        "ranking_profile": result.get("ranking_profile"),
        "facts_returned": len(result.get("facts", []) or []),
        "results_returned": len(result.get("results", []) or []),
        "document_count": result.get("document_count"),
        "gap_searches_fired": int(result.get("gap_searches_fired") or 0),
        "gap_files_added": int(result.get("gap_files_added") or 0),
        "context_chars": context_chars,
    }


def _delivered_context_chars(
    result: dict[str, Any],
    symbol_hits: list[Any],
    location_hints: list[Any],
    dependency_chain: list[Any],
    top_files: list[Any],
) -> int:
    """Total characters of the focused context CB delivered to the model.
    This is the 'actual' side of the token-savings ratio (baseline = full files).
    Best-effort and exception-safe — never breaks logging."""
    total = 0
    try:
        for block in result.get("code_blocks", []) or []:
            if isinstance(block, dict):
                total += len(str(block.get("code") or block.get("content") or block.get("snippet") or ""))
            else:
                total += len(str(block))
        for collection in (symbol_hits, location_hints, dependency_chain):
            for item in collection:
                total += len(json.dumps(item, ensure_ascii=False)) if isinstance(item, (dict, list)) else len(str(item))
        summary = result.get("summary")
        if not summary and isinstance(result.get("analysis"), dict):
            summary = result["analysis"].get("summary")
        total += len(str(summary or ""))
        total += sum(len(str(p)) for p in (top_files or []))
    except Exception:
        return total
    return total


def infer_retrieval_mode(tool: str, result: dict[str, Any]) -> str:
    if tool == "search_context_hybrid":
        backend = str(result.get("embedding_backend") or "").lower()
        if backend == "sentence-transformers":
            return "hybrid_semantic"
        return "hybrid_hash"
    if tool in {"search_context", "find_related_files", "find_code_locations", "get_graphify_pack", "get_module_summary"}:
        return "keyword"
    return "other"


def log_tool_event(tool: str, arguments: dict[str, Any], result: dict[str, Any], latency_ms: int) -> str:
    event_id = f"evt_{uuid.uuid4().hex[:16]}"
    query = arguments.get("query") or arguments.get("pack_name") or arguments.get("module") or ""
    event = {
        "event_id": event_id,
        "timestamp": now_utc(),
        "tool": tool,
        "query": query,
        "arguments": safe_arguments(arguments),
        "latency_ms": latency_ms,
        **summarize_result(tool, result),
    }
    append_jsonl(usage_dir() / f"events_{monthly_suffix()}.jsonl", event)
    return event_id


def safe_arguments(arguments: dict[str, Any]) -> dict[str, Any]:
    safe: dict[str, Any] = {}
    for key, value in arguments.items():
        if isinstance(value, (str, int, float, bool)) or value is None:
            safe[key] = value
    return safe


def record_outcome(
    event_id: str,
    outcome: str,
    used_suggested_files: int = 0,
    extra_files_read: int = 0,
    needed_extra_search: bool = False,
    missed_files: list[str] | None = None,
    failure_reason: str = "none",
    notes: str = "",
) -> dict[str, Any]:
    normalized_outcome = outcome.strip().lower()
    normalized_reason = failure_reason.strip().lower()
    if normalized_outcome not in OUTCOMES:
        raise ValueError(f"outcome must be one of: {', '.join(sorted(OUTCOMES))}")
    if normalized_reason not in FAILURE_REASONS:
        raise ValueError(f"failure_reason must be one of: {', '.join(sorted(FAILURE_REASONS))}")

    payload = {
        "outcome_id": f"out_{uuid.uuid4().hex[:16]}",
        "event_id": event_id,
        "timestamp": now_utc(),
        "outcome": normalized_outcome,
        "used_suggested_files": max(0, int(used_suggested_files)),
        "extra_files_read": max(0, int(extra_files_read)),
        "needed_extra_search": bool(needed_extra_search),
        "missed_files": missed_files or [],
        "missed_file_count": len(missed_files or []),
        "failure_reason": normalized_reason,
        "notes": notes[:1000],
    }
    append_jsonl(usage_dir() / f"outcomes_{monthly_suffix()}.jsonl", payload)
    return payload


def timed_call(tool: str, arguments: dict[str, Any], func: Any) -> dict[str, Any]:
    start = time.perf_counter()
    result = func()
    latency_ms = int((time.perf_counter() - start) * 1000)
    if isinstance(result, dict) and tool not in {"record_outcome", "get_usage_summary"}:
        event_id = log_tool_event(tool, arguments, result, latency_ms)
        result = {"event_id": event_id, **result}
    return result
