from __future__ import annotations

import argparse
import hashlib
import json
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
        _is_code_identifier = (
            not raw.islower()                         # CamelCase: "HmsLedgerController"
            or "_" in raw                             # snake_case: "hms_ledger_service"
            or any(c.isdigit() for c in raw)          # versioned: "posV2", "v2"
            or (raw.islower() and len(raw) >= 15)     # long compound: "hmsledgerservice"
        )
        if not _is_code_identifier:
            continue
        if lowered not in seen:
            seen.add(lowered)
            identifiers.append(raw)
    return identifiers


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
    given file and returns its chunk with the highest edge_count, independent of
    any query-relevance score, so it can be force-included alongside whatever
    chunk already won on keyword matching. Mirrors the standard "parent-child"
    hierarchical RAG pattern: always pair a narrow, topic-matched chunk with its
    broader parent instead of letting the two compete in one ranking.
    """
    best: ContextDocument | None = None
    best_edge_count = -1
    for doc in docs:
        if doc.kind != "graphify_graph_chunk":
            continue
        source_file = str((doc.metadata or {}).get("source_file") or "").replace("\\", "/").lower()
        if source_file != normalized_path:
            continue
        edge_count = int((doc.metadata or {}).get("edge_count") or 0)
        if edge_count > best_edge_count:
            best_edge_count = edge_count
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


def aggregate_files(
    results: list[dict[str, Any]],
    max_files: int,
    query_tokens: list[str],
    named_files: set[str] | None = None,
) -> list[dict[str, Any]]:
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
        for idx, file_path in enumerate(file_candidates):
            if not file_path:
                continue
            if "→" in file_path or "->" in file_path or "`" in file_path:
                continue
            score = result_score / (idx + 1)
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
                    score *= 3.0
                    score += 1500.0
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


def extract_symbol_hits(
    results: list[dict[str, Any]],
    limit: int = 20,
    preferred_paths: set[str] | None = None,
    per_path_limit: int = 4,
    query_tokens: list[str] | None = None,
) -> list[dict[str, Any]]:
    # Collect ALL candidate symbols per path first, then keep the per_path_limit
    # that are most RELEVANT to the query — not the first N in declaration order.
    # Index stores up to max_symbol_hints_per_doc symbols in source order; a huge
    # file's root-cause methods sit far down that list, so a positional cap drops
    # them before the relevance sort can ever see them.
    query_distinctive = {
        token for token in set(query_tokens or [])
        if token not in _generic_file_tokens()
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
        hits.extend(cands[: max(1, per_path_limit)])
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
    identifier_hits = sum(1 for token in query_distinctive if token in label_tokens or token in path_tokens or token in label_lower or token in normalized)
    score += identifier_hits * 90.0
    for token in query_distinctive:
        if token in normalized:
            score += 160.0
    for identifier in query_identifiers or []:
        lowered = identifier.lower()
        if lowered in normalized:
            score += 900.0
        elif lowered in label_lower:
            score += 650.0
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
    top_score = top[0][0] if top else 0.0
    confidence = 0.0 if not top else min(0.95, top_score / (top_score + 45.0))

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
    ranked_files = aggregate_files(file_results, max_files, query_tokens, named_files=query_named_files(query))
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
