from __future__ import annotations

import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from graphify_loader import load_config
from mcp_tools.tools import clamp_int, clean_query, graph_hint_guardrails, tool_error, _get_stale_status
from mcp_tools.usage import timed_call, log_tool_event
from search import RANKING_PROFILE, search, select_primary_owner, extract_symbol_hits, extract_location_hints, is_low_value_symbol, tokenize
from cb_profiles import load_profile

from context_bridge.rag.hybrid_search import HybridSearchRequest, execute_hybrid_search
from context_bridge.rag.rules_loader import load_ranking_rules
from context_bridge.rag.vector_store import read_manifest


ALLOWED_RETRIEVAL_MODES = {"keyword", "hybrid", "semantic"}
SUPPORTED_FUSION_STRATEGIES = {"weighted_rrf"}

# Server-side cache of full retrieval payloads keyed by event_id.
# Allows analyze_context to receive the complete retrieval even after
# the MCP response has been slimmed for Claude's context window.
_FULL_RETRIEVAL_CACHE: dict[str, tuple[dict, float]] = {}
_RETRIEVAL_CACHE_TTL = 600.0  # 10 minutes

# The actionable retrieval Claude needs to act, in EVERY pipeline mode (simple,
# validated, iterative, full) regardless of whether local AI ran. CB always delivers
# this base payload; the AI `analysis` (when present) is attached on top, never a
# replacement. Keeps ranked files, extracted symbols/line numbers, real code blocks,
# dependency chain and the verification guidance. Pure pre-fusion debug payloads
# (keyword_files/vector_candidates/results/diagnostics) and runtime metadata are dropped.
_ACTIONABLE_FIELDS = frozenset({
    "event_id", "query", "confidence", "retrieval_mode", "mode",
    "query_profile", "used_vector", "message",
    "modules", "packs", "facts",
    "primary_owner", "files", "symbol_hits", "location_hints",
    "dependency_chain", "related_files", "code_blocks",
    "graph_hint", "verification_required", "source_of_truth",
    "verification_guidance", "fallback_guidance",
    "is_stale", "stale_hint",
})


@dataclass(frozen=True)
class HybridRuntimeConfig:
    default_mode: str
    project_profile: str
    rules_root: str
    ranking_rules: dict[str, Any]
    top_k_keyword: int
    top_k_vector: int
    protected_keyword_count: int
    keyword_weight: float
    vector_weight: float
    require_scope_match: bool
    min_vector_score: float
    fusion_strategy: str
    search_max_results: int
    search_max_files: int


def search_context_hybrid(
    query: str,
    max_results: int | None = None,
    max_files: int | None = None,
    top_k_vector: int | None = None,
    protected_keyword_count: int | None = None,
) -> dict[str, Any]:
    runtime = load_hybrid_runtime_config()
    output_max_results = clamp_int(max_results, runtime.search_max_results, 1, 25, "max_results")
    output_max_files = clamp_int(max_files, runtime.search_max_files, 1, 40, "max_files")
    vector_limit = clamp_int(top_k_vector, runtime.top_k_vector, 1, 40, "top_k_vector")
    protected_keywords = clamp_int(
        protected_keyword_count,
        runtime.protected_keyword_count,
        0,
        40,
        "protected_keyword_count",
    )
    keyword_candidate_limit = max(output_max_files, runtime.top_k_keyword)
    keyword_doc_limit = max(output_max_results, runtime.search_max_results, keyword_candidate_limit)

    keyword_payload = search(query, max_results=keyword_doc_limit, max_files=keyword_candidate_limit)
    keyword_candidates = keyword_file_candidates(keyword_payload)
    default_mode = runtime.default_mode
    query_intents = list(keyword_payload.get("query_intents", []))
    vector_index_path = vector_index_path_from_env()
    vector_manifest_path = vector_manifest_path_from_env()
    hybrid = execute_hybrid_search(
        HybridSearchRequest(
            query=query,
            mode=default_mode,
            query_terms=keyword_payload.get("query_terms", []),
            query_intents=query_intents,
            top_k_keyword=keyword_candidate_limit,
            top_k_vector=vector_limit,
            keyword_candidates=keyword_candidates,
            protected_keyword_count=protected_keywords,
            keyword_weight=runtime.keyword_weight,
            vector_weight=runtime.vector_weight,
            require_scope_match=runtime.require_scope_match,
            min_vector_score=runtime.min_vector_score,
            fusion_strategy=runtime.fusion_strategy,
            vector_index_path=vector_index_path,
            vector_manifest_path=vector_manifest_path,
            embedding_backend=os.environ.get("CONTEXT_BRIDGE_EMBEDDING_BACKEND"),
            embedding_model=os.environ.get("CONTEXT_BRIDGE_EMBEDDING_MODEL"),
            project_rules=runtime.ranking_rules,
            low_signal_terms=list(_active_hybrid_profile().low_signal_terms()),
            noise_files=_active_hybrid_profile().noise_files(),
        )
    )
    manifest = read_manifest(vector_manifest_path)
    embedding_backend = manifest.embedding_backend if manifest else "unknown"
    embedding_model = manifest.embedding_model if manifest else "unknown"
    retrieval_mode = resolve_retrieval_mode_label(default_mode, embedding_backend)
    _is_stale = _get_stale_status()

    # Pack injection: pull all files from matching Graphify pack source-files.txt.
    # This guarantees CB never misses a file that Graphify already indexed for a matched intent.
    _profile = _active_hybrid_profile()
    _graphify_root = str(Path(PROJECT_ROOT()) / "graphify-out")
    _pack_files = _profile.pack_files_for_intents(keyword_payload.get("query_terms", []), _graphify_root)
    _fused_base = list(hybrid.fused_candidates)
    _existing_norm = {str(item.get("path") or "").replace("\\", "/").lower() for item in _fused_base if item.get("path")}
    # Give pack-injected files the median fused score so they compete in the ranked list
    # rather than being appended as dead weight at position 13+.
    _fused_scores = [float(item.get("score") or 0.0) for item in _fused_base if item.get("score")]
    _pack_base_score = float(sorted(_fused_scores)[len(_fused_scores) // 2]) if _fused_scores else 1.0
    _pack_injected = [
        {"path": p, "score": _pack_base_score, "source": "graphify_pack"}
        for p in _pack_files
        if p.replace("\\", "/").lower() not in _existing_norm
    ]
    # Merge and re-sort so pack files compete for top positions by score.
    fused_candidates_extended = sorted(
        _fused_base + _pack_injected,
        key=lambda x: float(x.get("score") or 0.0),
        reverse=True,
    )

    fused_paths = {
        str(item.get("path") or "").replace("\\", "/").lower()
        for item in fused_candidates_extended
        if str(item.get("path") or "").strip()
    }
    filtered_symbol_hits = [
        item
        for item in keyword_payload.get("symbol_hits", [])
        if str(item.get("path") or "").replace("\\", "/").lower() in fused_paths
    ]

    # Pull symbol hints for pack-injected files that the keyword search never ranked.
    # These files are in the candidate list but had no symbol hits because they weren't
    # in the keyword search results — extract them directly from the index.
    if _pack_injected:
        _pack_norm_paths = {p.replace("\\", "/").lower() for p in _pack_files if p.replace("\\", "/").lower() not in _existing_norm}
        filtered_symbol_hits = _inject_pack_symbol_hints(filtered_symbol_hits, _pack_norm_paths)
    # Inject symbols for top-ranked files that pins elevated but keyword search never saw.
    # Without this, a file at rank #1 via pins shows zero symbols despite being the root cause.
    _hits_with_symbols = {str(h.get("path") or "").replace("\\", "/").lower() for h in filtered_symbol_hits}
    _top_unseen = {
        str(item.get("path") or "").replace("\\", "/").lower()
        for item in fused_candidates_extended[:6]
        if str(item.get("path") or "").replace("\\", "/").lower() not in _hits_with_symbols
        and str(item.get("path") or "").strip()
    }
    if _top_unseen:
        filtered_symbol_hits = _inject_pack_symbol_hints(filtered_symbol_hits, _top_unseen)
    filtered_location_hints = [
        item
        for item in keyword_payload.get("location_hints", [])
        if str(item.get("path") or "").replace("\\", "/").lower() in fused_paths
    ]
    filtered_dependency_chain = [
        item
        for item in keyword_payload.get("dependency_chain", [])
        if (
            str(item.get("source_file") or "").replace("\\", "/").lower() in fused_paths
            or str(item.get("target_file") or "").replace("\\", "/").lower() in fused_paths
        )
    ]
    filtered_related_files = [
        item
        for item in keyword_payload.get("related_files", [])
        if str(item or "").replace("\\", "/").lower() in fused_paths
    ]
    filtered_code_blocks = [
        item
        for item in keyword_payload.get("code_blocks", [])
        if str(item.get("path") or "").replace("\\", "/").lower() in fused_paths
    ]
    fused_order = {
        str(item.get("path") or "").replace("\\", "/").lower(): index
        for index, item in enumerate(fused_candidates_extended[:output_max_files])
    }
    primary_owner = select_primary_owner(
        filtered_symbol_hits or keyword_payload.get("symbol_hits", []),
        fused_order,
        tokenize(query),
        fused_paths,
    )
    return {
        "query": query,
        "confidence": keyword_payload.get("confidence"),
        "retrieval_mode": retrieval_mode,
        "mode": hybrid.mode,
        "query_profile": hybrid.diagnostics.get("query_profile"),
        "used_vector": hybrid.used_vector,
        "message": hybrid.message,
        "modules": keyword_payload.get("modules", []),
        "packs": keyword_payload.get("packs", []),
        "files": fused_candidates_extended[:output_max_files],
        "keyword_files": keyword_candidates[:output_max_files],
        "vector_candidates": hybrid.vector_candidates[:output_max_files],
        "suppressed_vector_candidates": hybrid.suppressed_vector_candidates[:3],
        "facts": keyword_payload.get("facts", []),
        "primary_owner": primary_owner,
        "symbol_hits": filtered_symbol_hits or keyword_payload.get("symbol_hits", []),
        "location_hints": extract_location_hints(filtered_symbol_hits) if filtered_symbol_hits else (filtered_location_hints or keyword_payload.get("location_hints", [])),
        "dependency_chain": filtered_dependency_chain or keyword_payload.get("dependency_chain", []),
        "related_files": filtered_related_files or keyword_payload.get("related_files", []),
        "code_blocks": filtered_code_blocks or keyword_payload.get("code_blocks", []),
        "results": keyword_payload.get("results", [])[:output_max_results],
        "diagnostics": hybrid.diagnostics,
        "vector_candidate_count": len(hybrid.vector_candidates),
        "suppressed_vector_count": len(hybrid.suppressed_vector_candidates),
        "embedding_backend": embedding_backend,
        "embedding_model": embedding_model,
        "vector_index_path": str(vector_index_path),
        "vector_manifest_path": str(vector_manifest_path),
        "is_stale": _is_stale,
        "stale_hint": "Run: python context_bridge/src/indexer.py" if _is_stale else None,
        "ranking_profile": RANKING_PROFILE,
        "hybrid_profile": "guarded-keyword-owner-first-v1",
        "configured_default_mode": default_mode,
        "runtime_config": {
            "top_k_keyword": runtime.top_k_keyword,
            "top_k_vector": runtime.top_k_vector,
            "protected_keyword_count": runtime.protected_keyword_count,
            "keyword_weight": runtime.keyword_weight,
            "vector_weight": runtime.vector_weight,
            "require_scope_match": runtime.require_scope_match,
            "min_vector_score": runtime.min_vector_score,
            "fusion_strategy": runtime.fusion_strategy,
            "search_max_results": runtime.search_max_results,
            "search_max_files": runtime.search_max_files,
            "applied_max_results": output_max_results,
            "applied_max_files": output_max_files,
            "applied_top_k_vector": vector_limit,
            "applied_protected_keyword_count": protected_keywords,
            "keyword_candidate_limit": keyword_candidate_limit,
            "query_intents": query_intents,
            "query_profile": hybrid.diagnostics.get("query_profile"),
            "project_profile": runtime.project_profile,
            "semantic_rule_count": len((runtime.ranking_rules or {}).get("semantic_rules", [])),
        },
        **graph_hint_guardrails("search_context_hybrid"),
    }


def find_code_locations_hybrid(query: str, max_results: int | None = None) -> dict[str, Any]:
    output_limit = clamp_int(max_results, 8, 1, 25, "max_results")
    result = search_context_hybrid(
        query=query,
        max_results=output_limit,
        max_files=output_limit,
    )
    files = result.get("files", [])[:output_limit]
    return {
        "query": query,
        "confidence": result.get("confidence"),
        "retrieval_mode": result.get("retrieval_mode"),
        "mode": result.get("mode"),
        "query_profile": result.get("query_profile"),
        "used_vector": result.get("used_vector"),
        "primary_owner": result.get("primary_owner"),
        "owner_files": files,
        "symbol_hits": result.get("symbol_hits", [])[: output_limit * 2],
        "location_hints": result.get("location_hints", [])[: output_limit * 2],
        "dependency_chain": result.get("dependency_chain", [])[: output_limit * 2],
        "related_files": result.get("related_files", [])[: output_limit * 2],
        "code_blocks": result.get("code_blocks", [])[: min(output_limit, 6)],
        "modules": result.get("modules", [])[:5],
        "packs": result.get("packs", [])[:8],
        "diagnostics": result.get("diagnostics", {}),
        "ranking_profile": result.get("ranking_profile"),
        "hybrid_profile": result.get("hybrid_profile"),
        "runtime_config": result.get("runtime_config", {}),
        **graph_hint_guardrails("find_code_locations"),
    }


@lru_cache(maxsize=4)
def _load_runtime_config(config_name: str) -> dict[str, Any]:
    # config_name is used as the cache key AND passed to load_config so the
    # cached value is always consistent with the name that was requested.
    return load_config(PROJECT_ROOT(), config_name)


_HYBRID_PROFILE_CACHE: dict[str, Any] = {}


def _active_hybrid_profile():
    """Return the ranking profile plugin for the current config (cached per config+profile key).
    CONTEXT_BRIDGE_PROFILE env var overrides config's project_profile without editing files."""
    profile_env = (os.environ.get("CONTEXT_BRIDGE_PROFILE") or "").strip().lower()
    config_name = _active_config_name()
    cache_key = f"{config_name}:{profile_env}"
    if cache_key in _HYBRID_PROFILE_CACHE:
        return _HYBRID_PROFILE_CACHE[cache_key]
    if profile_env:
        project_profile = profile_env
        rules_root = "context_bridge/rules"
    else:
        config = _load_runtime_config(config_name)
        project_profile = str(config.get("project_profile") or "").strip().lower() or "default"
        rules_root = str(config.get("rules_root") or "context_bridge/rules").replace("\\", "/").strip().strip("/") or "context_bridge/rules"
    prof = load_profile(PROJECT_ROOT(), rules_root, project_profile)
    _HYBRID_PROFILE_CACHE[cache_key] = prof
    return prof


def _active_config_name() -> str:
    """Single source of truth for the active config file name."""
    return (os.environ.get("CONTEXT_BRIDGE_CONFIG") or "config.hybrid.json").strip() or "config.hybrid.json"


def configured_retrieval_mode() -> str:
    env_value = (os.environ.get("CONTEXT_BRIDGE_RETRIEVAL_MODE") or "").strip().lower()
    if env_value in ALLOWED_RETRIEVAL_MODES:
        return env_value
    config = _load_runtime_config(_active_config_name())
    rag = config.get("rag") or {}
    if rag.get("enabled") is False:
        return "keyword"
    configured = str(rag.get("default_mode") or "hybrid").strip().lower()
    if configured in ALLOWED_RETRIEVAL_MODES:
        return configured
    return "hybrid"


def load_hybrid_runtime_config() -> HybridRuntimeConfig:
    config = _load_runtime_config(_active_config_name())
    rag = config.get("rag") or {}
    search_config = config.get("search") or {}
    default_mode = configured_retrieval_mode()
    fusion_strategy = str(rag.get("fusion_strategy") or "weighted_rrf").strip().lower() or "weighted_rrf"
    if fusion_strategy not in SUPPORTED_FUSION_STRATEGIES:
        fusion_strategy = "weighted_rrf"
    profile_env = (os.environ.get("CONTEXT_BRIDGE_PROFILE") or "").strip().lower()
    if profile_env:
        project_profile = profile_env
        rules_root = str(config.get("rules_root") or "context_bridge/rules").replace("\\", "/").strip().strip("/") or "context_bridge/rules"
    else:
        project_profile = str(config.get("project_profile") or "").strip().lower() or "default"
        rules_root = str(config.get("rules_root") or "context_bridge/rules").replace("\\", "/").strip().strip("/") or "context_bridge/rules"
    ranking_rules = load_ranking_rules(str(PROJECT_ROOT()), rules_root, project_profile)
    return HybridRuntimeConfig(
        default_mode=default_mode,
        project_profile=project_profile,
        rules_root=rules_root,
        ranking_rules=ranking_rules,
        top_k_keyword=clamp_int(rag.get("top_k_keyword"), 20, 1, 60, "top_k_keyword"),
        top_k_vector=clamp_int(rag.get("top_k_vector"), 12, 1, 60, "top_k_vector"),
        protected_keyword_count=clamp_int(rag.get("protected_keyword_count"), 8, 0, 60, "protected_keyword_count"),
        keyword_weight=clamp_float(rag.get("keyword_weight"), 1.0, 0.0, 10.0),
        vector_weight=clamp_float(rag.get("vector_weight"), 0.35, 0.0, 10.0),
        require_scope_match=coerce_bool(rag.get("require_scope_match"), True),
        min_vector_score=clamp_float(rag.get("min_vector_score"), 0.0, -1.0, 1.0),
        fusion_strategy=fusion_strategy,
        search_max_results=clamp_int(search_config.get("max_results"), 12, 1, 25, "max_results"),
        search_max_files=clamp_int(search_config.get("max_files"), 25, 1, 40, "max_files"),
    )


def resolve_retrieval_mode_label(mode: str, embedding_backend: str) -> str:
    if mode == "keyword":
        return "keyword"
    if mode == "semantic":
        return "semantic" if embedding_backend == "sentence-transformers" else "semantic_hash"
    return "hybrid_semantic" if embedding_backend == "sentence-transformers" else "hybrid_hash"


def clamp_float(value: Any, default: float, minimum: float, maximum: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = default
    return max(minimum, min(maximum, number))


def coerce_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "on"}:
            return True
        if lowered in {"0", "false", "no", "off"}:
            return False
    if value is None:
        return default
    return bool(value)


def get_full_retrieval(event_id: str) -> dict[str, Any] | None:
    """Return the cached full retrieval for an event_id, or None if expired/missing."""
    entry = _FULL_RETRIEVAL_CACHE.get(event_id)
    if entry is None:
        return None
    result, ts = entry
    if time.time() - ts > _RETRIEVAL_CACHE_TTL:
        _FULL_RETRIEVAL_CACHE.pop(event_id, None)
        return None
    return result


def _cache_full_retrieval(result: dict[str, Any]) -> None:
    event_id = result.get("event_id")
    if not event_id:
        return
    _FULL_RETRIEVAL_CACHE[event_id] = (result, time.time())
    # Evict expired entries (cheap — runs at most once per call)
    now = time.time()
    expired = [k for k, (_, ts) in _FULL_RETRIEVAL_CACHE.items() if now - ts > _RETRIEVAL_CACHE_TTL]
    for k in expired:
        _FULL_RETRIEVAL_CACHE.pop(k, None)


# Safety bound on the single most numerous field; generous (this is the whole answer
# Claude gets) but capped so one huge file's symbol list can't blow up the context
# window. Applied identically in every mode so behaviour stays consistent.
_ACTIONABLE_SYMBOL_CAP = 80


def _actionable_retrieval(result: dict[str, Any]) -> dict[str, Any]:
    """Build the consistent actionable payload CB returns in EVERY pipeline mode.
    Keeps the ranked files, extracted symbols, code blocks, dependency chain and
    verification guidance; drops only pre-fusion debug payloads
    (keyword_files/vector_candidates/results/diagnostics) and runtime metadata that
    don't help fix the issue. The AI `analysis`, when produced, is attached on top of
    this base — it never replaces it."""
    payload = {k: v for k, v in result.items() if k in _ACTIONABLE_FIELDS}
    symbol_hits = result.get("symbol_hits") or []
    if len(symbol_hits) > _ACTIONABLE_SYMBOL_CAP:
        payload["symbol_hits"] = symbol_hits[:_ACTIONABLE_SYMBOL_CAP]
        payload["symbol_hits_truncated"] = len(symbol_hits)
    return payload


def _cb_pre_validate(query: str, retrieval: dict[str, Any]) -> dict[str, Any]:
    """
    Pure-code CB self-check before local AI sees the retrieval.
    Checks pack coverage and dependency chain completeness using data already in the
    retrieval payload — no index re-load, no AI calls, microsecond cost.
    """
    files = retrieval.get("files") or []
    confirmed: list[str] = [str(f.get("path") or "").replace("\\", "/") for f in files if f.get("path")]
    missing_from_index: list[str] = []  # kept for API compatibility; not populated without index re-load

    # Pack coverage — which packs are present but have no confirmed files retrieved
    packs = retrieval.get("packs") or []
    pack_files_map: dict[str, list[str]] = {}
    for p in packs:
        name = str(p.get("name") or "")
        pack_file_list = [str(f) for f in (p.get("files") or []) if f]
        if name:
            pack_files_map[name] = pack_file_list

    uncovered_packs: list[str] = []
    confirmed_lower = {c.lower() for c in confirmed}
    for pack_name, pack_files in pack_files_map.items():
        if not pack_files:
            continue
        any_covered = any(pf.lower() in confirmed_lower for pf in pack_files)
        if not any_covered:
            uncovered_packs.append(pack_name)

    # Dependency gaps — target files in dependency chain not in retrieved set
    dep_chain = retrieval.get("dependency_chain") or []
    dep_targets: set[str] = set()
    retrieved_lower = {str(f.get("path") or "").replace("\\", "/").lower() for f in files}
    for d in dep_chain:
        target = str(d.get("target_file") or "").replace("\\", "/").lower()
        if target and target not in retrieved_lower:
            dep_targets.add(target)

    gaps_found = bool(missing_from_index or uncovered_packs or dep_targets)
    return {
        "ran": True,
        "gaps_found": gaps_found,
        "confirmed_file_count": len(confirmed),
        "missing_from_index": missing_from_index[:10],
        "uncovered_packs": uncovered_packs[:5],
        "dependency_gap_targets": sorted(dep_targets)[:10],
    }


def _run_auto_analysis(query: str, full_retrieval: dict[str, Any]) -> dict[str, Any] | None:
    """
    Run the analysis stage internally as part of search_context_hybrid when
    auto_analyze is enabled. Returns the analysis dict or None on timeout/error.
    """
    try:
        from analysis.config import is_auto_analyze_enabled, auto_analyze_timeout_seconds
        from context_bridge.analysis.stage import run_analysis_stage, select_code_blocks_for_analysis

        project_root = PROJECT_ROOT()
        if not is_auto_analyze_enabled(project_root):
            return None

        timeout = auto_analyze_timeout_seconds(project_root)

        def _run() -> dict[str, Any]:
            analysis = run_analysis_stage(query, full_retrieval, project_root)
            blocks = select_code_blocks_for_analysis(analysis, full_retrieval)
            return {
                "model":    analysis.get("model", ""),
                "provider": analysis.get("provider", ""),
                "relevance_check": analysis.get("relevance_check", ""),
                "confidence": analysis.get("confidence", ""),
                "summary": analysis.get("summary", ""),
                "topics": analysis.get("topics", []),
                "ignored_files": analysis.get("ignored_files", []),
                "gap_search_queries": analysis.get("gap_search_queries", []),
                "search_gaps": analysis.get("search_gaps", []),
                "ranked_files": analysis.get("ranked_files", []),
                "selected_symbols": analysis.get("selected_symbols", []),
                "dependencies": analysis.get("dependencies", []),
                "impacted_files": analysis.get("impacted_files", []),
                "risks": analysis.get("risks", []),
                "recommended_code_blocks": blocks,
                "current_implementation": analysis.get("current_implementation", ""),
                "workflow": analysis.get("workflow", ""),
                "metrics": {
                    "provider_latency_ms": analysis.get("provider_latency_ms", 0),
                    "prompt_chars": analysis.get("prompt_chars", 0),
                    "selected_block_count": len(blocks),
                    "total_retrieval_blocks": len(full_retrieval.get("code_blocks") or []),
                    "cache_hit": bool(analysis.get("cache_hit")),
                    "parse_failed": bool(analysis.get("parse_error")),
                    "parse_incomplete": bool(analysis.get("parse_incomplete")),
                },
                **({"parse_error": True} if analysis.get("parse_error") else {}),
            }

        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(_run)
            return future.result(timeout=timeout)

    except FuturesTimeoutError:
        print("[ContextBridge] auto_analyze timed out — returning retrieval without analysis", file=sys.stderr)
        return None
    except Exception as exc:
        print(f"[ContextBridge] auto_analyze error: {exc}", file=sys.stderr)
        return None


def _run_proactive_gaps(query: str, result: dict[str, Any]) -> list[str]:
    """
    Fire gap searches based on the original query BEFORE local AI runs.
    Uses the profile's proactive_gap_queries() table — triggers checked against
    the raw query text. Returns list of file paths added.
    Profile method is optional — silently skipped if not defined.
    """
    profile = _active_hybrid_profile()
    get_proactive = getattr(profile, "proactive_gap_queries", None)
    if not callable(get_proactive):
        return []

    lower = query.lower()
    existing_paths = {str(f.get("path", "")) for f in (result.get("files") or [])}
    added: list[str] = []

    for triggers, gap_query in get_proactive():
        if not any(t in lower for t in triggers):
            continue
        try:
            from context_bridge.rag.hybrid_search import hybrid_search
            gap_results = hybrid_search(gap_query, max_results=6, project_root=PROJECT_ROOT())
            for item in gap_results.get("files") or []:
                path = str(item.get("path", ""))
                if path and path not in existing_paths:
                    result.setdefault("files", []).append({
                        **item,
                        "role": "primary",
                        "source": "proactive_gap",
                        "reason": f"Proactive gap: {gap_query[:60]}",
                    })
                    existing_paths.add(path)
                    added.append(path)
        except Exception as exc:
            print(f"[ContextBridge] Proactive gap error for '{gap_query}': {exc}", file=sys.stderr)

    return added


def _cb_verify_topics(analysis: dict[str, Any], result: dict[str, Any]) -> list[str]:
    """
    Generic CB verification: after local AI pass 1, cross-check each topic's
    entry_method against the actual symbol_hits in the retrieval result.

    If the claimed entry_method is not found in the symbol index for that file,
    override file_match to False so the gap-fill + self-reflect pipeline stages
    can retrieve the correct file and re-evaluate.

    Returns a list of primary_file paths where the override was applied.
    """
    topics = analysis.get("topics") or []
    symbol_hits = result.get("symbol_hits") or []
    if not topics or not symbol_hits:
        return []

    # Build path → set-of-lowercase-labels from every symbol hit
    path_symbols: dict[str, set[str]] = {}
    for hit in symbol_hits:
        path = str(hit.get("path") or "").replace("\\", "/").lower()
        label = str(hit.get("label") or "").lower().strip()
        if path and label:
            path_symbols.setdefault(path, set()).add(label)

    candidate_paths = {
        str(f.get("path") or "").replace("\\", "/").lower()
        for f in (result.get("files") or [])
    }

    overridden: list[str] = []
    for topic in topics:
        if topic.get("file_match") is False:
            continue  # already flagged — nothing to do

        primary = str(topic.get("primary_file") or "").replace("\\", "/").strip()
        method  = str(topic.get("entry_method")  or "").strip()

        if not primary or not method or method.lower() in ("unknown", "—", ""):
            continue

        primary_lower = primary.lower()
        method_lower  = method.lower()

        known_symbols = path_symbols.get(primary_lower)

        if known_symbols is None:
            # File is not represented in symbol hits at all
            if primary_lower not in candidate_paths:
                # File was never retrieved — likely hallucinated
                topic["file_match"] = False
                topic["_cb_verify_note"] = "primary_file absent from retrieval candidates"
                overridden.append(primary)
            # If the file IS a candidate but has no symbols, leave it alone
            # (some files are legitimately symbol-free, e.g. DTOs)
            continue

        if method_lower not in known_symbols:
            # File exists in index but the claimed method isn't in its symbol hints
            topic["file_match"] = False
            topic["_cb_verify_note"] = (
                f"entry_method '{method}' not found in symbol index for {primary}"
            )
            overridden.append(primary)

    return overridden


def _extract_gap_query(issue_text: str) -> str:
    """
    Build a clean CB gap-search query from the issue text.
    Checks the active profile's domain gap-query table first — returns a known-good
    code-level query that matches the project's index (file names, symbols).
    Falls back to stopword-stripped user text only if no domain match.
    No Qwen involvement — pure Python lookup.
    """
    import re
    lower = issue_text.lower()
    for triggers, query in _active_hybrid_profile().gap_queries():
        if any(t in lower for t in triggers):
            return query

    # fallback — strip narrative words, keep code-close keywords
    stop = {
        "a","an","the","is","are","was","were","be","been","being",
        "have","has","had","do","does","did","will","would","could",
        "should","may","might","shall","can","need","there","and",
        "or","but","in","on","at","to","for","of","with","by","from",
        "it","its","this","that","these","those","also","not","no",
        "i","we","they","he","she","patient","staff","unable","check",
        "waiting","want","please","now","then","just","so","very",
        "stuck","blocked","cannot","linked","valid","ghost","session",
    }
    words = re.findall(r"[a-zA-Z]+", lower)
    keywords = [w for w in words if w not in stop and len(w) > 2]
    return " ".join(keywords[:6])


def _run_gap_searches(topics: list[dict], ranked_files: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    For each topic where Qwen flagged file_match=false, fire a targeted CB re-search.
    The search query is extracted from the user's original issue text — never from Qwen.
    This eliminates hallucinated queries entirely.

    Dedup baseline is Qwen's ranked_files (what actually reaches the AI), NOT the
    original CB retrieval. Because the Qwen-only pipeline drops the raw CB retrieval,
    deduping against it would silently lose any file Qwen failed to carry forward.
    """
    import json, time as _time
    existing_paths: set[str] = {
        str(f.get("path") or "").replace("\\", "/").lower()
        for f in (ranked_files or [])
    }
    new_ranked: list[dict[str, Any]] = []
    log_entries: list[dict[str, Any]] = []

    gap_topics = [t for t in topics if t.get("file_match") is False]

    for topic in gap_topics[:3]:  # cap at 3
        issue_text = str(topic.get("issue") or "")
        query = _extract_gap_query(issue_text)
        if not query:
            continue
        found_files: list[str] = []
        try:
            print(f"[ContextBridge] Gap re-search: '{query}' (from user text: '{issue_text[:60]}')", file=sys.stderr)
            gap_result = search_context_hybrid(query=query, max_files=6)
            for f in (gap_result.get("files") or []):
                path = str(f.get("path") or "").replace("\\", "/").lower()
                original_path = f.get("path")
                if path and path not in existing_paths:
                    new_ranked.append({
                        "path": original_path,
                        "role": "primary",
                        "symbols": [],
                        "reason": f"Gap re-search for: {issue_text[:80]}",
                        "source": "gap_search",
                    })
                    existing_paths.add(path)
                    found_files.append(str(original_path))
        except Exception as exc:
            print(f"[ContextBridge] Gap re-search failed for '{query}': {exc}", file=sys.stderr)
        log_entries.append({
            "topic": issue_text,
            "query_used": query,
            "query_source": "extracted from user prompt — no hallucination",
            "files_found": found_files,
        })

    # Write gap search log for dashboard
    try:
        log_path = PROJECT_ROOT() / "context_bridge" / "usage" / "last_gap_search.json"
        log_path.write_text(json.dumps({
            "timestamp": _time.strftime("%Y-%m-%dT%H:%M:%SZ", _time.gmtime()),
            "gaps_fired": len(log_entries),
            "files_added": len(new_ranked),
            "entries": log_entries,
        }, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass

    return new_ranked


def call_hybrid_tool(name: str, arguments: dict[str, Any] | None) -> dict[str, Any]:
    args = arguments or {}
    try:
        if name == "search_context_hybrid":
            query = clean_query(args.get("query"))
            start = time.perf_counter()
            result = search_context_hybrid(
                    query=query,
                    max_results=args.get("max_results"),
                    max_files=args.get("max_files"),
                    top_k_vector=args.get("top_k_vector"),
                    protected_keyword_count=args.get("protected_keyword_count"),
            )
            payload = _run_pipeline(query, result)
            latency_ms = int((time.perf_counter() - start) * 1000)
            event_id = log_tool_event(name, args, payload, latency_ms)
            payload = {"event_id": event_id, **payload}
            _cache_full_retrieval(payload)
            return payload
        if name == "find_code_locations":
            query = clean_query(args.get("query"))
            return timed_call(
                name,
                args,
                lambda: find_code_locations_hybrid(
                    query=query,
                    max_results=args.get("max_results"),
                ),
            )
        raise ValueError(f"Unknown hybrid tool: {name}")
    except Exception as exc:
        import sys
        import traceback
        print(f"[ContextBridge] tool error in {name}: {type(exc).__name__}: {exc}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        return tool_error(f"{type(exc).__name__}: {exc}", name)


def _run_pipeline(query: str, result: dict[str, Any]) -> dict[str, Any]:
    """
    Orchestrate CB → local AI → gap fill → self-reflection based on pipeline_mode config.

    simple      CB only — local AI skipped entirely
    validated   CB + local AI once (original behaviour)
    iterative   CB + local AI + CB gap fill (gap results fed back to local AI)
    full        CB pre-validate + local AI + CB gap fill + local AI self-reflect
    """
    from analysis.config import (
        pipeline_mode, cb_pre_validate_enabled, gap_fill_enabled,
        self_reflection_enabled, max_gap_iterations,
        is_auto_analyze_enabled, show_ai_meta,
    )
    from context_bridge.analysis.stage import run_reflection_pass

    project_root = PROJECT_ROOT()
    mode = pipeline_mode(project_root)
    pipeline_log: list[str] = [f"mode={mode}"]

    # Every mode returns this consistent actionable retrieval as its base; the AI
    # `analysis` (when produced) is attached on top, never as a replacement.
    payload = _actionable_retrieval(result)

    # ── simple: skip local AI entirely ──────────────────────────────────────
    if mode == "simple" or not is_auto_analyze_enabled(project_root):
        payload["analysis"] = None
        payload["source"] = "cb_only"
        payload["pipeline_mode"] = mode
        payload["pipeline_log"] = ["cb_only — local AI skipped"]
        return payload

    # ── CB pre-validate (full mode or cb_pre_validate=true) ─────────────────
    pre_validation: dict[str, Any] = {"ran": False}
    if cb_pre_validate_enabled(project_root):
        try:
            pre_validation = _cb_pre_validate(query, result)
            pipeline_log.append(f"pre_validate=ran gaps={pre_validation.get('gaps_found')}")
            # Inject pre-validation findings into retrieval so local AI prompt can use them
            result["_cb_pre_validation"] = pre_validation
        except Exception as exc:
            print(f"[ContextBridge] CB pre-validate error: {exc}", file=sys.stderr)
            pre_validation = {"ran": False, "error": str(exc)}

    # ── proactive gap injection (before local AI, based on query pattern) ───
    proactive_added = _run_proactive_gaps(query, result)
    if proactive_added:
        pipeline_log.append(f"proactive_gap=added:{len(proactive_added)}")

    # ── local AI pass 1 ─────────────────────────────────────────────────────
    analysis = _run_auto_analysis(query, result)

    if not analysis:
        # Local AI failed/timed out — Claude still gets the full actionable retrieval.
        payload["analysis"] = None
        payload["source"] = "cb_fallback"
        payload["pipeline_mode"] = mode
        payload["pipeline_log"] = pipeline_log + ["local_ai=failed fallback=cb_raw"]
        payload["pre_validation"] = pre_validation
        return payload

    pipeline_log.append("local_ai=pass1_done")

    # ── CB verification: override file_match if entry_method absent from symbol index ──
    cb_verify_overrides = _cb_verify_topics(analysis, result)
    if cb_verify_overrides:
        pipeline_log.append(f"cb_verify=override:{len(cb_verify_overrides)}")
        print(
            f"[ContextBridge] CB verify overrode file_match on: {cb_verify_overrides}",
            file=sys.stderr,
        )

    # ── gap fill (iterative + full modes) ───────────────────────────────────
    gap_iterations_run = 0
    if gap_fill_enabled(project_root):
        max_iters = max_gap_iterations(project_root)
        for _i in range(max_iters):
            topics = analysis.get("topics") or []
            gap_topics = [t for t in topics if t.get("file_match") is False]
            if not gap_topics:
                break
            ranked = list(analysis.get("ranked_files") or [])
            gap_files = _run_gap_searches(topics, ranked)
            if not gap_files:
                break
            ranked.extend(gap_files)
            analysis["ranked_files"] = ranked
            analysis["gap_searches_fired"] = (analysis.get("gap_searches_fired") or 0) + len(gap_topics)
            analysis["gap_files_added"] = (analysis.get("gap_files_added") or 0) + len(gap_files)
            gap_iterations_run += 1
            pipeline_log.append(f"gap_fill=iter{_i+1} added={len(gap_files)}")

            # In iterative mode: no re-analysis after gap fill, Claude gets merged result
            # In full mode: re-run local AI with gap files injected (handled by self-reflect below)
            if mode == "iterative":
                break

    # ── self-reflection pass (full mode or self_reflection=true) ────────────
    if self_reflection_enabled(project_root) and gap_iterations_run > 0:
        try:
            reflection = run_reflection_pass(query, result, analysis, project_root)
            if reflection and not reflection.get("skipped"):
                analysis = reflection
                pipeline_log.append("self_reflect=done")
            else:
                pipeline_log.append("self_reflect=skipped")
        except Exception as exc:
            print(f"[ContextBridge] Self-reflection error: {exc}", file=sys.stderr)
            pipeline_log.append(f"self_reflect=error:{exc}")
    elif self_reflection_enabled(project_root):
        pipeline_log.append("self_reflect=skipped(no_gaps)")

    # ── build final response ─────────────────────────────────────────────────
    # Same actionable base as every other mode, with the AI analysis attached on top.
    # This keeps CB's output consistent: the raw ranked files / symbols / code blocks /
    # guidance are always present, so Claude is never left with only a thin or
    # parse-failed analysis object.
    payload["analysis"] = analysis
    payload["source"] = "local_ai"
    payload["pipeline_mode"] = mode
    payload["pipeline_log"] = pipeline_log
    payload["pre_validation"] = pre_validation
    payload["gap_searches_fired"] = int(analysis.get("gap_searches_fired") or 0) if analysis else 0
    payload["gap_files_added"] = int(analysis.get("gap_files_added") or 0) if analysis else 0

    # ── AI meta (top-level, always visible) — suppress with show_ai_meta: false ──
    if show_ai_meta(project_root) and analysis:
        metrics = analysis.get("metrics") or {}
        payload["ai_meta"] = {
            "model":               analysis.get("model", ""),
            "provider":            analysis.get("provider", ""),
            "latency_ms":          metrics.get("provider_latency_ms", 0),
            "latency_s":           round(metrics.get("provider_latency_ms", 0) / 1000, 1),
            "cache_hit":           metrics.get("cache_hit", False),
            "pipeline_mode":       mode,
        }

    return payload


def _inject_pack_symbol_hints(
    existing_hits: list[dict[str, Any]],
    pack_norm_paths: set[str],
) -> list[dict[str, Any]]:
    """
    Pull symbol hints from the index for pack-injected files that didn't appear
    in the keyword search results and therefore have no symbol hits yet.
    """
    try:
        from search import load_index
        from graphify_loader import load_config
        project_root = PROJECT_ROOT()
        config = load_config(project_root, _active_config_name())
        docs = load_index(project_root, config)
    except Exception:
        return existing_hits

    existing_labels: set[tuple[str, str]] = {
        (str(h.get("label") or "").lower(), str(h.get("path") or "").lower())
        for h in existing_hits
    }
    injected: list[dict[str, Any]] = []
    for doc in docs:
        symbols = (doc.metadata or {}).get("symbol_hints") or []
        for sym in symbols:
            if not isinstance(sym, dict):
                continue
            source_file = str(sym.get("source_file") or "").replace("\\", "/")
            if source_file.lower() not in pack_norm_paths:
                continue
            label = str(sym.get("label") or "")
            kind = str(sym.get("kind") or "")
            if not label or is_low_value_symbol(label, kind):
                continue
            key = (label.lower(), source_file.lower())
            if key in existing_labels:
                continue
            existing_labels.add(key)
            injected.append({
                "label": label,
                "kind": kind,
                "path": source_file,
                "line": sym.get("line"),
                "source_location": str(sym.get("source_location") or ""),
                "module": doc.module,
                "pack": doc.pack,
                "source": "graphify_pack",
                "source_type": doc.source_type,
                "score": 0.0,
            })

    return existing_hits + injected


def keyword_file_candidates(keyword_payload: dict[str, Any]) -> list[dict[str, object]]:
    candidates: list[dict[str, object]] = []
    for rank, item in enumerate(keyword_payload.get("files") or [], start=1):
        if not isinstance(item, dict):
            continue
        path = str(item.get("path") or "")
        if not path:
            continue
        candidates.append(
            {
                "rank": rank,
                "title": path.rsplit("/", 1)[-1],
                "path": path,
                "source": item.get("source"),
                "source_type": item.get("source_type"),
                "score": item.get("score", 0.0),
                "module": infer_module_from_path(path),
                "pack": item.get("pack"),
                "files": [path],
                "retrieval": "keyword",
            }
        )
    return candidates


def infer_module_from_path(path: str) -> str | None:
    """Map a file path to a module for hybrid fusion scoping. The folder→module
    convention is project-specific, so it is supplied by the active profile;
    core returns None (generic apps get no module labels)."""
    return _active_hybrid_profile().infer_module_from_path(path)


def vector_index_path_from_env() -> Path:
    value = (os.environ.get("CONTEXT_BRIDGE_VECTOR_INDEX") or "").strip()
    if value:
        return Path(value)
    return PROJECT_ROOT() / "context_bridge" / "data" / "vector_index.jsonl"


def vector_manifest_path_from_env() -> Path:
    value = (os.environ.get("CONTEXT_BRIDGE_VECTOR_META") or "").strip()
    if value:
        return Path(value)
    return PROJECT_ROOT() / "context_bridge" / "data" / "vector_meta.json"


def PROJECT_ROOT() -> Path:
    return Path(__file__).resolve().parents[2]
