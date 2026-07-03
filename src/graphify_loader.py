from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any

from models import ContextDocument


WORD_RE = re.compile(r"[A-Za-z0-9_./:-]+")
LINE_HINT_RE = re.compile(r"^[Ll](\d+)$")

DEFAULT_REQUIRED_ROOTS = (
    {"path": "graphify-out", "kind": "graphify", "role": "central_graphify", "required": True},
)

# Core ships with no project-specific roots. Each project declares its own
# application folders via config (settings.discovery.*). These defaults are the
# generic fallback used only when a config omits the corresponding key.
DEFAULT_DISCOVERY_ROOTS: tuple[dict[str, Any], ...] = ()

DEFAULT_OPTIONAL_ROOTS = (
    {"path": "docs", "kind": "docs", "role": "docs", "required": False},
)

DEFAULT_REQUIRED_ROOT_FILES = {
    "graphify-out": ["manifest.json"],
}

DEFAULT_OWNERSHIP_ROOTS: tuple[dict[str, Any], ...] = ()

DEFAULT_SOURCE_ROOT_PREFIXES = (
    "graphify-out/",
    "docs/",
)

_ACTIVE_CONFIG: dict[str, Any] = {
    "_ownership_graph_roots": {},
    "_source_root_prefixes": DEFAULT_SOURCE_ROOT_PREFIXES,
}

DEFAULT_SYMBOL_CAPTURE_NODE_TYPES = (
    "controller_action",
    "service_method",
    "job_method",
    "ui_function",
    "controller_class",
    "service_class",
    "job_class",
    "ui_component",
)

DEFAULT_DEPENDENCY_EDGE_TYPES = (
    "calls",
    "uses",
    "depends_on",
    "maps",
    "reads",
    "writes",
    "publishes",
    "subscribes",
    "imports",
    "imports_from",
    "references",
    "inherits",
)


_KNOWN_CONFIG_KEYS = {
    "version", "workspace_root", "index_path", "settings", "controls",
    "project_profile", "rules_root", "rag", "search", "pipeline",
    "required_roots", "optional_roots", "discovery_roots", "ownership_graph_roots",
    "secondary_graph_roots", "source_root_prefixes", "ignore_parts", "ignore_extensions",
    "required_root_files", "max_dependency_hints_per_doc", "max_graph_chunks_per_graph",
    "max_graph_chunk_nodes", "max_graph_chunk_edges",
}


def load_config(project_root: Path, config_name: str | None = None) -> dict[str, Any]:
    import sys
    if not config_name:
        config_name = (os.environ.get("CONTEXT_BRIDGE_CONFIG") or "config.json").strip() or "config.json"
    config_path = project_root / "context_bridge" / config_name
    if not config_path.exists():
        raise FileNotFoundError(
            f"[ContextBridge] Config file not found: {config_path}\n"
            f"  Expected CONTEXT_BRIDGE_CONFIG='{config_name}' to exist in {project_root / 'context_bridge'}"
        )
    raw = json.loads(config_path.read_text(encoding="utf-8"))
    unknown = set(raw) - _KNOWN_CONFIG_KEYS
    if unknown:
        print(f"[ContextBridge] Unknown top-level keys in {config_name} (possible typos): {sorted(unknown)}", file=sys.stderr)
    return normalize_config_shape(raw)


def normalize_config_shape(raw_config: dict[str, Any]) -> dict[str, Any]:
    config = dict(raw_config)
    settings = config.pop("settings", None)
    if isinstance(settings, dict):
        merge_grouped_settings(config, settings)
    controls = config.pop("controls", None)
    if isinstance(controls, dict):
        merge_grouped_settings(config, controls)
    return config


def merge_grouped_settings(target: dict[str, Any], grouped: dict[str, Any]) -> None:
    for key, value in grouped.items():
        if key.startswith("_"):
            continue
        if isinstance(value, dict):
            nested_values = {nested_key: nested_value for nested_key, nested_value in value.items() if not nested_key.startswith("_")}
            if key == "rag":
                target["rag"] = dict(nested_values)
                continue
            for nested_key, nested_value in nested_values.items():
                target[nested_key] = nested_value
            continue
        target[key] = value


def prepare_indexing_config(project_root: Path, raw_config: dict[str, Any]) -> dict[str, Any]:
    config = dict(raw_config)
    resolved_roots, report = resolve_scan_roots(project_root, config)
    config["_ownership_graph_roots"] = merge_ownership_roots(config)
    config["_source_root_prefixes"] = merged_source_root_prefixes(config)
    config["_resolved_scan_roots"] = resolved_roots
    config["_discovery_report"] = report
    _ACTIVE_CONFIG.clear()
    _ACTIVE_CONFIG.update({
        "_ownership_graph_roots": config["_ownership_graph_roots"],
        "_source_root_prefixes": config["_source_root_prefixes"],
    })
    return config


def stable_id(path: str, suffix: str = "") -> str:
    digest = hashlib.sha1(f"{path}:{suffix}".encode("utf-8")).hexdigest()[:16]
    return f"doc_{digest}"


def normalize_rel(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def should_ignore(path: Path, config: dict[str, Any]) -> bool:
    ignore_parts = {part.lower() for part in config.get("ignore_parts", [])}
    ignore_exts = {ext.lower() for ext in config.get("ignore_extensions", [])}
    parts = {part.lower() for part in path.parts}
    if parts.intersection(ignore_parts):
        return True
    return path.suffix.lower() in ignore_exts


def normalize_config_path(value: str) -> str:
    return value.replace("\\", "/").strip().strip("/")


def normalize_source_prefix(value: str) -> str:
    normalized = normalize_config_path(value)
    if not normalized:
        return normalized
    return normalized if normalized.endswith("/") else f"{normalized}/"


def merge_config_entries(
    config: dict[str, Any],
    primary_key: str,
    legacy_key: str,
    defaults: tuple[dict[str, Any], ...],
) -> list[dict[str, Any]]:
    values = config.get(primary_key)
    if values is None:
        values = config.get(legacy_key)
    if values is None:
        values = list(defaults)
    return [dict(item) for item in values or []]


def merged_source_root_prefixes(config: dict[str, Any]) -> tuple[str, ...]:
    values = list(DEFAULT_SOURCE_ROOT_PREFIXES)
    values.extend(config.get("source_root_prefixes") or [])
    normalized = [normalize_source_prefix(str(value)) for value in values if str(value).strip()]
    deduped: list[str] = []
    seen: set[str] = set()
    for value in normalized:
        if value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    return tuple(deduped)


def merge_ownership_roots(config: dict[str, Any]) -> dict[str, tuple[str | None, str | None]]:
    entries = merge_config_entries(config, "ownership_graph_roots", "secondary_graph_roots", DEFAULT_OWNERSHIP_ROOTS)
    merged: dict[str, tuple[str | None, str | None]] = {}
    for item in entries:
        path = normalize_config_path(str(item.get("path") or ""))
        area = str(item.get("area") or "").strip() or None
        pack = str(item.get("pack") or "").strip() or None
        if not path:
            continue
        merged[path] = (area, pack)
    return merged


def merge_required_root_files(config: dict[str, Any]) -> dict[str, list[str]]:
    merged = {path: list(files) for path, files in DEFAULT_REQUIRED_ROOT_FILES.items()}
    for path, files in (config.get("required_root_files") or {}).items():
        key = normalize_config_path(str(path))
        values = [str(item).strip() for item in files or [] if str(item).strip()]
        if not key or not values:
            continue
        merged[key] = dedupe(merged.get(key, []) + values)
    return merged


def guess_role_from_path(path: str, kind: str) -> str:
    normalized = normalize_config_path(path)
    if normalized == "graphify-out":
        return "central_graphify"
    if normalized.endswith("/graphify-out"):
        return "ownership_graphify"
    if kind == "assistant_knowledge":
        return "assistant_knowledge"
    if kind == "docs":
        return "docs"
    return "extra"


def root_entry(path: str, kind: str, role: str, required: bool, source: str) -> dict[str, Any]:
    return {
        "path": normalize_config_path(path),
        "kind": kind,
        "role": role,
        "required": required,
        "source": source,
    }


def discovery_entry(
    path: str,
    kind: str,
    role: str,
    source: str,
    match_dir_name: str = "graphify-out",
    required_if_parent_exists: bool = True,
) -> dict[str, Any]:
    return {
        "path": normalize_config_path(path),
        "kind": kind,
        "role": role,
        "source": source,
        "match_dir_name": match_dir_name,
        "required_if_parent_exists": required_if_parent_exists,
    }


def merge_fixed_roots(config: dict[str, Any]) -> list[dict[str, Any]]:
    roots = []
    for item in merge_config_entries(config, "required_roots", "additional_required_roots", DEFAULT_REQUIRED_ROOTS):
        roots.append(
            root_entry(
                item["path"],
                item.get("kind", "graphify"),
                item.get("role", guess_role_from_path(item["path"], item.get("kind", "graphify"))),
                bool(item.get("required", True)),
                "config-required" if config.get("required_roots") is not None else "default-required",
            )
        )
    for item in merge_config_entries(config, "optional_roots", "additional_optional_roots", DEFAULT_OPTIONAL_ROOTS):
        roots.append(
            root_entry(
                item["path"],
                item.get("kind", "docs"),
                item.get("role", guess_role_from_path(item["path"], item.get("kind", "docs"))),
                bool(item.get("required", False)),
                "config-optional" if config.get("optional_roots") is not None else "default-optional",
            )
        )
    for item in config.get("scan_roots", []) or []:
        path = normalize_config_path(str(item.get("path") or ""))
        kind = str(item.get("kind") or "").strip() or "graphify"
        if not path:
            continue
        roots.append(root_entry(path, kind, guess_role_from_path(path, kind), False, "config-legacy-scan_roots"))
    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in roots:
        key = f"{item['path']}|{item['kind']}|{item['role']}"
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def merge_discovery_roots(config: dict[str, Any]) -> list[dict[str, Any]]:
    roots = []
    discovery_items = merge_config_entries(config, "discovery_roots", "additional_discovery_roots", DEFAULT_DISCOVERY_ROOTS)
    for item in discovery_items:
        path = normalize_config_path(str(item.get("path") or ""))
        kind = str(item.get("kind") or "graphify").strip() or "graphify"
        role = str(item.get("role") or "ownership_graphify").strip() or "ownership_graphify"
        if not path:
            continue
        roots.append(
            discovery_entry(
                path,
                kind,
                role,
                "config-discovery" if config.get("discovery_roots") is not None else "default-discovery",
                str(item.get("match_dir_name") or "graphify-out"),
                bool(item.get("required_if_parent_exists", True)),
            )
        )
    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in roots:
        key = f"{item['path']}|{item['kind']}|{item['role']}|{item['match_dir_name']}"
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def find_named_directories(parent: Path, dir_name: str, config: dict[str, Any]) -> list[Path]:
    discovered: list[Path] = []
    ignore_parts = {part.lower() for part in config.get("ignore_parts", [])}
    for path in parent.rglob(dir_name):
        if not path.is_dir():
            continue
        parts = {part.lower() for part in path.parts}
        if parts.intersection(ignore_parts):
            continue
        discovered.append(path)
    return sorted(discovered)


def root_has_indexable_files(root_path: Path, root_kind: str, config: dict[str, Any]) -> bool:
    for path in root_path.rglob("*"):
        if path.is_file() and is_included_file(path, root_kind, config):
            return True
    return False


def resolve_scan_roots(project_root: Path, config: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    fixed_roots = merge_fixed_roots(config)
    discovery_roots = merge_discovery_roots(config)
    required_root_files = merge_required_root_files(config)

    resolved_roots: list[dict[str, Any]] = []
    resolved_keys: set[str] = set()
    required_found: list[str] = []
    required_missing: list[str] = []
    optional_found: list[str] = []
    optional_missing: list[str] = []
    warnings: list[str] = []
    errors: list[str] = []
    discovery_parents: list[dict[str, Any]] = []
    discovered_graphify_roots: list[str] = []

    def add_resolved(item: dict[str, Any], source: str | None = None) -> None:
        key = f"{item['path']}|{item['kind']}"
        if key in resolved_keys:
            return
        resolved_keys.add(key)
        payload = dict(item)
        if source:
            payload["source"] = source
        resolved_roots.append(payload)

    for item in fixed_roots:
        root_path = (project_root / item["path"]).resolve()
        exists = root_path.exists()
        record = item["path"]
        if exists:
            add_resolved(item)
            if item["required"]:
                required_found.append(record)
            else:
                optional_found.append(record)
        elif item["required"]:
            required_missing.append(record)
            errors.append(f"Missing required root: {record}")
        else:
            optional_missing.append(record)
            warnings.append(f"Missing optional root: {record}")

    for item in discovery_roots:
        parent_path = (project_root / item["path"]).resolve()
        exists = parent_path.exists()
        found_paths: list[str] = []
        if exists:
            for discovered in find_named_directories(parent_path, item["match_dir_name"], config):
                rel = normalize_rel(discovered, project_root)
                found_paths.append(rel)
                discovered_graphify_roots.append(rel)
                add_resolved(
                    {
                        "path": rel,
                        "kind": item["kind"],
                        "role": item["role"],
                        "required": False,
                        "source": f"discovered-from:{item['path']}",
                    }
                )
            if item.get("required_if_parent_exists", True) and not found_paths:
                warnings.append(
                    f"Discovery root exists but no {item['match_dir_name']} folders were found under: {item['path']}"
                )
        else:
            warnings.append(f"Discovery parent root is missing: {item['path']}")
        discovery_parents.append(
            {
                "path": item["path"],
                "exists": exists,
                "match_dir_name": item["match_dir_name"],
                "found_count": len(found_paths),
                "found_paths": found_paths,
            }
        )

    graphify_roots_without_indexable_files: list[str] = []
    required_root_files_missing: list[dict[str, Any]] = []
    for item in resolved_roots:
        root_path = (project_root / item["path"]).resolve()
        if item["kind"] == "graphify" and not root_has_indexable_files(root_path, item["kind"], config):
            graphify_roots_without_indexable_files.append(item["path"])
            warnings.append(f"Graphify root has no indexable files: {item['path']}")
        expected_files = required_root_files.get(item["path"], [])
        if not expected_files:
            continue
        missing_files = [name for name in expected_files if not (root_path / name).exists()]
        if missing_files:
            required_root_files_missing.append({"path": item["path"], "missing_files": missing_files})
            errors.append(f"Required files missing under {item['path']}: {', '.join(missing_files)}")

    status = "ok"
    if errors:
        status = "error"
    elif warnings:
        status = "warning"

    report = {
        "workspace_root": str(project_root),
        "status": status,
        "required_roots_found": required_found,
        "required_roots_missing": required_missing,
        "optional_roots_found": optional_found,
        "optional_roots_missing": optional_missing,
        "discovery_parents": discovery_parents,
        "discovered_graphify_roots": dedupe(discovered_graphify_roots),
        "graphify_roots_without_indexable_files": graphify_roots_without_indexable_files,
        "required_root_files_missing": required_root_files_missing,
        "resolved_scan_roots": resolved_roots,
        "resolved_scan_root_count": len(resolved_roots),
        "central_graphify_found": "graphify-out" in required_found,
        "ownership_graphify_found_count": sum(1 for item in resolved_roots if item.get("role") == "ownership_graphify"),
        "warnings": dedupe(warnings),
        "errors": dedupe(errors),
    }
    return resolved_roots, report


def is_included_file(path: Path, root_kind: str, config: dict[str, Any]) -> bool:
    if should_ignore(path, config):
        return False

    name = path.name
    path_text = path.as_posix()
    include_names = set(config.get("include_file_names", []))
    include_contains = config.get("include_path_contains", [])

    if root_kind == "graphify":
        if name.endswith(".enrichment.json"):
            return True
        return name in include_names or any(marker.replace("\\", "/") in path_text for marker in include_contains)

    if root_kind == "assistant_knowledge":
        return path.suffix.lower() in set(config.get("assistant_include_extensions", []))

    if root_kind == "docs":
        return path.suffix.lower() == ".md"

    return False


def infer_secondary_area(rel_path: str) -> tuple[str | None, str | None]:
    rel = rel_path.replace("\\", "/")
    ownership_roots = _ACTIVE_CONFIG.get("_ownership_graph_roots") or {}
    for root, values in ownership_roots.items():
        if rel == root or rel.startswith(root + "/"):
            return values
    return None, None


def infer_secondary_source_root(rel_path: str) -> str | None:
    rel = rel_path.replace("\\", "/")
    ownership_roots = _ACTIVE_CONFIG.get("_ownership_graph_roots") or {}
    for root in ownership_roots:
        if rel == root or rel.startswith(root + "/"):
            return root.removesuffix("/graphify-out")
    return None


def canonicalize_source_file(graph_rel_path: str, source_file: str) -> str:
    value = source_file.replace("\\", "/").strip()
    if not value:
        return value
    source_root_prefixes = _ACTIVE_CONFIG.get("_source_root_prefixes") or DEFAULT_SOURCE_ROOT_PREFIXES
    if value.startswith(tuple(source_root_prefixes)):
        return value
    source_root = infer_secondary_source_root(graph_rel_path)
    if not source_root:
        return value
    return f"{source_root}/{value}".replace("//", "/")


def infer_module_pack(rel_path: str) -> tuple[str | None, str | None]:
    area, pack = infer_secondary_area(rel_path)
    if area:
        return area, pack

    parts = rel_path.replace("\\", "/").split("/")
    if "graphify-out" in parts:
        idx = parts.index("graphify-out")
        if len(parts) > idx + 2:
            return parts[idx + 1], parts[idx + 2]
        if len(parts) > idx + 1:
            return parts[idx + 1], None
    if "ops-knowledge" in parts:
        idx = parts.index("ops-knowledge")
        if len(parts) > idx + 1:
            return parts[idx + 1], parts[idx + 2] if len(parts) > idx + 2 else None
    if "graphify-safe" in parts:
        idx = parts.index("graphify-safe")
        if len(parts) > idx + 1:
            return parts[idx + 1], parts[idx + 2] if len(parts) > idx + 2 else None
    return None, None


def extract_source_files(text: str) -> list[str]:
    files: list[str] = []
    for raw in text.splitlines():
        line = raw.strip().strip("-*` ")
        if not line:
            continue
        if re.search(r"\.(cs|tsx|ts|js|json|sql|md|yaml|yml)$", line, re.IGNORECASE):
            files.append(line.replace("\\", "/"))
    return dedupe(files)[:100]


def extract_facts(text: str, max_facts: int = 25) -> list[str]:
    facts: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith(("#", "|", "```")):
            continue
        if len(line) < 25:
            continue
        if len(line) > 400:
            line = line[:397] + "..."
        if any(marker in line.lower() for marker in ("source:", "last verified", "graphify-out/")):
            continue
        if line.startswith(("-", "*")) or ":" in line or "->" in line or "=" in line:
            facts.append(line.strip("-* "))
        if len(facts) >= max_facts:
            break
    return dedupe(facts)


def dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        key = value.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(value)
    return out


def symbol_capture_enabled(config: dict[str, Any]) -> bool:
    return bool(config.get("enable_symbol_hints", True))


def configured_symbol_node_types(config: dict[str, Any]) -> set[str]:
    values = config.get("symbol_capture_node_types", DEFAULT_SYMBOL_CAPTURE_NODE_TYPES)
    return {str(value).strip() for value in values if str(value).strip()}


def dependency_chain_enabled(config: dict[str, Any]) -> bool:
    return bool(config.get("enable_dependency_chain", True))


def configured_dependency_edge_types(config: dict[str, Any]) -> set[str]:
    values = config.get("dependency_edge_types", DEFAULT_DEPENDENCY_EDGE_TYPES)
    return {str(value).strip().lower() for value in values if str(value).strip()}


def parse_source_location(value: Any) -> int | None:
    text = str(value or "").strip()
    if not text:
        return None
    match = LINE_HINT_RE.match(text)
    if match:
        return int(match.group(1))
    digits = re.findall(r"\d+", text)
    if digits:
        return int(digits[0])
    return None


def classify_symbol_kind(label: str, source_file: str) -> str | None:
    normalized_label = label.strip()
    path = source_file.lower()
    if not normalized_label or not path:
        return None
    if normalized_label.endswith(".cs") or normalized_label.endswith(".tsx") or normalized_label.endswith(".ts"):
        return "file"
    if normalized_label.startswith(".") and normalized_label.endswith("()"):
        if "/controllers/" in path:
            return "controller_action"
        if "/services/" in path:
            return "service_method"
        if "/jobs/" in path:
            return "job_method"
        if "/src/" in path or path.endswith((".tsx", ".ts", ".js", ".jsx")):
            return "ui_function"
        return "method"
    if normalized_label.endswith("Controller") and "/controllers/" in path:
        return "controller_class"
    if normalized_label.endswith("Service") and "/services/" in path:
        return "service_class"
    if normalized_label.endswith("Job") and "/jobs/" in path:
        return "job_class"
    if path.endswith(".tsx"):
        return "ui_component" if normalized_label[:1].isupper() else "ui_function"
    if path.endswith((".ts", ".js", ".jsx")):
        return "ui_function"
    if normalized_label.endswith("Dto") or normalized_label.endswith("Dtos"):
        return "dto_type"
    if normalized_label.endswith("Entity") or "/entities/" in path:
        return "entity_type"
    if normalized_label.endswith("()") and not normalized_label.startswith("."):
        return "method"
    return None


def collect_symbol_hints(
    rel: str,
    nodes: list[dict[str, Any]],
    config: dict[str, Any],
    source_file_filter: str | None = None,
) -> list[dict[str, Any]]:
    if not symbol_capture_enabled(config):
        return []

    allowed_kinds = configured_symbol_node_types(config)
    max_symbols = int(config.get("max_symbol_hints_per_doc", 40))
    hints: list[dict[str, Any]] = []
    seen: set[tuple[str, str, int | None]] = set()

    for node in nodes:
        label = _node_label(node).strip()
        source_file = canonicalize_source_file(rel, _node_source_file(node))
        if not label or not source_file:
            continue
        if source_file_filter and source_file != source_file_filter:
            continue
        kind = classify_symbol_kind(label, source_file)
        if not kind or kind not in allowed_kinds:
            continue
        line = parse_source_location(node.get("source_location"))
        key = (label.lower(), source_file.lower(), line)
        if key in seen:
            continue
        seen.add(key)
        hints.append(
            {
                "label": label,
                "kind": kind,
                "source_file": source_file,
                "source_location": str(node.get("source_location") or ""),
                "line": line,
                "node_id": str(node.get("id") or ""),
            }
        )
        if len(hints) >= max_symbols:
            break
    return hints


def build_node_lookup(
    rel: str,
    nodes: list[dict[str, Any]],
) -> tuple[dict[str, dict[str, Any]], dict[str, list[str]]]:
    node_by_id: dict[str, dict[str, Any]] = {}
    label_to_files: dict[str, list[str]] = {}
    for node in nodes:
        label = _node_label(node).strip()
        source_file = canonicalize_source_file(rel, _node_source_file(node))
        node_id = str(node.get("id") or "").strip()
        node_payload = {
            "label": label,
            "source_file": source_file,
            "source_location": str(node.get("source_location") or ""),
            "line": parse_source_location(node.get("source_location")),
            "node_id": node_id,
        }
        if node_id:
            node_by_id[node_id] = node_payload
        if label and source_file:
            label_to_files.setdefault(label, []).append(source_file)
    return node_by_id, label_to_files


def collect_dependency_hints(
    rel: str,
    nodes: list[dict[str, Any]],
    links: list[dict[str, Any]],
    config: dict[str, Any],
    source_file_filter: str | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    if not dependency_chain_enabled(config):
        return [], []

    allowed_relations = configured_dependency_edge_types(config)
    max_edges = int(config.get("max_dependency_hints_per_doc", 60))
    node_by_id, label_to_files = build_node_lookup(rel, nodes)
    hints: list[dict[str, Any]] = []
    related_files: list[str] = []
    seen: set[tuple[str, str, str, str]] = set()

    for edge in links:
        relation = str(edge.get("relation") or edge.get("label") or "").strip().lower()
        if not relation or relation not in allowed_relations:
            continue
        source_ref = str(edge.get("source") or edge.get("from") or "").strip()
        target_ref = str(edge.get("target") or edge.get("to") or "").strip()
        if not source_ref or not target_ref:
            continue

        _src_files = label_to_files.get(source_ref, [])
        _tgt_files = label_to_files.get(target_ref, [])
        source_node = node_by_id.get(source_ref, {"label": source_ref, "source_file": _src_files[0] if _src_files else "", "line": None})
        target_node = node_by_id.get(target_ref, {"label": target_ref, "source_file": _tgt_files[0] if _tgt_files else "", "line": None})
        source_file = str(source_node.get("source_file") or canonicalize_source_file(rel, str(edge.get("source_file") or "")))
        target_file = str(target_node.get("source_file") or "")
        if source_file_filter and source_file_filter not in {source_file, target_file}:
            continue

        # Skip intra-file edges — internal method calls within the same file
        # are not useful for cross-file navigation and produce self-loop noise.
        if source_file and target_file and source_file.lower() == target_file.lower():
            continue

        key = (str(source_node.get("label") or source_ref).lower(), relation, str(target_node.get("label") or target_ref).lower(), source_file.lower())
        if key in seen:
            continue
        seen.add(key)

        if source_file:
            related_files.append(source_file)
        if target_file:
            related_files.append(target_file)

        hints.append(
            {
                "relation": relation,
                "source_label": str(source_node.get("label") or source_ref),
                "source_file": source_file,
                "source_location": str(edge.get("source_location") or source_node.get("source_location") or ""),
                "source_line": parse_source_location(edge.get("source_location") or source_node.get("source_location")),
                "target_label": str(target_node.get("label") or target_ref),
                "target_file": target_file,
                "target_location": str(target_node.get("source_location") or ""),
                "target_line": target_node.get("line"),
            }
        )
        if len(hints) >= max_edges:
            break

    return hints, dedupe([value for value in related_files if value])


def load_text_document(path: Path, project_root: Path, root_kind: str, config: dict[str, Any]) -> ContextDocument | None:
    max_bytes = int(config.get("max_text_file_bytes", 1_048_576))
    if path.stat().st_size > max_bytes:
        return None

    rel = normalize_rel(path, project_root)
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None

    module, pack = infer_module_pack(rel)
    _, secondary_pack = infer_secondary_area(rel)
    title = path.stem.replace("-", " ").replace("_", " ")
    source_type = path.name if path.name in {"GRAPH_REPORT.md", "source-files.txt", "scope-summary.md", "manifest.json", "index.md"} else "behavior pack" if "/behavior/" in rel else path.suffix.lower()

    return ContextDocument(
        id=stable_id(rel),
        title=title,
        text=text,
        path=rel,
        source=rel,
        source_type=source_type,
        kind=root_kind,
        module=module,
        pack=pack,
        files=[canonicalize_source_file(rel, file_path) for file_path in extract_source_files(text)],
        facts=extract_facts(text),
        metadata={
            "size_bytes": path.stat().st_size,
            "source_level": "secondary" if secondary_pack else "central",
            "area": module,
        },
    )


def graph_value_text(value: Any) -> str:
    if isinstance(value, dict):
        return " ".join(str(v) for v in value.values() if isinstance(v, (str, int, float)))
    return str(value)


def _node_label(node: dict[str, Any]) -> str:
    return str(node.get("label") or node.get("id") or "")


def _node_source_file(node: dict[str, Any]) -> str:
    return str(node.get("source_file") or node.get("file") or "").replace("\\", "/")


def load_graph_document(path: Path, project_root: Path, config: dict[str, Any]) -> ContextDocument | None:
    rel = normalize_rel(path, project_root)
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, json.JSONDecodeError):
        return None

    max_nodes = int(config.get("max_graph_nodes_per_doc", 200))
    max_edges = int(config.get("max_graph_edges_per_doc", 300))
    nodes = data.get("nodes") or []
    links = data.get("links") or data.get("edges") or []

    node_lines: list[str] = []
    source_files: list[str] = []
    facts: list[str] = []
    for node in nodes[:max_nodes]:
        if not isinstance(node, dict):
            continue
        label = node.get("label") or node.get("id") or ""
        source_file = node.get("source_file") or node.get("file") or ""
        if source_file:
            source_files.append(canonicalize_source_file(rel, str(source_file)))
        if label:
            node_lines.append(f"NODE {label} {source_file}")

    edge_lines: list[str] = []
    for edge in links[:max_edges]:
        if not isinstance(edge, dict):
            continue
        source = edge.get("source") or edge.get("from") or ""
        target = edge.get("target") or edge.get("to") or ""
        relation = edge.get("relation") or edge.get("label") or ""
        confidence = edge.get("confidence") or ""
        line = f"EDGE {source} {relation} {target} {confidence}".strip()
        edge_lines.append(line)
        if relation and source and target and len(facts) < 25:
            facts.append(f"{source} --{relation}--> {target}")

    module, pack = infer_module_pack(rel)
    _, secondary_pack = infer_secondary_area(rel)
    text = "\n".join(node_lines + edge_lines)
    typed_nodes = [node for node in nodes if isinstance(node, dict)]
    typed_links = [edge for edge in links if isinstance(edge, dict)]
    symbol_hints = collect_symbol_hints(rel, typed_nodes, config)
    dependency_hints, related_files = collect_dependency_hints(rel, typed_nodes, typed_links, config)
    return ContextDocument(
        id=stable_id(rel),
        title=f"{pack or module or 'graph'} graph",
        text=text,
        path=rel,
        source=rel,
        source_type=path.name,
        kind="graphify_graph",
        module=module,
        pack=pack,
        files=dedupe(source_files)[:150],
        facts=dedupe(facts),
        metadata={
            "node_count": len(nodes),
            "edge_count": len(links),
            "size_bytes": path.stat().st_size,
            "source_level": "secondary" if secondary_pack else "central",
            "area": module,
            "symbol_hints_enabled": symbol_capture_enabled(config),
            "symbol_hint_count": len(symbol_hints),
            "symbol_hints": symbol_hints,
            "dependency_chain_enabled": dependency_chain_enabled(config),
            "dependency_hint_count": len(dependency_hints),
            "dependency_hints": dependency_hints,
            "related_files": related_files[:50],
        },
    )


def load_graph_chunks(path: Path, project_root: Path, config: dict[str, Any]) -> list[ContextDocument]:
    rel = normalize_rel(path, project_root)
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, json.JSONDecodeError):
        return []

    nodes = [node for node in (data.get("nodes") or []) if isinstance(node, dict)]
    links = [edge for edge in (data.get("links") or data.get("edges") or []) if isinstance(edge, dict)]
    module, pack = infer_module_pack(rel)
    _, secondary_pack = infer_secondary_area(rel)
    if not secondary_pack:
        if not config.get("chunk_central_graph"):
            return []

    max_chunks = int(config.get("max_graph_chunks_per_graph", 250))
    max_nodes = int(config.get("max_graph_chunk_nodes", 80))
    max_edges = int(config.get("max_graph_chunk_edges", 120))

    nodes_by_file: dict[str, list[dict[str, Any]]] = {}
    labels_by_file: dict[str, set[str]] = {}
    label_to_file: dict[str, str] = {}
    id_to_file: dict[str, str] = {}
    for node in nodes:
        source_file = canonicalize_source_file(rel, _node_source_file(node))
        label = _node_label(node)
        if not source_file:
            continue
        nodes_by_file.setdefault(source_file, []).append(node)
        labels_by_file.setdefault(source_file, set()).add(label)
        if label:
            label_to_file[label] = source_file
        node_id = str(node.get("id") or "").strip()
        if node_id:
            id_to_file[node_id] = source_file

    # Graphify's graph.json follows the standard node-link format (NetworkX/D3.js):
    # edges reference nodes by their "id" field, not by "label". Resolve by id first
    # (the correct, standard lookup) and fall back to label only for edges that don't
    # use id-shaped references.
    edges_by_file: dict[str, list[dict[str, Any]]] = {source_file: [] for source_file in nodes_by_file}
    for edge in links:
        source = str(edge.get("source") or edge.get("from") or "")
        target = str(edge.get("target") or edge.get("to") or "")
        candidate_files = {
            id_to_file.get(source) or label_to_file.get(source),
            id_to_file.get(target) or label_to_file.get(target),
        }
        for source_file in candidate_files:
            if source_file:
                edges_by_file.setdefault(source_file, []).append(edge)

    docs: list[ContextDocument] = []
    for source_file in sorted(nodes_by_file)[:max_chunks]:
        file_nodes = nodes_by_file[source_file][:max_nodes]
        file_edges = edges_by_file.get(source_file, [])[:max_edges]
        node_lines = [
            f"NODE {_node_label(node)} {canonicalize_source_file(rel, _node_source_file(node))}"
            for node in file_nodes
            if _node_label(node)
        ]
        edge_lines: list[str] = []
        facts: list[str] = []
        for edge in file_edges:
            source = edge.get("source") or edge.get("from") or ""
            target = edge.get("target") or edge.get("to") or ""
            relation = edge.get("relation") or edge.get("label") or ""
            line = f"EDGE {source} {relation} {target}".strip()
            edge_lines.append(line)
            if relation and source and target and len(facts) < 25:
                facts.append(f"{source} --{relation}--> {target}")

        title = source_file.split("/")[-1]
        symbol_hints = collect_symbol_hints(rel, file_nodes, config, source_file_filter=source_file)
        # Pass the full graph's node list (not just this file's own nodes) so that
        # cross-file edge endpoints (e.g. an imported file's node) can still be
        # resolved to their real source_file. file_edges stays scoped to just the
        # edges touching this file.
        dependency_hints, related_files = collect_dependency_hints(
            rel,
            nodes,
            file_edges,
            config,
            source_file_filter=source_file,
        )
        docs.append(ContextDocument(
            id=stable_id(rel, source_file),
            title=f"{title} ownership graph",
            text="\n".join(node_lines + edge_lines),
            path=f"{rel}::{source_file}",
            source=rel,
            source_type="graph chunk",
            kind="graphify_graph_chunk",
            module=module,
            pack=pack,
            files=[source_file],
            facts=dedupe(facts),
            metadata={
                "source_level": "secondary",
                "area": module,
                "source_file": source_file,
                "node_count": len(nodes_by_file[source_file]),
                "edge_count": len(edges_by_file.get(source_file, [])),
                "symbol_hints_enabled": symbol_capture_enabled(config),
                "symbol_hint_count": len(symbol_hints),
                "symbol_hints": symbol_hints,
                "dependency_chain_enabled": dependency_chain_enabled(config),
                "dependency_hint_count": len(dependency_hints),
                "dependency_hints": dependency_hints,
                "related_files": [value for value in related_files[:25] if value and value != source_file],
            },
        ))
    return docs


def iter_indexable_files(project_root: Path, config: dict[str, Any]) -> list[tuple[Path, str]]:
    files: list[tuple[Path, str]] = []
    roots = config.get("_resolved_scan_roots") or config.get("scan_roots", [])
    for root in roots:
        root_path = (project_root / root["path"]).resolve()
        root_kind = root["kind"]
        if not root_path.exists():
            continue
        for path in root_path.rglob("*"):
            if not path.is_file():
                continue
            if is_included_file(path, root_kind, config):
                files.append((path, root_kind))
    return files


def build_documents(project_root: Path, config: dict[str, Any]) -> list[ContextDocument]:
    docs: list[ContextDocument] = []
    for path, kind in iter_indexable_files(project_root, config):
        if path.name == "graph.json" or path.name.endswith(".enrichment.json"):
            doc = load_graph_document(path, project_root, config)
            if path.name == "graph.json":
                docs.extend(load_graph_chunks(path, project_root, config))
        else:
            doc = load_text_document(path, project_root, kind, config)
        if doc is not None and doc.text.strip():
            docs.append(doc)
    return docs
