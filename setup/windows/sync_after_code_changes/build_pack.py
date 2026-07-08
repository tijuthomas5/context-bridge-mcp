"""
build_pack.py -- generic, project-agnostic Graphify pack builder.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
from pathlib import Path

# NOTE on naming: `extract` below is `graphify.extract.extract()`, the local
# AST-parsing function -- NOT the `graphify extract` CLI command (Graphify's
# separate paid/LLM semantic pass). This script never invokes that CLI command.
# As an extra guard (see safe_extract_env below), we also strip the API-key env
# vars that would let graphify's extract() attempt a networked semantic call,
# so a rebuild fails loud instead of silently going online.
from graphify.analyze import god_nodes, surprising_connections, suggest_questions
from graphify.build import build_from_json
from graphify.cluster import cluster, score_all
from graphify.detect import detect
from graphify.export import to_html, to_json
from graphify.extract import collect_files, extract
from graphify.report import generate

# Env vars that (per graphify's own CLI output) enable networked/LLM semantic
# extraction. Cleared before every rebuild so this script cannot go online
# even if the calling shell has them set -- see code review finding (offline
# guarantee must be enforced in code, not just documented).
NETWORK_EXTRACTION_ENV_VARS = ("GEMINI_API_KEY", "GOOGLE_API_KEY")


def enforce_offline_extraction():
    cleared = [v for v in NETWORK_EXTRACTION_ENV_VARS if os.environ.pop(v, None) is not None]
    if cleared:
        print("-- offline guard: cleared " + ", ".join(cleared) + " for this process --")


def find_repo_root(pack_dir):
    current = pack_dir.resolve()
    for ancestor in [current] + list(current.parents):
        if ancestor.name == "graphify-out":
            return ancestor.parent
    raise SystemExit("Could not find a 'graphify-out' ancestor above " + str(pack_dir))


def safe_join(root, rel):
    """Resolve `rel` against `root` and refuse it if it escapes root.

    source-files.txt is repo config, but nothing validates its contents today.
    Without this check, an entry like '..\\..\\secret.txt' would let build_pack.py
    read and copy a file from outside the repo into a generated corpus. Every
    path from source-files.txt must go through this before being read or copied.
    """
    root_resolved = root.resolve()
    candidate = (root_resolved / rel).resolve()
    try:
        candidate.relative_to(root_resolved)
    except ValueError:
        raise ValueError("Refusing source-files.txt entry outside repo root: " + rel)
    return candidate


def copy_corpus(root, raw_dir, source_files):
    corpus_dir = raw_dir / "corpus"
    if corpus_dir.exists():
        shutil.rmtree(corpus_dir)
    corpus_dir.mkdir(parents=True, exist_ok=True)

    copied = []
    for rel in source_files:
        src = safe_join(root, rel)
        if not src.exists():
            raise FileNotFoundError("Missing source file for graphify corpus: " + rel)
        dest = corpus_dir / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
        copied.append(dest)
    return copied


def build_manifest(files):
    manifest = {}
    for file_path in files:
        manifest[str(file_path)] = {
            "mtime": file_path.stat().st_mtime,
            "hash": hashlib.md5(file_path.read_bytes()).hexdigest(),
        }
    return manifest


def community_labels(communities):
    return {cid: "Community " + str(cid) for cid in communities}


def build_pack(pack_dir, root):
    raw_dir = pack_dir / "raw"
    source_list = raw_dir / "source-files.txt"
    if not source_list.exists():
        raise FileNotFoundError("Missing source-files.txt in " + str(raw_dir))

    source_files = [
        line.strip() for line in source_list.read_text(encoding="utf-8").splitlines() if line.strip()
    ]
    copied = copy_corpus(root, raw_dir, source_files)
    manifest = build_manifest(copied)
    (raw_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    detection = detect(raw_dir / "corpus")
    (raw_dir / ".graphify_detect.json").write_text(json.dumps(detection, indent=2), encoding="utf-8")

    code_paths = []
    for entry in detection.get("files", {}).get("code", []):
        path = Path(entry)
        if path.is_dir():
            code_paths.extend(collect_files(path))
        else:
            code_paths.append(path)

    if code_paths:
        extraction = extract(code_paths, cache_root=raw_dir / "cache")
    else:
        extraction = {"nodes": [], "edges": [], "input_tokens": 0, "output_tokens": 0}
    (raw_dir / ".graphify_extract.json").write_text(json.dumps(extraction, indent=2), encoding="utf-8")

    graph = build_from_json(extraction)
    communities = cluster(graph)
    cohesion = score_all(graph, communities)
    labels = community_labels(communities)
    gods = god_nodes(graph)
    surprises = surprising_connections(graph, communities)
    questions = suggest_questions(graph, communities, labels)

    to_json(graph, communities, str(raw_dir / "graph.json"), force=True)
    to_html(graph, communities, str(raw_dir / "graph.html"), community_labels=labels)

    analysis = {
        "communities": dict((str(k), v) for k, v in communities.items()),
        "cohesion": dict((str(k), v) for k, v in cohesion.items()),
        "gods": gods,
        "surprises": surprises,
        "suggested_questions": questions,
    }
    (raw_dir / ".graphify_analysis.json").write_text(json.dumps(analysis, indent=2), encoding="utf-8")

    report = generate(
        graph,
        communities,
        cohesion,
        labels,
        gods,
        surprises,
        detection,
        {"input": extraction.get("input_tokens", 0), "output": extraction.get("output_tokens", 0)},
        str(raw_dir / "corpus"),
        suggested_questions=questions,
        built_at_commit=None,
    )
    (raw_dir / "GRAPH_REPORT.md").write_text(report, encoding="utf-8")

    return {
        "nodes": graph.number_of_nodes(),
        "edges": graph.number_of_edges(),
        "communities": len(communities),
    }


def main():
    parser = argparse.ArgumentParser(description="Generic, project-agnostic Graphify pack builder.")
    parser.add_argument("pack_dir", help="Path to a graphify-out/<module>/<pack>/ folder with raw/source-files.txt")
    parser.add_argument("--repo-root", default=None, help="Override auto-detected repo root.")
    args = parser.parse_args()

    enforce_offline_extraction()

    pack_dir = Path(args.pack_dir).resolve()
    root = Path(args.repo_root).resolve() if args.repo_root else find_repo_root(pack_dir)

    stats = build_pack(pack_dir, root)
    try:
        label = str(pack_dir.relative_to(root))
    except ValueError:
        label = str(pack_dir)
    print(json.dumps({label: stats}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
