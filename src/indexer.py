from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from graphify_loader import build_documents, load_config, prepare_indexing_config
from graphify_loader import normalize_rel
from graphify_loader import iter_indexable_files


def project_root_from_here() -> Path:
    return Path(__file__).resolve().parents[2]


def summarize_indexed_inputs(
    project_root: Path,
    resolved_roots: list[dict[str, object]],
    indexed_files: list[Path],
) -> dict[str, object]:
    root_summaries: list[dict[str, object]] = []
    total_indexed = 0

    for root in resolved_roots:
        root_rel = str(root.get("path") or "").replace("\\", "/")
        root_abs = (project_root / root_rel).resolve()
        files_for_root: list[str] = []
        for path in indexed_files:
            try:
                path.resolve().relative_to(root_abs)
                files_for_root.append(normalize_rel(path, project_root))
            except ValueError:
                continue
        files_for_root.sort()
        total_indexed += len(files_for_root)
        root_summaries.append(
            {
                "path": root_rel,
                "kind": root.get("kind"),
                "role": root.get("role"),
                "indexed_file_count": len(files_for_root),
                "indexed_files": files_for_root,
            }
        )

    used_roots = [item for item in root_summaries if item["indexed_file_count"] > 0]
    unused_roots = [item for item in root_summaries if item["indexed_file_count"] == 0]
    return {
        "used_root_count": len(used_roots),
        "unused_root_count": len(unused_roots),
        "total_indexed_file_entries": total_indexed,
        "used_roots": used_roots,
        "unused_roots": unused_roots,
    }


def main() -> int:
    project_root = project_root_from_here()
    raw_config = load_config(project_root)
    config = prepare_indexing_config(project_root, raw_config)
    discovery_report = dict(config.get("_discovery_report") or {})

    discovery_report_path = project_root / "context_bridge" / "data" / "discovery_report.json"
    discovery_report_path.parent.mkdir(parents=True, exist_ok=True)
    discovery_report_path.write_text(json.dumps(discovery_report, indent=2), encoding="utf-8")

    if discovery_report.get("status") == "error":
        print(json.dumps({
            "discovery_report_path": str(discovery_report_path),
            "status": "error",
            "errors": discovery_report.get("errors", []),
            "warnings": discovery_report.get("warnings", []),
        }, indent=2))
        return 1

    docs = build_documents(project_root, config)
    indexed_files = [path for path, _ in iter_indexable_files(project_root, config)]
    resolved_roots = list(config.get("_resolved_scan_roots") or [])
    indexed_inputs = summarize_indexed_inputs(project_root, resolved_roots, indexed_files)
    discovery_report["indexed_inputs"] = indexed_inputs
    discovery_report_path.write_text(json.dumps(discovery_report, indent=2), encoding="utf-8")
    latest_source_mtime = max((path.stat().st_mtime for path in indexed_files), default=0.0)

    index_rel = Path("context_bridge") / config.get("index_path", "data/context_index.json")
    index_path = project_root / index_rel
    index_path.parent.mkdir(parents=True, exist_ok=True)

    payload = {
        "version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "workspace_root": str(project_root),
        "document_count": len(docs),
        "source_file_count": len(indexed_files),
        "latest_source_mtime": latest_source_mtime,
        "discovery_report_path": str(discovery_report_path),
        "discovery_summary": {
            "status": discovery_report.get("status"),
            "resolved_scan_root_count": discovery_report.get("resolved_scan_root_count", 0),
            "ownership_graphify_found_count": discovery_report.get("ownership_graphify_found_count", 0),
            "warnings": len(discovery_report.get("warnings", [])),
            "used_root_count": indexed_inputs.get("used_root_count", 0),
        },
        "documents": [doc.to_dict() for doc in docs],
    }
    index_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    source_types: dict[str, int] = {}
    symbol_hint_document_count = 0
    symbol_hint_total = 0
    dependency_hint_document_count = 0
    dependency_hint_total = 0
    for doc in docs:
        source_types[doc.source_type] = source_types.get(doc.source_type, 0) + 1
        symbol_count = int((doc.metadata or {}).get("symbol_hint_count", 0) or 0)
        if symbol_count > 0:
            symbol_hint_document_count += 1
            symbol_hint_total += symbol_count
        dependency_count = int((doc.metadata or {}).get("dependency_hint_count", 0) or 0)
        if dependency_count > 0:
            dependency_hint_document_count += 1
            dependency_hint_total += dependency_count

    print(json.dumps({
        "index_path": str(index_path),
        "discovery_report_path": str(discovery_report_path),
        "document_count": len(docs),
        "resolved_scan_root_count": discovery_report.get("resolved_scan_root_count", 0),
        "ownership_graphify_found_count": discovery_report.get("ownership_graphify_found_count", 0),
        "used_root_count": indexed_inputs.get("used_root_count", 0),
        "symbol_hint_document_count": symbol_hint_document_count,
        "symbol_hint_total": symbol_hint_total,
        "dependency_hint_document_count": dependency_hint_document_count,
        "dependency_hint_total": dependency_hint_total,
        "warnings": discovery_report.get("warnings", []),
        "source_types": dict(sorted(source_types.items())),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
