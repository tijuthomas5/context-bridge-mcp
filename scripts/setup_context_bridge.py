from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONTEXT_BRIDGE_ROOT = PROJECT_ROOT / "context_bridge"

# (template -> real file) scaffolded on first run. Real files are NEVER overwritten
# on re-run unless --force is passed, so your customised configs/profile survive
# repeated setups (e.g. after every Graphify update).
SCAFFOLD_FILES = {
    "config.hybrid.example.json": "config.hybrid.json",
    "config.example.json": "config.json",
    "config.semantic.example.json": "config.semantic.json",
    "start_Context_Bridge.example.bat": "start_Context_Bridge.bat",
}

# Directories that must exist for the runtime/index/telemetry to work.
SCAFFOLD_DIRS = ("data", "usage", "rules/projects")


def scaffold_files(force: bool) -> None:
    """Create real config/start files from *.example templates.
    Default = create-if-missing (never clobber). --force = overwrite from template."""
    print("\n== Scaffold config files ==", flush=True)
    for rel_dir in SCAFFOLD_DIRS:
        (CONTEXT_BRIDGE_ROOT / rel_dir).mkdir(parents=True, exist_ok=True)
    for template_name, target_name in SCAFFOLD_FILES.items():
        template = CONTEXT_BRIDGE_ROOT / template_name
        target = CONTEXT_BRIDGE_ROOT / target_name
        if not template.exists():
            print(f"  template missing, skipped: {template_name}", flush=True)
            continue
        existed = target.exists()
        if existed and not force:
            print(f"  preserved (already exists): {target_name}", flush=True)
            continue
        shutil.copyfile(template, target)
        print(f"  {'overwritten from template' if existed else 'created from template'}: {target_name}", flush=True)
    if not force:
        print("  (existing files preserved — rerun with --force to reset them to the templates)", flush=True)

REQUIREMENT_FILES = {
    "base": CONTEXT_BRIDGE_ROOT / "setup" / "requirements-base.txt",
    "semantic": CONTEXT_BRIDGE_ROOT / "setup" / "requirements-semantic.txt",
    "all": CONTEXT_BRIDGE_ROOT / "setup" / "requirements-all.txt",
}


def run_step(command: list[str], title: str) -> None:
    print(f"\n== {title} ==", flush=True)
    print("Please wait... this step may take a few minutes.", flush=True)
    completed = subprocess.run(command, cwd=str(PROJECT_ROOT), check=False)
    if completed.returncode != 0:
        raise SystemExit(completed.returncode)


def run_indexer_step(command: list[str], title: str) -> bool:
    """Run the indexer but treat exit code 1 (missing Graphify roots) as a recoverable
    warning rather than a hard abort — the rest of setup (config scaffold, deps) can still
    complete successfully on a fresh clone that has no graphify-out yet."""
    print(f"\n== {title} ==", flush=True)
    print("Please wait... this step may take a few minutes.", flush=True)
    completed = subprocess.run(command, cwd=str(PROJECT_ROOT), check=False)
    if completed.returncode != 0:
        print("\n[WARNING] Index build did not complete — graphify-out data may be missing.", flush=True)
        print("Next steps:", flush=True)
        print("  1. Generate Graphify output for your project (see README.md — Indexing section).", flush=True)
        print("  2. Place it at: <your-repo>/graphify-out/  (and any nested graphify-out/ folders).", flush=True)
        print("  3. Edit config.hybrid.json -> settings.discovery to point at your source folders.", flush=True)
        print("  4. Rerun setup_context_bridge.bat — it is safe to rerun at any time.", flush=True)
        return False
    return True


def print_discovery_summary() -> None:
    report_path = CONTEXT_BRIDGE_ROOT / "data" / "discovery_report.json"
    if not report_path.exists():
        print("\nDiscovery report not found.", flush=True)
        return
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    print("\n== Discovery Summary ==", flush=True)
    print(f"Status: {payload.get('status', 'unknown')}", flush=True)
    print(f"Central graphify-out: {'found' if payload.get('central_graphify_found') else 'missing'}", flush=True)
    print(f"Ownership graphify folders found: {payload.get('ownership_graphify_found_count', 0)}", flush=True)
    print(f"Resolved scan roots: {payload.get('resolved_scan_root_count', 0)}", flush=True)
    if payload.get("required_roots_found"):
        print("Required roots found:", flush=True)
        for item in payload["required_roots_found"]:
            print(f"  - {item}", flush=True)
    if payload.get("optional_roots_found"):
        print("Optional roots found:", flush=True)
        for item in payload["optional_roots_found"]:
            print(f"  - {item}", flush=True)
    if payload.get("optional_roots_missing"):
        print("Missing optional roots:", flush=True)
        for item in payload["optional_roots_missing"]:
            print(f"  - {item}", flush=True)
    if payload.get("discovery_parents"):
        print("Discovery parents scanned:", flush=True)
        for item in payload["discovery_parents"]:
            state = "found" if item.get("exists") else "missing"
            print(
                f"  - {item.get('path')}: {state}, discovered {item.get('found_count', 0)} graphify-out folder(s)",
                flush=True,
            )
    indexed_inputs = payload.get("indexed_inputs") or {}
    used_roots = indexed_inputs.get("used_roots") or []
    if used_roots:
        print("Indexed roots used:", flush=True)
        for item in used_roots:
            print(
                f"  - {item.get('path')}: {item.get('indexed_file_count', 0)} file(s) included",
                flush=True,
            )
    unused_roots = indexed_inputs.get("unused_roots") or []
    if unused_roots:
        print("Resolved roots with 0 included files:", flush=True)
        for item in unused_roots:
            print(f"  - {item.get('path')}", flush=True)
    if payload.get("required_roots_missing"):
        print("Missing required roots:", flush=True)
        for item in payload["required_roots_missing"]:
            print(f"  - {item}", flush=True)
    if payload.get("required_root_files_missing"):
        print("Missing required root files:", flush=True)
        for item in payload["required_root_files_missing"]:
            print(f"  - {item['path']}: {', '.join(item.get('missing_files', []))}", flush=True)
    if payload.get("graphify_roots_without_indexable_files"):
        print("Graphify roots without indexable files:", flush=True)
        for item in payload["graphify_roots_without_indexable_files"]:
            print(f"  - {item}", flush=True)
    if payload.get("warnings"):
        print("Warnings:", flush=True)
        for item in payload["warnings"]:
            print(f"  - {item}", flush=True)
    print(f"Discovery report written to: {report_path}", flush=True)
    print("Open that JSON file to see the full per-folder indexed file list.", flush=True)


def print_keyword_index_summary() -> None:
    index_path = CONTEXT_BRIDGE_ROOT / "data" / "context_index.json"
    if not index_path.exists():
        print("\nKeyword index file not found after build.", flush=True)
        return
    payload = json.loads(index_path.read_text(encoding="utf-8"))
    print("\n== Keyword Index Summary ==", flush=True)
    print(f"Index path: {index_path}", flush=True)
    print(f"Document count: {payload.get('document_count', 0)}", flush=True)
    print(f"Source file count: {payload.get('source_file_count', 0)}", flush=True)
    print(f"Created at: {payload.get('created_at', 'unknown')}", flush=True)
    print("Note: the keyword index is rebuilt fresh each time this setup is run.", flush=True)


def print_semantic_index_summary() -> None:
    manifest_path = CONTEXT_BRIDGE_ROOT / "data" / "vector_meta.semantic.json"
    if not manifest_path.exists():
        print("\nSemantic index manifest not found after build.", flush=True)
        return
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    print("\n== Semantic Index Summary ==", flush=True)
    print(f"Manifest path: {manifest_path}", flush=True)
    print(f"Embedding backend: {payload.get('embedding_backend', 'unknown')}", flush=True)
    print(f"Embedding model: {payload.get('embedding_model', 'unknown')}", flush=True)
    print(f"Chunk count: {payload.get('chunk_count', 0)}", flush=True)
    print(f"Source document count: {payload.get('source_document_count', 0)}", flush=True)
    print(f"Created at: {payload.get('created_at', 'unknown')}", flush=True)
    print("Note: the semantic index is overwritten with a fresh build each time it is requested.", flush=True)


def hash_build_command() -> list[str]:
    return [
        sys.executable,
        "context_bridge/rag/build_vector_index.py",
        "--config",
        "config.hybrid.json",
        "--backend",
        "hash",
        "--model",
        "hash-384",
        "--chunks-output",
        "context_bridge/data/vector_chunks.jsonl",
        "--index-output",
        "context_bridge/data/vector_index.jsonl",
        "--manifest-output",
        "context_bridge/data/vector_meta.json",
    ]


def semantic_build_command() -> list[str]:
    return [
        sys.executable,
        "context_bridge/rag/build_vector_index.py",
        "--config",
        "config.hybrid.json",
        "--backend",
        "sentence-transformers",
        "--model",
        "all-MiniLM-L6-v2",
        "--chunks-output",
        "context_bridge/data/vector_chunks.semantic.jsonl",
        "--index-output",
        "context_bridge/data/vector_index.semantic.jsonl",
        "--manifest-output",
        "context_bridge/data/vector_meta.semantic.json",
        "--batch-size",
        "32",
    ]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="One-click local setup for ContextBridge.")
    parser.add_argument(
        "--profile",
        choices=sorted(REQUIREMENT_FILES),
        default="all",
        help="Dependency bundle to install.",
    )
    parser.add_argument(
        "--skip-install",
        action="store_true",
        help="Skip pip install if dependencies are already present.",
    )
    parser.add_argument(
        "--skip-semantic-index",
        action="store_true",
        help="Skip semantic vector index build for semantic/all profiles.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing config/start files from the *.example templates (default: preserve them).",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    print(f"Workspace root: {PROJECT_ROOT}", flush=True)
    print(f"ContextBridge root: {CONTEXT_BRIDGE_ROOT}", flush=True)
    print(f"Setup profile: {args.profile}", flush=True)
    print("This setup is rerunnable. Running it again is safe and rebuilds generated index files.", flush=True)
    print("If the window appears quiet during indexing or semantic build, wait for the next stage summary.", flush=True)

    # Scaffold config/start files BEFORE indexing — a fresh clone needs a config to index with.
    scaffold_files(force=args.force)
    semantic_build_enabled = args.profile in {"semantic", "all"} and not args.skip_semantic_index
    print(f"Semantic index build in this run: {'yes' if semantic_build_enabled else 'no'}", flush=True)

    if not args.skip_install:
        run_step(
            [sys.executable, "-m", "pip", "install", "-r", str(REQUIREMENT_FILES[args.profile])],
            f"Install dependencies from {REQUIREMENT_FILES[args.profile].name}",
        )
        print(
            "Dependency step finished. If pip showed 'Requirement already satisfied', that means the package was already installed and reused.",
            flush=True,
        )
    else:
        print("Dependency install step skipped because --skip-install was used.", flush=True)

    if args.profile in {"semantic", "all"}:
        run_step(
            [sys.executable, "context_bridge/scripts/check_rag_dependencies.py"],
            "Validate semantic dependencies",
        )
    else:
        print("Semantic dependency validation skipped because the selected profile is base.", flush=True)

    index_ok = run_indexer_step(
        [sys.executable, "context_bridge/src/indexer.py"],
        "Discover Graphify roots and build keyword index",
    )
    print("Reading the generated reports now...", flush=True)
    print_discovery_summary()
    if index_ok:
        print("Keyword index build finished.", flush=True)
        print_keyword_index_summary()
        run_step(hash_build_command(), "Build hash vector index (required for hybrid mode)")
        print("Hash vector index build finished.", flush=True)

    if semantic_build_enabled and index_ok:
        run_step(semantic_build_command(), "Build semantic vector index")
        print("Semantic vector index build finished. Reading the generated manifest now...", flush=True)
        print_semantic_index_summary()
    elif args.profile in {"semantic", "all"} and args.skip_semantic_index:
        print("\nSemantic index build was skipped because --skip-semantic-index was used.", flush=True)
    elif args.profile == "base":
        print("\nSemantic index build skipped because the selected profile is base.", flush=True)
    else:
        print("\nSemantic index build skipped for this run.", flush=True)

    print("\n== Next Steps ==", flush=True)
    if not index_ok:
        print("  !! Add your Graphify data first (see warnings above), then rerun setup.", flush=True)
    print("  Start server + dashboard:  context_bridge\\setup\\windows\\1.  start_Context_Bridge.bat", flush=True)
    print("    (or on Mac/Linux:         context_bridge/setup/mac/start_context_bridge.sh)", flush=True)
    print("  MCP endpoint: http://127.0.0.1:8755/sse", flush=True)
    print("  Dashboard:    http://127.0.0.1:8795", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
