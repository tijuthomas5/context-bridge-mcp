from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from graphify_loader import load_config
from models import ContextDocument
from cb_profiles import load_profile


TOKEN_RE = re.compile(r"[a-z0-9]+", re.IGNORECASE)
QUERY_IDENTIFIER_RE = re.compile(r"\b[A-Za-z_][A-Za-z0-9_.]{2,}\b")
# A genuine internal CamelCase/PascalCase "hump" -- a lowercase letter immediately
# followed by an uppercase one (e.g. "MedicationOverview" has "nO"). Used by
# strict_camel_identifiers() (see below) to tell real multi-word code identifiers
# apart from plain English words that are merely capitalized by sentence/title-case
# position (e.g. "Overview", "Symptom"). Deliberately NOT used by
# query_identifier_tokens() -- see the note in that function for why.
_CAMEL_HUMP_RE = re.compile(r"[a-z][A-Z]")
STOP_WORDS = {
    "the", "and", "for", "with", "from", "this", "that", "what", "where", "when", "how",
    "why", "can", "does", "into", "have", "has", "are", "was", "were", "will", "shall",
    "file", "files", "code", "work", "issue", "bug", "fix",
    # narrative / emotional words that pollute keyword scoring on long prompts
    "nightmare", "furious", "hostage", "threatening", "physically", "absolutely",
    "completely", "immediately", "worse",
    # NOTE: "phantom", "fatal", "locking", "ghost" are HMS domain terms, not narrative
    # noise. "phantom" is a ledger-intent trigger token in the profile — keep them out.
    "horrible", "terrible", "urgent", "critical", "please", "help", "trying",
    "getting", "showing", "saying", "told", "called", "went", "came", "came",
    "police", "security", "family", "management", "hospital", "system", "just",
    "still", "even", "already", "always", "never", "again", "back", "much", "also",
}

MODULE_INTENT_TOKENS: dict[str, set[str]] = {}
# Module-to-vocab mapping is empty in core; profiles supply domain-specific entries via module_intent_tokens().

BROAD_SOURCE_TYPES = {"index.md", "scope-summary.md"}
GRAPH_OWNER_SOURCE_TYPES = {"graph.json", "dependency-edges.enrichment.json"}
OWNERSHIP_TOKENS = {
    "file", "files", "where", "implemented", "implementation", "owner", "ownership", "entity", "entities",
    "dto", "dtos", "service", "services", "controller", "controllers", "api", "type", "types", "ui",
    "frontend", "backend", "component", "components", "page", "pages", "appdbcontext", "dbset",
    "mapper", "mapping", "endpoint", "route",
}
BUSINESS_FLOW_TOKENS = {
    "workflow", "flow", "behavior", "state", "machine", "policy", "decision", "invariant", "scenario",
    "lifecycle", "process", "rule", "rules",
}
RUNTIME_TOKENS = {
    "debug", "runtime", "sql", "config", "permission", "permissions", "production", "verify", "check",
    "failing", "failed", "issue", "bug",
}
CODE_LEVEL_TOKENS = {
    "helper", "helpers", "hook", "hooks", "prop", "props", "parser", "parse", "preview", "sheet",
    "template", "bootstrap", "offline", "serviceworker", "service", "worker", "variable", "variables",
    "function", "functions", "method", "methods", "internal",
}
IMPLEMENTATION_TRACE_TOKENS = {
    "where", "handled", "handle", "implemented", "implementation", "blocked", "wrong", "failing", "failed",
    "reopen", "approval", "approve", "job", "jobs", "scheduler", "scheduled", "background", "controller",
    "controllers", "service", "services", "upload", "delete", "timezone", "batch", "reservation",
    "validation", "permission", "mapping", "owner", "ownership", "flow", "trace", "route", "endpoint",
    "cart", "checkout", "movement", "session", "reminder", "reminders",
    "escalation", "recipient", "recipients", "scope", "preview", "highlight", "remove", "rowversion",
    "queue", "safety", "concurrency", "scheduler", "scheduled", "attachment", "attachments", "uploaded",
    "upload", "result", "results", "bridge", "handoff", "selector", "appointment", "reservation",
    "variance", "quantity", "effective", "access", "evaluator", "catalog", "skipped", "skip",
    "completion", "completed", "running", "report", "open", "logo", "template",
    "print", "profile", "fallback", "store", "switch", "stale", "cleanup", "payment", "failure",
}
CROSS_MODULE_TOKENS = {"bridge", "integration", "cross", "handoff", "sync", "link", "between"}
# Structural (domain-agnostic) tokens only. Project-specific module names
# (e.g. hms, pos) are contributed at runtime by the active profile — see
# _generic_file_tokens(). Core stays generic.
GENERIC_FILE_TOKENS_BASE = {
    "main", "service", "services", "controller", "controllers", "dto", "dtos", "entity", "entities",
    "api", "type", "types", "ui", "src", "module", "modules",
    "frontend", "backend", "implemented", "implementation", "where", "file", "files",
}

# Deliberately SEPARATE from GENERIC_FILE_TOKENS_BASE/_generic_file_tokens() -- that set
# feeds score_document() and aggregate_files(), which drive general file search ranking
# and are already stable/tuned. This set is scoped ONLY to primary-owner symbol scoring
# (score_primary_owner_candidate()), so this fix cannot change how files rank in general
# search results, only which SYMBOL wins primary-owner among already-eligible candidates.
#
# Real diagnosed case: a query naming a file explicitly (e.g. "SomeModal.tsx") causes
# query_identifier_tokens() to split off a bare extension identifier (everything after the
# last "."). Every candidate of that extension trivially contains it in its path -- it's
# just the file extension -- so without this filter, score_primary_owner_candidate() handed
# out a flat +900 "identifier match" bonus to any file of that extension for matching
# something that isn't a real identifier at all and is guaranteed to match every file of
# that type in the codebase. Same problem applies to any language's extension token (.py,
# .java, .go, .rb, .php, ...) any time a query names a file with its extension -- not
# extension-specific.
#
# Short stopwords are included for the same reason: they can appear as bare substrings
# inside an unrelated identifier (e.g. a short 2-3 letter word matching as a substring
# inside a longer camelCase component/file name -- confirmed real case: a stopword from the
# query text matched as a bare substring inside an unrelated identifier, worth 160 points,
# which was enough by itself to flip primary-owner to the wrong candidate) and were being
# counted as genuine distinctive-token matches.
#
# Deliberately NOT merged into the existing STOP_WORDS set (used by tokenize() globally)
# for the same scoping reason as the extension tokens above: STOP_WORDS feeds general
# keyword search/tokenization everywhere in this file, and changing it would affect how
# ALL documents get scored and ranked, not just primary-owner symbol selection. Keeping
# a separate list here means this fix cannot touch general search ranking at all.
#
# This list intentionally covers common short (2-4 letter) English function words --
# prepositions, conjunctions, articles, short pronouns -- since these are the ones most
# likely to appear as an accidental substring inside a longer real identifier. Tokens of
# length 1 (e.g. "a", "i") never reach this point at all -- tokenize() already drops
# anything shorter than 2 characters.
_PRIMARY_OWNER_EXCLUDED_TOKENS = {
    # common file-extension tokens (language-agnostic, not just this project's stack)
    "tsx", "ts", "jsx", "js", "cs", "py", "java", "go", "rb", "php", "json", "md", "yml", "yaml",
    # 2-letter short stopwords that can appear as substrings inside unrelated identifiers
    "is", "in", "to", "of", "as", "on", "at", "or", "an", "no", "so", "up", "us", "we", "by", "if",
    # 3-4 letter short stopwords, same reason
    "the", "and", "for", "are", "was", "has", "not", "but", "yet", "nor", "via", "per",
    "our", "you", "his", "her", "its", "who", "why", "from", "this", "that", "into", "than", "then", "with",
}


def _is_excluded_owner_token(token: str) -> bool:
    """Shared exclusion check for score_primary_owner_candidate()'s three token-matching
    spots (distinctive-token path loop, identifier_hits count, query_identifiers loop) --
    single place to maintain the excluded list rather than duplicating it three times."""
    return token.lower() in _PRIMARY_OWNER_EXCLUDED_TOKENS


def _generic_file_tokens() -> set[str]:
    """Structural tokens + the active profile's module names (so a query token
    like a module name is treated as non-distinctive, matching legacy behavior)."""
    try:
        module_names = set(_active_profile().module_intent_tokens().keys())
    except Exception:
        module_names = set()
    return GENERIC_FILE_TOKENS_BASE | module_names
OWNER_PATH_MARKERS = (
    "/controllers/",
    "/services/",
    "/jobs/",
    "/dtos/",
    "/entities/",
    "/api/",
    "/components/",
    "/pages/",
    "/hooks/",
    "/utils/",
)
OWNER_FILE_PATTERNS = (
    "controller.cs",
    "service.cs",
    "job.cs",
    "dto.cs",
    "dtos.cs",
    "entity.cs",
    ".tsx",
)
# Project-specific patterns (e.g. "hmsapi.ts", "hms.types.ts") are injected by the active profile.
BROAD_FILE_PATTERNS = (
    "capability",
    "/workflows/",
    "/decisions/",
    "/blocker-playbooks/",
    "/chatbot-intents/",
    "/configs/",
    "index.md",
    "scope-summary.md",
)


SOURCE_EXTENSIONS = (".cs", ".tsx", ".ts", ".js")
IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
TS_COMPONENT_RE = re.compile(r"^\s*export\s+default\s+function\s+([A-Za-z_][A-Za-z0-9_]*)")
TS_FUNCTION_RE = re.compile(r"^\s*(?:export\s+)?(?:async\s+)?function\s+([A-Za-z_][A-Za-z0-9_]*)")
TS_TYPED_CONST_RE = re.compile(r"^\s*(?:export\s+)?const\s+([A-Za-z_][A-Za-z0-9_]*)\s*:\s*[^=]+\s*=")
TS_CONST_RE = re.compile(r"^\s*(?:export\s+)?const\s+([A-Za-z_][A-Za-z0-9_]*)\s*=")
CS_CLASS_RE = re.compile(r"^\s*(?:public|internal|private|protected)?\s*(?:sealed\s+|abstract\s+|partial\s+)*class\s+([A-Za-z_][A-Za-z0-9_]*)")
CS_METHOD_RE = re.compile(
    r"^\s*(?:public|private|protected|internal)\s+(?:static\s+)?(?:async\s+)?[A-Za-z0-9_<>\[\]\?,\s]+\s+([A-Za-z_][A-Za-z0-9_]*)\s*\("
)
SYMBOL_KIND_PRIORITY = {
    "controller_action": 0,
    "service_method": 0,
    "job_method": 0,
    "ui_component": 0,
    "ui_function": 1,
    "controller_class": 1,
    "service_class": 1,
    "job_class": 1,
    "method": 2,
    "dto_type": 3,
    "entity_type": 3,
    "file": 5,
}
SYMBOL_PRIMARY_OWNER_WEIGHT = {
    "controller_action": 1100.0,
    "service_method": 1050.0,
    "job_method": 1025.0,
    "ui_component": 1000.0,
    "ui_function": 900.0,
    "controller_class": 850.0,
    "service_class": 825.0,
    "job_class": 800.0,
    "method": 650.0,
    "dto_type": 350.0,
    "entity_type": 320.0,
    "file": 0.0,
}


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _raw_score_confidence(top_score: float, config: dict[str, Any]) -> float:
    confidence_scale = float(config.get("confidence_score_scale", 45.0))
    if top_score <= 0:
        return 0.0
    return min(0.95, float(top_score) / (float(top_score) + confidence_scale))


def _normalized_signal(value: int, target: int) -> float:
    if target <= 0:
        return 0.0
    return _clamp01(float(value) / float(target))


def _is_informative_confidence_token(token: str) -> bool:
    lowered = token.lower()
    if len(lowered) < 3:
        return False
    if lowered in STOP_WORDS:
        return False
    if lowered in _PRIMARY_OWNER_EXCLUDED_TOKENS:
        return False
    if lowered in _generic_file_tokens():
        return False
    return True


def _query_match_signal(
    query_tokens: list[str] | None,
    primary_owner: dict[str, Any] | None,
    ranked_files: list[dict[str, Any]] | None,
) -> float:
    informative_tokens = sorted({
        token.lower()
        for token in (query_tokens or [])
        if _is_informative_confidence_token(token)
    })
    if not informative_tokens:
        return 0.0

    haystack_parts: list[str] = []
    if primary_owner:
        haystack_parts.extend([
            str(primary_owner.get("label") or ""),
            str(primary_owner.get("path") or ""),
            str(primary_owner.get("pack") or ""),
            str(primary_owner.get("source") or ""),
        ])
    for item in (ranked_files or [])[:5]:
        source = item.get("source")
        haystack_parts.extend([
            str(item.get("path") or ""),
            str(item.get("pack") or ""),
            str(source if isinstance(source, str) else " ".join(source or [])),
        ])
    haystack = " ".join(haystack_parts).lower()
    matched = sum(1 for token in informative_tokens if token in haystack)
    target = max(1, min(len(informative_tokens), 4))
    return _normalized_signal(matched, target)


def compute_result_confidence(
    baseline_confidence: float,
    primary_owner: dict[str, Any] | None,
    code_blocks: list[dict[str, Any]] | None,
    symbol_hits: list[dict[str, Any]] | None,
    location_hints: list[dict[str, Any]] | None,
    dependency_chain: list[dict[str, Any]] | None,
    query_tokens: list[str] | None = None,
    ranked_files: list[dict[str, Any]] | None = None,
) -> float:
    owner_signal = 1.0 if primary_owner else 0.0
    code_signal = _normalized_signal(len(code_blocks or []), 4)
    symbol_signal = _normalized_signal(len(symbol_hits or []), 30)
    location_signal = _normalized_signal(len(location_hints or []), 8)
    dependency_signal = _normalized_signal(len(dependency_chain or []), 6)
    query_match_signal = _query_match_signal(query_tokens, primary_owner, ranked_files)

    evidence_confidence = (
        owner_signal * 0.28
        + code_signal * 0.24
        + symbol_signal * 0.20
        + location_signal * 0.14
        + dependency_signal * 0.14
    )
    final_confidence = (
        (float(baseline_confidence) * 0.20)
        + (evidence_confidence * 0.55)
        + (query_match_signal * 0.25)
    )
    if query_match_signal < 0.20:
        final_confidence = min(final_confidence, 0.35)
    elif query_match_signal < 0.40:
        final_confidence = min(final_confidence, 0.55)
    if not primary_owner or not (code_blocks or []):
        final_confidence = min(final_confidence, 0.45)
    return round(min(0.95, _clamp01(final_confidence)), 3)


DEPENDENCY_RELATION_WEIGHT = {
    "calls": 600.0,
    "invokes": 600.0,
    "inherits": 520.0,
    "uses": 520.0,
    "depends_on": 500.0,
    "imports": 480.0,
    "imports_from": 480.0,
    "references": 450.0,
    "maps_to": 430.0,
    "returns": 420.0,
    "contains": 300.0,
    "defines": 280.0,
}


def project_root_from_here() -> Path:
    return Path(__file__).resolve().parents[2]


_PROFILE_CACHE: dict[str, Any] = {}


def _active_profile():
    """Load the active project ranking profile plugin (cached per config+profile key).
    CONTEXT_BRIDGE_PROFILE env var overrides the config's project_profile without editing files."""
    profile_env = (os.environ.get("CONTEXT_BRIDGE_PROFILE") or "").strip().lower()
    config_name = (os.environ.get("CONTEXT_BRIDGE_CONFIG") or "config.json").strip() or "config.json"
    cache_key = f"{config_name}:{profile_env}"
    cached = _PROFILE_CACHE.get(cache_key)
    if cached is not None:
        return cached
    root = project_root_from_here()
    if profile_env:
        project_profile = profile_env
        rules_root = "context_bridge/rules"
    else:
        try:
            config = load_config(root, config_name)
        except Exception:
            config = {}
        project_profile = str(config.get("project_profile") or "")
        rules_root = str(config.get("rules_root") or "context_bridge/rules")
    prof = load_profile(root, rules_root, project_profile)
    _PROFILE_CACHE[cache_key] = prof
    return prof


def tokenize(text: str) -> list[str]:
    expanded = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", text)
    raw_tokens = [m.group(0).lower() for m in TOKEN_RE.finditer(expanded)]
    tokens: list[str] = []
    for token in raw_tokens:
        if len(token) < 2 or token in STOP_WORDS:
            continue
        tokens.append(token)
        if len(token) > 3 and token.endswith("s"):
            tokens.append(token[:-1])
        if token == "followup":
            tokens.extend(["follow", "up"])
    return tokens


# Negation cues checked around a matched identifier -- used ONLY for the
# primary-owner exact-match bonus (see primary_owner_query_identifiers() below),
# NOT for file-level relevance (query_identifier_tokens() itself stays
# unfiltered). A query saying "X is not the owner" still means the FILE
# containing X is almost always the right file to retrieve -- the user is
# ruling X out from within the correct area, not saying X is irrelevant.
# Filtering negation into query_identifier_tokens() directly was tried and
# caused a real regression: it also stripped the file-level exact-identifier
# boost (score_document()), dropping a correct file out of the top-25 window
# entirely. Negation must only suppress "reward this SYMBOL as the decisive
# answer", never "this file is relevant".
#
# If a negation cue sits close enough to plausibly negate the identifier
# (either side: "not GetFoo" or "GetFoo is not the owner" -- real queries
# phrase it both ways), that identifier is dropped from the primary-owner
# candidate list. Mirrors the "selected proximity" negation-exclusion approach
# used in real-world search/IR systems (e.g. Amazon product search's
# negation-aware filtering, negation detection in clinical-text retrieval):
# exclude a term's positive-match credit when a negation cue is nearby, rather
# than attempt full syntactic negation-scope parsing.
_NEGATION_CUE_RE = re.compile(
    r"\b(?:not|never|without|except|excluding|neither|nor)\b|n't\b|\brather than\b|\binstead of\b|\bno longer\b",
    re.IGNORECASE,
)
# Character window checked on each side of the identifier match. This is a proximity
# heuristic, not exact word-count precision or full negation-scope parsing -- it can
# occasionally skip a legitimate identifier whose nearby "not" negates something else
# in the sentence. That's an accepted, bounded trade-off: the identifier still
# competes normally on every other scoring signal: it only loses this one extra bonus.
_NEGATION_WINDOW_CHARS = 40


def _is_negated_nearby(query: str, start: int, end: int) -> bool:
    window_start = max(0, start - _NEGATION_WINDOW_CHARS)
    window_end = min(len(query), end + _NEGATION_WINDOW_CHARS)
    return bool(_NEGATION_CUE_RE.search(query[window_start:window_end]))


def query_identifier_tokens(query: str) -> list[str]:
    identifiers: list[str] = []
    seen: set[str] = set()
    for match in QUERY_IDENTIFIER_RE.finditer(query):
        raw = match.group(0).strip()
        lowered = raw.lower()
        if len(raw) < 3:
            continue
        if lowered in STOP_WORDS:
            continue
        if "." in raw:
            parts = [part for part in raw.split(".") if part]
            for part in parts:
                part_lower = part.lower()
                if len(part) < 3 or part_lower in seen:
                    continue
                seen.add(part_lower)
                identifiers.append(part)
            continue
        # Skip plain English words — keep only tokens that look like code identifiers.
        # A token is a code identifier if it has uppercase (CamelCase), an underscore,
        # a digit, or is a very long compound word (≥15 chars, e.g. "hmsledgerservice").
        # Plain lowercase words like "evaluation", "controller", "settlement" are NOT
        # code identifiers and must be skipped — otherwise they become exact_identifier_tokens
        # that suppress all semantic vectors whose text doesn't contain that exact word.
        #
        # NOTE: this stays deliberately loose (`not raw.islower()` accepts ANY
        # initial-capital word, not just real multi-hump CamelCase). Several existing
        # callers rely on that looseness -- e.g. score_primary_owner_candidate()'s
        # label-substring bonus depends on words like "Medication"/"Overview" being
        # extracted here so a candidate whose own name contains those query words gets
        # rewarded (see tests/debug_evt_20_hybrid_primary_owner.py). A prior attempt to
        # tighten this in place (requiring an internal lowercase->uppercase transition)
        # broke that case even though it fixed the flooding regression it targeted
        # (see tests/debug_evt_20_regression.py) -- so per the Parallel-Change/
        # expand-contract pattern, the stricter check now lives in the separate,
        # additive `strict_camel_identifiers()` function below instead of here. Do NOT
        # tighten this function directly again without re-verifying both debug scripts.
        _is_code_identifier = (
            not raw.islower()
            or "_" in raw
            or any(c.isdigit() for c in raw)
            or (raw.islower() and len(raw) >= 15)
        )
        if not _is_code_identifier:
            continue
        if lowered not in seen:
            seen.add(lowered)
            identifiers.append(raw)
    return identifiers


def strict_camel_identifiers(query: str) -> list[str]:
    """A stricter, SEPARATE view of query identifiers: only tokens that look like a
    genuine multi-word code identifier -- CamelCase/PascalCase with a real internal
    "hump" (a lowercase-to-uppercase transition, e.g. "HmsFormsService" has "sF"),
    snake_case, a token containing a digit, or a long lowercase compound (>=15 chars).

    This intentionally does NOT modify or replace query_identifier_tokens(), which
    stays loose on purpose because other callers rely on that looseness (see the note
    in query_identifier_tokens()). This is an additive, expand-only function (Parallel
    Change / expand-contract pattern) for consumers that need real confidence a token
    is an actual code identifier -- e.g. a future "confirm this whole file is relevant"
    trigger -- where a plain capitalized English word like "Overview" or "Symptom"
    must NOT count, to avoid the false-positive flooding regression documented in
    tests/debug_evt_20_regression.py.

    Built on top of query_identifier_tokens()'s already-deduped, already-tokenized
    output rather than re-parsing the query, so both functions always agree on what
    counts as a "token" in the first place -- only the strictness of the final filter
    differs.
    """
    strict: list[str] = []
    for identifier in query_identifier_tokens(query):
        if "_" in identifier:
            strict.append(identifier)
        elif any(c.isdigit() for c in identifier):
            strict.append(identifier)
        elif identifier.islower() and len(identifier) >= 15:
            strict.append(identifier)
        elif _CAMEL_HUMP_RE.search(identifier):
            strict.append(identifier)
    return strict


def filter_strict_camel(identifiers: list[str]) -> list[str]:
    """Apply the same strictness test as strict_camel_identifiers() to an
    already-extracted list of identifiers (e.g. one that has already been
    negation-filtered by primary_owner_query_identifiers()). Used when you
    want both negation-filtering AND strictness, but the two filters live in
    separate functions (strict_camel_identifiers works on the raw query text;
    primary_owner_query_identifiers applies negation suppression). Neither
    function calls the other, so this is the correct composition point."""
    return [
        identifier for identifier in identifiers
        if (
            "_" in identifier
            or any(c.isdigit() for c in identifier)
            or (identifier.islower() and len(identifier) >= 15)
            or _CAMEL_HUMP_RE.search(identifier)
        )
    ]


def primary_owner_query_identifiers(query: str) -> list[str]:
    """Identifiers eligible for the primary-owner exact-match bonus
    (score_primary_owner_candidate()) ONLY -- a negation-filtered view built on
    top of query_identifier_tokens(), which itself stays unfiltered for
    file-level relevance (score_document()). See the _NEGATION_CUE_RE comment
    above for why this must be a separate function rather than a change to
    query_identifier_tokens() itself.

    Re-finds each identifier's position in the raw query text (via
    QUERY_IDENTIFIER_RE, the same regex query_identifier_tokens() uses) so the
    negation-proximity check has real character offsets to work with --
    query_identifier_tokens() itself only returns strings, not positions.
    """
    identifiers = query_identifier_tokens(query)
    if not identifiers:
        return identifiers
    negated: set[str] = set()
    for match in QUERY_IDENTIFIER_RE.finditer(query):
        if _is_negated_nearby(query, match.start(), match.end()):
            raw = match.group(0).strip()
            negated.add(raw.lower())
            if "." in raw:
                for part in raw.split("."):
                    if part:
                        negated.add(part.lower())
    if not negated:
        return identifiers
    return [identifier for identifier in identifiers if identifier.lower() not in negated]


def query_named_files(query: str) -> set[str]:
    """Extract whole filename-like dotted identifiers directly named in the query
    text (e.g. "admissionPolicy.ts", "admissionPolicy.types.ts"), lowercased.

    Reuses QUERY_IDENTIFIER_RE -- the same regex query_identifier_tokens() already
    matches these dotted strings with -- but query_identifier_tokens() immediately
    SPLITS each one on '.' into separate word parts for keyword scoring and
    discards the whole form. This keeps the whole filename intact so a ranked
    file's own basename can be checked for an EXACT match, not just a substring
    keyword overlap. Used by aggregate_files() to keep a file the query names
    explicitly inside the default max_files window even when many
    topically-similar files outscore it on generic keyword overlap alone.
    """
    named: set[str] = set()
    for match in QUERY_IDENTIFIER_RE.finditer(query):
        raw = match.group(0).strip()
        if len(raw) < 3 or "." not in raw:
            continue
        named.add(raw.lower())
    return named


def expand_query_tokens(query: str, tokens: list[str]) -> list[str]:
    expanded = list(tokens)
    expanded.extend(_active_profile().expand_query_tokens(query, list(tokens)))
    return expanded


def token_counts(text: str) -> Counter[str]:
    return Counter(tokenize(text))


def detect_module_intents(query_tokens: list[str]) -> set[str]:
    token_set = set(query_tokens)
    merged = {**MODULE_INTENT_TOKENS, **_active_profile().module_intent_tokens()}
    return {
        module
        for module, markers in merged.items()
        if token_set.intersection(markers)
    }


def detect_query_intents(query_tokens: list[str]) -> set[str]:
    token_set = set(query_tokens)
    intents: set[str] = set()
    if token_set.intersection(OWNERSHIP_TOKENS):
        intents.add("ownership")
    if token_set.intersection(BUSINESS_FLOW_TOKENS):
        intents.add("business_flow")
    if token_set.intersection(RUNTIME_TOKENS):
        intents.add("runtime_debug")
    if token_set.intersection(IMPLEMENTATION_TRACE_TOKENS):
        intents.add("implementation_trace")
    if token_set.intersection(CODE_LEVEL_TOKENS):
        intents.add("code_level")
    if token_set.intersection(CROSS_MODULE_TOKENS) or len(detect_module_intents(query_tokens)) >= 2:
        intents.add("cross_module")
    if not intents:
        intents.add("general")
    return intents


def load_index(project_root: Path, config: dict[str, Any]) -> list[ContextDocument]:
    index_rel = Path("context_bridge") / config.get("index_path", "data/context_index.json")
    index_path = project_root / index_rel
    if not index_path.exists():
        raise FileNotFoundError(f"Index not found: {index_path}. Run: python context_bridge/src/indexer.py")
    payload = json.loads(index_path.read_text(encoding="utf-8"))
    return [ContextDocument.from_dict(item) for item in payload.get("documents", [])]


def source_path(project_root: Path, relative_path: str) -> Path | None:
    normalized = str(relative_path or "").replace("\\", "/").strip()
    if not normalized:
        return None
    candidate = (project_root / normalized).resolve()
    try:
        candidate.relative_to(project_root.resolve())
    except ValueError:
        return None
    return candidate


def read_source_lines(project_root: Path, relative_path: str, cache: dict[str, list[str] | None]) -> list[str] | None:
    normalized = str(relative_path or "").replace("\\", "/").strip()
    if normalized in cache:
        return cache[normalized]
    file_path = source_path(project_root, normalized)
    if file_path is None or not file_path.exists() or not file_path.is_file():
        cache[normalized] = None
        return None
    if file_path.suffix.lower() not in SOURCE_EXTENSIONS:
        cache[normalized] = None
        return None
    cache[normalized] = file_path.read_text(encoding="utf-8", errors="replace").splitlines()
    return cache[normalized]


def label_search_patterns(label: str, kind: str) -> list[re.Pattern[str]]:
    text = str(label or "").strip()
    if not text:
        return []
    name = text
    if name.startswith(".") and name.endswith("()"):
        name = name[1:-2]
    elif name.endswith("()"):
        name = name[:-2]
    name = name.strip()
    if not name:
        return []
    escaped = re.escape(name)
    patterns: list[str] = []
    if kind in {"controller_class", "service_class", "job_class"}:
        patterns.extend([
            rf"\bclass\s+{escaped}\b",
            rf"\bpartial\s+class\s+{escaped}\b",
        ])
    elif kind == "ui_component":
        patterns.extend([
            rf"\bfunction\s+{escaped}\b",
            rf"\bconst\s+{escaped}\b",
            rf"\bexport\s+function\s+{escaped}\b",
            rf"\bexport\s+const\s+{escaped}\b",
        ])
    elif kind in {"controller_action", "service_method", "job_method", "ui_function", "method"}:
        patterns.extend([
            rf"\b{name}\s*\(",
            rf"\b{name}\s*<",
            rf"\b{name}\s*=",
            rf"\bfunction\s+{escaped}\b",
            rf"\bconst\s+{escaped}\b",
            rf"\basync\s+function\s+{escaped}\b",
            rf"\basync\s+{escaped}\s*\(",
            rf"\bpublic\b.*\b{escaped}\s*\(",
            rf"\bprivate\b.*\b{escaped}\s*\(",
            rf"\bprotected\b.*\b{escaped}\s*\(",
        ])
    elif kind == "file":
        return []
    else:
        patterns.extend([
            rf"\binterface\s+{escaped}\b",
            rf"\btype\s+{escaped}\b",
            rf"\bclass\s+{escaped}\b",
            rf"\bconst\s+{escaped}\b",
        ])
    return [re.compile(pattern) for pattern in patterns]


def normalize_symbol_name(label: str, kind: str) -> str:
    text = str(label or "").strip()
    if not text:
        return ""
    if kind in {"controller_action", "service_method", "job_method", "method"} and text.startswith(".") and text.endswith("()"):
        return text[1:-2]
    if kind == "ui_function" and text.endswith("()"):
        return text[:-2]
    return text


def is_low_value_symbol(label: str, kind: str) -> bool:
    name = normalize_symbol_name(label, kind)
    if not name:
        return True
    if name.upper() == name and "_" in name:
        return True
    if kind in {"ui_function", "ui_component"}:
        if any(char in name for char in "{}[]"):
            return True
        if " " in name:
            return True
        if not IDENTIFIER_RE.match(name):
            return True
    return False


def infer_kind_from_source(path: str, name: str, line_text: str) -> str:
    normalized = path.replace("\\", "/").lower()
    if normalized.endswith(".tsx"):
        if name[:1].isupper():
            return "ui_component"
        return "ui_function"
    if normalized.endswith((".ts", ".js")):
        return "ui_function"
    if normalized.endswith(".cs"):
        if "/controllers/" in normalized:
            return "controller_class" if "class " in line_text else "controller_action"
        if "/services/" in normalized:
            return "service_class" if "class " in line_text else "service_method"
        if "/jobs/" in normalized:
            return "job_class" if "class " in line_text else "job_method"
        if "/entities/" in normalized:
            return "entity_type" if "class " in line_text else "method"
        if "/dtos/" in normalized:
            return "dto_type" if "class " in line_text else "method"
        return "method"
    return "file"


def extract_source_symbols(path: str, lines: list[str], max_symbols: int = 6) -> list[dict[str, Any]]:
    symbols: list[dict[str, Any]] = []
    seen: set[tuple[str, int]] = set()
    suffix = path.lower()
    file_anchor_labels = expected_anchor_labels_for_path(path)
    collected: list[tuple[int, dict[str, Any]]] = []
    for index, raw_line in enumerate(lines, start=1):
        candidates: list[str] = []
        if suffix.endswith((".tsx", ".ts", ".js")):
            for pattern in (TS_COMPONENT_RE, TS_TYPED_CONST_RE, TS_FUNCTION_RE, TS_CONST_RE):
                match = pattern.search(raw_line)
                if match:
                    candidates.append(match.group(1))
        elif suffix.endswith(".cs"):
            for pattern in (CS_CLASS_RE, CS_METHOD_RE):
                match = pattern.search(raw_line)
                if match:
                    candidates.append(match.group(1))
        for name in candidates:
            if not IDENTIFIER_RE.match(name):
                continue
            key = (name, index)
            if key in seen:
                continue
            seen.add(key)
            kind = infer_kind_from_source(path, name, raw_line)
            if is_low_value_symbol(name, kind):
                continue
            label = f"{name}()" if kind.endswith("function") or kind.endswith("method") or kind.endswith("action") else name
            priority = 3
            stripped = raw_line.strip()
            normalized_name = name.lower()
            if normalized_name in file_anchor_labels:
                priority = -1
            elif suffix.endswith(".tsx") and stripped.startswith("export const ") and name[:1].isupper():
                priority = 0
            elif suffix.endswith(".tsx") and stripped.startswith("export default function "):
                priority = 0
            elif suffix.endswith(".tsx") and kind == "ui_component":
                priority = 1
            elif suffix.endswith((".tsx", ".ts", ".js")) and kind == "ui_function":
                priority = 2
            elif suffix.endswith(".cs") and kind in {"controller_action", "service_method", "job_method"}:
                priority = 0
            elif suffix.endswith(".cs") and kind in {"controller_class", "service_class", "job_class"}:
                priority = 1
            collected.append(
                (
                    priority,
                    {
                        "label": label,
                        "kind": kind,
                        "path": path,
                        "line": index,
                        "source_location": f"L{index}",
                        "module": None,
                        "pack": None,
                        "source": "live-source-fallback",
                        "source_type": "live source",
                        "score": 0.0,
                    },
                )
            )
    collected.sort(key=lambda item: (item[0], item[1]["line"]))
    for _, symbol in collected[:max_symbols]:
        symbols.append(symbol)
    return symbols


def expected_anchor_labels_for_path(path: str) -> set[str]:
    normalized = path.replace("\\", "/")
    name = normalized.rsplit("/", 1)[-1]
    if "." in name:
        name = name.rsplit(".", 1)[0]
    labels = {name.lower()}
    if "/services/" in normalized.lower() and not name.startswith("I"):
        labels.add(f"i{name}".lower())
    return labels


def verify_symbol_line(
    project_root: Path,
    path: str,
    label: str,
    kind: str,
    graph_line: int | None,
    file_cache: dict[str, list[str] | None],
    window: int,
) -> dict[str, Any]:
    lines = read_source_lines(project_root, path, file_cache)
    if not lines:
        return {
            "line": graph_line,
            "graph_line": graph_line,
            "line_status": "file_missing",
            "line_delta": None,
        }

    patterns = label_search_patterns(label, kind)
    if not patterns:
        return {
            "line": graph_line,
            "graph_line": graph_line,
            "line_status": "not_verifiable",
            "line_delta": None,
        }

    def match_line(line_text: str) -> bool:
        return any(pattern.search(line_text) for pattern in patterns)

    if isinstance(graph_line, int) and 1 <= graph_line <= len(lines):
        start = max(1, graph_line - max(1, window))
        end = min(len(lines), graph_line + max(1, window))
        for line_no in range(start, end + 1):
            if match_line(lines[line_no - 1]):
                status = "exact" if line_no == graph_line else "adjusted"
                return {
                    "line": line_no,
                    "graph_line": graph_line,
                    "line_status": status,
                    "line_delta": line_no - graph_line,
                }

    for line_no, line_text in enumerate(lines, start=1):
        if match_line(line_text):
            delta = None if graph_line is None else line_no - graph_line
            return {
                "line": line_no,
                "graph_line": graph_line,
                "line_status": "adjusted" if graph_line is not None else "located",
                "line_delta": delta,
            }

    return {
        "line": graph_line,
        "graph_line": graph_line,
        "line_status": "not_found",
        "line_delta": None,
    }


def build_code_block(
    project_root: Path,
    path: str,
    line: int | None,
    symbol: str,
    kind: str,
    file_cache: dict[str, list[str] | None],
    before: int,
    after: int,
    line_status: str,
    graph_line: int | None,
    line_delta: int | None,
) -> dict[str, Any] | None:
    lines = read_source_lines(project_root, path, file_cache)
    if not lines or not isinstance(line, int) or line < 1 or line > len(lines):
        return None
    start = max(1, line - max(0, before))
    end = min(len(lines), line + max(0, after))
    snippet_lines = []
    for line_no in range(start, end + 1):
        prefix = ">" if line_no == line else " "
        snippet_lines.append(f"{prefix}{line_no}: {lines[line_no - 1]}")
    block_id = "blk_" + hashlib.md5(f"{path}::{symbol}::{line}".encode("utf-8")).hexdigest()[:12]
    return {
        "block_id": block_id,
        "path": path,
        "symbol": symbol,
        "kind": kind,
        "line": line,
        "graph_line": graph_line,
        "line_status": line_status,
        "line_delta": line_delta,
        "line_start": start,
        "line_end": end,
        "text": "\n".join(snippet_lines),
    }


def doc_mentions_path(doc: ContextDocument, normalized_path: str) -> bool:
    source_file = str((doc.metadata or {}).get("source_file") or "").replace("\\", "/").lower()
    if source_file == normalized_path:
        return True
    if any(str(item or "").replace("\\", "/").lower() == normalized_path for item in doc.files):
        return True
    metadata = dict(doc.metadata or {})
    for symbol in metadata.get("symbol_hints") or []:
        if str((symbol or {}).get("source_file") or "").replace("\\", "/").lower() == normalized_path:
            return True
    for dependency in metadata.get("dependency_hints") or []:
        if str((dependency or {}).get("source_file") or "").replace("\\", "/").lower() == normalized_path:
            return True
        if str((dependency or {}).get("target_file") or "").replace("\\", "/").lower() == normalized_path:
            return True
    return False


def collect_docs_for_paths(
    scored: list[tuple[float, ContextDocument, list[str]]],
    normalized_paths: set[str],
    limit: int,
) -> list[tuple[float, ContextDocument, list[str]]]:
    exact: list[tuple[float, ContextDocument, list[str]]] = []
    seen: set[str] = set()
    for score, doc, reasons in scored:
        if doc.id in seen:
            continue
        if any(doc_mentions_path(doc, normalized_path) for normalized_path in normalized_paths):
            exact.append((score, doc, reasons))
            seen.add(doc.id)
            if len(exact) >= limit:
                break
    return exact


def broadest_chunk_for_path(docs: list[ContextDocument], normalized_path: str) -> ContextDocument | None:
    """Find the single most-complete chunk for a file that has multiple duplicate
    pack-scoped chunks (one graph-chunk document per Graphify pack that references
    it -- each pack's own extraction only captures the edges relevant to that
    pack's own feature scope, so a shared/hub file can have several chunks, each
    with a different, incomplete subset of its real dependency edges).

    A query's own keyword-relevance scoring naturally favors whichever chunk is
    topically closest to the query, which can starve out the one chunk that
    actually holds a cross-feature connection -- even though the index itself is
    correct. This looks across the FULL (unfiltered, unscored) document set for a
    given file and returns its most useful chunk, independent of any
    query-relevance score, so it can be force-included alongside whatever chunk
    already won on keyword matching. Mirrors the standard "parent-child"
    hierarchical RAG pattern: always pair a narrow, topic-matched chunk with its
    broader parent instead of letting the two compete in one ranking.

    Selection key is `dependency_hint_count` (the filtered, curated set of real
    cross-file relationships -- see collect_dependency_hints()), not raw
    `edge_count`. Raw edge_count includes every edge touching the file
    (self-edges, same-file edges, and edges to relation types excluded from
    dependency_hints), so a chunk with many raw-but-noisy edges could otherwise
    beat a chunk with fewer raw edges but more actually-useful cross-file
    dependencies -- the opposite of what "most complete" should mean here.
    edge_count is kept only as a tiebreaker between chunks with equal
    dependency_hint_count.
    """
    best: ContextDocument | None = None
    best_key = (-1, -1)
    for doc in docs:
        if doc.kind != "graphify_graph_chunk":
            continue
        source_file = str((doc.metadata or {}).get("source_file") or "").replace("\\", "/").lower()
        if source_file != normalized_path:
            continue
        metadata = doc.metadata or {}
        dependency_hint_count = int(metadata.get("dependency_hint_count") or 0)
        edge_count = int(metadata.get("edge_count") or 0)
        key = (dependency_hint_count, edge_count)
        if key > best_key:
            best_key = key
            best = doc
    return best


def reserve_top_file_code_block_slots(
    symbol_hits: list[dict[str, Any]],
    ranked_files: list[dict[str, Any]],
    reserve_count: int = 2,
) -> list[dict[str, Any]]:
    """Move up to `reserve_count` of the top-ranked file's own symbol_hits to the
    front of the list, ahead of everything else, preserving their relative order
    and the relative order of everything not reserved.

    enrich_symbol_hits() consumes this list strictly in order and stops once
    code_block_max_blocks is reached, globally across all files. Without this,
    the #1 ranked file can be represented by only its single highest-scoring
    symbol (or none) if a few other well-ranked files each contribute several
    strong-scoring symbols first. This guarantees the top file gets a fair
    minimum share of the existing budget -- it does not add any candidate that
    wasn't already going to be considered, and does not change scores or ranks.
    """
    if not symbol_hits or not ranked_files or reserve_count <= 0:
        return symbol_hits
    top_path = str(ranked_files[0].get("path") or "").replace("\\", "/").lower()
    if not top_path:
        return symbol_hits
    reserved: list[dict[str, Any]] = []
    remainder: list[dict[str, Any]] = []
    for item in symbol_hits:
        item_path = str(item.get("path") or "").replace("\\", "/").lower()
        if item_path == top_path and len(reserved) < reserve_count:
            reserved.append(item)
        else:
            remainder.append(item)
    if not reserved:
        return symbol_hits
    return reserved + remainder


def enrich_symbol_hits(
    project_root: Path,
    config: dict[str, Any],
    symbol_hits: list[dict[str, Any]],
    file_cache: dict[str, list[str] | None],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    window = int(config.get("line_verify_window", 12) or 12)
    before = int(config.get("code_block_context_before", 4) or 4)
    after = int(config.get("code_block_context_after", 8) or 8)
    max_blocks = int(config.get("code_block_max_blocks", 6) or 6)
    enable_code_blocks = bool(config.get("enable_code_blocks", True))
    enriched: list[dict[str, Any]] = []
    code_blocks: list[dict[str, Any]] = []

    for hit in symbol_hits:
        current = dict(hit)
        verified = verify_symbol_line(
            project_root=project_root,
            path=str(current.get("path") or ""),
            label=str(current.get("label") or ""),
            kind=str(current.get("kind") or ""),
            graph_line=current.get("line") if isinstance(current.get("line"), int) else None,
            file_cache=file_cache,
            window=window,
        )
        current["graph_line"] = verified.get("graph_line")
        current["verified_line"] = verified.get("line")
        current["line"] = verified.get("line")
        current["line_status"] = verified.get("line_status")
        current["line_delta"] = verified.get("line_delta")
        if enable_code_blocks and len(code_blocks) < max_blocks:
            block = build_code_block(
                project_root=project_root,
                path=str(current.get("path") or ""),
                line=current.get("line") if isinstance(current.get("line"), int) else None,
                symbol=str(current.get("label") or ""),
                kind=str(current.get("kind") or ""),
                file_cache=file_cache,
                before=before,
                after=after,
                line_status=str(current.get("line_status") or ""),
                graph_line=current.get("graph_line") if isinstance(current.get("graph_line"), int) else None,
                line_delta=current.get("line_delta") if isinstance(current.get("line_delta"), int) else None,
            )
            if block:
                current["code_block"] = block
                code_blocks.append(block)
        enriched.append(current)
    return enriched, code_blocks


def append_fallback_symbols(
    project_root: Path,
    ranked_files: list[dict[str, Any]],
    symbol_hits: list[dict[str, Any]],
    file_cache: dict[str, list[str] | None],
    limit: int = 24,
) -> list[dict[str, Any]]:
    seen = {
        (
            str(item.get("label") or "").lower(),
            str(item.get("path") or "").lower(),
            int(item.get("line") or 0),
        )
        for item in symbol_hits
    }
    covered_paths = {str(item.get("path") or "").lower() for item in symbol_hits}
    kinds_by_path: dict[str, set[str]] = defaultdict(set)
    for item in symbol_hits:
        kinds_by_path[str(item.get("path") or "").lower()].add(str(item.get("kind") or ""))
    ranked_by_path = {str(item.get("path") or "").lower(): item for item in ranked_files}
    fallback_hits = list(symbol_hits)
    for file_item in ranked_files:
        path = str(file_item.get("path") or "")
        normalized = path.lower()
        if not path or not path.lower().endswith(SOURCE_EXTENSIONS):
            continue
        needs_component_anchor = normalized.endswith(".tsx") and "ui_component" not in kinds_by_path.get(normalized, set())
        anchor_labels = expected_anchor_labels_for_path(path)
        existing_anchor_labels = {
            str(item.get("label") or "").replace("()", "").lower()
            for item in symbol_hits
            if str(item.get("path") or "").lower() == normalized
        }
        needs_class_anchor = (
            normalized.endswith(".cs")
            and (
                ("/controllers/" in normalized and ("controller_class" not in kinds_by_path.get(normalized, set()) or not existing_anchor_labels.intersection(anchor_labels)))
                or ("/services/" in normalized and ("service_class" not in kinds_by_path.get(normalized, set()) or not existing_anchor_labels.intersection(anchor_labels)))
                or ("/jobs/" in normalized and ("job_class" not in kinds_by_path.get(normalized, set()) or not existing_anchor_labels.intersection(anchor_labels)))
                or ("/entities/" in normalized and ("entity_type" not in kinds_by_path.get(normalized, set()) or not existing_anchor_labels.intersection(anchor_labels)))
                or ("/dtos/" in normalized and ("dto_type" not in kinds_by_path.get(normalized, set()) or not existing_anchor_labels.intersection(anchor_labels)))
            )
        )
        if normalized in covered_paths and not needs_component_anchor and not needs_class_anchor:
            continue
        lines = read_source_lines(project_root, path, file_cache)
        if not lines:
            continue
        added_for_path = False
        for symbol in extract_source_symbols(path, lines):
            if needs_component_anchor and str(symbol.get("kind") or "") != "ui_component":
                continue
            if needs_class_anchor and str(symbol.get("kind") or "") not in {"controller_class", "service_class", "job_class", "entity_type", "dto_type"}:
                continue
            key = (
                str(symbol.get("label") or "").lower(),
                str(symbol.get("path") or "").lower(),
                int(symbol.get("line") or 0),
            )
            if key in seen:
                continue
            seen.add(key)
            symbol["module"] = file_item.get("module")
            symbol["pack"] = file_item.get("pack")
            symbol["score"] = float(file_item.get("score") or 0.0)
            symbol["source"] = (file_item.get("source") or ["live-source-fallback"])[0] if isinstance(file_item.get("source"), list) else file_item.get("source")
            fallback_hits.append(symbol)
            covered_paths.add(normalized)
            kinds_by_path[normalized].add(str(symbol.get("kind") or ""))
            added_for_path = True
            break
        if added_for_path:
            continue
    fallback_hits.sort(
        key=lambda item: (
            ranked_by_path.get(str(item.get("path") or "").lower(), {}).get("score", 0.0) == 0,
            SYMBOL_KIND_PRIORITY.get(str(item.get("kind") or ""), 9),
            -float(item.get("score") or 0.0),
            str(item.get("path") or ""),
            int(item.get("line") or 0),
        )
    )
    return fallback_hits[:limit]


def score_document(doc: ContextDocument, query_tokens: list[str], query: str) -> tuple[float, list[str]]:
    haystacks = {
        "title": doc.title.lower(),
        "path": doc.path.lower(),
        "module": (doc.module or "").lower(),
        "pack": (doc.pack or "").lower(),
        "source_type": doc.source_type.lower(),
        "text": doc.text.lower(),
        "files": " ".join(doc.files).lower(),
        "facts": " ".join(doc.facts).lower(),
    }
    haystack_counts = {name: token_counts(text) for name, text in haystacks.items()}
    weights = {
        "title": 7.0,
        "path": 6.0,
        "module": 8.0,
        "pack": 8.0,
        "source_type": 2.0,
        "text": 1.0,
        "files": 5.0,
        "facts": 5.0,
    }
    score = 0.0
    reasons: list[str] = []
    query_identifiers = query_identifier_tokens(query)
    for token in query_tokens:
        token_score = 0.0
        token_reasons: list[str] = []
        for name, counts in haystack_counts.items():
            count = counts.get(token, 0)
            if count <= 0:
                continue
            add = weights[name] * min(count, 8)
            token_score += add
            token_reasons.append(name)
        if token_score:
            score += token_score
            reasons.append(f"matched '{token}' in {', '.join(token_reasons[:4])}")

    phrase = query.strip().lower()
    if len(phrase) >= 4:
        for name in ("title", "path", "module", "pack", "facts"):
            if phrase in haystacks[name]:
                score += 20.0
                reasons.append(f"matched phrase in {name}")

    for identifier in query_identifiers:
        lowered = identifier.lower()
        matched = False
        if lowered in haystacks["path"] or lowered in haystacks["files"] or lowered in haystacks["title"]:
            score += 160.0
            matched = True
        elif lowered in haystacks["text"]:
            score += 70.0
            matched = True
        if matched:
            reasons.append(f"matched identifier '{identifier}'")

    token_set = set(query_tokens)
    query_intents = detect_query_intents(query_tokens)
    query_identifiers = query_identifier_tokens(query)
    query_identifiers = query_identifier_tokens(query)
    source_level = str(doc.metadata.get("source_level", "central")).lower()
    area = str(doc.metadata.get("area", "")).lower()

    if doc.source_type in {"GRAPH_REPORT.md", "source-files.txt", "scope-summary.md", "behavior pack", "index.md"}:
        score *= 1.12
    if doc.source_type in GRAPH_OWNER_SOURCE_TYPES:
        score *= 0.95
    if doc.source_type == "graph chunk":
        score *= 1.08

    intents = detect_module_intents(query_tokens)
    doc_module = (doc.module or "").lower()
    if intents:
        if doc_module in intents:
            score *= 1.45
            reasons.append(f"boosted for module intent '{doc_module}'")
        elif doc_module and doc_module not in intents and "cross_module" not in query_intents:
            score *= 0.82
            reasons.append(f"penalized outside module intent '{doc_module}'")

    if "ownership" in query_intents:
        if source_level == "secondary":
            score *= 1.45
            reasons.append("boosted secondary ownership graph")
        if doc.source_type in {"graph chunk", "GRAPH_REPORT.md", "source-files.txt", *GRAPH_OWNER_SOURCE_TYPES}:
            score *= 1.18
            reasons.append("boosted ownership source")
        if doc.source_type in {"index.md", "scope-summary.md"}:
            score *= 0.72
            reasons.append("reduced broad source for ownership query")
    if "implementation_trace" in query_intents:
        if doc.source_type in {"source-files.txt", "graph chunk", *GRAPH_OWNER_SOURCE_TYPES}:
            score *= 1.5
            reasons.append("boosted source-owner document")
        if source_level == "secondary":
            score *= 1.35
            reasons.append("boosted secondary implementation trace")
        if doc.source_type in {"index.md", "scope-summary.md", ".md"}:
            score *= 0.68
            reasons.append("reduced broad doc for implementation trace")
        if doc.source_type == "behavior pack" and not any(
            marker in doc.path.lower()
            for marker in ("api-map", "source-files", "data-dictionary", "runtime-verification")
        ):
            score *= 0.78
            reasons.append("reduced generic behavior doc for implementation trace")
    if "business_flow" in query_intents:
        if doc.source_type == "behavior pack":
            score *= 1.35
            reasons.append("boosted behavior source for flow query")
        if source_level == "secondary":
            score *= 0.88
            reasons.append("reduced secondary graph for flow query")
    if "runtime_debug" in query_intents and "runtime-verification" in doc.path.lower():
        score *= 1.5
        reasons.append("boosted runtime verification source")
    if "code_level" in query_intents:
        if doc.source_type in {"graph chunk", "source-files.txt", "GRAPH_REPORT.md", *GRAPH_OWNER_SOURCE_TYPES}:
            score *= 1.35
            reasons.append("boosted code-level source")
        if doc.source_type in {"index.md", "scope-summary.md"}:
            score *= 0.58
            reasons.append("reduced broad source for code-level query")
    if "cross_module" in query_intents:
        lowered = f"{doc.path} {doc.pack or ''} {doc.title}".lower()
        if any(marker in lowered for marker in ("cross-module", "bridge", "bridges", "integration", "integrations")):
            score *= 1.55
            reasons.append("boosted cross-module bridge source")

    score, _doc_reasons = _active_profile().adjust_document_score(
        score, query_tokens, doc.path, doc.pack, doc.title, doc.text
    )
    reasons.extend(_doc_reasons)

    layer_hits = {
        "data": {"data", "appdbcontext", "dbset", "migration", "migrations"},
        "dtos": {"dto", "dtos", "type", "types"},
        "entities": {"entity", "entities"},
        "services": {"service", "services"},
        "controllers": {"controller", "controllers", "endpoint", "route"},
        "api": {"api", "client"},
        # NOTE: "components"/"ui" intentionally removed — nearly every frontend file
        # lives under a `components/` folder in this codebase, so matching that word
        # was a near-universal, non-discriminating boost, not a real topical signal.
        # It was inflating irrelevant generic UI files (modals/panels/forms) to the
        # top of results whenever a query merely used the word "components" in its
        # phrasing (e.g. "Which components participate in X?"), regardless of topic.
    }
    area_text = f"{area} {doc.path.lower()} {doc.title.lower()}"
    for layer, markers in layer_hits.items():
        if token_set.intersection(markers) and layer in area_text:
            score *= 1.12
            reasons.append(f"boosted layer match '{layer}'")
            break

    if doc.source_type in BROAD_SOURCE_TYPES:
        score *= 0.78
        reasons.append("penalized broad source")
    if doc.source_type == "behavior pack":
        score *= 1.15
        reasons.append("boosted behavior pack")
    return score, reasons


def best_snippets(doc: ContextDocument, query_tokens: list[str], limit: int = 3) -> list[str]:
    candidates = doc.facts[:]
    for raw in doc.text.splitlines():
        line = raw.strip()
        if not line or line.startswith(("#", "|", "```")):
            continue
        if len(line) > 280:
            line = line[:277] + "..."
        candidates.append(line)

    scored: list[tuple[int, str]] = []
    for line in candidates:
        lower = line.lower()
        hits = sum(1 for token in query_tokens if token in lower)
        if hits:
            scored.append((hits, line))
    scored.sort(key=lambda item: (-item[0], len(item[1])))
    return [line for _, line in scored[:limit]]


RANKING_PROFILE = "pack-first-owner-v4"


def file_position_divisor(idx: int) -> float:
    """Divisor applied to a document's score for the idx-th file in its own
    "files" list, before any relevance-based scoring.

    A file's position in that list is an artifact of how the document happened
    to enumerate related files -- it is not itself a relevance signal, so a
    flat linear divisor (idx + 1) over-punishes files that are real owners but
    happen to be listed later (e.g. idx=9 -> a 10x reduction before any real
    scoring even applies). This is the same "position bias" problem documented
    in ranking/search literature (e.g. position-bias-corrected ranking, IPW
    correction methods) -- the standard mitigation is to dampen rather than
    remove the signal, so idx=0 (the common case) is completely unaffected and
    only deeper positions are cushioned.

    idx=0  -> 1.0   (unchanged from the original 1/(idx+1) behavior)
    idx=1  -> 2.0   (unchanged)
    idx=4  -> ~2.61  (was 5.0)
    idx=9  -> ~3.30  (was 10.0)
    idx=24 -> ~4.22  (was 25.0)
    """
    if idx <= 1:
        return float(idx + 1)
    return 1.0 + math.log1p(idx)


def named_file_match_strength(basename: str, result_query_tokens: list[str]) -> float:
    """How completely the query's own words cover this named file's distinctive
    words, as a 0..1 fraction.

    query_named_files() only checks whether the query literally mentions a
    filename -- it does not distinguish an exact-subject match from a
    same-family decoy the query also happens to name (e.g. a query about
    "discharge readiness REPORT" that also lists a similarly-named but
    different "discharge readiness PAGE" file as one of several keywords).
    Real-world search/entity-resolution ranking treats these as different
    match tiers -- exact match ranked strictly above partial match -- rather
    than giving every named candidate an identical reward. This returns that
    tier as a continuous fraction: 1.0 when every one of the file's own
    distinctive words is echoed in the query, lower when some are missing.

    Floored at 0.4 so an explicitly-named file never loses its boost entirely
    (it was still asked for by name) -- only the DEGREE of the boost changes.
    """
    stem = basename.rsplit(".", 1)[0]
    basename_tokens = {
        token
        for token in tokenize(stem.replace("_", " ").replace("-", " "))
        if token not in _generic_file_tokens()
    }
    if not basename_tokens:
        return 1.0
    query_token_set = set(result_query_tokens)
    covered = sum(1 for token in basename_tokens if token in query_token_set)
    fraction = covered / len(basename_tokens)
    return max(0.4, fraction)


def aggregate_files(
    results: list[dict[str, Any]],
    max_files: int,
    query_tokens: list[str],
    named_files: set[str] | None = None,
    max_files_per_document: int = 0,
) -> list[dict[str, Any]]:
    """
    max_files_per_document: 0 (default) = no cap, identical to pre-existing behavior --
    every file a matching document lists goes through the full scoring loop below.

    When set >0, bounds per-query cost for any single document with an unusually long
    `files` list (e.g. a dependency-edge enrichment doc can list up to 150 files) by only
    running the full scoring loop on that document's most query-relevant files, not all
    of them. This mirrors how large-scale search systems (Lucene block-skipping, staged
    retrieval funnels) bound per-query cost: cheap relevance pass first, expensive scoring
    only on the bounded survivors -- not a raw positional truncation.

    Deliberately NOT a simple `file_candidates[:cap]` slice: a document's `files` list is
    stored in first-seen/JSON order (see file_position_divisor()'s own docstring -- this
    codebase already treats list position as unrelated to relevance and dampens it with a
    log curve rather than a hard cutoff for exactly that reason). Slicing by raw position
    would silently drop a genuinely relevant file that happened to be listed late. Instead,
    when a document's file list exceeds the cap, it's re-ordered by a cheap per-file query
    token match count first, and only the top `max_files_per_document` of THAT order are
    kept -- same intent as the existing scoring below, just cheaper, and only used to
    decide what survives to the real scoring pass.
    """
    scores: dict[str, float] = defaultdict(float)
    sources: dict[str, set[str]] = defaultdict(set)
    query_intents_all: set[str] = set()
    query_tokens_all: list[str] = []
    scoped_modules: set[str] = set()
    scoped_packs: set[str] = set()
    for result in results[:25]:
        query_intents_all.update(result.get("_query_intents", []))
        query_tokens_all.extend(result.get("_query_tokens", []))
        if result.get("module"):
            scoped_modules.add(str(result.get("module")).lower())
        if result.get("pack"):
            scoped_packs.add(str(result.get("pack")).lower())
    top_specific_packs = detect_top_specific_packs(results)

    for result in results:
        result_score = float(result["score"])
        result_query_tokens = result.get("_query_tokens", [])
        query_intents = set(result.get("_query_intents", []))
        file_candidates = list(result.get("files", []))
        source_level = str((result.get("metadata") or {}).get("source_level", "")).lower()
        if result.get("pack") == "secondary-ownership" and source_level == "secondary":
            file_candidates = file_candidates[: secondary_file_limit(result)]
        if max_files_per_document and len(file_candidates) > max_files_per_document:
            def _quick_query_match_count(fp: str) -> int:
                norm = fp.replace("\\", "/").lower()
                return sum(1 for token in result_query_tokens if token in norm)
            # Stable sort: ties keep their original relative order, so this only
            # reorders when a file actually matches more query tokens than another.
            file_candidates = sorted(file_candidates, key=_quick_query_match_count, reverse=True)
            file_candidates = file_candidates[:max_files_per_document]
        for idx, file_path in enumerate(file_candidates):
            if not file_path:
                continue
            if "→" in file_path or "->" in file_path or "`" in file_path:
                continue
            score = result_score / file_position_divisor(idx)
            normalized = file_path.replace("\\", "/").lower()
            path_tokens = tokenize(file_path.replace("\\", "/").replace("/", " "))
            path_token_set = set(path_tokens)
            path_hits = sum(1 for token in result_query_tokens if token in path_token_set or token in normalized)
            distinctive_hits = sum(
                1
                for token in set(result_query_tokens)
                if token not in _generic_file_tokens() and (token in path_token_set or token in normalized)
            )
            if path_hits:
                score *= 1.0 + min(path_hits, 8) * 0.22
                score += path_hits * 35.0
            if distinctive_hits:
                score *= 1.0 + min(distinctive_hits, 5) * 0.55
                score += distinctive_hits * 90.0
            if named_files:
                # The query names this exact filename outright (e.g. "admissionPolicy.ts").
                # Mirrors how real-world code-search ranking (e.g. Sourcegraph's BM25F)
                # applies a dedicated boost for filename/symbol matches, separate from
                # generic keyword overlap -- an explicit "this is the file" signal should
                # not have to out-compete dozens of topically-similar files on generic
                # word overlap alone to survive the default max_files window.
                basename = normalized.rsplit("/", 1)[-1]
                if basename in named_files:
                    # Use the ORIGINAL-case basename for match-strength tokenizing --
                    # `basename` above is already lowercased (from `normalized`), which
                    # destroys the camelCase boundaries tokenize() relies on to split
                    # compound filenames (e.g. "NotificationsController.cs" would become
                    # one unsplittable "notificationscontroller" token instead of
                    # "notifications" + "controller", scoring a false near-zero match).
                    original_basename = file_path.replace("\\", "/").rsplit("/", 1)[-1]
                    strength = named_file_match_strength(original_basename, result_query_tokens)
                    score *= 1.0 + 2.0 * strength
                    score += 1500.0 * strength
            if "ownership" in query_intents:
                if any(layer in normalized for layer in (
                    "/entities/", "/dtos/", "/services/", "/controllers/", "/api/", "/components/", "/pages/",
                    "/jobs/",
                )) or any(p in normalized for p in _active_profile().extra_owner_file_patterns()):
                    score *= 1.18
                if result.get("source_type") == "graph chunk":
                    score *= 1.55
            if "implementation_trace" in query_intents:
                score = apply_owner_file_score(
                    score,
                    normalized,
                    file_path,
                    result,
                    result_query_tokens,
                    scoped_modules,
                    scoped_packs,
                    top_specific_packs,
                )
            else:
                if "ownership" in query_intents:
                    score = apply_basic_file_noise_penalty(score, normalized, file_path)
                # Run profile adjust_owner_score for all non-implementation_trace queries so
                # intent-based suppressions fire on business/philosophical queries too.
                # Use query_tokens (the user's full query) not result_query_tokens (per-document
                # tokens) — intent guards must check the query context, not the document context.
                # Safe for any project — NoOpProfile returns score unchanged.
                score = _active_profile().adjust_owner_score(
                    score, normalized, query_tokens, result, top_specific_packs
                )
            score = apply_pack_first_score(score, normalized, result, top_specific_packs)
            scores[file_path] += score
            sources[file_path].add(result["source"])
    # Global domain gate: keep only pins whose module is the query's subject.
    # This neutralizes off-domain intents (permissions/calendar/pos) firing on
    # stray words in long multi-symptom queries, without per-intent guards.
    _dominant_modules = query_dominant_modules(query_tokens)
    _gated_pins = gate_pins_by_domain(pinned_owner_files(query_tokens), _dominant_modules)
    for idx, file_path in enumerate(_gated_pins):
        scores[file_path] += score_pinned_owner_file(file_path, idx, query_tokens)
        sources[file_path].add("deterministic-owner-routing-confidence")
    apply_owner_group_completeness(
        results,
        scores,
        sources,
        scoped_modules,
        top_specific_packs,
        query_tokens,
    )
    ranked = _dedup_file_paths_by_suffix(
        sorted(scores.items(), key=lambda item: item[1], reverse=True)
    )[:max_files]
    return [
        {
            "path": path,
            "score": round(score, 2),
            "source": sorted(sources[path])[:5],
        }
        for path, score in ranked
    ]


# ---- Cross-pack file-score rebalancing (additive, post-processing only) ----
# Mirrors rerank_top_primary_owner_candidates()'s "rescore a small bounded
# window, only override on a clear margin" pattern (see that function's
# docstring for the general rationale). This is the file-ranking equivalent:
# aggregate_files() sums a file's score across every document that lists it
# (`scores[file_path] += score`, no cap) -- which correctly rewards genuine
# cross-pack centrality most of the time, but when a query happens to touch
# two packs that are BOTH topically relevant to it, a file cited by both can
# out-add a file that is the true single decisive answer but is backed by one
# strongly relevant pack plus one only-loosely-relevant one.
#
# Real diagnosed case: a decoy file was listed by two packs that are both
# genuinely relevant to the query's general topic, so it accumulates real
# score from both. The true answer file was ALSO technically listed by two
# packs, so a naive "count how many packs" fix would treat both files
# identically and change nothing -- the real tell is that the true answer's
# second pack was only loosely relevant to this specific query, so it
# contributed far less than the decoy's second pack did. That's why this
# dampens by per-pack PEAK document score (how strongly each pack actually
# backed the file), not by raw pack count.
#
# Deliberately a separate, additive pass -- does not modify aggregate_files()
# or score_document(). Only re-examines a small bounded window of the top
# already-ranked files, and only overrides aggregate_files()'s original order
# when the recomputed, per-pack-decomposed evidence disagrees by a clear
# margin -- never on a close call, so a file that's already winning mostly on
# its own single-pack strength (the common, correct case) is left untouched.
_FILE_RESCORE_WINDOW = 10
_FILE_RESCORE_OVERRIDE_MARGIN = 0.15
# Each additional pack backing the same file counts for less than the one
# before it -- extra corroboration still counts, it just can't compound
# near-linearly the way plain addition does. Floor keeps a 4th+ pack from
# being worthless, matching the "never fully zero out a signal" convention
# already used elsewhere (e.g. identifier_corroboration_strength()'s 0.4 floor).
_FILE_RESCORE_PACK_WEIGHTS = (1.0, 0.35, 0.15)
_FILE_RESCORE_PACK_WEIGHT_FLOOR = 0.08


def _per_pack_peak_scores(file_path: str, results: list[dict[str, Any]]) -> dict[str, float]:
    """For one file, the single strongest per-document score contributed by
    each distinct pack that lists it. Uses the PEAK (not sum) within a pack --
    multiple documents from the SAME pack (graph.json + source-files.txt +
    behavior/retrieval-hints.md all pointing at the same fact) are expected,
    legitimate reinforcement of one real signal and are deliberately NOT
    dampened here; only stacking ACROSS distinct packs is."""
    peaks: dict[str, float] = {}
    normalized_target = file_path.replace("\\", "/").lower()
    for result in results:
        files = result.get("files") or []
        if not any(str(f).replace("\\", "/").lower() == normalized_target for f in files):
            continue
        pack = str(result.get("pack") or "").strip().lower()
        if not pack:
            # Non-Graphify sources (e.g. a plain docs/*.md file) have no pack --
            # keyed separately per source_type so they still count as one
            # independent corroborating source rather than being dropped.
            pack = f"__nopack__:{result.get('source_type', '')}"
        score = float(result.get("score") or 0.0)
        if score > peaks.get(pack, 0.0):
            peaks[pack] = score
    return peaks


def rebalance_cross_pack_file_stacking(
    ranked_files: list[dict[str, Any]],
    results: list[dict[str, Any]],
    window: int = _FILE_RESCORE_WINDOW,
) -> list[dict[str, Any]]:
    """Second-pass, additive rescore of aggregate_files()'s output.

    `ranked_files` is aggregate_files()'s own return value (already sorted).
    `results` is the same per-document result list aggregate_files() was
    called with -- needed here to re-derive per-pack contributions that
    aggregate_files() itself already collapsed into a single summed score.

    Pure post-processing: does not modify aggregate_files() or
    score_document(), and can be unwired from the call site with zero effect
    on either, exactly like rerank_top_primary_owner_candidates().
    """
    if not ranked_files:
        return ranked_files
    candidates = ranked_files[:window]
    rest = ranked_files[window:]
    if len(candidates) < 2:
        return ranked_files

    def _evidence_total(item: dict[str, Any]) -> float:
        peaks = _per_pack_peak_scores(str(item.get("path") or ""), results)
        if not peaks:
            return float(item.get("score") or 0.0)
        ordered_peaks = sorted(peaks.values(), reverse=True)
        total = 0.0
        for idx, peak in enumerate(ordered_peaks):
            weight = (
                _FILE_RESCORE_PACK_WEIGHTS[idx]
                if idx < len(_FILE_RESCORE_PACK_WEIGHTS)
                else _FILE_RESCORE_PACK_WEIGHT_FLOOR
            )
            total += peak * weight
        return total

    evidence_by_id = {id(item): _evidence_total(item) for item in candidates}
    max_evidence = max(evidence_by_id.values(), default=0.0)
    # TEMPORARY diagnostic (additive-only, does not affect ranking or scoring):
    # exposes what this pass actually computed so a live rerun can be used to
    # calibrate _FILE_RESCORE_PACK_WEIGHTS / _FILE_RESCORE_OVERRIDE_MARGIN with
    # real numbers instead of guessing again. Safe to remove once evt_93 is
    # confirmed fixed and the weights are settled.
    for item in candidates:
        item["_rescore_evidence"] = round(evidence_by_id[id(item)], 2)
        item["_rescore_packs"] = len(_per_pack_peak_scores(str(item.get("path") or ""), results))
    if max_evidence <= 0:
        return ranked_files

    original_top = candidates[0]
    original_top_evidence = evidence_by_id[id(original_top)]
    best_item = max(candidates, key=lambda item: evidence_by_id[id(item)])
    best_evidence = evidence_by_id[id(best_item)]

    if best_item is original_top:
        return ranked_files
    # Only override when the challenger clearly outscores the original pick on
    # normalized evidence -- a close call keeps aggregate_files()'s own order,
    # same conservative-margin philosophy as _RERANK_OVERRIDE_MARGIN.
    if (best_evidence - original_top_evidence) / max_evidence < _FILE_RESCORE_OVERRIDE_MARGIN:
        return ranked_files

    reordered = sorted(candidates, key=lambda item: evidence_by_id[id(item)], reverse=True)
    return reordered + rest


def detect_top_specific_packs(results: list[dict[str, Any]], limit: int = 4) -> set[str]:
    pack_scores: dict[str, float] = defaultdict(float)
    for result in results[:80]:
        pack = str(result.get("pack") or "").lower()
        if not pack or pack == "secondary-ownership":
            continue
        source_type = str(result.get("source_type") or "").lower()
        if source_type in {"source-files.txt", "behavior pack", "graph_report.md", "manifest.json", *GRAPH_OWNER_SOURCE_TYPES}:
            pack_scores[pack] += float(result.get("score") or 0.0)
    ranked = sorted(pack_scores.items(), key=lambda item: item[1], reverse=True)
    return {pack for pack, _ in ranked[:limit]}


def secondary_file_limit(result: dict[str, Any]) -> int:
    source_type = str(result.get("source_type") or "").lower()
    if source_type == "graph chunk":
        return 2
    if source_type in GRAPH_OWNER_SOURCE_TYPES:
        return 8
    return 5


def score_pinned_owner_file(file_path: str, index: int, query_tokens: list[str]) -> float:
    """Score deterministic pins so the profile-authored ORDER is preserved.

    The order a profile lists pins for an intent IS its confidence ranking — the
    most-specific root-cause owner is listed first, supporting files after. Each
    pin gets its own 1M-wide band (100M, 99M, 98M …) so a later pin can NEVER
    overtake an earlier one; a small query-name-match nudge only breaks ties
    inside a band.

    Why not score by query/path match instead: that let generic /services/ and
    /controllers/ files with incidental name matches (e.g. a Follow-up *Service*
    matching an injected "notification" token) float above the true owner ENTITY
    (state machine) and UI PAGE (cache layer), which carry smaller path scores.
    Order-dominant scoring keeps deterministic routing deterministic.
    """
    path_tokens = set(tokenize(file_path.replace("\\", "/").replace("/", " ")))
    query_distinctive = {
        token for token in set(query_tokens)
        if token not in _generic_file_tokens()
    } or set(query_tokens)
    matched = sum(1 for token in query_distinctive if token in path_tokens)
    base = 100_000_000.0 - (index * 1_000_000.0)   # strict order bands, 1M apart
    nudge = min(matched, 9) * 50_000.0             # tiebreak only; max 450K << 1M band
    return base + nudge


def apply_pack_first_score(score: float, normalized: str, result: dict[str, Any], top_specific_packs: set[str]) -> float:
    pack = str(result.get("pack") or "").lower()
    source_type = str(result.get("source_type") or "").lower()
    source_level = str((result.get("metadata") or {}).get("source_level", "")).lower()
    if pack in top_specific_packs:
        if source_type == "source-files.txt":
            score *= 3.2
            score += 900.0
        elif source_type in GRAPH_OWNER_SOURCE_TYPES and source_level != "secondary":
            score *= 2.2
            score += 450.0
        elif source_type == "behavior pack":
            score *= 1.35
    elif top_specific_packs and pack == "secondary-ownership" and source_level == "secondary":
        score *= 0.45
    return score


def apply_owner_group_completeness(
    results: list[dict[str, Any]],
    scores: dict[str, float],
    sources: dict[str, set[str]],
    scoped_modules: set[str],
    top_specific_packs: set[str],
    query_tokens: list[str],
) -> None:
    if not scores:
        return
    query_token_set = set(query_tokens)
    candidate_rows = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    anchor_files = [
        path
        for path, _ in candidate_rows
        if is_rankable_owner_file(path)
    ][:6]
    if not anchor_files:
        return
    anchor_set = {path.replace("\\", "/").lower() for path in anchor_files}
    for result in results[:120]:
        pack = str(result.get("pack") or "").lower()
        module = str(result.get("module") or "").lower()
        metadata = dict(result.get("metadata") or {})
        normalized_files = [
            str(item or "").replace("\\", "/").strip()
            for item in result.get("files", []) or []
            if str(item or "").strip()
        ]
        result_source_file = str(metadata.get("source_file") or "").replace("\\", "/").strip()
        is_anchor_context = any(path.lower() in anchor_set for path in normalized_files)
        if result_source_file and result_source_file.lower() in anchor_set:
            is_anchor_context = True
        if not is_anchor_context and pack not in top_specific_packs:
            continue
        companions = collect_owner_companions(metadata)
        for companion in companions:
            normalized = companion.replace("\\", "/").lower()
            if normalized in anchor_set:
                continue
            if not is_rankable_owner_file(companion):
                continue
            bonus = 180.0
            if pack and pack in top_specific_packs:
                bonus += 160.0
            if module and module in scoped_modules:
                bonus += 110.0
            if any(token in normalized for token in query_token_set if token not in _generic_file_tokens()):
                bonus += 120.0
            bonus += owner_path_score(companion) * 1.2
            if result_source_file and result_source_file.lower() in anchor_set:
                bonus += 140.0
            scores[companion] += bonus
            sources[companion].add("owner-group-completeness")


def collect_owner_companions(metadata: dict[str, Any]) -> list[str]:
    companions: list[str] = []
    for value in metadata.get("related_files") or []:
        text = str(value or "").strip()
        if text:
            companions.append(text.replace("\\", "/"))
    for item in metadata.get("dependency_hints") or []:
        if not isinstance(item, dict):
            continue
        for field in ("source_file", "target_file"):
            text = str(item.get(field) or "").strip()
            if text:
                companions.append(text.replace("\\", "/"))
    return dedupe_preserve_order([item for item in companions if item])


def is_rankable_owner_file(path: str) -> bool:
    normalized = str(path or "").replace("\\", "/").lower()
    if not normalized or not re.search(r"\.(cs|tsx|ts|js)$", normalized):
        return False
    return any(marker in normalized for marker in OWNER_PATH_MARKERS)


def pinned_owner_files(query_tokens: list[str]) -> list[str]:
    return _active_profile().pinned_owner_files(list(query_tokens))


def query_dominant_modules(query_tokens: list[str]) -> set[str]:
    """Global domain gate: vote-count the query tokens against each module's
    vocabulary (profile.module_intent_tokens) and return the dominant module(s).

    A long multi-symptom query mentions many modules as downstream effects, but
    only one or two are the real subject. The module whose vocabulary the query
    hits hardest is the subject; the rest are noise. Returning an empty set means
    "no clear signal" and disables the gate (no filtering) so we never over-filter.
    """
    try:
        module_vocab = _active_profile().module_intent_tokens()
    except Exception:
        return set()
    if not module_vocab:
        return set()
    token_set = set(query_tokens)
    votes = {module: len(token_set & vocab) for module, vocab in module_vocab.items()}
    top = max(votes.values(), default=0)
    if top <= 0:
        return set()  # no module signal -> gate disabled
    # Dominant = clearly ahead of the pack. Floor of 2 avoids gating on a single
    # stray token; the 0.45 ratio keeps genuine secondary modules in a real
    # cross-module bridge query while dropping incidental one-word mentions.
    # For runtime/debug queries the symptom tokens (e.g. "permission", "config")
    # scatter across many unrelated modules; raise the ratio to 0.75 so only the
    # module with the strongest hit count qualifies as dominant.
    ratio = 0.75 if token_set.intersection(RUNTIME_TOKENS) else 0.45
    threshold = max(2.0, top * ratio)
    return {module for module, count in votes.items() if count >= threshold}


def gate_pins_by_domain(pins: list[str], dominant: set[str]) -> list[str]:
    """Drop pinned files whose module is KNOWN and not in the dominant set.

    Files whose module cannot be inferred (None) are always kept — the gate only
    removes files it can prove belong to an unrelated module. This is the single
    mechanism that replaces per-intent cross-module exclusion guards.
    """
    if not dominant:
        return pins  # gate disabled
    profile = _active_profile()
    kept: list[str] = []
    for path in pins:
        try:
            module = profile.infer_module_from_path(path)
        except Exception:
            module = None
        if module is None or module in dominant:
            kept.append(path)
    return kept


def dedupe_preserve_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        key = value.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(value)
    return out


def _dedup_file_paths_by_suffix(ranked: list[tuple[str, float]]) -> list[tuple[str, float]]:
    """Drop path variants that refer to the same physical file as a higher-scored entry.

    The indexer stores the same file under multiple relative roots
    (e.g. "main_service/POS/Services/CartService.cs", "POS/Services/CartService.cs",
    "Services/CartService.cs"). These produce different score-dict keys so exact-match
    dedup misses them. Suffix dedup: if a new path is a strict path-suffix of an
    already-kept path (or vice-versa) they are the same physical file — the first
    (highest-scored) occurrence wins. Mirrors dedupe_ranked_keys() in hybrid_search.py.
    """
    kept_norms: list[str] = []
    output: list[tuple[str, float]] = []
    for path, score in ranked:
        norm = path.replace("\\", "/").lower()
        duplicate = False
        for kept in kept_norms:
            if kept.endswith("/" + norm) or norm.endswith("/" + kept) or kept == norm:
                duplicate = True
                break
        if duplicate:
            continue
        kept_norms.append(norm)
        output.append((path, score))
    return output


def apply_basic_file_noise_penalty(score: float, normalized: str, file_path: str) -> float:
    if "→" in file_path or "->" in file_path or "`" in file_path:
        score *= 0.42
    if not re.search(r"\.(cs|tsx|ts|js|json|sql|md|yaml|yml)$", normalized):
        score *= 0.65
    return score


def apply_owner_file_score(
    score: float,
    normalized: str,
    file_path: str,
    result: dict[str, Any],
    query_tokens: list[str],
    scoped_modules: set[str],
    scoped_packs: set[str],
    top_specific_packs: set[str],
) -> float:
    is_real_source = bool(re.search(r"\.(cs|tsx|ts|js)$", normalized))
    is_owner_path = any(marker in normalized for marker in OWNER_PATH_MARKERS)
    _all_owner_patterns = OWNER_FILE_PATTERNS + _active_profile().extra_owner_file_patterns()
    is_owner_file = any(pattern in normalized for pattern in _all_owner_patterns)
    is_broad = any(pattern in normalized for pattern in BROAD_FILE_PATTERNS)
    is_relationship = "→" in file_path or "->" in file_path or "`" in file_path
    source_type = str(result.get("source_type", "")).lower()
    source_level = str((result.get("metadata") or {}).get("source_level", "")).lower()

    if is_real_source:
        score *= 1.35
        score += 120.0
    if is_owner_path:
        score *= 1.75
        score += 220.0
    if is_owner_file:
        score *= 1.45
        score += 120.0
    if source_type in {"source-files.txt", "graph chunk", *GRAPH_OWNER_SOURCE_TYPES}:
        score *= 1.35
    if source_level == "secondary":
        score *= 1.45

    file_tokens = set(tokenize(file_path.replace("\\", "/").replace("/", " ")))
    distinctive_hits = [
        token for token in set(query_tokens)
        if token not in _generic_file_tokens() and (token in file_tokens or token in normalized)
    ]
    query_distinctive = {token for token in set(query_tokens) if token not in _generic_file_tokens()}
    class_name = normalized.rsplit("/", 1)[-1].rsplit(".", 1)[0]
    class_tokens = set(tokenize(class_name))
    class_hits = query_distinctive.intersection(class_tokens)
    if distinctive_hits:
        score *= 1.0 + min(len(distinctive_hits), 5) * 0.75
        score += len(distinctive_hits) * 140.0
    if class_hits:
        score *= 1.0 + min(len(class_hits), 6) * 0.9
        score += len(class_hits) * 220.0
    if "controller" in query_tokens and normalized.endswith("controller.cs"):
        score *= 1.6
        score += 180.0
    if "service" in query_tokens and normalized.endswith("service.cs"):
        score *= 1.45
        score += 140.0
    if ("job" in query_tokens or "scheduler" in query_tokens) and normalized.endswith("job.cs"):
        score *= 1.8
        score += 220.0

    score = _active_profile().adjust_owner_score(
        score, normalized, query_tokens, result, top_specific_packs
    )
    # Stage-2 scoping: once broad docs identify a module/pack, prefer files under
    # that source area. Module/pack-specific multipliers live in the active profile.
    score = _active_profile().adjust_scoped_score(score, normalized, scoped_modules, scoped_packs)

    if is_relationship:
        score *= 0.22
    if is_broad:
        score *= 0.18
    if not is_real_source:
        score *= 0.45
    return score


def aggregate_named(results: list[dict[str, Any]], key: str, limit: int = 8) -> list[dict[str, Any]]:
    scores: dict[str, float] = defaultdict(float)
    source_types: dict[str, Counter[str]] = defaultdict(Counter)
    for result in results:
        value = result.get(key)
        if not value:
            continue
        scores[value] += float(result["score"])
        source_types[value][result.get("source_type", "unknown")] += 1
    ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)[:limit]
    return [
        {
            "name": name,
            "score": round(score, 2),
            "source_types": dict(source_types[name].most_common()),
        }
        for name, score in ranked
    ]


def _symbol_query_relevance(label: str, query_distinctive: set[str]) -> int:
    """Count distinctive query tokens present in a (camelCase-split) symbol label.

    Used to choose the most query-relevant symbols per file BEFORE the per-file
    cap is applied, so a root-cause method deep in a large file (e.g.
    SignAndSaveTreatmentOrderRowAsync at line 8000+) is not dropped just because
    generic getters are declared earlier.
    """
    if not query_distinctive:
        return 0
    label_tokens = set(tokenize(label))
    return sum(1 for token in query_distinctive if token in label_tokens)


def _normalize_symbol_label(label: str) -> str:
    """Strip the method-call wrapper (".Foo()" -> "foo") so a symbol label can
    be compared directly against a bare query identifier like "Foo"."""
    normalized = label.strip()
    if normalized.startswith("."):
        normalized = normalized[1:]
    if normalized.endswith("()"):
        normalized = normalized[:-2]
    return normalized.lower()


# Widened per-file candidate cap used ONLY when a STRICT identifier (real
# CamelCase/PascalCase hump, snake_case, digit, or long compound -- see
# strict_camel_identifiers()) confirms a file is genuinely relevant. Deliberately
# modest (not the unbounded/40-cap version tried and reverted earlier) and never
# bypasses this function's own overall `limit` truncation below -- it only lets
# a confirmed file's OTHER (unnamed sibling) symbols compete for a slot instead
# of being cut off at the default per_path_limit.
_CONFIRMED_FILE_SYMBOL_CAP = 16


def extract_symbol_hits(
    results: list[dict[str, Any]],
    limit: int = 20,
    preferred_paths: set[str] | None = None,
    per_path_limit: int = 4,
    query_tokens: list[str] | None = None,
    query_identifiers: list[str] | None = None,
    strict_identifiers: list[str] | None = None,
) -> list[dict[str, Any]]:
    # Collect ALL candidate symbols per path first, then keep the per_path_limit
    # that are most RELEVANT to the query — not the first N in declaration order.
    # Index stores up to max_symbol_hints_per_doc symbols in source order; a huge
    # file's root-cause methods sit far down that list, so a positional cap drops
    # them before the relevance sort can ever see them.
    #
    # query_identifiers (exact method/class names named in the query) guarantee a
    # slot for a matching symbol regardless of per_path_limit -- retrieval recall
    # is bounded by whatever survives this stage, and a later re-ranker (e.g.
    # score_primary_owner_candidate()'s exact-identifier bonus) can never recover
    # a candidate this cap already discarded. _symbol_query_relevance() below only
    # counts generic token overlap and has no awareness of an exact identifier
    # match, so without this, a query naming an exact method by name could still
    # lose that method here before the exact-match bonus ever gets a chance to
    # apply it. This only ever ADDS a candidate back in, never removes or
    # reorders the existing top-N selection.
    #
    # A whole-file-widening version of this (confirming an entire file's cap
    # once ANY candidate matched) was tried and reverted once already -- it
    # regressed a previously-working query. Root cause: query_identifier_tokens()
    # treats any capitalized word as a candidate "identifier" (not just real
    # camelCase/PascalCase code names), so plain prose words like "Overview" or
    # "Symptom" incorrectly confirmed many unrelated files at once, flooding the
    # result with noise. Fixed this time by gating the widening on
    # strict_identifiers (strict_camel_identifiers()) instead of the loose
    # query_identifiers -- see below. query_identifiers itself keeps doing the
    # narrow single-candidate guarantee it always did, unchanged.
    identifiers_lower = {i.lower() for i in (query_identifiers or []) if i}
    strict_lower = {i.lower() for i in (strict_identifiers or []) if i}
    # len >= 3 filters out 1-2 char stop words (is, to, of ...) that appear
    # as trivial substrings of almost any label (e.g. "to" in "lastAu**to**..."),
    # producing false label_token_match credits unrelated to real query overlap.
    query_distinctive = {
        token for token in set(query_tokens or [])
        if token not in _generic_file_tokens() and len(token) >= 3
    }
    candidates_by_path: dict[str, list[dict[str, Any]]] = defaultdict(list)
    seen: set[tuple[str, str, int | None]] = set()
    for result in results:
        metadata = dict(result.get("metadata") or {})
        for symbol in metadata.get("symbol_hints") or []:
            if not isinstance(symbol, dict):
                continue
            label = str(symbol.get("label") or "")
            kind = str(symbol.get("kind") or "")
            if is_low_value_symbol(label, kind):
                continue
            source_file = str(symbol.get("source_file") or "")
            line = symbol.get("line")
            if preferred_paths and source_file.lower() not in preferred_paths:
                continue
            key = (label.lower(), source_file.lower(), line if isinstance(line, int) else None)
            if not source_file or key in seen:
                continue
            seen.add(key)
            candidates_by_path[source_file.lower()].append(
                {
                    "label": label,
                    "kind": kind,
                    "path": source_file,
                    "line": line,
                    "source_location": str(symbol.get("source_location") or ""),
                    "module": result.get("module"),
                    "pack": result.get("pack"),
                    "source": result.get("source"),
                    "source_type": result.get("source_type"),
                    "score": result.get("score"),
                }
            )
    hits: list[dict[str, Any]] = []
    for cands in candidates_by_path.values():
        if query_distinctive and len(cands) > per_path_limit:
            # Stable sort: query-relevant symbols first, ties keep source order.
            cands.sort(key=lambda h: -_symbol_query_relevance(str(h.get("label") or ""), query_distinctive))
        # Widen this file's cap only when one of its OWN candidates exactly
        # matches a strict identifier -- real confirmation the query is naming
        # something that actually lives in this file, not a coincidental prose
        # word. This lets the file's other, unnamed sibling symbols compete for
        # a slot instead of being cut off at the default per_path_limit. Still
        # bounded by _CONFIRMED_FILE_SYMBOL_CAP and still subject to this
        # function's overall `limit` truncation further below -- unlike the
        # reverted attempt, this never bypasses either bound.
        effective_cap = per_path_limit
        if strict_lower and any(
            _normalize_symbol_label(str(c.get("label") or "")) in strict_lower for c in cands
        ):
            effective_cap = max(effective_cap, _CONFIRMED_FILE_SYMBOL_CAP)
        kept = cands[: max(1, effective_cap)]
        if identifiers_lower and len(cands) > len(kept):
            kept_keys = {(str(h.get("label") or "").lower(), h.get("line")) for h in kept}
            for cand in cands[len(kept):]:
                if _normalize_symbol_label(str(cand.get("label") or "")) not in identifiers_lower:
                    continue
                cand_key = (str(cand.get("label") or "").lower(), cand.get("line"))
                if cand_key in kept_keys:
                    continue
                kept.append(cand)
                kept_keys.add(cand_key)
        hits.extend(kept)
    hits.sort(
        key=lambda item: (
            SYMBOL_KIND_PRIORITY.get(str(item.get("kind") or ""), 9),
            -float(item.get("score") or 0.0),
            str(item.get("path") or ""),
            int(item.get("line") or 0),
        )
    )
    return hits[:limit]


def extract_location_hints(symbol_hits: list[dict[str, Any]], limit: int = 12) -> list[dict[str, Any]]:
    locations: list[dict[str, Any]] = []
    seen: set[tuple[str, int | None]] = set()
    for hit in symbol_hits:
        path = str(hit.get("path") or "")
        line = hit.get("line")
        key = (path.lower(), line if isinstance(line, int) else None)
        if not path or key in seen:
            continue
        seen.add(key)
        locations.append(
            {
                "path": path,
                "line": line,
                "graph_line": hit.get("graph_line"),
                "verified_line": hit.get("verified_line"),
                "line_status": hit.get("line_status"),
                "line_delta": hit.get("line_delta"),
                "symbol": hit.get("label"),
                "kind": hit.get("kind"),
                "source_location": hit.get("source_location"),
                "code_block": hit.get("code_block"),
            }
        )
        if len(locations) >= limit:
            break
    return locations


def owner_path_score(path: str) -> float:
    normalized = str(path or "").replace("\\", "/").lower()
    if "/controllers/" in normalized:
        return 180.0
    if "/services/" in normalized:
        return 170.0
    if "/jobs/" in normalized:
        return 165.0
    if normalized.endswith(".tsx"):
        return 155.0
    if normalized.endswith(".ts"):
        return 125.0
    if "/dtos/" in normalized:
        return 90.0
    if "/entities/" in normalized:
        return 80.0
    return 40.0


def identifier_corroboration_strength(
    identifier: str, query_tokens: list[str], all_identifiers: list[str]
) -> float:
    """How much of a named identifier's own distinctive words are corroborated
    by the query's language OUTSIDE of the identifier list itself, as a 0..1
    fraction.

    A query can name several same-family candidates at once (e.g. listing a
    real target alongside a similarly-spelled decoy as "keywords", with no cue
    for which one is the actual subject). The flat exact-identifier bonus in
    score_primary_owner_candidate() otherwise rewards every named candidate
    equally, even one whose only word overlap with the query is the fact that
    its own name got typed into the query text. This checks, per distinctive
    word in the identifier, whether that word's TOTAL occurrence count in the
    query exceeds how many times it appears merely embedded inside the full
    set of named identifiers -- i.e. whether the query's own descriptive
    language (not just the identifier list) independently uses that word. A
    word that only shows up because it's baked into one candidate's own name
    does not count as corroboration.

    Floored at 0.4 so a named identifier never loses its bonus entirely --
    only the DEGREE of the boost changes.

    Word-form canonicalization (_canon below): tokenize()'s pluralization
    handling is a crude "strip trailing s", which produces a WRONG stem for
    "-ies" words (e.g. "parties" -> "partie", not the real singular "party").
    Real diagnosed case: a query names "PartiesController.cs" but only ever
    uses the plain word "party" (singular) elsewhere in its own descriptive
    text -- never "parties" or "partie" as literal substrings. Without
    canonicalization, ident_words for "PartiesController" ends up as
    {"parties", "partie"}, NEITHER of which ever matches the query's "party"
    mentions, so corroboration always floors at 0.4 even though the query
    clearly is about parties/party. Tried first without canonicalization (just
    adding "party" as a third separate word alongside the existing two): that
    made no difference at all, because it only grew the denominator (now 3
    words) without the extra corroborated word being enough to lift the
    fraction above the 0.4 floor. Canonicalizing instead COLLAPSES all three
    spellings ("parties", "partie", "party") into one comparison bucket, so
    corroboration is measured once per real-world word instead of once per
    spelling variant of that word. Verified directly: this took the party
    query's fraction from 0/2=0.0 (floored to 0.4) to 1/1=1.0, without
    changing the outcome of two other already-fixed real queries used as
    regression checks.
    """
    def _canon(word: str) -> str:
        if len(word) > 4 and word.endswith("ies"):
            return word[:-3] + "y"
        if len(word) > 3 and word.endswith("ie"):
            return word[:-2] + "y"
        if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
            return word[:-1]
        return word

    ident_words = {_canon(token) for token in tokenize(identifier) if token not in _generic_file_tokens()}
    if not ident_words:
        return 1.0
    identifier_word_counts: Counter[str] = Counter()
    for other in all_identifiers:
        identifier_word_counts.update(
            _canon(token) for token in tokenize(other) if token not in _generic_file_tokens()
        )
    query_word_counts: Counter[str] = Counter(_canon(token) for token in query_tokens)
    corroborated = sum(
        1 for word in ident_words
        if query_word_counts.get(word, 0) > identifier_word_counts.get(word, 0)
    )
    fraction = corroborated / len(ident_words)
    return max(0.4, fraction)


def score_primary_owner_candidate(
    hit: dict[str, Any],
    ranked_file_order: dict[str, int],
    query_tokens: list[str],
    preferred_paths: set[str],
    query_identifiers: list[str] | None = None,
) -> float:
    path = str(hit.get("path") or "")
    normalized = path.replace("\\", "/").lower()
    label = str(hit.get("label") or "")
    kind = str(hit.get("kind") or "")
    score = SYMBOL_PRIMARY_OWNER_WEIGHT.get(kind, 100.0)
    file_rank = ranked_file_order.get(normalized, 10_000)
    score += max(0.0, 1100.0 - min(file_rank, 50) * 85.0)
    score += owner_path_score(path)
    if normalized in preferred_paths:
        score += 220.0
    if file_rank > 5 and normalized not in preferred_paths:
        score -= min(400.0, (file_rank - 5) * 55.0)
    line_status = str(hit.get("line_status") or "")
    if line_status == "exact":
        score += 120.0
    elif line_status == "adjusted":
        score += 60.0
    label_lower = label.lower()
    anchor_labels = expected_anchor_labels_for_path(path)
    if kind in {"controller_class", "service_class", "job_class"} and label.replace("()", "").lower() in anchor_labels:
        score += 820.0
    path_tokens = set(tokenize(path.replace("\\", "/").replace("/", " ")))
    query_distinctive = {token for token in set(query_tokens) if token not in _generic_file_tokens()}
    label_tokens = set(tokenize(label))
    identifier_hits = sum(
        1 for token in query_distinctive
        if not _is_excluded_owner_token(token)
        and (token in label_tokens or token in path_tokens or token in label_lower or token in normalized)
    )
    score += identifier_hits * 90.0
    for token in query_distinctive:
        if _is_excluded_owner_token(token):
            continue
        if token in normalized:
            score += 160.0
    for identifier in query_identifiers or []:
        if _is_excluded_owner_token(identifier):
            continue
        lowered = identifier.lower()
        if lowered in normalized or lowered in label_lower:
            strength = identifier_corroboration_strength(identifier, query_tokens, query_identifiers or [])
            if lowered in normalized:
                score += 900.0 * strength
            else:
                score += 650.0 * strength
    if kind in {"controller_action", "service_method", "job_method", "ui_component"} and identifier_hits:
        score += 180.0
    if "/helpers/" in normalized or normalized.endswith("helper.cs") or "statushelper" in normalized:
        if not {"helper", "helpers", "status", "statuses", "cancel", "cancelled", "terminal", "active"}.intersection(query_distinctive):
            score -= 720.0
    if kind == "service_method" and label_lower.startswith(".is"):
        if not {"status", "cancel", "cancelled", "terminal", "active"}.intersection(query_distinctive):
            score -= 520.0
    if "service" in query_distinctive and "/services/" in normalized:
        score += 260.0
    if "controller" in query_distinctive and "/controllers/" in normalized:
        score += 260.0
    score = _active_profile().adjust_primary_owner_score(score, normalized, query_distinctive)
    return score


def select_primary_owner(
    symbol_hits: list[dict[str, Any]],
    ranked_file_order: dict[str, int],
    query_tokens: list[str],
    preferred_paths: set[str],
    query_identifiers: list[str] | None = None,
) -> dict[str, Any] | None:
    if not symbol_hits:
        return None
    ranked = sorted(
        symbol_hits,
        key=lambda item: (
            -score_primary_owner_candidate(item, ranked_file_order, query_tokens, preferred_paths, query_identifiers),
            int(item.get("line") or 0),
        ),
    )
    return ranked[0] if ranked else None


# ---- Second-pass primary-owner rerank (additive, post-processing only) ----
# Mirrors Elasticsearch/OpenSearch's "rescore" pattern: a secondary scoring
# pass that only re-examines a small bounded window of the top candidates an
# earlier stage already produced, combined via normalized (0-1) signals and
# fixed weights instead of raw unbounded addition. Does NOT modify
# score_primary_owner_candidate() or select_primary_owner() -- this is a pure,
# separate post-processing step that runs after them and can be removed
# without touching either. See rerank_top_primary_owner_candidates() docstring
# for the full rationale.

# Bounded window of top candidates re-examined -- never the whole symbol_hits
# pool, matching Elasticsearch/OpenSearch rescore's window_size concept.
#
# Widened from 5 to 10 after a real diagnosed case (a negation query -- see
# tests/debug_query2_rerank_window.py): a file whose PATH text happened to
# overlap several distinctive query words (e.g. multiple query words all
# literally appearing in one folder/file's path) received an uncapped,
# per-token path bonus in score_primary_owner_candidate()
# that pushed all 5 of ITS generic symbols above the real answer's rank in the
# raw sorted pool, even though the real answer's own kind weight is higher
# (service_method 1050 vs ui_function 900). At window=5 the reranker never
# even saw the real answer (it was ranked 7th) to compare it. Still bounded --
# not unbounded -- consistent with Elasticsearch/OpenSearch rescore's
# window_size being a deliberately small multiple of the final result count,
# not the whole candidate pool.
_RERANK_WINDOW = 10

# How much better (on the normalized 0-1 scale) the runner-up must score to
# override the original pick. Deliberately conservative: a close call keeps
# the original pick, only a clear disagreement swaps it -- this is what stops
# the reranker from flipping a case that was already correct on a coin-flip
# margin.
_RERANK_OVERRIDE_MARGIN = 0.08

# Fixed importance weights for the normalized signals below. These intentionally
# do NOT mirror score_primary_owner_candidate()'s raw point values -- the whole
# point of this pass is that no single signal's raw ceiling (e.g. file-rank's
# 1100) can dominate purely because its number happens to be large. Sums to 1.0.
#
# file_rank is intentionally ABSENT from this reranker even though
# score_primary_owner_candidate() uses it heavily. Reason: the fusion file
# ranking that would supply this signal is itself biased by path-bonus
# inflation -- a file whose path happens to contain query-distinctive tokens
# gets a large path bonus (+160 per token) in the first-pass scorer, so it
# ranks high in the fusion and then also scores high on file_rank_signal here.
# That is a circular bias: the reranker would simply amplify the same mistake
# the first pass already made, not correct it. Removing file_rank forces the
# reranker to rely purely on LABEL-grounded and semantically-stable signals
# (identifier identity, symbol kind, and per-label token overlap), which are
# immune to the coincidental path-token coincidence that caused the bug.
#
# token_overlap is split into label_token_match (0.15) and path_token_match
# (0.07). A query token appearing in the LABEL of a symbol directly says "this
# symbol's NAME matches the query", which is much more meaningful than the same
# token appearing only in its file-path (which may be a pure path coincidence).
# The split lets a symbol with two label-matching tokens reliably out-score one
# that got its overlap purely from a coincidentally-named ancestor directory.
_RERANK_SIGNAL_WEIGHTS = {
    "identifier_match": 0.40,
    "kind": 0.40,
    "label_token_match": 0.15,
    "path_token_match": 0.05,
}


def _normalized_rerank_signals(
    hit: dict[str, Any],
    ranked_file_order: dict[str, int],
    query_tokens: list[str],
    query_identifiers: list[str] | None,
) -> dict[str, float]:
    """Express score_primary_owner_candidate()'s core signals as 0-1 fractions
    of their own realistic maximum, instead of raw unbounded points. Used only
    by rerank_top_primary_owner_candidates() -- does not change or replace
    score_primary_owner_candidate() itself."""
    path = str(hit.get("path") or "")
    normalized_path = path.replace("\\", "/").lower()
    label = str(hit.get("label") or "")
    kind = str(hit.get("kind") or "")

    kind_weight = SYMBOL_PRIMARY_OWNER_WEIGHT.get(kind, 100.0)
    max_kind_weight = max(SYMBOL_PRIMARY_OWNER_WEIGHT.values()) or 1.0
    kind_signal = kind_weight / max_kind_weight

    # file_rank deliberately not computed here -- see _RERANK_SIGNAL_WEIGHTS
    # comment for why the fusion file rank is excluded from the reranker.

    # len >= 3 filters out 1-2 char stop words ("is", "to", "of" ...) that appear
    # as trivial substrings of almost any label (e.g. "to" inside "lastAu**to**..."),
    # producing false label_token_match credits unrelated to real query overlap.
    query_distinctive = {
        token for token in set(query_tokens or [])
        if token not in _generic_file_tokens() and len(token) >= 3
    }
    label_tokens = set(tokenize(label))
    path_tokens = set(tokenize(normalized_path))
    label_lower = label.lower()

    # label_token_match: tokens from the query that appear IN THE LABEL itself
    # (whole-word match via tokenize() OR raw substring in the lowercase label).
    # A label match directly says "this symbol's own name contains the query
    # term", which is semantically much stronger than the same token appearing
    # only in the surrounding file path.
    label_overlap = sum(
        1 for token in query_distinctive
        if token in label_tokens or token in label_lower
    )
    label_token_match = min(1.0, label_overlap / 3.0) if query_distinctive else 0.0

    # path_token_match: tokens that hit only the FILE PATH, not the label.
    # This still gives some credit for file-context relevance (e.g. a service
    # sitting under a matching folder name) but at a much lower weight (0.07
    # vs 0.15 for label), so a file whose path coincidentally contains query
    # tokens (the path-bonus problem seen in the widened-rerank-window case
    # above) cannot dominate.
    path_overlap = sum(
        1 for token in query_distinctive
        if (token in path_tokens or token in normalized_path)
        and token not in label_tokens and token not in label_lower
    )
    path_token_match = min(1.0, path_overlap / 3.0) if query_distinctive else 0.0

    identifier_signal = 0.0
    for identifier in query_identifiers or []:
        lowered = identifier.lower()
        if lowered and (lowered in normalized_path or lowered in label.lower()):
            identifier_signal = 1.0
            break

    return {
        "identifier_match": identifier_signal,
        "kind": kind_signal,
        "label_token_match": label_token_match,
        "path_token_match": path_token_match,
    }


def _rerank_score(signals: dict[str, float]) -> float:
    return sum(_RERANK_SIGNAL_WEIGHTS[name] * value for name, value in signals.items())


def rerank_top_primary_owner_candidates(
    symbol_hits: list[dict[str, Any]],
    original_pick: dict[str, Any] | None,
    ranked_file_order: dict[str, int],
    query_tokens: list[str],
    query_identifiers: list[str] | None = None,
    window: int = _RERANK_WINDOW,
) -> dict[str, Any] | None:
    """Second-pass, additive rerank of select_primary_owner()'s output.

    Re-examines only a small bounded window of the top candidates that
    select_primary_owner() already sorted to the front (symbol_hits must
    already be sorted by score_primary_owner_candidate(), as it is at every
    current call site) -- never the whole symbol_hits pool. Only overrides the
    original pick when a normalized (0-1), weighted comparison disagrees with
    it by a clear margin (_RERANK_OVERRIDE_MARGIN), not on a marginal
    difference.

    `query_identifiers` should be STRICT identifiers (strict_camel_identifiers()),
    not the loose query_identifier_tokens()/primary_owner_query_identifiers()
    lists used elsewhere. Real diagnosed case: a loose identifier like bare
    "HMS" matches almost every candidate's path in an HMS-domain codebase
    (nearly every file lives under an hms/ folder), so it contributes a
    near-universal, non-discriminating 1.0 identifier_match signal to both
    sides of a comparison -- neutering this signal's 0.35 weight for exactly
    the queries where a real discriminator matters most. Strict identifiers
    only match when the query names something genuinely specific.

    Why this can help: score_primary_owner_candidate() combines many signals
    as raw, unbounded points (file-rank alone can contribute up to 1100), so a
    candidate can win purely because one signal's raw ceiling is large, not
    because it's actually the better answer. Normalizing each signal to 0-1
    before combining prevents any single signal from silently dominating --
    validated against Elasticsearch/OpenSearch's rescore pattern and general
    learning-to-rank feature-normalization practice.

    This is a pure post-processing step: it does not modify
    score_primary_owner_candidate() or select_primary_owner(), and can be
    unwired from the call site with zero effect on either.
    """
    if not original_pick or not symbol_hits:
        return original_pick

    candidates = symbol_hits[:window]
    if not candidates:
        return original_pick

    def candidate_key(hit: dict[str, Any]) -> tuple[str, Any, Any]:
        return (str(hit.get("label") or "").lower(), hit.get("path"), hit.get("line"))

    original_key = candidate_key(original_pick)

    scored = [
        (hit, _rerank_score(_normalized_rerank_signals(hit, ranked_file_order, query_tokens, query_identifiers)))
        for hit in candidates
    ]

    original_score = next((score for hit, score in scored if candidate_key(hit) == original_key), None)
    if original_score is None:
        # Original pick fell outside the window (shouldn't normally happen
        # since select_primary_owner() already sorted it to #1) -- score it
        # directly so the comparison is always apples-to-apples.
        original_score = _rerank_score(
            _normalized_rerank_signals(original_pick, ranked_file_order, query_tokens, query_identifiers)
        )

    best_hit, best_score = max(scored, key=lambda item: item[1])
    if candidate_key(best_hit) == original_key:
        return original_pick
    if best_score - original_score >= _RERANK_OVERRIDE_MARGIN:
        return best_hit
    return original_pick


def score_dependency_entry(
    entry: dict[str, Any],
    query_tokens: list[str],
    ranked_file_order: dict[str, int],
    preferred_paths: set[str],
) -> float:
    source_file = str(entry.get("source_file") or "")
    target_file = str(entry.get("target_file") or "")
    relation = str(entry.get("relation") or "").lower()
    source_norm = source_file.replace("\\", "/").lower()
    target_norm = target_file.replace("\\", "/").lower()
    source_rank = ranked_file_order.get(source_norm, 10_000)
    target_rank = ranked_file_order.get(target_norm, 10_000)
    score = DEPENDENCY_RELATION_WEIGHT.get(relation, 250.0)
    score += max(0.0, 450.0 - min(source_rank, 30) * 25.0)
    score += max(0.0, 420.0 - min(target_rank, 30) * 22.0)
    score += owner_path_score(source_file) * 0.7
    score += owner_path_score(target_file) * 0.65
    if source_norm in preferred_paths:
        score += 180.0
    if target_norm in preferred_paths:
        score += 180.0
    if source_norm and target_norm and source_norm == target_norm:
        score -= 420.0
    text = " ".join(
        [
            source_file,
            target_file,
            str(entry.get("source_label") or ""),
            str(entry.get("target_label") or ""),
            relation,
        ]
    ).lower()
    score += sum(50.0 for token in set(query_tokens) if token not in _generic_file_tokens() and token in text)
    return score


def extract_dependency_chain(
    results: list[dict[str, Any]],
    limit: int = 12,
    preferred_paths: set[str] | None = None,
    ranked_file_order: dict[str, int] | None = None,
    query_tokens: list[str] | None = None,
) -> list[dict[str, Any]]:
    chain: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, str]] = set()
    ranked_file_order = ranked_file_order or {}
    query_tokens = query_tokens or []
    preferred_paths = preferred_paths or set()
    for result in results:
        metadata = dict(result.get("metadata") or {})
        for dependency in metadata.get("dependency_hints") or []:
            if not isinstance(dependency, dict):
                continue
            key = (
                str(dependency.get("source_label") or "").lower(),
                str(dependency.get("relation") or "").lower(),
                str(dependency.get("target_label") or "").lower(),
                str(dependency.get("source_file") or "").lower(),
            )
            if key in seen:
                continue
            source_file = str(dependency.get("source_file") or "")
            target_file = str(dependency.get("target_file") or "")
            if preferred_paths and source_file.lower() not in preferred_paths and target_file.lower() not in preferred_paths:
                continue
            seen.add(key)
            entry = {
                "relation": str(dependency.get("relation") or ""),
                "source_label": str(dependency.get("source_label") or ""),
                "source_file": source_file,
                "source_line": dependency.get("source_line"),
                "target_label": str(dependency.get("target_label") or ""),
                "target_file": target_file,
                "target_line": dependency.get("target_line"),
                "module": result.get("module"),
                "pack": result.get("pack"),
                "source": result.get("source"),
                "source_type": result.get("source_type"),
                "score": result.get("score"),
            }
            entry["_rank_score"] = score_dependency_entry(entry, query_tokens, ranked_file_order, preferred_paths)
            chain.append(entry)
    chain.sort(key=lambda item: (-float(item.get("_rank_score") or 0.0), -float(item.get("score") or 0.0)))
    return [{key: value for key, value in item.items() if key != "_rank_score"} for item in chain[:limit]]


def extract_related_files(
    results: list[dict[str, Any]],
    limit: int = 20,
    preferred_paths: set[str] | None = None,
    ranked_file_order: dict[str, int] | None = None,
    query_tokens: list[str] | None = None,
    ranked_files: list[dict[str, Any]] | None = None,
) -> list[str]:
    ranked_file_order = ranked_file_order or {}
    query_tokens = query_tokens or []
    preferred_paths = preferred_paths or set()
    related_scores: dict[str, float] = defaultdict(float)
    seen_pairs: set[tuple[str, str]] = set()

    def add_related(path_value: str, base_score: float, result_path: str, anchor_path: str | None = None) -> None:
        normalized = str(path_value or "").strip()
        if not normalized:
            return
        key = normalized.lower()
        # Allow this candidate in if it is itself already an independently-ranked file,
        # OR it is directly connected (via this same hint) to a file that IS already
        # ranked -- e.g. a dependency edge's other endpoint, or the ranked document that
        # listed it as a related file. Requiring every expanded candidate to
        # independently re-qualify defeats the point of graph expansion (surfacing files
        # a keyword/vector search alone would miss); real multi-hop retrieval practice
        # propagates relevance from an already-confirmed-relevant anchor to what it
        # connects to, rather than re-scoring each candidate from scratch. Mirrors the
        # source-or-target logic extract_dependency_chain() already uses safely.
        anchor = str(anchor_path if anchor_path is not None else result_path or "").strip().lower()
        if preferred_paths and key not in preferred_paths and anchor not in preferred_paths:
            return
        seen_key = (result_path.lower(), key)
        if seen_key in seen_pairs:
            return
        seen_pairs.add(seen_key)
        score = base_score
        score += max(0.0, 300.0 - min(ranked_file_order.get(key, 10_000), 40) * 15.0)
        score += owner_path_score(normalized) * 0.6
        if key in preferred_paths:
            score += 120.0
        lower_text = normalized.lower()
        score += sum(35.0 for token in set(query_tokens) if token not in _generic_file_tokens() and token in lower_text)
        related_scores[normalized] += score

    for result in results:
        metadata = dict(result.get("metadata") or {})
        result_path = str(result.get("path") or "")
        for path in metadata.get("related_files") or []:
            add_related(str(path or ""), 260.0, result_path)
        for path in result.get("files") or []:
            add_related(str(path or ""), 340.0, result_path)
        source_file = str(metadata.get("source_file") or "")
        if source_file:
            add_related(source_file, 280.0, result_path)
        for dependency in metadata.get("dependency_hints") or []:
            if not isinstance(dependency, dict):
                continue
            dep_source = str(dependency.get("source_file") or "")
            dep_target = str(dependency.get("target_file") or "")
            # Anchor each side of the edge on the OTHER side, matching
            # extract_dependency_chain()'s source-or-target gate: if either endpoint of
            # this real edge is already a ranked file, the other endpoint is allowed in
            # too, even if it was never independently keyword-ranked on its own.
            add_related(dep_source, 220.0, result_path, anchor_path=dep_target)
            add_related(dep_target, 240.0, result_path, anchor_path=dep_source)
    ranked = sorted(related_scores.items(), key=lambda item: item[1], reverse=True)
    output = [path for path, _ in ranked[:limit]]
    existing = {path.lower() for path in output}
    for item in ranked_files or []:
        path = str(item.get("path") or "").strip()
        if not path or path.lower() in existing:
            continue
        output.append(path)
        existing.add(path.lower())
        if len(output) >= limit:
            break
    return output[:limit]


def search(query: str, max_results: int | None = None, max_files: int | None = None) -> dict[str, Any]:
    project_root = project_root_from_here()
    config = load_config(project_root)
    docs = load_index(project_root, config)
    query_tokens = expand_query_tokens(query, tokenize(query))
    if not query_tokens:
        return {
            "query": query,
            "confidence": 0.0,
            "error": "Query had no searchable terms.",
            "results": [],
        }

    query_intents = detect_query_intents(query_tokens)
    query_identifiers = query_identifier_tokens(query)
    scored: list[tuple[float, ContextDocument, list[str]]] = []
    for doc in docs:
        score, reasons = score_document(doc, query_tokens, query)
        if score > 0:
            scored.append((score, doc, reasons))
    scored.sort(key=lambda item: item[0], reverse=True)

    max_results = max_results or int(config.get("max_results", 12))
    max_files = max_files or int(config.get("max_files", 25))
    top = scored[:max_results]
    file_candidate_count = max(max_results, int(config.get("file_candidate_documents", 50)))
    file_top = scored if len(scored) <= file_candidate_count * 10 else scored[:file_candidate_count]
    # 0 (default) preserves today's behavior exactly -- every file a matching document
    # lists gets the full scoring treatment. Set >0 only if a project's documents (e.g.
    # a dependency-edge enrichment doc listing 100+ files) are measurably slowing down
    # aggregate_files() -- see max_files_per_document_in_aggregation docstring below.
    max_files_per_document = int(config.get("max_files_per_document_in_aggregation", 0))
    top_score = top[0][0] if top else 0.0
    # The saturating divisor below used to be a hardcoded 45.0 -- calibrated back when
    # real top_score values were in the low hundreds. Years of independent scoring
    # tuning since then (owner-file boosts, pack-first multipliers, symbol weights)
    # pushed real top_score values into the tens of thousands, so top_score/(top_score+45)
    # saturates to the 0.95 cap on virtually every real match -- confidence stopped
    # discriminating between a weak and a strong result. Making this a config value
    # (rather than picking a new hardcoded constant) prevents the same silent staleness
    # from recurring as scoring keeps evolving -- each project can recalibrate to its
    # own real score distribution instead of inheriting a number tuned for someone else's.
    baseline_confidence = _raw_score_confidence(top_score, config)

    def result_payload(score: float, doc: ContextDocument, reasons: list[str], include_private: bool = False) -> dict[str, Any]:
        payload = {
            "title": doc.title,
            "kind": doc.kind,
            "module": doc.module,
            "pack": doc.pack,
            "path": doc.path,
            "source": doc.source,
            "source_type": doc.source_type,
            "score": round(score, 2),
            "reason": reasons[:6],
            "snippets": best_snippets(doc, query_tokens),
            "files": doc.files[:30],
            "facts": doc.facts[:8],
            "metadata": doc.metadata,
        }
        if include_private:
            payload["_query_tokens"] = query_tokens
            payload["_query_intents"] = sorted(query_intents)
        return payload

    results: list[dict[str, Any]] = []
    for score, doc, reasons in top:
        results.append(result_payload(score, doc, reasons))

    file_results = [
        result_payload(score, doc, reasons, include_private=True)
        for score, doc, reasons in file_top
    ]
    ranked_files = aggregate_files(
        file_results, max_files, query_tokens,
        named_files=query_named_files(query),
        max_files_per_document=max_files_per_document,
    )
    # Additive post-pass -- see rebalance_cross_pack_file_stacking() docstring.
    # Only reorders the top window on a clear evidence margin; a no-op returns
    # ranked_files unchanged, so this can never make results worse than
    # aggregate_files() alone already produced.
    ranked_files = rebalance_cross_pack_file_stacking(ranked_files, file_results)
    ranked_file_paths = {str(item.get("path") or "").lower() for item in ranked_files}
    exact_hint_results = [
        result_payload(score, doc, reasons, include_private=True)
        for score, doc, reasons in collect_docs_for_paths(scored, ranked_file_paths, max(file_candidate_count, 120))
    ]
    merged_hint_results: list[dict[str, Any]] = []
    seen_hint_keys: set[str] = set()
    for item in exact_hint_results + file_results[: max(file_candidate_count, max_results)]:
        key = str(item.get("path") or "")
        if key in seen_hint_keys:
            continue
        seen_hint_keys.add(key)
        merged_hint_results.append(item)
    # Guarantee completeness for a bounded set of the most relevant ranked files:
    # always additionally include each one's single broadest chunk (by edge_count)
    # across all of its duplicate pack-scoped chunks, not just whichever chunk
    # happened to win the query's own keyword-relevance race. No-op for files that
    # only have one chunk, or whose broadest chunk was already collected above.
    # Bounded to the top 5 ranked files to keep cost/scope proportional to where it
    # matters (the files results are actually built around) and avoid diluting the
    # rest of the result set. See broadest_chunk_for_path() for the full rationale.
    for item in ranked_files[:5]:
        broaden_path = str(item.get("path") or "").replace("\\", "/").lower()
        if not broaden_path:
            continue
        broadest_doc = broadest_chunk_for_path(docs, broaden_path)
        if broadest_doc is None:
            continue
        broadest_key = str(broadest_doc.path or "")
        if broadest_key in seen_hint_keys:
            continue
        for score, doc, reasons in scored:
            if doc.id == broadest_doc.id:
                broadest_payload = result_payload(score, doc, reasons, include_private=True)
                break
        else:
            broadest_payload = result_payload(0.0, broadest_doc, ["broadest_chunk_for_completeness"], include_private=True)
        seen_hint_keys.add(broadest_key)
        merged_hint_results.append(broadest_payload)
    hint_results = file_results[: max(file_candidate_count, max_results)]
    ranked_file_order = {
        str(item.get("path") or "").lower(): index
        for index, item in enumerate(ranked_files)
    }
    project_file_cache: dict[str, list[str] | None] = {}
    symbol_hits = extract_symbol_hits(merged_hint_results, preferred_paths=ranked_file_paths, per_path_limit=8, query_tokens=query_tokens)
    symbol_hits = append_fallback_symbols(project_root, ranked_files, symbol_hits, project_file_cache)
    symbol_hits.sort(
        key=lambda item: (
            -score_primary_owner_candidate(item, ranked_file_order, query_tokens, ranked_file_paths, query_identifiers),
            int(item.get("line") or 0),
        )
    )
    # Reserve a slice of the code_block budget for the top-ranked file specifically.
    # enrich_symbol_hits() fills code blocks strictly in list order until
    # code_block_max_blocks is hit, globally across every file combined. When several
    # well-ranked files each contribute a few high-scoring symbols, they can collectively
    # exhaust that budget before the #1 file's own secondary (non-top-priority) symbols
    # -- e.g. an inner helper function -- ever get a turn, even though that file is the
    # actual answer. This does not change scoring or file ranking; it only guarantees the
    # top file's own top few candidates are placed within the existing budget instead of
    # only its single highest-scoring symbol.
    symbol_hits = reserve_top_file_code_block_slots(symbol_hits, ranked_files)
    symbol_hits, code_blocks = enrich_symbol_hits(project_root, config, symbol_hits, project_file_cache)
    location_hints = extract_location_hints(symbol_hits)
    dependency_chain = extract_dependency_chain(
        merged_hint_results,
        preferred_paths=ranked_file_paths,
        ranked_file_order=ranked_file_order,
        query_tokens=query_tokens,
    )
    related_files = extract_related_files(
        merged_hint_results,
        preferred_paths=ranked_file_paths,
        ranked_file_order=ranked_file_order,
        query_tokens=query_tokens,
        ranked_files=ranked_files,
    )
    primary_owner = select_primary_owner(symbol_hits, ranked_file_order, query_tokens, ranked_file_paths, query_identifiers)
    confidence = compute_result_confidence(
        baseline_confidence,
        primary_owner,
        code_blocks,
        symbol_hits,
        location_hints,
        dependency_chain,
        query_tokens=query_tokens,
        ranked_files=ranked_files,
    )
    routing_results = results + file_results[:80]

    facts: list[dict[str, Any]] = []
    for result in results:
        for fact in result.get("facts", [])[:4]:
            facts.append({
                "fact": fact,
                "source": result["source"],
                "source_type": result["source_type"],
            })
            if len(facts) >= 20:
                break
        if len(facts) >= 20:
            break

    return {
        "query": query,
        "confidence": round(confidence, 3),
        "query_terms": query_tokens,
        "query_intents": sorted(query_intents),
        "modules": aggregate_named(routing_results, "module"),
        "packs": aggregate_named(routing_results, "pack", limit=12),
        "files": ranked_files,
        "facts": facts,
        "primary_owner": primary_owner,
        "symbol_hits": symbol_hits,
        "location_hints": location_hints,
        "dependency_chain": dependency_chain,
        "related_files": related_files,
        "code_blocks": code_blocks,
        "results": results,
        "ranking_profile": RANKING_PROFILE,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Search the local ContextBridge index.")
    parser.add_argument("query", help="Search query")
    parser.add_argument("--max-results", type=int, default=None)
    args = parser.parse_args(argv)

    try:
        payload = search(args.query, args.max_results)
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
