"""
scan_repo.py -- generic, project-agnostic repo scanner for ContextBridge.
"""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.resolve().parents[3]
GRAPHIFY_OUT = REPO_ROOT / "graphify-out"
BUILD_PACK_SCRIPT = SCRIPT_DIR / "build_pack.py"
PROJECT_MAP_PATH = SCRIPT_DIR / "project_map.json"
ORPHAN_REPORT_PATH = SCRIPT_DIR / "orphan_review.json"

DEFAULT_IGNORE_DIRS = {
    "node_modules", "bin", "obj", "dist", "build", ".git", "__pycache__",
    "__tests__", "e2e", "Migrations", "graphify-out", ".venv", "venv",
}
DEFAULT_IGNORE_PATTERNS = [
    "*.test.ts", "*.test.tsx", "*.spec.ts", "*.spec.tsx",
    "*.Designer.cs", "*DbContextFactory.cs",
]
PROJECT_MARKERS = ["package.json", "*.csproj", "pyproject.toml", "go.mod", "pom.xml"]
MARKER_EXTENSIONS = {
    "package.json": [".ts", ".tsx", ".js", ".jsx"],
    "*.csproj": [".cs"],
    "pyproject.toml": [".py"],
    "go.mod": [".go"],
    "pom.xml": [".java"],
}


def auto_detect_project_map():
    roots = []
    for child in sorted(REPO_ROOT.iterdir()):
        if not child.is_dir() or child.name in DEFAULT_IGNORE_DIRS or child.name.startswith("."):
            continue
        matched_ext = None
        for marker in PROJECT_MARKERS:
            if list(child.glob(marker)) or list(child.glob("*/" + marker)):
                matched_ext = MARKER_EXTENSIONS[marker]
                break
        if matched_ext:
            roots.append({"name": child.name, "path": child.name, "extensions": matched_ext})

    if not roots:
        roots.append({
            "name": "root",
            "path": ".",
            "extensions": [".ts", ".tsx", ".js", ".jsx", ".cs", ".py", ".go", ".java"],
        })

    return {
        "roots": roots,
        "modules_override": {},
        "ignore_dirs": sorted(DEFAULT_IGNORE_DIRS),
        "ignore_file_patterns": DEFAULT_IGNORE_PATTERNS,
        "excluded_modules": [],
    }


def load_project_map():
    if PROJECT_MAP_PATH.exists():
        return json.loads(PROJECT_MAP_PATH.read_text(encoding="utf-8")), False

    project_map = auto_detect_project_map()
    PROJECT_MAP_PATH.write_text(json.dumps(project_map, indent=2), encoding="utf-8")
    return project_map, True


def module_for_path(rel_path, root_name, root_path):
    root_rel = Path(root_path).as_posix().strip("./")
    rel = rel_path
    if root_rel and root_rel != ".":
        rel = rel_path[len(root_rel):].lstrip("/")
    parts = rel.split("/")
    return parts[0] if len(parts) > 1 else root_name


def matches_any_pattern(name, patterns):
    return any(fnmatch.fnmatch(name, pat) for pat in patterns)


def inventory_real_files(project_map):
    import os

    ignore_dirs = set(project_map.get("ignore_dirs", DEFAULT_IGNORE_DIRS))
    ignore_patterns = project_map.get("ignore_file_patterns", DEFAULT_IGNORE_PATTERNS)
    modules_override = project_map.get("modules_override", {})

    files = {}
    for root_entry in project_map.get("roots", []):
        root_path = REPO_ROOT / root_entry["path"]
        if not root_path.exists():
            continue
        extensions = tuple(root_entry.get("extensions", []))

        for dirpath, dirnames, filenames in os.walk(root_path):
            dirnames[:] = [d for d in dirnames if d not in ignore_dirs and not d.startswith(".")]
            for name in filenames:
                f = Path(dirpath) / name
                if extensions and f.suffix not in extensions:
                    continue
                if matches_any_pattern(name, ignore_patterns):
                    continue
                rel = f.relative_to(REPO_ROOT).as_posix()
                override = modules_override.get(root_entry["name"])
                module = override if override else module_for_path(rel, root_entry["name"], root_entry["path"])
                files[rel] = module
    return files


def inventory_pack_files():
    covered = {}
    pack_module_counts = {}
    if not GRAPHIFY_OUT.exists():
        return covered, pack_module_counts

    for pack_dir in sorted(GRAPHIFY_OUT.glob("*/*")):
        source_list = pack_dir / "raw" / "source-files.txt"
        if not source_list.exists():
            continue
        pack_key = pack_dir.parent.name + "/" + pack_dir.name
        for line in source_list.read_text(encoding="utf-8", errors="replace").splitlines():
            rel = line.strip().replace("\\", "/")
            if not rel:
                continue
            covered.setdefault(rel, []).append(pack_key)
            parts = rel.split("/")
            folder = parts[1] if len(parts) > 2 else (parts[0] if parts else "")
            pack_module_counts.setdefault(pack_key, {}).setdefault(folder, 0)
            pack_module_counts[pack_key][folder] += 1

    return covered, pack_module_counts


def guess_pack_for_orphan(orphan_rel, pack_module_counts):
    parts = orphan_rel.split("/")
    folder = parts[1] if len(parts) > 2 else (parts[0] if parts else "")
    best_pack, best_score = None, 0
    for pack_key, folder_counts in pack_module_counts.items():
        score = folder_counts.get(folder, 0)
        if score > best_score:
            best_pack, best_score = pack_key, score
    if best_pack:
        return best_pack + " (folder-affinity guess, " + str(best_score) + " related files)"
    return "UNASSIGNED -- no existing pack looks related, may need a new pack"


def write_orphan_report(orphans, pack_module_counts):
    entries = []
    for orphan in orphans:
        parts = orphan.split("/")
        folder = parts[1] if len(parts) > 2 else (parts[0] if parts else "")
        best_pack, best_score = None, 0
        for pack_key, folder_counts in pack_module_counts.items():
            score = folder_counts.get(folder, 0)
            if score > best_score:
                best_pack, best_score = pack_key, score
        entries.append({
            "file": orphan,
            "suggested_pack": best_pack,
            "confidence": best_score,
            "decision": "",
        })
    payload = {
        "generated_by": "scan_repo.py",
        "instructions": (
            "Review each entry. Set 'decision' to an existing pack key "
            "(e.g. 'billing/invoicing') to add this file to that pack's "
            "source-files.txt, to 'NEW:<pack-name>' to flag it for a new pack, "
            "or leave blank / 'skip' to ignore. This file is never read "
            "automatically -- applying decisions is a separate, explicit step."
        ),
        "orphan_count": len(entries),
        "orphans": entries,
    }
    ORPHAN_REPORT_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def find_native_graphify_folders(project_map):
    import os

    ignore_dirs = set(project_map.get("ignore_dirs", DEFAULT_IGNORE_DIRS))
    found = []
    for root_entry in project_map.get("roots", []):
        root_path = REPO_ROOT / root_entry["path"]
        if not root_path.exists():
            continue
        extensions = tuple(root_entry.get("extensions", []))
        for dirpath, dirnames, filenames in os.walk(root_path):
            if "graphify-out" in dirnames:
                found.append((Path(dirpath) / "graphify-out", extensions))
            dirnames[:] = [
                d for d in dirnames if d not in ignore_dirs and not d.startswith(".") and d != "graphify-out"
            ]
    return found


def native_graphify_is_stale(native_dir, extensions, project_map):
    import os

    ignore_dirs = set(project_map.get("ignore_dirs", DEFAULT_IGNORE_DIRS))
    graph_json = native_dir / "graph.json"
    if not graph_json.exists():
        return True, "no graph.json yet -- never run graphify update/extract here"

    graph_mtime = graph_json.stat().st_mtime
    parent = native_dir.parent
    newest_mtime = 0.0
    newest_file = None

    for dirpath, dirnames, filenames in os.walk(parent):
        dirnames[:] = [d for d in dirnames if d not in ignore_dirs and not d.startswith(".")]
        for name in filenames:
            f = Path(dirpath) / name
            if extensions and f.suffix not in extensions:
                continue
            mtime = f.stat().st_mtime
            if mtime > newest_mtime:
                newest_mtime = mtime
                newest_file = f

    if newest_file is not None and newest_mtime > graph_mtime:
        rel = newest_file.relative_to(REPO_ROOT).as_posix()
        return True, "source changed after last graphify update/extract here (newest: " + rel + ")"
    return False, "up to date (mtime-based check)"


def hash_file(path):
    return hashlib.md5(path.read_bytes()).hexdigest()


def safe_repo_path(rel):
    """Resolve rel against REPO_ROOT and refuse it if it escapes REPO_ROOT.

    source-files.txt is trusted config today with no path validation. A crafted
    entry like '..\\..\\secret.txt' would otherwise let this read/hash a file
    outside the repo. Returns None (not an exception) so callers can surface it
    as a normal stale-reason instead of crashing the whole scan.
    """
    root_resolved = REPO_ROOT.resolve()
    candidate = (root_resolved / rel).resolve()
    try:
        candidate.relative_to(root_resolved)
    except ValueError:
        return None
    return candidate


def pack_is_stale(pack_dir):
    raw_dir = pack_dir / "raw"
    source_list = raw_dir / "source-files.txt"
    manifest_path = raw_dir / "manifest.json"
    source_files = [ln.strip() for ln in source_list.read_text(encoding="utf-8").splitlines() if ln.strip()]

    if not manifest_path.exists():
        return True, "no manifest.json yet"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return True, "manifest.json is not valid JSON"

    is_hash_manifest = bool(manifest) and all(isinstance(v, dict) for v in manifest.values())
    if not is_hash_manifest:
        return True, "manifest.json is not a hash manifest yet"

    by_suffix = {}
    for key, value in manifest.items():
        by_suffix[key.replace("\\", "/")] = value.get("hash")

    for rel in source_files:
        src = safe_repo_path(rel)
        if src is None:
            return True, "REFUSED -- source-files.txt entry escapes repo root: " + rel
        if not src.exists():
            return True, "source file missing on disk: " + rel
        matched = None
        for suffix, h in by_suffix.items():
            if suffix.endswith(rel):
                matched = h
                break
        if matched is None:
            return True, "file not present in manifest: " + rel
        if matched != hash_file(src):
            return True, "content changed since last build: " + rel

    return False, "up to date"


def discover_packs(project_map):
    packs = []
    if not GRAPHIFY_OUT.exists():
        return packs
    excluded = set(project_map.get("excluded_modules", []))
    for module_dir in GRAPHIFY_OUT.iterdir():
        if not module_dir.is_dir() or module_dir.name in excluded:
            continue
        for pack_dir in module_dir.iterdir():
            if pack_dir.is_dir() and (pack_dir / "raw" / "source-files.txt").exists():
                packs.append(pack_dir)
    return sorted(packs)


def run_native_update(native_dir):
    target = native_dir.parent
    print("-- graphify update " + str(target.relative_to(REPO_ROOT)) + " --")
    try:
        result = subprocess.run(["graphify", "update", str(target)], cwd=str(REPO_ROOT))
    except FileNotFoundError:
        print("  [SKIPPED] `graphify` CLI not found on PATH -- install/activate it, then rerun.")
        return 1
    return result.returncode


def run_build(pack_dir):
    print("-- building " + str(pack_dir.relative_to(REPO_ROOT)) + " --")
    result = subprocess.run(
        [sys.executable, str(BUILD_PACK_SCRIPT), str(pack_dir), "--repo-root", str(REPO_ROOT)],
        cwd=str(REPO_ROOT),
    )
    return result.returncode


def main():
    parser = argparse.ArgumentParser(description="Generic whole-repo scan for ContextBridge pack drift.")
    parser.add_argument("--rebuild", action="store_true", help="Rebuild stale packs after reporting.")
    parser.add_argument("--reindex", action="store_true", help="After --rebuild, also reindex CB.")
    args = parser.parse_args()

    project_map, bootstrapped = load_project_map()
    if bootstrapped:
        print("No project_map.json found -- auto-detected one and saved it to:")
        print("  " + str(PROJECT_MAP_PATH))
        print("Review/edit it if the roots or modules look wrong, then rerun.\n")

    print("== Repo Scan: roots ==")
    for r in project_map.get("roots", []):
        print("  " + r["name"] + " -> " + r["path"] + " " + str(r.get("extensions", [])))

    real_files = inventory_real_files(project_map)
    covered_files, pack_module_counts = inventory_pack_files()

    orphans = sorted(set(real_files) - set(covered_files))

    print("\n== Section A: New / Orphaned Files ==")
    print("Real files scanned: " + str(len(real_files)) + " | already covered by a pack: " + str(len(covered_files)) + " | orphaned: " + str(len(orphans)))
    for orphan in orphans[:200]:
        guess = guess_pack_for_orphan(orphan, pack_module_counts)
        print("  - " + orphan + " -> " + guess)
    if len(orphans) > 200:
        print("  ... and " + str(len(orphans) - 200) + " more")

    write_orphan_report(orphans, pack_module_counts)
    print("Full orphan list + best-guess packs written to: " + str(ORPHAN_REPORT_PATH))

    packs = discover_packs(project_map)
    stale = []
    up_to_date = 0
    for pack_dir in packs:
        is_stale, reason = pack_is_stale(pack_dir)
        if is_stale:
            stale.append((pack_dir, reason))
        else:
            up_to_date += 1

    print("\n== Section B: Stale Packs ==")
    print("Packs checked: " + str(len(packs)) + " | up to date: " + str(up_to_date) + " | stale: " + str(len(stale)))
    for pack_dir, reason in stale:
        print("  - " + pack_dir.parent.name + "/" + pack_dir.name + ": " + reason)

    native_folders = find_native_graphify_folders(project_map)
    native_stale = []
    native_fresh = 0
    for native_dir, extensions in native_folders:
        is_stale, reason = native_graphify_is_stale(native_dir, extensions, project_map)
        if is_stale:
            native_stale.append((native_dir, reason))
        else:
            native_fresh += 1

    print("\n== Section C: Native Graphify Folders ==")
    print(
        "Native folders found: "
        + str(len(native_folders))
        + " | up to date: "
        + str(native_fresh)
        + " | stale: "
        + str(len(native_stale))
    )
    for native_dir, reason in native_stale:
        print("  - " + str(native_dir.relative_to(REPO_ROOT)) + ": " + reason)
    if native_stale:
        print("  (`graphify extract` -- the paid/LLM pass -- is never run automatically;")
        print("   `graphify update` -- free, AST-only -- WILL run automatically below with --rebuild)")

    errors = []

    if not args.rebuild:
        print("\n(no --rebuild flag: report only, nothing changed on disk)")
        print_summary(orphans, stale, native_stale, rebuilt=False, errors=errors)
        return 0

    print("\n== Rebuilding stale packs ==")
    packs_ok = 0
    for pack_dir, _ in stale:
        code = run_build(pack_dir)
        if code != 0:
            print("[FAILED] " + str(pack_dir.relative_to(REPO_ROOT)) + " exited with code " + str(code))
            errors.append({"stage": "pack build", "target": pack_dir.parent.name + "/" + pack_dir.name, "code": code})
        else:
            packs_ok += 1

    native_ok = 0
    if native_stale:
        print("\n== Updating stale native graphify-out folders (graphify update, safe/free) ==")
        for native_dir, _ in native_stale:
            code = run_native_update(native_dir)
            if code != 0:
                print("[WARNING] graphify update failed for " + str(native_dir.relative_to(REPO_ROOT)) + " (code " + str(code) + ") -- continuing")
                errors.append({"stage": "native update", "target": str(native_dir.relative_to(REPO_ROOT)), "code": code})
            else:
                native_ok += 1

    if args.reindex:
        setup_script = REPO_ROOT / "context_bridge" / "scripts" / "setup_context_bridge.py"
        print("-- reindexing via " + str(setup_script.relative_to(REPO_ROOT)) + " --")
        result = subprocess.run([sys.executable, str(setup_script)], cwd=str(REPO_ROOT))
        if result.returncode != 0:
            errors.append({"stage": "reindex", "target": "setup_context_bridge.py", "code": result.returncode})

    print_summary(orphans, stale, native_stale, rebuilt=True, errors=errors, packs_ok=packs_ok, native_ok=native_ok)
    return 1 if errors else 0


def print_summary(orphans, stale, native_stale, rebuilt, errors, packs_ok=0, native_ok=0):
    print("\n== Summary ==")

    if errors:
        print(str(len(errors)) + " error(s):")
        for i, e in enumerate(errors, 1):
            print("  " + str(i) + ". [" + e["stage"] + "] " + e["target"] + " -- exit code " + str(e["code"]))
    else:
        print("No errors.")

    print("Orphaned files (not in any pack): " + str(len(orphans)) + " -- see orphan_review.json, review manually")

    if rebuilt:
        print("Custom packs rebuilt: " + str(packs_ok) + "/" + str(len(stale)) + " succeeded")
        if native_stale:
            print("Native graphify-out folders updated: " + str(native_ok) + "/" + str(len(native_stale)) + " succeeded")
    else:
        print("Custom packs needing rebuild: " + str(len(stale)) + " -- rerun with option 2 to fix")
        print("Native graphify-out folders needing update: " + str(len(native_stale)) + " -- rerun with option 2 to fix")


if __name__ == "__main__":
    sys.exit(main())
