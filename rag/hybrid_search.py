from __future__ import annotations

import contextvars
from dataclasses import dataclass
from pathlib import Path
import re
from typing import Any

# Per-call project-supplied low-signal terms (e.g. module names). Set at the start
# of execute_hybrid_search from the request; keeps the vector layer decoupled from
# any profile while still honoring project-specific term suppression.
_EXTRA_LOW_SIGNAL: contextvars.ContextVar[frozenset] = contextvars.ContextVar(
    "_extra_low_signal", default=frozenset()
)

from .embeddings import EmbeddingRequest, create_backend
from .vector_store import read_manifest, read_records, search_records


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_VECTOR_INDEX_PATH = PROJECT_ROOT / "context_bridge" / "data" / "vector_index.jsonl"
DEFAULT_VECTOR_META_PATH = PROJECT_ROOT / "context_bridge" / "data" / "vector_meta.json"
DEFAULT_KEYWORD_INDEX_PATH = PROJECT_ROOT / "context_bridge" / "data" / "context_index.json"
QUERY_IDENTIFIER_RE = re.compile(r"\b[A-Za-z_][A-Za-z0-9_.]{2,}\b")
CODE_DEBUG_QUERY_TERMS = {
    "bug", "issue", "failing", "failed", "failure", "wrong", "broken", "debug", "runtime",
    "preview", "delete", "remove", "highlight", "attachment", "batch", "reservation", "refund",
    "payment", "permission", "route", "guard", "evaluator", "catalog", "cleanup", "save",
    "persist", "upload", "validation", "submit", "lookup", "reopen", "approval", "concurrency",
    "rowversion", "null", "desync", "drift", "scheduler", "notification", "followup", "follow",
}
WORKFLOW_DISCOVERY_TERMS = {
    "workflow", "flow", "behavior", "state", "lifecycle", "process", "rule", "rules",
    "policy", "decision", "invariant", "scenario", "architecture",
}
INFRA_RUNTIME_TERMS = {
    "scheduler", "job", "jobs", "cron", "middleware", "interceptor", "webhook", "websocket",
    "offline", "bootstrap", "serviceworker", "worker", "auth", "authorization",
    "authentication", "pipeline", "retry", "idempotency", "queue", "background",
    "startup", "warmup", "timeout",
}
BRIDGE_TERMS = {
    "bridge", "integration", "cross", "handoff", "sync", "link", "between",
}
# Domain-agnostic low-signal terms. Project-specific module names (e.g. hms, pos)
# are supplied per-request via HybridSearchRequest.low_signal_terms so the vector
# layer stays generic and decoupled from any profile.
LOW_SIGNAL_QUERY_TERMS = {
    "system", "issue", "problem",
    "fails", "failing", "failure", "error", "wrong", "broken", "query", "data", "flow", "module",
}
OVERLOADED_SEMANTIC_TERMS = {
    "index", "search", "permission", "permissions", "job", "jobs", "report", "reports",
    "template", "templates", "settings", "config", "configuration", "pdf", "print", "printing",
    "retry", "retries", "webhook", "webhooks", "timezone", "timezones",
}
OWNER_FILE_HINT_TERMS = {
    "controller", "controllers", "service", "services", "job", "jobs", "worker", "workers",
    "middleware", "handler", "handlers", "repository", "repositories", "provider", "providers",
    "resolver", "resolvers", "engine", "engines", "utility", "utilities", "helper", "helpers",
}
CODE_SOURCE_TYPES = {"graph chunk", "graph.json", "dependency-edges.enrichment.json", "source-files.txt", "live source"}
DOC_SOURCE_TYPES = {"behavior pack", "graph_report.md", "index.md", "scope-summary.md", ".md", "manifest.json"}
EXPLICIT_API_QUERY_TERMS = {
    "api", "endpoint", "endpoints", "route", "routes", "controller", "controllers",
    "client", "http", "request", "response",
}
# These "noise file" sets are project-specific (shell/support/root files that
# vector ranking should de-prioritize). Core ships empty; the active profile
# supplies them per-request via HybridSearchRequest.noise_files. Kept generic.
GENERIC_UI_SHELL_FILES: frozenset = frozenset()
GENERIC_FRONTEND_SUPPORT_FILES: frozenset = frozenset()
GENERIC_BACKEND_ROOT_FILES: frozenset = frozenset()

_EXTRA_NOISE_FILES: contextvars.ContextVar[dict] = contextvars.ContextVar(
    "_extra_noise_files", default={}
)


def _ui_shell_files() -> frozenset:
    return GENERIC_UI_SHELL_FILES | frozenset(_EXTRA_NOISE_FILES.get().get("ui_shell", ()))


def _frontend_support_files() -> frozenset:
    return GENERIC_FRONTEND_SUPPORT_FILES | frozenset(_EXTRA_NOISE_FILES.get().get("frontend_support", ()))


def _backend_root_files() -> frozenset:
    return GENERIC_BACKEND_ROOT_FILES | frozenset(_EXTRA_NOISE_FILES.get().get("backend_root", ()))
GENERIC_DOCUMENT_EXTENSIONS = (".md", ".json")

@dataclass
class HybridSearchRequest:
    query: str
    mode: str
    project_rules: dict[str, Any] | None = None
    query_terms: list[str] | None = None
    query_intents: list[str] | None = None
    query_profile: str | None = None
    top_k_keyword: int = 20
    top_k_vector: int = 12
    vector_index_path: Path = DEFAULT_VECTOR_INDEX_PATH
    vector_manifest_path: Path = DEFAULT_VECTOR_META_PATH
    embedding_backend: str | None = None
    embedding_model: str | None = None
    dimensions: int | None = None
    min_vector_score: float = 0.0
    keyword_candidates: list[dict[str, Any]] | None = None
    protected_keyword_count: int = 8
    keyword_weight: float = 1.0
    vector_weight: float = 0.35
    require_scope_match: bool = True
    exact_identifier_tokens: list[str] | None = None
    fusion_strategy: str = "weighted_rrf"
    low_signal_terms: list[str] | None = None
    noise_files: dict[str, list[str]] | None = None


@dataclass
class HybridSearchResponse:
    query: str
    mode: str
    used_vector: bool
    message: str
    keyword_candidates: list[dict[str, object]]
    vector_candidates: list[dict[str, object]]
    fused_candidates: list[dict[str, object]]
    suppressed_vector_candidates: list[dict[str, object]]
    diagnostics: dict[str, object]


_RECORD_CACHE: dict[str, object] = {"path": None, "mtime": None, "records": []}


def execute_hybrid_search(request: HybridSearchRequest) -> HybridSearchResponse:
    _EXTRA_LOW_SIGNAL.set(frozenset(
        str(t).strip().lower() for t in (request.low_signal_terms or []) if str(t).strip()
    ))
    _EXTRA_NOISE_FILES.set({
        key: [str(v).strip().lower() for v in vals if str(v).strip()]
        for key, vals in (request.noise_files or {}).items()
    })
    query = request.query.strip()
    mode = request.mode.strip().lower() or "keyword"
    keyword_candidates = list(request.keyword_candidates or [])
    if request.exact_identifier_tokens is None:
        request.exact_identifier_tokens = query_identifier_tokens(query)
    query_profile = request.query_profile or classify_query_profile(
        query_terms=request.query_terms or [],
        query_intents=request.query_intents or [],
        keyword_candidates=keyword_candidates,
    )

    if not query:
        return HybridSearchResponse(
            query=request.query,
            mode=mode,
            used_vector=False,
            message="Query had no searchable text.",
            keyword_candidates=keyword_candidates[: request.top_k_keyword],
            vector_candidates=[],
            fused_candidates=keyword_candidates[: request.top_k_keyword],
            suppressed_vector_candidates=[],
            diagnostics={"guard": "empty-query", "query_profile": query_profile},
        )

    if mode == "keyword":
        ranked = _apply_rules_to_keyword_candidates(
            keyword_candidates[: request.top_k_keyword],
            query_terms=request.query_terms or [],
            query_profile=query_profile,
            project_rules=request.project_rules or {},
        )
        return HybridSearchResponse(
            query=query,
            mode=mode,
            used_vector=False,
            message="Keyword mode selected; vector retrieval skipped.",
            keyword_candidates=keyword_candidates[: request.top_k_keyword],
            vector_candidates=[],
            fused_candidates=ranked,
            suppressed_vector_candidates=[],
            diagnostics={"guard": "keyword-mode", "query_profile": query_profile},
        )

    if mode == "semantic":
        vector_candidates = search_vector_index(request)
        semantic = semantic_owner_rerank(
            keyword_candidates=keyword_candidates[: request.top_k_keyword],
            vector_candidates=vector_candidates,
            max_results=max(request.top_k_keyword, request.top_k_vector),
            exact_identifier_tokens=request.exact_identifier_tokens or [],
            query_terms=request.query_terms or [],
            query_profile=query_profile,
            project_rules=request.project_rules or {},
        )
        return HybridSearchResponse(
            query=query,
            mode=mode,
            used_vector=True,
            message="Semantic mode selected; vector scope applied and owner files reranked.",
            keyword_candidates=keyword_candidates[: request.top_k_keyword],
            vector_candidates=vector_candidates,
            fused_candidates=semantic["fused"],
            suppressed_vector_candidates=semantic["suppressed"],
            diagnostics=semantic["diagnostics"],
        )

    vector_candidates = search_vector_index(request)
    fusion = fuse_candidates(
        keyword_candidates=keyword_candidates[: request.top_k_keyword],
        vector_candidates=vector_candidates,
        max_results=max(request.top_k_keyword, request.top_k_vector),
        protected_keyword_count=request.protected_keyword_count,
        keyword_weight=request.keyword_weight,
        vector_weight=request.vector_weight,
        require_scope_match=request.require_scope_match,
        exact_identifier_tokens=request.exact_identifier_tokens,
        fusion_strategy=request.fusion_strategy,
        query_profile=query_profile,
        query_terms=request.query_terms or [],
        project_rules=request.project_rules or {},
    )
    if not keyword_candidates and mode == "hybrid":
        message = "Vector retrieval completed. No keyword candidates were supplied, so fusion is vector-only."
    else:
        message = "Vector retrieval completed."

    fused = fusion["fused"]
    # When all vectors were suppressed, fusion output is essentially keyword order and
    # the protected_keyword_count guard prevents rules from demoting top keyword files.
    # Re-sort by rules here so penalties/boosts always take effect.
    all_suppressed = len(fusion.get("suppressed", [])) > 0 and not any(
        c for c in vector_candidates
        if c not in fusion.get("suppressed", [])
    )
    if request.project_rules and len(fusion.get("suppressed", [])) >= len(vector_candidates) > 0:
        fused = _apply_rules_to_keyword_candidates(
            fused,
            query_terms=request.query_terms or [],
            query_profile=query_profile,
            project_rules=request.project_rules or {},
        )

    return HybridSearchResponse(
        query=query,
        mode=mode,
        used_vector=True,
        message=message,
        keyword_candidates=keyword_candidates[: request.top_k_keyword],
        vector_candidates=vector_candidates,
        fused_candidates=fused,
        suppressed_vector_candidates=fusion["suppressed"],
        diagnostics=fusion["diagnostics"],
    )


def search_vector_index(request: HybridSearchRequest) -> list[dict[str, object]]:
    manifest = read_manifest(request.vector_manifest_path)
    if manifest is None:
        raise FileNotFoundError(f"Vector manifest not found: {request.vector_manifest_path}")
    records = load_records_cached(request.vector_index_path)
    backend_name = request.embedding_backend or manifest.embedding_backend
    model = request.embedding_model or manifest.embedding_model
    dimensions = request.dimensions or manifest.dimensions
    backend = create_backend(backend_name, model)
    embedding = backend.embed(EmbeddingRequest(texts=[request.query], model=model, dimensions=dimensions))
    if not embedding.vectors:
        return []
    results = search_records(
        records,
        embedding.vectors[0],
        top_k=request.top_k_vector,
        min_score=request.min_vector_score,
    )
    return [format_vector_candidate(result.to_dict(), rank=idx + 1) for idx, result in enumerate(results)]


def load_records_cached(path: Path) -> list:
    current_mtime = path.stat().st_mtime
    if _RECORD_CACHE["path"] == str(path) and _RECORD_CACHE["mtime"] == current_mtime:
        return list(_RECORD_CACHE["records"])
    records = read_records(path)
    _RECORD_CACHE["path"] = str(path)
    _RECORD_CACHE["mtime"] = current_mtime
    _RECORD_CACHE["records"] = records
    return records


def format_vector_candidate(payload: dict[str, object], *, rank: int) -> dict[str, object]:
    text = str(payload.get("text") or "")
    return {
        "rank": rank,
        "score": payload.get("score", 0.0),
        "chunk_id": payload.get("chunk_id"),
        "doc_id": payload.get("doc_id"),
        "module": payload.get("module"),
        "pack": payload.get("pack"),
        "source_type": payload.get("source_type"),
        "source": payload.get("source"),
        "path": payload.get("path"),
        "files": list(payload.get("files") or [])[:20],
        "facts": list(payload.get("facts") or [])[:8],
        "snippet": text[:900],
        "retrieval": "vector",
    }


def fuse_candidates(
    *,
    keyword_candidates: list[dict[str, Any]],
    vector_candidates: list[dict[str, object]],
    max_results: int,
    protected_keyword_count: int,
    keyword_weight: float,
    vector_weight: float,
    require_scope_match: bool,
    exact_identifier_tokens: list[str] | None,
    fusion_strategy: str,
    query_profile: str,
    query_terms: list[str] | None = None,
    project_rules: dict[str, Any] | None = None,
) -> dict[str, object]:
    if not keyword_candidates:
        fused, code_first_stats = apply_code_first_guard(
            vector_candidates,
            query_profile=query_profile,
            max_results=max_results,
        )
        return {
            "fused": fused,
            "suppressed": [],
            "diagnostics": {
                "guard": "vector-only",
                "protected_keyword_count": 0,
                "allowed_vector_count": len(fused),
                "suppressed_vector_count": 0,
                "exact_identifier_tokens": exact_identifier_tokens or [],
                "fusion_strategy": "vector-only",
                "query_profile": query_profile,
                **code_first_stats,
            },
        }
    scope = build_keyword_scope(keyword_candidates)
    keyword_lock = build_keyword_lock(keyword_candidates, query_profile=query_profile)
    allowed_vectors: list[dict[str, object]] = []
    suppressed_vectors: list[dict[str, object]] = []
    for candidate in vector_candidates:
        allowed, reason = vector_scope_allowed(
            candidate,
            scope,
            require_scope_match=require_scope_match,
            exact_identifier_tokens=exact_identifier_tokens or [],
            query_profile=query_profile,
            keyword_lock=keyword_lock,
        )
        enriched = dict(candidate)
        enriched["guard_reason"] = reason
        if allowed:
            allowed_vectors.append(enriched)
        else:
            suppressed_vectors.append(enriched)

    scores: dict[str, float] = {}
    payloads: dict[str, dict[str, object]] = {}
    sources: dict[str, set[str]] = {}
    protected = keyword_candidates[: max(0, protected_keyword_count)]
    protected_keys = {candidate_key(candidate) for candidate in protected}
    for rank, candidate in enumerate(keyword_candidates, start=1):
        key = candidate_key(candidate)
        penalty = generic_candidate_penalty(
            candidate,
            query_terms=query_terms or [],
            query_profile=query_profile,
            exact_identifier_tokens=exact_identifier_tokens or [],
        )
        project_delta = apply_project_semantic_rules(
            candidate,
            query_terms=query_terms or [],
            query_profile=query_profile,
            project_rules=project_rules or {},
        )
        specificity_delta = candidate_specificity_delta(
            candidate,
            query_terms=query_terms or [],
            query_profile=query_profile,
        )
        scores[key] = scores.get(key, 0.0) + max(
            0.0,
            (keyword_weight / (60 + rank)) - (penalty / 100.0) + (project_delta / 100.0) + (specificity_delta / 100.0),
        )
        payloads.setdefault(key, dict(candidate))
        sources.setdefault(key, set()).add("keyword")
    for rank, candidate in enumerate(allowed_vectors, start=1):
        key = candidate_key(candidate)
        penalty = generic_candidate_penalty(
            candidate,
            query_terms=query_terms or [],
            query_profile=query_profile,
            exact_identifier_tokens=exact_identifier_tokens or [],
        )
        project_delta = apply_project_semantic_rules(
            candidate,
            query_terms=query_terms or [],
            query_profile=query_profile,
            project_rules=project_rules or {},
        )
        specificity_delta = candidate_specificity_delta(
            candidate,
            query_terms=query_terms or [],
            query_profile=query_profile,
        )
        scores[key] = scores.get(key, 0.0) + max(
            0.0,
            (vector_weight / (60 + rank)) - (penalty / 100.0) + (project_delta / 100.0) + (specificity_delta / 100.0),
        )
        payloads.setdefault(key, dict(candidate))
        sources.setdefault(key, set()).add("vector")
    ranked = sorted(
        ((key, score) for key, score in scores.items() if key not in protected_keys),
        key=lambda item: item[1],
        reverse=True,
    )
    ordered_keys = [(candidate_key(candidate), scores[candidate_key(candidate)]) for candidate in protected]
    ordered_keys.extend(ranked)
    ordered_keys = dedupe_ranked_keys(ordered_keys)[:max_results]
    output: list[dict[str, object]] = []
    for _, (key, score) in enumerate(ordered_keys, start=1):
        payload = dict(payloads[key])
        payload["fusion_score"] = round(score, 6)
        payload["retrieval"] = "+".join(sorted(sources[key]))
        payload["guard"] = "protected-keyword" if key in protected_keys else "scoped-fusion"
        output.append(payload)
    output, code_first_stats = apply_code_first_guard(
        output,
        query_profile=query_profile,
        max_results=max_results,
    )
    for rank, payload in enumerate(output, start=1):
        payload["rank"] = rank
    return {
        "fused": output,
        "suppressed": suppressed_vectors,
        "diagnostics": {
            "guard": "scope-gated-keyword-first",
            "protected_keyword_count": len(protected),
            "allowed_vector_count": len(allowed_vectors),
            "suppressed_vector_count": len(suppressed_vectors),
            "scope_modules": sorted(scope["modules"]),
            "scope_packs": sorted(scope["packs"]),
            "keyword_lock": keyword_lock,
            "exact_identifier_tokens": exact_identifier_tokens or [],
            "fusion_strategy": fusion_strategy,
            "query_profile": query_profile,
            **code_first_stats,
        },
    }


def semantic_owner_rerank(
    *,
    keyword_candidates: list[dict[str, Any]],
    vector_candidates: list[dict[str, object]],
    max_results: int,
    exact_identifier_tokens: list[str],
    query_terms: list[str],
    query_profile: str,
    project_rules: dict[str, Any],
) -> dict[str, object]:
    if not vector_candidates:
        fused, code_first_stats = apply_code_first_guard(
            keyword_candidates,
            query_profile=query_profile,
            max_results=max_results,
        )
        for rank, payload in enumerate(fused, start=1):
            payload["rank"] = rank
        return {
            "fused": fused,
            "suppressed": [],
            "diagnostics": {
                "guard": "semantic-no-vectors",
                "scope_modules": [],
                "scope_packs": [],
                "kept_keyword_count": len(fused),
                "suppressed_keyword_count": 0,
                "exact_identifier_tokens": exact_identifier_tokens,
                "fusion_strategy": "semantic-owner-rerank",
                "query_profile": query_profile,
                **code_first_stats,
            },
        }
    if not keyword_candidates:
        fused, code_first_stats = apply_code_first_guard(
            vector_candidates,
            query_profile=query_profile,
            max_results=max_results,
        )
        for rank, payload in enumerate(fused, start=1):
            payload["rank"] = rank
        return {
            "fused": fused,
            "suppressed": [],
            "diagnostics": {
                "guard": "semantic-vector-only",
                "scope_modules": sorted(build_vector_scope(vector_candidates)["modules"]),
                "scope_packs": sorted(build_vector_scope(vector_candidates)["packs"]),
                "kept_keyword_count": 0,
                "suppressed_keyword_count": 0,
                "exact_identifier_tokens": exact_identifier_tokens,
                "fusion_strategy": "semantic-owner-rerank",
                "query_profile": query_profile,
                **code_first_stats,
            },
        }

    keyword_lock = build_keyword_lock(keyword_candidates, query_profile=query_profile)
    effective_vectors: list[dict[str, object]] = []
    suppressed: list[dict[str, object]] = []
    for candidate in vector_candidates:
        if candidate_matches_keyword_lock(candidate, keyword_lock):
            effective_vectors.append(candidate)
        else:
            enriched = dict(candidate)
            enriched["guard_reason"] = "dominant-module-lock"
            suppressed.append(enriched)
    if not effective_vectors:
        effective_vectors = list(vector_candidates)
        suppressed = []

    scope = build_vector_scope(effective_vectors)
    scored: list[tuple[float, dict[str, Any]]] = []
    for candidate in keyword_candidates:
        allowed, reason = keyword_scope_allowed(
            candidate,
            scope,
            exact_identifier_tokens=exact_identifier_tokens,
            query_terms=query_terms,
            query_profile=query_profile,
            keyword_lock=keyword_lock,
        )
        if not allowed:
            enriched = dict(candidate)
            enriched["guard_reason"] = reason
            suppressed.append(enriched)
            continue
        score = semantic_keyword_score(
            candidate,
            effective_vectors,
            scope,
            exact_identifier_tokens=exact_identifier_tokens,
            query_terms=query_terms,
            query_profile=query_profile,
            keyword_lock=keyword_lock,
            project_rules=project_rules,
        )
        scored.append((score, dict(candidate)))

    if not scored:
        fused, code_first_stats = apply_code_first_guard(
            vector_candidates,
            query_profile=query_profile,
            max_results=max_results,
        )
        for rank, payload in enumerate(fused, start=1):
            payload["rank"] = rank
        return {
            "fused": fused,
            "suppressed": suppressed,
            "diagnostics": {
                "guard": "semantic-fallback-vector",
                "scope_modules": sorted(scope["modules"]),
                "scope_packs": sorted(scope["packs"]),
                "keyword_lock": keyword_lock,
                "kept_keyword_count": 0,
                "suppressed_keyword_count": len(suppressed),
                "exact_identifier_tokens": exact_identifier_tokens,
                "fusion_strategy": "semantic-owner-rerank",
                "query_profile": query_profile,
                **code_first_stats,
            },
        }

    scored.sort(key=lambda item: item[0], reverse=True)
    fused: list[dict[str, object]] = []
    for _, (score, candidate) in enumerate(scored[:max_results], start=1):
        payload = dict(candidate)
        payload["fusion_score"] = round(score, 6)
        payload["retrieval"] = "semantic+keyword"
        payload["guard"] = "semantic-owner-rerank"
        fused.append(payload)
    fused, code_first_stats = apply_code_first_guard(
        fused,
        query_profile=query_profile,
        max_results=max_results,
    )
    for rank, payload in enumerate(fused, start=1):
        payload["rank"] = rank
    return {
        "fused": fused,
        "suppressed": suppressed,
        "diagnostics": {
            "guard": "semantic-owner-rerank",
            "scope_modules": sorted(scope["modules"]),
            "scope_packs": sorted(scope["packs"]),
            "keyword_lock": keyword_lock,
            "kept_keyword_count": len(fused),
            "suppressed_keyword_count": len(suppressed),
            "exact_identifier_tokens": exact_identifier_tokens,
            "fusion_strategy": "semantic-owner-rerank",
            "query_profile": query_profile,
            **code_first_stats,
        },
    }


def classify_query_profile(
    *,
    query_terms: list[str],
    query_intents: list[str],
    keyword_candidates: list[dict[str, Any]],
) -> str:
    term_set = {str(term).strip().lower() for term in query_terms if str(term).strip()}
    intent_set = {str(intent).strip().lower() for intent in query_intents if str(intent).strip()}
    if term_set.intersection(BRIDGE_TERMS):
        return "cross_module_bridge"
    if term_set.intersection(INFRA_RUNTIME_TERMS):
        return "infra_runtime"
    if "business_flow" in intent_set and not intent_set.intersection({"implementation_trace", "runtime_debug", "code_level", "ownership"}):
        return "workflow_discovery"
    if intent_set.intersection({"implementation_trace", "runtime_debug", "code_level", "ownership"}) or term_set.intersection(CODE_DEBUG_QUERY_TERMS):
        return "code_debug"
    if term_set.intersection(WORKFLOW_DISCOVERY_TERMS):
        return "workflow_discovery"
    return "code_debug"


def source_type_bucket(candidate: dict[str, object] | dict[str, Any]) -> str:
    source_type = normalize_scope_value(candidate.get("source_type"))
    if source_type in CODE_SOURCE_TYPES:
        return "code"
    if source_type in DOC_SOURCE_TYPES:
        return "doc"
    path = normalize_path_value(candidate.get("path") or candidate.get("source"))
    if path.endswith((".cs", ".tsx", ".ts", ".js")):
        return "code"
    if path.endswith((".md", ".json")):
        return "doc"
    return "other"


def code_first_window_settings(query_profile: str, max_results: int) -> tuple[int, int]:
    if query_profile not in {"code_debug", "infra_runtime"}:
        return 0, max_results
    window = min(8, max_results)
    max_non_code = 1
    return window, max_non_code


def apply_code_first_guard(
    candidates: list[dict[str, object]],
    *,
    query_profile: str,
    max_results: int,
) -> tuple[list[dict[str, object]], dict[str, int]]:
    window, max_non_code = code_first_window_settings(query_profile, max_results)
    trimmed = list(candidates[:max_results])
    if window <= 0 or not trimmed:
        return trimmed, {
            "code_first_window": window,
            "code_first_max_non_code": max_non_code,
            "code_first_non_code_before": 0,
            "code_first_non_code_after": 0,
        }

    initial_window = trimmed[:window]
    non_code_before = sum(1 for candidate in initial_window if source_type_bucket(candidate) != "code")
    code_candidates = [candidate for candidate in trimmed if source_type_bucket(candidate) == "code"]
    non_code_candidates = [candidate for candidate in trimmed if source_type_bucket(candidate) != "code"]

    promoted: list[dict[str, object]] = []
    seen: set[str] = set()

    def add_candidate(candidate: dict[str, object]) -> None:
        key = candidate_key(candidate)
        if key in seen:
            return
        seen.add(key)
        promoted.append(candidate)

    target_code_count = max(0, window - max_non_code)
    for candidate in code_candidates[:target_code_count]:
        add_candidate(candidate)
    for candidate in non_code_candidates[:max_non_code]:
        add_candidate(candidate)
    for candidate in trimmed:
        add_candidate(candidate)

    promoted = promoted[:max_results]
    non_code_after = sum(1 for candidate in promoted[:window] if source_type_bucket(candidate) != "code")
    return promoted, {
        "code_first_window": window,
        "code_first_max_non_code": max_non_code,
        "code_first_non_code_before": non_code_before,
        "code_first_non_code_after": non_code_after,
    }


def _apply_rules_to_keyword_candidates(
    candidates: list[dict[str, object]],
    *,
    query_terms: list[str],
    query_profile: str,
    project_rules: dict[str, Any],
) -> list[dict[str, object]]:
    """Re-sort keyword candidates by applying project boost/penalty rules.

    Scores from the Graphify layer can reach 1000+ (pack-first +900 bonus), making an
    additive delta of ±12 negligible. We normalize to [0, 1] first so rule deltas
    (typically ±5 to ±36) dominate the sort and can actually reorder results.
    """
    if not project_rules or not candidates:
        return candidates
    raw_scores = [float(c.get("score") or 0.0) for c in candidates]
    max_score = max(raw_scores, default=1.0) or 1.0
    scored = []
    for candidate, raw in zip(candidates, raw_scores):
        norm = raw / max_score  # [0, 1]
        delta = apply_project_semantic_rules(
            candidate,
            query_terms=query_terms,
            query_profile=query_profile,
            project_rules=project_rules,
        )
        scored.append((norm + delta, candidate))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [c for _, c in scored]


def tokenize_path_name(path: str) -> set[str]:
    name = path.rsplit("/", 1)[-1]
    return {part for part in re.split(r"[^a-z0-9]+", name.lower()) if part}


def query_prefers_api_surface(query_terms: list[str], exact_identifier_tokens: list[str]) -> bool:
    term_set = {str(term).strip().lower() for term in query_terms if str(term).strip()}
    if term_set.intersection(EXPLICIT_API_QUERY_TERMS):
        return True
    for token in exact_identifier_tokens:
        lowered = str(token).strip().lower()
        if lowered.endswith(("controller", "api", "client")) or lowered in EXPLICIT_API_QUERY_TERMS:
            return True
    return False


def generic_candidate_penalty(
    candidate: dict[str, object] | dict[str, Any],
    *,
    query_terms: list[str],
    query_profile: str,
    exact_identifier_tokens: list[str],
) -> float:
    if query_profile not in {"code_debug", "infra_runtime", "cross_module_bridge"}:
        return 0.0

    path = normalize_path_value(candidate.get("path") or candidate.get("source"))
    if not path:
        return 0.0

    term_set = {str(term).strip().lower() for term in query_terms if str(term).strip()}
    overloaded_terms = term_set.intersection(OVERLOADED_SEMANTIC_TERMS)
    if query_prefers_api_surface(query_terms, exact_identifier_tokens):
        explicit_api_query = True
    else:
        explicit_api_query = False

    path_tokens = tokenize_path_name(path)
    exact_hits = [token.lower() for token in exact_identifier_tokens if token.lower() in path]
    query_overlap = [term for term in term_set if len(term) >= 4 and term in path_tokens]
    if exact_hits:
        return 0.0

    filename = path.rsplit("/", 1)[-1]
    penalty = 0.0
    candidate_bucket = source_type_bucket(candidate)
    overlap_count = len(query_overlap)

    if overloaded_terms and candidate_bucket == "doc":
        penalty += 4.0
        if overlap_count == 0:
            penalty += 3.5
    if overloaded_terms and filename.endswith(GENERIC_DOCUMENT_EXTENSIONS):
        penalty += 2.5

    if filename in _ui_shell_files():
        penalty += 4.5
    if filename in _frontend_support_files():
        penalty += 4.5
    if filename in _backend_root_files():
        penalty += 4.5

    if filename.endswith("api.ts") and not explicit_api_query:
        penalty += 3.8
    if filename.endswith("client.ts") and not explicit_api_query:
        penalty += 3.2
    if filename.endswith("store.ts") and "store" not in term_set:
        penalty += 2.4
    if filename.endswith("controller.cs") and not explicit_api_query and filename in _backend_root_files():
        penalty += 2.6
    if overloaded_terms and filename in _backend_root_files() and overlap_count <= 1:
        penalty += 3.0
    if overloaded_terms and filename in _frontend_support_files() and overlap_count <= 1:
        penalty += 3.0

    if query_overlap:
        penalty *= 0.45

    return penalty


def significant_query_terms(query_terms: list[str]) -> list[str]:
    low_signal = LOW_SIGNAL_QUERY_TERMS | _EXTRA_LOW_SIGNAL.get()
    output: list[str] = []
    seen: set[str] = set()
    for term in query_terms:
        lowered = str(term).strip().lower()
        if len(lowered) < 4 or lowered in low_signal or lowered in seen:
            continue
        seen.add(lowered)
        output.append(lowered)
    return output


def candidate_query_overlap_count(
    candidate: dict[str, object] | dict[str, Any],
    *,
    query_terms: list[str],
) -> int:
    path = normalize_path_value(candidate.get("path") or candidate.get("source"))
    title = str(candidate.get("title") or "").strip().lower()
    files_text = " ".join(normalize_path_value(item) for item in candidate.get("files") or [])
    haystack = " ".join(part for part in [path, title, files_text] if part)
    if not haystack:
        return 0
    return sum(1 for term in significant_query_terms(query_terms) if term in haystack)


def candidate_specificity_delta(
    candidate: dict[str, object] | dict[str, Any],
    *,
    query_terms: list[str],
    query_profile: str,
) -> float:
    if query_profile not in {"code_debug", "infra_runtime", "cross_module_bridge"}:
        return 0.0
    overlap = candidate_query_overlap_count(candidate, query_terms=query_terms)
    term_set = {str(term).strip().lower() for term in query_terms if str(term).strip()}
    overloaded_terms = term_set.intersection(OVERLOADED_SEMANTIC_TERMS)
    source_bucket = source_type_bucket(candidate)
    path = normalize_path_value(candidate.get("path") or candidate.get("source"))
    filename = path.rsplit("/", 1)[-1]
    filename_tokens = tokenize_path_name(path)
    owner_hint = bool(filename_tokens.intersection(OWNER_FILE_HINT_TERMS))
    delta = 0.0
    if overlap >= 3:
        delta += 3.2 if overloaded_terms else 2.4
    elif overlap == 2:
        delta += 2.0 if overloaded_terms else 1.4
    elif overlap == 1:
        delta += 0.75 if overloaded_terms else 0.45
    elif len(significant_query_terms(query_terms)) >= 3:
        delta -= 2.2 if source_bucket == "doc" and overloaded_terms else 1.35
    if owner_hint and source_bucket == "code" and (overlap or term_set.intersection(OWNER_FILE_HINT_TERMS)):
        delta += 1.4
    if overloaded_terms and source_bucket == "doc" and overlap <= 1:
        delta -= 1.6
    if overloaded_terms and filename in _backend_root_files() and overlap <= 1:
        delta -= 1.2
    if overloaded_terms and filename in _frontend_support_files() and overlap <= 1:
        delta -= 1.2
    return delta


def project_rule_matches(rule: dict[str, Any], term_set: set[str], query_profile: str) -> bool:
    profiles = [str(value).strip() for value in rule.get("query_profiles") or [] if str(value).strip()]
    if profiles and query_profile not in profiles:
        return False
    terms_all = {str(value).strip().lower() for value in rule.get("terms_all") or [] if str(value).strip()}
    terms_any = {str(value).strip().lower() for value in rule.get("terms_any") or [] if str(value).strip()}
    terms_none = {str(value).strip().lower() for value in rule.get("terms_none") or [] if str(value).strip()}
    try:
        terms_min_any = int(rule.get("terms_min_any") or (1 if terms_any else 0))
    except (TypeError, ValueError):
        terms_min_any = 1 if terms_any else 0
    if terms_all and not terms_all.issubset(term_set):
        return False
    if terms_none and terms_none.intersection(term_set):
        return False
    if terms_any and len(terms_any.intersection(term_set)) < terms_min_any:
        return False
    return bool(terms_all or terms_any or not profiles)


def apply_project_semantic_rules(
    candidate: dict[str, Any],
    *,
    query_terms: list[str],
    query_profile: str,
    project_rules: dict[str, Any],
) -> float:
    rules = list((project_rules or {}).get("semantic_rules") or [])
    if not rules:
        return 0.0

    term_set = {str(term).strip().lower() for term in query_terms if str(term).strip()}
    path = normalize_path_value(candidate.get("path") or candidate.get("source"))
    if not path:
        return 0.0

    delta = 0.0
    for rule in rules:
        if not project_rule_matches(rule, term_set, query_profile):
            continue
        for item in rule.get("path_boosts") or []:
            suffix = normalize_path_value(item.get("suffix"))
            contains = normalize_path_value(item.get("contains"))
            score = float(item.get("score") or 0.0)
            if suffix and path.endswith(suffix):
                delta += score
            elif contains and contains in path:
                delta += score
        for item in rule.get("path_penalties") or []:
            suffix = normalize_path_value(item.get("suffix"))
            contains = normalize_path_value(item.get("contains"))
            score = float(item.get("score") or 0.0)
            if suffix and path.endswith(suffix):
                delta -= score
            elif contains and contains in path:
                delta -= score
    return delta


def candidate_key(candidate: dict[str, Any]) -> str:
    for field in ("path", "source", "chunk_id", "doc_id", "title"):
        value = candidate.get(field)
        if value:
            return f"{field}:{str(value).lower()}"
    return repr(sorted(candidate.items()))


def dedupe_ranked_keys(items: list[tuple[str, float]]) -> list[tuple[str, float]]:
    """Deduplicate ranked keys by exact match AND path-suffix match.

    The indexer can store the same physical file under multiple relative path roots
    (e.g. "main_service/POS/Services/CartService.cs", "POS/Services/CartService.cs",
    "Services/CartService.cs"). These produce different candidate_key values so the
    exact-match seen-set doesn't catch them. Path-suffix dedup: if a new path:... key's
    path portion is a strict suffix of an already-kept path:... key (or vice-versa), they
    refer to the same physical file. The higher-ranked item (first encountered in the
    sorted list) is kept; the shorter-path variants are dropped.
    """
    seen: set[str] = set()
    kept_paths: list[str] = []   # path portions of already-kept path: keys (lowercase)
    output: list[tuple[str, float]] = []
    for key, score in items:
        if key in seen:
            continue
        if key.startswith("path:"):
            path_part = key[5:]  # strip "path:" prefix; already lowercased by candidate_key
            duplicate = False
            for kept in kept_paths:
                # One path is a suffix of the other → same physical file under different roots
                if kept.endswith(path_part) or path_part.endswith(kept):
                    duplicate = True
                    break
            if duplicate:
                continue
            kept_paths.append(path_part)
        seen.add(key)
        output.append((key, score))
    return output


def build_keyword_scope(keyword_candidates: list[dict[str, Any]]) -> dict[str, set[str]]:
    modules: set[str] = set()
    packs: set[str] = set()
    paths: set[str] = set()
    files: set[str] = set()
    for candidate in keyword_candidates[:12]:
        module = normalize_scope_value(candidate.get("module"))
        pack = normalize_scope_value(candidate.get("pack"))
        path = normalize_path_value(candidate.get("path") or candidate.get("source"))
        if module:
            modules.add(module)
        if pack:
            packs.add(pack)
        if path:
            paths.add(path)
        for file_path in candidate.get("files") or []:
            normalized = normalize_path_value(file_path)
            if normalized:
                files.add(normalized)
    return {"modules": modules, "packs": packs, "paths": paths, "files": files}


def build_vector_scope(vector_candidates: list[dict[str, object]]) -> dict[str, set[str]]:
    modules: set[str] = set()
    packs: set[str] = set()
    paths: set[str] = set()
    files: set[str] = set()
    for candidate in vector_candidates[:12]:
        module = normalize_scope_value(candidate.get("module"))
        pack = normalize_scope_value(candidate.get("pack"))
        path = normalize_path_value(candidate.get("path") or candidate.get("source"))
        if module:
            modules.add(module)
        if pack:
            packs.add(pack)
        if path:
            paths.add(path)
        for file_path in candidate.get("files") or []:
            normalized = normalize_path_value(file_path)
            if normalized:
                files.add(normalized)
    return {"modules": modules, "packs": packs, "paths": paths, "files": files}


def build_keyword_lock(
    keyword_candidates: list[dict[str, Any]],
    *,
    query_profile: str,
) -> dict[str, object]:
    if query_profile not in {"code_debug", "infra_runtime"}:
        return {
            "enabled": False,
            "dominant_module": "",
            "module_share": 0.0,
            "dominant_pack": "",
            "pack_share": 0.0,
        }

    module_scores: dict[str, float] = {}
    pack_scores: dict[str, float] = {}
    total_weight = 0.0
    for rank, candidate in enumerate(keyword_candidates[:8], start=1):
        weight = 1.0 / rank
        total_weight += weight
        module = normalize_scope_value(candidate.get("module"))
        pack = normalize_scope_value(candidate.get("pack"))
        if module:
            module_scores[module] = module_scores.get(module, 0.0) + weight
        if pack:
            pack_scores[pack] = pack_scores.get(pack, 0.0) + weight

    dominant_module = ""
    dominant_pack = ""
    module_share = 0.0
    pack_share = 0.0
    if module_scores and total_weight > 0:
        dominant_module, dominant_module_weight = max(module_scores.items(), key=lambda item: item[1])
        module_share = dominant_module_weight / total_weight
    if pack_scores and total_weight > 0:
        dominant_pack, dominant_pack_weight = max(pack_scores.items(), key=lambda item: item[1])
        pack_share = dominant_pack_weight / total_weight

    enabled = bool(dominant_module) and module_share >= 0.55
    return {
        "enabled": enabled,
        "dominant_module": dominant_module,
        "module_share": round(module_share, 4),
        "dominant_pack": dominant_pack,
        "pack_share": round(pack_share, 4),
    }


def candidate_matches_keyword_lock(candidate: dict[str, object] | dict[str, Any], keyword_lock: dict[str, object]) -> bool:
    if not keyword_lock.get("enabled"):
        return True
    dominant_module = str(keyword_lock.get("dominant_module") or "").strip().lower()
    dominant_pack = str(keyword_lock.get("dominant_pack") or "").strip().lower()
    module = normalize_scope_value(candidate.get("module"))
    pack = normalize_scope_value(candidate.get("pack"))
    if module and module == dominant_module:
        return True
    if dominant_pack and pack and pack == dominant_pack:
        return True
    return False


def keyword_scope_allowed(
    candidate: dict[str, Any],
    scope: dict[str, set[str]],
    *,
    exact_identifier_tokens: list[str],
    query_terms: list[str],
    query_profile: str,
    keyword_lock: dict[str, object],
) -> tuple[bool, str]:
    haystack = " ".join(
        [
            str(candidate.get("path") or ""),
            str(candidate.get("source") or ""),
            str(candidate.get("title") or ""),
            " ".join(str(item) for item in candidate.get("files") or []),
        ]
    ).lower()
    if exact_identifier_tokens:
        hits = [token for token in exact_identifier_tokens if token.lower() in haystack]
        if hits:
            return True, "identifier-match"
    path = normalize_path_value(candidate.get("path") or candidate.get("source"))
    term_set = {str(term).strip().lower() for term in query_terms if str(term).strip()}
    if {"offline", "service", "worker", "bootstrap", "offlineenabled", "settingsprovider"}.intersection(term_set):
        if (
            path.endswith("main.tsx")
            or path.endswith("settingsprovider.tsx")
            or path.endswith("offlinegate.ts")
            or path.endswith("useposconfig.ts")
            or path.endswith("organizationservice.cs")
        ):
            return True, "offline-owner-allow"
    candidate_bucket = source_type_bucket(candidate)
    module = normalize_scope_value(candidate.get("module"))
    pack = normalize_scope_value(candidate.get("pack"))
    files = {normalize_path_value(file_path) for file_path in candidate.get("files") or []}
    files.discard("")
    if not candidate_matches_keyword_lock(candidate, keyword_lock):
        return False, "dominant-module-lock"
    if query_profile in {"code_debug", "infra_runtime"} and candidate_bucket == "doc":
        if path and path in scope["paths"]:
            return True, "doc-same-source"
        if files and files.intersection(scope["files"]):
            return True, "doc-shared-file"
        if pack and pack in scope["packs"]:
            return True, "doc-same-pack"
        # Intra-module fallback: allow behavior docs from the same module when the
        # keyword lock confirms module dominance. Mirrors the fix in vector_scope_allowed.
        dominant_module = normalize_scope_value(keyword_lock.get("dominant_module"))
        if module and keyword_lock.get("enabled") and module == dominant_module:
            return True, "doc-same-module"
        return False, "code-profile-doc-suppressed"
    if query_profile == "workflow_discovery" and candidate_bucket == "doc":
        if pack and pack in scope["packs"]:
            return True, "workflow-doc-pack"
        if module and module in scope["modules"]:
            return True, "workflow-doc-module"
    if path and path in scope["paths"]:
        return True, "same-source"
    if files and files.intersection(scope["files"]):
        return True, "shared-file"
    if pack and pack in scope["packs"]:
        return True, "same-pack"
    if module and module in scope["modules"]:
        return True, "same-module"
    return False, "semantic-scope-mismatch"


def semantic_keyword_score(
    candidate: dict[str, Any],
    vector_candidates: list[dict[str, object]],
    scope: dict[str, set[str]],
    *,
    exact_identifier_tokens: list[str],
    query_terms: list[str],
    query_profile: str,
    keyword_lock: dict[str, object],
    project_rules: dict[str, Any],
) -> float:
    rank = int(candidate.get("rank") or 9999)
    score = 1.0 / (20 + rank)
    raw_score = float(candidate.get("score") or 0.0)
    score += min(raw_score, 100_000_000.0) / 100_000_000.0
    path = normalize_path_value(candidate.get("path") or candidate.get("source"))
    pack = normalize_scope_value(candidate.get("pack"))
    module = normalize_scope_value(candidate.get("module"))
    title = str(candidate.get("title") or "").lower()
    term_set = {str(term).strip().lower() for term in query_terms if str(term).strip()}
    candidate_bucket = source_type_bucket(candidate)
    if not candidate_matches_keyword_lock(candidate, keyword_lock):
        score -= 12.0
    if query_profile in {"code_debug", "infra_runtime"}:
        if candidate_bucket == "code":
            score += 4.5
        elif candidate_bucket == "doc":
            score -= 6.5
    elif query_profile == "workflow_discovery":
        if candidate_bucket == "doc":
            score += 3.0
        elif candidate_bucket == "code":
            score += 1.0
    elif query_profile == "cross_module_bridge" and candidate_bucket == "code":
        score += 2.5
    if path in scope["files"] or path in scope["paths"]:
        score += 6.0
    if pack and pack in scope["packs"]:
        score += 3.5
    if module and module in scope["modules"]:
        score += 1.5
    if exact_identifier_tokens:
        for token in exact_identifier_tokens:
            lowered = token.lower()
            if lowered in path or lowered in title:
                score += 5.0
    score += apply_project_semantic_rules(
        candidate,
        query_terms=query_terms,
        query_profile=query_profile,
        project_rules=project_rules,
    )
    score += candidate_specificity_delta(
        candidate,
        query_terms=query_terms,
        query_profile=query_profile,
    )
    score -= generic_candidate_penalty(
        candidate,
        query_terms=query_terms,
        query_profile=query_profile,
        exact_identifier_tokens=exact_identifier_tokens,
    )
    for vector_rank, vector in enumerate(vector_candidates[:12], start=1):
        vector_weight = 1.0 / (10 + vector_rank)
        vector_path = normalize_path_value(vector.get("path") or vector.get("source"))
        vector_pack = normalize_scope_value(vector.get("pack"))
        vector_module = normalize_scope_value(vector.get("module"))
        vector_files = {normalize_path_value(item) for item in vector.get("files") or []}
        vector_bucket = source_type_bucket(vector)
        if path and path == vector_path:
            score += 7.0 * vector_weight
        if path and path in vector_files:
            score += 5.5 * vector_weight
        if pack and pack == vector_pack:
            score += 3.0 * vector_weight
        if module and module == vector_module:
            score += 1.2 * vector_weight
        if query_profile in {"code_debug", "infra_runtime"} and vector_bucket == "doc":
            score -= 1.6 * vector_weight
        elif query_profile == "workflow_discovery" and vector_bucket == "doc":
            score += 1.4 * vector_weight
    return score


def vector_scope_allowed(
    candidate: dict[str, object],
    scope: dict[str, set[str]],
    *,
    require_scope_match: bool,
    exact_identifier_tokens: list[str],
    query_profile: str,
    keyword_lock: dict[str, object],
) -> tuple[bool, str]:
    haystack = " ".join(
        [
            str(candidate.get("path") or ""),
            str(candidate.get("source") or ""),
            str(candidate.get("snippet") or ""),
            " ".join(str(item) for item in candidate.get("files") or []),
        ]
    ).lower()
    if exact_identifier_tokens:
        hits = [token for token in exact_identifier_tokens if token.lower() in haystack]
        if not hits and require_scope_match:
            return False, "missing-identifier-match"
    if not require_scope_match:
        return True, "scope-check-disabled"
    candidate_bucket = source_type_bucket(candidate)
    module = normalize_scope_value(candidate.get("module"))
    pack = normalize_scope_value(candidate.get("pack"))
    path = normalize_path_value(candidate.get("path") or candidate.get("source"))
    files = {normalize_path_value(file_path) for file_path in candidate.get("files") or []}
    files.discard("")
    if not candidate_matches_keyword_lock(candidate, keyword_lock):
        return False, "dominant-module-lock"
    if query_profile in {"code_debug", "infra_runtime"} and candidate_bucket == "doc":
        if path and path in scope["paths"]:
            return True, "doc-same-source"
        if files and files.intersection(scope["files"]):
            return True, "doc-shared-file"
        if pack and pack in scope["packs"]:
            return True, "doc-same-pack"
        # Intra-module fallback: allow behavior docs from the same module when the
        # keyword lock confirms module dominance. Prevents over-suppression of
        # semantically relevant sub-domain docs (pharmacy, ledger, package) that
        # don't share a pack with keyword candidates but belong to the same module.
        dominant_module = normalize_scope_value(keyword_lock.get("dominant_module"))
        if module and keyword_lock.get("enabled") and module == dominant_module:
            return True, "doc-same-module"
        return False, "code-profile-doc-suppressed"
    if query_profile == "cross_module_bridge" and candidate_bucket == "doc":
        if pack and pack in scope["packs"]:
            return True, "bridge-doc-pack"
        if module and module in scope["modules"]:
            return True, "bridge-doc-module"
    if path and path in scope["paths"]:
        return True, "same-source"
    if files and files.intersection(scope["files"]):
        return True, "shared-file"
    if pack and pack in scope["packs"]:
        return True, "same-pack"
    if module and module in scope["modules"]:
        return True, "same-module"
    return False, "scope-mismatch"


def query_identifier_tokens(query: str) -> list[str]:
    identifiers: list[str] = []
    seen: set[str] = set()
    for match in QUERY_IDENTIFIER_RE.finditer(query):
        raw = match.group(0).strip()
        lowered = raw.lower()
        if len(raw) < 3:
            continue
        if "." in raw:
            for part in [part for part in raw.split(".") if part]:
                part_lower = part.lower()
                if len(part) < 3 or part_lower in seen:
                    continue
                seen.add(part_lower)
                identifiers.append(part)
            continue
        # Only keep tokens that look like code identifiers — not plain English words.
        # A token qualifies if it has uppercase (CamelCase), underscore, a digit,
        # or is a very long compound (≥15 chars like "hmsledgerservice").
        # Plain lowercase words like "evaluation", "settlement", "controller"
        # must be excluded — they become exact_identifier_tokens that suppress
        # all semantic vectors whose text doesn't contain that exact English word.
        _is_code_identifier = (
            not raw.islower()                        # CamelCase: "HmsLedgerController"
            or "_" in raw                            # snake_case: "hms_ledger"
            or any(c.isdigit() for c in raw)         # versioned: "posV2", "v2"
            or (raw.islower() and len(raw) >= 15)    # long compound: "hmsledgerservice"
        )
        if not _is_code_identifier:
            continue
        if lowered not in seen:
            seen.add(lowered)
            identifiers.append(raw)
    return identifiers


def normalize_scope_value(value: object) -> str:
    return str(value or "").strip().lower()


def normalize_path_value(value: object) -> str:
    return str(value or "").replace("\\", "/").strip().lower()
